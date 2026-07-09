from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, WikiPage, WikiPageSource
from .context_budget import DEFAULT_WIKI_CONTEXT_BUDGET_TOKENS, apply_context_budget

MIN_WIKI_SCORE = 0.2
STRONG_WIKI_SCORE = 0.42
MAX_SCAN_PAGES = 500
MAX_CONTEXT_CHARS = 3600
MAX_SNIPPETS = 5

CJK_STOP_TERMS = {
    "什么",
    "怎么",
    "如何",
    "是否",
    "可以",
    "需要",
    "有关",
    "相关",
    "一下",
    "这个",
    "那个",
    "哪些",
    "多少",
    "有没有",
}
EN_STOP_TERMS = {
    "what",
    "how",
    "why",
    "when",
    "where",
    "which",
    "the",
    "and",
    "for",
    "with",
    "from",
    "about",
    "please",
}


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _truncate(text: str, max_chars: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _terms(text: str) -> set[str]:
    compact = _compact(text)
    terms = set(re.findall(r"[a-z0-9_]{2,}", compact))
    terms = {term for term in terms if term not in EN_STOP_TERMS}
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", compact))
    for size in (2, 3, 4, 5, 6):
        for index in range(max(0, len(cjk) - size + 1)):
            term = cjk[index : index + size]
            if term not in CJK_STOP_TERMS:
                terms.add(term)
    return {term for term in terms if len(term) >= 2}


def _question_phrases(question: str) -> set[str]:
    compact = _compact(question)
    phrases: set[str] = set()
    cleaned = re.sub(r"(是什么|有哪些|怎么做|如何|什么|吗|呢|？|\?)", "", compact)
    if len(cleaned) >= 4:
        phrases.add(cleaned[:32])
    for match in re.findall(r"[\u4e00-\u9fff]{4,12}", compact):
        if match not in CJK_STOP_TERMS:
            phrases.add(match)
    return phrases


def _page_text(page: WikiPage) -> str:
    return " ".join([page.title or "", page.summary or "", page.content_md or ""])


def _score_page(question: str, page: WikiPage) -> tuple[float, list[str]]:
    query_terms = _terms(question)
    if not query_terms:
        return 0.0, []
    title_text = _compact(page.title or "")
    summary_text = _compact(page.summary or "")
    full_text = _compact(_page_text(page))
    hits = [term for term in query_terms if term and term in full_text]
    title_hits = [term for term in query_terms if term and term in title_text]
    summary_hits = [term for term in query_terms if term and term in summary_text]
    if not hits and not title_hits:
        return 0.0, []

    unique_hits = set(hits)
    coverage = len(unique_hits) / max(1, len(query_terms))
    if coverage < 0.16 and not title_hits:
        return 0.0, []

    phrase_hits = [phrase for phrase in _question_phrases(question) if len(phrase) >= 4 and phrase in full_text]
    title_boost = min(0.2, len(set(title_hits)) * 0.065)
    summary_boost = min(0.16, len(set(summary_hits)) * 0.04)
    phrase_boost = min(0.14, len(set(phrase_hits)) * 0.07)
    confidence_boost = min(0.06, max(0.0, float(page.confidence or 0.0)) * 0.06)
    length_penalty = min(0.08, math.log10(max(1000, len(full_text))) * 0.01)
    score = coverage * 0.68 + title_boost + summary_boost + phrase_boost + confidence_boost + 0.04 - length_penalty
    return round(max(0.0, min(0.99, score)), 4), sorted(set(hits + title_hits + summary_hits + phrase_hits), key=len, reverse=True)[:14]


def _source_allowed(db: Session, source: WikiPageSource, user: User, knowledge_scope: str) -> bool:
    if getattr(user, "is_admin", False):
        return True
    try:
        from ..retrieval import has_document_access, user_group_ids

        doc = source.document
        if not doc:
            return False
        return has_document_access(db, doc, user, user_group_ids(user), knowledge_scope=knowledge_scope)
    except Exception:
        return False


def _visible_sources(db: Session, page: WikiPage, user: User, knowledge_scope: str) -> list[WikiPageSource]:
    sources = sorted(list(page.sources or []), key=lambda item: item.source_order or 0)
    if not sources:
        return []
    return [source for source in sources if _source_allowed(db, source, user, knowledge_scope)]


def _split_blocks(markdown: str) -> list[str]:
    raw_blocks = re.split(r"\n\s*\n", markdown or "")
    blocks: list[str] = []
    current_heading = ""
    for raw in raw_blocks:
        block = raw.strip()
        if not block:
            continue
        if block.startswith("---"):
            continue
        if block.startswith("#"):
            current_heading = block.split("\n", 1)[0].strip()
            blocks.append(_truncate(block, 900))
            continue
        if current_heading and not block.startswith("#"):
            blocks.append(_truncate(f"{current_heading}\n{block}", 1100))
        else:
            blocks.append(_truncate(block, 1100))
    return blocks


def _block_score(block: str, hits: list[str]) -> float:
    compact = _compact(block)
    score = 0.0
    for term in hits:
        if not term:
            continue
        count = compact.count(_compact(term))
        if count:
            score += min(3, count) * (1.0 + min(len(term), 8) / 10)
    if "[s" in compact or "来源" in block:
        score += 0.5
    if block.lstrip().startswith("#"):
        score += 0.25
    return score


def _best_snippets(page: WikiPage, hits: list[str], max_blocks: int = MAX_SNIPPETS) -> list[str]:
    blocks = _split_blocks(page.content_md or "")
    if not blocks:
        return []
    if not hits:
        return [_truncate(blocks[0], 900)]
    scored = [(_block_score(block, hits), index, block) for index, block in enumerate(blocks)]
    selected = [(score, index, block) for score, index, block in scored if score > 0]
    if not selected:
        return [_truncate(blocks[0], 900)]
    selected.sort(key=lambda item: (-item[0], item[1]))
    ordered = sorted(selected[:max_blocks], key=lambda item: item[1])
    return [block for _, _, block in ordered]


def _context_content(page: WikiPage, hits: list[str], sources: list[WikiPageSource]) -> str:
    parts: list[str] = [f"# {page.title}"]
    if page.summary:
        parts.extend(["", "## Wiki 摘要", _truncate(page.summary, 1200)])
    snippets = _best_snippets(page, hits)
    if snippets:
        parts.extend(["", "## 命中片段"])
        parts.extend(snippets)
    source_quotes = [source.quote for source in sources[:4] if source.quote]
    if source_quotes:
        parts.extend(["", "## 可核验来源摘录"])
        parts.extend(f"- [S{index + 1}] {_truncate(quote, 360)}" for index, quote in enumerate(source_quotes))
    return _truncate("\n\n".join(parts), MAX_CONTEXT_CHARS)


def _context_for_page(page: WikiPage, score: float, hits: list[str], sources: list[WikiPageSource]) -> dict[str, Any]:
    primary_source = sources[0] if sources else None
    doc = primary_source.document if primary_source else None
    content = _context_content(page, hits, sources)
    return {
        "document_id": doc.id if doc else "",
        "document_title": doc.title if doc else page.title,
        "filename": doc.filename if doc else f"{page.slug}.md",
        "chunk_id": primary_source.chunk_id if primary_source else "",
        "page_number": primary_source.page_number if primary_source else None,
        "chunk_index": f"wiki:{page.slug}",
        "source_type": "wiki",
        "content": content,
        "score": score,
        "match_terms": hits,
        "match_reason": "compiled_wiki_page",
        "retrieval_channel": "wiki",
        "wiki_page_id": page.id,
        "wiki_slug": page.slug,
        "wiki_title": page.title,
        "wiki_page_type": page.page_type,
        "wiki_confidence": page.confidence,
        "wiki_source_count": len(sources),
        "wiki_context_char_count": len(content),
        "wiki_context_pack": "matched_snippets_v3_budgeted",
        "source_quotes": [source.quote for source in sources[:6] if source.quote],
    }


def retrieve_wiki_contexts(db: Session, question: str, user: User, top_k: int = 5, knowledge_scope: str = "production") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pages = db.execute(
        select(WikiPage)
        .where(WikiPage.status == "published")
        .where(WikiPage.knowledge_scope == knowledge_scope)
        .order_by(WikiPage.updated_at.desc())
        .limit(MAX_SCAN_PAGES)
    ).scalars().all()
    scored: list[tuple[float, WikiPage, list[str], list[WikiPageSource]]] = []
    skipped_for_access = 0
    for page in pages:
        score, hits = _score_page(question, page)
        if score < MIN_WIKI_SCORE:
            continue
        sources = _visible_sources(db, page, user, knowledge_scope)
        if page.sources and not sources:
            skipped_for_access += 1
            continue
        if not page.sources and not getattr(user, "is_admin", False):
            skipped_for_access += 1
            continue
        scored.append((score, page, hits, sources))
    scored.sort(key=lambda item: (-item[0], item[1].title or ""))
    selected = scored[: max(1, top_k)]
    raw_contexts = [_context_for_page(page, score, hits, sources) for score, page, hits, sources in selected]
    contexts, budget_meta = apply_context_budget(raw_contexts, requested_tokens=DEFAULT_WIKI_CONTEXT_BUDGET_TOKENS)
    best_score = selected[0][0] if selected else 0.0
    strong_hits = [item for item in selected if item[0] >= STRONG_WIKI_SCORE]
    used = bool(strong_hits)
    return contexts, {
        "enabled": True,
        "used": used,
        "candidate_count": len(scored),
        "context_count": len(contexts),
        "raw_context_count": len(raw_contexts),
        "best_score": best_score,
        "threshold": STRONG_WIKI_SCORE,
        "strong_count": len(strong_hits),
        "skipped_for_access": skipped_for_access,
        "context_pack": "matched_snippets_v3_budgeted",
        "budget": budget_meta,
        "reason": "wiki_hit" if used else ("wiki_weak_hit" if contexts else "wiki_no_hit"),
    }
