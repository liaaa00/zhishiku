from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..citation_utils import (
    bounded_limit,
    build_location_descriptor,
    citation_content_url,
    citation_view_url,
    html_escape,
    preview_cache_headers,
    snippet_text,
)
from ..database import get_db
from ..document_access import resolve_document_file_for_user
from ..document_status import status_to_dict
from ..models import DocumentChunk, DocumentProcessingStatus, User
from .deps import require_user

router = APIRouter()


@router.get("/api/documents/{document_id}/view")
def view_document_file(document_id: str, chunk_id: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(require_user)):
    doc, file_path = resolve_document_file_for_user(db, document_id, user)
    headers = {"X-Document-Id": doc.id, **preview_cache_headers()}
    if chunk_id:
        chunk = db.get(DocumentChunk, chunk_id)
        if chunk and chunk.document_id == doc.id:
            headers["X-Document-Page"] = str(chunk.page_number or "")
            headers["X-Document-Chunk-Index"] = str(chunk.chunk_index)
    return FileResponse(path=str(file_path), filename=doc.filename, headers=headers)


@router.get("/api/documents/{document_id}/content")
def get_document_content(
    document_id: str,
    response: Response,
    chunk_id: Optional[str] = None,
    limit: int = Query(8, ge=1, le=50),
    include_content: bool = True,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    doc, _ = resolve_document_file_for_user(db, document_id, user)
    response.headers.update(preview_cache_headers())
    chunk_limit = bounded_limit(limit, 8, 50)
    if chunk_id:
        chunk = db.get(DocumentChunk, chunk_id)
        if not chunk or chunk.document_id != doc.id:
            raise HTTPException(status_code=404, detail="引用片段不存在")
        chunks = [chunk]
    else:
        chunks = db.execute(
            select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index.asc()).limit(chunk_limit)
        ).scalars().all()
    serialized_chunks = [
        {
            "id": c.id,
            "chunk_id": c.id,
            "chunk_index": c.chunk_index,
            "page_number": c.page_number,
            "page": c.page_number,
            "content": c.content if include_content else "",
            "snippet": snippet_text(c.content, 500),
            "matched_snippet": snippet_text(c.content, 500),
            "highlight_ranges": [],
            "highlight_html": html_escape(snippet_text(c.content, 500)),
            "location": build_location_descriptor({"source_type": doc.source_type, "page_number": c.page_number, "chunk_index": c.chunk_index}),
        }
        for c in chunks
    ]
    return {
        "id": doc.id,
        "document_id": doc.id,
        "title": doc.title,
        "filename": doc.filename,
        "source_type": doc.source_type,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "view_url": citation_view_url(doc.id, chunk_id),
        "content_url": citation_content_url(doc.id, chunk_id),
        "chunks": serialized_chunks,
        "chunk_count": len(serialized_chunks),
        "limit": chunk_limit,
        "content_included": include_content,
        "content": "\n\n".join(c["content"] for c in serialized_chunks if c["content"]),
    }


@router.get("/api/documents/{document_id}/meta")
def get_document_meta(document_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    doc, _ = resolve_document_file_for_user(db, document_id, user)
    return {
        "id": doc.id,
        "title": doc.title,
        "filename": doc.filename,
        "source_type": doc.source_type,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "view_url": citation_view_url(doc.id),
        "content_url": citation_content_url(doc.id),
    }


@router.get("/api/documents/status")
def list_document_status(scope: str = "all", db: Session = Depends(get_db), user: User = Depends(require_user)):
    rows = db.execute(select(DocumentProcessingStatus).order_by(DocumentProcessingStatus.updated_at.desc())).scalars().all()
    result = []
    for item in rows:
        doc = item.document
        if not doc:
            continue
        is_chat = str(doc.source_type or "").startswith("chat_")
        if scope == "chat" and not is_chat:
            continue
        if scope == "admin" and is_chat:
            continue
        if is_chat and doc.created_by != user.id:
            continue
        if not is_chat and not user.is_admin:
            continue
        result.append(status_to_dict(item))
    return result
