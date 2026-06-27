"""Regression for table schema alias confirmation/ignore flow.

Run from internal-ai-assistant/backend:
    python tests/qa_table_schema_aliases_regression.py
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_table_schema_aliases.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["DEFAULT_ADMIN_USERNAME"] = "schema_admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "schema_admin_password"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Document, DocumentTableRow, User  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.table_retrieval import table_mode_contexts  # noqa: E402


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")


def _row(row_id: str, row_number: int, city: str, company: str) -> DocumentTableRow:
    payload = {
        "区域": city,
        "网点主体": company,
        "是否启用": "有效",
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-schema-alias",
        sheet_name="新表",
        row_number=row_number,
        row_key=f"新表:{row_number}",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text=" | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=False,
    )


def main() -> None:
    app_main = importlib.import_module("app.main")
    from fastapi.testclient import TestClient

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app_main.ensure_runtime_schema()

    db = SessionLocal()
    try:
        admin = User(id="schema-admin", username="schema_admin", password_hash=hash_password("schema_admin_password"), is_admin=True, is_active=True)
        doc = Document(
            id="doc-schema-alias",
            title="schema alias fixture",
            filename="schema_alias_fixture.xlsx",
            storage_path="fixture.xlsx",
            source_type="xlsx",
            created_by=admin.id,
        )
        db.add_all([admin, doc, _row("alias-row-1", 2, "上海", "上海一号网点"), _row("alias-row-2", 3, "北京", "北京一号网点")])
        db.commit()

        contexts, meta = table_mode_contexts(db, "列出上海有效网点清单", admin, top_k=10)
        suggestions = meta.get("table_schema_suggestions", {}).get("doc-schema-alias") or []
        if not suggestions:
            raise AssertionError(f"expected initial schema suggestions, got {meta}")
        ignored_candidate = next((item for item in suggestions if item.get("semantic_name") == "status"), suggestions[0])
    finally:
        db.close()

    client = TestClient(app_main.app)
    login = client.post("/api/auth/login", json={"username": "schema_admin", "password": "schema_admin_password"})
    assert_status(login, 200, "login")
    headers = auth_headers(login.json()["token"])

    confirm_payload = {
        "document_id": "doc-schema-alias",
        "sheet_name": "",
        "raw_name": "网点主体",
        "semantic_name": "company",
        "suggestion_key": "doc-schema-alias:company:网点主体",
        "confidence": 12.0,
        "reasons": ["人工指定公司列"],
        "samples": ["上海一号网点"],
    }
    confirm = client.post("/api/admin/table-schema-aliases/confirm", json=confirm_payload, headers=headers)
    assert_status(confirm, 200, "confirm alias")
    confirmed = confirm.json().get("alias") or {}
    if confirmed.get("status") != "confirmed" or confirmed.get("raw_name") != "网点主体":
        raise AssertionError(f"confirm endpoint should persist confirmed alias, got {confirmed}")

    ignore = client.post("/api/admin/table-schema-aliases/ignore", json=ignored_candidate, headers=headers)
    assert_status(ignore, 200, "ignore alias")
    ignored = ignore.json().get("alias") or {}
    if ignored.get("status") != "ignored":
        raise AssertionError(f"ignore endpoint should persist ignored alias, got {ignored}")

    alias_list = client.get("/api/admin/table-schema-aliases", params={"document_id": "doc-schema-alias"}, headers=headers)
    assert_status(alias_list, 200, "list aliases")
    statuses = {(item.get("semantic_name"), item.get("raw_name")): item.get("status") for item in alias_list.json()}
    if statuses.get(("company", "网点主体")) != "confirmed":
        raise AssertionError(f"confirmed alias should be listed, got {alias_list.json()}")
    if statuses.get((ignored.get("semantic_name"), ignored.get("raw_name"))) != "ignored":
        raise AssertionError(f"ignored alias should be listed, got {alias_list.json()}")

    db = SessionLocal()
    try:
        admin = db.get(User, "schema-admin")
        contexts, meta = table_mode_contexts(db, "列出公司名称=上海一号网点的有效网点", admin, top_k=10)
        schema_entries = meta.get("table_schema", {}).get("doc-schema-alias") or []
        company_entry = next((item for item in schema_entries if item.get("semantic_name") == "company"), None)
        if not company_entry or company_entry.get("raw_name") != "网点主体":
            raise AssertionError(f"confirmed alias should override inferred company mapping, got {schema_entries}")
        row_ids = {str(item.get("table_row_id")) for item in contexts if not item.get("is_header")}
        if "alias-row-1" not in row_ids:
            raise AssertionError(f"confirmed alias should participate in filters, got rows={row_ids}, meta={meta}")
        refreshed_suggestions = meta.get("table_schema_suggestions", {}).get("doc-schema-alias") or []
        ignored_pair = (ignored.get("semantic_name"), ignored.get("raw_name"))
        if any((item.get("semantic_name"), item.get("raw_name")) == ignored_pair for item in refreshed_suggestions):
            raise AssertionError(f"ignored suggestion should not be shown again, got {refreshed_suggestions}")
    finally:
        db.close()

    print("Table schema aliases regression passed.")


if __name__ == "__main__":
    main()
