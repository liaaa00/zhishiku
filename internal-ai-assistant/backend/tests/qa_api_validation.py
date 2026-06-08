"""QA smoke/regression checks for knowledge citations, feedback, and file access.

This script is intentionally self-contained and does not require pytest. It uses an
isolated SQLite database and FastAPI TestClient so it can be run by reviewers/CI:

    cd internal-ai-assistant/backend
    python tests/qa_api_validation.py

It verifies the API contract that supports the front-end acceptance path:
- answers with matching knowledge return citations and persist citations in history;
- no accessible knowledge returns a refusal-style answer with no sources;
- citation file view is authenticated and blocks storage_path traversal;
- feedback rejects empty/overlong content, accepts valid feedback, and admin can review it;
- another user cannot access a private chat/feedback/file owned by the first user.
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
DB_PATH = DATA_DIR / "qa_validation.sqlite3"

# Configure before importing the application modules.
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["DEFAULT_ADMIN_USERNAME"] = "qa_admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "qa_admin_password"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def assert_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")


def main() -> None:
    reset_storage()

    app_main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    security = importlib.import_module("app.security")
    from fastapi.testclient import TestClient

    # Avoid external LLM/network calls. The chat route still performs real local retrieval.
    def fake_chat_answer(question, contexts, api_key=None, base_url=None, model=None):
        joined = " | ".join(c.get("content", "") for c in contexts)
        return f"基于知识库回答：{question}。引用内容：{joined[:120]}"

    app_main.chat_answer = fake_chat_answer

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    app_main.ensure_runtime_schema()

    db = database.SessionLocal()
    try:
        admin = models.User(
            id="qa-admin",
            username="qa_admin",
            password_hash=security.hash_password("qa_admin_password"),
            is_admin=True,
            is_active=True,
        )
        employee = models.User(
            id="qa-user-1",
            username="qa_user_1",
            password_hash=security.hash_password("qa_user_password"),
            is_admin=False,
            is_active=True,
        )
        outsider = models.User(
            id="qa-user-2",
            username="qa_user_2",
            password_hash=security.hash_password("qa_user_password"),
            is_admin=False,
            is_active=True,
        )
        group = models.Group(id="qa-group", name="QA knowledge group")
        employee.groups.append(group)
        db.add_all([admin, employee, outsider, group])

        allowed_file = UPLOAD_DIR / "qa_policy.txt"
        allowed_file.write_text("QA policy: expense reimbursements require invoice approval and manager sign-off.", encoding="utf-8")
        allowed_doc = models.Document(
            id="qa-doc-allowed",
            title="QA Policy",
            filename="qa_policy.txt",
            storage_path=str(allowed_file),
            source_type="txt",
            created_by=admin.id,
        )
        allowed_doc.groups.append(group)
        db.add(allowed_doc)
        db.flush()
        allowed_chunk = models.DocumentChunk(
            id="qa-chunk-allowed",
            document_id=allowed_doc.id,
            page_number=1,
            chunk_index=0,
            content="Expense reimbursements require invoice approval and manager sign-off.",
            embedding_json=json.dumps(app_main.embed_texts(["expense invoice approval manager sign-off"])[0]),
        )
        db.add(allowed_chunk)

        blocked_file = Path(tempfile.gettempdir()) / "qa_outside_upload_root.txt"
        blocked_file.write_text("outside upload root", encoding="utf-8")
        blocked_doc = models.Document(
            id="qa-doc-traversal",
            title="Traversal Target",
            filename="qa_outside_upload_root.txt",
            storage_path=str(blocked_file),
            source_type="txt",
            created_by=admin.id,
        )
        blocked_doc.groups.append(group)
        db.add(blocked_doc)
        db.commit()
    finally:
        db.close()

    client = TestClient(app_main.app)

    login_admin = client.post("/api/auth/login", json={"username": "qa_admin", "password": "qa_admin_password"})
    assert_status(login_admin, 200, "admin login")
    admin_token = login_admin.json()["token"]

    login_employee = client.post("/api/auth/login", json={"username": "qa_user_1", "password": "qa_user_password"})
    assert_status(login_employee, 200, "employee login")
    employee_token = login_employee.json()["token"]

    login_outsider = client.post("/api/auth/login", json={"username": "qa_user_2", "password": "qa_user_password"})
    assert_status(login_outsider, 200, "outsider login")
    outsider_token = login_outsider.json()["token"]

    # 1) Knowledge hit: answer must be grounded and include citation metadata.
    chat_hit = client.post(
        "/api/chat",
        headers=auth_headers(employee_token),
        json={"question": "How do expense reimbursements work?", "top_k": 5},
    )
    assert_status(chat_hit, 200, "knowledge-hit chat")
    chat_data = chat_hit.json()
    assert chat_data["source_count"] >= 1, "knowledge-hit chat should return at least one source"
    assert chat_data["sources"][0]["document_id"] == "qa-doc-allowed", "citation should identify source document"
    assert chat_data["sources"][0]["view_url"].startswith("/api/documents/qa-doc-allowed/view"), "citation should expose view_url"
    assert "基于知识库" in chat_data["answer"], "answer should be grounded by fake knowledge-only LLM"

    # 2) History preserves assistant citations.
    history = client.get(f"/api/chat/sessions/{chat_data['session_id']}", headers=auth_headers(employee_token))
    assert_status(history, 200, "history fetch")
    assistant_messages = [m for m in history.json()["messages"] if m["role"] == "assistant"]
    assert assistant_messages and assistant_messages[-1]["sources"], "history should preserve assistant citations"

    # 3) Citation file open/view requires auth and respects authorization.
    unauth_view = client.get("/api/documents/qa-doc-allowed/view")
    assert_status(unauth_view, 401, "unauthenticated citation view")
    view_ok = client.get("/api/documents/qa-doc-allowed/view?chunk_id=qa-chunk-allowed", headers=auth_headers(employee_token))
    assert_status(view_ok, 200, "authorized citation view")
    assert view_ok.headers.get("x-document-id") == "qa-doc-allowed", "view response should include document id header"
    outsider_view = client.get("/api/documents/qa-doc-allowed/view", headers=auth_headers(outsider_token))
    assert_status(outsider_view, 404, "unauthorized user citation view")

    # 4) Storage path traversal / outside upload root is blocked even for an otherwise authorized document.
    blocked_view = client.get("/api/documents/qa-doc-traversal/view", headers=auth_headers(employee_token))
    assert_status(blocked_view, 403, "outside upload root document view")

    # 5) Feedback validation and admin review path.
    empty_feedback = client.post(
        "/api/chat/feedback",
        headers=auth_headers(employee_token),
        json={"session_id": chat_data["session_id"], "message_id": chat_data["message_id"], "content": "   "},
    )
    assert_status(empty_feedback, 400, "empty feedback rejected")

    long_feedback = client.post(
        "/api/chat/feedback",
        headers=auth_headers(employee_token),
        json={"session_id": chat_data["session_id"], "message_id": chat_data["message_id"], "content": "x" * 2001},
    )
    assert_status(long_feedback, 400, "overlong feedback rejected")

    wrong_user_feedback = client.post(
        "/api/chat/feedback",
        headers=auth_headers(outsider_token),
        json={"session_id": chat_data["session_id"], "message_id": chat_data["message_id"], "content": "I should not submit this."},
    )
    assert_status(wrong_user_feedback, 404, "wrong user feedback rejected")

    accepted_feedback = client.post(
        "/api/chat/feedback",
        headers=auth_headers(employee_token),
        json={
            "session_id": chat_data["session_id"],
            "message_id": chat_data["message_id"],
            "rating": "user_feedback",
            "content": "Please cite the exact policy section next time.",
        },
    )
    assert_status(accepted_feedback, 200, "valid feedback accepted")
    feedback_id = accepted_feedback.json()["id"]

    admin_feedback = client.get("/api/admin/feedback", headers=auth_headers(admin_token))
    assert_status(admin_feedback, 200, "admin feedback list")
    feedback_items = admin_feedback.json()
    matched = next((item for item in feedback_items if item["id"] == feedback_id), None)
    assert matched, "admin feedback list should include submitted feedback"
    assert matched["question"], "feedback should include question snapshot"
    assert matched["answer"], "feedback should include answer snapshot"
    assert matched["sources"] and matched["sources"][0]["document_id"] == "qa-doc-allowed", "feedback should preserve citation snapshot"

    review = client.put(
        f"/api/admin/feedback/{feedback_id}",
        headers=auth_headers(admin_token),
        json={"status": "reviewed", "review_note": "QA verified."},
    )
    assert_status(review, 200, "admin feedback review")
    assert review.json()["status"] == "reviewed", "admin review should persist reviewed status"

    # 6) No-hit / no-permission chat: no citations and refusal-style answer.
    no_permission = client.post(
        "/api/chat",
        headers=auth_headers(outsider_token),
        json={"question": "How do expense reimbursements work?", "top_k": 5},
    )
    assert_status(no_permission, 200, "no-permission chat")
    no_permission_data = no_permission.json()
    assert no_permission_data["source_count"] == 0, "no-permission chat should not return sources"
    assert "未在知识库中找到依据" in no_permission_data["answer"], "no-permission answer should explain no accessible knowledge was found"

    # 7) No semantic hit despite having access: must not cite unrelated documents.
    unrelated = client.post(
        "/api/chat",
        headers=auth_headers(employee_token),
        json={"question": "What is the cafeteria menu tomorrow?", "top_k": 5},
    )
    assert_status(unrelated, 200, "unrelated accessible-knowledge chat")
    unrelated_data = unrelated.json()
    assert unrelated_data["source_count"] == 0, (
        "unrelated question should refuse/no-hit instead of returning citations; "
        f"got source_count={unrelated_data['source_count']} sources={unrelated_data.get('sources')}"
    )
    assert "未在知识库中找到依据" in unrelated_data["answer"], "unrelated no-hit answer should explain no related knowledge was found"

    print("QA API validation passed: 20 checks covering citations, history, feedback, file view, auth, no-hit refusal, semantic relevance, and input limits.")


if __name__ == "__main__":
    main()
