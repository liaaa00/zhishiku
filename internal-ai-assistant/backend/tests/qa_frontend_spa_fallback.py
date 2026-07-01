"""Regression for backend page routes preferring the built Vue SPA.

Run from internal-ai-assistant/backend:
    python tests/qa_frontend_spa_fallback.py
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_frontend_spa.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()

# Configure before importing application modules.
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["DEFAULT_ADMIN_USERNAME"] = "spa_admin"
os.environ["DEFAULT_ADMIN_PASSWORD"] = "spa_admin_password"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def require_status(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}: {response.text}")


def require_contains(response, needle: str, label: str) -> None:
    if needle not in response.text:
        raise AssertionError(f"{label}: expected response to contain {needle!r}, got: {response.text[:200]!r}")


def main() -> None:
    app_main = importlib.import_module("app.main")
    config = importlib.import_module("app.config")
    from fastapi.testclient import TestClient

    client = TestClient(app_main.app)
    original_dist_dir = config.FRONTEND_DIST_DIR
    original_main_dist_dir = app_main.FRONTEND_DIST_DIR

    try:
        with tempfile.TemporaryDirectory(prefix="qa_frontend_dist_") as tmp:
            dist_dir = Path(tmp)
            (dist_dir / "assets").mkdir()
            (dist_dir / "index.html").write_text(
                '<!doctype html><html><body><div id="app">SPA_INDEX_SENTINEL</div></body></html>',
                encoding="utf-8",
            )
            (dist_dir / "assets" / "app.js").write_text("console.log('ASSET_SENTINEL')", encoding="utf-8")
            app_main.FRONTEND_DIST_DIR = dist_dir

            for path in ("/login", "/chat", "/admin"):
                response = client.get(path)
                require_status(response, 200, f"{path} serves SPA index when built")
                require_contains(response, "SPA_INDEX_SENTINEL", f"{path} serves SPA index when built")

            asset_response = client.get("/assets/app.js")
            require_status(asset_response, 200, "built frontend asset")
            require_contains(asset_response, "ASSET_SENTINEL", "built frontend asset")

            for traversal_path in ("/assets/../index.html", "/assets/%2e%2e/index.html"):
                traversal_response = client.get(traversal_path)
                if traversal_response.status_code not in {404, 405}:
                    raise AssertionError(
                        "asset traversal should not serve files outside assets, "
                        f"got HTTP {traversal_response.status_code}: {traversal_response.text[:200]!r}"
                    )

        missing_dist = Path(tempfile.gettempdir()) / "qa_frontend_dist_missing"
        app_main.FRONTEND_DIST_DIR = missing_dist

        chat_response = client.get("/chat")
        require_status(chat_response, 200, "/chat fallback")
        require_contains(chat_response, "Internal Copilot", "/chat fallback keeps legacy HTML")

        admin_response = client.get("/admin")
        require_status(admin_response, 200, "/admin fallback")
        require_contains(admin_response, "Knowledge Admin", "/admin fallback keeps legacy HTML")

        login_response = client.get("/login", follow_redirects=False)
        require_status(login_response, 307, "/login fallback redirects to chat")
        if login_response.headers.get("location") != "/chat":
            raise AssertionError(f"/login fallback expected location /chat, got {login_response.headers.get('location')!r}")
    finally:
        config.FRONTEND_DIST_DIR = original_dist_dir
        app_main.FRONTEND_DIST_DIR = original_main_dist_dir

    print("qa_frontend_spa_fallback passed")


if __name__ == "__main__":
    main()
