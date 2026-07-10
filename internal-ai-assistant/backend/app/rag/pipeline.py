from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..document_metadata import (
    enrich_context_metadata,
    filter_contexts_by_allowed_kinds,
    normalize_document_scope,
)
from ..document_routing_config import allowed_kinds_for_query_topic_config
from ..models import Document, DocumentChunk, User
from ..settings_service import get_embedding_config
from ..wiki.search import retrieve_wiki_contexts
from .evidence_checker import check_evidence, check_wiki_evidence
from .query_analyzer import analyze_query
from .retrieval_router import select_route
from .retrievers import metadata_retriever, summary_retriever, table_retriever, text_retriever
from .schemas import RetrievalResult


GRAPH_QUERY_TERMS = (
    "图谱",
    "关系",
    "关联",
    "节点",
    "图谱节点",
    "派单规则",
    "触发",
    "对应",
    "属于",
    "谁负责",
    "谁处理",
    "由谁",
    "哪个团队",
    "哪个公司",
    "哪家公司",
    "后道",
    "后续",
    "流程",
    "步骤",
    "下一步",
    "派出",
    "传导",
    "截止时间",
    "操作规则",
    "开设公司",
    "公司名称",
    "公积金比例",
)


GRAPH_PRIMARY_QUERY_TERMS = (
    # 用户不需要知道“图谱”这个后台概念；这些自然问法也应自动使用关系证据作为主上下文。
    "图谱",
    "关系",
    "关联",
    "节点",
    "派单规则",
    "触发",
    "对应",
    "属于",
    "谁负责",
    "谁处理",
    "由谁",
    "哪个团队",
    "哪个公司",
    "哪家公司",
    "后道",
    "流程",
    "步骤",
    "下一步",
    "传导",
    "操作规则",
    "包含哪些",
    "有哪些",
)


def _should_use_graph_as_primary_context(question: str) -> bool:
    text = re.sub(r"\s+", "", question or "")
    if not text:
        return False
    return any(term in text for term in GRAPH_PRIMARY_QUERY_TERMS)


def _embedding_quality_meta(db: Session) -> dict[str, Any]:
    cfg = get_embedding_config(db)
    provider = str(cfg.get("provider") or "local").strip().lower()
    model = str(cfg.get("model") or "local-hash").strip()
    api_key_set = bool(cfg.get("api_key"))
    remote_provider = provider in {"openai", "openai-compatible", "remote"}
    using_local_hash = (not remote_provider) or (not api_key_set) or model.lower() == "local-hash"
    warning = "当前使用 local-hash，本地可用但语义召回能力有限；配置远程 embedding 后建议重建向量库。" if using_local_hash else "已配置远程 embedding；如刚切换配置，请重建向量库避免新旧向量混用。"
    return {
        "provider": provider,
        "model": model,
        "api_key_set": api_key_set,
        "using_local_hash": using_local_hash,
        "ready": not using_local_hash,
        "warning": warning,
    }


def _retrieve_by_route(db: Session, question: str, user: User, top_k: int, analysis, route, knowledge_scope: str) -> RetrievalResult:
    if route.name == "table":
        return table_retriever.search(db, question, user, analysis, top_k=top_k, knowledge_scope=knowledge_scope)
    if route.name == "metadata":
        return metadata_retriever.search(db, question, user, analysis, top_k=top_k, knowledge_scope=knowledge_scope)
    if route.name == "summary":
        return summary_retriever.search(db, question, user, analysis, top_k=max(top_k, 10), knowledge_scope=knowledge_scope)
    return text_retriever.search(db, question, user, analysis, top_k=top_k, knowledge_scope=knowledge_scope)


def _should_check_graph(question: str, route_name: str) -> bool:
    if route_name in {"metadata", "summary"}:
        return False
    text = re.sub(r"\s+", "", question or "")
    if not text:
        return False
    # 员工侧电子签问题有专门的文本检索对齐逻辑，图谱介入只会把“流程”类问法
    # 误引向工单系统/表格文件（如“劳动合同电子签流程”被图谱抢走）。
    from ..retrieval import _is_esign_query

    if _is_esign_query(question):
        return False
    if any(term in text for term in GRAPH_QUERY_TERMS):
        return True
    # 表格中的城市/月度规则也可用图谱辅助诊断，但 table 答案仍以结构化行为准。
    return bool(re.search(r"20\d{2}年\d{1,2}月", text)) and any(term in text for term in ("社保", "医保", "公积金", "银行账户"))


