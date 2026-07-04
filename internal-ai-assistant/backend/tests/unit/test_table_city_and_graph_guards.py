from __future__ import annotations

from app.rag.schemas import EvidenceCheck, QueryAnalysis, RetrievalResult, RetrievalRoute
from app.table_plan import parse_table_query_plan


def _u(value: str) -> str:
    return value.encode("utf-8").decode("unicode_escape")


def test_ningbo_beilun_city_filter_collapses_to_longest_match() -> None:
    question = _u("\\u5b81\\u6ce2\\u5317\\u4ed1\\u516c\\u79ef\\u91d1\\u6bd4\\u4f8b\\u6709\\u54ea\\u4e9b\\uff1f")

    plan = parse_table_query_plan(question)

    city_filters = [item for item in plan.filters if item.get("column") == "city"]
    assert city_filters == [{"column": "city", "operator": "contains", "value": _u("\\u5b81\\u6ce2\\u5317\\u4ed1")}]
    assert "fund_ratio" in plan.select_columns


def test_beilun_document_context_does_not_create_city_filter() -> None:
    question = _u(
        "\\u5317\\u4ed1\\u5206\\u516c\\u53f8\\u8868\\u91cc\\u5317\\u4eac"
        "\\u94f6\\u884c\\u8d26\\u6237\\u548c\\u793e\\u4fdd\\u516c\\u79ef\\u91d1"
        "\\u8d26\\u6237\\u662f\\u5426\\u5f00\\u5177\\u5b8c\\u6210\\uff1f"
    )

    plan = parse_table_query_plan(question)

    city_filters = [item for item in plan.filters if item.get("column") == "city"]
    assert city_filters == [{"column": "city", "operator": "contains", "value": _u("\\u5317\\u4eac")}]
    assert "bank_account" in plan.select_columns
    assert "social_account" in plan.select_columns


def test_table_route_is_not_overridden_by_graph_primary_terms(monkeypatch) -> None:
    from app.rag import pipeline

    question = _u("\\u5317\\u4ed1\\u5206\\u516c\\u53f8\\u7684\\u516c\\u79ef\\u91d1\\u6bd4\\u4f8b\\u6709\\u54ea\\u4e9b\\uff1f")
    table_context = {"document_id": "table-doc", "content": "table answer", "retrieval_channel": "table"}
    graph_context = {"document_id": "graph-doc", "content": "graph answer", "retrieval_channel": "graph"}

    monkeypatch.setattr(
        pipeline,
        "analyze_query",
        lambda value: QueryAnalysis(query=value, intent="table_query", confidence=0.95, route_hint="table"),
    )
    monkeypatch.setattr(
        pipeline,
        "select_route",
        lambda analysis: RetrievalRoute(name="table", intent="table_query", confidence=0.95, reason="unit-test"),
    )
    monkeypatch.setattr(
        pipeline,
        "_retrieve_by_route",
        lambda *args, **kwargs: RetrievalResult(
            contexts=[table_context],
            backend="table",
            note="table",
            candidate_count=1,
            meta={},
        ),
    )
    monkeypatch.setattr(pipeline, "_graph_contexts_for_question", lambda *args, **kwargs: [graph_context])
    monkeypatch.setattr(pipeline, "_explicit_title_match_document_ids", lambda *args, **kwargs: set())
    monkeypatch.setattr(pipeline, "enrich_context_metadata", lambda db, contexts: contexts)
    monkeypatch.setattr(pipeline, "allowed_kinds_for_query_topic_config", lambda *args, **kwargs: set())
    monkeypatch.setattr(pipeline, "filter_contexts_by_allowed_kinds", lambda contexts, allowed: (contexts, 0))
    monkeypatch.setattr(
        pipeline,
        "check_evidence",
        lambda contexts, analysis, route: EvidenceCheck(
            sufficient=True,
            reason="unit-test",
            source_count=len(contexts),
            document_count=len({item.get("document_id") for item in contexts}),
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_embedding_quality_meta",
        lambda db: {"using_local_hash": True, "ready": False},
    )

    contexts, backend, _note, _candidate_count, meta = pipeline.retrieve_contexts(
        db=None,
        question=question,
        user=None,
        top_k=5,
        knowledge_scope="test",
    )

    assert backend == "table"
    assert contexts == [table_context]
    assert meta["retrieval_route"]["name"] == "table"
    assert meta["graph_retrieval"]["matched"] is True
    assert meta["graph_retrieval"]["direct_answer"] is False
    assert meta["graph_retrieval"]["merged_into_contexts"] is False
