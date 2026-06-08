import html
from typing import Optional


def snippet_text(text: str, max_len: int = 300) -> str:
    clean = " ".join((text or "").split())
    return clean[:max_len]


def bounded_limit(value: int, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(1, min(parsed, maximum))


def citation_view_url(document_id: str, chunk_id: Optional[str] = None) -> str:
    url = f"/api/documents/{document_id}/view"
    return f"{url}?chunk_id={chunk_id}" if chunk_id else url


def citation_content_url(document_id: str, chunk_id: Optional[str] = None) -> str:
    url = f"/api/documents/{document_id}/content"
    return f"{url}?chunk_id={chunk_id}" if chunk_id else url


def preview_cache_headers() -> dict:
    return {"Cache-Control": "private, max-age=60", "Vary": "Authorization"}


def html_escape(value: str) -> str:
    return html.escape(str(value or ""), quote=False)


def build_location_descriptor(context: dict) -> str:
    parts: list[str] = []
    source_type = str(context.get("source_type") or "")
    if source_type:
        parts.append(source_type)
    page_number = context.get("page_number")
    if page_number not in (None, ""):
        parts.append(f"page {page_number}")
    chunk_index = context.get("chunk_index")
    if chunk_index not in (None, ""):
        parts.append(f"chunk {chunk_index}")
    line_number = context.get("line_number")
    if line_number not in (None, ""):
        parts.append(f"line {line_number}")
    anchor = context.get("anchor") or context.get("section_title")
    if anchor:
        parts.append(str(anchor))
    return " | ".join(parts)
