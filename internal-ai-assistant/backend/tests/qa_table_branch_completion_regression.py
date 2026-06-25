"""Regression for Beilun branch completion table filtering.

Run from internal-ai-assistant/backend:
    python tests/qa_table_branch_completion_regression.py

The question uses Beilun as the business subject, not as a city filter.
Rows should qualify only when bank account, social/security fund account,
provident-fund ratio, and opened company name are all completed/present.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_table_branch_completion.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Document, DocumentTableRow, User  # noqa: E402
from app.table_retrieval import table_mode_contexts  # noqa: E402


def _row(row_id: str, row_number: int, city: str, bank: str, social: str, ratio: str, company: str) -> DocumentTableRow:
    payload = {
        "省份": "测试省",
        "城市": city,
        "当前进度-1.银行账户是否开具完成": bank,
        "当前进度-2.社保公积金账户是否开具完成": social,
        "当前进度-3.公积金比例": ratio,
        "当前进度-4.开设公司名称": company,
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-branch-progress",
        sheet_name="Sheet1",
        row_number=row_number,
        row_key=f"Sheet1:{row_number}",
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
            id="doc-branch-progress",
            title="北仑分公司开设最新进度表0310",
            filename="北仑分公司开设最新进度表0310.xlsx",
            storage_path="fixture.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        db.add(user)
        db.add(doc)
        db.add_all(
            [
                _row("row-ok-1", 3, "宁波北仑", "是", "是", "5%+5%", "外服（浙江）企业服务有限公司"),
                _row("row-ok-2", 4, "北京", "是", "是", "5%+5%", "外服（浙江）企业服务有限公司北京分公司"),
                _row("row-social-no", 5, "运城", "是", "否", "5%+5%", "外服（浙江）企业服务有限公司运城分公司"),
                _row("row-no-ratio", 6, "大连", "是", "是", "", "外服（浙江）企业服务有限公司大连分公司"),
                _row("row-not-opened", 7, "贵阳", "否", "否", "", "未开设"),
            ]
        )
        db.commit()

        question = "北仑现在开设了多少家分公司，以银行账户、社保公积金账户、公积金比例和公司名称全部开设完成的为准来进行统计"
        contexts, meta = table_mode_contexts(db, question, user, top_k=10)
        data_rows = [item for item in contexts if not item.get("is_header")]
        row_ids = {str(item.get("table_row_id")) for item in data_rows}

        expected = {"row-ok-1", "row-ok-2"}
        if row_ids != expected:
            raise AssertionError(f"expected only {sorted(expected)}, got {sorted(row_ids)}; meta={meta}")
        if not meta.get("branch_completion_filter"):
            raise AssertionError(f"branch completion filter was not enabled: {meta}")
        if meta.get("branch_completion_matched_rows") != 2:
            raise AssertionError(f"expected 2 matched rows in meta, got {meta}")

        print("Table branch completion regression passed.")
    finally:
        db.close()
        engine.dispose()
        try:
            DB_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
