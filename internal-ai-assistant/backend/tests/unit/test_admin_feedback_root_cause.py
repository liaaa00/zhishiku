from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Feedback, User
from app.routers.admin_feedback import router as admin_feedback_router
from app.routers.deps import require_admin


def test_admin_feedback_review_persists_root_cause() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        db.add(Feedback(
            id="fb-root-cause",
            user_id="user-1",
            username="alice",
            rating="unhelpful",
            category="not_helpful",
            content="answer missed the source",
            question_snapshot="what is the policy?",
            answer_snapshot="old answer",
            sources_json="[]",
            status="new",
        ))
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_feedback_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True)

    client = TestClient(app)
    review = client.put("/api/admin/feedback/fb-root-cause", json={
        "status": "resolved",
        "admin_note": "retrieval missed the right document",
        "root_cause": "retrieval_miss",
    })
    assert review.status_code == 200
    assert review.json()["root_cause"] == "retrieval_miss"

    detail = client.get("/api/admin/feedback/fb-root-cause")
    assert detail.status_code == 200
    assert detail.json()["root_cause"] == "retrieval_miss"

    filtered = client.get("/api/admin/feedback", params={"root_cause": "retrieval_miss"})
    assert filtered.status_code == 200
    assert any(item["id"] == "fb-root-cause" for item in filtered.json())

    invalid = client.put("/api/admin/feedback/fb-root-cause", json={"status": "reviewed", "root_cause": "bad_value"})
    assert invalid.status_code == 400
