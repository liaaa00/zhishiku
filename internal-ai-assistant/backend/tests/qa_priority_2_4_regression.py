"""Focused regression for priority 2-4 backend upgrades.

Run from internal-ai-assistant/backend:
    python tests/qa_priority_2_4_regression.py

Checks:
- chat sources include grounding/highlight metadata;
- no-hit chats return grounded=false/no_sources=true and an explicit refusal message;
- file preview endpoint supports chunk-based metadata and cached auth response;
- feedback accepts category, persists admin review fields, and supports filterable admin list.
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
DB_PATH = DATA_DIR / "qa_priority_2_4_regression.sqlite3"

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["DEFAULT_ADMIN_USERNAME"] = "qa_admin_p24"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "qa_admin_password"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_p24_*"):
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

    def fake_chat_answer(question, contexts, api_key=None, base_url=None, model=None):
        joined = " | ".join(c.get("content", "") for c in contexts)
        return f"grounded: {question}: {joined[:120]}"

    app_main.chat_answer = fake_chat_answer

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    app_main.ensure_runtime_schema()

    db = database.SessionLocal()
    try:
        admin = models.User(id="qa-p24-admin", username="qa_admin_p24", password_hash=security.hash_password("qa_admin_password"), is_admin=True, is_active=True)
        user = models.User(id="qa-p24-user", username="qa_user_p24", password_hash=security.hash_password("qa_user_password"), is_admin=False, is_active=True)
        group = models.Group(id="qa-p24-group", name="QA P24 Group")
        user.groups.append(group)
        db.add_all([admin, user, group])

        doc_file = UPLOAD_DIR / "qa_p24_policy.txt"
        doc_file.write_text("Expense reimbursements require invoice approval and manager sign-off.", encoding="utf-8")
        doc = models.Document(id="qa-p24-doc", title="QA P24 Policy", filename="qa_p24_policy.txt", storage_path=str(doc_file), source_type="txt", created_by=admin.id)
        doc.groups.append(group)
        db.add(doc)
        db.flush()
        db.add(models.DocumentChunk(id="qa-p24-chunk", document_id=doc.id, page_number=1, chunk_index=0, content="Expense reimbursements require invoice approval and manager sign-off.", embedding_json=json.dumps(app_main.embed_texts(["expense invoice approval manager sign-off"])[0])))
        db.commit()
    finally:
        db.close()

    client = TestClient(app_main.app)
    admin_login = client.post("/api/auth/login", json={"username": "qa_admin_p24", "password": "qa_admin_password"})
    require_status(admin_login, 200, "admin login")
    admin_token = admin_login.json()["token"]
    user_login = client.post("/api/auth/login", json={"username": "qa_user_p24", "password": "qa_user_password"})
    require_status(user_login, 200, "user login")
    user_token = user_login.json()["token"]

    hit = client.post("/api/chat", headers=headers(user_token), json={"question": "expense invoice approval", "top_k": 5})
    require_status(hit, 200, "knowledge hit chat")
    hit_json = hit.json()
    assert hit_json["grounded"] is True, hit_json
    assert hit_json["confidence"] is not None, hit_json
    assert hit_json["sources"] and hit_json["sources"][0].get("matched_snippet"), hit_json
    assert hit_json["sources"][0].get("match_reason"), hit_json
    assert hit_json["sources"][0].get("highlight_ranges") is not None, hit_json

    miss = client.post("/api/chat", headers=headers(user_token), json={"question": "cafeteria menu tomorrow", "top_k": 5})
    require_status(miss, 200, "no hit chat")
    miss_json = miss.json()
    assert miss_json["grounded"] is False, miss_json
    assert miss_json["no_sources"] is True, miss_json
    assert "未在知识库中找到依据" in miss_json["answer"], miss_json

    preview = client.get("/api/documents/qa-p24-doc/content?chunk_id=qa-p24-chunk&include_content=false", headers=headers(user_token))
    require_status(preview, 200, "preview content")
    preview_json = preview.json()
    assert preview.headers.get("cache-control") == "private, max-age=60", preview.headers
    assert preview_json["chunk_count"] == 1, preview_json
    assert preview_json["chunks"][0]["matched_snippet"], preview_json
    assert preview_json["chunks"][0]["highlight_html"], preview_json

    feedback = client.post(
        "/api/chat/feedback",
        headers=headers(user_token),
        json={"session_id": hit_json["session_id"], "message_id": hit_json["message_id"], "rating": "user_feedback", "category": "missing_source", "content": "Please cite the exact section."},
    )
    require_status(feedback, 200, "feedback submit")
    feedback_id = feedback.json()["id"]
    assert feedback.json()["category"] == "missing_source", feedback.json()

    review = client.put(f"/api/admin/feedback/{feedback_id}", headers=headers(admin_token), json={"status": "reviewed", "admin_note": "Checked and confirmed."})
    require_status(review, 200, "feedback review")
    assert review.json()["admin_note"] == "Checked and confirmed.", review.json()

    filtered = client.get("/api/admin/feedback?category=missing_source&status=reviewed&limit=10", headers=headers(admin_token))
    require_status(filtered, 200, "feedback filtered list")
    assert any(item["id"] == feedback_id for item in filtered.json()), filtered.json()

    print("Priority 2-4 regression passed.")


if __name__ == "__main__":
    main()
