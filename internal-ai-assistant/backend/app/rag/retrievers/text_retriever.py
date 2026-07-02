from __future__ import annotations

from sqlalchemy.orm import Session

from ...models import User
from ..schemas import QueryAnalysis, RetrievalResult


def search(db: Session, question: str, user: User, analysis: QueryAnalysis, top_k: int = 5, knowledge_scope: str = "production") -> RetrievalResult:
    # Import lazily to avoid import cycles while retrieval.py delegates to rag.pipeline.
    from ...retrieval import _adaptive_text_retrieve_contexts

    contexts, backend, note, candidate_count, meta = _adaptive_text_retrieve_contexts(db, question, user, top_k=top_k, knowledge_scope=knowledge_scope)
    meta = dict(meta or {})
    meta.setdefault("mode", "text")
    meta.setdefault("intent", "text_qa")
    meta["query_analysis"] = analysis.to_dict()
    return RetrievalResult(contexts, backend, note, candidate_count, meta)
