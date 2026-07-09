from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Document, DocumentChunk, DocumentProcessingStatus, WikiCompileStatus, WikiPage, WikiPageLink, WikiPageSource

MAX_WIKI_SOURCE_CHUNKS = 24
MAX_FACT_BULLETS = 12
MAX_DERIVED_PAGES = 6
COMPILER_VERSION = "deterministic-wiki-v2"
PROMPT_VERSION = "deterministic-derived-pages-v1"
DEFAULT_SOURCE_CONFIDENCE = 0.74
DEFAULT_DERIVED_CONFIDENCE = 0.68


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


def _derived_slug(doc: Document, page_type: str, title: str) -> str:
    return f"{page_type}-{str(doc.id)[:8]}-{_slugify_title(title, page_type)}"


def _norm_token(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


DERIVED_PAGE_PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "page_type": "process",
        "suffix": "流程",
        "section": "流程页",
        "keywords": ("流程", "步骤", "操作", "办理", "发起", "审核", "签署", "注册", "认证", "归档", "派单", "交付"),
    },
    {
        "page_type": "rule",
        "suffix": "规则",
        "section": "规则页",
        "keywords": ("规则", "要求", "必须", "不得", "截止", "权限", "审核", "条件", "标准", "范围", "限制"),
    },
    {
        "page_type": "entity",
        "suffix": "对象",
        "section": "实体页",
        "keywords": ("员工", "客户", "公司", "账户", "合同", "岗位", "部门", "城市", "单位", "材料", "表单", "系统"),
    },
    {
        "page_type": "concept",
        "suffix": "概念",
        "section": "概念页",
        "keywords": ("概述", "说明", "定义", "平台", "系统", "产品", "服务", "业务", "知识", "主题"),
    },
)


def _keyword_score(text: str, keywords: tuple[str, ...]) -> int:
    compact = _norm_token(text)
    return sum(1 for keyword in keywords if _norm_token(keyword) in compact)


