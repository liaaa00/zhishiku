from __future__ import annotations

from app.routers.chat_api import build_prompt_context_preview, build_retrieval_debug_summary, build_source_quality_notice


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
