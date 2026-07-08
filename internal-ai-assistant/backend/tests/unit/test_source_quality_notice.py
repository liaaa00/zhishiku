from __future__ import annotations

from app.routers.chat_api import build_prompt_context_preview, build_retrieval_debug_summary, build_source_quality_notice, build_table_fact_block, digest_contexts_for_answer, merge_table_fact_block, model_contexts_for_answer, should_use_fast_extractive_answer, should_use_table_llm_analysis, table_contexts_for_answer


def test_source_quality_notice_summarizes_poor_and_blocked_sources() -> None:
    notice = build_source_quality_notice([
        {
            "document_id": "good-doc",
            "document_title": "Good",
            "source_quality": {"grade": "good", "reasons": []},
        },
        {
            "document_id": "poor-doc",
            "document_title": "Poor Parse",
            "source_quality": {"grade": "poor", "reasons": ["very_low_text"]},
        },
        {
            "document_id": "blocked-doc",
            "document_title": "Blocked Parse",
            "source_quality": {"grade": "blocked", "reasons": ["processing_failed", "very_low_text"]},
        },
    ])

    assert notice["has_low_quality_sources"] is True
    assert notice["warning"]
    assert notice["affected_source_count"] == 2
    assert notice["affected_document_count"] == 2
    assert notice["grades"] == {"poor": 1, "blocked": 1}
    assert notice["reasons"] == ["processing_failed", "very_low_text"]
    assert notice["documents"] == ["Poor Parse", "Blocked Parse"]


def test_source_quality_notice_is_empty_for_good_sources() -> None:
    notice = build_source_quality_notice([
        {"document_id": "good-doc", "source_quality": {"grade": "good"}},
        {"document_id": "unknown-doc", "source_quality": {}},
    ])

    assert notice["has_low_quality_sources"] is False
    assert notice["warning"] == ""
    assert notice["affected_source_count"] == 0
    assert notice["affected_document_count"] == 0
    assert notice["grades"] == {}


def test_prompt_context_preview_matches_answer_context_shape() -> None:
    preview = build_prompt_context_preview([
        {
            "document_title": "Policy A",
            "page_number": 2,
            "source_type": "pdf",
            "location": "第2页",
            "content": "hello " * 400,
        }
    ], max_chars_per_source=80, max_total_chars=500)

    assert preview["source_count"] == 1
    assert preview["previewed_source_count"] == 1
    assert preview["clipped_sources"] == 1
    assert "[来源1] 文档：Policy A" in preview["text"]
    assert "类型：pdf" in preview["text"]
    assert preview["text"].endswith("…")


def test_model_contexts_for_answer_filters_blocked_and_irrelevant_text() -> None:
    contexts = [
        {
            "document_id": "blocked-doc",
            "document_title": "Blocked",
            "content": "irrelevant blocked text",
            "retrieval_channel": "semantic",
            "score": 0.99,
            "source_quality": {"grade": "blocked"},
        },
        {
            "document_id": "zero-doc",
            "document_title": "Zero",
            "content": "irrelevant zero score text",
            "retrieval_channel": "semantic",
            "score": 0.0,
            "rerank_score": 0.0,
            "intent_ranking": {"positive_signals": []},
        },
        {
            "document_id": "good-doc",
            "document_title": "Good",
            "content": "relevant answer text",
            "retrieval_channel": "semantic",
            "score": 0.1,
            "intent_ranking": {"positive_signals": ["relevant"]},
        },
        {
            "document_id": "table-header",
            "document_title": "Table Header",
            "content": "city=city",
            "retrieval_channel": "table",
            "is_header": True,
            "score": 0.45,
        },
        {
            "document_id": "table-doc",
            "document_title": "Table",
            "content": "table answer",
            "retrieval_channel": "table",
            "is_header": False,
            "score": 0.0,
        },
        {
            "document_id": "graph-doc",
            "document_title": "Graph",
            "content": "graph answer",
            "retrieval_channel": "graph",
            "score": 0.0,
        },
    ]

    selected = model_contexts_for_answer(contexts, summary_mode=False)
    selected_ids = [item.get("document_id") for item in selected]

    assert "blocked-doc" not in selected_ids
    assert "zero-doc" not in selected_ids
    assert "table-header" not in selected_ids
    assert selected_ids == ["good-doc", "table-doc", "graph-doc"]


def test_model_contexts_for_answer_returns_empty_when_no_evidence_passes_gate() -> None:
    selected = model_contexts_for_answer([
        {
            "document_id": "zero-doc",
            "content": "irrelevant zero score text",
            "retrieval_channel": "semantic",
            "score": 0.0,
            "rerank_score": -0.2,
            "intent_ranking": {"positive_signals": []},
        }
    ], summary_mode=False)

    assert selected == []


def test_model_contexts_for_answer_filters_weak_generic_company_matches() -> None:
    selected = model_contexts_for_answer([
        {
            "document_id": "weak-pageindex-doc",
            "document_title": "新版外服云平台注册流程-微助手",
            "content": "上海外服（集团）有限公司操作手册",
            "retrieval_channel": "pageindex",
            "pageindex_source": True,
            "score": 0.47,
            "rerank_score": 0.5533,
            "match_terms": ["公司"],
            "intent_ranking": {"positive_signals": [], "lexical_coverage": 0.0625},
        },
        {
            "document_id": "specific-doc",
            "document_title": "公积金办理说明",
            "content": "公积金办理说明和材料要求",
            "retrieval_channel": "pageindex",
            "pageindex_source": True,
            "score": 0.47,
            "rerank_score": 0.5533,
            "match_terms": ["公积金"],
            "intent_ranking": {"positive_signals": [], "lexical_coverage": 0.2},
        },
    ], summary_mode=False)

    assert [item.get("document_id") for item in selected] == ["specific-doc"]


