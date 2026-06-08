import json
import re
from typing import List, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_client import embed_texts
from .grounding import filter_relevant_contexts, relevance_terms
from .models import Document, DocumentChunk, DocumentPageIndex, User, document_group_link
from .pageindex_adapter import load_pageindex_payload
from .vector_store import QdrantUnavailable, search_chunks

SQLITE_SCAN_LIMIT = 3000
ADAPTIVE_CANDIDATE_MAX = 120
ADAPTIVE_CONTEXT_MAX = 40
ADAPTIVE_FINAL_CONTEXT_MAX = 12
ADAPTIVE_FINAL_CONTEXT_MIN = 6
ADAPTIVE_NEIGHBOR_MAX = 18
PAGEINDEX_SUPPLEMENT_MAX = 12
PAGEINDEX_DOC_SCAN_MAX = 50
PAGEINDEX_PAGE_CHAR_LIMIT = 1800

BROAD_QUERY_PATTERNS = (
    "总结",
    "归纳",
    "梳理",
    "整理",
    "概括",
    "流程",
    "步骤",
    "制度",
    "规则",
    "规范",
    "清单",
    "表格",
    "所有",
    "全部",
    "完整",
    "详细",
    "哪些",
    "有哪些",
    "怎么",
    "如何",
)
DEEP_QUERY_PATTERNS = (
    "风险",
    "问题",
    "隐患",
    "影响",
    "原因",
    "对比",
    "差异",
    "优缺点",
    "方案",
    "建议",
    "策略",
    "分析",
    "排查",
    "复盘",
    "跨文档",
    "多个文档",
)
PRECISE_QUERY_PATTERNS = (
    "多少",
    "几天",
    "日期",
    "时间",
    "电话",
    "邮箱",
    "编号",
    "金额",
    "比例",
    "谁",
    "是什么",
)


def parse_embedding(value: str) -> List[float]:
    return json.loads(value)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-8)


def user_group_ids(user: User) -> list[str]:
    return [g.id for g in user.groups]


def has_document_access(db: Session, doc: Document, user: User, group_ids: list[str] | None = None) -> bool:
    source_type = str(doc.source_type or "")
    if source_type.startswith("chat_"):
        return doc.created_by == user.id or bool(user.is_admin)
    if user.is_admin:
        return True
    resolved_group_ids = group_ids if group_ids is not None else user_group_ids(user)
    if not resolved_group_ids:
        return False
    return bool(
        db.execute(
            select(document_group_link.c.group_id).where(
                document_group_link.c.document_id == doc.id,
                document_group_link.c.group_id.in_(resolved_group_ids),
            )
        ).first()
    )


def accessible_document_ids(db: Session, user: User, group_ids: list[str]) -> set[str]:
    # Personal attachment access is granted only to the owner.
    personal_rows = db.execute(select(Document.id).where(Document.source_type.like("chat_%"), Document.created_by == user.id)).all()
    ids = {row[0] for row in personal_rows}

    if user.is_admin:
        managed_rows = db.execute(select(Document.id).where(~Document.source_type.like("chat_%"))).all()
        ids.update(row[0] for row in managed_rows)
        return ids

    if group_ids:
        managed_rows = db.execute(
            select(Document.id)
            .join(document_group_link, document_group_link.c.document_id == Document.id)
            .where(~Document.source_type.like("chat_%"), document_group_link.c.group_id.in_(group_ids))
            .distinct()
        ).all()
        ids.update(row[0] for row in managed_rows)
    return ids


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _context_key(context: dict) -> tuple[str, str]:
    return (
        str(context.get("document_id") or ""),
        str(context.get("chunk_id") or context.get("chunk_index") or ""),
    )


def _chunk_context(doc: Document, chunk: DocumentChunk, score: float = 0.35, match_reason: str = "检索补充片段") -> dict:
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": chunk.id,
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "source_type": str(doc.source_type or ""),
        "content": chunk.content,
        "score": score,
        "match_terms": [],
        "match_reason": match_reason,
    }


