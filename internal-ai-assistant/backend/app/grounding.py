import re
from typing import List

from .citation_utils import (
    build_location_descriptor,
    citation_content_url,
    citation_view_url,
    html_escape,
    snippet_text,
)
from .routers.deps import LOW_CONFIDENCE_THRESHOLD, normalized_score

MIN_CONTEXT_SCORE = 0.18
HIGH_CONFIDENCE_THRESHOLD = 0.55
CHINESE_STOP_CHARS = set("的了和与及或为对中于以从按可有无这那此它其你我他她们吗呢啊吧")


def relevance_terms(text: str) -> set[str]:
    raw = (text or "").lower()
    terms = set(re.findall(r"[a-z0-9_]{2,}", raw))
    cjk_chars = [ch for ch in re.findall(r"[\u4e00-\u9fff]", raw) if ch not in CHINESE_STOP_CHARS]
    terms.update(cjk_chars)
    for size in (2, 3, 4):
        for i in range(max(0, len(cjk_chars) - size + 1)):
            terms.add("".join(cjk_chars[i : i + size]))
    return terms


def build_highlight_ranges(text: str, terms: list[str]) -> list[dict]:
    clean_text = text or ""
    if not clean_text or not terms:
        return []
    lower_text = clean_text.lower()
    ranges: list[dict] = []
    for term in sorted({t.strip() for t in terms if t and len(t.strip()) >= 2}, key=len, reverse=True):
        needle = term.lower()
        start = 0
        while True:
            idx = lower_text.find(needle, start)
            if idx < 0:
                break
            ranges.append({"start": idx, "end": idx + len(term), "text": clean_text[idx : idx + len(term)]})
            start = idx + len(term)
    ranges.sort(key=lambda item: (item["start"], item["end"]))
    deduped: list[dict] = []
    last_end = -1
    for item in ranges:
        if item["start"] < last_end:
            continue
        deduped.append(item)
        last_end = item["end"]
    return deduped


def highlight_text_html(text: str, ranges: list[dict]) -> str:
    if not text:
        return ""
    if not ranges:
        return html_escape(text)
    parts: list[str] = []
    cursor = 0
    for item in ranges:
        start = max(0, int(item.get("start", 0)))
        end = max(start, int(item.get("end", start)))
        if start > cursor:
            parts.append(html_escape(text[cursor:start]))
        parts.append(f'<mark data-range-start="{start}" data-range-end="{end}">{html_escape(text[start:end])}</mark>')
        cursor = end
    if cursor < len(text):
        parts.append(html_escape(text[cursor:]))
    return "".join(parts)


def citation_match_reason(context: dict, match_terms: list[str]) -> str:
    score = normalized_score(context.get("score"))
    if match_terms:
        return f"关键词命中: {'、'.join(match_terms[:5])}"
    if score is None:
        return "检索结果"
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return "高相关度命中"
    if score >= LOW_CONFIDENCE_THRESHOLD:
        return "中等相关度命中"
    return "低相关度命中"


def build_context_highlight(context: dict, match_terms: list[str]) -> tuple[str, list[dict]]:
    content = context.get("content") or ""
    ranges = build_highlight_ranges(content, match_terms)
    if not ranges and match_terms and content:
        first_term = match_terms[0]
        idx = content.lower().find(first_term.lower())
        if idx >= 0:
            ranges = [{"start": idx, "end": idx + len(first_term), "text": content[idx : idx + len(first_term)]}]
    return highlight_text_html(content, ranges), ranges


