from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..citation_utils import bounded_limit
from ..database import get_db
from ..document_quality import build_document_quality_report, list_document_quality_reports, report_needs_reparse
from ..document_status import set_doc_status
from ..models import BackgroundTask, Document, User
from ..task_service import enqueue_document_task
from ..upload_policy import KNOWLEDGE_FILE_EXTENSIONS
from .deps import audit, require_admin

router = APIRouter()


class QualityReparseRequest(BaseModel):
    document_ids: list[str] = []
    grades: list[str] = ["blocked", "poor"]
    limit: int = 100
    dry_run: bool = False


def _active_task_exists(db: Session, document_id: str) -> bool:
    return bool(
        db.execute(
            select(BackgroundTask.id).where(
                BackgroundTask.document_id == document_id,
                BackgroundTask.status.in_(["pending", "running"]),
            )
        ).first()
    )


@router.get("/api/admin/document-quality")
def list_document_quality(
    limit: int = Query(200, ge=1, le=1000),
    include_chat: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row_limit = bounded_limit(limit, 200, 1000)
    return list_document_quality_reports(db, limit=row_limit, include_chat=include_chat)


@router.get("/api/admin/documents/{document_id}/quality")
def get_document_quality(document_id: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    try:
        return build_document_quality_report(db, document_id)
    except ValueError as exc:
        if str(exc) == "document_not_found":
            raise HTTPException(status_code=404, detail="文档不存在") from exc
        raise


@router.post("/api/admin/document-quality/reparse")
def bulk_reparse_document_quality(req: QualityReparseRequest, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    row_limit = bounded_limit(req.limit, 1, 500)
    requested_ids = [str(doc_id).strip() for doc_id in req.document_ids if str(doc_id).strip()]
    target_grades = {str(grade).strip() for grade in req.grades if str(grade).strip()}

    if requested_ids:
        docs = db.execute(select(Document).where(Document.id.in_(requested_ids)).limit(row_limit)).scalars().all()
        reports = {doc.id: build_document_quality_report(db, doc.id) for doc in docs}
    else:
        all_reports = list_document_quality_reports(db, limit=row_limit, include_chat=False)["reports"]
        reports = {
            report["document"]["id"]: report
            for report in all_reports
            if not target_grades or report.get("quality", {}).get("grade") in target_grades
        }
        docs = db.execute(select(Document).where(Document.id.in_(reports.keys()))).scalars().all() if reports else []

    queued: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for doc in docs:
        report = reports.get(doc.id) or build_document_quality_report(db, doc.id)
        if not report_needs_reparse(report):
            skipped.append({"document_id": doc.id, "reason": "report_not_reparseable"})
            continue
        if _active_task_exists(db, doc.id):
            skipped.append({"document_id": doc.id, "reason": "task_pending"})
            continue
        if not Path(doc.storage_path).exists():
            set_doc_status(db, doc, "failed", "file_missing", "原始文件不存在，无法重新解析。", 0, False)
            skipped.append({"document_id": doc.id, "reason": "file_missing"})
            continue
        ext = Path(doc.filename or "").suffix.lower()
        if ext not in KNOWLEDGE_FILE_EXTENSIONS:
            skipped.append({"document_id": doc.id, "reason": "unsupported_file_type"})
            continue
        if req.dry_run:
            queued.append({"document_id": doc.id, "task_type": "document_reparse"})
            continue
        task = enqueue_document_task(db, doc, "document_reparse", actor)
        queued.append({"document_id": doc.id, "task_id": task.id, "task_type": task.task_type})
        audit(db, actor, "quality.bulk_reparse.enqueue", "document", doc.id, {"report_grade": report.get("quality", {}).get("grade")})

    if not req.dry_run:
        db.commit()
    return {
        "ok": True,
        "dry_run": req.dry_run,
        "limit": row_limit,
        "queued_count": len(queued),
        "skipped_count": len(skipped),
        "queued": queued,
        "skipped": skipped,
    }
