from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import User
from app.routers.auth import router as auth_router


def make_client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    app = FastAPI()
    app.include_router(auth_router)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), Session


def test_self_register_creates_inactive_non_admin_user() -> None:
    client, Session = make_client()

    resp = client.post("/api/auth/register", json={"username": "new.employee", "password": "register-pass-123"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["status"] == "pending_review"

    db = Session()
    try:
        user = db.execute(select(User).where(User.username == "new.employee")).scalar_one()
        assert user.is_admin is False
        assert user.is_active is False
        assert user.groups == []
    finally:
        db.close()

    login_resp = client.post("/api/auth/login", json={"username": "new.employee", "password": "register-pass-123"})
    assert login_resp.status_code == 403
    assert "停用" in login_resp.json()["detail"]


def test_self_register_rejects_duplicate_username_case_insensitive() -> None:
    client, _Session = make_client()

    first = client.post("/api/auth/register", json={"username": "CaseUser", "password": "register-pass-123"})
    assert first.status_code == 200

    duplicate = client.post("/api/auth/register", json={"username": "caseuser", "password": "register-pass-123"})
    assert duplicate.status_code == 400
    assert "已存在" in duplicate.json()["detail"]


def test_self_register_requires_strong_enough_password() -> None:
    client, _Session = make_client()

    resp = client.post("/api/auth/register", json={"username": "weak.user", "password": "short"})
    assert resp.status_code == 400
    assert "至少 8 位" in resp.json()["detail"]
