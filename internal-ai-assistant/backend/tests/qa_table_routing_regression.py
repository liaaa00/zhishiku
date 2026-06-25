"""Regression for table routing.

Run from internal-ai-assistant/backend:
    python tests/qa_table_routing_regression.py

Ensures process/document questions do not route into table mode,
while genuine table/statistical questions still do.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.table_query import is_table_query


def main() -> None:
    cases = {
        "上海外服劳动合同电子签流程是什么？": False,
        "上海劳动合同怎么签署？": False,
        "上海外服云平台注册流程是什么？": False,
        "上海社保公积金截止时间是什么？": True,
        "2026年3月社保预计缴款时间": True,
        "列出上海有效网点清单": True,
        "上海有哪些开设公司的城市名单？": True,
    }

    for question, expected in cases.items():
        actual = is_table_query(question)
        if actual != expected:
            raise AssertionError(f"{question}: expected {expected}, got {actual}")

    print("Table routing regression passed.")


if __name__ == "__main__":
    main()
