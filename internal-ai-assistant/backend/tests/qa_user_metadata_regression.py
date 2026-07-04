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
    allowed = {
        "id",
        "username",
        "is_admin",
        "is_active",
        "approval_status",
        "approval_note",
        "approved_by_username",
        "approved_at",
        "groups",
    }
    leaked = set(payload) - allowed
    if leaked:
        raise AssertionError(f"user payload leaked unsupported metadata fields: {sorted(leaked)}; payload={payload}")
    if not isinstance(payload.get("groups"), list):
        raise AssertionError(f"user payload should expose groups as list only, got {payload}")
    if "approval_status" in payload and payload["approval_status"] not in {"pending", "approved", "rejected"}:
        raise AssertionError(f"user payload exposed invalid approval_status: {payload}")


def assert_openapi_response_schema(openapi: dict, method: str, path: str) -> None:
    operation = openapi.get("paths", {}).get(path, {}).get(method.lower())
    if not operation:
        raise AssertionError(f"OpenAPI operation missing for {method} {path}")
    schema = operation.get("responses", {}).get("200", {}).get("content", {}).get("application/json", {}).get("schema")
    if not schema:
        raise AssertionError(f"OpenAPI response schema missing for {method} {path}: {operation}")


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

    groups = client.get("/api/admin/groups", headers=headers(token))
    require_status(groups, 200, "list groups")
    for group_payload in groups.json():
        if set(group_payload) != {"id", "name"}:
            raise AssertionError(f"group payload should only contain id/name, got {group_payload}")

    openapi = client.get("/openapi.json").json()
    for method, path in [
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/refresh"),
        ("GET", "/api/me"),
        ("GET", "/api/admin/users"),
        ("POST", "/api/admin/users"),
        ("PUT", "/api/admin/users/{user_id}"),
        ("GET", "/api/admin/groups"),
        ("POST", "/api/admin/groups"),
        ("PUT", "/api/admin/groups/{group_id}"),
    ]:
        assert_openapi_response_schema(openapi, method, path)

    print("User metadata minimization regression passed.")


if __name__ == "__main__":
    main()
