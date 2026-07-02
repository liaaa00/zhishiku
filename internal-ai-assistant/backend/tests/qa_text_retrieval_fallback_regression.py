"""Regression coverage for OCR-normalized keyword retrieval and fallback snippets.

Run from internal-ai-assistant/backend:
    python tests/qa_text_retrieval_fallback_regression.py
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai_client import extractive_fallback_answer  # noqa: E402
from app.retrieval import _keyword_score, keyword_terms_for_query  # noqa: E402


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(text or "")))


def test_keyword_score_normalizes_ocr_compatibility_chars() -> None:
    question = "工单系统里，后道交付团队登录后可以查询待办工单、导出材料附件并回写什么？"
    content = "后道交付团队可凭权限登录系统查询各类业务的待办⼯单，并导出办理所需的信息表单及材料附件，交付结果回写⾄系统。"

    score, hits = _keyword_score(keyword_terms_for_query(question), "浙江企服工单系统开发需求文档", content)

    normalized_hits = _norm(" ".join(hits))
    assert score > 0.5
    assert "待办工单" in normalized_hits
    assert "材料附件" in normalized_hits


def test_extractive_fallback_uses_focus_window_for_long_process_context() -> None:
    prefix = "章节摘要：这是较长的背景说明。" * 80
    evidence = "后道交付团队可凭权限登录系统查询各类业务的待办⼯单，并导出办理所需的对应信息表单及材料附件，推进后续业务办理和交付，并对交付结果回写⾄系统进行进度反馈。"
    contexts = [
        {
            "document_title": "浙江企服工单系统开发需求文档",
            "filename": "浙江企服工单系统开发需求文档.pdf",
            "content": prefix + evidence,
        }
    ]

    answer = extractive_fallback_answer("工单系统里，后道交付团队登录后可以查询和导出什么，并需要回写什么？", contexts, reason="test")
    normalized_answer = _norm(answer)

    assert "待办工单" in normalized_answer
    assert "信息表单" in normalized_answer
    assert "材料附件" in normalized_answer
    assert "进度反馈" in normalized_answer


if __name__ == "__main__":
    test_keyword_score_normalizes_ocr_compatibility_chars()
    test_extractive_fallback_uses_focus_window_for_long_process_context()
    print("Text retrieval fallback regression passed.")
