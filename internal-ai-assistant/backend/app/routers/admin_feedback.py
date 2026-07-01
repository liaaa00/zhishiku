import json
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..admin_schemas import FeedbackReview
from ..citation_utils import bounded_limit, snippet_text
from ..database import get_db
from ..models import AuditLog, Feedback, User
from .deps import audit, parse_json_list, require_admin

router = APIRouter()

FEEDBACK_STATUSES = {"new", "reviewed", "resolved", "ignored"}
FEEDBACK_CATEGORIES = {"incorrect", "missing_source", "not_helpful", "other"}
FEEDBACK_ROOT_CAUSES = {"", "answer_quality", "retrieval_miss", "insufficient_source", "document_quality", "permission_scope", "unclear_question", "other"}


class FeedbackBulkAction(BaseModel):
    ids: list[str]
    status: str = "reviewed"
    admin_note: str = ""
    root_cause: str = ""


def feedback_to_dict(f: Feedback, summary: bool = False) -> dict:
    sources = parse_json_list(f.sources_json)
    if summary:
        sources = sources[:2]
    review_note = getattr(f, "review_note", "") or ""
    admin_note = getattr(f, "admin_note", "") or review_note
    return {
        "id": f.id,
        "user_id": f.user_id,
        "username": f.username,
        "session_id": f.session_id,
        "message_id": f.message_id,
        "rating": f.rating,
        "category": getattr(f, "category", "other") or "other",
        "feedback_category": getattr(f, "category", "other") or "other",
        "content": snippet_text(f.content, 180) if summary else f.content,
        "question": snippet_text(f.question_snapshot, 220) if summary else f.question_snapshot,
        "answer": snippet_text(f.answer_snapshot, 260) if summary else f.answer_snapshot,
        "sources": sources,
        "citations": sources,
        "status": f.status,
        "created_at": f.created_at.isoformat() if f.created_at else None,
        "reviewed_at": f.reviewed_at.isoformat() if f.reviewed_at else None,
        "handled_at": getattr(f, "handled_at", None).isoformat() if getattr(f, "handled_at", None) else None,
        "handled_by_user_id": getattr(f, "handled_by_user_id", None),
        "handled_by_username": getattr(f, "handled_by_username", "") or "",
        "root_cause": getattr(f, "root_cause", "") or "",
        "review_note": snippet_text(review_note, 180) if summary else review_note,
        "admin_note": snippet_text(admin_note, 180) if summary else admin_note,
        "summary": summary,
    }


@router.get("/api/admin/feedback")
def list_feedback(
    status: Optional[str] = None,
    category: Optional[str] = None,
    rating: Optional[str] = None,
    root_cause: Optional[str] = None,
    search: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(300, ge=1, le=300),
    summary: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    status_filter = (status or "").strip().lower()
    category_filter = (category or "").strip().lower()
    rating_filter = (rating or "").strip().lower()
    root_cause_filter = (root_cause or "").strip().lower()
    search_filter = (search or "").strip()
    if status_filter and status_filter not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="反馈状态只能是 new/reviewed/resolved/ignored")
    if category_filter and category_filter not in FEEDBACK_CATEGORIES:
        raise HTTPException(status_code=400, detail="反馈分类只能是 incorrect/missing_source/not_helpful/other")
    if root_cause_filter and root_cause_filter not in FEEDBACK_ROOT_CAUSES:
        raise HTTPException(status_code=400, detail="反馈归因不合法")
    stmt = select(Feedback)
    if status_filter:
        stmt = stmt.where(Feedback.status == status_filter)
    if category_filter:
        stmt = stmt.where(Feedback.category == category_filter)
    if rating_filter:
        stmt = stmt.where(Feedback.rating == rating_filter)
    if root_cause_filter:
        stmt = stmt.where(Feedback.root_cause == root_cause_filter)
    if search_filter:
        like = f"%{search_filter}%"
        stmt = stmt.where(
            or_(
                Feedback.username.like(like),
                Feedback.user_id.like(like),
                Feedback.rating.like(like),
                Feedback.category.like(like),
                Feedback.root_cause.like(like),
                Feedback.content.like(like),
                Feedback.question_snapshot.like(like),
                Feedback.answer_snapshot.like(like),
                Feedback.review_note.like(like),
                Feedback.admin_note.like(like),
            )
        )
    if date_from:
        stmt = stmt.where(Feedback.created_at >= datetime.fromisoformat(date_from[:10]))
    if date_to:
        stmt = stmt.where(Feedback.created_at < datetime.combine(datetime.fromisoformat(date_to[:10]).date(), datetime.max.time()))
    row_limit = bounded_limit(limit, 300, 300)
    rows = db.execute(stmt.order_by(Feedback.created_at.desc()).limit(row_limit)).scalars().all()
    return [feedback_to_dict(f, summary=summary) for f in rows]


