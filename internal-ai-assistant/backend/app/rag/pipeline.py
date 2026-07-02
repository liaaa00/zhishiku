from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from ..models import User
from .evidence_checker import check_evidence
from .query_analyzer import analyze_query
from .retrieval_router import select_route
from .retrievers import metadata_retriever, summary_retriever, table_retriever, text_retriever
from .schemas import RetrievalResult


GRAPH_QUERY_TERMS = (
    "图谱",
    "关系",
    "关联",
    "对应",
    "属于",
    "谁负责",
    "谁处理",
    "后道",
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


def _retrieve_by_route(db: Session, question: str, user: User, top_k: int, analysis, route) -> RetrievalResult:
    if route.name == "table":
        return table_retriever.search(db, question, user, analysis, top_k=top_k)
    if route.name == "metadata":
        return metadata_retriever.search(db, question, user, analysis, top_k=top_k)
    if route.name == "summary":
        return summary_retriever.search(db, question, user, analysis, top_k=max(top_k, 10))
    return text_retriever.search(db, question, user, analysis, top_k=top_k)


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


def _graph_contexts_for_question(db: Session, question: str, user: User, top_k: int) -> list[dict[str, Any]]:
    try:
        from ..graph_retrieval import retrieve_graph_contexts

        return retrieve_graph_contexts(db, question, user, top_k=max(3, min(top_k, 8)))
    except Exception:
        return []


def retrieve_contexts(db: Session, question: str, user: User, top_k: int = 5) -> tuple[list[dict], str, str, int, dict]:
    """First-stage retrieval router entrypoint.

    Return shape intentionally matches legacy retrieval.adaptive_retrieve_contexts:
    (contexts, retrieval_backend, retrieval_note, candidate_count, retrieval_meta).
    """

    analysis = analyze_query(question)
    route = select_route(analysis)
    result = _retrieve_by_route(db, question, user, top_k, analysis, route)

    graph_checked = _should_check_graph(question, route.name)
    graph_contexts = _graph_contexts_for_question(db, question, user, top_k) if graph_checked else []
    contexts = result.contexts
    backend = result.backend
    note_parts = [result.note]
    if graph_checked:
        note_parts.append(f"graph_checked={len(graph_contexts)}")
    if graph_contexts and route.name != "table":
        contexts = _merge_contexts(contexts, graph_contexts, max(top_k, len(contexts), 8))
        backend = "hybrid+graph" if backend else "graph"
        note_parts.append("graph_merged")

    evidence = check_evidence(contexts, analysis, route)

    meta = dict(result.meta or {})
    meta.update(
        {
            "rag_router_version": "phase1_rules",
            "query_analysis": analysis.to_dict(),
            "retrieval_route": route.to_dict(),
            "evidence_check": evidence.to_dict(),
            "graph_retrieval": {
                "checked": graph_checked,
                "matched": bool(graph_contexts),
                "context_count": len(graph_contexts),
                "merged_into_contexts": bool(graph_contexts and route.name != "table"),
            },
        }
    )
    note = "; ".join(part for part in [*note_parts, f"route={route.name}", f"evidence={evidence.reason}"] if part)
    return contexts, backend, note, result.candidate_count + len(graph_contexts), meta