def sqlite_search_chunks(db: Session, query_vector: List[float], user: User, group_ids: list[str], limit: int) -> List[dict]:
    doc_ids = accessible_document_ids(db, user, group_ids)
    if not doc_ids:
        return []

    rows = db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.document_id.in_(doc_ids))
        .order_by(Document.created_at.desc(), DocumentChunk.chunk_index.asc())
        .limit(SQLITE_SCAN_LIMIT)
    ).all()

    scored: list[dict] = []
    for chunk, doc in rows:
        scored.append(
            {
                "document_id": doc.id,
                "document_title": doc.title,
                "filename": doc.filename,
                "chunk_id": chunk.id,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "source_type": str(doc.source_type or ""),
                "content": chunk.content,
                "score": cosine_similarity(query_vector, parse_embedding(chunk.embedding_json)),
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def retrieval_plan_for_question(question: str, top_k: int = 5) -> dict:
    text = (question or "").strip()
    compact = re.sub(r"\s+", "", text.lower())
    hint = max(1, min(_safe_int(top_k, 5), ADAPTIVE_CONTEXT_MAX))
    cjk_len = len(re.findall(r"[\u4e00-\u9fff]", compact))
    ascii_terms = re.findall(r"[a-z0-9_]{2,}", compact)
    length_score = len(compact) + len(ascii_terms) * 3
    broad_hits = [item for item in BROAD_QUERY_PATTERNS if item in compact]
    deep_hits = [item for item in DEEP_QUERY_PATTERNS if item in compact]
    precise_hits = [item for item in PRECISE_QUERY_PATTERNS if item in compact]

    if deep_hits or length_score >= 90 or len(broad_hits) >= 2:
        intent = "deep_analysis"
        target_contexts = 24
        min_contexts = 12
        candidate_limit = 96
        adjacent_window = 1
        neighbor_budget = 16
        min_score = 0.12
    elif broad_hits or cjk_len >= 35 or length_score >= 58:
        intent = "broad_business"
        target_contexts = 16
        min_contexts = 8
        candidate_limit = 72
        adjacent_window = 1
        neighbor_budget = 12
        min_score = 0.14
    elif precise_hits and length_score <= 46:
        intent = "precise_lookup"
        target_contexts = 6
        min_contexts = 3
        candidate_limit = 30
        adjacent_window = 1
        neighbor_budget = 6
        min_score = 0.18
    else:
        intent = "balanced"
        target_contexts = 10
        min_contexts = 5
        candidate_limit = 48
        adjacent_window = 1
        neighbor_budget = 8
        min_score = 0.16

    target_contexts = max(target_contexts, hint)
    target_contexts = min(target_contexts, ADAPTIVE_CONTEXT_MAX)
    min_contexts = min(max(min_contexts, min(hint, target_contexts)), target_contexts)
    candidate_limit = min(max(candidate_limit, target_contexts * 3), ADAPTIVE_CANDIDATE_MAX)
    neighbor_budget = min(neighbor_budget, ADAPTIVE_NEIGHBOR_MAX)
    return {
        "mode": "adaptive",
        "intent": intent,
        "top_k_hint": hint,
        "target_contexts": target_contexts,
        "min_contexts": min_contexts,
        "candidate_limit": candidate_limit,
        "adjacent_window": adjacent_window,
        "neighbor_budget": neighbor_budget,
        "min_score": min_score,
        "broad_hits": broad_hits[:6],
        "deep_hits": deep_hits[:6],
        "precise_hits": precise_hits[:6],
    }


def retrieve_candidate_contexts(db: Session, question: str, user: User, top_k: int = 5, candidate_limit: int | None = None) -> Tuple[List[dict], str, str, int]:
    if candidate_limit is None:
        limit = max(1, min(int(top_k or 5), 10))
        candidate_limit = max(limit * 3, limit)
    else:
        candidate_limit = max(1, min(int(candidate_limit or top_k or 5), ADAPTIVE_CANDIDATE_MAX))
    query_vector = embed_texts([question])[0]
    group_ids = user_group_ids(user)
    retrieval_backend = "sqlite"
    retrieval_note = ""
    try:
        candidate_contexts = search_chunks(query_vector, user.id, bool(user.is_admin), group_ids, candidate_limit)
        retrieval_backend = "qdrant"
        if not candidate_contexts:
            raise QdrantUnavailable("Qdrant returned no matches; falling back to SQLite")
    except QdrantUnavailable as exc:
        retrieval_note = str(exc)
        candidate_contexts = sqlite_search_chunks(db, query_vector, user, group_ids, candidate_limit)
    return candidate_contexts, retrieval_backend, retrieval_note, len(candidate_contexts)


def _merge_unique_contexts(primary: list[dict], supplement: list[dict], limit: int) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for context in [*primary, *supplement]:
        key = _context_key(context)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        merged.append(context)
        if len(merged) >= limit:
            break
    return merged


def _rerank_context_score(question_terms: set[str], context: dict, original_rank: int) -> float:
    text = " ".join(
        str(item or "")
        for item in [
            context.get("document_title"),
            context.get("filename"),
            context.get("section_title"),
            context.get("anchor"),
            context.get("match_reason"),
            context.get("content"),
        ]
    )
    terms = relevance_terms(text)
    overlap = question_terms.intersection(terms)
    title_terms = relevance_terms(" ".join(str(context.get(item) or "") for item in ["document_title", "filename", "section_title", "anchor"]))
    title_overlap = question_terms.intersection(title_terms)
    coverage = len(overlap) / max(len(question_terms), 1)
    title_boost = min(0.24, len(title_overlap) * 0.08)
    pageindex_boost = 0.18 if context.get("pageindex_source") else 0.0
    source_score = min(_safe_float(context.get("score"), 0.0), 1.0) * 0.45
    lexical_score = min(0.45, coverage * 0.45)
    rank_penalty = min(0.08, original_rank * 0.004)
    return source_score + lexical_score + title_boost + pageindex_boost - rank_penalty


def rerank_contexts(question: str, contexts: list[dict], limit: int) -> tuple[list[dict], int]:
    if not contexts:
        return [], 0
    limit = max(1, min(int(limit or ADAPTIVE_FINAL_CONTEXT_MAX), ADAPTIVE_CONTEXT_MAX))
    question_terms = relevance_terms(question)
    scored: list[tuple[float, int, dict]] = []
    for idx, context in enumerate(contexts):
        score = _rerank_context_score(question_terms, context, idx) if question_terms else _safe_float(context.get("score"), 0.0)
        scored.append((score, idx, context))
    scored.sort(key=lambda item: (bool(item[2].get("pageindex_source")), item[0]), reverse=True)

    selected: list[dict] = []
    per_doc_count: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    pageindex_selected = 0
    # First pass: keep diversity and prefer at most a few contexts from the same document.
    for score, _idx, context in scored:
        key = _context_key(context)
        doc_id = key[0]
        if not doc_id or key in seen:
            continue
        if per_doc_count.get(doc_id, 0) >= 3 and len(selected) >= ADAPTIVE_FINAL_CONTEXT_MIN:
            continue
        context = dict(context)
        context["rerank_score"] = round(score, 4)
        selected.append(context)
        seen.add(key)
        per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1
        if context.get("pageindex_source"):
            pageindex_selected += 1
        if len(selected) >= limit:
            break

    # Second pass: if diversity filtering made the result too small, fill with next best items.
    if len(selected) < min(ADAPTIVE_FINAL_CONTEXT_MIN, limit):
        for score, _idx, context in scored:
            key = _context_key(context)
            if not key[0] or key in seen:
                continue
            context = dict(context)
            context["rerank_score"] = round(score, 4)
            selected.append(context)
            seen.add(key)
            if context.get("pageindex_source"):
                pageindex_selected += 1
            if len(selected) >= min(ADAPTIVE_FINAL_CONTEXT_MIN, limit):
                break
    return selected[:limit], pageindex_selected


def expand_contexts_with_adjacent_chunks(
    db: Session,
    contexts: list[dict],
    user: User,
    group_ids: list[str],
    window: int = 1,
    max_added: int = 8,
) -> tuple[list[dict], int]:
    if not contexts or window <= 0 or max_added <= 0:
        return contexts, 0

    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    added = 0
    for context in contexts:
        key = _context_key(context)
        if key not in seen:
            result.append(context)
            seen.add(key)
        if added >= max_added:
            continue
        document_id = str(context.get("document_id") or "")
        chunk_index = _safe_int(context.get("chunk_index"), -1)
        if not document_id or chunk_index < 0:
            continue
        indices = [idx for idx in range(chunk_index - window, chunk_index + window + 1) if idx >= 0 and idx != chunk_index]
        if not indices:
            continue
        rows = db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.document_id == document_id, DocumentChunk.chunk_index.in_(indices))
            .order_by(DocumentChunk.chunk_index.asc())
        ).all()
        base_score = _safe_float(context.get("score"), 0.35)
        for chunk, doc in rows:
            if added >= max_added:
                break
            if not has_document_access(db, doc, user, group_ids):
                continue
            neighbor_key = (doc.id, chunk.id)
            if neighbor_key in seen:
                continue
            distance = abs(_safe_int(chunk.chunk_index) - chunk_index)
            neighbor_score = max(min(base_score - 0.03 * distance, base_score), 0.1)
            result.append(_chunk_context(doc, chunk, score=neighbor_score, match_reason="相邻片段补全文档上下文"))
            seen.add(neighbor_key)
            added += 1
    return result, added


