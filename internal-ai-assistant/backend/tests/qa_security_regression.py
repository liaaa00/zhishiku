"""Regression for password hash migration and CORS allow-listing.

Run from internal-ai-assistant/backend:
    python tests/qa_security_regression.py
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_security.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()

# Configure before importing application modules.
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["DEFAULT_ADMIN_USERNAME"] = "security_admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "security_admin_password"
os.environ["CORS_ORIGINS"] = "http://localhost:8080,http://localhost:5174"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")


def require_header(response, name: str, expected: str | None, label: str) -> None:
    actual = response.headers.get(name)
    if actual != expected:
        raise AssertionError(f"{label}: expected {name}={expected!r}, got {actual!r}")


def main() -> None:
    app_main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    security = importlib.import_module("app.security")
    from fastapi.testclient import TestClient

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    app_main.ensure_runtime_schema()

    legacy_password = "legacy_password_123"
    legacy_hash = hashlib.sha256(legacy_password.encode("utf-8")).hexdigest()

    db = database.SessionLocal()
    try:
        legacy_user = models.User(
            id="security-legacy-admin",
            username="security_admin",
            password_hash=legacy_hash,
            is_admin=True,
            is_active=True,
        )
        bcrypt_user = models.User(
            id="security-bcrypt-user",
            username="security_bcrypt_user",
            password_hash=security.hash_password("bcrypt_password_123"),
            is_admin=False,
            is_active=True,
        )
        db.add_all([legacy_user, bcrypt_user])
        db.commit()
    finally:
        db.close()

    client = TestClient(app_main.app)

    legacy_login = client.post(
        "/api/auth/login",
        json={"username": "security_admin", "password": legacy_password},
    )
    require_status(legacy_login, 200, "legacy SHA256 login")

    db = database.SessionLocal()
    try:
        migrated = db.get(models.User, "security-legacy-admin")
        if migrated is None:
            raise AssertionError("legacy user missing after login")
        if security.is_legacy_hash(migrated.password_hash):
            raise AssertionError("legacy hash was not migrated after successful login")
        if not migrated.password_hash.startswith("$2"):
            raise AssertionError(f"migrated hash should be bcrypt-like, got {migrated.password_hash!r}")
        if not security.verify_password(legacy_password, migrated.password_hash):
            raise AssertionError("migrated bcrypt hash does not verify original password")
    finally:
        db.close()

    bcrypt_login = client.post(
        "/api/auth/login",
        json={"username": "security_bcrypt_user", "password": "bcrypt_password_123"},
    )
    require_status(bcrypt_login, 200, "bcrypt login")

    allowed_preflight = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET",
        },
    )
    require_status(allowed_preflight, 200, "allowed CORS preflight")
    require_header(allowed_preflight, "access-control-allow-origin", "http://localhost:5174", "allowed CORS origin")

    denied_preflight = client.options(
        "/api/health",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    require_status(denied_preflight, 400, "denied CORS preflight")
    require_header(denied_preflight, "access-control-allow-origin", None, "denied CORS origin")

    print("Security regression passed.")


if __name__ == "__main__":
    main()
