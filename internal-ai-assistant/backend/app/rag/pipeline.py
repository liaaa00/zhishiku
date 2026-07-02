from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ..document_metadata import (
    allowed_kinds_for_query_topic,
    enrich_context_metadata,
    filter_contexts_by_allowed_kinds,
    normalize_document_scope,
)
from ..models import User
from ..settings_service import get_embedding_config
from .evidence_checker import check_evidence
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
    if any(term in text for term in GRAPH_QUERY_TERMS):
        return True
    # 表格中的城市/月度规则也可用图谱辅助诊断，但 table 答案仍以结构化行为准。
    return bool(re.search(r"20\d{2}年\d{1,2}月", text)) and any(term in text for term in ("社保", "医保", "公积金", "银行账户"))


def _context_identity(context: dict[str, Any]) -> str:
    return "|".join(str(context.get(key) or "") for key in ("retrieval_channel", "document_id", "chunk_id", "chunk_index", "content"))


def _merge_contexts(primary: list[dict[str, Any]], extra: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for context in [*extra, *primary]:
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
    result = _retrieve_by_route(db, question, user, top_k, analysis, route, scope)

    graph_checked = _should_check_graph(question, route.name)
    graph_contexts = _graph_contexts_for_question(db, question, user, top_k, scope) if graph_checked else []
    graph_primary_query = _should_use_graph_as_primary_context(question)
    original_route = route.to_dict()
    contexts = result.contexts
    backend = result.backend
    note_parts = [result.note]
    route_meta = route.to_dict()
    if graph_checked:
        note_parts.append(f"graph_checked={len(graph_contexts)}")
    if graph_contexts and graph_primary_query:
        # 关系/流程/派单规则等自然问法由系统内部自动使用图谱证据作为主答案上下文；用户不需要知道或说出“图谱”。
        contexts = graph_contexts
        backend = "graph"
        route_meta = {"name": "text", "intent": "text_qa", "confidence": max(float(route.confidence or 0.0), 0.86), "reason": f"graph_primary_query_overrode_{route.name}"}
        note_parts.append("graph_direct")
    elif graph_contexts and route.name != "table":
        contexts = _merge_contexts(contexts, graph_contexts, max(top_k, len(contexts), 8))
        backend = "hybrid+graph" if backend else "graph"
        note_parts.append("graph_merged")

    contexts = enrich_context_metadata(db, contexts)
    route_name_for_filter = str(route_meta.get("name") or route.name)
    query_profile = (result.meta or {}).get("query_profile") or {}
    allowed_doc_kinds = allowed_kinds_for_query_topic(query_profile.get("topic"), route_name_for_filter)
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
            "rag_router_version": "phase1_rules",
            "query_analysis": analysis.to_dict(),
            "retrieval_route": route_meta,
            "original_retrieval_route": original_route,
            "knowledge_scope": scope,
            "allowed_document_kinds": sorted(allowed_doc_kinds),
            "document_kind_filtered_count": document_kind_dropped,
            "embedding_quality": _embedding_quality_meta(db),
            "evidence_check": evidence.to_dict(),
            "graph_retrieval": {
                "checked": graph_checked,
                "matched": bool(graph_contexts),
                "context_count": len(graph_contexts),
                "merged_into_contexts": bool(graph_contexts and (route.name != "table" or graph_primary_query)),
                "direct_answer": bool(graph_contexts and graph_primary_query),
            },
        }
    )
    note = "; ".join(part for part in [*note_parts, f"route={route_meta.get('name') or route.name}", f"evidence={evidence.reason}"] if part)
    return contexts, backend, note, result.candidate_count + len(graph_contexts), meta
