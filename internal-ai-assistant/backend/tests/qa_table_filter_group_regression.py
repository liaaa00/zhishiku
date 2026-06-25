"""Regression for table value filters, grouping, and distinct counting.

Run from internal-ai-assistant/backend:
    python tests/qa_table_filter_group_regression.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_table_filter_group.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Document, DocumentTableRow, User  # noqa: E402
from app.table_query import build_table_answer  # noqa: E402
from app.table_retrieval import table_mode_contexts  # noqa: E402


def _row(row_id: str, row_number: int, city: str, company: str, status: str = "有效") -> DocumentTableRow:
    payload = {
        "城市": city,
        "公司名称": company,
        "网点状态": status,
        "当前进度": "已完成",
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-table-filter-group",
        sheet_name="202606",
        row_number=row_number,
        row_key=f"202606:{row_number}",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text=" | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=False,
    )


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(id="admin", username="admin", password_hash="x", is_admin=True)
        doc = Document(
            id="doc-table-filter-group",
            title="有效网点清单202606",
            filename="有效网点清单202606.xlsx",
            storage_path="fixture.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        db.add(user)
        db.add(doc)
        db.add_all(
            [
                _row("row-sh-1", 2, "上海", "上海一号网点"),
                _row("row-sh-2", 3, "上海", "上海二号网点"),
                _row("row-sh-disabled", 4, "上海", "上海停用网点", "停用"),
                _row("row-bj-1", 5, "北京", "北京一号网点"),
                _row("row-cd-1", 6, "成都", "成都一号网点"),
            ]
        )
        db.commit()

        filter_question = "列出城市=上海的有效网点清单"
        contexts, meta = table_mode_contexts(db, filter_question, user, top_k=10)
        row_ids = {str(item.get("table_row_id")) for item in contexts if not item.get("is_header")}
        if row_ids != {"row-sh-1", "row-sh-2", "row-sh-disabled"}:
            raise AssertionError(f"city filter should keep only Shanghai rows, got {sorted(row_ids)}; meta={meta}")
        if meta.get("value_filter_matched_rows") != 3:
            raise AssertionError(f"expected 3 value-filter matches, got {meta}")

        multi_filter_question = "列出城市=上海且状态=有效的网点清单"
        multi_contexts, multi_meta = table_mode_contexts(db, multi_filter_question, user, top_k=10)
        multi_row_ids = {str(item.get("table_row_id")) for item in multi_contexts if not item.get("is_header")}
        if multi_row_ids != {"row-sh-1", "row-sh-2"}:
            raise AssertionError(f"multi filters should keep only active Shanghai rows, got {sorted(multi_row_ids)}; meta={multi_meta}")
        multi_answer = build_table_answer(multi_filter_question, multi_contexts)
        if "过滤条件：城市 包含 上海；状态 包含 有效" not in multi_answer:
            raise AssertionError(f"answer should explain multi filters; answer={multi_answer}")

        group_question = "有效网点按城市统计分别有多少个？"
        group_contexts, group_meta = table_mode_contexts(db, group_question, user, top_k=10)
        answer = build_table_answer(group_question, group_contexts)
        if "按城市统计" not in answer or "上海：3 条" not in answer or "北京：1 条" not in answer:
            raise AssertionError(f"grouped answer missing expected city counts; meta={group_meta}; answer={answer}")

        distinct_question = "有效网点覆盖多少个城市？"
        distinct_contexts, distinct_meta = table_mode_contexts(db, distinct_question, user, top_k=10)
        distinct_answer = build_table_answer(distinct_question, distinct_contexts)
        if "共有 3 个城市" not in distinct_answer:
            raise AssertionError(f"distinct city answer should count 3 cities; meta={distinct_meta}; answer={distinct_answer}")

        print("Table filter/group regression passed.")
    finally:
        db.close()
        engine.dispose()
        try:
            DB_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