def _select_chunks_by_keywords(chunks: list[DocumentChunk], keywords: tuple[str, ...], limit: int = 8) -> list[DocumentChunk]:
    scored: list[tuple[int, int, DocumentChunk]] = []
    for order, chunk in enumerate(chunks[:MAX_WIKI_SOURCE_CHUNKS]):
        score = _keyword_score(chunk.content or "", keywords)
        if score > 0:
            scored.append((score, -order, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [chunk for _score, _order, chunk in scored[:limit]]


def _derived_page_specs(doc: Document, chunks: list[DocumentChunk]) -> list[dict[str, Any]]:
    title = doc.title or doc.filename or "Untitled document"
    specs: list[dict[str, Any]] = []
    used_titles: set[str] = set()
    for pattern in DERIVED_PAGE_PATTERNS:
        selected = _select_chunks_by_keywords(chunks, pattern["keywords"])
        if not selected:
            continue
        page_title = f"{title}{pattern['suffix']}"
        if page_title in used_titles:
            continue
        used_titles.add(page_title)
        specs.append(
            {
                "page_type": pattern["page_type"],
                "section": pattern["section"],
                "title": page_title,
                "slug": _derived_slug(doc, pattern["page_type"], page_title),
                "keywords": pattern["keywords"],
                "chunks": selected,
            }
        )
        if len(specs) >= MAX_DERIVED_PAGES:
            break
    return specs


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


def _source_marker_for_chunk(chunks: list[DocumentChunk], chunk: DocumentChunk) -> int:
    for idx, item in enumerate(chunks[:MAX_WIKI_SOURCE_CHUNKS], start=1):
        if item.id == chunk.id:
            return idx
    return 1


def _link_line(title: str, slug: str) -> str:
    return f"[[{title}|{slug}]]"


def build_derived_wiki_markdown(
    doc: Document,
    all_chunks: list[DocumentChunk],
    spec: dict[str, Any],
    *,
    source_title: str,
    source_slug: str,
    sibling_links: list[tuple[str, str]],
) -> tuple[str, str]:
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    title = str(spec["title"])
    scope = getattr(doc, "knowledge_scope", "production") or "production"
    selected: list[DocumentChunk] = list(spec.get("chunks") or [])
    facts: list[str] = []
    summary_sentences: list[str] = []
    for chunk in selected:
        source_no = _source_marker_for_chunk(all_chunks, chunk)
        for sentence in _sentence_candidates(chunk.content or "", limit=2):
            if sentence not in summary_sentences:
                summary_sentences.append(sentence)
            facts.append(f"- {sentence} [S{source_no}]")
            if len(facts) >= 8:
                break
        if len(facts) >= 8:
            break
    summary_text = " ".join(summary_sentences)[:900]
    related_links = [_link_line(source_title, source_slug)]
    related_links.extend(_link_line(link_title, link_slug) for link_title, link_slug in sibling_links if link_slug != str(spec["slug"]))
    body_parts: list[str] = [
        "---",
        f"title: {_yaml_scalar(title)}",
        f"type: {spec['page_type']}",
        f"source_document_id: {_yaml_scalar(doc.id)}",
        f"knowledge_scope: {_yaml_scalar(scope)}",
        f"compiler_version: {_yaml_scalar(COMPILER_VERSION)}",
        f"prompt_version: {_yaml_scalar(PROMPT_VERSION)}",
        f"confidence: {DEFAULT_DERIVED_CONFIDENCE}",
        f"source_chunk_count: {len(selected)}",
        f"compiled_at: {_yaml_scalar(now)}",
        "---",
        "",
        f"# {title}",
        "",
        f"> 本页由 Wiki 编译器 v2 从原始文档 {_link_line(source_title, source_slug)} 中抽取生成；所有事实均保留 [Sx] 来源标记。",
        "",
        f"## {spec['section']}摘要",
        "\n".join(facts[:5]) or "- 暂无足够可抽取内容 [S1]",
        "",
        "## 关键事实",
        "\n".join(facts) or "- 暂无足够可抽取事实 [S1]",
        "",
        "## 相关 Wiki 页面",
    ]
    for link in list(dict.fromkeys(related_links))[:8]:
        body_parts.append(f"- {link}")
    body_parts.extend(
        [
            "",
            "## 来源索引",
        ]
    )
    for chunk in selected:
        source_no = _source_marker_for_chunk(all_chunks, chunk)
        body_parts.append(
            f"- [S{source_no}] 原始文档：{source_title}；文档 ID：`{doc.id}`；chunk：`{chunk.id}`；页码：{_page_label(chunk)}。"
        )
    return "\n".join(body_parts).strip() + "\n", summary_text


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


def _upsert_wiki_page(db: Session, *, slug: str, scope: str) -> WikiPage:
    page = db.execute(select(WikiPage).where(WikiPage.slug == slug, WikiPage.knowledge_scope == scope)).scalar_one_or_none()
    if not page:
        page = WikiPage(id=_new_id(), slug=slug, knowledge_scope=scope)
        db.add(page)
    return page


def _replace_page_sources(db: Session, page: WikiPage, doc: Document, chunks: list[DocumentChunk]) -> None:
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


def _replace_page_links(db: Session, page: WikiPage, targets: list[WikiPage], *, link_type: str = "wikilink") -> None:
    db.flush()
    db.execute(
        delete(WikiPageLink)
        .where(WikiPageLink.source_page_id == page.id)
        .where(WikiPageLink.link_type == link_type)
    )
    seen: set[str] = set()
    for target in targets:
        if not target.id or target.id == page.id or target.id in seen:
            continue
        seen.add(target.id)
        db.add(
            WikiPageLink(
                id=_new_id(),
                source_page_id=page.id,
                target_page_id=target.id,
                link_type=link_type,
                anchor_text=target.title or target.slug or link_type,
            )
        )


def _delete_stale_derived_pages(db: Session, doc: Document, scope: str, active_slugs: set[str]) -> int:
    stale_pages = (
        db.execute(
            select(WikiPage)
            .join(WikiPageSource, WikiPageSource.page_id == WikiPage.id)
            .where(WikiPageSource.document_id == doc.id)
            .where(WikiPage.knowledge_scope == scope)
            .where(WikiPage.page_type != "source")
            .where(WikiPage.slug.notin_(active_slugs))
        )
        .unique()
        .scalars()
        .all()
    )
    compiler_prefixes = tuple(f"{pattern['page_type']}-" for pattern in DERIVED_PAGE_PATTERNS)
    deleted = 0
    for page in stale_pages:
        if not page.slug.startswith(compiler_prefixes):
            continue
        db.execute(delete(WikiPageLink).where(WikiPageLink.source_page_id == page.id))
        db.execute(delete(WikiPageLink).where(WikiPageLink.target_page_id == page.id))
        db.execute(delete(WikiPageSource).where(WikiPageSource.page_id == page.id))
        db.delete(page)
        deleted += 1
    return deleted

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

    source_slug = _document_slug(doc)
    scope = getattr(doc, "knowledge_scope", "production") or "production"
    checksum = _wiki_checksum(doc, chunks)
    source_page = _upsert_wiki_page(db, slug=source_slug, scope=scope)

    derived_specs = _derived_page_specs(doc, chunks)
    sibling_links = [(str(spec["title"]), str(spec["slug"])) for spec in derived_specs]

    content_md, summary = build_document_wiki_markdown(doc, chunks)
    if sibling_links:
        related_lines = ["", "## Wiki 编译器 v2 生成页"]
        related_lines.extend(f"- {_link_line(title, slug)}" for title, slug in sibling_links)
        content_md = content_md.rstrip() + "\n" + "\n".join(related_lines) + "\n"
    source_page.title = doc.title or doc.filename or "Untitled document"
    source_page.page_type = "source"
    source_page.status = "published" if publish else "draft"
    source_page.summary = summary
    source_page.content_md = content_md
    source_page.checksum = checksum
    source_page.confidence = _confidence_for_chunks(chunks)
    source_page.updated_at = datetime.utcnow()
    _replace_page_sources(db, source_page, doc, chunks)

    db.flush()
    derived_pages: list[WikiPage] = []
    for spec in derived_specs:
        page = _upsert_wiki_page(db, slug=str(spec["slug"]), scope=scope)
        derived_md, derived_summary = build_derived_wiki_markdown(
            doc,
            chunks,
            spec,
            source_title=source_page.title,
            source_slug=source_page.slug,
            sibling_links=sibling_links,
        )
        page.title = str(spec["title"])
        page.page_type = str(spec["page_type"])
        page.status = "published" if publish else "draft"
        page.summary = derived_summary
        page.content_md = derived_md
        page.checksum = f"{checksum}:{spec['page_type']}"
        page.confidence = DEFAULT_DERIVED_CONFIDENCE
        page.updated_at = datetime.utcnow()
        _replace_page_sources(db, page, doc, list(spec.get("chunks") or chunks[:1]))
        derived_pages.append(page)

    db.flush()
    _replace_page_links(db, source_page, derived_pages, link_type="compiler_v2")
    for page in derived_pages:
        targets = [source_page] + [other for other in derived_pages if other.id != page.id]
        _replace_page_links(db, page, targets, link_type="compiler_v2")
    stale_deleted_count = _delete_stale_derived_pages(
        db,
        doc,
        scope,
        {str(page.slug) for page in derived_pages},
    )

    page_count = 1 + len(derived_pages)
    _set_compile_status(db, doc.id, "ready", f"compiled wiki v2 pages with {COMPILER_VERSION}", page_count, "")
    db.flush()
    return {
        "ok": True,
        "status": "ready",
        "document_id": doc.id,
        "page_id": source_page.id,
        "slug": source_page.slug,
        "page_count": page_count,
        "derived_page_count": len(derived_pages),
        "stale_deleted_count": stale_deleted_count,
        "derived_pages": [
            {"id": page.id, "slug": page.slug, "title": page.title, "page_type": page.page_type}
            for page in derived_pages
        ],
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
