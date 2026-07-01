from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import Group, User
from app.routers.admin_users import router as admin_users_router
from app.routers.deps import require_admin
from app.security import hash_password


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash=hash_password("admin-pass-123"), is_admin=True, is_active=True, approval_status="approved")
        pending = User(id="pending-user", username="pending.user", password_hash=hash_password("user-pass-123"), is_admin=False, is_active=False, approval_status="pending")
        group = Group(id="group-1", name="HR")
        db.add_all([admin, pending, group])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_users_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True, approval_status="approved")
    return TestClient(app), Session


def test_admin_can_approve_pending_user_with_groups() -> None:
    client, Session = make_client()

    resp = client.post("/api/admin/users/pending-user/approval", json={
        "action": "approve",
        "note": "verified",
        "group_ids": ["group-1"],
        "is_admin": False,
    })

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["is_active"] is True
    assert payload["approval_status"] == "approved"
    assert payload["approval_note"] == "verified"
    assert payload["groups"] == [{"id": "group-1", "name": "HR"}]

    db = Session()
    try:
        user = db.execute(select(User).where(User.id == "pending-user")).scalar_one()
        assert user.is_active is True
        assert user.approval_status == "approved"
        assert user.approved_by_username == "admin"
        assert [group.id for group in user.groups] == ["group-1"]
    finally:
        db.close()


def test_admin_can_reject_pending_user_and_keep_disabled() -> None:
    client, Session = make_client()

    resp = client.post("/api/admin/users/pending-user/approval", json={"action": "reject", "note": "not employee"})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["is_active"] is False
    assert payload["approval_status"] == "rejected"
    assert payload["approval_note"] == "not employee"
    assert payload["groups"] == []

    db = Session()
    try:
        user = db.get(User, "pending-user")
        assert user is not None
        assert user.is_active is False
        assert user.approval_status == "rejected"
        assert user.groups == []
    finally:
        db.close()
