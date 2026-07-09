from __future__ import annotations

import re
from dataclasses import dataclass

SOURCE_MARKER_RE = re.compile(r"(?<![A-Za-z0-9_])\[S(?P<index>\d+)\]")
CLAIM_CITATION_RE = re.compile(r"\^\[(?P<body>[^\]]+)\]")
WIKILINK_RE = re.compile(r"\[\[(?P<body>[^\]]+)\]\]")

EXCLUDED_CITATION_SECTIONS = {
    "关键原文摘录",
    "来源索引",
    "原始证据",
    "source index",
    "sources",
    "raw evidence",
}


@dataclass(frozen=True)
class SourceMarker:
    index: int
    line: int
    raw: str


@dataclass(frozen=True)
class ClaimBlock:
    text: str
    line: int
    cited: bool


def _line_number_at(text: str, pos: int) -> int:
    return text.count("\n", 0, max(0, pos)) + 1


def extract_source_markers(markdown: str) -> list[SourceMarker]:
    markers: list[SourceMarker] = []
    for match in SOURCE_MARKER_RE.finditer(markdown or ""):
        try:
            index = int(match.group("index"))
        except ValueError:
            continue
        markers.append(SourceMarker(index=index, line=_line_number_at(markdown, match.start()), raw=match.group(0)))
    return markers


def extract_claim_citations(markdown: str) -> list[str]:
    return [match.group("body").strip() for match in CLAIM_CITATION_RE.finditer(markdown or "") if match.group("body").strip()]


def extract_wikilinks(markdown: str) -> list[str]:
    links: list[str] = []
    for match in WIKILINK_RE.finditer(markdown or ""):
        body = (match.group("body") or "").strip()
        if not body:
            continue
        links.append(body.split("|", 1)[0].strip())
    return links


def _strip_frontmatter(markdown: str) -> str:
    text = markdown or ""
    match = re.match(r"^---\s*\n[\s\S]*?\n---\s*\n?", text)
    if match:
        return text[match.end() :]
    return text


def _heading_title(line: str) -> str | None:
    match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line.strip())
    if not match:
        return None
    return match.group(1).strip()


def _normalize_heading(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip().lower()


def _is_excluded_section(section: str) -> bool:
    normalized = _normalize_heading(section)
    return any(item in normalized for item in EXCLUDED_CITATION_SECTIONS)


def _is_claim_like(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.startswith(("#", "```", ">", "|", "---")):
        return False
    # Bullets frequently contain the compiled facts in our source pages, so keep
    # them as claim blocks after removing the list marker.
    stripped = re.sub(r"^[-*+]\s+", "", stripped)
    if len(stripped) < 12:
        return False
    if re.match(r"^\[S\d+\]", stripped):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]", stripped))


def claim_blocks(markdown: str) -> list[ClaimBlock]:
    """Return prose/list claim blocks that should carry source support.

    This is the Python equivalent of the reference projects' "split prose before
    evaluating citations" idea, adapted to our database-backed Wiki pages and
    `[S1]` source markers. It deliberately skips source dump sections so copied
    original excerpts do not inflate citation coverage.
    """

    body = _strip_frontmatter(markdown)
    blocks: list[ClaimBlock] = []
    in_code = False
    current_section = ""
    paragraph: list[str] = []
    paragraph_start = 1

    def flush_paragraph() -> None:
        nonlocal paragraph, paragraph_start
        if not paragraph:
            return
        text = " ".join(item.strip() for item in paragraph if item.strip()).strip()
        paragraph = []
        if not text or _is_excluded_section(current_section):
            return
        if _is_claim_like(text):
            blocks.append(ClaimBlock(text=text, line=paragraph_start, cited=has_source_marker(text) or bool(CLAIM_CITATION_RE.search(text))))

    for line_no, line in enumerate(body.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_paragraph()
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = _heading_title(line)
        if heading is not None:
            flush_paragraph()
            current_section = heading
            continue
        if _is_excluded_section(current_section):
            flush_paragraph()
            continue
        if not stripped:
            flush_paragraph()
            continue
        if re.match(r"^[-*+]\s+", stripped):
            flush_paragraph()
            item = re.sub(r"^[-*+]\s+", "", stripped).strip()
            if _is_claim_like(item):
                blocks.append(ClaimBlock(text=item, line=line_no, cited=has_source_marker(item) or bool(CLAIM_CITATION_RE.search(item))))
            continue
        if not paragraph:
            paragraph_start = line_no
        paragraph.append(stripped)
    flush_paragraph()
    return blocks


def has_source_marker(text: str) -> bool:
    return bool(SOURCE_MARKER_RE.search(text or ""))


def citation_coverage(markdown: str) -> dict[str, float | int]:
    blocks = claim_blocks(markdown)
    cited = [block for block in blocks if block.cited]
    return {
        "claim_block_count": len(blocks),
        "cited_block_count": len(cited),
        "coverage": round(len(cited) / max(1, len(blocks)), 4),
    }


def invalid_source_markers(markdown: str, source_count: int) -> list[SourceMarker]:
    return [marker for marker in extract_source_markers(markdown) if marker.index <= 0 or marker.index > max(0, source_count)]
