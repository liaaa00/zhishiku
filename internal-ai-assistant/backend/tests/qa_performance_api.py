"""Performance-focused API compatibility checks.

Run from internal-ai-assistant/backend:
    python tests/qa_performance_api.py

Covers backend support for the frontend chunk-splitting work:
- citation preview can be fetched in small, snippet-only payloads;
- preview/view responses include private cache headers and preserve auth checks;
- admin list endpoints can be limited/summarized for lazy-loaded admin tabs.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "qa_performance_api.sqlite3"

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["DEFAULT_ADMIN_USERNAME"] = "qa_perf_admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "qa_perf_password"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_perf_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def require_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")


def main() -> None:
    reset_storage()

    app_main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    security = importlib.import_module("app.security")
    from fastapi.testclient import TestClient

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    app_main.ensure_runtime_schema()

    db = database.SessionLocal()
    try:
        admin = models.User(
            id="qa-perf-admin",
            username="qa_perf_admin",
            password_hash=security.hash_password("qa_perf_password"),
            is_admin=True,
            is_active=True,
        )
        group = models.Group(id="qa-perf-group", name="QA Performance Group")
        db.add_all([admin, group])

        doc_file = UPLOAD_DIR / "qa_perf_policy.txt"
        doc_file.write_text("\n".join(f"Policy preview paragraph {i}" for i in range(12)), encoding="utf-8")
        doc = models.Document(
            id="qa-perf-doc",
            title="QA Performance Policy",
            filename="qa_perf_policy.txt",
            storage_path=str(doc_file),
            source_type="txt",
            created_by=admin.id,
        )
        doc.groups.append(group)
        db.add(doc)
        db.flush()
        status = models.DocumentProcessingStatus(
            document_id=doc.id,
            user_id=admin.id,
            status="ready",
            stage="indexed",
            message="ready",
            chunks=12,
            searchable=True,
        )
        db.add(status)
        for index in range(12):
            db.add(
                models.DocumentChunk(
                    id=f"qa-perf-chunk-{index}",
                    document_id=doc.id,
                    page_number=1,
                    chunk_index=index,
                    content=f"Policy preview paragraph {index}. This is chunk {index} with enough content for snippet testing.",
                    embedding_json=json.dumps(app_main.embed_texts([f"performance chunk {index}"])[0]),
                )
            )
        for index in range(5):
            db.add(
                models.Feedback(
                    id=f"qa-perf-feedback-{index}",
                    user_id=admin.id,
                    username=admin.username,
                    rating="user_feedback",
                    content="x" * 500,
                    question_snapshot="q" * 500,
                    answer_snapshot="a" * 700,
                    sources_json=json.dumps([{"document_id": doc.id, "content": "s" * 300} for _ in range(4)]),
                    status="new",
                )
            )
        for index in range(4):
            db.add(models.BackgroundTask(id=f"qa-perf-task-{index}", task_type="document_parse", document_id=doc.id, status="success"))
            db.add(models.AuditLog(id=f"qa-perf-audit-{index}", actor_user_id=admin.id, actor_username=admin.username, action="qa.action"))
        db.commit()
    finally:
        db.close()

    client = TestClient(app_main.app)
    login = client.post("/api/auth/login", json={"username": "qa_perf_admin", "password": "qa_perf_password"})
    require_status(login, 200, "admin login")
    token = login.json()["token"]

    preview = client.get("/api/documents/qa-perf-doc/content?limit=2&include_content=false", headers=headers(token))
    require_status(preview, 200, "limited snippet-only preview")
    payload = preview.json()
    assert payload["chunk_count"] == 2, payload
    assert payload["limit"] == 2, payload
    assert payload["content_included"] is False, payload
    assert payload["content"] == "", payload
    assert all(chunk["content"] == "" and chunk["snippet"] for chunk in payload["chunks"]), payload
    assert preview.headers.get("cache-control") == "private, max-age=60"
    assert preview.headers.get("vary") == "Authorization"

    view = client.get("/api/documents/qa-perf-doc/view?chunk_id=qa-perf-chunk-1", headers=headers(token))
    require_status(view, 200, "cached authenticated file view")
    assert view.headers.get("x-document-id") == "qa-perf-doc"
    assert view.headers.get("x-document-chunk-index") == "1"
    assert view.headers.get("cache-control") == "private, max-age=60"

    feedback = client.get("/api/admin/feedback?limit=2&summary=true", headers=headers(token))
    require_status(feedback, 200, "admin feedback limited summary")
    feedback_items = feedback.json()
    assert len(feedback_items) == 2, feedback_items
    assert all(item["summary"] is True for item in feedback_items), feedback_items
    assert all(len(item["answer"]) <= 260 and len(item["sources"]) <= 2 for item in feedback_items), feedback_items

    docs = client.get("/api/admin/documents?limit=1&summary=true", headers=headers(token))
    require_status(docs, 200, "admin documents summary")
    doc_items = docs.json()
    assert len(doc_items) == 1, doc_items
    assert doc_items[0]["groups"] == [] and doc_items[0]["groups_included"] is False, doc_items

    tasks = client.get("/api/admin/tasks?limit=2", headers=headers(token))
    require_status(tasks, 200, "admin tasks limited")
    assert len(tasks.json()) == 2, tasks.text

    audits = client.get("/api/admin/audit-logs?limit=2", headers=headers(token))
    require_status(audits, 200, "admin audit logs limited")
    assert len(audits.json()) == 2, audits.text

    print("QA performance API checks passed.")


if __name__ == "__main__":
    main()
