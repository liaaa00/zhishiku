from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .document_metadata import (
    DOC_KIND_EMPLOYEE_GUIDE,
    DOC_KIND_FORM,
    DOC_KIND_GENERAL,
    DOC_KIND_POLICY,
    DOC_KIND_TABLE,
    DOC_KIND_WORKORDER,
    normalize_document_kind,
)
from .models import Document, DocumentChunk, Setting
from .settings_service import get_setting, set_setting

DOCUMENT_ROUTING_CONFIG_KEY = "document_routing_rules"

DEFAULT_DOCUMENT_ROUTING_CONFIG: dict[str, Any] = {
    "version": 2,
    "document_kinds": [
        {"value": DOC_KIND_POLICY, "label": "制度/政策/通知", "extensions": [], "markers": ["制度", "政策", "规定", "规范", "办法", "细则", "通知", "公告"]},
        {"value": DOC_KIND_EMPLOYEE_GUIDE, "label": "操作指南/员工服务", "extensions": [], "markers": ["操作指南", "使用手册", "微助手", "外服云", "员工服务", "实名认证", "个人注册", "签署指南"]},
        {"value": DOC_KIND_WORKORDER, "label": "流程/SOP/工单", "extensions": [], "markers": ["流程", "SOP", "工单", "工单系统", "合同组", "派单", "后道", "交付", "需求文档", "入职管理", "离职管理"]},
        {"value": DOC_KIND_FORM, "label": "表单/信息采集", "extensions": [], "markers": ["表单", "信息采集", "信息表", "入职人员信息表", "银行帐号", "银行账号", "开户行", "劳动合同起始日", "劳动合同到期日"]},
        {"value": DOC_KIND_TABLE, "label": "表格/清单/台账", "extensions": ["xlsx", "xls", "csv"], "markers": ["清单", "台账", "明细表", "统计表"]},
        {"value": "contract", "label": "合同/协议/模板", "extensions": [], "markers": ["合同", "协议", "甲方", "乙方", "签约", "续签", "模板", "条款"]},
        {"value": "finance", "label": "财务/报销/发票", "extensions": [], "markers": ["财务", "报销", "发票", "付款", "收款", "开票", "费用", "付款审批"]},
        {"value": "hr", "label": "人事/入离转调", "extensions": [], "markers": ["人事", "入职", "离职", "转正", "调岗", "劳动合同", "员工档案", "社保", "公积金"]},
        {"value": "project", "label": "项目/交付资料", "extensions": [], "markers": ["项目", "交付", "里程碑", "验收", "需求说明", "实施方案", "项目计划"]},
        {"value": "training", "label": "培训/学习资料", "extensions": [], "markers": ["培训", "课件", "学习", "考试", "课程", "教材"]},
        {"value": DOC_KIND_GENERAL, "label": "通用/其他文档", "extensions": [], "markers": []},
    ],
    "route_rules": [
        {"topic": "form_fields", "route": "text", "allowed_kinds": [DOC_KIND_FORM, DOC_KIND_TABLE, "hr"]},
        {"topic": "employee_portal", "route": "text", "allowed_kinds": [DOC_KIND_EMPLOYEE_GUIDE, DOC_KIND_GENERAL, DOC_KIND_POLICY, "hr", "training"]},
        {"topic": "employee_esign", "route": "text", "allowed_kinds": [DOC_KIND_EMPLOYEE_GUIDE, DOC_KIND_GENERAL, DOC_KIND_POLICY, "contract", "hr"]},
        {"topic": "workorder", "route": "text", "allowed_kinds": [DOC_KIND_WORKORDER, DOC_KIND_POLICY, DOC_KIND_GENERAL, "project"]},
        {"route": "table", "allowed_kinds": [DOC_KIND_TABLE, DOC_KIND_FORM, "finance", "hr"]},
    ],
    "classification": {
        "low_confidence_threshold": 0.55,
    },
}


def _slug(value: Any, default: str = "") -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_\-]+", "_", raw)
    raw = re.sub(r"_+", "_", raw).strip("_-")
    return raw or default


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def default_document_routing_config() -> dict[str, Any]:
    return json.loads(json.dumps(DEFAULT_DOCUMENT_ROUTING_CONFIG, ensure_ascii=False))


