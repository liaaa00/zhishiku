from __future__ import annotations

from app.table_schema import infer_column_semantics, semantic_schema_suggestions, semantic_value


def test_infer_column_semantics_prefers_named_and_sample_hints() -> None:
    rows = [
        {"所在城市": "上海", "当前进度": "已开通", "机构主体": "上海示例有限公司"},
        {"所在城市": "北仑", "当前进度": "未开通", "机构主体": "宁波示例分公司"},
    ]

    semantic_map = infer_column_semantics(rows)

    assert semantic_map["city"].raw_name == "所在城市"
    assert semantic_map["status"].raw_name == "当前进度"
    assert semantic_map["company"].raw_name == "机构主体"
    assert semantic_value(rows[0], "city", semantic_map) == "上海"
    assert semantic_value(rows[1], "status", semantic_map) == "未开通"


def test_semantic_schema_suggestions_are_confirmable_and_stable() -> None:
    rows = [{"所在城市": "上海", "当前进度": "有效"}]
    semantic_map = infer_column_semantics(rows)

    suggestions = semantic_schema_suggestions(
        semantic_map,
        document_id="doc-1",
        document_title="城市状态表",
        sheet_name="Sheet1",
    )

    city = next(item for item in suggestions if item["semantic_name"] == "city")
    assert city["suggestion_key"] == "doc-1:Sheet1:city:所在城市"
    assert city["action"] == "map_column_alias"
    assert city["status"] == "suggested"
    assert city["document_title"] == "城市状态表"
    assert city["confidence"] >= 1.0
    assert city["samples"] == ["上海"]
