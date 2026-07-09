"""Copy the local SQLite application database into PostgreSQL.

Run from ``backend`` after the PostgreSQL service is reachable:

    python scripts/migrate_sqlite_to_postgres.py --drop-target --reset-target

The script uses the SQLAlchemy model metadata as the target schema, so it is
intended for the current application schema rather than historical Alembic state.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, delete, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.config import DATABASE_URL
from app.database import Base
from app import models  # noqa: F401 - register all model tables

DEFAULT_SQLITE_PATH = ROOT / "data" / "app.db"


def _table_order() -> list[str]:
    return [table.name for table in Base.metadata.sorted_tables]


def _connect_sqlite(path: Path) -> Engine:
    if not path.exists():
        raise SystemExit(f"SQLite database not found: {path}")
    return create_engine(f"sqlite:///{path.as_posix()}")


def _connect_postgres(url: str) -> Engine:
    if not (url.startswith("postgresql://") or url.startswith("postgresql+")):
        raise SystemExit("Target DATABASE_URL must be PostgreSQL for this migration")
    return create_engine(url, pool_pre_ping=True)


def _source_ids(source: Engine, table_name: str) -> set[str]:
    table = Base.metadata.tables[table_name]
    with Session(source) as db:
        return {str(row[0]) for row in db.execute(select(table.c.id)).all() if row[0] is not None}


def _sanitize_nullable_foreign_keys(source: Engine, table_name: str, rows: list[dict]) -> None:
    if table_name in {"audit_logs", "documents", "background_tasks", "chat_sessions", "feedback", "table_schema_aliases"}:
        user_ids = _source_ids(source, "users")
        for row in rows:
            for key in ("actor_user_id", "created_by", "user_id", "handled_by_user_id", "updated_by"):
                if key in row and row[key] is not None and str(row[key]) not in user_ids:
                    row[key] = None
    if table_name == "feedback":
        session_ids = _source_ids(source, "chat_sessions")
        message_ids = _source_ids(source, "chat_messages")
        for row in rows:
            if row.get("session_id") is not None and str(row["session_id"]) not in session_ids:
                row["session_id"] = None
            if row.get("message_id") is not None and str(row["message_id"]) not in message_ids:
                row["message_id"] = None
    if table_name == "document_chunks":
        document_ids = _source_ids(source, "documents")
        rows[:] = [row for row in rows if str(row.get("document_id")) in document_ids]


def _row_dicts(source: Engine, table_name: str) -> list[dict]:
    table = Base.metadata.tables[table_name]
    with Session(source) as db:
        rows = [dict(row) for row in db.execute(select(table)).mappings().all()]
    _sanitize_nullable_foreign_keys(source, table_name, rows)
    return rows


def _clear_target(target: Engine, table_names: Iterable[str]) -> None:
    with target.begin() as conn:
        for table_name in reversed(list(table_names)):
            conn.execute(delete(Base.metadata.tables[table_name]))


def _copy_rows(source: Engine, target: Engine, table_names: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with target.begin() as conn:
        for table_name in table_names:
            table = Base.metadata.tables[table_name]
            rows = _row_dicts(source, table_name)
            counts[table_name] = len(rows)
            if rows:
                conn.execute(table.insert(), rows)
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite app.db into PostgreSQL")
    parser.add_argument("--sqlite-path", default=str(DEFAULT_SQLITE_PATH), help="Path to the source SQLite database")
    parser.add_argument("--postgres-url", default=os.getenv("POSTGRES_DATABASE_URL") or DATABASE_URL, help="Target PostgreSQL SQLAlchemy URL")
    parser.add_argument("--reset-target", action="store_true", help="Delete existing PostgreSQL rows before copying")
    parser.add_argument("--drop-target", action="store_true", help="Drop and recreate PostgreSQL tables before copying")
    args = parser.parse_args()

    source = _connect_sqlite(Path(args.sqlite_path))
    target = _connect_postgres(args.postgres_url)
    table_names = _table_order()

    if args.drop_target:
        Base.metadata.drop_all(bind=target)
    Base.metadata.create_all(bind=target)
    if args.reset_target:
        _clear_target(target, table_names)
    counts = _copy_rows(source, target, table_names)

    print({
        "ok": True,
        "source": str(Path(args.sqlite_path).resolve()),
        "target": args.postgres_url.split("@")[0] + "@***" if "@" in args.postgres_url else args.postgres_url,
        "table_count": len(table_names),
        "row_count": sum(counts.values()),
        "tables": counts,
    })


if __name__ == "__main__":
    main()