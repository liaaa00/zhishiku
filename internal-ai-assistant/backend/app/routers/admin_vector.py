from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, DocumentChunk, User
from ..vector_store import QdrantUnavailable, qdrant_enabled, upsert_document_chunks
from .deps import audit, require_admin

router = APIRouter()


@router.get("/api/admin/vector/status")
def vector_status(_: User = Depends(require_admin)):
    return {"backend": "qdrant" if qdrant_enabled() else "sqlite", "qdrant_enabled": qdrant_enabled()}


@router.post("/api/admin/vector/reindex")
def reindex_vectors(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not qdrant_enabled():
        return {"ok": False, "message": "当前 VECTOR_BACKEND 不是 qdrant"}
    docs = db.execute(select(Document)).scalars().all()
    total = 0
    try:
        for doc in docs:
            chunks = db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)).scalars().all()
            if chunks:
                upsert_document_chunks(doc, chunks)
                total += len(chunks)
        audit(db, actor, "vector.reindex", "vector", "qdrant", {"chunks": total})
        db.commit()
        return {"ok": True, "chunks": total}
    except QdrantUnavailable as exc:
        raise HTTPException(status_code=503, detail=f"Qdrant 不可用：{exc}")
