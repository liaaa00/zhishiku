import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .ai_client import image_to_text
from .config import DEFAULT_ADMIN_PASSWORD, DEFAULT_ADMIN_USERNAME, PDF_OCR_MAX_PAGES, PDF_OCR_ZOOM
from .database import SessionLocal, engine
from .document_index import add_chunks
from .document_status import set_doc_status
from .document_utils import extract_supported_document
from .models import BackgroundTask, Document, DocumentPageIndex, Setting, User
from .pageindex_adapter import build_pageindex_for_document, can_build_pageindex, mark_pageindex_pending
from .settings_service import get_model_config
from .security import hash_password
from .routers.deps import audit, new_id

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".md", ".markdown", ".docx", ".pptx", ".xlsx", ".csv"}

worker_started = False
worker_lock = threading.Lock()


def _total_extracted_chars(pages: list[tuple[int | None, str]]) -> int:
    return sum(len((text or "").strip()) for _, text in pages or [])


def _ocr_pdf_pages(file_path: Path, cfg: dict) -> list[tuple[int | None, str]]:
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("扫描版 PDF 需要安装 PyMuPDF 才能转图片 OCR。") from exc

    result: list[tuple[int | None, str]] = []
    max_pages = max(1, int(PDF_OCR_MAX_PAGES or 20))
    zoom = max(1.0, float(PDF_OCR_ZOOM or 2.0))
    with fitz.open(str(file_path)) as pdf, tempfile.TemporaryDirectory(prefix="pdf_ocr_") as tmp_dir:
        total_pages = min(len(pdf), max_pages)
        matrix = fitz.Matrix(zoom, zoom)
        for page_index in range(total_pages):
            page = pdf.load_page(page_index)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = Path(tmp_dir) / f"page_{page_index + 1}.png"
            pix.save(str(image_path))
            text = image_to_text(str(image_path), cfg["api_key"], cfg["base_url"], cfg["model"])
            if text and text.strip():
                result.append((page_index + 1, text.strip()))
    return result


def enqueue_document_task(db: Session, doc: Document, task_type: str, actor: Optional[User]) -> BackgroundTask:
    task = BackgroundTask(
        id=new_id(),
        task_type=task_type,
        document_id=doc.id,
        status="pending",
        created_by=actor.id if actor else None,
    )
    db.add(task)
    set_doc_status(db, doc, "pending", "queued", "已进入后台解析队列，稍后自动处理。", 0, False)
    audit(db, actor, "task.enqueue", "document", doc.id, {"task_type": task_type, "filename": doc.filename})
    return task


def _record_pageindex_skipped(db: Session, doc: Document, reason: str) -> None:
    row = db.get(DocumentPageIndex, doc.id)
    if row:
        row.status = "not_built"
        row.index_type = "pageindex"
        row.error_message = reason[:1500]
        row.updated_at = datetime.utcnow()
        db.flush()


def _record_pageindex_failed(db: Session, doc: Document, exc: Exception) -> None:
    row = db.get(DocumentPageIndex, doc.id)
    if not row:
        row = DocumentPageIndex(document_id=doc.id)
        db.add(row)
    row.status = "failed"
    row.index_type = "pageindex"
    row.engine = row.engine or "pageindex"
    row.error_message = str(exc)[:1500]
    row.page_count = 0
    row.node_count = 0
    row.updated_at = datetime.utcnow()
    db.flush()


def _maybe_build_pageindex(db: Session, doc: Document, pages: list[tuple[int | None, str]]) -> None:
    allowed, reason = can_build_pageindex(doc, pages)
    if not allowed:
        _record_pageindex_skipped(db, doc, reason)
        db.commit()
        return
    try:
        cfg = get_model_config(db)
        mark_pageindex_pending(db, doc, "building")
        db.commit()
        build_pageindex_for_document(db, doc, pages, cfg=cfg)
    except Exception as exc:
        db.rollback()
        # PageIndex is a sidecar index. It must never make the traditional chunk index fail.
        _record_pageindex_failed(db, doc, exc)
        db.commit()


