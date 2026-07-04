from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Document, DocumentProcessingStatus, Feedback, User
from app.routers.admin_evaluation import router as admin_evaluation_router
from app.routers.deps import require_admin
from app.security import hash_password


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash=hash_password("admin-pass-123"), is_admin=True, is_active=True, approval_status="approved")
        doc = Document(id="doc-1", title="Policy", filename="policy.txt", storage_path="/tmp/policy.txt", source_type="txt", created_by="admin")
        status = DocumentProcessingStatus(document_id="doc-1", user_id="admin", status="failed", stage="parse_error", searchable=False, message="parse failed")
        feedback = Feedback(id="fb-1", user_id="user-1", username="alice", rating="unhelpful", category="not_helpful", content="missed", status="new", root_cause="retrieval_miss")
        db.add_all([admin, doc, status, feedback])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_evaluation_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True, approval_status="approved")
    return TestClient(app)


def test_evaluation_overview_summarizes_feedback_documents_and_cases() -> None:
    client = make_client()

    resp = client.get("/api/admin/evaluation/overview")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["case_count"] >= 1
    assert payload["feedback"]["total"] == 1
    assert payload["feedback"]["new"] == 1
    assert payload["feedback"]["by_root_cause"]["retrieval_miss"] == 1
    assert payload["documents"]["total"] == 1
    assert payload["documents"]["failed"] == 1
    assert any("反馈" in item or "文档" in item for item in payload["risk_signals"])
    assert payload["automation_note"]


def test_admin_can_create_and_delete_custom_evaluation_case() -> None:
    client = make_client()

    create_resp = client.post(
        "/api/admin/evaluation/cases",
        json={"id": "custom-case-1", "category": "反馈沉淀", "question": "制度报销需要哪些材料？", "why": "来自用户反馈", "top_k": 6},
    )
    assert create_resp.status_code == 200
    created = create_resp.json()["case"]
    assert created["id"] == "custom-case-1"
    assert created["source"] == "custom"

    list_resp = client.get("/api/admin/evaluation/cases")
    assert list_resp.status_code == 200
    cases = list_resp.json()["cases"]
    assert any(item["id"] == "custom-case-1" and item["source"] == "custom" for item in cases)

    overview_resp = client.get("/api/admin/evaluation/overview")
    assert overview_resp.status_code == 200
    assert any(item["id"] == "custom-case-1" for item in overview_resp.json()["cases"])

    delete_resp = client.delete("/api/admin/evaluation/cases/custom-case-1")
    assert delete_resp.status_code == 200
    list_after = client.get("/api/admin/evaluation/cases").json()["cases"]
    assert not any(item["id"] == "custom-case-1" for item in list_after)
