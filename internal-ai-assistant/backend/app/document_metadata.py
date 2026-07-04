from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document

DOCUMENT_SCOPE_TEST = "test"
DOCUMENT_SCOPE_PRODUCTION = "production"
DOCUMENT_SCOPE_ALL = "all"
DOCUMENT_SCOPE_VALUES = {DOCUMENT_SCOPE_TEST, DOCUMENT_SCOPE_PRODUCTION, DOCUMENT_SCOPE_ALL}

DOC_KIND_TABLE = "table"
DOC_KIND_EMPLOYEE_GUIDE = "employee_guide"
DOC_KIND_WORKORDER = "workorder"
DOC_KIND_FORM = "form"
DOC_KIND_POLICY = "policy"
DOC_KIND_GENERAL = "general"
DOC_KIND_VALUES = {
    DOC_KIND_TABLE,
    DOC_KIND_EMPLOYEE_GUIDE,
    DOC_KIND_WORKORDER,
    DOC_KIND_FORM,
    DOC_KIND_POLICY,
    DOC_KIND_GENERAL,
}

FORM_MARKERS = ("入职人员信息表", "信息表", "银行帐号", "银行账号", "开户行", "劳动合同起始日", "劳动合同到期日")
WORKORDER_MARKERS = ("工单", "工单系统", "合同组", "派单", "后道", "交付", "需求文档", "入职管理", "离职管理")
EMPLOYEE_GUIDE_MARKERS = ("员工", "微助手", "外服云", "个人注册", "员工服务", "签署指南", "操作指南", "实名认证")
POLICY_MARKERS = ("制度", "政策", "规定", "规范", "办法", "细则")
TABLE_EXTENSIONS = {"xlsx", "xls", "csv"}


def normalize_document_scope(value: Any, default: str = DOCUMENT_SCOPE_PRODUCTION) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"prod", "formal", "official", "正式", "正式库"}:
        return DOCUMENT_SCOPE_PRODUCTION
    if raw in {"test", "testing", "sandbox", "测试", "测试库"}:
        return DOCUMENT_SCOPE_TEST
    if raw in DOCUMENT_SCOPE_VALUES:
        return raw
    return default


def normalize_document_kind(value: Any, default: str = DOC_KIND_GENERAL) -> str:
    raw = str(value or "").strip().lower()
    alias = {
        "spreadsheet": DOC_KIND_TABLE,
        "excel": DOC_KIND_TABLE,
        "xlsx": DOC_KIND_TABLE,
        "csv": DOC_KIND_TABLE,
        "员工指南": DOC_KIND_EMPLOYEE_GUIDE,
        "employee": DOC_KIND_EMPLOYEE_GUIDE,
        "guide": DOC_KIND_EMPLOYEE_GUIDE,
        "工单": DOC_KIND_WORKORDER,
        "workflow": DOC_KIND_WORKORDER,
        "表单": DOC_KIND_FORM,
        "信息表": DOC_KIND_FORM,
        "制度": DOC_KIND_POLICY,
        "policy": DOC_KIND_POLICY,
    }
    raw = alias.get(raw, raw)
    if raw in DOC_KIND_VALUES:
        return raw
    if re.fullmatch(r"[a-z0-9_][a-z0-9_-]{1,48}", raw):
        return raw
    return default


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker.lower() in text for marker in markers)


def infer_document_kind(title: Any = "", filename: Any = "", source_type: Any = "", content_sample: Any = "") -> str:
    ext = str(source_type or "").strip().lower().lstrip(".")
    filename_text = str(filename or "")
    if not ext and "." in filename_text:
        ext = filename_text.rsplit(".", 1)[-1].lower()
    text = _compact(" ".join(str(item or "") for item in (title, filename, content_sample)))
    if ext in TABLE_EXTENSIONS:
        if _contains_any(text, FORM_MARKERS):
            return DOC_KIND_FORM
        return DOC_KIND_TABLE
    if _contains_any(text, FORM_MARKERS):
        return DOC_KIND_FORM
    if _contains_any(text, WORKORDER_MARKERS):
        return DOC_KIND_WORKORDER
    if _contains_any(text, EMPLOYEE_GUIDE_MARKERS):
        return DOC_KIND_EMPLOYEE_GUIDE
    if _contains_any(text, POLICY_MARKERS):
        return DOC_KIND_POLICY
    return DOC_KIND_GENERAL


def get_document_scope(doc: Document | None) -> str:
    return normalize_document_scope(getattr(doc, "knowledge_scope", "") if doc is not None else "")


def get_document_kind(doc: Document | None) -> str:
    raw = getattr(doc, "document_kind", "") if doc is not None else ""
    inferred = infer_document_kind(
        getattr(doc, "title", "") if doc is not None else "",
        getattr(doc, "filename", "") if doc is not None else "",
        getattr(doc, "source_type", "") if doc is not None else "",
    )
    return normalize_document_kind(raw, inferred)


def apply_document_scope_filter(query, scope: str | None):
    normalized = normalize_document_scope(scope, DOCUMENT_SCOPE_PRODUCTION) if scope else DOCUMENT_SCOPE_PRODUCTION
    if normalized == DOCUMENT_SCOPE_ALL:
        return query
    return query.where(Document.knowledge_scope == normalized)


def document_matches_scope(doc: Document | None, scope: str | None = None) -> bool:
    normalized = normalize_document_scope(scope, DOCUMENT_SCOPE_PRODUCTION) if scope else DOCUMENT_SCOPE_PRODUCTION
    if normalized == DOCUMENT_SCOPE_ALL:
        return True
    return get_document_scope(doc) == normalized


def allowed_kinds_for_query_topic(topic: str | None, route_name: str | None = None) -> set[str]:
    topic = str(topic or "general")
    route_name = str(route_name or "")
    if route_name == "table":
        return {DOC_KIND_TABLE, DOC_KIND_FORM}
    if topic == "form_fields":
        return {DOC_KIND_FORM, DOC_KIND_TABLE}
    if topic in {"employee_portal", "employee_esign"}:
        return {DOC_KIND_EMPLOYEE_GUIDE, DOC_KIND_GENERAL, DOC_KIND_POLICY}
    if topic == "workorder":
        return {DOC_KIND_WORKORDER, DOC_KIND_POLICY, DOC_KIND_GENERAL}
    return set()


def enrich_context_metadata(db: Session, contexts: list[dict]) -> list[dict]:
    doc_ids = {str(item.get("document_id") or "") for item in contexts if item.get("document_id")}
    if not doc_ids:
        return contexts
    docs = {
        doc.id: doc
        for doc in db.execute(select(Document).where(Document.id.in_(doc_ids))).scalars().all()
    }
    enriched: list[dict] = []
    for context in contexts:
        doc = docs.get(str(context.get("document_id") or ""))
        if not doc:
            enriched.append(context)
            continue
        item = dict(context)
        item.setdefault("knowledge_scope", get_document_scope(doc))
        item.setdefault("document_kind", get_document_kind(doc))
        enriched.append(item)
    return enriched


def filter_contexts_by_allowed_kinds(contexts: list[dict], allowed_kinds: set[str]) -> tuple[list[dict], int]:
    if not allowed_kinds:
        return contexts, 0
    kept: list[dict] = []
    dropped = 0
    for context in contexts:
        kind = str(context.get("document_kind") or DOC_KIND_GENERAL)
        if kind in allowed_kinds:
            kept.append(context)
        else:
            dropped += 1
    return kept, dropped
