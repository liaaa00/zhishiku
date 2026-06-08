import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_schemas import ChunkUpdate, DocumentPermissionUpdate
from ..admin_utils import load_groups_by_ids
from ..ai_client import embed_texts, image_to_text
from ..citation_utils import bounded_limit
from ..database import get_db
from ..document_access import cleanup_document_rows, ensure_admin_document
from ..document_status import set_doc_status
from ..document_utils import extract_supported_document
from ..models import BackgroundTask, Document, DocumentChunk, DocumentPageIndex, DocumentProcessingStatus, User
from ..pageindex_adapter import build_pageindex_for_document, load_pageindex_payload, pageindex_admin_summary, pageindex_integration_status
from ..settings_service import get_model_config
from ..task_service import IMAGE_EXTENSIONS, _ocr_pdf_pages, _total_extracted_chars, enqueue_document_task
from ..upload_policy import KNOWLEDGE_FILE_EXTENSIONS, MAX_CHUNK_CONTENT_CHARS
from ..upload_security import validate_upload_file
from ..upload_storage import save_upload
from ..vector_store import QdrantUnavailable, upsert_document_chunks
from .deps import audit, require_admin

router = APIRouter()


@router.get("/api/admin/page-index/status")
def get_pageindex_status(_: User = Depends(require_admin)):
    return pageindex_integration_status()


@router.get("/api/admin/documents")
def list_documents(
    limit: int = Query(500, ge=1, le=1000),
    summary: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row_limit = bounded_limit(limit, 500, 1000)
    docs = db.execute(
        select(Document)
        .where(~Document.source_type.like("chat_%"))
        .order_by(Document.created_at.desc())
        .limit(row_limit)
    ).scalars().all()
    result = []
    for d in docs:
        st = db.get(DocumentProcessingStatus, d.id)
        pi = db.get(DocumentPageIndex, d.id)
        result.append(
            {
                "id": d.id,
                "title": d.title,
                "filename": d.filename,
                "source_type": d.source_type,
                "groups": [] if summary else [{"id": g.id, "name": g.name} for g in d.groups],
                "groups_included": not summary,
                "status": st.status if st else "pending",
                "stage": st.stage if st else "uploaded",
                "message": st.message if st else "文档已上传，等待后台解析。",
                "chunks": st.chunks if st else 0,
                "searchable": st.searchable if st else False,
                "page_index": pageindex_admin_summary(pi),
                "created_at": d.created_at.isoformat(),
            }
        )
    return result


@router.post("/api/admin/documents")
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    _, ext = validate_upload_file(file, KNOWLEDGE_FILE_EXTENSIONS, "后台知识库支持 PDF、Word(.docx)、PowerPoint(.pptx)、Excel(.xlsx)、CSV、TXT、Markdown、图片 PNG/JPG/JPEG/WEBP/GIF（自动 OCR）。旧版 .doc/.ppt/.xls 请先另存为 .docx/.pptx/.xlsx。")
    doc_id, storage_path, filename = save_upload(file, "admin")

    doc = Document(id=doc_id, title=Path(filename).stem, filename=filename, storage_path=str(storage_path), source_type=ext.lstrip('.'), created_by=user.id)
    db.add(doc)
    db.flush()
    task = enqueue_document_task(db, doc, "document_parse", user)
    db.commit()
    return {"id": doc.id, "title": doc.title, "task_id": task.id, "status": "queued", "searchable": False, "message": "文档已上传，正在后台解析。"}


@router.get("/api/admin/documents/{document_id}/chunks")
def list_document_chunks(document_id: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    chunks = db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index.asc())
    ).scalars().all()
    return {
        "document": {"id": doc.id, "title": doc.title, "filename": doc.filename},
        "chunks": [
            {"id": c.id, "page_number": c.page_number, "chunk_index": c.chunk_index, "content": c.content}
            for c in chunks
        ],
    }


