from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Document, DocumentChunk, DocumentProcessingStatus, WikiCompileStatus, WikiPage, WikiPageSource

MAX_WIKI_SOURCE_CHUNKS = 24
MAX_EXTRACT_CHARS = 9000


def _new_id() -> str:
    return str(uuid.uuid4())


def _compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _slugify_title(title: str, fallback: str) -> str:
    raw = _compact_spaces(title).lower()
    raw = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "-", raw).strip("-")
    raw = raw[:80].strip("-")
    return raw or fallback


def _document_slug(doc: Document) -> str:
    return f"doc-{str(doc.id)[:8]}-{_slugify_title(doc.title or doc.filename or 'document', str(doc.id)[:8])}"


def _wiki_checksum(doc: Document, chunks: list[DocumentChunk]) -> str:
    digest = hashlib.sha256()
    digest.update(str(doc.id).encode("utf-8"))
    digest.update(str(doc.title or "").encode("utf-8"))
    digest.update(str(doc.filename or "").encode("utf-8"))
    for chunk in chunks:
        digest.update(str(chunk.id).encode("utf-8"))
        digest.update(str(chunk.chunk_index).encode("utf-8"))
        digest.update((chunk.content or "").encode("utf-8"))
    return digest.hexdigest()


def _sentence_candidates(text: str, limit: int = 6) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    pieces = re.split(r"(?<=[。！？!?；;\.])\s*", normalized)
    cleaned: list[str] = []
    for piece in pieces:
        item = piece.strip(" -\t\r\n")
        if len(item) < 12:
            continue
        cleaned.append(item[:240])
        if len(cleaned) >= limit:
            break
    if cleaned:
        return cleaned
    return [normalized[:240]]


def _extractive_summary(chunks: list[DocumentChunk]) -> str:
    text = "\n".join((chunk.content or "") for chunk in chunks[:8])[:MAX_EXTRACT_CHARS]
    bullets = _sentence_candidates(text, limit=5)
    if not bullets:
        return ""
    return "\n".join(f"- {item}" for item in bullets)


def _source_excerpt(chunk: DocumentChunk, max_chars: int = 700) -> str:
    text = _compact_spaces(chunk.content or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def build_document_wiki_markdown(doc: Document, chunks: list[DocumentChunk]) -> tuple[str, str]:
    """Compile one source document into a stable Markdown wiki page.

    This first compiler is intentionally deterministic: it does not call an LLM, so
    ingestion stays reliable. Later passes can replace the extractive sections with
    LLM-written entity/concept/rule pages while keeping the same storage contract.
    """

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    title = doc.title or doc.filename or "Untitled document"
    summary = _extractive_summary(chunks)
    body_parts: list[str] = [
        "---",
        f"title: {title}",
        "type: source",
        f"source_document_id: {doc.id}",
        f"knowledge_scope: {getattr(doc, 'knowledge_scope', 'production') or 'production'}",
        f"compiled_at: {now}",
        "---",
        "",
        f"# {title}",
        "",
        "## 编译摘要",
        summary or "- 暂无足够文本生成摘要。",
        "",
        "## 结构化笔记",
        "这是一页由系统从原始文档自动编译的 Wiki 源文档页。问答优先使用本页，再按引用回到原始材料核验。",
        "",
        "## 关键原文摘录",
    ]
    for chunk in chunks[:MAX_WIKI_SOURCE_CHUNKS]:
        page = f"第 {chunk.page_number} 页" if chunk.page_number else "未标页码"
        body_parts.extend(
            [
                "",
                f"### 片段 {chunk.chunk_index} · {page}",
                _source_excerpt(chunk),
            ]
        )
    body_parts.extend(
        [
            "",
            "## 原始证据",
            f"- 原始文档：{doc.title or doc.filename}",
            f"- 文档 ID：`{doc.id}`",
            f"- 文件名：`{doc.filename}`",
        ]
    )
    return "\n".join(body_parts).strip() + "\n", summary


def _set_compile_status(db: Session, doc_id: str, status: str, message: str = "", page_count: int = 0, error_message: str = "") -> WikiCompileStatus:
    row = db.get(WikiCompileStatus, doc_id)
    if not row:
        row = WikiCompileStatus(document_id=doc_id)
        db.add(row)
    row.status = status
    row.message = message
    row.page_count = page_count
    row.error_message = error_message
    row.updated_at = datetime.utcnow()
    return row


def compile_document_to_wiki(db: Session, document_id: str, *, publish: bool = True) -> dict[str, Any]:
    doc = db.get(Document, document_id)
    if not doc:
        raise ValueError("document not found")
    chunks = db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index.asc())
    ).scalars().all()
    if not chunks:
        _set_compile_status(db, doc.id, "failed", error_message="document has no chunks")
        db.flush()
        return {"ok": False, "status": "failed", "document_id": doc.id, "page_count": 0, "error": "document has no chunks"}

    slug = _document_slug(doc)
    scope = getattr(doc, "knowledge_scope", "production") or "production"
    checksum = _wiki_checksum(doc, chunks)
    page = db.execute(select(WikiPage).where(WikiPage.slug == slug, WikiPage.knowledge_scope == scope)).scalar_one_or_none()
    if not page:
        page = WikiPage(id=_new_id(), slug=slug, knowledge_scope=scope)
        db.add(page)

    content_md, summary = build_document_wiki_markdown(doc, chunks)
    page.title = doc.title or doc.filename or "Untitled document"
    page.page_type = "source"
    page.status = "published" if publish else "draft"
    page.summary = summary
    page.content_md = content_md
    page.checksum = checksum
    page.confidence = 0.72
    page.updated_at = datetime.utcnow()

    db.flush()
    db.execute(delete(WikiPageSource).where(WikiPageSource.page_id == page.id))
    for order, chunk in enumerate(chunks[:MAX_WIKI_SOURCE_CHUNKS]):
        db.add(
            WikiPageSource(
                id=_new_id(),
                page_id=page.id,
                document_id=doc.id,
                chunk_id=chunk.id,
                page_number=chunk.page_number,
                source_order=order,
                quote=_source_excerpt(chunk, max_chars=360),
            )
        )
    _set_compile_status(db, doc.id, "ready", "compiled source wiki page", 1, "")
    db.flush()
    return {"ok": True, "status": "ready", "document_id": doc.id, "page_id": page.id, "slug": page.slug, "page_count": 1}


def compile_ready_documents(db: Session, *, knowledge_scope: str = "production", limit: int = 50, publish: bool = True) -> dict[str, Any]:
    stmt = (
        select(Document)
        .join(DocumentProcessingStatus, DocumentProcessingStatus.document_id == Document.id)
        .where(DocumentProcessingStatus.status == "ready")
        .where(Document.knowledge_scope == knowledge_scope)
        .order_by(Document.created_at.asc())
        .limit(max(1, min(limit, 200)))
    )
    docs = db.execute(stmt).scalars().all()
    results = [compile_document_to_wiki(db, doc.id, publish=publish) for doc in docs]
    return {
        "ok": True,
        "knowledge_scope": knowledge_scope,
        "document_count": len(docs),
        "compiled_count": sum(1 for item in results if item.get("ok")),
        "results": results,
    }
