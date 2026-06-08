from __future__ import annotations

import json
import os
import re
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from .config import PAGEINDEX_DIR, PAGEINDEX_ENABLED, PAGEINDEX_MIN_CHARS, PAGEINDEX_REPO_PATH
from .models import Document, DocumentPageIndex

NATIVE_OFFICIAL_PAGEINDEX_EXTENSIONS = {".pdf", ".md", ".markdown"}
TEXT_TO_MARKDOWN_PAGEINDEX_EXTENSIONS = {".docx", ".pptx", ".xlsx", ".csv", ".txt"}
IMAGE_PAGEINDEX_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SUPPORTED_PAGEINDEX_EXTENSIONS = NATIVE_OFFICIAL_PAGEINDEX_EXTENSIONS | TEXT_TO_MARKDOWN_PAGEINDEX_EXTENSIONS | IMAGE_PAGEINDEX_EXTENSIONS


PageTextLike = Iterable[tuple[int | None, str]]


def _utcnow() -> datetime:
    return datetime.utcnow()


def _normalize_text(text: str, limit: int | None = None) -> str:
    normalized = " ".join(str(text or "").split())
    if limit and len(normalized) > limit:
        return normalized[:limit].rstrip() + "..."
    return normalized


def _safe_filename_stem(filename: str) -> str:
    stem = Path(filename or "document").stem.strip()
    return stem or "document"


def _total_text_chars(pages: list[tuple[int | None, str]] | None) -> int:
    return sum(len(text or "") for _, text in (pages or []))


