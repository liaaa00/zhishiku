from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Document, DocumentChunk, DocumentPageIndex, DocumentProcessingStatus, DocumentTableRow
from .table_schema import infer_column_semantics, semantic_columns_debug

TABULAR_SOURCE_TYPES = {"xlsx", "xls", "csv"}
TEXT_SOURCE_TYPES = {"pdf", "docx", "pptx", "txt", "md", "markdown"}
IMAGE_SOURCE_TYPES = {"png", "jpg", "jpeg", "webp", "gif"}


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def _norm_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _safe_json_loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except Exception:
        return fallback


def _processing_diagnostics(status: DocumentProcessingStatus | None) -> dict[str, Any]:
    if not status:
        return {"ocr_triggered": False, "extracted_chars": None, "ocr_chars": None, "ocr_reason": ""}
    message = status.message or ""
    reason_match = re.search(r"原因=([^；）]+)", message)
    extracted_match = re.search(r"普通抽取=(\d+) 字", message)
    threshold_match = re.search(r"阈值=(\d+) 字", message)
    ocr_match = re.search(r"OCR 后=(\d+) 字", message)
    return {
        "stage": status.stage,
        "ocr_triggered": status.stage == "pdf_vision_ocr" or "OCR 后=" in message or "视觉 OCR" in message,
        "ocr_reason": reason_match.group(1) if reason_match else "",
        "extracted_chars": int(extracted_match.group(1)) if extracted_match else None,
        "ocr_chars": int(ocr_match.group(1)) if ocr_match else None,
        "ocr_threshold_chars": int(threshold_match.group(1)) if threshold_match else None,
    }


def _severity_rank(severity: str) -> int:
    return {"critical": 4, "warning": 3, "info": 2, "ok": 1}.get(severity, 0)


def _issue(severity: str, code: str, message: str, suggestion: str = "") -> dict[str, str]:
    item = {"severity": severity, "code": code, "message": message}
    if suggestion:
        item["suggestion"] = suggestion
    return item


def _score_from_issues(issues: list[dict[str, str]]) -> int:
    score = 100
    for item in issues:
        severity = item.get("severity")
        if severity == "critical":
            score -= 35
        elif severity == "warning":
            score -= 15
        elif severity == "info":
            score -= 5
    return max(0, min(100, score))


def _grade(score: int, issues: list[dict[str, str]]) -> str:
    if any(item.get("severity") == "critical" for item in issues):
        return "blocked"
    if score >= 85:
        return "good"
    if score >= 65:
        return "needs_review"
    return "poor"


REPARSE_ISSUE_CODES = {
    "processing_failed",
    "no_chunks",
    "very_low_text",
    "empty_chunks",
    "no_table_rows",
}
PAGE_INDEX_REBUILD_ISSUE_CODES = {"page_index_failed", "page_index_stale", "page_index_missing"}
MANUAL_REUPLOAD_ISSUE_CODES = {"file_missing", "file_empty"}


def recommended_actions_from_issues(issues: list[dict[str, str]], *, storage_exists: bool = True) -> list[dict[str, Any]]:
    codes = {str(item.get("code") or "") for item in issues}
    actions: list[dict[str, Any]] = []
    if codes & MANUAL_REUPLOAD_ISSUE_CODES or not storage_exists:
        actions.append(
            {
                "code": "manual_reupload",
                "label": "重新上传原文件",
                "priority": "critical",
                "available": False,
                "reason": "原文件缺失或为空，系统无法自动修复。",
            }
        )
    if storage_exists and codes & REPARSE_ISSUE_CODES:
        actions.append(
            {
                "code": "reparse",
                "label": "重新解析并重建切片",
                "priority": "high",
                "available": True,
                "reason": "解析失败、切片缺失或表格结构异常时优先重新解析。",
            }
        )
    if storage_exists and codes & PAGE_INDEX_REBUILD_ISSUE_CODES:
        actions.append(
            {
                "code": "rebuild_page_index",
                "label": "重建高级结构索引",
                "priority": "normal",
                "available": True,
                "reason": "PageIndex 缺失、失败或过期会影响章节级检索。",
            }
        )
    if not actions:
        actions.append(
            {
                "code": "none",
                "label": "无需处理",
                "priority": "low",
                "available": False,
                "reason": "未发现需要自动修复的问题。",
            }
        )
    return actions


def report_needs_reparse(report: dict[str, Any]) -> bool:
    actions = report.get("recommended_actions") or []
    return any(item.get("code") == "reparse" and item.get("available") for item in actions)


