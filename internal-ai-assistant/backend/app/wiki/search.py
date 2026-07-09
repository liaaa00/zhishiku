from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import User, WikiPage, WikiPageSource

MIN_WIKI_SCORE = 0.18
STRONG_WIKI_SCORE = 0.34


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _terms(text: str) -> set[str]:
    compact = _compact(text)
    terms = set(re.findall(r"[a-z0-9_]{2,}", compact))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", compact))
    for size in (2, 3, 4, 5, 6):
        for index in range(max(0, len(cjk) - size + 1)):
            terms.add(cjk[index : index + size])
    return {term for term in terms if len(term) >= 2}


def _page_text(page: WikiPage) -> str:
    return " ".join([page.title or "", page.summary or "", page.content_md or ""])


def _score_page(question: str, page: WikiPage) -> tuple[float, list[str]]:
    query_terms = _terms(question)
    if not query_terms:
        return 0.0, []
    title_text = _compact(page.title or "")
    full_text = _compact(_page_text(page))
    hits = [term for term in query_terms if term and term in full_text]
    title_hits = [term for term in query_terms if term and term in title_text]
    if not hits and not title_hits:
        return 0.0, []
    coverage = len(set(hits)) / max(1, len(query_terms))
    title_boost = min(0.24, len(set(title_hits)) * 0.08)
    summary_text = _compact(page.summary or "")
    summary_hits = [term for term in query_terms if term and term in summary_text]
    summary_boost = min(0.16, len(set(summary_hits)) * 0.04)
    score = min(0.99, coverage * 0.72 + title_boost + summary_boost + 0.08)
    return round(score, 4), sorted(set(hits + title_hits), key=len, reverse=True)[:12]


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
        return [] if not getattr(user, "is_admin", False) else []
    return [source for source in sources if _source_allowed(db, source, user, knowledge_scope)]


def _context_for_page(page: WikiPage, score: float, hits: list[str], sources: list[WikiPageSource]) -> dict[str, Any]:
    primary_source = sources[0] if sources else None
    doc = primary_source.document if primary_source else None
    return {
        "document_id": doc.id if doc else "",
        "document_title": doc.title if doc else page.title,
        "filename": doc.filename if doc else f"{page.slug}.md",
        "chunk_id": primary_source.chunk_id if primary_source else "",
        "page_number": primary_source.page_number if primary_source else None,
        "chunk_index": f"wiki:{page.slug}",
        "source_type": "wiki",
        "content": page.content_md,
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
        "source_quotes": [source.quote for source in sources[:6] if source.quote],
    }


def retrieve_wiki_contexts(db: Session, question: str, user: User, top_k: int = 5, knowledge_scope: str = "production") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pages = db.execute(
        select(WikiPage)
        .where(WikiPage.status == "published")
        .where(WikiPage.knowledge_scope == knowledge_scope)
        .order_by(WikiPage.updated_at.desc())
        .limit(500)
    ).scalars().all()
    scored: list[tuple[float, WikiPage, list[str], list[WikiPageSource]]] = []
    for page in pages:
        score, hits = _score_page(question, page)
        if score < MIN_WIKI_SCORE:
            continue
        sources = _visible_sources(db, page, user, knowledge_scope)
        if page.sources and not sources:
            continue
        scored.append((score, page, hits, sources))
    scored.sort(key=lambda item: (-item[0], item[1].title or ""))
    selected = scored[: max(1, top_k)]
    contexts = [_context_for_page(page, score, hits, sources) for score, page, hits, sources in selected]
    best_score = selected[0][0] if selected else 0.0
    strong_hits = [item for item in selected if item[0] >= STRONG_WIKI_SCORE]
    used = bool(strong_hits)
    return contexts, {
        "enabled": True,
        "used": used,
        "candidate_count": len(scored),
        "context_count": len(contexts),
        "best_score": best_score,
        "threshold": STRONG_WIKI_SCORE,
        "reason": "wiki_hit" if used else ("wiki_weak_hit" if contexts else "wiki_no_hit"),
    }