def _flatten_pageindex_nodes(nodes: list[dict], parent_title: str = "") -> list[dict]:
    flattened: list[dict] = []
    for node in nodes or []:
        title = str(node.get("title") or "").strip()
        section_title = " / ".join(part for part in [parent_title, title] if part)
        item = dict(node)
        item["section_title"] = section_title or title
        flattened.append(item)
        children = node.get("nodes") or []
        if isinstance(children, list) and children:
            flattened.extend(_flatten_pageindex_nodes(children, section_title))
    return flattened


def _pageindex_node_score(question_terms: set[str], node: dict, doc: Document, payload: dict) -> tuple[float, list[str]]:
    haystack = " ".join(
        str(item or "")
        for item in [
            doc.title,
            doc.filename,
            payload.get("doc_description"),
            node.get("section_title") or node.get("title"),
            node.get("summary") or node.get("prefix_summary"),
            node.get("text"),
        ]
    )
    node_terms = relevance_terms(haystack)
    overlap = sorted(question_terms.intersection(node_terms), key=len, reverse=True)
    if not overlap:
        return 0.0, []
    long_hits = sum(1 for term in overlap if len(term) >= 2)
    title = str(node.get("section_title") or node.get("title") or "")
    title_terms = relevance_terms(title)
    title_overlap = question_terms.intersection(title_terms)
    score = 0.24 + min(0.5, long_hits * 0.08) + min(0.18, len(title_overlap) * 0.06)
    return min(score, 0.92), overlap[:12]