def _default_kind_values() -> set[str]:
    return {str(item.get("value")) for item in DEFAULT_DOCUMENT_ROUTING_CONFIG["document_kinds"] if item.get("value")}


def enabled_document_kind_values_from_config(config: dict[str, Any]) -> set[str]:
    return {
        str(item.get("value") or "")
        for item in config.get("document_kinds", [])
        if item.get("value") and not bool(item.get("disabled"))
    }


def sanitize_document_routing_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, dict):
        config = {}
    default = default_document_routing_config()
    sanitized: dict[str, Any] = {"version": int(config.get("version") or default["version"])}

    kinds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in _as_list(config.get("document_kinds")):
        if not isinstance(item, dict):
            continue
        value = _slug(item.get("value"), "")
        if not value or value in seen:
            continue
        seen.add(value)
        label = str(item.get("label") or value).strip() or value
        kinds.append(
            {
                "value": value,
                "label": label[:80],
                "extensions": sorted({_slug(ext, "") for ext in _as_list(item.get("extensions")) if _slug(ext, "")}),
                "markers": [str(marker).strip() for marker in _as_list(item.get("markers")) if str(marker).strip()][:80],
                "disabled": bool(item.get("disabled")) and value != DOC_KIND_GENERAL,
            }
        )
    if not kinds:
        for item in default["document_kinds"]:
            value = str(item.get("value") or "")
            if value and value not in seen:
                kinds.append(item)
                seen.add(value)
    elif DOC_KIND_GENERAL not in seen:
        general_default = next((item for item in default["document_kinds"] if item.get("value") == DOC_KIND_GENERAL), None)
        if general_default:
            kinds.append(general_default)
            seen.add(DOC_KIND_GENERAL)
    sanitized["document_kinds"] = kinds

    valid_kinds = enabled_document_kind_values_from_config(sanitized)
    route_rules: list[dict[str, Any]] = []
    for item in _as_list(config.get("route_rules")):
        if not isinstance(item, dict):
            continue
        allowed = [_slug(kind, "") for kind in _as_list(item.get("allowed_kinds"))]
        allowed = [kind for kind in dict.fromkeys(allowed) if kind in valid_kinds]
        if not allowed:
            continue
        rule: dict[str, Any] = {"allowed_kinds": allowed}
        topic = str(item.get("topic") or "").strip()
        route = str(item.get("route") or "").strip().lower()
        if topic:
            rule["topic"] = topic
        if route:
            rule["route"] = route
        if rule.get("topic") or rule.get("route"):
            route_rules.append(rule)
    if not route_rules:
        for item in default["route_rules"]:
            allowed = [_slug(kind, "") for kind in _as_list(item.get("allowed_kinds"))]
            allowed = [kind for kind in dict.fromkeys(allowed) if kind in valid_kinds]
            if not allowed:
                continue
            rule: dict[str, Any] = {"allowed_kinds": allowed}
            topic = str(item.get("topic") or "").strip()
            route = str(item.get("route") or "").strip().lower()
            if topic:
                rule["topic"] = topic
            if route:
                rule["route"] = route
            if rule.get("topic") or rule.get("route"):
                route_rules.append(rule)
    sanitized["route_rules"] = route_rules

    classification = config.get("classification") if isinstance(config.get("classification"), dict) else {}
    try:
        threshold = float(classification.get("low_confidence_threshold", default["classification"]["low_confidence_threshold"]))
    except (TypeError, ValueError):
        threshold = float(default["classification"]["low_confidence_threshold"])
    sanitized["classification"] = {"low_confidence_threshold": max(0.0, min(threshold, 1.0))}
    return sanitized


def get_document_routing_config(db: Session | None) -> dict[str, Any]:
    if db is None:
        return default_document_routing_config()
    raw = get_setting(db, DOCUMENT_ROUTING_CONFIG_KEY, "")
    if not raw:
        return default_document_routing_config()
    try:
        return sanitize_document_routing_config(json.loads(raw))
    except Exception:
        return default_document_routing_config()


