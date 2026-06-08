from datetime import datetime

from sqlalchemy.orm import Session

from .models import Document, DocumentProcessingStatus


def set_doc_status(
    db: Session,
    doc: Document,
    status: str,
    stage: str,
    message: str,
    chunks: int = 0,
    searchable: bool = False,
):
    item = None
    for obj in db.new:
        if isinstance(obj, DocumentProcessingStatus) and obj.document_id == doc.id:
            item = obj
            break
    if item is None:
        with db.no_autoflush:
            item = db.get(DocumentProcessingStatus, doc.id)
    if not item:
        item = DocumentProcessingStatus(document_id=doc.id, user_id=doc.created_by)
        db.add(item)
    item.status = status
    item.stage = stage
    item.message = message
    item.chunks = chunks
    item.searchable = searchable
    item.updated_at = datetime.utcnow()


def status_to_dict(item: DocumentProcessingStatus) -> dict:
    doc = item.document
    return {
        "document_id": item.document_id,
        "title": doc.title if doc else "未知文档",
        "filename": doc.filename if doc else "",
        "source_type": doc.source_type if doc else "",
        "status": item.status,
        "stage": item.stage,
        "message": item.message,
        "chunks": item.chunks,
        "searchable": item.searchable,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }
