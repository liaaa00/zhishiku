import json
import math

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_schemas import VectorStatusResponse
from ..ai_client import embed_texts
from ..database import get_db
from ..models import Document, DocumentChunk, User
from ..settings_service import get_embedding_config
from ..vector_store import QdrantUnavailable, qdrant_enabled, qdrant_health, recreate_collection, upsert_document_chunks
from .deps import audit, require_admin

router = APIRouter()


@router.get("/api/admin/vector/status", response_model=VectorStatusResponse)
def vector_status(_: User = Depends(require_admin)):
    return qdrant_health()


@router.post("/api/admin/vector/reindex")
def reindex_vectors(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if not qdrant_enabled():
        return {"ok": False, "message": "当前 VECTOR_BACKEND 不是 qdrant"}
    chunks = db.execute(select(DocumentChunk).order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)).scalars().all()
    if not chunks:
        return {"ok": True, "chunks": 0, "documents": 0, "dimension": 0}
    config = get_embedding_config(db)
    previous_embeddings = [chunk.embedding_json for chunk in chunks]
    documents = {str(doc.id): doc for doc in db.execute(select(Document)).scalars().all()}
    chunks_by_document: dict[str, list[DocumentChunk]] = {}
    for chunk in chunks:
        chunks_by_document.setdefault(str(chunk.document_id), []).append(chunk)
    vectors: list[list[float]] = []
    replacement_started = False

    def vector_dimension(items: list[list[float]], label: str) -> int:
        if not items or any(not isinstance(vector, list) or not vector for vector in items):
            raise ValueError(f"{label}存在空向量或无效向量")
        if any(
            not isinstance(value, (int, float)) or not math.isfinite(value)
            for vector in items
            for value in vector
        ):
            raise ValueError(f"{label}包含非数字或非有限值")
        dimensions = {len(vector) for vector in items}
        if len(dimensions) != 1:
            raise ValueError(f"{label}维度不一致")
        return dimensions.pop()

    def restore_previous_collection(previous_dimension: int) -> None:
        for chunk, embedding_json in zip(chunks, previous_embeddings):
            chunk.embedding_json = embedding_json
        recreate_collection(previous_dimension)
        for document_id, document_chunks in chunks_by_document.items():
            doc = documents.get(document_id)
            if doc is not None:
                upsert_document_chunks(doc, document_chunks)

    try:
        previous_vectors = [json.loads(embedding_json) for embedding_json in previous_embeddings]
        previous_dimension = vector_dimension(previous_vectors, "旧向量")
        for start in range(0, len(chunks), 32):
            batch = chunks[start : start + 32]
            generated = embed_texts([chunk.content for chunk in batch], strict=True)
            if len(generated) != len(batch):
                raise ValueError(f"Embedding 返回数量不匹配：期望 {len(batch)}，实际 {len(generated)}")
            vectors.extend(generated)
        if len(vectors) != len(chunks):
            raise ValueError(f"Embedding 返回数量不匹配：期望 {len(chunks)}，实际 {len(vectors)}")
        dimension = vector_dimension(vectors, "Embedding 向量")

        replacement_started = True
        recreate_collection(dimension)
        for chunk, vector in zip(chunks, vectors):
            chunk.embedding_json = json.dumps(vector)
        db.flush()
        for document_id, document_chunks in chunks_by_document.items():
            doc = documents.get(document_id)
            if doc is not None:
                upsert_document_chunks(doc, document_chunks)
        detail = {
            "chunks": len(chunks),
            "documents": len(chunks_by_document),
            "dimension": dimension,
            "provider": config.get("provider") or "local",
            "model": config.get("model") or "local-hash",
        }
        audit(db, actor, "vector.reindex", "vector", "qdrant", detail)
        db.commit()
        return {"ok": True, **detail}
    except Exception as exc:
        db.rollback()
        if replacement_started:
            try:
                restore_previous_collection(previous_dimension)
            except Exception as restore_exc:
                raise HTTPException(
                    status_code=503,
                    detail=f"向量重建失败且旧集合恢复失败：{str(exc)[:120]}；恢复错误：{str(restore_exc)[:120]}",
                ) from exc
        if isinstance(exc, QdrantUnavailable):
            raise HTTPException(status_code=503, detail=f"Qdrant 不可用：{exc}") from exc
        raise HTTPException(status_code=502, detail=f"Embedding 重建失败：{str(exc)[:240]}") from exc