def _pageindex_node_content(payload: dict, node: dict) -> tuple[str, int | None, str]:
    start = _safe_int(node.get("start_index") or node.get("line_num") or node.get("page"), 0)
    end = _safe_int(node.get("end_index") or node.get("start_index") or node.get("line_num") or node.get("page"), start)
    if end < start:
        end = start
    title = str(node.get("section_title") or node.get("title") or "").strip()
    location = f"页/行 {start}-{end}" if start and end and start != end else (f"页/行 {start}" if start else "结构节点")

    content_parts: list[str] = []
    pages = payload.get("pages") or []
    if isinstance(pages, list) and pages:
        for page in pages:
            page_no = _safe_int(page.get("page"), 0) if isinstance(page, dict) else 0
            if start and page_no and not (start <= page_no <= end):
                continue
            text = str(page.get("content") or "") if isinstance(page, dict) else ""
            if text.strip():
                content_parts.append(f"[第 {page_no} 页]\n{text.strip()}")
            if sum(len(part) for part in content_parts) >= PAGEINDEX_PAGE_CHAR_LIMIT:
                break
    if not content_parts:
        fallback = str(node.get("text") or node.get("summary") or node.get("prefix_summary") or payload.get("doc_description") or "")
        if fallback.strip():
            content_parts.append(fallback.strip())
    content = "\n\n".join(content_parts)
    if len(content) > PAGEINDEX_PAGE_CHAR_LIMIT:
        content = content[:PAGEINDEX_PAGE_CHAR_LIMIT].rstrip() + "..."
    if title:
        content = f"[高级结构索引] {title}（{location}）\n{content}"
    return content.strip(), (start or None), location


