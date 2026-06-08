"""Final QA regression for integration worktree.

Run from internal-ai-assistant/backend:
    python tests/qa_final_regression.py

The script records whether the accepted integration commit satisfies:
- chat citations include message_id, sources/citations, view_url, content_url;
- unrelated accessible knowledge refuses/no-hit and returns no unrelated citations;
- document content/view enforce auth, permissions, chunk lookup, and storage_path safety;
- feedback with rating=user_feedback is accepted (required by previous QA blocker);
- feedback with a currently accepted rating can be listed, detailed, and reviewed by admin.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "qa_final_regression.sqlite3"

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["DEFAULT_ADMIN_USERNAME"] = "qa_admin_final"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "qa_admin_password"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_final_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def require_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")


def assert_no_hit(payload: dict, label: str) -> None:
    if payload.get("source_count") != 0:
        raise AssertionError(f"{label}: expected source_count=0, got {payload.get('source_count')} sources={payload.get('sources')}")
    if payload.get("sources") or payload.get("citations"):
        raise AssertionError(f"{label}: expected no sources/citations, got sources={payload.get('sources')} citations={payload.get('citations')}")


def main() -> None:
    reset_storage()

    app_main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    security = importlib.import_module("app.security")
    from fastapi.testclient import TestClient

    def fake_chat_answer(question, contexts, api_key=None, base_url=None, model=None):
        joined = " | ".join(c.get("content", "") for c in contexts)
        return f"grounded answer for {question}: {joined[:120]}"

    app_main.chat_answer = fake_chat_answer

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    app_main.ensure_runtime_schema()

    db = database.SessionLocal()
    try:
        admin = models.User(id="qa-final-admin", username="qa_admin_final", password_hash=security.hash_password("qa_admin_password"), is_admin=True, is_active=True)
        employee = models.User(id="qa-final-user-1", username="qa_final_user_1", password_hash=security.hash_password("qa_user_password"), is_admin=False, is_active=True)
        outsider = models.User(id="qa-final-user-2", username="qa_final_user_2", password_hash=security.hash_password("qa_user_password"), is_admin=False, is_active=True)
        group = models.Group(id="qa-final-group", name="QA Final Group")
        employee.groups.append(group)
        db.add_all([admin, employee, outsider, group])

        allowed_file = UPLOAD_DIR / "qa_final_policy.txt"
        allowed_file.write_text("Expense reimbursements require invoice approval and manager sign-off.", encoding="utf-8")
        allowed_doc = models.Document(id="qa-final-doc-allowed", title="QA Final Policy", filename="qa_final_policy.txt", storage_path=str(allowed_file), source_type="txt", created_by=admin.id)
        allowed_doc.groups.append(group)
        db.add(allowed_doc)
        db.flush()
        allowed_chunk = models.DocumentChunk(
            id="qa-final-chunk-allowed",
            document_id=allowed_doc.id,
            page_number=1,
            chunk_index=0,
            content="Expense reimbursements require invoice approval and manager sign-off.",
            embedding_json=json.dumps(app_main.embed_texts(["expense invoice approval manager sign-off"])[0]),
        )
        db.add(allowed_chunk)

        outside_file = Path(tempfile.gettempdir()) / "qa_final_outside_upload_root.txt"
        outside_file.write_text("outside upload root", encoding="utf-8")
        outside_doc = models.Document(id="qa-final-doc-outside", title="Outside File", filename="qa_final_outside_upload_root.txt", storage_path=str(outside_file), source_type="txt", created_by=admin.id)
        outside_doc.groups.append(group)
        db.add(outside_doc)
        db.commit()
    finally:
        db.close()

    client = TestClient(app_main.app)

    admin_login = client.post("/api/auth/login", json={"username": "qa_admin_final", "password": "qa_admin_password"})
    require_status(admin_login, 200, "admin login")
    admin_token = admin_login.json()["token"]
    employee_login = client.post("/api/auth/login", json={"username": "qa_final_user_1", "password": "qa_user_password"})
    require_status(employee_login, 200, "employee login")
    employee_token = employee_login.json()["token"]
    outsider_login = client.post("/api/auth/login", json={"username": "qa_final_user_2", "password": "qa_user_password"})
    require_status(outsider_login, 200, "outsider login")
    outsider_token = outsider_login.json()["token"]

    chat_hit = client.post("/api/chat", headers=headers(employee_token), json={"question": "expense invoice approval", "top_k": 5})
    require_status(chat_hit, 200, "knowledge-hit chat")
    hit = chat_hit.json()
    assert hit.get("message_id") and hit.get("assistant_message_id") == hit.get("message_id"), "chat should return message_id and assistant_message_id"
    assert hit.get("source_count") >= 1, "knowledge-hit chat should return sources"
    assert hit.get("sources") and hit.get("citations"), "chat should return sources/citations"
    source = hit["sources"][0]
    assert source.get("document_id") == "qa-final-doc-allowed", "source should reference allowed doc"
    assert source.get("view_url", "").startswith("/api/documents/qa-final-doc-allowed/view"), "source should include view_url"
    assert source.get("content_url", "").startswith("/api/documents/qa-final-doc-allowed/content"), "source should include content_url"

    history = client.get(f"/api/chat/sessions/{hit['session_id']}", headers=headers(employee_token))
    require_status(history, 200, "history fetch")
    assistant_messages = [m for m in history.json()["messages"] if m["role"] == "assistant"]
    assert assistant_messages and assistant_messages[-1].get("sources"), "history should preserve assistant sources"

    unrelated = client.post("/api/chat", headers=headers(employee_token), json={"question": "cafeteria menu tomorrow", "top_k": 5})
    require_status(unrelated, 200, "unrelated accessible-knowledge chat")
    assert_no_hit(unrelated.json(), "unrelated accessible-knowledge chat")

    no_permission = client.post("/api/chat", headers=headers(outsider_token), json={"question": "expense invoice approval", "top_k": 5})
    require_status(no_permission, 200, "no-permission chat")
    assert_no_hit(no_permission.json(), "no-permission chat")

    require_status(client.get("/api/documents/qa-final-doc-allowed/content"), 401, "content requires auth")
    content_ok = client.get("/api/documents/qa-final-doc-allowed/content?chunk_id=qa-final-chunk-allowed", headers=headers(employee_token))
    require_status(content_ok, 200, "content chunk authorized")
    content_json = content_ok.json()
    assert content_json.get("content") and content_json.get("chunks"), "content endpoint should return content and chunks"
    assert content_json["chunks"][0].get("chunk_id") == "qa-final-chunk-allowed", "content endpoint should return requested chunk"
    require_status(client.get("/api/documents/qa-final-doc-allowed/content?chunk_id=missing", headers=headers(employee_token)), 404, "missing chunk rejected")
    require_status(client.get("/api/documents/qa-final-doc-allowed/content", headers=headers(outsider_token)), 404, "content unauthorized user")

    view_ok = client.get("/api/documents/qa-final-doc-allowed/view?chunk_id=qa-final-chunk-allowed", headers=headers(employee_token))
    require_status(view_ok, 200, "view authorized")
    assert view_ok.headers.get("x-document-id") == "qa-final-doc-allowed", "view should include x-document-id"
    require_status(client.get("/api/documents/qa-final-doc-allowed/view", headers=headers(outsider_token)), 404, "view unauthorized user")
    require_status(client.get("/api/documents/qa-final-doc-outside/view", headers=headers(employee_token)), 403, "view outside upload root blocked")
    require_status(client.get("/api/documents/qa-final-doc-outside/content", headers=headers(employee_token)), 403, "content outside upload root blocked")

    empty_feedback = client.post("/api/chat/feedback", headers=headers(employee_token), json={"session_id": hit["session_id"], "message_id": hit["message_id"], "content": "   "})
    require_status(empty_feedback, 400, "empty feedback rejected")
    long_feedback = client.post("/api/chat/feedback", headers=headers(employee_token), json={"session_id": hit["session_id"], "message_id": hit["message_id"], "content": "x" * 2001})
    require_status(long_feedback, 400, "overlong feedback rejected")
    wrong_user_feedback = client.post("/api/chat/feedback", headers=headers(outsider_token), json={"session_id": hit["session_id"], "message_id": hit["message_id"], "content": "not mine"})
    require_status(wrong_user_feedback, 404, "wrong user feedback rejected")

    user_feedback_response = client.post(
        "/api/chat/feedback",
        headers=headers(employee_token),
        json={"session_id": hit["session_id"], "message_id": hit["message_id"], "rating": "user_feedback", "content": "Please cite exact section."},
    )
    if user_feedback_response.status_code != 200:
        print("BLOCKER rating=user_feedback response:", user_feedback_response.status_code, user_feedback_response.text)
        raise AssertionError("rating=user_feedback must not return 400/validation error")

    feedback_id = user_feedback_response.json()["id"]
    admin_list = client.get("/api/admin/feedback", headers=headers(admin_token))
    require_status(admin_list, 200, "admin feedback list")
    matched = next((item for item in admin_list.json() if item["id"] == feedback_id), None)
    assert matched, "admin list should include feedback"
    assert matched.get("question") and matched.get("answer") and matched.get("sources"), "feedback list should preserve question/answer/sources snapshots"

    admin_detail = client.get(f"/api/admin/feedback/{feedback_id}", headers=headers(admin_token))
    require_status(admin_detail, 200, "admin feedback detail")
    detail = admin_detail.json()
    assert detail.get("id") == feedback_id and detail.get("sources"), "feedback detail should include snapshots"

    review = client.put(f"/api/admin/feedback/{feedback_id}", headers=headers(admin_token), json={"status": "reviewed", "review_note": "QA final verified."})
    require_status(review, 200, "admin feedback review")
    assert review.json().get("status") == "reviewed", "review status should be reviewed"
    resolved = client.put(f"/api/admin/feedback/{feedback_id}", headers=headers(admin_token), json={"status": "resolved", "review_note": "Resolved."})
    require_status(resolved, 200, "admin feedback resolve")
    assert resolved.json().get("status") == "resolved", "review status should be resolved"

    print("QA final regression passed.")


if __name__ == "__main__":
    main()
