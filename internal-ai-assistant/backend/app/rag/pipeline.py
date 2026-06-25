from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import User
from .evidence_checker import check_evidence
from .query_analyzer import analyze_query
from .retrieval_router import select_route
from .retrievers import metadata_retriever, summary_retriever, table_retriever, text_retriever
from .schemas import RetrievalResult


def _retrieve_by_route(db: Session, question: str, user: User, top_k: int, analysis, route) -> RetrievalResult:
    if route.name == "table":
        return table_retriever.search(db, question, user, analysis, top_k=top_k)
    if route.name == "metadata":
        return metadata_retriever.search(db, question, user, analysis, top_k=top_k)
    if route.name == "summary":
        return summary_retriever.search(db, question, user, analysis, top_k=top_k)
    return text_retriever.search(db, question, user, analysis, top_k=top_k)


def retrieve_contexts(db: Session, question: str, user: User, top_k: int = 5) -> tuple[list[dict], str, str, int, dict]:
    """First-stage retrieval router entrypoint.

    Return shape intentionally matches legacy retrieval.adaptive_retrieve_contexts:
    (contexts, retrieval_backend, retrieval_note, candidate_count, retrieval_meta).
    """

    analysis = analyze_query(question)
    route = select_route(analysis)
    result = _retrieve_by_route(db, question, user, top_k, analysis, route)
    evidence = check_evidence(result.contexts, analysis, route)

    meta = dict(result.meta or {})
    meta.update(
        {
            "rag_router_version": "phase1_rules",
            "query_analysis": analysis.to_dict(),
            "retrieval_route": route.to_dict(),
            "evidence_check": evidence.to_dict(),
        }
    )
    note = "; ".join(part for part in [result.note, f"route={route.name}", f"evidence={evidence.reason}"] if part)
    return result.contexts, result.backend, note, result.candidate_count, meta