def _chunk_stats(chunks: list[DocumentChunk]) -> dict[str, Any]:
    lengths = [len(c.content or "") for c in chunks]
    normalized = [_norm_text(c.content or "") for c in chunks if _norm_text(c.content or "")]
    dup_count = sum(count - 1 for count in Counter(normalized).values() if count > 1)
    page_numbers = sorted({c.page_number for c in chunks if c.page_number is not None})
    return {
        "count": len(chunks),
        "total_chars": sum(lengths),
        "avg_chars": round(mean(lengths), 1) if lengths else 0,
        "min_chars": min(lengths) if lengths else 0,
        "max_chars": max(lengths) if lengths else 0,
        "short_chunks": sum(1 for length in lengths if 0 < length < 80),
        "empty_chunks": sum(1 for length in lengths if length == 0),
        "duplicate_chunks": dup_count,
        "page_count_from_chunks": len(page_numbers),
        "page_numbers_sample": page_numbers[:10],
    }


def _table_stats(table_rows: list[DocumentTableRow]) -> dict[str, Any]:
    rows_by_sheet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    header_counts: Counter[str] = Counter()
    data_counts: Counter[str] = Counter()
    parse_failures = 0
    sparse_rows = 0
    all_columns: set[str] = set()

    for item in table_rows:
        sheet = item.sheet_name or "Sheet1"
        row = _safe_json_loads(item.row_json, {})
        if not isinstance(row, dict):
            row = {}
            parse_failures += 1
        cleaned = {str(k): _clean(v) for k, v in row.items() if _clean(v)}
        all_columns.update(cleaned.keys())
        if item.is_header:
            header_counts[sheet] += 1
            continue
        data_counts[sheet] += 1
        rows_by_sheet[sheet].append(cleaned)
        if len(cleaned) <= 1:
            sparse_rows += 1

    semantic_by_sheet: dict[str, list[dict[str, Any]]] = {}
    for sheet, rows in rows_by_sheet.items():
        semantic_by_sheet[sheet] = semantic_columns_debug(infer_column_semantics(rows))

    semantic_names = sorted({item["semantic_name"] for items in semantic_by_sheet.values() for item in items})
    sheet_summaries = []
    for sheet in sorted(set(header_counts) | set(data_counts) | set(rows_by_sheet)):
        sheet_rows = rows_by_sheet.get(sheet, [])
        sheet_columns = sorted({key for row in sheet_rows for key in row.keys()})
        sheet_summaries.append(
            {
                "sheet_name": sheet,
                "header_rows": int(header_counts.get(sheet, 0)),
                "data_rows": int(data_counts.get(sheet, 0)),
                "columns": sheet_columns,
                "column_count": len(sheet_columns),
                "semantic_columns": semantic_by_sheet.get(sheet, []),
            }
        )

    return {
        "row_count": len(table_rows),
        "header_rows": sum(header_counts.values()),
        "data_rows": sum(data_counts.values()),
        "sheet_count": len(sheet_summaries),
        "columns": sorted(all_columns),
        "column_count": len(all_columns),
        "semantic_fields": semantic_names,
        "semantic_field_count": len(semantic_names),
        "sparse_rows": sparse_rows,
        "row_json_parse_failures": parse_failures,
        "sheets": sheet_summaries,
    }