def test_retrieval_debug_summary_warns_on_low_confidence_and_quality() -> None:
    quality_notice = {"has_low_quality_sources": True, "warning": "low quality"}
    summary = build_retrieval_debug_summary([
        {"document_id": "doc-1", "retrieval_channel": "semantic"},
        {"document_id": "doc-1", "pageindex_source": True},
    ], candidate_count=8, confidence=0.2, quality_notice=quality_notice)

    assert summary["answer_context_count"] == 2
    assert summary["unique_document_count"] == 1
    assert summary["channel_counts"]["semantic"] == 1
    assert summary["channel_counts"]["pageindex"] == 1
    assert "low quality" in summary["warnings"]
    assert any("置信度" in item for item in summary["warnings"])


def test_model_contexts_for_answer_caps_large_non_summary_contexts() -> None:
    contexts = [
        {
            "document_id": f"doc-{index}",
            "document_title": "Long Doc",
            "content": "长内容" * 2000,
            "retrieval_channel": "pageindex",
            "score": 0.8,
            "pageindex_source": True,
        }
        for index in range(12)
    ]

    selected = model_contexts_for_answer(contexts, summary_mode=False)

    assert len(selected) <= 8
    assert len(selected) < len(contexts)
    assert sum(len(item.get("content") or "") for item in selected) <= 18000


def test_table_contexts_for_answer_keep_all_table_rows() -> None:
    contexts = [
        {
            "document_id": "table-doc",
            "document_title": "Table",
            "content": f"城市=城市{index}",
            "retrieval_channel": "table",
            "is_header": False,
            "score": 0.0,
        }
        for index in range(12)
    ]
    contexts.insert(
        0,
        {
            "document_id": "table-header",
            "document_title": "Table Header",
            "content": "城市=城市",
            "retrieval_channel": "table",
            "is_header": True,
            "score": 0.45,
        },
    )

    model_selected = model_contexts_for_answer(contexts, summary_mode=False)
    table_selected = table_contexts_for_answer(contexts)
    digest_selected = digest_contexts_for_answer(contexts, model_selected, table_answer_mode=True)

    assert len(model_selected) == 8
    assert len(table_selected) == 12
    assert len(digest_selected) == 12
    assert all(not item.get("is_header") for item in table_selected)


def test_table_llm_analysis_intent_only_for_analytical_questions() -> None:
    assert should_use_table_llm_analysis("分析一下这些城市分公司开设进度有什么风险") is True
    assert should_use_table_llm_analysis("基于刚才表格结果进一步看一下短板") is True
    assert should_use_table_llm_analysis("目前北仑在哪些城市开了分公司") is False


def test_table_fact_block_keeps_deterministic_result_for_llm_analysis() -> None:
    contexts = [
        {
            "document_id": "doc-table",
            "document_title": "北仑分公司开设最新进度表0310",
            "retrieval_channel": "table",
            "table_row_id": "row-1",
            "sheet_name": "Sheet1",
            "row_number": 3,
            "content": "城市=北京 | 当前进度-4.开设公司名称=外服（浙江）企业服务有限公司北京分公司",
            "table_row": {
                "城市": "北京",
                "当前进度-4.开设公司名称": "外服（浙江）企业服务有限公司北京分公司",
            },
            "table_semantic_map": {},
            "score": 1.0,
        },
        {
            "document_id": "doc-table",
            "document_title": "北仑分公司开设最新进度表0310",
            "retrieval_channel": "table",
            "table_row_id": "row-2",
            "sheet_name": "Sheet1",
            "row_number": 4,
            "content": "城市=上海 | 当前进度-4.开设公司名称=外服（浙江）企业服务有限公司上海分公司",
            "table_row": {
                "城市": "上海",
                "当前进度-4.开设公司名称": "外服（浙江）企业服务有限公司上海分公司",
            },
            "table_semantic_map": {},
            "score": 1.0,
        },
    ]

    fact_block, structured = build_table_fact_block("分析这些分公司开设情况有什么风险", contexts)
    merged = merge_table_fact_block("## 表格结构化证据包\n- 命中表格行数：2", fact_block)

    assert "规则计算结果（硬事实，必须保持一致）" in fact_block
    assert "LLM 只能解释、归纳和提出建议，不能改写这些数字或明细" in fact_block
    assert "结论：共有 2 家命中记录" in fact_block
    assert structured["type"] in {"count", "retrieve", "list"}
    assert merged.startswith("## 规则计算结果")
    assert "## 表格结构化证据包" in merged


def test_fast_extractive_answer_is_used_for_large_broad_contexts() -> None:
    contexts = [
        {
            "document_id": f"doc-{index}",
            "document_title": "浙江企服工单系统开发需求文档",
            "content": "功能需求和流程说明" * 30,
            "retrieval_channel": "pageindex",
            "score": 0.82,
            "pageindex_source": True,
        }
        for index in range(6)
    ]

    assert should_use_fast_extractive_answer(
        "浙江企服工单系统开发需求文档主要包含哪些功能需求？",
        contexts,
        {"intent": "deep_analysis"},
        summary_mode=False,
        table_answer_mode=False,
    ) is True
    assert should_use_fast_extractive_answer(
        "202512重庆社保截止时间是什么？",
        contexts,
        {"intent": "precise_lookup"},
        summary_mode=False,
        table_answer_mode=False,
    ) is False
