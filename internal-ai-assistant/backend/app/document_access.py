from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .config import UPLOAD_DIR
from .models import BackgroundTask, Document, DocumentChunk, DocumentPageIndex, DocumentProcessingStatus, DocumentTableRow, GraphExtractionStatus, GraphMention, GraphRelation, TableSchemaAlias, document_group_link
from .pageindex_adapter import delete_pageindex_files
from .retrieval import has_document_access
from .vector_store import QdrantUnavailable, delete_document_vectors


def resolve_document_file_for_user(db: Session, document_id: str, user) -> tuple[Document, Path]:
    doc = db.get(Document, document_id)
    if not doc or not has_document_access(db, doc, user):
        raise HTTPException(status_code=404, detail="引用文件不存在或无权访问")
    try:
        upload_root = UPLOAD_DIR.resolve()
        file_path = Path(doc.storage_path).resolve()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="引用文件路径无效") from exc
    if upload_root != file_path and upload_root not in file_path.parents:
        raise HTTPException(status_code=403, detail="引用文件路径不允许访问")
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="引用文件已不存在")
    return doc, file_path


def ensure_admin_document(db: Session, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if not doc or str(doc.source_type or "").startswith("chat_"):
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


def cleanup_document_rows(db: Session, document_id: str):
    db.query(GraphMention).filter(GraphMention.document_id == document_id).delete()
    db.query(GraphRelation).filter(GraphRelation.source_document_id == document_id).delete()
    db.query(GraphExtractionStatus).filter(GraphExtractionStatus.document_id == document_id).delete()
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    db.query(DocumentTableRow).filter(DocumentTableRow.document_id == document_id).delete()
    db.query(TableSchemaAlias).filter(TableSchemaAlias.document_id == document_id).delete()
    db.query(DocumentPageIndex).filter(DocumentPageIndex.document_id == document_id).delete()
    db.query(DocumentProcessingStatus).filter(DocumentProcessingStatus.document_id == document_id).delete()
    db.query(BackgroundTask).filter(BackgroundTask.document_id == document_id).delete()
    db.execute(document_group_link.delete().where(document_group_link.c.document_id == document_id))
    delete_pageindex_files(document_id)
    try:
        delete_document_vectors(document_id)
    except QdrantUnavailable:
        pass