def _context_identity(context: dict[str, Any]) -> str:
    return "|".join(str(context.get(key) or "") for key in ("document_id", "chunk_id", "chunk_index", "content"))


def _compact_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _add_title_token(tokens: set[str], token: str) -> None:
    compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(token or "")).lower()
    if len(compact) >= 4 and not compact.isdigit():
        tokens.add(compact)
        without_tail_number = re.sub(r"\d{2,}$", "", compact)
        if len(without_tail_number) >= 4 and not without_tail_number.isdigit():
            tokens.add(without_tail_number)


def _title_match_tokens(value: Any) -> set[str]:
    raw = str(value or "").rsplit(".", 1)[0]
    tokens: set[str] = set()
    _add_title_token(tokens, raw)
    for part in re.split(r"[^0-9A-Za-z\u4e00-\u9fff]+", raw):
        _add_title_token(tokens, part)
    return tokens


def _document_title_matches_question(question: str, title: str, filename: str) -> bool:
    compact_question = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(question or "")).lower()
    if len(compact_question) < 4:
        return False
    for candidate in (title, str(filename or "").rsplit(".", 1)[0]):
        for token in _title_match_tokens(candidate):
            if token in compact_question:
                return True
    return False


def _explicit_title_match_document_ids(db: Session, question: str, knowledge_scope: str, user: User | None = None) -> set[str]:
    """Return accessible documents whose title/filename is explicitly mentioned in the question.

    Graph evidence is useful as supporting context, but when the user names a document
    such as “电子劳动合同操作指南”, the named document should remain the primary source.
    """
    query = select(Document)
    if user is None:
        # Without a user object we cannot safely apply personal attachment permissions,
        # so keep the legacy conservative behavior for chat-scoped uploads.
        query = query.where(~Document.source_type.like("chat_%"))
    if knowledge_scope != "all":
        query = query.where(Document.knowledge_scope == knowledge_scope)
    group_ids = None
    has_access = None
    if user is not None:
        from ..retrieval import has_document_access, user_group_ids

        group_ids = user_group_ids(user)
        has_access = has_document_access
    matched: set[str] = set()
    for doc in db.execute(query).scalars().all():
        if has_access is not None and not has_access(db, doc, user, group_ids, knowledge_scope=knowledge_scope):
            continue
        if _document_title_matches_question(question, doc.title or "", doc.filename or ""):
            matched.add(str(doc.id))
    return matched


def _question_recall_terms(question: str) -> set[str]:
    compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", str(question or "")).lower()
    terms = set(re.findall(r"[a-z0-9_]{2,}", compact))
    cjk = "".join(re.findall(r"[\u4e00-\u9fff]", compact))
    for size in (2, 3, 4, 5, 6):
        for index in range(max(0, len(cjk) - size + 1)):
            terms.add(cjk[index : index + size])
    return {term for term in terms if len(term) >= 2}


def _explicit_title_match_contexts(db: Session, question: str, document_ids: set[str], limit: int) -> list[dict[str, Any]]:
    if not document_ids:
        return []
    docs = {doc.id: doc for doc in db.execute(select(Document).where(Document.id.in_(document_ids))).scalars().all()}
    if not docs:
        return []
    terms = _question_recall_terms(question)
    chunks = db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id.in_(docs.keys()))
        .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index.asc())
    ).scalars().all()
    scored: list[tuple[float, int, dict[str, Any]]] = []
    for chunk in chunks:
        doc = docs.get(chunk.document_id)
        if not doc:
            continue
        haystack = f"{doc.title} {doc.filename} {chunk.content or ''}".lower()
        hits = [term for term in terms if term in haystack]
        title_hits = [term for term in terms if term in f"{doc.title} {doc.filename}".lower()]
        score = 0.86 + min(0.12, len(hits) * 0.015) + min(0.08, len(title_hits) * 0.02)
        context = {
            "document_id": doc.id,
            "document_title": doc.title,
            "filename": doc.filename,
            "chunk_id": chunk.id,
            "page_number": chunk.page_number,
            "chunk_index": chunk.chunk_index,
            "source_type": doc.source_type,
            "content": chunk.content,
            "score": round(min(score, 0.99), 4),
            "match_terms": hits[:12],
            "match_reason": "显式标题命中文档",
            "retrieval_channel": "title_match",
            "title_match_protected": True,
        }
        scored.append((float(context["score"]), int(chunk.chunk_index or 0), context))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[: max(1, limit)]]


def _merge_contexts(primary: list[dict[str, Any]], extra: list[dict[str, Any]], limit: int, *, extra_first: bool = True) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    ordered = [*extra, *primary] if extra_first else [*primary, *extra]
    for context in ordered:
        identity = _context_identity(context)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(context)
        if len(merged) >= limit:
            break
    return merged


def _graph_contexts_for_question(db: Session, question: str, user: User, top_k: int, knowledge_scope: str) -> list[dict[str, Any]]:
    try:
        from ..graph_retrieval import retrieve_graph_contexts

        return retrieve_graph_contexts(db, question, user, top_k=max(3, min(top_k, 8)), knowledge_scope=knowledge_scope)
    except Exception:
        return []


def retrieve_contexts(db: Session, question: str, user: User, top_k: int = 5, knowledge_scope: str = "production") -> tuple[list[dict], str, str, int, dict]:
    """First-stage retrieval router entrypoint.

    Return shape intentionally matches legacy retrieval.adaptive_retrieve_contexts:
    (contexts, retrieval_backend, retrieval_note, candidate_count, retrieval_meta).
    """

    analysis = analyze_query(question)
    route = select_route(analysis)
    scope = normalize_document_scope(knowledge_scope, "production")

    wiki_contexts: list[dict[str, Any]] = []
    wiki_meta: dict[str, Any] = {"enabled": True, "used": False, "reason": "wiki_skipped_for_table_route"}
    wiki_gate = None
    if route.name != "table":
        wiki_contexts, wiki_meta = retrieve_wiki_contexts(db, question, user, top_k=max(top_k, 5), knowledge_scope=scope)
    if wiki_meta.get("used") and wiki_contexts:
        wiki_contexts = enrich_context_metadata(db, wiki_contexts)
        wiki_gate = check_wiki_evidence(wiki_contexts, analysis, wiki_meta)
        wiki_meta = {
            **wiki_meta,
            "direct_return": wiki_gate.sufficient,
            "evidence_gate": wiki_gate.to_dict(),
        }
        if wiki_gate.sufficient:
            route_meta = {
                "name": "wiki",
                "intent": analysis.intent,
                "confidence": max(float(analysis.confidence or 0.0), float(wiki_meta.get("best_score") or 0.0)),
                "reason": "wiki_first_evidence_sufficient",
            }
            meta = {
                "rag_router_version": "wiki_first_v2_evidence_gated",
                "query_analysis": analysis.to_dict(),
                "retrieval_route": route_meta,
                "original_retrieval_route": route.to_dict(),
                "knowledge_scope": scope,
                "wiki_first": wiki_meta,
                "embedding_quality": _embedding_quality_meta(db),
                "evidence_check": wiki_gate.to_dict(),
                "graph_retrieval": {"checked": False, "matched": False, "context_count": 0, "merged_into_contexts": False, "direct_answer": False},
            }
            note = "; ".join(
                part
                for part in [
                    "wiki_first=direct",
                    f"wiki_candidates={wiki_meta.get('candidate_count', 0)}",
                    "route=wiki",
                    f"evidence={wiki_gate.reason}",
                ]
                if part
            )
            return wiki_contexts, "wiki", note, int(wiki_meta.get("candidate_count") or len(wiki_contexts)), meta

    result = _retrieve_by_route(db, question, user, top_k, analysis, route, scope)

    graph_checked = _should_check_graph(question, route.name)
    graph_contexts = _graph_contexts_for_question(db, question, user, top_k, scope) if graph_checked else []
    explicit_title_match_ids = _explicit_title_match_document_ids(db, question, scope, user)
    graph_primary_query = route.name != "table" and _should_use_graph_as_primary_context(question) and not explicit_title_match_ids
    original_route = route.to_dict()
    contexts = result.contexts
    backend = result.backend
    note_parts = [result.note]
    route_meta = route.to_dict()
    if wiki_gate is not None and wiki_contexts:
        from ..retrieval import rerank_contexts

        mixed_limit = max(top_k, len(contexts), 8)
        mixed_contexts = _merge_contexts(wiki_contexts, contexts, mixed_limit * 2, extra_first=False)
        contexts, _wiki_selected = rerank_contexts(
            question,
            mixed_contexts,
            mixed_limit,
            (result.meta or {}).get("query_profile"),
        )
        backend = f"{backend}+wiki" if backend else "wiki_fallback"
        note_parts.append(f"wiki_fallback={wiki_gate.reason}")
        wiki_meta = {
            **wiki_meta,
            "direct_return": False,
            "fallback_merged": True,
            "fallback_context_count": len(wiki_contexts),
        }
    if graph_checked:
        note_parts.append(f"graph_checked={len(graph_contexts)}")
    if graph_contexts and graph_primary_query:
        # 关系/流程/派单规则等自然问法由系统内部自动使用图谱证据作为主答案上下文；用户不需要知道或说出“图谱”。
        contexts = graph_contexts
        backend = "graph"
        route_meta = {"name": "text", "intent": "text_qa", "confidence": max(float(route.confidence or 0.0), 0.86), "reason": f"graph_primary_query_overrode_{route.name}"}
        note_parts.append("graph_direct")
    elif graph_contexts and route.name != "table":
        contexts = _merge_contexts(contexts, graph_contexts, max(top_k, len(contexts), 8), extra_first=not bool(explicit_title_match_ids))
        backend = "hybrid+graph" if backend else "graph"
        note_parts.append("graph_merged")

    title_match_contexts = _explicit_title_match_contexts(db, question, explicit_title_match_ids, max(top_k, 8)) if route.name != "table" else []
    if title_match_contexts:
        contexts = _merge_contexts(title_match_contexts, contexts, max(top_k, len(contexts), 8), extra_first=False)
        backend = f"{backend}+title" if backend else "title_match"
        note_parts.append(f"title_match_contexts={len(title_match_contexts)}")

    contexts = enrich_context_metadata(db, contexts)
    route_name_for_filter = str(route_meta.get("name") or route.name)
    query_profile = (result.meta or {}).get("query_profile") or {}
    allowed_doc_kinds = allowed_kinds_for_query_topic_config(db, query_profile.get("topic"), route_name_for_filter)
    filtered_contexts, document_kind_dropped = filter_contexts_by_allowed_kinds(contexts, allowed_doc_kinds)
    if filtered_contexts:
        contexts = filtered_contexts

    evidence_route_name = route_meta.get("name") or route.name
    if evidence_route_name != route.name:
        route.name = evidence_route_name
        route.intent = route_meta.get("intent") or route.intent
        route.reason = route_meta.get("reason") or route.reason
    evidence = check_evidence(contexts, analysis, route)

    meta = dict(result.meta or {})
    meta.update(
        {
            "rag_router_version": "wiki_first_v2_hybrid_fallback" if wiki_gate is not None else "phase1_rules",
            "wiki_first": wiki_meta,
            "query_analysis": analysis.to_dict(),
            "retrieval_route": route_meta,
            "original_retrieval_route": original_route,
            "knowledge_scope": scope,
            "allowed_document_kinds": sorted(allowed_doc_kinds),
            "document_kind_filtered_count": document_kind_dropped,
            "title_match_context_count": len(title_match_contexts),
            "embedding_quality": _embedding_quality_meta(db),
            "evidence_check": evidence.to_dict(),
            "graph_retrieval": {
                "checked": graph_checked,
                "matched": bool(graph_contexts),
                "context_count": len(graph_contexts),
                "merged_into_contexts": bool(graph_contexts and (route.name != "table" or graph_primary_query)),
                "direct_answer": bool(graph_contexts and graph_primary_query),
                "explicit_title_match_document_ids": sorted(explicit_title_match_ids),
                "title_match_protected_primary": bool(explicit_title_match_ids),
            },
        }
    )
    note = "; ".join(part for part in [*note_parts, f"route={route_meta.get('name') or route.name}", f"evidence={evidence.reason}"] if part)
    wiki_candidate_count = int(wiki_meta.get("candidate_count") or 0) if wiki_gate is not None else 0
    return contexts, backend, note, result.candidate_count + len(graph_contexts) + wiki_candidate_count, meta