@router.get("/api/admin/documents/{document_id}/page-index")
def get_document_page_index(document_id: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    row, payload = load_pageindex_payload(db, doc.id)
    summary = pageindex_admin_summary(row)
    return {
        "document": {"id": doc.id, "title": doc.title, "filename": doc.filename},
        "page_index": summary,
        "structure": (payload or {}).get("structure") or [],
        "doc_description": (payload or {}).get("doc_description") or summary.get("description") or "",
        "page_count": (payload or {}).get("page_count") or (payload or {}).get("line_count") or summary.get("page_count") or 0,
    }


@router.post("/api/admin/documents/{document_id}/page-index/rebuild")
def rebuild_document_page_index(document_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    if not Path(doc.storage_path).exists():
        raise HTTPException(status_code=404, detail="原始文件不存在")
    try:
        cfg = get_model_config(db)
        ext = Path(doc.filename or "").suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            text_content = image_to_text(str(doc.storage_path), cfg["api_key"], cfg["base_url"], cfg["model"])
            pages = [(1, text_content)] if text_content else []
        else:
            pages = extract_supported_document(str(doc.storage_path))
            if ext == ".pdf" and _total_extracted_chars(pages) == 0:
                pages = _ocr_pdf_pages(Path(doc.storage_path), cfg)
        row = build_pageindex_for_document(db, doc, pages, cfg=cfg, force=True)
        audit(db, actor, "page_index.rebuild", "document", doc.id, {"status": row.status if row else "not_built"})
        db.commit()
        return {"ok": True, "page_index": pageindex_admin_summary(row)}
    except Exception as exc:
        row = db.get(DocumentPageIndex, doc.id)
        if not row:
            row = DocumentPageIndex(document_id=doc.id)
            db.add(row)
        row.status = "failed"
        row.index_type = "pageindex"
        row.error_message = str(exc)[:1500]
        db.commit()
        raise HTTPException(status_code=500, detail=f"高级索引重建失败：{exc}")


@router.put("/api/admin/documents/{document_id}/chunks/{chunk_id}")
def update_document_chunk(document_id: str, chunk_id: str, req: ChunkUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    chunk = db.get(DocumentChunk, chunk_id)
    if not chunk or chunk.document_id != doc.id:
        raise HTTPException(status_code=404, detail="切片不存在")
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="切片内容不能为空")
    if len(content) > MAX_CHUNK_CONTENT_CHARS:
        raise HTTPException(status_code=400, detail=f"切片内容不能超过 {MAX_CHUNK_CONTENT_CHARS} 个字")
    chunk.content = content
    chunk.embedding_json = json.dumps(embed_texts([content])[0])
    db.flush()
    try:
        upsert_document_chunks(doc, [chunk])
    except QdrantUnavailable:
        pass
    page_index = db.get(DocumentPageIndex, doc.id)
    page_index_stale = False
    if page_index and page_index.status == "ready":
        page_index.status = "stale"
        page_index.error_message = "普通片段已被手动编辑；请重建高级索引以同步 PageIndex 结构树。"
        page_index_stale = True
    audit(db, actor, "chunk.edit", "document", doc.id, {"chunk_id": chunk_id, "page_index_stale": page_index_stale})
    db.commit()
    return {
        "ok": True,
        "page_index_stale": page_index_stale,
        "message": "片段已保存；请重建高级索引以同步 PageIndex 结构树。" if page_index_stale else "片段已保存。",
    }


@router.post("/api/admin/documents/{document_id}/reparse")
def reparse_document(document_id: str, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    if Path(doc.filename).suffix.lower() not in KNOWLEDGE_FILE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="当前文件类型不支持重新解析")
    if not Path(doc.storage_path).exists():
        set_doc_status(db, doc, "failed", "file_missing", "原始文件不存在，无法重新解析。", 0, False)
        db.commit()
        raise HTTPException(status_code=404, detail="原始文件不存在")
    db.query(BackgroundTask).filter(BackgroundTask.document_id == doc.id, BackgroundTask.status.in_(["pending", "running"])).delete()
    task = enqueue_document_task(db, doc, "document_reparse", user)
    db.commit()
    return {"ok": True, "task_id": task.id, "status": "queued", "message": "已进入后台重新解析队列。"}


@router.delete("/api/admin/documents/{document_id}")
def delete_document(document_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    storage_path = Path(doc.storage_path) if doc.storage_path else None
    title = doc.title
    cleanup_document_rows(db, doc.id)
    audit(db, actor, "document.delete", "document", doc.id, {"title": title, "filename": doc.filename})
    db.delete(doc)
    db.commit()
    if storage_path:
        storage_path.unlink(missing_ok=True)
    return {"ok": True}


@router.put("/api/admin/documents/{document_id}/permissions")
def update_document_permissions(document_id: str, req: DocumentPermissionUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    doc.groups = load_groups_by_ids(db, req.group_ids)
    db.flush()
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)).scalars().all()
    try:
        upsert_document_chunks(doc, chunks)
    except QdrantUnavailable:
        pass
    audit(db, actor, "document.permissions_update", "document", doc.id, {"group_ids": req.group_ids})
    db.commit()
    return {"id": doc.id, "group_ids": [g.id for g in doc.groups]}
