from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..document_metadata import normalize_document_scope
from ..document_routing_config import (
    classify_document,
    default_document_routing_config,
    get_document_routing_config,
    set_document_routing_config,
)
from ..models import Document, User
from .deps import audit, require_admin

router = APIRouter()


class DocumentRoutingConfigPayload(BaseModel):
    config: dict[str, Any]


class ReclassifyPayload(BaseModel):
    knowledge_scope: str = "all"
    only_low_confidence: bool = False


def _document_kind_options(config: dict[str, Any]) -> list[dict[str, str]]:
    options = []
    for item in config.get("document_kinds", []):
        value = str(item.get("value") or "").strip()
        if not value or bool(item.get("disabled")):
            continue
        options.append({"value": value, "label": str(item.get("label") or value)})
    return options


@router.get("/api/admin/document-routing/config")
def get_routing_config(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    config = get_document_routing_config(db)
    return {"config": config, "document_kind_options": _document_kind_options(config)}


@router.put("/api/admin/document-routing/config")
def save_routing_config(req: DocumentRoutingConfigPayload, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    config = set_document_routing_config(db, req.config)
    audit(db, actor, "document_routing.config_update", "setting", "document_routing_rules", {"document_kind_count": len(config.get("document_kinds", [])), "route_rule_count": len(config.get("route_rules", []))})
    db.commit()
    return {"ok": True, "config": config, "document_kind_options": _document_kind_options(config)}


@router.post("/api/admin/document-routing/reset")
def reset_routing_config(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    config = set_document_routing_config(db, default_document_routing_config())
    audit(db, actor, "document_routing.config_reset", "setting", "document_routing_rules", {})
    db.commit()
    return {"ok": True, "config": config, "document_kind_options": _document_kind_options(config)}


@router.post("/api/admin/document-routing/reclassify")
def reclassify_documents(req: ReclassifyPayload, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    scope = normalize_document_scope(req.knowledge_scope, "all")
    query = select(Document).where(~Document.source_type.like("chat_%"))
    if scope != "all":
        query = query.where(Document.knowledge_scope == scope)
    if req.only_low_confidence:
        query = query.where(Document.document_kind_status.in_(["needs_review", "auto"]))
    docs = db.execute(query.order_by(Document.created_at.desc())).scalars().all()
    config = get_document_routing_config(db)
    threshold = float(config.get("classification", {}).get("low_confidence_threshold", 0.55) or 0.55)
    changed = 0
    needs_review = 0
    results = []
    for doc in docs:
        old_kind = str(doc.document_kind or "general")
        result = classify_document(db, doc)
        next_kind = str(result.get("kind") or "general")
        confidence = float(result.get("confidence") or 0.0)
        reason = "; ".join(str(item) for item in result.get("reasons") or [])[:1000]
        status = "needs_review" if confidence < threshold else "auto"
        if next_kind != old_kind:
            changed += 1
        if status == "needs_review":
            needs_review += 1
        doc.document_kind = next_kind
        doc.document_kind_confidence = confidence
        doc.document_kind_reason = reason
        doc.document_kind_status = status
        results.append({
            "id": doc.id,
            "title": doc.title,
            "filename": doc.filename,
            "old_kind": old_kind,
            "document_kind": next_kind,
            "confidence": confidence,
            "status": status,
            "reason": reason,
        })
    audit(db, actor, "document_routing.reclassify", "document", "bulk", {"scope": scope, "total": len(docs), "changed": changed, "needs_review": needs_review})
    db.commit()
    return {"ok": True, "scope": scope, "total": len(docs), "changed": changed, "needs_review": needs_review, "results": results[:200]}