def parse_document_to_chunks(db: Session, doc: Document) -> int:
    ext = Path(doc.filename).suffix.lower()
    source_type = str(doc.source_type or "")
    storage_path = Path(doc.storage_path)
    if not storage_path.exists():
        raise FileNotFoundError("原始文件不存在")

    if source_type == "chat_image" or ext in IMAGE_EXTENSIONS:
        cfg = get_model_config(db)
        set_doc_status(db, doc, "processing", "vision_ocr", "正在调用视觉模型提取图片文字和内容。")
        db.commit()
        text_content = image_to_text(str(storage_path), cfg["api_key"], cfg["base_url"], cfg["model"])
        pages = [(1, text_content)] if text_content else []
        chunks = add_chunks(db, doc.id, pages)
        db.commit()
        _maybe_build_pageindex(db, doc, pages)
        return chunks

    if ext in DOCUMENT_EXTENSIONS:
        stage = {
            ".pdf": "pdf_text_extract",
            ".docx": "word_text_extract",
            ".pptx": "pptx_text_extract",
            ".xlsx": "spreadsheet_extract",
            ".csv": "csv_extract",
            ".txt": "text_extract",
            ".md": "markdown_extract",
            ".markdown": "markdown_extract",
        }.get(ext, "document_extract")
        set_doc_status(db, doc, "processing", stage, "正在解析文档内容。")
        db.commit()
        pages = extract_supported_document(str(storage_path))
        if ext == ".pdf" and _total_extracted_chars(pages) == 0:
            cfg = get_model_config(db)
            set_doc_status(db, doc, "processing", "pdf_vision_ocr", f"PDF 未提取到文本，正在对前 {PDF_OCR_MAX_PAGES} 页进行视觉 OCR。")
            db.commit()
            pages = _ocr_pdf_pages(storage_path, cfg)
        chunks = add_chunks(db, doc.id, pages)
        db.commit()
        _maybe_build_pageindex(db, doc, pages)
        return chunks

    raise ValueError("不支持的文件类型")


def process_task_once(task_id: str):
    db = SessionLocal()
    try:
        task = db.get(BackgroundTask, task_id)
        if not task or task.status not in {"pending", "running"}:
            return
        doc = db.get(Document, task.document_id) if task.document_id else None
        if not doc:
            task.status = "failed"
            task.last_error = "文档不存在"
            task.finished_at = datetime.utcnow()
            db.commit()
            return

        task.status = "running"
        task.attempts += 1
        task.started_at = datetime.utcnow()
        task.updated_at = datetime.utcnow()
        set_doc_status(db, doc, "processing", "worker", "后台任务正在处理。", 0, False)
        db.commit()

        try:
            chunks = parse_document_to_chunks(db, doc)
            if chunks:
                set_doc_status(db, doc, "ready", "indexed", "后台解析完成，文档已加入检索索引。", chunks, True)
                task.status = "success"
                task.last_error = ""
            else:
                set_doc_status(db, doc, "failed", "need_ocr", "没有解析出可检索文本；扫描件 PDF 需要接入 PDF OCR。", 0, False)
                task.status = "failed"
                task.last_error = "没有解析出可检索文本"
            task.finished_at = datetime.utcnow()
            task.updated_at = datetime.utcnow()
            audit(db, None, "task.finish", "document", doc.id, {"task_id": task.id, "status": task.status, "chunks": chunks})
            db.commit()
        except Exception as exc:
            task.status = "failed"
            task.last_error = str(exc)
            task.finished_at = datetime.utcnow()
            task.updated_at = datetime.utcnow()
            set_doc_status(db, doc, "failed", "parse_error", f"后台解析失败：{exc}", 0, False)
            audit(db, None, "task.fail", "document", doc.id, {"task_id": task.id, "error": str(exc)})
            db.commit()
    finally:
        db.close()


def task_worker_loop():
    while True:
        db = SessionLocal()
        try:
            task = db.execute(
                select(BackgroundTask).where(BackgroundTask.status == "pending").order_by(BackgroundTask.created_at.asc())
            ).scalars().first()
            task_id = task.id if task else None
        finally:
            db.close()
        if task_id:
            process_task_once(task_id)
        else:
            time.sleep(1.5)


def start_task_worker():
    global worker_started
    with worker_lock:
        if worker_started:
            return
        worker_started = True
        threading.Thread(target=task_worker_loop, daemon=True, name="document-task-worker").start()