def _pageindex_context(doc: Document, node: dict, payload: dict, score: float, match_terms: list[str]) -> dict | None:
    content, page_number, location = _pageindex_node_content(payload, node)
    if not content:
        return None
    node_id = str(node.get("node_id") or node.get("section_title") or node.get("title") or page_number or "node")
    title = str(node.get("section_title") or node.get("title") or "")
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": "",
        "page_number": page_number,
        "chunk_index": f"pageindex:{node_id}",
        "source_type": str(doc.source_type or ""),
        "content": content,
        "score": score,
        "match_terms": match_terms,
        "match_reason": "高级结构索引命中章节/页面",
        "section_title": title,
        "anchor": title,
        "location": f"pageindex | {location}" + (f" | {title}" if title else ""),
        "pageindex_source": True,
    }


def retrieve_pageindex_contexts(
    db: Session,
    question: str,
    user: User,
    group_ids: list[str],
    base_contexts: list[dict] | None = None,
    max_contexts: int = PAGEINDEX_SUPPLEMENT_MAX,
) -> list[dict]:
    question_terms = relevance_terms(question)
    if not question_terms or max_contexts <= 0:
        return []
    accessible_ids = accessible_document_ids(db, user, group_ids)
    if not accessible_ids:
        return []

    preferred_ids: list[str] = []
    for context in base_contexts or []:
        doc_id = str(context.get("document_id") or "")
        if doc_id and doc_id in accessible_ids and doc_id not in preferred_ids:
            preferred_ids.append(doc_id)

    rows = db.execute(
        select(DocumentPageIndex, Document)
        .join(Document, Document.id == DocumentPageIndex.document_id)
        .where(DocumentPageIndex.status == "ready", DocumentPageIndex.document_id.in_(accessible_ids))
        .order_by(Document.created_at.desc())
        .limit(PAGEINDEX_DOC_SCAN_MAX)
    ).all()
    row_by_doc = {doc.id: (row, doc) for row, doc in rows}
    ordered_pairs: list[tuple[DocumentPageIndex, Document]] = []
    for doc_id in preferred_ids:
        pair = row_by_doc.pop(doc_id, None)
        if pair:
            ordered_pairs.append(pair)
    ordered_pairs.extend(row_by_doc.values())

    scored_contexts: list[dict] = []
    for row, doc in ordered_pairs:
        _, payload = load_pageindex_payload(db, doc.id)
        if not payload:
            continue
        nodes = _flatten_pageindex_nodes(payload.get("structure") or [])
        scored_nodes: list[tuple[float, list[str], dict]] = []
        for node in nodes:
            score, terms = _pageindex_node_score(question_terms, node, doc, payload)
            if score > 0:
                scored_nodes.append((score, terms, node))
        scored_nodes.sort(key=lambda item: item[0], reverse=True)
        if not scored_nodes and doc.id in preferred_ids:
            # If vector retrieval already selected this document, add the first structural node
            # as a lightweight context even when lexical overlap is weak.
            for node in nodes[:1]:
                scored_nodes.append((0.26, [], node))
        for score, terms, node in scored_nodes[:2]:
            context = _pageindex_context(doc, node, payload, score, terms)
            if context:
                scored_contexts.append(context)
    scored_contexts.sort(key=lambda item: _safe_float(item.get("score")), reverse=True)
    return scored_contexts[:max_contexts]


