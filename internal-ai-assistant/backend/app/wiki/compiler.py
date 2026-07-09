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
MAX_FACT_BULLETS = 12
COMPILER_VERSION = "deterministic-source-v2"
PROMPT_VERSION = "no-llm-v1"
DEFAULT_SOURCE_CONFIDENCE = 0.74


def _new_id() -> str:
    return str(uuid.uuid4())


def _compact_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _yaml_scalar(value: Any) -> str:
    text = str(value or "")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


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


def document_wiki_checksum(doc: Document, chunks: list[DocumentChunk]) -> str:
    """Public checksum helper used by wiki health checks."""

    return _wiki_checksum(doc, chunks)


def _sentence_candidates(text: str, limit: int = 6) -> list[str]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return []
    pieces = re.split(r"(?<=[。！？；.!?;])\s*", normalized)
    cleaned: list[str] = []
    for piece in pieces:
        item = piece.strip(" -\t\r\n")
        if len(item) < 12:
            continue
        cleaned.append(item[:260])
        if len(cleaned) >= limit:
            break
    if cleaned:
        return cleaned
    return [normalized[:260]]


def _summary_sentences(chunks: list[DocumentChunk], limit: int = 5) -> list[tuple[str, int]]:
    selected: list[tuple[str, int]] = []
    for order, chunk in enumerate(chunks[:MAX_WIKI_SOURCE_CHUNKS]):
        for sentence in _sentence_candidates(chunk.content or "", limit=3):
            selected.append((sentence, order))
            if len(selected) >= limit:
                return selected
    return selected


def _extractive_summary(chunks: list[DocumentChunk]) -> tuple[str, str]:
    candidates = _summary_sentences(chunks, limit=5)
    if not candidates:
        return "", ""
    summary_md = "\n".join(f"- {sentence} [S{order + 1}]" for sentence, order in candidates)
    summary_text = " ".join(sentence for sentence, _ in candidates)[:1200]
    return summary_md, summary_text


def _fact_bullets(chunks: list[DocumentChunk]) -> str:
    bullets: list[str] = []
    seen: set[str] = set()
    for order, chunk in enumerate(chunks[:MAX_WIKI_SOURCE_CHUNKS]):
        for sentence in _sentence_candidates(chunk.content or "", limit=4):
            key = _compact_spaces(sentence)[:80]
            if key in seen:
                continue
            seen.add(key)
            bullets.append(f"- {sentence} [S{order + 1}]")
            if len(bullets) >= MAX_FACT_BULLETS:
                return "\n".join(bullets)
    return "\n".join(bullets)


def _source_excerpt(chunk: DocumentChunk, max_chars: int = 700) -> str:
    text = _compact_spaces(chunk.content or "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _page_label(chunk: DocumentChunk) -> str:
    return f"第 {chunk.page_number} 页" if chunk.page_number else "未标页码"


def _confidence_for_chunks(chunks: list[DocumentChunk]) -> float:
    # Deterministic source pages are less risky than free-form LLM pages, but
    # confidence should still reflect source coverage instead of pretending all
    # compiled pages are perfect.
    coverage_boost = min(0.12, max(0, len(chunks) - 1) * 0.01)
    return round(min(0.86, DEFAULT_SOURCE_CONFIDENCE + coverage_boost), 2)


def build_document_wiki_markdown(doc: Document, chunks: list[DocumentChunk]) -> tuple[str, str]:
    """Compile one source document into a stable, cited Markdown wiki page.

    This compiler is intentionally deterministic: it does not call an LLM, so
    ingestion stays reliable. It still follows the LLM-Wiki safety contract we
    borrowed from the reference projects: every generated claim is traceable to
    a numbered source chunk, and the page records compiler/prompt provenance.
    Later LLM passes can generate entity/concept/rule pages on top of the same
    source index without replacing this auditable source page.
    """

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    title = doc.title or doc.filename or "Untitled document"
    scope = getattr(doc, "knowledge_scope", "production") or "production"
    summary_md, summary_text = _extractive_summary(chunks)
    fact_bullets = _fact_bullets(chunks)
    confidence = _confidence_for_chunks(chunks)
    body_parts: list[str] = [
        "---",
        f"title: {_yaml_scalar(title)}",
        "type: source",
        f"source_document_id: {_yaml_scalar(doc.id)}",
        f"knowledge_scope: {_yaml_scalar(scope)}",
        f"compiler_version: {_yaml_scalar(COMPILER_VERSION)}",
        f"prompt_version: {_yaml_scalar(PROMPT_VERSION)}",
        f"confidence: {confidence}",
        f"source_chunk_count: {len(chunks)}",
        f"compiled_at: {_yaml_scalar(now)}",
        "---",
        "",
        f"# {title}",
        "",
        "> 本页由系统从原始文档确定性编译生成。正文中的 [S1]、[S2] 等编号对应下方“来源索引”，用于核验每条事实。",
        "",
        "## 编译摘要",
        summary_md or "- 暂无足够文本生成摘要。",
        "",
        "## 关键事实（带来源编号）",
        fact_bullets or "- 暂无可抽取事实。",
        "",
        "## 结构化笔记",
        f"- 页面类型：source（原始文档摘要页）",
        f"- 原始文档：{title}",
        f"- 知识范围：{scope}",
        f"- 编译器版本：{COMPILER_VERSION}",
        f"- 引用规则：回答时优先使用带来源编号的事实；无法由来源编号支持的内容必须标记为资料不足。",
        "",
        "## 关键原文摘录",
    ]
    for order, chunk in enumerate(chunks[:MAX_WIKI_SOURCE_CHUNKS], start=1):
        body_parts.extend(
            [
                "",
                f"### [S{order}] 片段 {chunk.chunk_index} · {_page_label(chunk)}",
                _source_excerpt(chunk),
            ]
        )
    body_parts.extend(
        [
            "",
            "## 来源索引",
        ]
    )
    for order, chunk in enumerate(chunks[:MAX_WIKI_SOURCE_CHUNKS], start=1):
        body_parts.append(
            f"- [S{order}] 原始文档：{title}；文档 ID：`{doc.id}`；chunk：`{chunk.id}`；页码：{_page_label(chunk)}。"
        )
    body_parts.extend(
        [
            "",
            "## 原始证据",
            f"- 原始文档：{title}",
            f"- 文档 ID：`{doc.id}`",
            f"- 文件名：`{doc.filename}`",
        ]
    )
    return "\n".join(body_parts).strip() + "\n", summary_text


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
    page.confidence = _confidence_for_chunks(chunks)
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
    _set_compile_status(db, doc.id, "ready", f"compiled source wiki page with {COMPILER_VERSION}", 1, "")
    db.flush()
    return {
        "ok": True,
        "status": "ready",
        "document_id": doc.id,
        "page_id": page.id,
        "slug": page.slug,
        "page_count": 1,
        "checksum": checksum,
        "compiler_version": COMPILER_VERSION,
    }


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
