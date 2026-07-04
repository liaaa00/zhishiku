from __future__ import annotations

from app.routers.chat_api import decide_chat_route


def test_table_business_question_routes_to_knowledge_without_ai_classifier() -> None:
    route = decide_chat_route("202603重庆社保的截止时间是什么？", [], {})

    assert route["should_retrieve"] is True
    assert route["intent"] == "knowledge"
    assert route["source"] == "rule_table_query"


def test_business_negative_question_routes_to_knowledge_without_ai_classifier() -> None:
    route = decide_chat_route("公司今年年会抽奖一等奖是什么？", [], {})

    assert route["should_retrieve"] is True
    assert route["intent"] == "knowledge"
    assert route["source"] == "rule_business_knowledge"


def test_general_chat_still_does_not_retrieve() -> None:
    route = decide_chat_route("你好，你是谁？", [], {})

    assert route["should_retrieve"] is False
    assert route["intent"] == "chat"