def _count_nodes(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes or []:
        total += 1
        total += _count_nodes(node.get("nodes") or [])
    return total


def _document_index_dir(document_id: str) -> Path:
    return PAGEINDEX_DIR / document_id


def _index_json_path(document_id: str) -> Path:
    return _document_index_dir(document_id) / "index.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_under_pageindex_dir(path: Path) -> bool:
    try:
        root = PAGEINDEX_DIR.resolve()
        resolved = path.resolve()
        return resolved == root or root in resolved.parents
    except Exception:
        return False


def can_build_pageindex(doc: Document, pages: list[tuple[int | None, str]] | None = None) -> tuple[bool, str]:
    if not PAGEINDEX_ENABLED:
        return False, "pageindex_disabled"
    ext = Path(doc.filename or "").suffix.lower()
    if ext not in SUPPORTED_PAGEINDEX_EXTENSIONS:
        return False, f"unsupported_extension:{ext or 'unknown'}"
    if pages is not None and _total_text_chars(pages) < PAGEINDEX_MIN_CHARS:
        return False, f"too_short:{_total_text_chars(pages)}<{PAGEINDEX_MIN_CHARS}"
    return True, "supported"


def _ensure_row(db: Session, doc: Document) -> DocumentPageIndex:
    row = db.get(DocumentPageIndex, doc.id)
    if not row:
        row = DocumentPageIndex(document_id=doc.id)
        db.add(row)
    row.updated_at = _utcnow()
    return row


def mark_pageindex_pending(db: Session, doc: Document, message: str = "queued") -> DocumentPageIndex:
    row = _ensure_row(db, doc)
    row.status = "pending"
    row.index_type = "pageindex"
    row.engine = row.engine or "pending"
    row.error_message = message
    row.updated_at = _utcnow()
    db.flush()
    return row


def delete_pageindex_files(document_id: str) -> None:
    target = _document_index_dir(document_id)
    if target.exists() and _is_under_pageindex_dir(target):
        shutil.rmtree(target, ignore_errors=True)


def _flatten_structure_titles(nodes: list[dict[str, Any]]) -> list[str]:
    titles: list[str] = []
    for node in nodes or []:
        title = str(node.get("title") or "").strip()
        if title:
            titles.append(title)
        titles.extend(_flatten_structure_titles(node.get("nodes") or []))
    return titles


def _node_id(counter: list[int]) -> str:
    value = counter[0]
    counter[0] += 1
    return f"{value:04d}"


def _first_line_title(text: str, fallback: str, max_len: int = 80) -> str:
    for raw in str(text or "").splitlines():
        line = " ".join(raw.strip().split())
        if line:
            return line[:max_len]
    return fallback


def _build_pdf_like_structure(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counter = [0]
    if not pages:
        return []

    # Keep small documents flat. For larger documents, group every five pages so the
    # structure behaves more like a table of contents and remains readable in admin UI.
    if len(pages) <= 20:
        nodes = []
        for page in pages:
            page_no = int(page.get("page") or len(nodes) + 1)
            content = str(page.get("content") or "")
            nodes.append(
                {
                    "title": _first_line_title(content, f"Page {page_no}"),
                    "node_id": _node_id(counter),
                    "start_index": page_no,
                    "end_index": page_no,
                    "summary": _normalize_text(content, 500),
                }
            )
        return nodes

    grouped: list[dict[str, Any]] = []
    for start in range(0, len(pages), 5):
        group = pages[start : start + 5]
        start_page = int(group[0].get("page") or start + 1)
        end_page = int(group[-1].get("page") or start_page)
        group_text = "\n".join(str(p.get("content") or "") for p in group)
        children = []
        for page in group:
            page_no = int(page.get("page") or len(children) + start_page)
            content = str(page.get("content") or "")
            children.append(
                {
                    "title": _first_line_title(content, f"Page {page_no}"),
                    "node_id": _node_id(counter),
                    "start_index": page_no,
                    "end_index": page_no,
                    "summary": _normalize_text(content, 350),
                }
            )
        grouped.append(
            {
                "title": f"Pages {start_page}-{end_page}",
                "node_id": _node_id(counter),
                "start_index": start_page,
                "end_index": end_page,
                "summary": _normalize_text(group_text, 700),
                "nodes": children,
            }
        )
    return grouped


def _build_markdown_structure(markdown: str) -> list[dict[str, Any]]:
    lines = str(markdown or "").splitlines()
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    raw_nodes: list[dict[str, Any]] = []
    counter = [0]

    for idx, line in enumerate(lines, start=1):
        match = heading_re.match(line)
        if not match:
            continue
        raw_nodes.append(
            {
                "level": len(match.group(1)),
                "title": match.group(2).strip()[:120],
                "node_id": _node_id(counter),
                "start_index": idx,
                "end_index": len(lines),
                "line_num": idx,
                "nodes": [],
            }
        )

    if not raw_nodes:
        return [
            {
                "title": _first_line_title(markdown, "Markdown Document"),
                "node_id": _node_id(counter),
                "start_index": 1,
                "end_index": max(1, len(lines)),
                "line_num": 1,
                "summary": _normalize_text(markdown, 800),
            }
        ]

    for i, node in enumerate(raw_nodes):
        next_start = len(lines) + 1
        for later in raw_nodes[i + 1 :]:
            if later["level"] <= node["level"]:
                next_start = later["start_index"]
                break
        node["end_index"] = max(node["start_index"], next_start - 1)
        start = max(0, node["start_index"] - 1)
        end = max(start + 1, node["end_index"])
        node["summary"] = _normalize_text("\n".join(lines[start:end]), 700)

    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for node in raw_nodes:
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        public_node = {k: v for k, v in node.items() if k != "level"}
        internal_node = {**public_node, "level": node["level"]}
        if stack:
            stack[-1].setdefault("nodes", []).append(public_node)
        else:
            roots.append(public_node)
        stack.append(internal_node)
    return roots


def _normalise_pages(pages: list[tuple[int | None, str]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for idx, (page_number, content) in enumerate(pages or [], start=1):
        normalized.append({"page": int(page_number or idx), "content": str(content or "")})
    return normalized


def _markdown_escape_title(text: str, fallback: str) -> str:
    title = " ".join(str(text or "").strip().split()) or fallback
    title = title.replace("#", "").strip() or fallback
    return title[:120]


def _content_preview_title(text: str, fallback: str) -> str:
    first = _first_line_title(str(text or ""), fallback, max_len=90)
    first = re.sub(r"^\[[^\]]+\]\s*", "", first).strip()
    return _markdown_escape_title(first, fallback)


def _pages_to_markdown(doc: Document, pages: list[tuple[int | None, str]]) -> str:
    ext = Path(doc.filename or "").suffix.lower()
    doc_title = _markdown_escape_title(doc.title or _safe_filename_stem(doc.filename or "document"), "Document")
    lines: list[str] = [f"# {doc_title}", "", f"- 原始文件：{doc.filename or doc.title or doc.id}", f"- 转换来源：{ext or 'unknown'}", ""]

    if ext in {".md", ".markdown"}:
        markdown = "\n\n".join(str(text or "") for _, text in pages).strip()
        if markdown:
            return markdown

    if ext == ".docx":
        lines.extend(["## Word 文档内容", ""])
        for idx, (_, text) in enumerate(pages or [], start=1):
            content = str(text or "").strip()
            if content:
                lines.extend([f"### 第 {idx} 部分", "", content, ""])
    elif ext == ".pptx":
        lines.extend(["## PowerPoint 幻灯片", ""])
        for idx, (page_number, text) in enumerate(pages or [], start=1):
            content = str(text or "").strip()
            if content:
                slide_no = int(page_number or idx)
                title = _content_preview_title(content, f"幻灯片 {slide_no}")
                lines.extend([f"### 幻灯片 {slide_no}：{title}", "", content, ""])
    elif ext in {".xlsx", ".csv"}:
        lines.extend(["## 表格数据", ""])
        for idx, (page_number, text) in enumerate(pages or [], start=1):
            content = str(text or "").strip()
            if content:
                sheet_no = int(page_number or idx)
                title = _content_preview_title(content, f"表格 {sheet_no}")
                lines.extend([f"### {title}", "", "```text", content, "```", ""])
    elif ext == ".txt":
        lines.extend(["## 文本文档", ""])
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", "\n".join(str(text or "") for _, text in pages)) if p.strip()]
        if paragraphs:
            for idx, paragraph in enumerate(paragraphs, start=1):
                title = _content_preview_title(paragraph, f"段落 {idx}")
                lines.extend([f"### {title}", "", paragraph, ""])
        else:
            lines.append("\n".join(str(text or "") for _, text in pages).strip())
    elif ext in IMAGE_PAGEINDEX_EXTENSIONS:
        lines.extend(["## 图片 OCR 内容", ""])
        content = "\n\n".join(str(text or "").strip() for _, text in pages if str(text or "").strip())
        if content:
            lines.extend(["### 识别文本", "", content, ""])
    else:
        lines.extend(["## 文档内容", ""])
        for idx, (_, text) in enumerate(pages or [], start=1):
            content = str(text or "").strip()
            if content:
                title = _content_preview_title(content, f"内容 {idx}")
                lines.extend([f"### {title}", "", content, ""])

    markdown = "\n".join(lines).strip()
    if markdown.count("\n#") == 0 and markdown.startswith("# "):
        markdown += "\n\n## 内容\n\n暂无可转换内容。"
    return markdown + "\n"


def _converted_markdown_path(doc: Document) -> Path:
    return _document_index_dir(doc.id) / "converted_input.md"


def _write_converted_markdown(doc: Document, pages: list[tuple[int | None, str]]) -> Path:
    path = _converted_markdown_path(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_pages_to_markdown(doc, pages), encoding="utf-8")
    return path


def _build_lightweight_index(doc: Document, pages: list[tuple[int | None, str]]) -> tuple[dict[str, Any], str, str | None]:
    ext = Path(doc.filename or "").suffix.lower()
    normalized_pages = _normalise_pages(pages)
    doc_name = doc.filename or doc.title or doc.id
    if ext == ".pdf":
        structure = _build_pdf_like_structure(normalized_pages)
        page_count_key = "page_count"
        page_count_value = len(normalized_pages)
        payload_pages = normalized_pages
        doc_type = "pdf"
    else:
        markdown = _pages_to_markdown(doc, pages)
        structure = _build_markdown_structure(markdown)
        page_count_key = "line_count"
        page_count_value = max(1, len(markdown.splitlines()))
        payload_pages = []
        doc_type = "md"

    all_text = "\n".join(page.get("content", "") for page in normalized_pages) or "\n".join(text or "" for _, text in pages)
    payload: dict[str, Any] = {
        "id": doc.id,
        "internal_document_id": doc.id,
        "type": doc_type,
        "path": doc.storage_path,
        "doc_name": doc_name,
        "doc_description": _normalize_text(all_text, 900),
        page_count_key: page_count_value,
        "structure": structure,
        "engine": "lightweight-page-tree",
        "source": "internal-fallback",
    }
    if payload_pages:
        payload["pages"] = payload_pages
    return payload, "lightweight-page-tree", None


def _candidate_pageindex_repo_paths() -> list[Path]:
    candidates: list[Path] = []
    if PAGEINDEX_REPO_PATH:
        candidates.append(Path(PAGEINDEX_REPO_PATH).expanduser())
    env_path = os.getenv("PAGEINDEX_SOURCE_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    # Optional vendored location if the project owner later chooses to add the MIT repo.
    candidates.append(Path(__file__).resolve().parents[2] / "third_party" / "PageIndex")
    return candidates


def _load_official_client_class() -> tuple[Any | None, str]:
    last_error = ""
    for candidate in _candidate_pageindex_repo_paths():
        if not (candidate / "pageindex" / "client.py").exists():
            continue
        candidate_str = str(candidate.resolve())
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)
        try:
            from pageindex import PageIndexClient  # type: ignore

            return PageIndexClient, candidate_str
        except Exception as exc:  # dependency missing or import error
            last_error = f"{candidate_str}: {exc}"
    return None, last_error or "official_pageindex_source_not_found"


def _configure_litellm_env(cfg: dict | None) -> None:
    cfg = cfg or {}
    api_key = str(cfg.get("api_key") or "").strip()
    base_url = str(cfg.get("base_url") or "").strip()
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
    if base_url:
        os.environ["OPENAI_API_BASE"] = base_url
        os.environ["OPENAI_BASE_URL"] = base_url


def _official_model_name(cfg: dict | None) -> str | None:
    env_model = os.getenv("PAGEINDEX_MODEL", "").strip()
    if env_model:
        return env_model
    cfg = cfg or {}
    model = str(cfg.get("model") or "").strip()
    base_url = str(cfg.get("base_url") or "").strip()
    if base_url and model and "/" not in model:
        return f"openai/{model}"
    return model or None


def _build_official_index(doc: Document, cfg: dict | None, pages: list[tuple[int | None, str]]) -> tuple[dict[str, Any], str, str | None]:
    PageIndexClient, source = _load_official_client_class()
    if PageIndexClient is None:
        raise RuntimeError(source)

    _configure_litellm_env(cfg)
    workspace = _document_index_dir(doc.id) / "official-workspace"
    if workspace.exists() and _is_under_pageindex_dir(workspace):
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)

    model = _official_model_name(cfg)
    client = PageIndexClient(
        api_key=(cfg or {}).get("api_key") or None,
        model=model,
        retrieve_model=os.getenv("PAGEINDEX_RETRIEVE_MODEL", "").strip() or model,
        workspace=str(workspace),
    )
    ext = Path(doc.filename or "").suffix.lower()
    if ext in NATIVE_OFFICIAL_PAGEINDEX_EXTENSIONS:
        index_input_path = doc.storage_path
        index_mode = "auto"
    else:
        index_input_path = str(_write_converted_markdown(doc, pages))
        index_mode = "md"
    workspace_doc_id = client.index(index_input_path, mode=index_mode)
    official_json = workspace / f"{workspace_doc_id}.json"
    if not official_json.exists():
        raise RuntimeError("official_pageindex_output_missing")
    payload = _read_json(official_json)
    payload["internal_document_id"] = doc.id
    payload["workspace_doc_id"] = workspace_doc_id
    payload["engine"] = "official-pageindex"
    payload["source"] = source
    payload["input_mode"] = "native" if ext in NATIVE_OFFICIAL_PAGEINDEX_EXTENSIONS else "converted-markdown"
    payload["original_extension"] = ext or "unknown"
    return payload, "official-pageindex", workspace_doc_id


def build_pageindex_for_document(
    db: Session,
    doc: Document,
    pages: list[tuple[int | None, str]],
    cfg: Optional[dict] = None,
    force: bool = False,
) -> DocumentPageIndex | None:
    allowed, reason = can_build_pageindex(doc, pages)
    if not allowed and not force:
        return None
    if not pages:
        raise ValueError("pageindex_requires_extracted_text")

    row = _ensure_row(db, doc)
    row.status = "processing"
    row.index_type = "pageindex"
    row.engine = "processing"
    row.error_message = ""
    row.updated_at = _utcnow()
    db.flush()

    delete_pageindex_files(doc.id)
    output_path = _index_json_path(doc.id)
    official_error = ""
    payload: dict[str, Any] | None = None
    engine = ""
    workspace_doc_id: str | None = None

    if not os.getenv("PAGEINDEX_FORCE_LIGHTWEIGHT", "").strip():
        try:
            payload, engine, workspace_doc_id = _build_official_index(doc, cfg, pages)
        except Exception as exc:
            official_error = f"official PageIndex unavailable, using lightweight fallback: {exc}"

    if payload is None:
        payload, engine, workspace_doc_id = _build_lightweight_index(doc, pages)

    structure = payload.get("structure") or []
    page_count = int(payload.get("page_count") or payload.get("line_count") or len(payload.get("pages") or []) or 0)
    node_count = _count_nodes(structure if isinstance(structure, list) else [])
    if not node_count:
        raise ValueError("pageindex_structure_empty")

    _write_json(output_path, payload)

    row.status = "ready"
    row.engine = engine
    row.workspace_doc_id = workspace_doc_id or str(payload.get("workspace_doc_id") or doc.id)
    row.index_path = str(output_path)
    row.doc_description = _normalize_text(payload.get("doc_description") or "", 2000)
    row.page_count = page_count
    row.node_count = node_count
    row.error_message = official_error[:1500]
    row.updated_at = _utcnow()
    db.flush()
    return row


def load_pageindex_payload(db: Session, document_id: str) -> tuple[DocumentPageIndex | None, dict[str, Any] | None]:
    row = db.get(DocumentPageIndex, document_id)
    if not row or row.status != "ready" or not row.index_path:
        return row, None
    path = Path(row.index_path)
    if not path.exists() or not _is_under_pageindex_dir(path):
        return row, None
    try:
        return row, _read_json(path)
    except Exception:
        return row, None


def pageindex_admin_summary(row: DocumentPageIndex | None) -> dict[str, Any]:
    if not row:
        return {"status": "not_built", "ready": False}
    return {
        "status": row.status,
        "ready": row.status == "ready",
        "engine": row.engine,
        "page_count": row.page_count,
        "node_count": row.node_count,
        "description": row.doc_description,
        "error_message": row.error_message,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def pageindex_integration_status() -> dict[str, Any]:
    candidate_paths = [str(path) for path in _candidate_pageindex_repo_paths()]
    existing_paths = [path for path in candidate_paths if (Path(path) / "pageindex" / "client.py").exists()]
    PageIndexClient, source_or_error = _load_official_client_class()
    official_available = PageIndexClient is not None
    forced_lightweight = bool(os.getenv("PAGEINDEX_FORCE_LIGHTWEIGHT", "").strip())
    engine = "lightweight-page-tree" if forced_lightweight or not official_available else "official-pageindex"
    return {
        "enabled": PAGEINDEX_ENABLED,
        "engine": engine,
        "official_available": official_available,
        "forced_lightweight": forced_lightweight,
        "repo_path": PAGEINDEX_REPO_PATH,
        "candidate_paths": candidate_paths,
        "existing_paths": existing_paths,
        "status_detail": "official PageIndex ready" if official_available else source_or_error,
        "min_chars": PAGEINDEX_MIN_CHARS,
        "storage_dir": str(PAGEINDEX_DIR),
        "supported_extensions": sorted(SUPPORTED_PAGEINDEX_EXTENSIONS),
        "native_extensions": sorted(NATIVE_OFFICIAL_PAGEINDEX_EXTENSIONS),
        "converted_markdown_extensions": sorted(TEXT_TO_MARKDOWN_PAGEINDEX_EXTENSIONS | IMAGE_PAGEINDEX_EXTENSIONS),
        "conversion_note": "PDF/Markdown 使用官方原生模式；Word/Excel/PPT/CSV/TXT/图片 OCR 会先转换成 Markdown，再交给 PageIndex。",
    }
