from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..citation_utils import bounded_limit
from ..database import get_db
from ..models import BackgroundTask, DocumentProcessingStatus, User
from .deps import audit, require_admin

router = APIRouter()


@router.get("/api/admin/tasks")
def list_tasks(limit: int = Query(500, ge=1, le=500), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    row_limit = bounded_limit(limit, 500, 500)
    rows = db.execute(
        select(BackgroundTask).options(selectinload(BackgroundTask.document)).order_by(BackgroundTask.created_at.desc()).limit(row_limit)
    ).scalars().all()
    status_by_doc = {
        item.document_id: item
        for item in db.execute(select(DocumentProcessingStatus)).scalars().all()
    }
    return [
        {
            "id": t.id,
            "task_type": t.task_type,
            "document_id": t.document_id,
            "document_title": t.document.title if t.document else "",
            "document_filename": t.document.filename if t.document else "",
            "document_status": status_by_doc.get(t.document_id).status if t.document_id and status_by_doc.get(t.document_id) else "",
            "document_stage": status_by_doc.get(t.document_id).stage if t.document_id and status_by_doc.get(t.document_id) else "",
            "document_message": status_by_doc.get(t.document_id).message if t.document_id and status_by_doc.get(t.document_id) else "",
            "status": t.status,
            "attempts": t.attempts,
            "last_error": t.last_error,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        }
        for t in rows
    ]


@router.post("/api/admin/tasks/{task_id}/retry")
def retry_task(task_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    task = db.get(BackgroundTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status == "running":
        raise HTTPException(status_code=400, detail="任务正在执行中")
    task.status = "pending"
    task.last_error = ""
    task.finished_at = None
    task.updated_at = datetime.utcnow()
    audit(db, actor, "task.retry", "task", task.id, {"document_id": task.document_id})
    db.commit()
    return {"ok": True}
