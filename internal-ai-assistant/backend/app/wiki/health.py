from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Document, DocumentChunk, WikiCompileStatus, WikiPage
from .citations import citation_coverage, extract_wikilinks, invalid_source_markers
from .compiler import _slugify_title, document_wiki_checksum

LOW_CONFIDENCE_THRESHOLD = 0.45
MIN_CONTENT_CHARS = 80
MIN_CITATION_COVERAGE = 0.55
MAX_FINDINGS = 200

ERROR_DEDUCTION = 6
WARNING_DEDUCTION = 2
INFO_DEDUCTION = 0.5


def _compact_title(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _deduction(severity: str) -> float:
    if severity == "error":
        return ERROR_DEDUCTION
    if severity == "warning":
        return WARNING_DEDUCTION
    return INFO_DEDUCTION


def _finding(rule: str, severity: str, message: str, page: WikiPage | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rule": rule,
        "severity": severity,
        "message": message,
        "deduction": _deduction(severity),
    }
    if page is not None:
        payload.update(
            {
                "page_id": page.id,
                "slug": page.slug,
                "title": page.title,
                "page_type": page.page_type,
                "status": page.status,
            }
        )
    payload.update(extra)
    return payload


def _page_stale(db: Session, page: WikiPage) -> bool:
    if not page.sources:
        return False
    first_doc = page.sources[0].document
    if not first_doc:
        return False
    chunks = db.execute(
        select(DocumentChunk).where(DocumentChunk.document_id == first_doc.id).order_by(DocumentChunk.chunk_index.asc())
    ).scalars().all()
    if not chunks:
        return False
    return bool(page.checksum and page.checksum != document_wiki_checksum(first_doc, chunks))


def _strip_wikilink_anchor(value: str) -> str:
    return (value or "").split("#", 1)[0].strip()


def _page_target_keys(page: WikiPage) -> set[str]:
    keys = {
        str(page.slug or "").lower(),
        _slugify_title(str(page.title or ""), str(page.slug or page.id or "page")).lower(),
        _compact_title(str(page.title or "")),
    }
    return {key for key in keys if key}


def _wikilink_target_keys(link: str) -> set[str]:
    target = _strip_wikilink_anchor(link)
    if not target:
        return set()
    keys = {
        target.lower(),
        _slugify_title(target, target).lower(),
        _compact_title(target),
    }
    return {key for key in keys if key}


def evaluate_wiki_health(db: Session, *, knowledge_scope: str = "production", include_findings: bool = True) -> dict[str, Any]:
    pages = db.execute(
        select(WikiPage).where(WikiPage.knowledge_scope == knowledge_scope).order_by(WikiPage.updated_at.desc())
    ).scalars().all()
    statuses = db.execute(
        select(WikiCompileStatus)
        .join(Document, WikiCompileStatus.document_id == Document.id)
        .where(Document.knowledge_scope == knowledge_scope)
    ).scalars().all()

    findings: list[dict[str, Any]] = []
    title_to_pages: dict[str, list[WikiPage]] = defaultdict(list)
    known_wikilink_targets: set[str] = set()
    for page in pages:
        known_wikilink_targets.update(_page_target_keys(page))

    total_claim_blocks = 0
    total_cited_blocks = 0
    wikilink_count = 0
    broken_wikilink_count = 0

    for page in pages:
        content_md = page.content_md or ""
        source_count = len(page.sources)
        title_to_pages[_compact_title(page.title)].append(page)
        if page.status == "published" and not page.sources:
            findings.append(_finding("missing-source", "error", "Published wiki page has no source mapping", page))
        if not (page.summary or "").strip():
            findings.append(_finding("missing-summary", "warning", "Wiki page has no summary", page))
        if len(content_md.strip()) < MIN_CONTENT_CHARS:
            findings.append(_finding("empty-page", "error", "Wiki page content is too short", page))
        if float(page.confidence or 0.0) < LOW_CONFIDENCE_THRESHOLD:
            findings.append(_finding("low-confidence", "warning", "Wiki page confidence is below threshold", page, confidence=page.confidence))
        if page.status == "published" and _page_stale(db, page):
            findings.append(_finding("stale-page", "warning", "Source document changed after this wiki page was compiled", page))

        invalid_markers = invalid_source_markers(content_md, source_count)
        if invalid_markers:
            findings.append(
                _finding(
                    "source-marker-out-of-range",
                    "error",
                    "Wiki page references source markers that do not exist",
                    page,
                    source_count=source_count,
                    invalid_markers=[
                        {"index": marker.index, "line": marker.line, "raw": marker.raw}
                        for marker in invalid_markers[:20]
                    ],
                    invalid_marker_count=len(invalid_markers),
                )
            )

        coverage = citation_coverage(content_md)
        claim_block_count = int(coverage["claim_block_count"])
        cited_block_count = int(coverage["cited_block_count"])
        total_claim_blocks += claim_block_count
        total_cited_blocks += cited_block_count
        if (
            page.status == "published"
            and source_count > 0
            and claim_block_count > 0
            and float(coverage["coverage"]) < MIN_CITATION_COVERAGE
        ):
            findings.append(
                _finding(
                    "low-citation-coverage",
                    "warning",
                    "Too many claim-like blocks lack source markers",
                    page,
                    citation_coverage=coverage["coverage"],
                    claim_block_count=claim_block_count,
                    cited_block_count=cited_block_count,
                    threshold=MIN_CITATION_COVERAGE,
                )
            )

        for wikilink in extract_wikilinks(content_md):
            target_keys = _wikilink_target_keys(wikilink)
            if not target_keys:
                continue
            wikilink_count += 1
            if target_keys.isdisjoint(known_wikilink_targets):
                broken_wikilink_count += 1
                findings.append(
                    _finding(
                        "broken-wikilink",
                        "warning",
                        "Wiki page links to a missing wiki page",
                        page,
                        target=wikilink,
                    )
                )

    for title_key, duplicate_pages in title_to_pages.items():
        if title_key and len(duplicate_pages) > 1:
            for page in duplicate_pages:
                findings.append(
                    _finding(
                        "duplicate-title",
                        "warning",
                        "Multiple wiki pages share the same normalized title",
                        page,
                        duplicate_count=len(duplicate_pages),
                    )
                )

    failed_statuses = [status for status in statuses if status.status == "failed"]
    for status in failed_statuses:
        findings.append(
            _finding(
                "compile-failed",
                "error",
                "A document failed Wiki compilation",
                None,
                document_id=status.document_id,
                error_message=status.error_message,
            )
        )

    rule_counts = Counter(item["rule"] for item in findings)
    severity_counts = Counter(item["severity"] for item in findings)
    total_deduction = sum(float(item["deduction"]) for item in findings)
    score = max(0.0, 100.0 - total_deduction)
    published_pages = [page for page in pages if page.status == "published"]
    sourced_pages = [page for page in pages if page.sources]
    overall_citation_coverage = 1.0 if total_claim_blocks == 0 else round(total_cited_blocks / total_claim_blocks, 4)
    payload: dict[str, Any] = {
        "knowledge_scope": knowledge_scope,
        "score": round(score, 1),
        "max_score": 100,
        "page_count": len(pages),
        "published_count": len(published_pages),
        "draft_count": sum(1 for page in pages if page.status == "draft"),
        "sourced_page_count": len(sourced_pages),
        "source_coverage": round(len(sourced_pages) / max(1, len(pages)), 4),
        "claim_block_count": total_claim_blocks,
        "cited_block_count": total_cited_blocks,
        "citation_coverage": overall_citation_coverage,
        "wikilink_count": wikilink_count,
        "broken_wikilink_count": broken_wikilink_count,
        "failed_document_count": len(failed_statuses),
        "finding_count": len(findings),
        "rule_counts": dict(sorted(rule_counts.items())),
        "severity_counts": dict(sorted(severity_counts.items())),
        "thresholds": {
            "low_confidence": LOW_CONFIDENCE_THRESHOLD,
            "min_content_chars": MIN_CONTENT_CHARS,
            "min_citation_coverage": MIN_CITATION_COVERAGE,
        },
    }
    if include_findings:
        payload["findings"] = findings[:MAX_FINDINGS]
        payload["findings_truncated"] = len(findings) > MAX_FINDINGS
    return payload
