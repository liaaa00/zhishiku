from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..admin_schemas import TableSchemaAliasAction
from ..database import get_db
from ..document_access import ensure_admin_document
from ..models import User
from ..table_schema_aliases import CONFIRMED_STATUS, IGNORED_STATUS, load_table_schema_aliases, serialize_table_schema_alias, upsert_table_schema_alias
from .deps import audit, require_admin

router = APIRouter()


def _save_alias_action(status: str, req: TableSchemaAliasAction, db: Session, actor: User):
    ensure_admin_document(db, req.document_id)
    try:
        item = upsert_table_schema_alias(
            db,
            document_id=req.document_id,
            sheet_name=req.sheet_name,
            raw_name=req.raw_name,
            semantic_name=req.semantic_name,
            status=status,
            actor=actor,
            suggestion_key=req.suggestion_key,
            confidence=req.confidence,
            reasons=req.reasons,
            samples=req.samples,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="schema 映射请求参数不完整或状态无效") from exc
    db.flush()
    audit(
        db,
        actor,
        f"table_schema.{status}",
        "table_schema_alias",
        item.id,
        {
            "document_id": item.document_id,
            "sheet_name": item.sheet_name,
            "raw_name": item.raw_name,
            "semantic_name": item.semantic_name,
            "confidence": item.confidence,
        },
    )
    db.commit()
    return {"ok": True, "alias": serialize_table_schema_alias(item)}


@router.get("/api/admin/table-schema-aliases")
def list_table_schema_aliases(
    document_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    normalized_status = (status or "").strip().lower() or None
    if normalized_status and normalized_status not in {CONFIRMED_STATUS, IGNORED_STATUS}:
        raise HTTPException(status_code=400, detail="status 只能是 confirmed/ignored")
    if document_id:
        ensure_admin_document(db, document_id)
    rows = load_table_schema_aliases(db, [document_id] if document_id else None, status=normalized_status)
    return [serialize_table_schema_alias(item) for item in rows]


@router.post("/api/admin/table-schema-aliases/confirm")
def confirm_table_schema_alias(req: TableSchemaAliasAction, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return _save_alias_action(CONFIRMED_STATUS, req, db, actor)


@router.post("/api/admin/table-schema-aliases/ignore")
def ignore_table_schema_alias(req: TableSchemaAliasAction, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    return _save_alias_action(IGNORED_STATUS, req, db, actor)