@router.get("/api/admin/feedback/{feedback_id}")
def get_feedback_detail(feedback_id: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    item = db.get(Feedback, feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    return feedback_to_dict(item)


@router.put("/api/admin/feedback/{feedback_id}")
def review_feedback(feedback_id: str, req: FeedbackReview, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    item = db.get(Feedback, feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    status = (req.status or "reviewed").strip().lower()
    if status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="反馈状态只能是 new/reviewed/resolved/ignored")
    admin_note = (req.admin_note or req.review_note or "").strip()[:1000]
    root_cause = (req.root_cause or "").strip().lower()
    if root_cause not in FEEDBACK_ROOT_CAUSES:
        raise HTTPException(status_code=400, detail="反馈归因不合法")
    item.status = status
    item.root_cause = root_cause
    item.review_note = admin_note
    item.admin_note = admin_note
    item.reviewed_at = datetime.utcnow()
    item.handled_by_user_id = actor.id
    item.handled_by_username = actor.username
    item.handled_at = datetime.utcnow()
    audit(db, actor, "feedback.review", "feedback", item.id, {"status": item.status, "admin_note": admin_note, "root_cause": root_cause})
    db.commit()
    return {"ok": True, "id": item.id, "status": item.status, "admin_note": admin_note, "root_cause": root_cause, "handled_by_username": actor.username}


@router.delete("/api/admin/feedback/{feedback_id}")
def delete_feedback(feedback_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    item = db.get(Feedback, feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    audit(db, actor, "feedback.delete", "feedback", item.id, {"username": item.username, "status": item.status, "category": item.category})
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/api/admin/feedback/bulk")
def bulk_feedback_action(req: FeedbackBulkAction, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    ids = list(dict.fromkeys(req.ids or []))
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要处理的反馈")
    status = (req.status or "reviewed").strip().lower()
    if status not in FEEDBACK_STATUSES:
        raise HTTPException(status_code=400, detail="反馈状态只能是 new/reviewed/resolved/ignored")
    admin_note = (req.admin_note or "").strip()[:1000]
    root_cause = (req.root_cause or "").strip().lower()
    if root_cause not in FEEDBACK_ROOT_CAUSES:
        raise HTTPException(status_code=400, detail="反馈归因不合法")
    rows = db.execute(select(Feedback).where(Feedback.id.in_(ids))).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="反馈不存在")
    updated = []
    now = datetime.utcnow()
    for item in rows:
        item.status = status
        item.root_cause = root_cause
        item.review_note = admin_note
        item.admin_note = admin_note
        item.reviewed_at = now
        item.handled_by_user_id = actor.id
        item.handled_by_username = actor.username
        item.handled_at = now
        updated.append(item.id)
    audit(db, actor, "feedback.bulk_update", "feedback", ",".join(updated), {"status": status, "count": len(updated), "admin_note": admin_note, "root_cause": root_cause})
    db.commit()
    return {"ok": True, "count": len(updated), "ids": updated, "status": status, "admin_note": admin_note, "root_cause": root_cause}


@router.get("/api/admin/audit-logs")
def list_audit_logs(limit: int = Query(300, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row_limit = bounded_limit(limit, 300, 500)
    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(row_limit)).scalars().all()
    return [
        {
            "id": r.id,
            "actor_username": r.actor_username,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "detail": json.loads(r.detail_json or "{}"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