def _build_issues(doc: Document, status: DocumentProcessingStatus | None, page_index: DocumentPageIndex | None, chunk_stats: dict[str, Any], table_stats: dict[str, Any], storage_exists: bool, file_size: int) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    source_type = (doc.source_type or "").lower().lstrip(".")

    if not storage_exists:
        issues.append(_issue("critical", "file_missing", "原始文件不存在，无法重新解析或定位原文。", "请重新上传文件。"))
    elif file_size == 0:
        issues.append(_issue("critical", "file_empty", "原始文件大小为 0。", "请检查文件是否损坏后重新上传。"))

    if status and status.status == "failed":
        issues.append(_issue("critical", "processing_failed", f"解析任务失败：{status.message or status.stage}", "请查看后台任务错误并重新解析。"))
    elif status and status.status in {"pending", "processing"}:
        issues.append(_issue("info", "processing_not_finished", "文件仍在解析中，当前诊断可能不完整。"))

    if chunk_stats["count"] == 0:
        severity = "warning" if source_type in TABULAR_SOURCE_TYPES else "critical"
        issues.append(_issue(severity, "no_chunks", "未生成可检索文本切片。", "请重新解析；扫描 PDF/图片需确认 OCR 可用。"))
    else:
        if chunk_stats["total_chars"] < 80:
            issues.append(_issue("warning", "very_low_text", "可检索文本总量很少，可能解析不完整。", "请检查原文是否为扫描件或复杂版式。"))
        if chunk_stats["empty_chunks"]:
            issues.append(_issue("warning", "empty_chunks", f"存在 {chunk_stats['empty_chunks']} 个空切片。", "建议重新解析并检查切片策略。"))
        if chunk_stats["short_chunks"] >= max(3, chunk_stats["count"] // 2):
            issues.append(_issue("info", "many_short_chunks", "短切片较多，可能影响语义检索上下文。", "后续可按标题/段落优化切片。"))
        if chunk_stats["duplicate_chunks"]:
            issues.append(_issue("info", "duplicate_chunks", f"发现 {chunk_stats['duplicate_chunks']} 个重复切片。", "后续可在入库前去重。"))

    if source_type in TABULAR_SOURCE_TYPES:
        if table_stats["data_rows"] == 0:
            issues.append(_issue("critical", "no_table_rows", "表格文件未生成结构化数据行。", "请检查表头识别、合并单元格和空行处理。"))
        else:
            if table_stats["header_rows"] == 0:
                issues.append(_issue("warning", "no_header_rows", "未识别到表头行，字段含义可能不稳定。", "建议优化表头识别或人工确认字段映射。"))
            if table_stats["semantic_field_count"] == 0:
                issues.append(_issue("warning", "no_semantic_columns", "未识别出城市、公司、状态、金额等语义字段。", "建议配置字段别名或优化表头。"))
            if table_stats["sparse_rows"]:
                issues.append(_issue("info", "sparse_table_rows", f"存在 {table_stats['sparse_rows']} 行字段过少。", "建议过滤说明行、合计行或空行。"))

    if page_index:
        if page_index.status == "failed":
            issues.append(_issue("warning", "page_index_failed", f"高级索引构建失败：{page_index.error_message[:160]}", "可在后台重建高级索引。"))
        elif page_index.status == "stale":
            issues.append(_issue("info", "page_index_stale", "高级索引已过期。", "请重建高级索引以同步最新切片。"))
    else:
        issues.append(_issue("info", "page_index_missing", "尚未构建高级结构索引。", "如需章节级检索，可构建 PageIndex。"))

    return sorted(issues, key=lambda item: _severity_rank(item.get("severity", "")), reverse=True)


def build_document_quality_report(db: Session, document_id: str) -> dict[str, Any]:
    doc = db.get(Document, document_id)
    if not doc:
        raise ValueError("document_not_found")

    status = db.get(DocumentProcessingStatus, doc.id)
    page_index = db.get(DocumentPageIndex, doc.id)
    chunks = db.execute(select(DocumentChunk).where(DocumentChunk.document_id == doc.id).order_by(DocumentChunk.chunk_index.asc())).scalars().all()
    table_rows = db.execute(select(DocumentTableRow).where(DocumentTableRow.document_id == doc.id).order_by(DocumentTableRow.sheet_name.asc(), DocumentTableRow.row_number.asc())).scalars().all()

    storage_path = Path(doc.storage_path or "")
    storage_exists = bool(doc.storage_path) and storage_path.exists()
    file_size = storage_path.stat().st_size if storage_exists and storage_path.is_file() else 0
    chunk_summary = _chunk_stats(chunks)
    table_summary = _table_stats(table_rows)
    processing_summary = _processing_diagnostics(status)
    issues = _build_issues(doc, status, page_index, chunk_summary, table_summary, storage_exists, file_size)
    score = _score_from_issues(issues)

    recommended_actions = recommended_actions_from_issues(issues, storage_exists=storage_exists)

    return {
        "document": {
            "id": doc.id,
            "title": doc.title,
            "filename": doc.filename,
            "source_type": doc.source_type,
            "storage_exists": storage_exists,
            "file_size": file_size,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
        },
        "status": {
            "status": status.status if status else "unknown",
            "stage": status.stage if status else "unknown",
            "message": status.message if status else "",
            "searchable": bool(status.searchable) if status else False,
            "chunks": int(status.chunks or 0) if status else 0,
            "updated_at": status.updated_at.isoformat() if status and status.updated_at else None,
        },
        "quality": {
            "score": score,
            "grade": _grade(score, issues),
            "issue_count": len(issues),
            "critical_count": sum(1 for item in issues if item.get("severity") == "critical"),
            "warning_count": sum(1 for item in issues if item.get("severity") == "warning"),
        },
        "chunks": chunk_summary,
        "table": table_summary,
        "processing": processing_summary,
        "page_index": {
            "status": page_index.status if page_index else "missing",
            "page_count": int(page_index.page_count or 0) if page_index else 0,
            "node_count": int(page_index.node_count or 0) if page_index else 0,
            "error_message": page_index.error_message if page_index else "",
            "updated_at": page_index.updated_at.isoformat() if page_index and page_index.updated_at else None,
        },
        "issues": issues,
        "recommended_actions": recommended_actions,
    }


def list_document_quality_reports(db: Session, *, limit: int = 200, include_chat: bool = False) -> dict[str, Any]:
    query = select(Document).order_by(Document.created_at.desc()).limit(limit)
    if not include_chat:
        query = query.where(~Document.source_type.like("chat_%"))
    docs = db.execute(query).scalars().all()
    reports = [build_document_quality_report(db, doc.id) for doc in docs]
    grade_counts = Counter(report["quality"]["grade"] for report in reports)
    return {
        "total": len(reports),
        "grade_counts": dict(grade_counts),
        "reports": reports,
    }