def adaptive_retrieve_contexts(db: Session, question: str, user: User, top_k: int = 5) -> Tuple[List[dict], str, str, int, dict]:
    plan = retrieval_plan_for_question(question, top_k)
    candidate_contexts, retrieval_backend, retrieval_note, candidate_count = retrieve_candidate_contexts(
        db,
        question,
        user,
        top_k=top_k,
        candidate_limit=int(plan["candidate_limit"]),
    )
    filtered = filter_relevant_contexts(candidate_contexts, question, min_score=float(plan["min_score"]))
    filtered.sort(key=lambda item: _safe_float(item.get("score")), reverse=True)

    target_contexts = int(plan["target_contexts"])
    min_contexts = int(plan["min_contexts"])
    best_score = max((_safe_float(item.get("score"), 0.0) for item in filtered), default=max((_safe_float(item.get("score"), 0.0) for item in candidate_contexts), default=0.0))
    final_contexts = filtered[:target_contexts]
    if len(final_contexts) < min_contexts and filtered and best_score >= max(0.18, float(plan["min_score"])):
        # 低命中时不要直接放弃：用候选池中分数最高的片段补足最小上下文，随后仍会由置信度逻辑提示风险。
        final_contexts = _merge_unique_contexts(final_contexts, candidate_contexts, min_contexts)

    group_ids = user_group_ids(user)
    expand_allowed = bool(final_contexts) and best_score >= max(0.22, float(plan["min_score"]))
    expanded_contexts, adjacent_added = expand_contexts_with_adjacent_chunks(
        db,
        final_contexts if expand_allowed else [],
        user,
        group_ids,
        window=int(plan["adjacent_window"]),
        max_added=int(plan["neighbor_budget"]),
    ) if expand_allowed else (final_contexts, 0)
    pageindex_contexts = retrieve_pageindex_contexts(
        db,
        question,
        user,
        group_ids,
        base_contexts=expanded_contexts or final_contexts or candidate_contexts,
        max_contexts=PAGEINDEX_SUPPLEMENT_MAX,
    )
    pageindex_added = len(pageindex_contexts)
    if pageindex_contexts:
        # PageIndex carries the document structure/tree and should be the primary context.
        # Vector/SQLite chunks are kept only as supplemental evidence after structural hits.
        expanded_contexts = _merge_unique_contexts(pageindex_contexts, expanded_contexts, ADAPTIVE_CONTEXT_MAX)
    expanded_contexts = expanded_contexts[:ADAPTIVE_CONTEXT_MAX]
    pre_rerank_count = len(expanded_contexts)
    final_limit = min(ADAPTIVE_FINAL_CONTEXT_MAX, max(ADAPTIVE_FINAL_CONTEXT_MIN, int(plan["target_contexts"])))
    expanded_contexts, pageindex_selected = rerank_contexts(question, expanded_contexts, final_limit)

    best_score = max((_safe_float(item.get("score"), 0.0) for item in [*candidate_contexts, *pageindex_contexts]), default=0.0)
    unique_docs = {str(item.get("document_id") or "") for item in expanded_contexts if item.get("document_id")}
    meta = {
        **plan,
        "candidate_count": candidate_count,
        "filtered_count": len(filtered),
        "final_context_count": len(expanded_contexts),
        "pre_rerank_context_count": pre_rerank_count,
        "rerank_limit": final_limit,
        "adjacent_added": adjacent_added,
        "pageindex_added": pageindex_added,
        "pageindex_selected": pageindex_selected,
        "unique_document_count": len(unique_docs),
        "best_score": round(best_score, 4),
        "backend": "hybrid" if pageindex_added else retrieval_backend,
        "fallback_note": retrieval_note,
    }
    note_parts = [
        retrieval_note,
        f"adaptive:{plan['intent']}",
        f"candidates={candidate_count}",
        f"filtered={len(filtered)}",
        f"contexts={len(expanded_contexts)}",
        f"rerank={pre_rerank_count}->{len(expanded_contexts)}",
    ]
    if adjacent_added:
        note_parts.append(f"adjacent_added={adjacent_added}")
    if pageindex_added:
        note_parts.append(f"pageindex_added={pageindex_added}")
        retrieval_backend = "hybrid"
    retrieval_note = "; ".join(part for part in note_parts if part)
    return expanded_contexts, retrieval_backend, retrieval_note, candidate_count, meta
