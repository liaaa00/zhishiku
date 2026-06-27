from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import TableSchemaAlias, User
from .table_schema import ColumnSemanticMatch, SEMANTIC_LABELS, unique_clean_values

CONFIRMED_STATUS = "confirmed"
IGNORED_STATUS = "ignored"
ALLOWED_STATUSES = {CONFIRMED_STATUS, IGNORED_STATUS}


def schema_suggestion_key(document_id: str, sheet_name: str, semantic_name: str, raw_name: str) -> str:
    return ":".join(part for part in [document_id, sheet_name, semantic_name, raw_name] if part)


def _json_list(value: str) -> list[Any]:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def serialize_table_schema_alias(item: TableSchemaAlias) -> dict[str, Any]:
    return {
        "id": item.id,
        "document_id": item.document_id,
        "sheet_name": item.sheet_name or "",
        "raw_name": item.raw_name or "",
        "semantic_name": item.semantic_name or "",
        "label": SEMANTIC_LABELS.get(item.semantic_name, item.semantic_name),
        "status": item.status or CONFIRMED_STATUS,
        "confidence": item.confidence or 0.0,
        "suggestion_key": item.suggestion_key or schema_suggestion_key(item.document_id, item.sheet_name or "", item.semantic_name or "", item.raw_name or ""),
        "action": "map_column_alias",
        "reasons": _json_list(item.reasons_json),
        "samples": _json_list(item.samples_json),
        "created_by": item.created_by,
        "updated_by": item.updated_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def load_table_schema_aliases(
    db: Session,
    document_ids: Iterable[str] | None = None,
    *,
    status: str | None = None,
) -> list[TableSchemaAlias]:
    stmt = select(TableSchemaAlias)
    ids = [str(item) for item in (document_ids or []) if item]
    if ids:
        stmt = stmt.where(TableSchemaAlias.document_id.in_(ids))
    if status:
        stmt = stmt.where(TableSchemaAlias.status == status)
    return list(db.execute(stmt.order_by(TableSchemaAlias.updated_at.desc())).scalars().all())


def alias_status_lookup(aliases: Iterable[TableSchemaAlias]) -> dict[tuple[str, str, str, str], TableSchemaAlias]:
    result: dict[tuple[str, str, str, str], TableSchemaAlias] = {}
    for item in aliases:
        result[(item.document_id or "", item.sheet_name or "", item.semantic_name or "", item.raw_name or "")] = item
        # Sheet names are optional in the first MVP suggestions. Only sheet-empty aliases act as document-wide fallback.
        if not (item.sheet_name or ""):
            result[(item.document_id or "", "", item.semantic_name or "", item.raw_name or "")] = item
    return result


def apply_confirmed_schema_aliases(
    semantic_map: dict[str, ColumnSemanticMatch],
    aliases: Iterable[TableSchemaAlias],
    rows: Iterable[dict[str, Any]],
) -> dict[str, ColumnSemanticMatch]:
    result = dict(semantic_map or {})
    rows_list = [row for row in rows if isinstance(row, dict)]
    for alias in aliases:
        if alias.status != CONFIRMED_STATUS:
            continue
        raw_name = alias.raw_name or ""
        semantic_name = alias.semantic_name or ""
        if not raw_name or not semantic_name:
            continue
        values = [row.get(raw_name) for row in rows_list if raw_name in row]
        if not values and rows_list:
            # Do not force a mapping if the confirmed column no longer exists in this document.
            continue
        samples = unique_clean_values(values, limit=8)
        confidence = max(float(alias.confidence or 0.0), 9.0)
        result[semantic_name] = ColumnSemanticMatch(
            raw_name=raw_name,
            semantic_name=semantic_name,
            score=round(confidence, 4),
            reasons=["人工确认映射"],
            samples=samples or _json_list(alias.samples_json)[:8],
        )
    return result


def merge_schema_suggestion_status(
    suggestions: list[dict[str, Any]],
    aliases: Iterable[TableSchemaAlias],
) -> list[dict[str, Any]]:
    lookup = alias_status_lookup(aliases)
    merged: list[dict[str, Any]] = []
    for item in suggestions:
        key = (
            str(item.get("document_id") or ""),
            str(item.get("sheet_name") or ""),
            str(item.get("semantic_name") or ""),
            str(item.get("raw_name") or ""),
        )
        alias = lookup.get(key) or lookup.get((key[0], "", key[2], key[3]))
        if alias and alias.status == IGNORED_STATUS:
            continue
        enriched = dict(item)
        if alias:
            enriched.update(
                {
                    "id": alias.id,
                    "status": alias.status,
                    "suggestion_key": alias.suggestion_key or enriched.get("suggestion_key"),
                    "confirmed": alias.status == CONFIRMED_STATUS,
                    "updated_at": alias.updated_at.isoformat() if alias.updated_at else None,
                }
            )
        merged.append(enriched)
    return merged


def upsert_table_schema_alias(
    db: Session,
    *,
    document_id: str,
    sheet_name: str,
    raw_name: str,
    semantic_name: str,
    status: str,
    actor: User,
    suggestion_key: str = "",
    confidence: float = 0.0,
    reasons: list[str] | None = None,
    samples: list[str] | None = None,
) -> TableSchemaAlias:
    document_id = (document_id or "").strip()
    sheet_name = (sheet_name or "").strip()
    raw_name = (raw_name or "").strip()
    semantic_name = (semantic_name or "").strip()
    status = (status or "").strip().lower()
    if status not in ALLOWED_STATUSES:
        raise ValueError("invalid_status")
    if not document_id or not raw_name or not semantic_name:
        raise ValueError("missing_required_fields")
    suggestion_key = (suggestion_key or schema_suggestion_key(document_id, sheet_name, semantic_name, raw_name)).strip()
    existing = db.execute(
        select(TableSchemaAlias).where(
            TableSchemaAlias.document_id == document_id,
            TableSchemaAlias.sheet_name == sheet_name,
            TableSchemaAlias.raw_name == raw_name,
            TableSchemaAlias.semantic_name == semantic_name,
        )
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if existing:
        item = existing
    else:
        item = TableSchemaAlias(
            id=str(uuid.uuid4()),
            document_id=document_id,
            sheet_name=sheet_name,
            raw_name=raw_name,
            semantic_name=semantic_name,
            created_by=actor.id,
            created_at=now,
        )
        db.add(item)
    item.status = status
    item.confidence = float(confidence or 0.0)
    item.suggestion_key = suggestion_key
    item.reasons_json = json.dumps(reasons or [], ensure_ascii=False)
    item.samples_json = json.dumps(samples or [], ensure_ascii=False)
    item.updated_by = actor.id
    item.updated_at = now
    return item
