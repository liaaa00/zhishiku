import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .ai_client import chat_answer, embed_texts, image_to_text
from .config import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    UPLOAD_DIR,
)
from .database import Base, SessionLocal, engine, get_db
from .document_utils import chunk_text, extract_supported_document, safe_filename
from .models import (
    AuditLog,
    BackgroundTask,
    ChatMessage,
    ChatSession,
    Document,
    DocumentChunk,
    DocumentProcessingStatus,
    Feedback,
    Group,
    Setting,
    User,
    document_group_link,
)
from .security import create_token, decode_token, hash_password, verify_password
from .vector_store import QdrantUnavailable, delete_document_vectors, qdrant_enabled, search_chunks, upsert_document_chunks

app = FastAPI(title="内部 AI 问答助手", version="0.9.0")
security = HTTPBearer(auto_error=False)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

TEXT_EXTENSIONS = {".txt", ".md", ".markdown"}
OFFICE_EXTENSIONS = {".docx", ".xlsx", ".csv"}
KNOWLEDGE_FILE_EXTENSIONS = {".pdf", *TEXT_EXTENSIONS, *OFFICE_EXTENSIONS}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CHAT_FILE_EXTENSIONS = {*KNOWLEDGE_FILE_EXTENSIONS, *IMAGE_EXTENSIONS}


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str
    is_admin: bool = False
    group_ids: List[str] = []


class UserPasswordReset(BaseModel):
    password: str


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserGroupsUpdate(BaseModel):
    group_ids: List[str] = []
    is_admin: Optional[bool] = None


class GroupCreate(BaseModel):
    name: str


class DocumentPermissionUpdate(BaseModel):
    group_ids: List[str]


class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None
    top_k: int = 5


class FeedbackCreate(BaseModel):
    session_id: Optional[str] = None
    message_id: Optional[str] = None
    rating: Optional[str] = None
    content: str


class FeedbackReview(BaseModel):
    status: str = "reviewed"
    review_note: str = ""


class ModelConfig(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"


def new_id() -> str:
    return str(uuid.uuid4())


def row_to_user(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
        "is_active": getattr(user, "is_active", True),
        "groups": [{"id": g.id, "name": g.name} for g in user.groups],
    }


def get_setting(db: Session, key: str, default: str = "") -> str:
    item = db.get(Setting, key)
    return item.value if item else default


def set_setting(db: Session, key: str, value: str):
    item = db.get(Setting, key)
    if item:
        item.value = value
    else:
        db.add(Setting(key=key, value=value))


def get_model_config(db: Session) -> dict:
    return {
        "api_key": get_setting(db, "deepseek_api_key", ""),
        "base_url": get_setting(db, "deepseek_base_url", "https://api.deepseek.com"),
        "model": get_setting(db, "deepseek_model", "deepseek-chat"),
    }


def parse_embedding(value: str) -> List[float]:
    return json.loads(value)


def parse_json_list(value: str) -> list:
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def snippet_text(text: str, max_len: int = 300) -> str:
    clean = " ".join((text or "").split())
    return clean[:max_len]


def citation_view_url(document_id: str, chunk_id: Optional[str] = None) -> str:
    url = f"/api/documents/{document_id}/view"
    return f"{url}?chunk_id={chunk_id}" if chunk_id else url


def can_access_document(db: Session, doc: Document, user: User) -> bool:
    source_type = str(doc.source_type or "")
    if source_type.startswith("chat_"):
        return doc.created_by == user.id or user.is_admin
    if user.is_admin:
        return True
    group_ids = [g.id for g in user.groups]
    if not group_ids:
        return False
    return bool(
        db.execute(
            select(document_group_link.c.group_id).where(
                document_group_link.c.document_id == doc.id,
                document_group_link.c.group_id.in_(group_ids),
            )
        ).first()
    )


def build_citation(context: dict, index: int = 0) -> dict:
    document_id = context.get("document_id") or ""
    chunk_id = context.get("chunk_id") or ""
    filename = context.get("filename") or ""
    title = context.get("document_title") or filename or "未知文档"
    page_number = context.get("page_number")
    chunk_index = context.get("chunk_index")
    content = context.get("content") or ""
    citation = {
        "id": f"{document_id}:{chunk_id or chunk_index or index}",
        "document_id": document_id,
        "document_title": title,
        "title": title,
        "filename": filename or title,
        "file_name": filename or title,
        "page_number": page_number,
        "page": page_number,
        "chunk_id": chunk_id or None,
        "chunk_index": chunk_index,
        "source_type": context.get("source_type") or "document",
        "score": context.get("score"),
        "content": snippet_text(content),
        "snippet": snippet_text(content),
        "excerpt": snippet_text(content),
        "view_url": citation_view_url(document_id, chunk_id or None) if document_id else "",
        "url": citation_view_url(document_id, chunk_id or None) if document_id else "",
    }
    return citation


def serialize_sources(contexts: List[dict]) -> List[dict]:
    return [build_citation(c, i) for i, c in enumerate(contexts)]


def message_to_dict(message: ChatMessage) -> dict:
    sources = parse_json_list(getattr(message, "sources_json", "[]")) if message.role == "assistant" else []
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "created_at": message.created_at.isoformat(),
        "sources": sources,
        "citations": sources,
    }


def resolve_document_file_for_user(db: Session, document_id: str, user: User) -> tuple[Document, Path]:
    doc = db.get(Document, document_id)
    if not doc or not can_access_document(db, doc, user):
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


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-8)


def read_text_file(file_path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return file_path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="文本文件编码无法识别，请使用 UTF-8 文本。")


def require_user(db: Session = Depends(get_db), cred: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> User:
    if not cred:
        raise HTTPException(status_code=401, detail="请先登录")
    try:
        payload = decode_token(cred.credentials)
        user = db.get(User, payload.get("sub"))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录") from exc
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def add_chunks(db: Session, document_id: str, pages: List[tuple[Optional[int], str]]) -> int:
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    try:
        delete_document_vectors(document_id)
    except QdrantUnavailable:
        pass
    all_chunks = []
    for page_number, text_content in pages:
        for chunk in chunk_text(text_content):
            all_chunks.append((page_number, chunk))
    if not all_chunks:
        return 0
    embeddings = embed_texts([c[1] for c in all_chunks])
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
    doc = db.get(Document, document_id)
    if doc:
        try:
            upsert_document_chunks(doc, chunk_rows)
        except QdrantUnavailable:
            # Qdrant 不可用时保留 SQLite 本地索引，问答会自动回退。
            pass
    return len(all_chunks)


def save_upload(file: UploadFile, prefix: str) -> tuple[str, Path, str]:
    filename = safe_filename(file.filename or "attachment")
    doc_id = new_id()
    storage_path = UPLOAD_DIR / f"{prefix}_{doc_id}_{filename}"
    total = 0
    try:
        with storage_path.open("wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"文件不能超过 {MAX_UPLOAD_MB}MB")
                f.write(chunk)
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise
    return doc_id, storage_path, filename


def set_doc_status(db: Session, doc: Document, status: str, stage: str, message: str, chunks: int = 0, searchable: bool = False):
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


def session_payload(db: Session, session: ChatSession) -> dict:
    messages = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
    ).scalars().all()
    first_user = next((m.content for m in messages if m.role == "user"), "新的对话")
    last = messages[-1].content if messages else "还没有消息"
    return {
        "id": session.id,
        "title": first_user[:28],
        "preview": last[:42],
        "message_count": len(messages),
        "created_at": session.created_at.isoformat(),
    }


def ensure_admin_document(db: Session, document_id: str) -> Document:
    doc = db.get(Document, document_id)
    if not doc or str(doc.source_type or "").startswith("chat_"):
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


def cleanup_document_rows(db: Session, document_id: str):
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    db.query(DocumentProcessingStatus).filter(DocumentProcessingStatus.document_id == document_id).delete()
    db.query(BackgroundTask).filter(BackgroundTask.document_id == document_id).delete()
    db.execute(document_group_link.delete().where(document_group_link.c.document_id == document_id))
    try:
        delete_document_vectors(document_id)
    except QdrantUnavailable:
        pass


worker_started = False
worker_lock = threading.Lock()


def audit(db: Session, actor: Optional[User], action: str, resource_type: str = "", resource_id: str = "", detail: Optional[dict] = None):
    db.add(
        AuditLog(
            id=new_id(),
            actor_user_id=actor.id if actor else None,
            actor_username=actor.username if actor else "system",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id or "",
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )


def ensure_runtime_schema():
    # SQLite 无迁移工具时做最小兼容：给旧库补新增列，新表仍由 create_all 创建。
    with engine.begin() as conn:
        user_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()}
        if "is_active" not in user_cols:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1")
        chat_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(chat_messages)").fetchall()}
        if chat_cols and "sources_json" not in chat_cols:
            conn.exec_driver_sql("ALTER TABLE chat_messages ADD COLUMN sources_json TEXT NOT NULL DEFAULT '[]'")


def enqueue_document_task(db: Session, doc: Document, task_type: str, actor: Optional[User]) -> BackgroundTask:
    task = BackgroundTask(id=new_id(), task_type=task_type, document_id=doc.id, status="pending", created_by=actor.id if actor else None)
    db.add(task)
    set_doc_status(db, doc, "pending", "queued", "已进入后台解析队列，稍后自动处理。", 0, False)
    audit(db, actor, "task.enqueue", "document", doc.id, {"task_type": task_type, "filename": doc.filename})
    return task


def parse_document_to_chunks(db: Session, doc: Document) -> int:
    ext = Path(doc.filename).suffix.lower()
    source_type = str(doc.source_type or "")
    storage_path = Path(doc.storage_path)
    if not storage_path.exists():
        raise FileNotFoundError("原始文件不存在")
    if source_type == "chat_image" or ext in IMAGE_EXTENSIONS:
        cfg = get_model_config(db)
        set_doc_status(db, doc, "processing", "vision_ocr", "正在调用视觉模型提取图片文字和内容。")
        text_content = image_to_text(str(storage_path), cfg["api_key"], cfg["base_url"], cfg["model"])
        return add_chunks(db, doc.id, [(None, text_content)] if text_content else [])
    if ext in KNOWLEDGE_FILE_EXTENSIONS:
        stage = {
            ".pdf": "pdf_text_extract",
            ".docx": "word_text_extract",
            ".xlsx": "spreadsheet_extract",
            ".csv": "csv_extract",
            ".txt": "text_extract",
            ".md": "markdown_extract",
            ".markdown": "markdown_extract",
        }.get(ext, "document_extract")
        set_doc_status(db, doc, "processing", stage, "正在解析文档内容。")
        return add_chunks(db, doc.id, extract_supported_document(str(storage_path)))
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


@app.on_event("startup")
def startup():
    Base.metadata.create_all(bind=engine)
    ensure_runtime_schema()
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
    start_task_worker()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/chat")


@app.get("/chat", response_class=HTMLResponse, include_in_schema=False)
def chat_page():
    return HTMLResponse(CHAT_HTML)


@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def admin_page():
    return HTMLResponse(ADMIN_HTML)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.9.0"}


@app.post("/api/auth/login")
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.username == req.username)).scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not getattr(user, "is_active", True):
        raise HTTPException(status_code=403, detail="账号已被停用，请联系管理员")
    audit(db, user, "auth.login", "user", user.id)
    db.commit()
    return {"token": create_token({"sub": user.id}), "user": row_to_user(user)}


