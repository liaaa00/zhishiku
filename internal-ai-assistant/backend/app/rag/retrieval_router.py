from __future__ import annotations

from .schemas import QueryAnalysis, RetrievalRoute


def select_route(analysis: QueryAnalysis) -> RetrievalRoute:
    """Select the first-stage retrieval route.

    The route is intentionally simple: query_analyzer owns intent detection;
    this module only applies operational safeguards and makes route decisions
    explicit in retrieval_meta for diagnostics.
    """

    if analysis.intent == "table_query":
        return RetrievalRoute(
            name="table",
            intent=analysis.intent,
            confidence=analysis.confidence,
            reason="table_query_intent",
        )
    if analysis.intent == "metadata_query":
        return RetrievalRoute(
            name="metadata",
            intent=analysis.intent,
            confidence=analysis.confidence,
            reason="metadata_query_intent",
        )
    if analysis.intent == "summary_query":
        return RetrievalRoute(
            name="summary",
            intent=analysis.intent,
            confidence=analysis.confidence,
            reason="summary_query_intent",
        )
    if analysis.intent == "text_qa":
        return RetrievalRoute(
            name="text",
            intent=analysis.intent,
            confidence=analysis.confidence,
            reason="text_qa_intent",
        )
    return RetrievalRoute(
        name="fallback",
        intent="unknown",
        confidence=analysis.confidence,
        reason="unknown_intent_fallback",
    )
