"""Regression for Alembic migration bootstrapping.

Run from internal-ai-assistant/backend:
    python tests/qa_alembic_regression.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_alembic_regression.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()


def run_alembic(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def require_success(result: subprocess.CompletedProcess[str], label: str) -> None:
    if result.returncode != 0:
        raise AssertionError(
            f"{label} failed with exit code {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )


def main() -> None:
    upgrade = run_alembic("upgrade", "head")
    require_success(upgrade, "alembic upgrade head")

    # Import after Alembic has created the database file so the application uses the same URL.
    os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
    from sqlalchemy import create_engine, inspect

    engine = create_engine(os.environ["DATABASE_URL"])
    tables = set(inspect(engine).get_table_names())
    expected = {
        "alembic_version",
        "audit_logs",
        "background_tasks",
        "chat_messages",
        "chat_sessions",
        "document_chunks",
        "document_group_link",
        "document_page_indexes",
        "document_processing_status",
        "document_table_rows",
        "documents",
        "feedback",
        "groups",
        "settings",
        "table_schema_aliases",
        "user_group_link",
        "users",
    }
    missing = expected - tables
    if missing:
        raise AssertionError(f"Alembic-created database is missing tables: {sorted(missing)}; got {sorted(tables)}")

    check = run_alembic("check")
    require_success(check, "alembic check")
    if "No new upgrade operations detected" not in (check.stdout + check.stderr):
        raise AssertionError(f"alembic check did not confirm schema parity:\nSTDOUT:\n{check.stdout}\nSTDERR:\n{check.stderr}")

    print("Alembic migration regression passed.")


if __name__ == "__main__":
    main()
