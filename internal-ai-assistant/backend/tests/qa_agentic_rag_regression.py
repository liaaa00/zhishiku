"""Regression checks for the bounded Agentic RAG controller.

Run from internal-ai-assistant/backend:
    python tests/qa_agentic_rag_regression.py

These checks intentionally avoid a real database. They validate the cheap control
layer that decides whether to spend an extra retrieval pass.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("VECTOR_BACKEND", "local")
os.environ.setdefault("EMBEDDING_PROVIDER", "local")

from app.retrieval import (  # noqa: E402
    agentic_route_for_question,
    evaluate_agentic_evidence,
    retrieval_plan_for_question,
    rewrite_query_for_agentic,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> None:
    simple_question = "劳动合同电子签入口在哪里？"
    simple_plan = retrieval_plan_for_question(simple_question)
    simple_route = agentic_route_for_question(simple_question, simple_plan)
    require(not simple_route["enabled"], f"simple lookup should stay single-pass, got {simple_route}")
    require(rewrite_query_for_agentic(simple_question, simple_route) == [], "simple route must not rewrite")

    complex_question = "员工收到劳动合同签署通知后，如果微助手登录失败，企业端和员工端分别应该怎么处理？"
    complex_plan = retrieval_plan_for_question(complex_question)
    complex_route = agentic_route_for_question(complex_question, complex_plan)
    require(complex_route["enabled"], f"multi-hop exception question should enable agentic route, got {complex_route}")
    require(complex_route["max_extra_rounds"] == 1, f"extra rounds must stay bounded, got {complex_route}")

    rewrites = rewrite_query_for_agentic(complex_question, complex_route)
    require(len(rewrites) == 1, f"expected one bounded rewrite, got {rewrites}")
    require(complex_question in rewrites[0], "rewrite must preserve original question")
    require("外服云" in rewrites[0] and "合同组" in rewrites[0], f"rewrite should add employee/internal recall terms, got {rewrites[0]}")

    low_quality = evaluate_agentic_evidence(complex_question, [{"document_id": "noise", "content": "无关片段", "score": 0.03}], complex_plan)
    require(not low_quality["enough"], f"low quality evidence should not stop, got {low_quality}")

    high_quality_contexts = [
        {
            "document_id": "employee-guide",
            "document_title": "员工电子劳动合同签署指南",
            "content": "员工收到短信通知后，登录外服云或微助手，进入员工服务入口，核对劳动合同信息后点击签署。若登录失败，需要完成手机号验证和身份绑定。",
            "score": 0.82,
            "rerank_score": 0.91,
        },
        {
            "document_id": "internal-guide",
            "document_title": "企业端合同工单处理说明",
            "content": "企业端由HR或合同组在工单系统中查看签署状态，处理异常通知、内部审核、盖章和归档。",
            "score": 0.76,
            "rerank_score": 0.84,
        },
        {
            "document_id": "support-guide",
            "document_title": "微助手登录异常处理",
            "content": "微助手无法登录或收不到通知时，先核验手机号、身份绑定和员工服务权限，再重新进入劳动合同签署入口。",
            "score": 0.72,
            "rerank_score": 0.79,
        },
    ]
    high_quality = evaluate_agentic_evidence(complex_question, high_quality_contexts, complex_plan)
    require(high_quality["enough"], f"strong multi-document evidence should stop, got {high_quality}")

    print("Agentic RAG regression: all checks passed.")


if __name__ == "__main__":
    main()
