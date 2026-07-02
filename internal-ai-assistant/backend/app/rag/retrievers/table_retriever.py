from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import User
from ...table_retrieval import table_mode_contexts
from ..schemas import QueryAnalysis, RetrievalResult


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def search(db: Session, question: str, user: User, analysis: QueryAnalysis, top_k: int = 5, knowledge_scope: str = "production") -> RetrievalResult:
    contexts, table_meta = table_mode_contexts(db, question, user, top_k=top_k, knowledge_scope=knowledge_scope)
    meta = {
        "mode": "table",
        "intent": "table_query",
        "candidate_count": len(contexts),
        "keyword_candidate_count": 0,
        "merged_candidate_count": len(contexts),
        "filtered_count": len(contexts),
        "final_context_count": len(contexts),
        "pre_rerank_context_count": len(contexts),
        "rerank_limit": len(contexts),
        "rule_rerank_limit": len(contexts),
        "llm_reranker_enabled": False,
        "llm_reranker_used": False,
        "llm_reranker_model": "",
        "llm_reranker_error": "",
        "llm_reranked_count": 0,
        "adjacent_added": 0,
        "pageindex_added": 0,
        "pageindex_selected": 0,
        "unique_document_count": len({c.get("document_id") for c in contexts if c.get("document_id")}),
        "best_score": max((_safe_float(item.get("score"), 0.0) for item in contexts), default=0.0),
        "backend": "table",
        "fallback_note": "table_query_mode",
        "table_mode": True,
        "query_analysis": analysis.to_dict(),
        **table_meta,
    }
    return RetrievalResult(
        contexts=contexts,
        backend="table",
        note=f"table_query_mode; rows={len(contexts)}",
        candidate_count=len(contexts),
        meta=meta,
    )
