import json
from typing import Optional

from sqlalchemy.orm import Session

from .ai_client import embed_texts
from .document_utils import chunk_text
from .models import Document, DocumentChunk
from .routers.deps import new_id
from .table_rows import replace_document_table_rows
from .vector_store import QdrantUnavailable, delete_document_vectors, upsert_document_chunks


def add_chunks(db: Session, document_id: str, pages: list[tuple[Optional[int], str]]) -> int:
    doc = db.get(Document, document_id)
    if doc:
        try:
            replace_document_table_rows(db, doc, pages)
        except Exception:
            # 表格行索引是增量增强能力，不能阻断普通切片入库。
            pass

    all_chunks: list[tuple[Optional[int], str]] = []
    for page_number, text_content in pages:
        for chunk in chunk_text(text_content):
            all_chunks.append((page_number, chunk))
    if not all_chunks:
        try:
            delete_document_vectors(document_id)
        except QdrantUnavailable:
            pass
        db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
        db.flush()
        return 0

    embeddings = embed_texts([c[1] for c in all_chunks])
    try:
        delete_document_vectors(document_id)
    except QdrantUnavailable:
        pass
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()

    chunk_rows = []
    for idx, ((page_number, content), emb) in enumerate(zip(all_chunks, embeddings)):
        row = DocumentChunk(
            id=new_id(),
            document_id=document_id,
            page_number=page_number,
            chunk_index=idx,
            content=content,
            embedding_json=json.dumps(emb),
        )
        db.add(row)
        chunk_rows.append(row)
    db.flush()

    if doc:
        try:
            upsert_document_chunks(doc, chunk_rows)
        except QdrantUnavailable:
            pass
    return len(all_chunks)