def filter_relevant_contexts(contexts: List[dict], question: str, min_score: float = MIN_CONTEXT_SCORE) -> List[dict]:
    if not contexts:
        return []
    question_terms = relevance_terms(question)
    question_cjk = "".join(re.findall(r"[\u4e00-\u9fff]", question or ""))
    filtered = []
    for context in contexts:
        score = context.get("score")
        haystack = " ".join([context.get("content") or "", context.get("document_title") or "", context.get("filename") or ""])
        content_terms = relevance_terms(haystack)
        overlap = question_terms.intersection(content_terms) if question_terms and content_terms else set()
        lexical_hit = bool(overlap) or bool(question_cjk and any(term in haystack for term in question_terms if len(term) >= 2))
        semantic_hit = isinstance(score, (int, float)) and score >= min_score
        if lexical_hit or semantic_hit:
            ordered_terms = sorted(list(overlap))[:12]
            context["match_terms"] = ordered_terms
            context["match_reason"] = citation_match_reason(context, ordered_terms)
            context["highlight_html"], context["highlight_ranges"] = build_context_highlight(context, ordered_terms)
            context["matched_snippet"] = snippet_text(context.get("content") or "")
            context["location"] = build_location_descriptor(context)
            filtered.append(context)
    return filtered


def build_citation(context: dict, index: int = 0) -> dict:
    document_id = context.get("document_id") or ""
    chunk_id = context.get("chunk_id") or ""
    filename = context.get("filename") or ""
    title = context.get("document_title") or filename or "未知文档"
    page_number = context.get("page_number")
    chunk_index = context.get("chunk_index")
    content = context.get("content") or ""
    citation = {
        "id": f"{document_id}:{chunk_id or chunk_index or index}",
        "document_id": document_id,
        "document_title": title,
        "title": title,
        "filename": filename or title,
        "file_name": filename or title,
        "page_number": page_number,
        "page": page_number,
        "chunk_id": chunk_id or None,
        "chunk_index": chunk_index,
        "source_type": context.get("source_type") or "document",
        "score": normalized_score(context.get("score")),
        "relevance_score": normalized_score(context.get("score")),
        "similarity": normalized_score(context.get("score")),
        "confidence": normalized_score(context.get("score")),
        "match_reason": context.get("match_reason") or citation_match_reason(context, context.get("match_terms") or []),
        "matched_snippet": context.get("matched_snippet") or snippet_text(content),
        "highlight_ranges": context.get("highlight_ranges") or build_highlight_ranges(content, context.get("match_terms") or []),
        "highlight_html": context.get("highlight_html") or highlight_text_html(content, context.get("highlight_ranges") or build_highlight_ranges(content, context.get("match_terms") or [])),
        "content": snippet_text(content),
        "snippet": snippet_text(content),
        "excerpt": snippet_text(content),
        "location": context.get("location") or build_location_descriptor(context),
        "anchor": context.get("anchor") or context.get("section_title") or "",
        "line_number": context.get("line_number"),
        "line": context.get("line_number"),
        "page_label": context.get("page_label") or (f"第{page_number}页" if page_number not in (None, "") else ""),
        "section_title": context.get("section_title") or "",
        "view_url": citation_view_url(document_id, chunk_id or None) if document_id else "",
        "url": citation_view_url(document_id, chunk_id or None) if document_id else "",
        "content_url": citation_content_url(document_id, chunk_id or None) if document_id else "",
        "summary_source": bool(context.get("summary_source")),
        "pageindex_source": bool(context.get("pageindex_source")),
        "index_source": "pageindex" if context.get("pageindex_source") else "chunk",
        "chunks_used": context.get("chunks_used"),
        "total_chunks": context.get("total_chunks"),
    }
    return citation


def serialize_sources(contexts: List[dict]) -> List[dict]:
    return [build_citation(c, i) for i, c in enumerate(contexts)]


def compute_grounding_confidence(contexts: List[dict]) -> float:
    scores = [normalized_score(c.get("score")) for c in contexts]
    scores = [s for s in scores if s is not None]
    if not contexts:
        return 0.0
    if scores:
        best = max(scores)
        lexical_boost = 0.12 if any(c.get("match_terms") for c in contexts) else 0.0
        return round(max(0.0, min(best + lexical_boost, 1.0)), 4)
    return 0.45 if any(c.get("match_terms") for c in contexts) else 0.0


def grounding_reason_for_contexts(contexts: List[dict], confidence: float) -> str:
    if not contexts:
        return "未在知识库中找到依据"
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        return "知识库命中依据置信度较低"
    return "回答基于知识库命中片段生成"