@app.get("/api/me")
def me(user: User = Depends(require_user)):
    return row_to_user(user)


@app.get("/api/chat/sessions")
def list_chat_sessions(db: Session = Depends(get_db), user: User = Depends(require_user)):
    sessions = db.execute(
        select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.created_at.desc())
    ).scalars().all()
    return [session_payload(db, s) for s in sessions]


@app.get("/api/chat/sessions/{session_id}")
def get_chat_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    ).scalars().all()
    return {
        "session": session_payload(db, session),
        "messages": [message_to_dict(m) for m in messages],
    }


@app.delete("/api/chat/sessions/{session_id}")
def delete_chat_session(session_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.delete(session)
    db.commit()
    return {"ok": True}


@app.get("/api/documents/{document_id}/view")
def view_document_file(document_id: str, chunk_id: Optional[str] = None, db: Session = Depends(get_db), user: User = Depends(require_user)):
    doc, file_path = resolve_document_file_for_user(db, document_id, user)
    headers = {"X-Document-Id": doc.id}
    if chunk_id:
        chunk = db.get(DocumentChunk, chunk_id)
        if chunk and chunk.document_id == doc.id:
            headers["X-Document-Page"] = str(chunk.page_number or "")
            headers["X-Document-Chunk-Index"] = str(chunk.chunk_index)
    return FileResponse(path=str(file_path), filename=doc.filename, headers=headers)


@app.get("/api/documents/{document_id}/meta")
def get_document_meta(document_id: str, db: Session = Depends(get_db), user: User = Depends(require_user)):
    doc, _ = resolve_document_file_for_user(db, document_id, user)
    return {
        "id": doc.id,
        "title": doc.title,
        "filename": doc.filename,
        "source_type": doc.source_type,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "view_url": citation_view_url(doc.id),
    }


@app.get("/api/documents/status")
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


@app.get("/api/admin/model")
def get_model(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    cfg = get_model_config(db)
    return {"base_url": cfg["base_url"], "model": cfg["model"], "api_key_set": bool(cfg["api_key"])}


@app.get("/api/admin/vector/status")
def vector_status(_: User = Depends(require_admin)):
    return {"backend": "qdrant" if qdrant_enabled() else "sqlite", "qdrant_enabled": qdrant_enabled()}


@app.post("/api/admin/vector/reindex")
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


@app.get("/api/admin/tasks")
def list_tasks(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.execute(select(BackgroundTask).order_by(BackgroundTask.created_at.desc())).scalars().all()
    return [
        {
            "id": t.id,
            "task_type": t.task_type,
            "document_id": t.document_id,
            "document_title": t.document.title if t.document else "",
            "status": t.status,
            "attempts": t.attempts,
            "last_error": t.last_error,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "started_at": t.started_at.isoformat() if t.started_at else None,
            "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        }
        for t in rows[:200]
    ]


@app.post("/api/admin/tasks/{task_id}/retry")
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


@app.get("/api/admin/feedback")
def list_feedback(status: Optional[str] = None, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    stmt = select(Feedback).order_by(Feedback.created_at.desc())
    if status:
        stmt = select(Feedback).where(Feedback.status == status).order_by(Feedback.created_at.desc())
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "id": f.id,
            "user_id": f.user_id,
            "username": f.username,
            "session_id": f.session_id,
            "message_id": f.message_id,
            "rating": f.rating,
            "content": f.content,
            "question": f.question_snapshot,
            "answer": f.answer_snapshot,
            "sources": parse_json_list(f.sources_json),
            "citations": parse_json_list(f.sources_json),
            "status": f.status,
            "created_at": f.created_at.isoformat() if f.created_at else None,
            "reviewed_at": f.reviewed_at.isoformat() if f.reviewed_at else None,
            "review_note": f.review_note,
        }
        for f in rows[:300]
    ]


@app.put("/api/admin/feedback/{feedback_id}")
def review_feedback(feedback_id: str, req: FeedbackReview, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    item = db.get(Feedback, feedback_id)
    if not item:
        raise HTTPException(status_code=404, detail="反馈不存在")
    status = (req.status or "reviewed").strip().lower()
    if status not in {"new", "reviewed", "resolved", "ignored"}:
        raise HTTPException(status_code=400, detail="反馈状态只能是 new/reviewed/resolved/ignored")
    item.status = status
    item.review_note = (req.review_note or "").strip()[:1000]
    item.reviewed_at = datetime.utcnow()
    audit(db, actor, "feedback.review", "feedback", item.id, {"status": item.status})
    db.commit()
    return {"ok": True, "id": item.id, "status": item.status}


@app.get("/api/admin/audit-logs")
def list_audit_logs(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    rows = db.execute(select(AuditLog).order_by(AuditLog.created_at.desc())).scalars().all()
    return [
        {
            "id": r.id,
            "actor_username": r.actor_username,
            "action": r.action,
            "resource_type": r.resource_type,
            "resource_id": r.resource_id,
            "detail": json.loads(r.detail_json or "{}"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows[:300]
    ]


@app.put("/api/admin/model")
def save_model(req: ModelConfig, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if req.api_key:
        set_setting(db, "deepseek_api_key", req.api_key.strip())
    set_setting(db, "deepseek_base_url", req.base_url.strip() or "https://api.deepseek.com")
    set_setting(db, "deepseek_model", req.model.strip() or "deepseek-chat")
    audit(db, actor, "model.update", "setting", "deepseek_model", {"base_url": req.base_url, "model": req.model, "api_key_set": bool(req.api_key)})
    db.commit()
    return {"ok": True}


@app.get("/api/admin/groups")
def list_groups(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    groups = db.execute(select(Group).order_by(Group.created_at.desc())).scalars().all()
    return [{"id": g.id, "name": g.name} for g in groups]


@app.post("/api/admin/groups")
def create_group(req: GroupCreate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="请输入岗位组名称")
    if db.execute(select(Group).where(Group.name == name)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="岗位组已存在")
    group = Group(id=new_id(), name=name)
    db.add(group)
    db.flush()
    audit(db, actor, "group.create", "group", group.id, {"name": group.name})
    db.commit()
    return {"id": group.id, "name": group.name}


@app.get("/api/admin/users")
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    users = db.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    return [row_to_user(u) for u in users]


@app.post("/api/admin/users")
def create_user(req: UserCreate, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    username = req.username.strip()
    if not username or not req.password:
        raise HTTPException(status_code=400, detail="请输入账号和密码")
    if db.execute(select(User).where(User.username == username)).scalar_one_or_none():
        raise HTTPException(status_code=400, detail="员工账号已存在")
    user = User(id=new_id(), username=username, password_hash=hash_password(req.password), is_admin=req.is_admin)
    if req.group_ids:
        user.groups = db.execute(select(Group).where(Group.id.in_(req.group_ids))).scalars().all()
    db.add(user)
    db.flush()
    audit(db, _, "user.create", "user", user.id, {"username": user.username, "is_admin": user.is_admin})
    db.commit()
    return row_to_user(user)


@app.put("/api/admin/users/{user_id}/groups")
def update_user_groups(user_id: str, req: UserGroupsUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    user.groups = db.execute(select(Group).where(Group.id.in_(req.group_ids))).scalars().all() if req.group_ids else []
    if req.is_admin is not None:
        if user.id == actor.id and not req.is_admin:
            raise HTTPException(status_code=400, detail="不能取消自己的管理员权限")
        user.is_admin = req.is_admin
    audit(db, actor, "user.update_groups", "user", user.id, {"group_ids": req.group_ids, "is_admin": user.is_admin})
    db.commit()
    return row_to_user(user)


@app.post("/api/admin/users/{user_id}/reset-password")
def reset_user_password(user_id: str, req: UserPasswordReset, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    if len(req.password or "") < 8:
        raise HTTPException(status_code=400, detail="新密码至少 8 位")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    user.password_hash = hash_password(req.password)
    audit(db, actor, "user.reset_password", "user", user.id, {"username": user.username})
    db.commit()
    return {"ok": True}


@app.put("/api/admin/users/{user_id}/status")
def update_user_status(user_id: str, req: UserStatusUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    if user.id == actor.id and not req.is_active:
        raise HTTPException(status_code=400, detail="不能停用自己的账号")
    user.is_active = req.is_active
    audit(db, actor, "user.update_status", "user", user.id, {"is_active": user.is_active})
    db.commit()
    return row_to_user(user)


@app.delete("/api/admin/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="员工不存在")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="不能删除自己的账号")
    if user.is_admin:
        admin_count = db.execute(select(User).where(User.is_admin == True, User.is_active == True)).scalars().all()
        if len(admin_count) <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个可用管理员")
    username = user.username
    user.groups = []
    audit(db, actor, "user.delete", "user", user.id, {"username": username})
    db.delete(user)
    db.commit()
    return {"ok": True}


@app.get("/api/admin/documents")
def list_documents(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    docs = db.execute(select(Document).order_by(Document.created_at.desc())).scalars().all()
    result = []
    for d in docs:
        if str(d.source_type or "").startswith("chat_"):
            continue
        st = db.get(DocumentProcessingStatus, d.id)
        result.append(
            {
                "id": d.id,
                "title": d.title,
                "filename": d.filename,
                "source_type": d.source_type,
                "groups": [{"id": g.id, "name": g.name} for g in d.groups],
                "status": st.status if st else "pending",
                "stage": st.stage if st else "uploaded",
                "chunks": st.chunks if st else 0,
                "searchable": st.searchable if st else False,
                "created_at": d.created_at.isoformat(),
            }
        )
    return result


@app.post("/api/admin/documents")
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    doc_id, storage_path, filename = save_upload(file, "admin")
    ext = Path(filename).suffix.lower()
    if ext not in KNOWLEDGE_FILE_EXTENSIONS:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="后台知识库支持 PDF、Word(.docx)、Excel(.xlsx)、CSV、TXT、Markdown。旧版 .doc/.xls 请先另存为 .docx/.xlsx。")
    doc = Document(id=doc_id, title=Path(filename).stem, filename=filename, storage_path=str(storage_path), source_type=ext.lstrip('.'), created_by=user.id)
    db.add(doc)
    db.flush()
    task = enqueue_document_task(db, doc, "document_parse", user)
    db.commit()
    return {"id": doc.id, "title": doc.title, "task_id": task.id, "status": "queued", "searchable": False, "message": "文档已上传，正在后台解析。"}


@app.get("/api/admin/documents/{document_id}/chunks")
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


@app.post("/api/admin/documents/{document_id}/reparse")
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


@app.delete("/api/admin/documents/{document_id}")
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


@app.put("/api/admin/documents/{document_id}/permissions")
def update_document_permissions(document_id: str, req: DocumentPermissionUpdate, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    doc = ensure_admin_document(db, document_id)
    doc.groups = db.execute(select(Group).where(Group.id.in_(req.group_ids))).scalars().all() if req.group_ids else []
    db.flush()
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)).scalars().all()
    try:
        upsert_document_chunks(doc, chunks)
    except QdrantUnavailable:
        pass
    audit(db, actor, "document.permissions_update", "document", doc.id, {"group_ids": req.group_ids})
    db.commit()
    return {"id": doc.id, "group_ids": [g.id for g in doc.groups]}


@app.post("/api/chat/attachments")
def upload_chat_attachment(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_user)):
    doc_id, storage_path, filename = save_upload(file, "chat")
    ext = Path(filename).suffix.lower()
    if ext not in CHAT_FILE_EXTENSIONS:
        storage_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="聊天附件支持 PDF、Word(.docx)、Excel(.xlsx)、CSV、TXT、Markdown、PNG、JPG、WEBP、GIF。")

    source_type = "chat_image" if ext in IMAGE_EXTENSIONS else f"chat_{ext.lstrip('.')}"
    doc = Document(id=doc_id, title=Path(filename).stem, filename=filename, storage_path=str(storage_path), source_type=source_type, created_by=user.id)
    db.add(doc)
    db.flush()
    task = enqueue_document_task(db, doc, "chat_attachment_parse", user)
    db.commit()
    return {"id": doc.id, "title": doc.title, "filename": filename, "kind": ext.lstrip("."), "searchable": False, "chunks": 0, "status": "queued", "task_id": task.id, "message": "附件已上传，正在后台解析/OCR。完成后会自动参与检索。"}


@app.post("/api/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(require_user)):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入问题")
    if req.session_id:
        existing = db.get(ChatSession, req.session_id)
        if not existing or existing.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    limit = max(1, min(req.top_k, 10))
    q_embedding = embed_texts([question])[0]
    group_ids = [g.id for g in user.groups]
    retrieval_backend = "sqlite"
    try:
        contexts = search_chunks(q_embedding, user.id, bool(user.is_admin), group_ids, limit)
        retrieval_backend = "qdrant"
        if not contexts:
            raise QdrantUnavailable("Qdrant 暂无命中，回退 SQLite")
    except QdrantUnavailable:
        rows = db.execute(select(DocumentChunk, Document).join(Document, Document.id == DocumentChunk.document_id)).all()
        scored = []
        for chunk, doc in rows:
            source_type = str(doc.source_type or "")
            is_personal = source_type.startswith("chat_")
            if is_personal:
                if doc.created_by != user.id:
                    continue
            elif not user.is_admin:
                if not group_ids:
                    continue
                allowed = db.execute(
                    select(document_group_link.c.group_id).where(
                        document_group_link.c.document_id == doc.id,
                        document_group_link.c.group_id.in_(group_ids),
                    )
                ).first()
                if not allowed:
                    continue
            scored.append(
                {
                    "document_id": doc.id,
                    "document_title": doc.title,
                    "filename": doc.filename,
                    "chunk_id": chunk.id,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "source_type": source_type,
                    "content": chunk.content,
                    "score": cosine_similarity(q_embedding, parse_embedding(chunk.embedding_json)),
                }
            )
        scored.sort(key=lambda x: x["score"], reverse=True)
        contexts = scored[:limit]
    sources = serialize_sources(contexts)
    if not contexts:
        answer = "没有在你有权限访问的内部文档或个人附件中找到相关内容。你可以换个问法，或先上传 PDF/Word/Excel/CSV/TXT/Markdown/图片附件。"
    else:
        cfg = get_model_config(db)
        answer = chat_answer(question, contexts, cfg["api_key"], cfg["base_url"], cfg["model"])
    session_id = req.session_id or new_id()
    if not req.session_id:
        db.add(ChatSession(id=session_id, user_id=user.id))
    user_message_id = new_id()
    assistant_message_id = new_id()
    db.add(ChatMessage(id=user_message_id, session_id=session_id, role="user", content=question))
    db.add(ChatMessage(id=assistant_message_id, session_id=session_id, role="assistant", content=answer, sources_json=json.dumps(sources, ensure_ascii=False)))
    audit(db, user, "chat.ask", "chat_session", session_id, {"retrieval_backend": retrieval_backend, "sources": len(sources)})
    db.commit()
    return {
        "session_id": session_id,
        "message_id": assistant_message_id,
        "assistant_message_id": assistant_message_id,
        "user_message_id": user_message_id,
        "answer": answer,
        "retrieval_backend": retrieval_backend,
        "sources": sources,
        "citations": sources,
        "source_count": len(sources),
    }


@app.post("/api/chat/feedback")
def submit_feedback(req: FeedbackCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="请输入反馈内容")
    if len(content) > 2000:
        raise HTTPException(status_code=400, detail="反馈内容不能超过 2000 字")
    rating = (req.rating or "").strip().lower()
    if len(rating) > 30:
        raise HTTPException(status_code=400, detail="反馈类型过长")
    session = None
    if req.session_id:
        session = db.get(ChatSession, req.session_id)
        if not session or session.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    message = None
    if req.message_id:
        message = db.get(ChatMessage, req.message_id)
        if not message or message.role != "assistant":
            raise HTTPException(status_code=404, detail="要反馈的回答不存在")
        msg_session = db.get(ChatSession, message.session_id)
        if not msg_session or msg_session.user_id != user.id:
            raise HTTPException(status_code=404, detail="要反馈的回答不存在")
        if session and message.session_id != session.id:
            raise HTTPException(status_code=400, detail="反馈消息不属于当前会话")
        session = msg_session
    question_snapshot = ""
    answer_snapshot = message.content if message else ""
    sources = parse_json_list(getattr(message, "sources_json", "[]")) if message else []
    if session:
        previous_messages = db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
        ).scalars().all()
        if message:
            before = [m for m in previous_messages if m.created_at <= message.created_at]
            question_snapshot = next((m.content for m in reversed(before) if m.role == "user"), "")
        else:
            question_snapshot = next((m.content for m in reversed(previous_messages) if m.role == "user"), "")
            answer_snapshot = next((m.content for m in reversed(previous_messages) if m.role == "assistant"), "")
            last_assistant = next((m for m in reversed(previous_messages) if m.role == "assistant"), None)
            sources = parse_json_list(getattr(last_assistant, "sources_json", "[]")) if last_assistant else []
    item = Feedback(
        id=new_id(),
        user_id=user.id,
        username=user.username,
        session_id=session.id if session else None,
        message_id=message.id if message else None,
        rating=rating,
        content=content,
        question_snapshot=question_snapshot[:4000],
        answer_snapshot=answer_snapshot[:8000],
        sources_json=json.dumps(sources, ensure_ascii=False),
    )
    db.add(item)
    audit(db, user, "feedback.submit", "feedback", item.id, {"session_id": item.session_id, "message_id": item.message_id, "rating": item.rating})
    db.commit()
    return {"ok": True, "id": item.id, "status": item.status, "message": "反馈已提交给管理员"}


CHAT_HTML = r'''
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>公司知识助手</title><style>
:root{--bg:#fff;--side:#f7f7f8;--hover:#ececf1;--line:#e5e7eb;--text:#171717;--sub:#6b7280;--weak:#9ca3af;--brand:#111827;--accent:#10a37f;--danger:#dc2626;--shadow:0 18px 48px rgba(15,23,42,.10)}*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}button,input,textarea{font:inherit}button{cursor:pointer}.app{height:100dvh;display:grid;grid-template-columns:280px minmax(0,1fr);overflow:hidden}.sidebar{background:var(--side);border-right:1px solid var(--line);padding:12px;display:flex;flex-direction:column;min-width:0}.side-top{display:flex;gap:8px;align-items:center;margin-bottom:12px}.brandmark{width:32px;height:32px;border-radius:10px;background:#111827;color:#fff;display:grid;place-items:center;font-weight:900}.new-btn{height:42px;border:1px solid var(--line);background:#fff;border-radius:12px;padding:0 12px;text-align:left;font-weight:700;display:flex;align-items:center;gap:9px}.new-btn:hover,.icon-btn:hover,.session-row:hover{background:var(--hover)}.side-title{font-size:12px;color:var(--weak);font-weight:800;margin:10px 8px}.session-list{overflow:auto;display:grid;gap:2px;padding-right:2px}.session-row{display:grid;grid-template-columns:minmax(0,1fr) 32px;align-items:center;border-radius:10px}.session-row.active{background:#e8e8ed}.session{min-width:0;border:0;background:transparent;text-align:left;padding:10px 10px;border-radius:10px}.session strong{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:14px}.session span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:var(--sub);font-size:12px;margin-top:3px}.session-delete{width:28px;height:28px;border:0;background:transparent;border-radius:8px;color:#9ca3af;font-size:18px}.session-delete:hover{background:#fee2e2;color:var(--danger)}.side-foot{margin-top:auto;display:grid;gap:8px}.account{display:flex;gap:9px;align-items:center;padding:10px;border-radius:12px}.avatar{width:30px;height:30px;border-radius:50%;background:#dbeafe;color:#1e40af;display:grid;place-items:center;font-size:12px;font-weight:900}.account strong{font-size:13px}.account p{margin:2px 0 0;color:var(--sub);font-size:12px}.chat{min-width:0;display:grid;grid-template-rows:56px minmax(0,1fr) auto}.chat-top{height:56px;border-bottom:1px solid var(--line);display:flex;align-items:center;justify-content:space-between;padding:0 18px}.chat-title{font-weight:800}.top-actions{display:flex;gap:8px;align-items:center}.icon-btn,.plain-btn{height:36px;border:1px solid var(--line);background:#fff;border-radius:10px;padding:0 12px;color:#374151;font-weight:700}.messages{overflow:auto;padding:28px 18px 18px}.inner{max-width:780px;margin:0 auto;display:flex;flex-direction:column;gap:24px}.hero{text-align:center;margin:8vh auto 0;max-width:720px}.hero-logo{width:52px;height:52px;border-radius:16px;background:#111827;color:#fff;margin:0 auto 18px;display:grid;place-items:center;font-weight:900}.hero h1{font-size:32px;line-height:1.15;letter-spacing:-.04em;margin:0 0 10px}.hero p{color:var(--sub);line-height:1.7;margin:0}.prompt-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:24px}.prompt{border:1px solid var(--line);background:#fff;border-radius:14px;text-align:left;padding:14px;color:#374151}.prompt:hover{background:#f9fafb}.prompt strong{display:block;color:#111827;margin-bottom:5px}.prompt span{font-size:13px;color:var(--sub);line-height:1.5}.message{display:flex;gap:14px;align-items:flex-start}.message.user{justify-content:flex-end}.message.ai{justify-content:flex-start}.bubble-avatar{width:30px;height:30px;border-radius:50%;background:#111827;color:#fff;display:grid;place-items:center;font-size:12px;font-weight:900;flex:0 0 auto}.message.user .bubble-avatar{display:none}.bubble{line-height:1.75;font-size:15px;max-width:100%;overflow-wrap:anywhere}.message.ai .bubble{padding-top:2px}.message.user .bubble{background:#f4f4f5;border-radius:18px;padding:11px 15px;max-width:min(620px,82%)}.bubble pre{background:#0f172a;color:#e5e7eb;border-radius:12px;padding:14px;overflow:auto}.bubble code{background:#f3f4f6;border-radius:6px;padding:2px 5px}.bubble pre code{background:transparent;padding:0}.bubble h2,.bubble h3{margin:10px 0 4px}.composer-wrap{padding:10px 18px 20px;background:linear-gradient(180deg,rgba(255,255,255,0),#fff 28%)}.upload-strip{max-width:780px;margin:0 auto 8px}.chip{display:inline-flex;align-items:center;border:1px solid var(--line);background:#f9fafb;border-radius:999px;padding:6px 9px;font-size:12px;color:#4b5563;margin:0 6px 6px 0}.chip.ready{background:#ecfdf5;border-color:#a7f3d0;color:#047857}.chip.failed{background:#fef2f2;border-color:#fecaca;color:#b91c1c}.composer{max-width:780px;margin:0 auto;border:1px solid #d1d5db;border-radius:18px;box-shadow:0 6px 20px rgba(15,23,42,.06);background:#fff;padding:10px}.composer.drag{outline:4px solid rgba(16,163,127,.12);border-color:#10a37f}textarea{width:100%;border:0;outline:0;resize:none;min-height:52px;max-height:180px;padding:8px;background:transparent;font-size:15px;line-height:1.55}.composer-row{border-top:1px solid #f1f5f9;display:flex;justify-content:space-between;align-items:center;gap:8px;padding-top:9px}.hint{font-size:12px;color:var(--sub)}.tools{display:flex;gap:8px}.send{height:36px;border:0;background:#111827;color:#fff;border-radius:10px;padding:0 14px;font-weight:800}.send:disabled{opacity:.55}.file-input{display:none}.drawer{position:fixed;top:0;right:0;bottom:0;width:min(420px,92vw);background:#fff;border-left:1px solid var(--line);box-shadow:var(--shadow);transform:translateX(105%);transition:.2s ease;z-index:30;display:flex;flex-direction:column}.drawer.open{transform:translateX(0)}.drawer-head{padding:16px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}.drawer-body{padding:16px;overflow:auto}.card{border:1px solid var(--line);border-radius:14px;padding:12px;margin-bottom:10px;background:#fff}.card strong{font-size:13px}.card p{font-size:12px;color:#64748b;line-height:1.65;margin:6px 0 0}.tag{display:inline-flex;border:1px solid #dbeafe;background:#eff6ff;color:#1d4ed8;border-radius:999px;padding:2px 7px;font-size:11px;font-weight:800}.tag.ready{background:#ecfdf5;border-color:#a7f3d0;color:#047857}.tag.failed{background:#fef2f2;border-color:#fecaca;color:#b91c1c}.tag.processing{background:#fff7ed;border-color:#fed7aa;color:#b45309}.modal{position:fixed;inset:0;background:rgba(15,23,42,.42);display:none;align-items:center;justify-content:center;padding:20px;z-index:50}.modal.open{display:flex}.dialog{width:min(420px,100%);background:#fff;border-radius:20px;padding:22px;box-shadow:var(--shadow)}.field{height:44px;border:1px solid #d1d5db;border-radius:12px;padding:0 12px;width:100%;outline:none}.form{display:grid;gap:10px}.dialog-actions{display:flex;gap:10px;margin-top:14px}.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);background:#111827;color:#fff;border-radius:999px;padding:10px 14px;font-size:13px;display:none;z-index:60}.toast.show{display:block}.mobile-menu{display:none}@media(max-width:860px){.app{grid-template-columns:1fr}.sidebar{display:none}.mobile-menu{display:inline-flex}.prompt-grid{grid-template-columns:1fr}.chat-top{padding:0 10px}.messages{padding:20px 12px}.composer-wrap{padding:8px 10px 14px}}
</style></head><body><div class="app"><aside class="sidebar"><div class="side-top"><div class="brandmark">AI</div><div><strong>知识助手</strong><div style="font-size:12px;color:#6b7280">Internal Copilot</div></div></div><button class="new-btn" onclick="newChat()">＋ 新建对话</button><div class="side-title">会话历史</div><div id="sessions" class="session-list"><div class="side-title">登录后同步历史</div></div><div class="side-foot"><div class="account"><div id="avatar" class="avatar">?</div><div><strong id="accountName">未登录</strong><p id="authState">登录后可使用权限知识库</p></div></div><button id="loginBtn" class="plain-btn" onclick="openLogin()">登录</button><button id="logoutBtn" class="plain-btn" onclick="logout()" style="display:none">退出登录</button><a id="adminLink" class="plain-btn" href="/admin" style="display:none;text-decoration:none;text-align:center;line-height:36px">后台管理</a></div></aside><main class="chat"><header class="chat-top"><button id="mobileAccountBtn" class="plain-btn mobile-menu" onclick="openLogin()">登录</button><div class="chat-title">公司知识助手</div><div class="top-actions"><button id="topAdminLink" class="plain-btn" onclick="location.href='/admin'" style="display:none">后台管理</button><button class="plain-btn" onclick="openSourceDrawer()">引用 / 状态</button></div></header><section id="msgs" class="messages"><div class="inner"><div class="hero"><div class="hero-logo">AI</div><h1>今天想了解什么？</h1><p>像 ChatGPT 一样提问。系统会先检索你有权限访问的公司文档、个人附件和图片识别结果，再生成回答。</p><div class="prompt-grid"><button class="prompt" onclick="askPrompt('帮我总结我能访问的文档重点')"><strong>总结资料</strong><span>按权限范围总结知识库重点。</span></button><button class="prompt" onclick="askPrompt('根据已上传附件，提炼关键信息')"><strong>分析附件</strong><span>上传 PDF/Word/Excel/CSV/TXT/Markdown/图片后提问。</span></button><button class="prompt" onclick="askPrompt('这个制度适用于哪些岗位？')"><strong>查权限</strong><span>只基于授权文档回答。</span></button><button class="prompt" onclick="askPrompt('列出回答的引用来源')"><strong>看引用</strong><span>回答后可在右侧查看命中片段。</span></button></div></div></div></section><div class="composer-wrap"><div id="uploadStrip" class="upload-strip"></div><div id="composer" class="composer"><textarea id="q" placeholder="给知识助手发送消息，或拖入文件…"></textarea><div class="composer-row"><div class="hint">支持 PDF / Word / Excel / CSV / TXT / MD / 图片，最大 30MB</div><div class="tools"><input id="fileInput" class="file-input" type="file" accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.gif" onchange="uploadSelectedFile(this.files[0])"><button class="plain-btn" onclick="chooseFile()">上传</button><button id="sendBtn" class="send" onclick="send()">发送</button></div></div></div></div></main></div><aside id="sourceDrawer" class="drawer"><div class="drawer-head"><div><strong>引用与解析状态</strong><div style="font-size:12px;color:#6b7280;margin-top:3px">查看最近命中的片段和附件解析结果</div></div><button class="plain-btn" onclick="closeSourceDrawer()">关闭</button></div><div class="drawer-body"><h3 style="margin:0 0 8px;font-size:14px">引用来源</h3><div id="sources"><div class="card"><strong>暂无引用</strong><p>发送问题后这里显示命中的文档片段。</p></div></div><h3 style="margin:18px 0 8px;font-size:14px">附件状态</h3><div id="statusList"><div class="card"><strong>暂无附件</strong><p>上传后显示解析、OCR 和索引状态。</p></div></div></div></aside><div id="loginModal" class="modal"><div class="dialog"><h3>登录知识助手</h3><p style="color:#6b7280;margin-top:4px">请输入你的公司账号。页面不会展示初始化密码。</p><div class="form"><input class="field" id="u" placeholder="账号" autocomplete="username"><input class="field" id="p" type="password" placeholder="密码" autocomplete="current-password"></div><div class="dialog-actions"><button id="modalLoginBtn" class="send" onclick="login()">登录</button><button class="plain-btn" onclick="closeLogin()">取消</button></div></div></div><div id="toast" class="toast"></div><script>
const $=id=>document.getElementById(id);let token=localStorage.token||'',currentUser=null,sessionId='',turn=0,isSending=false,isUploading=false;const msgs=$('msgs'),toast=$('toast'),sendBtn=$('sendBtn'),composer=$('composer');function escapeHtml(s){return String(s||'').replace(/[&<>'"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[m]))}function renderMarkdown(s){let html=escapeHtml(s||'');html=html.replace(/```([\s\S]*?)```/g,(m,c)=>'<pre><code>'+c.trim()+'</code></pre>');html=html.replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>').replace(/^- (.*)$/gm,'• $1');return html.replace(/\n/g,'<br>')}function showToast(t){toast.textContent=t;toast.classList.add('show');clearTimeout(window.tt);window.tt=setTimeout(()=>toast.classList.remove('show'),3300)}function openLogin(){$('loginModal').classList.add('open');setTimeout(()=>$('u').focus(),50)}function closeLogin(){$('loginModal').classList.remove('open')}function openSourceDrawer(){$('sourceDrawer').classList.add('open');loadStatuses()}function closeSourceDrawer(){$('sourceDrawer').classList.remove('open')}async function api(path,opt={}){opt.headers=Object.assign(token?{'Authorization':'Bearer '+token}:{},opt.headers||{});const r=await fetch(path,opt);const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||'请求失败');return j}function setAccount(user){currentUser=user;$('accountName').innerText=user.username;$('authState').innerText=user.is_admin?'管理员账号，可进入后台管理':'普通员工账号，仅显示授权知识库';$('avatar').innerText=user.username.slice(0,2).toUpperCase();$('loginBtn').style.display='none';$('logoutBtn').style.display='block';$('adminLink').style.display=user.is_admin?'block':'none';$('topAdminLink').style.display=user.is_admin?'inline-flex':'none';$('mobileAccountBtn').textContent='退出';$('mobileAccountBtn').onclick=logout}function resetAccount(){currentUser=null;$('accountName').innerText='未登录';$('authState').innerText='登录后可使用权限知识库';$('avatar').innerText='?';$('loginBtn').style.display='block';$('loginBtn').disabled=false;$('loginBtn').textContent='登录';$('logoutBtn').style.display='none';$('adminLink').style.display='none';$('topAdminLink').style.display='none';$('mobileAccountBtn').textContent='登录';$('mobileAccountBtn').onclick=openLogin;$('sessions').innerHTML='<div class="side-title">登录后同步历史</div>';$('statusList').innerHTML='<div class="card"><strong>暂无附件</strong><p>上传后显示解析、OCR 和索引状态。</p></div>'}function logout(){token='';localStorage.removeItem('token');sessionId='';turn=0;resetAccount();newChat();showToast('已退出登录')}async function initMe(){if(!token){resetAccount();return}try{const user=await api('/api/me');setAccount(user);await Promise.all([loadSessions(),loadStatuses()])}catch(e){localStorage.removeItem('token');token='';resetAccount()}}async function login(){if(!$('u').value.trim()||!$('p').value)return showToast('请输入账号和密码');$('modalLoginBtn').disabled=true;$('modalLoginBtn').textContent='登录中';try{const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('u').value.trim(),password:$('p').value})});const j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||'登录失败');token=j.token;localStorage.token=token;setAccount(j.user);closeLogin();await Promise.all([loadSessions(),loadStatuses()]);showToast('登录成功')}catch(e){showToast(e.message)}finally{$('modalLoginBtn').disabled=false;$('modalLoginBtn').textContent='登录'}}function resetHero(){msgs.innerHTML='<div class="inner"><div class="hero"><div class="hero-logo">AI</div><h1>今天想了解什么？</h1><p>像 ChatGPT 一样提问。系统会先检索你有权限访问的公司文档、个人附件和图片识别结果，再生成回答。</p><div class="prompt-grid"><button class="prompt" onclick="askPrompt(\'帮我总结我能访问的文档重点\')"><strong>总结资料</strong><span>按权限范围总结知识库重点。</span></button><button class="prompt" onclick="askPrompt(\'根据已上传附件，提炼关键信息\')"><strong>分析附件</strong><span>上传 PDF/Word/Excel/CSV/TXT/Markdown/图片后提问。</span></button><button class="prompt" onclick="askPrompt(\'这个制度适用于哪些岗位？\')"><strong>查权限</strong><span>只基于授权文档回答。</span></button><button class="prompt" onclick="askPrompt(\'列出回答的引用来源\')"><strong>看引用</strong><span>回答后可在右侧查看命中片段。</span></button></div></div></div>'}function newChat(){sessionId='';turn=0;$('sources').innerHTML='<div class="card"><strong>暂无引用</strong><p>发送问题后这里显示命中的文档片段。</p></div>';resetHero();document.querySelectorAll('.session-row').forEach(x=>x.classList.remove('active'))}async function loadSessions(){const list=await api('/api/chat/sessions');$('sessions').innerHTML=list.length?list.map(s=>'<div class="session-row '+(s.id===sessionId?'active':'')+'"><button class="session" onclick="openSession(\''+s.id+'\')"><strong>'+escapeHtml(s.title)+'</strong><span>'+escapeHtml(s.preview)+'</span></button><button class="session-delete" title="删除会话" onclick="deleteSession(event,\''+s.id+'\')">×</button></div>').join(''):'<div class="side-title">还没有历史会话</div>'}async function deleteSession(event,id){event.stopPropagation();if(!confirm('确定删除这条会话历史吗？'))return;await api('/api/chat/sessions/'+id,{method:'DELETE'});if(sessionId===id)newChat();await loadSessions();showToast('会话已删除')}async function openSession(id){const data=await api('/api/chat/sessions/'+id);sessionId=id;turn=data.messages.filter(m=>m.role==='user').length;msgs.innerHTML='<div class="inner"></div>';const inner=msgs.querySelector('.inner');data.messages.forEach(m=>appendMessage(m.role==='user'?'user':'ai',m.content,inner));await loadSessions()}function askPrompt(t){$('q').value=t;send()}function appendMessage(role,text,target){if(msgs.querySelector('.hero'))msgs.innerHTML='<div class="inner"></div>';const inner=target||msgs.querySelector('.inner');const div=document.createElement('div');div.className='message '+(role==='user'?'user':'ai');div.innerHTML=(role==='ai'?'<div class="bubble-avatar">AI</div>':'')+'<div class="bubble">'+(role==='ai'?renderMarkdown(text):escapeHtml(text))+'</div>';inner.appendChild(div);msgs.scrollTop=msgs.scrollHeight;return div}function renderSources(list){$('sources').innerHTML=(list||[]).map(s=>{const personal=String(s.source_type||'').startsWith('chat_');return '<div class="card"><strong>'+escapeHtml(s.document_title)+'</strong> <span class="tag">'+(personal?'个人附件':'授权文档')+'</span><p>'+escapeHtml(s.content)+'</p></div>'}).join('')||'<div class="card"><strong>暂无引用</strong><p>没有命中可引用片段。</p></div>'}async function send(){const text=$('q').value.trim();if(!text||isSending)return;if(!token){openLogin();return}isSending=true;sendBtn.disabled=true;sendBtn.textContent='发送中';appendMessage('user',text);$('q').value='';const loading=appendMessage('ai','正在检索授权文档和个人附件…');try{const j=await api('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:text,session_id:sessionId||null})});sessionId=j.session_id;loading.querySelector('.bubble').innerHTML=renderMarkdown(j.answer||'');renderSources(j.sources);await loadSessions()}catch(e){loading.querySelector('.bubble').textContent=e.message;showToast(e.message)}finally{isSending=false;sendBtn.disabled=false;sendBtn.textContent='发送'}}async function loadStatuses(){if(!token)return;try{const list=await api('/api/documents/status?scope=chat');$('statusList').innerHTML=list.length?list.slice(0,12).map(x=>'<div class="card"><strong>'+escapeHtml(x.title)+'</strong> <span class="tag '+escapeHtml(x.status)+'">'+escapeHtml({ready:'可检索',processing:'处理中',failed:'失败',pending:'等待'}[x.status]||x.status)+'</span><p>'+escapeHtml(x.message)+' '+(x.chunks?('片段：'+x.chunks):'')+'</p></div>').join(''):'<div class="card"><strong>暂无附件</strong><p>上传后显示解析、OCR 和索引状态。</p></div>'}catch(e){}}function chooseFile(){if(!token){openLogin();return}$('fileInput').click()}function addChip(t,cls=''){const c=document.createElement('span');c.className='chip '+cls;c.textContent=t;$('uploadStrip').appendChild(c);return c}async function uploadSelectedFile(file){if(!file)return;if(!token){openLogin();return}if(file.size>30*1024*1024)return showToast('文件不能超过 30MB');if(isUploading)return showToast('已有文件正在上传');isUploading=true;const chip=addChip('处理中：'+file.name);try{const fd=new FormData();fd.append('file',file);const j=await api('/api/chat/attachments',{method:'POST',body:fd});chip.textContent=(j.searchable?'可检索：':'已记录：')+j.filename;chip.className='chip '+(j.searchable?'ready':'failed');showToast(j.message);await loadStatuses()}catch(e){chip.textContent='失败：'+file.name;chip.className='chip failed';showToast(e.message);await loadStatuses()}finally{isUploading=false;$('fileInput').value=''}}['dragenter','dragover'].forEach(ev=>composer.addEventListener(ev,e=>{e.preventDefault();composer.classList.add('drag')}));['dragleave','drop'].forEach(ev=>composer.addEventListener(ev,e=>{e.preventDefault();composer.classList.remove('drag')}));composer.addEventListener('drop',e=>uploadSelectedFile(e.dataTransfer.files[0]));$('q').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();send()}});initMe();
</script></body></html>
'''


ADMIN_HTML = r'''
<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>知识助手控制台</title><style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e5e7eb;--text:#111827;--sub:#6b7280;--brand:#2563eb;--danger:#dc2626;--ok:#047857;--warn:#b45309;--shadow:0 16px 42px rgba(15,23,42,.06)}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}button,input,select{font:inherit}button{cursor:pointer}.layout{min-height:100dvh;display:grid;grid-template-columns:260px minmax(0,1fr);gap:16px;padding:16px}.side,.card,.topbar{background:#fff;border:1px solid var(--line);border-radius:20px;box-shadow:var(--shadow)}.side{padding:14px;display:flex;flex-direction:column;gap:16px}.brand{display:flex;gap:10px;align-items:center}.logo{width:36px;height:36px;border-radius:12px;background:#111827;color:#fff;display:grid;place-items:center;font-weight:900}.brand h1{font-size:15px;margin:0}.brand p{font-size:12px;color:var(--sub);margin:2px 0 0}.nav{display:grid;gap:6px}.nav button{height:40px;border:0;background:transparent;border-radius:12px;text-align:left;padding:0 12px;color:#4b5563;font-weight:800}.nav button.active,.nav button:hover{background:#f3f4f6;color:#111827}.login{margin-top:auto;background:#f9fafb;border:1px solid var(--line);border-radius:16px;padding:12px}.stack{display:grid;gap:9px}.field,select,input[type=file]{min-height:40px;border:1px solid #d1d5db;border-radius:11px;background:#fff;padding:0 11px;width:100%;outline:none}.btn{min-height:38px;border:1px solid #d1d5db;background:#fff;color:#374151;border-radius:11px;padding:0 12px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;gap:7px;text-decoration:none}.btn.primary{border-color:var(--brand);background:var(--brand);color:#fff}.btn.danger{border-color:#fecaca;color:#b91c1c;background:#fff}.main{display:grid;gap:14px;min-width:0}.topbar{padding:18px;display:flex;justify-content:space-between;gap:14px;align-items:center}.topbar h2{margin:0;font-size:22px}.topbar p{margin:5px 0 0;color:var(--sub);font-size:13px}.actions,.toolbar{display:flex;gap:8px;flex-wrap:wrap}.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.stat{background:#fff;border:1px solid var(--line);border-radius:18px;padding:15px}.stat span{font-size:12px;color:var(--sub);font-weight:900}.stat strong{font-size:26px;display:block;margin-top:7px}.card{overflow:hidden}.card-head{padding:15px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px;align-items:center}.card-head h3{margin:0}.card-body{padding:15px}.hide{display:none}.table-wrap{border:1px solid var(--line);border-radius:14px;overflow:auto}table{width:100%;border-collapse:collapse}th{background:#f9fafb;color:#6b7280;font-size:12px}th,td{padding:12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}.pill{display:inline-flex;border:1px solid var(--line);background:#f3f4f6;border-radius:999px;padding:4px 8px;font-size:12px;color:#4b5563;font-weight:800;margin:2px}.pill.ready{background:#ecfdf5;color:#047857}.pill.failed{background:#fef2f2;color:#b91c1c}.pill.processing{background:#fff7ed;color:#b45309}.perm-box{min-width:260px;display:grid;gap:8px}.perm-summary{font-size:12px;color:#6b7280;line-height:1.5}.perm-list{display:flex;flex-wrap:wrap;gap:8px}.perm-chip{min-height:34px;border:1px solid #d1d5db;background:#fff;color:#374151;border-radius:999px;padding:0 11px;font-size:12px;font-weight:800;display:inline-flex;align-items:center;gap:7px;transition:.15s ease}.perm-chip:hover{border-color:#93c5fd;background:#f8fafc}.perm-chip.selected{border-color:#2563eb;background:#eff6ff;color:#1d4ed8}.perm-chip.selected:before{content:'✓';font-weight:900}.perm-chip:not(.selected):before{content:'+';color:#9ca3af}.perm-clear{width:max-content;border:0;background:transparent;color:#64748b;font-size:12px;font-weight:800;padding:3px 0}.perm-clear:hover{color:#dc2626}.empty{border:1px dashed #cbd5e1;border-radius:14px;padding:24px;text-align:center;background:#f9fafb;color:#6b7280}.mask{position:fixed;inset:0;background:rgba(15,23,42,.38);display:none;z-index:20}.mask.open{display:block}.drawer{position:fixed;right:0;top:0;bottom:0;width:min(560px,94vw);background:#fff;box-shadow:-24px 0 80px rgba(15,23,42,.20);transform:translateX(100%);transition:.2s ease;z-index:21;display:flex;flex-direction:column}.drawer.open{transform:translateX(0)}.drawer-head{padding:18px;border-bottom:1px solid var(--line);display:flex;justify-content:space-between;gap:12px}.drawer-body{padding:18px;display:grid;gap:14px;overflow:auto}.label{font-size:13px;font-weight:900;color:#374151;margin-bottom:7px}.help,.muted{font-size:12px;color:#6b7280;line-height:1.6}.chunk{border:1px solid var(--line);border-radius:14px;padding:12px;background:#fff}.chunk pre{white-space:pre-wrap;word-break:break-word;margin:8px 0 0;color:#374151;font-size:13px;line-height:1.6}.toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:#111827;color:#fff;border-radius:999px;padding:10px 14px;font-size:13px;display:none;z-index:30}.toast.show{display:block}@media(max-width:1080px){.layout{display:block}.side{margin-bottom:14px}.stats{grid-template-columns:1fr}.topbar{display:block}.actions{margin-top:12px}}
</style></head><body><div class="layout"><aside class="side"><div class="brand"><div class="logo">AI</div><div><h1>权限控制台</h1><p>Knowledge Admin</p></div></div><nav class="nav"><button class="active" onclick="showTab('overview',this)">概览</button><button onclick="showTab('model',this)">模型配置</button><button onclick="showTab('groups',this)">岗位组</button><button onclick="showTab('users',this)">员工权限</button><button onclick="showTab('docs',this)">文档权限</button><button onclick="showTab('status',this)">解析状态</button><button onclick="showTab('tasks',this)">任务队列</button><button onclick="showTab('audit',this)">审计日志</button></nav><div class="login"><div class="stack" id="adminLoginForm"><input class="field" id="u" placeholder="账号" autocomplete="username"><input class="field" id="p" type="password" placeholder="密码" autocomplete="current-password"><button id="loginBtn" class="btn primary" onclick="login()">登录控制台</button><a class="btn" href="/chat">打开聊天页</a></div><div class="stack" id="adminAccount" style="display:none"><div class="empty" style="text-align:left"><strong id="adminName">未登录</strong><div class="muted" id="adminRole" style="margin-top:6px">管理员控制台</div></div><button class="btn danger" onclick="logout()">退出登录</button><a class="btn" href="/chat">返回聊天页</a></div></div></aside><main class="main"><section class="topbar"><div><h2>内部知识助手控制台</h2><p>管理模型、员工权限、文档授权、解析状态和文档生命周期。</p></div><div class="actions"><button class="btn" onclick="loadAll()">刷新</button><button class="btn" onclick="reindexVectors()">重建向量库</button><button class="btn primary" onclick="openDrawer('doc')">上传文档</button></div></section><section class="stats"><div class="stat"><span>员工</span><strong id="cUsers">0</strong></div><div class="stat"><span>岗位组</span><strong id="cGroups">0</strong></div><div class="stat"><span>文档</span><strong id="cDocs">0</strong></div><div class="stat"><span>模型 Key</span><strong id="cKey">-</strong></div></section><section id="overviewTab" class="card"><div class="card-head"><h3>上线前检查</h3></div><div class="card-body"><div class="table-wrap"><table><tr><th>能力</th><th>当前状态</th><th>建议</th></tr><tr><td>OCR/图片识别</td><td><span class="pill processing">已接入口</span></td><td>后台配置支持视觉输入的模型后即可使用。</td></tr><tr><td>会话历史</td><td><span class="pill ready">可用</span></td><td>聊天页左侧支持打开和删除历史。</td></tr><tr><td>文档解析状态</td><td><span class="pill ready">可用</span></td><td>上传后可查看解析阶段、片段数和失败原因。</td></tr><tr><td>生产化不足</td><td><span class="pill failed">待完善</span></td><td>建议补充真实向量库、审计日志、用户管理删除/重置密码、PDF OCR 队列。</td></tr></table></div></div></section><section id="modelTab" class="card hide"><div class="card-head"><h3>模型配置</h3><button class="btn primary" onclick="openDrawer('model')">编辑模型</button></div><div class="card-body"><div id="modelInfo" class="empty">登录后查看模型状态</div></div></section><section id="groupsTab" class="card hide"><div class="card-head"><h3>岗位组</h3><div class="toolbar"><input class="field" id="groupFilter" placeholder="筛选岗位组" style="max-width:220px" oninput="render()"><button class="btn primary" onclick="openDrawer('group')">新增岗位组</button></div></div><div class="card-body" id="groupsList"></div></section><section id="usersTab" class="card hide"><div class="card-head"><h3>员工访问权限</h3><div class="toolbar"><input class="field" id="userFilter" placeholder="筛选员工" style="max-width:220px" oninput="render()"><button class="btn primary" onclick="openDrawer('user')">新增员工</button></div></div><div class="card-body" id="usersList"></div></section><section id="docsTab" class="card hide"><div class="card-head"><h3>文档权限</h3><div class="toolbar"><input class="field" id="docFilter" placeholder="筛选文档" style="max-width:220px" oninput="render()"><button class="btn primary" onclick="openDrawer('doc')">上传文档</button></div></div><div class="card-body" id="docsList"></div></section><section id="statusTab" class="card hide"><div class="card-head"><h3>文档解析状态</h3><button class="btn" onclick="loadStatuses()">刷新状态</button></div><div class="card-body" id="statusList"></div></section><section id="tasksTab" class="card hide"><div class="card-head"><h3>后台任务队列</h3><button class="btn" onclick="loadTasks()">刷新任务</button></div><div class="card-body" id="tasksList"></div></section><section id="auditTab" class="card hide"><div class="card-head"><h3>审计日志</h3><button class="btn" onclick="loadAuditLogs()">刷新日志</button></div><div class="card-body" id="auditList"></div></section></main></div><div id="mask" class="mask" onclick="closeDrawer()"></div><aside id="drawer" class="drawer"><div class="drawer-head"><div><h3 id="drawerTitle">编辑</h3><p id="drawerDesc" class="muted">填写必要信息后保存。</p></div><button class="btn" onclick="closeDrawer()">关闭</button></div><div id="drawerBody" class="drawer-body"></div></aside><div id="toast" class="toast"></div><script>
let token=localStorage.token||'',adminUser=null,groups=[],users=[],docs=[],modelCfg={},statuses=[],tasks=[],auditLogs=[];const tabs={overview:overviewTab,model:modelTab,groups:groupsTab,users:usersTab,docs:docsTab,status:statusTab,tasks:tasksTab,audit:auditTab};function escapeHtml(s){return String(s||'').replace(/[&<>'"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[m]))}function showToast(t){toast.textContent=t;toast.classList.add('show');clearTimeout(window.tt);window.tt=setTimeout(()=>toast.classList.remove('show'),3000)}function showTab(n,b){Object.values(tabs).forEach(x=>x.classList.add('hide'));tabs[n].classList.remove('hide');document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));if(b)b.classList.add('active');if(n==='status')loadStatuses();if(n==='tasks')loadTasks();if(n==='audit')loadAuditLogs()}async function api(path,opt={}){opt.headers=Object.assign(token?{'Authorization':'Bearer '+token}:{},opt.headers||{});let r=await fetch(path,opt),j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||'请求失败');return j}function setAdminAccount(user){adminUser=user;adminName.innerText=user.username;adminRole.innerText='管理员账号 · 已登录';adminLoginForm.style.display='none';adminAccount.style.display='grid'}function resetAdminAccount(){adminUser=null;adminLoginForm.style.display='grid';adminAccount.style.display='none';cUsers.innerText='0';cGroups.innerText='0';cDocs.innerText='0';cKey.innerText='-';modelInfo.innerHTML='<div class="empty">登录后查看模型状态</div>'}function logout(){token='';localStorage.removeItem('token');groups=[];users=[];docs=[];statuses=[];tasks=[];auditLogs=[];resetAdminAccount();render();statusList.innerHTML=empty('暂无解析状态。');tasksList.innerHTML=empty('暂无后台任务。');auditList.innerHTML=empty('暂无审计日志。');showToast('已退出登录')}async function login(){if(!u.value.trim()||!p.value)return showToast('请输入账号和密码');loginBtn.disabled=true;loginBtn.textContent='登录中';try{let r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u.value.trim(),password:p.value})});let j=await r.json().catch(()=>({}));if(!r.ok)throw new Error(j.detail||'登录失败');if(!j.user.is_admin)throw new Error('只有管理员可以进入后台控制台');token=j.token;localStorage.token=token;setAdminAccount(j.user);await loadAll();showToast('登录成功')}catch(e){localStorage.removeItem('token');token='';resetAdminAccount();showToast(e.message)}finally{loginBtn.disabled=false;loginBtn.textContent='登录控制台'}}async function loadAll(){try{const me=await api('/api/me');if(!me.is_admin)throw new Error('只有管理员可以进入后台控制台');setAdminAccount(me);modelCfg=await api('/api/admin/model');groups=await api('/api/admin/groups');users=await api('/api/admin/users');docs=await api('/api/admin/documents');await loadStatuses(false);cUsers.innerText=users.length;cGroups.innerText=groups.length;cDocs.innerText=docs.length;cKey.innerText=modelCfg.api_key_set?'已配置':'未配置';modelInfo.innerHTML='<div class="table-wrap"><table><tr><th>项目</th><th>当前值</th></tr><tr><td>Base URL</td><td>'+escapeHtml(modelCfg.base_url)+'</td></tr><tr><td>模型</td><td>'+escapeHtml(modelCfg.model)+'</td></tr><tr><td>API Key</td><td>'+(modelCfg.api_key_set?'<span class="pill ready">已安全保存</span>':'<span class="pill failed">未配置</span>')+'</td></tr></table></div>';render()}catch(e){localStorage.removeItem('token');token='';resetAdminAccount();showToast(e.message||'请先登录控制台')}}function empty(text){return '<div class="empty">'+escapeHtml(text)+'</div>'}function statusPill(s){return '<span class="pill '+escapeHtml(s||'')+'">'+escapeHtml({ready:'可检索',processing:'处理中',failed:'失败',pending:'等待'}[s]||s||'未知')+'</span>'}function renderPermBox(d){const selected=(d.groups||[]).map(x=>x.id);if(!groups.length)return '<div class="perm-box"><div class="perm-summary">还没有岗位组，请先创建岗位组。</div></div>';const summary=selected.length?('已授权 '+selected.length+' 个岗位组'):'未授权给任何普通员工';return '<div class="perm-box"><div class="perm-summary">'+summary+'</div><div class="perm-list">'+groups.map(g=>'<button type="button" class="perm-chip '+(selected.includes(g.id)?'selected':'')+'" onclick="togglePerm(\''+d.id+'\',\''+g.id+'\')">'+escapeHtml(g.name)+'</button>').join('')+'</div>'+(selected.length?'<button type="button" class="perm-clear" onclick="clearPerms(\''+d.id+'\')">清空授权</button>':'')+'<div class="help">点击岗位组即可授权；再次点击即可取消。</div></div>'}function render(){let gf=(groupFilter?.value||'').toLowerCase(),uf=(userFilter?.value||'').toLowerCase(),df=(docFilter?.value||'').toLowerCase();let gs=groups.filter(g=>g.name.toLowerCase().includes(gf));groupsList.innerHTML=gs.length?'<div class="table-wrap"><table><tr><th>岗位组</th><th>组 ID</th></tr>'+gs.map(g=>'<tr><td><span class="pill">'+escapeHtml(g.name)+'</span></td><td class="muted">'+escapeHtml(g.id)+'</td></tr>').join('')+'</table></div>':empty('还没有岗位组。');let us=users.filter(x=>x.username.toLowerCase().includes(uf));usersList.innerHTML=us.length?'<div class="table-wrap"><table><tr><th>员工</th><th>岗位组</th><th>角色/状态</th><th>操作</th></tr>'+us.map(x=>'<tr><td><strong>'+escapeHtml(x.username)+'</strong></td><td>'+(x.groups.length?x.groups.map(g=>'<span class="pill">'+escapeHtml(g.name)+'</span>').join(' '):'<span class="muted">未分配</span>')+'</td><td>'+(x.is_admin?'<span class="pill">管理员</span>':'<span class="pill">员工</span>')+(x.is_active?'<span class="pill ready">启用</span>':'<span class="pill failed">停用</span>')+'</td><td><div class="toolbar"><button class="btn" onclick="toggleUser(\''+x.id+'\','+(!x.is_active)+')">'+(x.is_active?'停用':'启用')+'</button><button class="btn" onclick="resetPassword(\''+x.id+'\')">重置密码</button><button class="btn danger" onclick="deleteUser(\''+x.id+'\')">删除</button></div></td></tr>').join('')+'</table></div>':empty('还没有员工账号。');let ds=docs.filter(d=>(d.title||'').toLowerCase().includes(df)||(d.filename||'').toLowerCase().includes(df));docsList.innerHTML=ds.length?'<div class="table-wrap"><table><tr><th>文档</th><th>状态</th><th>授权岗位组</th><th>操作</th></tr>'+ds.map(d=>'<tr><td><strong>'+escapeHtml(d.title)+'</strong><div class="muted">'+escapeHtml(d.filename)+' · '+escapeHtml((d.created_at||'').slice(0,10))+'</div></td><td>'+statusPill(d.status)+'<div class="muted">片段：'+escapeHtml(d.chunks||0)+'</div></td><td>'+renderPermBox(d)+'</td><td><div class="toolbar"><button class="btn" onclick="viewChunks(\''+d.id+'\')">片段</button><button class="btn" onclick="reparseDoc(\''+d.id+'\')">重解析</button><button class="btn danger" onclick="deleteDoc(\''+d.id+'\')">删除</button></div></td></tr>').join('')+'</table></div>':empty('还没有上传知识库文档。')}async function loadStatuses(show=true){try{statuses=await api('/api/documents/status?scope=admin');statusList.innerHTML=statuses.length?'<div class="table-wrap"><table><tr><th>文档</th><th>状态</th><th>阶段</th><th>说明</th><th>片段</th></tr>'+statuses.map(x=>'<tr><td><strong>'+escapeHtml(x.title)+'</strong><div class="muted">'+escapeHtml(x.filename)+'</div></td><td>'+statusPill(x.status)+'</td><td>'+escapeHtml(x.stage)+'</td><td class="muted">'+escapeHtml(x.message)+'</td><td>'+escapeHtml(x.chunks)+'</td></tr>').join('')+'</table></div>':empty('暂无解析状态。')}catch(e){if(show)showToast(e.message)}}function openDrawer(type){mask.classList.add('open');drawer.classList.add('open');if(type==='model'){drawerTitle.innerText='配置模型';drawerDesc.innerText='图片识别需要填写支持视觉输入的 OpenAI-compatible 模型。';drawerBody.innerHTML='<div><div class="label">API Key</div><input class="field" id="apiKey" type="password" placeholder="粘贴 API Key"></div><div><div class="label">Base URL</div><input class="field" id="baseUrl" value="'+escapeHtml(modelCfg.base_url||'https://api.deepseek.com')+'"></div><div><div class="label">模型名</div><input class="field" id="model" value="'+escapeHtml(modelCfg.model||'deepseek-chat')+'"><div class="help">文本问答可用 deepseek-chat；图片 OCR/识别需要配置支持视觉输入的模型。</div></div><button class="btn primary" onclick="saveModel()">保存配置</button>'}if(type==='group'){drawerTitle.innerText='新增岗位组';drawerDesc.innerText='岗位组建议按真实权限边界划分。';drawerBody.innerHTML='<div><div class="label">岗位组名称</div><input class="field" id="newGroup" placeholder="例如：财务部、销售部、管理层"></div><button class="btn primary" onclick="addGroup()">创建岗位组</button>'}if(type==='user'){drawerTitle.innerText='新增员工';drawerDesc.innerText='员工使用同一个聊天页，但只能检索所属岗位组文档。';drawerBody.innerHTML='<div><div class="label">账号</div><input class="field" id="newUser" placeholder="员工账号"></div><div><div class="label">初始密码</div><input class="field" id="newPass" type="password" placeholder="设置密码"></div><div><div class="label">岗位组</div><select id="userGroup" class="field"><option value="">暂不分配</option>'+groups.map(g=>'<option value="'+g.id+'">'+escapeHtml(g.name)+'</option>').join('')+'</select></div><button class="btn primary" onclick="addUser()">创建员工</button>'}if(type==='doc'){drawerTitle.innerText='上传知识库文档';drawerDesc.innerText='支持 PDF、Word、Excel、CSV、TXT、Markdown，上传后进入后台解析队列。';drawerBody.innerHTML='<div><div class="label">知识库文件</div><input type="file" id="file" accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.markdown"><div class="help">单文件最大 30MB；旧版 .doc/.xls 请先另存为 .docx/.xlsx；扫描件 PDF 后续建议接入 PDF OCR 队列。</div></div><button class="btn primary" onclick="uploadDoc()">上传并解析</button>'}}function closeDrawer(){mask.classList.remove('open');drawer.classList.remove('open')}async function saveModel(){await api('/api/admin/model',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:apiKey.value,base_url:baseUrl.value,model:model.value})});closeDrawer();await loadAll();showToast('模型配置已保存')}async function addGroup(){if(!newGroup.value.trim())return showToast('请输入岗位组名称');await api('/api/admin/groups',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:newGroup.value.trim()})});closeDrawer();await loadAll();showToast('岗位组已创建')}async function addUser(){if(!newUser.value.trim()||!newPass.value.trim())return showToast('请输入账号和密码');await api('/api/admin/users',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:newUser.value.trim(),password:newPass.value,group_ids:userGroup.value?[userGroup.value]:[]})});closeDrawer();await loadAll();showToast('员工已创建')}async function uploadDoc(){if(!file.files[0])return showToast('请选择知识库文件');if(file.files[0].size>30*1024*1024)return showToast('文件不能超过 30MB');let fd=new FormData();fd.append('file',file.files[0]);showToast('正在上传解析，请稍等');await api('/api/admin/documents',{method:'POST',body:fd});closeDrawer();await loadAll();showToast('文档已上传，解析状态已更新')}async function reindexVectors(){if(!confirm('确定把现有文档片段同步到 Qdrant 向量库吗？'))return;showToast('正在重建向量库');try{const j=await api('/api/admin/vector/reindex',{method:'POST'});showToast(j.ok?'向量库已重建，片段：'+j.chunks:j.message)}catch(e){showToast(e.message)}}async function toggleUser(id,isActive){await api('/api/admin/users/'+id+'/status',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({is_active:isActive})});await loadAll();showToast(isActive?'账号已启用':'账号已停用')}async function resetPassword(id){const pwd=prompt('请输入新密码，至少 8 位');if(!pwd)return;if(pwd.length<8)return showToast('新密码至少 8 位');await api('/api/admin/users/'+id+'/reset-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pwd})});showToast('密码已重置')}async function deleteUser(id){if(!confirm('确定删除这个员工账号吗？'))return;await api('/api/admin/users/'+id,{method:'DELETE'});await loadAll();showToast('员工已删除')}async function loadTasks(){try{tasks=await api('/api/admin/tasks');tasksList.innerHTML=tasks.length?'<div class="table-wrap"><table><tr><th>任务</th><th>文档</th><th>状态</th><th>错误</th><th>操作</th></tr>'+tasks.map(t=>'<tr><td><strong>'+escapeHtml(t.task_type)+'</strong><div class="muted">'+escapeHtml((t.created_at||'').replace('T',' ').slice(0,19))+'</div></td><td>'+escapeHtml(t.document_title||t.document_id||'-')+'</td><td>'+statusPill(t.status)+'</td><td class="muted">'+escapeHtml(t.last_error||'')+'</td><td>'+(t.status==='running'?'<span class="muted">执行中</span>':'<button class="btn" onclick="retryTask(\''+t.id+'\')">重试</button>')+'</td></tr>').join('')+'</table></div>':empty('暂无后台任务。')}catch(e){showToast(e.message)}}async function retryTask(id){await api('/api/admin/tasks/'+id+'/retry',{method:'POST'});await loadTasks();showToast('任务已重新入队')}async function loadAuditLogs(){try{auditLogs=await api('/api/admin/audit-logs');auditList.innerHTML=auditLogs.length?'<div class="table-wrap"><table><tr><th>时间</th><th>操作者</th><th>动作</th><th>对象</th><th>详情</th></tr>'+auditLogs.map(x=>'<tr><td class="muted">'+escapeHtml((x.created_at||'').replace('T',' ').slice(0,19))+'</td><td>'+escapeHtml(x.actor_username)+'</td><td><span class="pill">'+escapeHtml(x.action)+'</span></td><td>'+escapeHtml(x.resource_type)+' '+escapeHtml(x.resource_id||'')+'</td><td class="muted">'+escapeHtml(JSON.stringify(x.detail||{}))+'</td></tr>').join('')+'</table></div>':empty('暂无审计日志。')}catch(e){showToast(e.message)}}async function savePerm(id,groupIds){document.querySelectorAll('.perm-chip,.perm-clear').forEach(x=>x.disabled=true);try{await api('/api/admin/documents/'+id+'/permissions',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({group_ids:groupIds})});docs=await api('/api/admin/documents');render();showToast('文档权限已更新')}finally{document.querySelectorAll('.perm-chip,.perm-clear').forEach(x=>x.disabled=false)}}function togglePerm(docId,groupId){const d=docs.find(x=>x.id===docId);if(!d)return;const ids=(d.groups||[]).map(x=>x.id);const next=ids.includes(groupId)?ids.filter(x=>x!==groupId):[...ids,groupId];savePerm(docId,next)}function clearPerms(docId){savePerm(docId,[])}async function viewChunks(id){mask.classList.add('open');drawer.classList.add('open');drawerTitle.innerText='文档片段';drawerDesc.innerText='查看当前文档被索引的文本片段。';drawerBody.innerHTML='<div class="empty">正在加载片段…</div>';try{const j=await api('/api/admin/documents/'+id+'/chunks');drawerBody.innerHTML=j.chunks.length?j.chunks.map(c=>'<div class="chunk"><strong>#'+escapeHtml(c.chunk_index)+' · 页码 '+escapeHtml(c.page_number||'未知')+'</strong><pre>'+escapeHtml(c.content)+'</pre></div>').join(''):'<div class="empty">暂无可检索片段。</div>'}catch(e){drawerBody.innerHTML='<div class="empty">'+escapeHtml(e.message)+'</div>'}}async function reparseDoc(id){if(!confirm('确定重新解析这个文档吗？会覆盖旧片段索引。'))return;showToast('正在重新解析');await api('/api/admin/documents/'+id+'/reparse',{method:'POST'});await loadAll();showToast('重新解析完成')}async function deleteDoc(id){if(!confirm('确定删除这个文档吗？这会同时删除片段、解析状态和权限配置。'))return;await api('/api/admin/documents/'+id,{method:'DELETE'});await loadAll();showToast('文档已删除')}loadAll();
</script></body></html>
'''