def initialize_runtime_schema():
    # SQLite 无迁移工具时做最小兼容：给旧库补新增列，新表仍由 create_all 创建。
    def add_column_if_missing(conn, table: str, column: str, ddl: str):
        cols = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
        if cols and column not in cols:
            try:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            except Exception as exc:
                refreshed = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()}
                if column not in refreshed:
                    raise exc

    with engine.begin() as conn:
        add_column_if_missing(conn, "users", "is_active", "is_active BOOLEAN NOT NULL DEFAULT 1")
        add_column_if_missing(conn, "chat_messages", "sources_json", "sources_json TEXT NOT NULL DEFAULT '[]'")
        add_column_if_missing(conn, "chat_messages", "mode", "mode TEXT NOT NULL DEFAULT 'knowledge'")
        add_column_if_missing(conn, "feedback", "sources_json", "sources_json TEXT NOT NULL DEFAULT '[]'")
        add_column_if_missing(conn, "feedback", "status", "status TEXT NOT NULL DEFAULT 'new'")
        add_column_if_missing(conn, "feedback", "reviewed_at", "reviewed_at DATETIME")
        add_column_if_missing(conn, "feedback", "review_note", "review_note TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(conn, "feedback", "category", "category TEXT NOT NULL DEFAULT 'other'")
        add_column_if_missing(conn, "feedback", "admin_note", "admin_note TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(conn, "feedback", "handled_by_user_id", "handled_by_user_id TEXT")
        add_column_if_missing(conn, "feedback", "handled_by_username", "handled_by_username TEXT NOT NULL DEFAULT ''")
        add_column_if_missing(conn, "feedback", "handled_at", "handled_at DATETIME")
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS document_table_rows (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                sheet_name TEXT NOT NULL DEFAULT '',
                row_number INTEGER,
                row_key TEXT NOT NULL DEFAULT '',
                row_json TEXT NOT NULL,
                row_text TEXT NOT NULL,
                is_header BOOLEAN NOT NULL DEFAULT 0,
                source_chunk_index INTEGER,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_document_table_rows_document_id ON document_table_rows(document_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_document_table_rows_sheet_name ON document_table_rows(sheet_name)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_document_table_rows_row_key ON document_table_rows(row_key)")
        conn.exec_driver_sql(
            """
            CREATE TABLE IF NOT EXISTS table_schema_aliases (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                sheet_name TEXT NOT NULL DEFAULT '',
                raw_name TEXT NOT NULL DEFAULT '',
                semantic_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'confirmed',
                confidence REAL NOT NULL DEFAULT 0,
                suggestion_key TEXT NOT NULL DEFAULT '',
                reasons_json TEXT NOT NULL DEFAULT '[]',
                samples_json TEXT NOT NULL DEFAULT '[]',
                created_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                updated_by TEXT REFERENCES users(id) ON DELETE SET NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_table_schema_aliases_document_id ON table_schema_aliases(document_id)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_table_schema_aliases_semantic_name ON table_schema_aliases(semantic_name)")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_table_schema_aliases_suggestion_key ON table_schema_aliases(suggestion_key)")
        conn.exec_driver_sql("CREATE UNIQUE INDEX IF NOT EXISTS ux_table_schema_aliases_mapping ON table_schema_aliases(document_id, sheet_name, raw_name, semantic_name)")


def bootstrap_default_admin():
    db = SessionLocal()
    try:
        admin = db.execute(select(User).where(User.username == DEFAULT_ADMIN_USERNAME)).scalar_one_or_none()
        if not admin:
            db.add(User(id=new_id(), username=DEFAULT_ADMIN_USERNAME, password_hash=hash_password(DEFAULT_ADMIN_PASSWORD), is_admin=True, is_active=True))
        else:
            admin.is_active = True
        if not db.get(Setting, "deepseek_base_url"):
            db.add(Setting(key="deepseek_base_url", value="https://api.deepseek.com"))
        if not db.get(Setting, "deepseek_model"):
            db.add(Setting(key="deepseek_model", value="deepseek-chat"))
        db.query(BackgroundTask).filter(BackgroundTask.status == "running").update({"status": "pending", "last_error": "服务重启后自动恢复队列"})
        db.commit()
    finally:
        db.close()