def set_document_routing_config(db: Session, config: Any) -> dict[str, Any]:
    sanitized = sanitize_document_routing_config(config)
    set_setting(db, DOCUMENT_ROUTING_CONFIG_KEY, json.dumps(sanitized, ensure_ascii=False, indent=2))
    return sanitized


def ensure_default_document_routing_config(db: Session) -> dict[str, Any]:
    if not db.get(Setting, DOCUMENT_ROUTING_CONFIG_KEY):
        config = default_document_routing_config()
        set_document_routing_config(db, config)
        return config
    return get_document_routing_config(db)


def configured_document_kind_values(db: Session | None = None, include_disabled: bool = False) -> set[str]:
    config = get_document_routing_config(db)
    if include_disabled:
        return {str(item.get("value") or "") for item in config.get("document_kinds", []) if item.get("value")}
    return enabled_document_kind_values_from_config(config)


def normalize_configured_document_kind(value: Any, default: str = DOC_KIND_GENERAL, db: Session | None = None) -> str:
    raw = _slug(value, "")
    if not raw:
        return default
    configured = configured_document_kind_values(db)
    if raw in configured:
        return raw
    fallback = normalize_document_kind(raw, default)
    return fallback if fallback in configured else default


def infer_document_kind_from_config(
    db: Session | None,
    title: Any = "",
    filename: Any = "",
    source_type: Any = "",
    content_sample: Any = "",
) -> dict[str, Any]:
    config = get_document_routing_config(db)
    ext = str(source_type or "").strip().lower().lstrip(".")
    filename_text = str(filename or "")
    if not ext and "." in filename_text:
        ext = filename_text.rsplit(".", 1)[-1].lower()
    text = _compact(" ".join(str(item or "") for item in (title, filename, content_sample)))

    best_kind = DOC_KIND_GENERAL
    best_score = 0.0
    reasons: list[str] = []
    general_kind = DOC_KIND_GENERAL
    for item in config.get("document_kinds", []):
        if bool(item.get("disabled")):
            continue
        kind = str(item.get("value") or "").strip()
        if kind == DOC_KIND_GENERAL:
            general_kind = kind
        if not kind:
            continue
        score = 0.0
        current_reasons: list[str] = []
        extensions = {str(value or "").strip().lower().lstrip(".") for value in item.get("extensions", [])}
        if ext and ext in extensions:
            score += 0.52
            current_reasons.append(f"extension:{ext}")
        matched_markers = []
        for marker in item.get("markers", []):
            marker_text = _compact(marker)
            if marker_text and marker_text in text:
                matched_markers.append(str(marker))
        if matched_markers:
            score += min(0.68, 0.34 + 0.12 * (len(matched_markers) - 1))
            current_reasons.append("markers:" + ",".join(matched_markers[:5]))
        if kind == DOC_KIND_GENERAL and not current_reasons:
            score = max(score, 0.18)
        if score > best_score:
            best_kind = kind
            best_score = score
            reasons = current_reasons
    if best_score < 0.2:
        best_kind = general_kind
        best_score = 0.2
        reasons = ["fallback:general"]
    return {"kind": normalize_configured_document_kind(best_kind, general_kind, db), "confidence": round(min(best_score, 1.0), 4), "reasons": reasons}


def allowed_kinds_for_query_topic_config(db: Session | None, topic: str | None, route_name: str | None = None) -> set[str]:
    config = get_document_routing_config(db)
    topic_text = str(topic or "general")
    route_text = str(route_name or "").strip().lower()
    for rule in config.get("route_rules", []):
        rule_topic = str(rule.get("topic") or "")
        rule_route = str(rule.get("route") or "").strip().lower()
        topic_ok = not rule_topic or rule_topic == topic_text
        route_ok = not rule_route or rule_route == route_text
        if topic_ok and route_ok:
            return {str(kind) for kind in rule.get("allowed_kinds", []) if kind}
    return set()


def sample_document_text(db: Session, document_id: str, limit: int = 4000) -> str:
    chunks = db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(3)
    ).scalars().all()
    return "\n".join(str(chunk.content or "") for chunk in chunks)[:limit]


def classify_document(db: Session, doc: Document) -> dict[str, Any]:
    sample = sample_document_text(db, doc.id)
    return infer_document_kind_from_config(db, doc.title, doc.filename, doc.source_type, sample)
