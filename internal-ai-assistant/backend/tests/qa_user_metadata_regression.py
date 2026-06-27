"""Regression for user metadata minimization.

Run from internal-ai-assistant/backend:
    python tests/qa_user_metadata_regression.py
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_user_metadata.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["DEFAULT_ADMIN_USERNAME"] = "meta_admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "meta_admin_password"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def require_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")


def assert_user_payload_minimal(payload: dict) -> None:
    allowed = {"id", "username", "is_admin", "is_active", "groups"}
    leaked = set(payload) - allowed
    if leaked:
        raise AssertionError(f"user payload leaked unsupported metadata fields: {sorted(leaked)}; payload={payload}")
    if not isinstance(payload.get("groups"), list):
        raise AssertionError(f"user payload should expose groups as list only, got {payload}")


def main() -> None:
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
        admin = models.User(id="meta-admin", username="meta_admin", password_hash=security.hash_password("meta_admin_password"), is_admin=True, is_active=True)
        group = models.Group(id="meta-group", name="飞书部门A")
        db.add_all([admin, group])
        db.commit()
    finally:
        db.close()

    client = TestClient(app_main.app)
    login = client.post("/api/auth/login", json={"username": "meta_admin", "password": "meta_admin_password"})
    require_status(login, 200, "login")
    token = login.json()["token"]

    created = client.post(
        "/api/admin/users",
        headers=headers(token),
        json={"username": "ou_mock_user_001", "password": "StrongPass123", "is_admin": False, "group_ids": ["meta-group"]},
    )
    require_status(created, 200, "create user")
    assert_user_payload_minimal(created.json())

    users = client.get("/api/admin/users", headers=headers(token))
    require_status(users, 200, "list users")
    for item in users.json():
        assert_user_payload_minimal(item)

    print("User metadata minimization regression passed.")


if __name__ == "__main__":
    main()
