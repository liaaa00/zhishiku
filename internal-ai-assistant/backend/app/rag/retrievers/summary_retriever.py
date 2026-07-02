from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import User
from ..schemas import QueryAnalysis, RetrievalResult
from . import metadata_retriever


def search(db: Session, question: str, user: User, analysis: QueryAnalysis, top_k: int = 5, knowledge_scope: str = "production") -> RetrievalResult:
    # The chat API already has a richer accessible_document_summary_contexts path.
    # This retriever is mainly for admin diagnostics and non-chat callers of the
    # first-stage RAG pipeline.
    result = metadata_retriever.search(db, question, user, analysis, top_k=max(top_k, 10), knowledge_scope=knowledge_scope)
    meta = dict(result.meta or {})
    meta["mode"] = "summary"
    meta["intent"] = "summary_query"
    meta["summary_mode"] = True
    return RetrievalResult(result.contexts, "metadata", "summary_metadata_mode", result.candidate_count, meta)
