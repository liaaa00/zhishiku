from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from .settings_service import get_setting

PROMPT_TEMPLATES_SETTING_KEY = "admin_prompt_templates_json"
PROMPT_TEMPLATE_ADOPTIONS_SETTING_KEY = "admin_prompt_template_adoptions_json"

DEFAULT_PROMPT_TEMPLATES: list[dict[str, Any]] = [
    {
        "key": "general",
        "label": "通用知识库问答",
        "document_kind": "general",
        "enabled": True,
        "content": "请只基于知识库来源回答；如果来源不足，明确说明未找到可靠依据，并提示管理员补充或检查文档。",
    },
    {
        "key": "contract",
        "label": "合同/协议类回答",
        "document_kind": "contract",
        "enabled": True,
        "content": "回答合同问题时优先引用合同名称、条款、页码和关键日期；不要做法律结论，必要时提示人工复核。",
    },
    {
        "key": "finance",
        "label": "财务类回答",
        "document_kind": "finance",
        "enabled": True,
        "content": "回答财务问题时突出金额、币种、期间、口径和来源页；如果表格口径不一致，先说明差异再给结论。",
    },
    {
        "key": "policy",
        "label": "制度/流程类回答",
        "document_kind": "policy",
        "enabled": True,
        "content": "回答制度流程问题时按步骤组织，标明适用对象、前置条件、处理时限和引用制度版本。",
    },
    {
        "key": "table",
        "label": "表格查询回答",
        "document_kind": "table",
        "enabled": True,
        "content": "回答表格查询时说明筛选条件、聚合口径和命中行；不要把未命中的字段编造成结果。",
    },
    {
        "key": "no_source",
        "label": "无可靠来源兜底",
        "document_kind": "general",
        "enabled": True,
        "content": "当没有足够来源时，不要猜测答案；输出未找到可靠依据，并建议换一种问法或补充文档。",
    },
]


def normalize_prompt_template(item: dict[str, Any]) -> dict[str, Any]:
    key = str(item.get("key") or "").strip().lower().replace(" ", "_")[:80]
    if not key:
        raise ValueError("template_key_required")
    content = str(item.get("content") or "").strip()
    if not content:
        raise ValueError("template_content_required")
    if len(content) > 4000:
        raise ValueError("template_content_too_long")
    return {
        "key": key,
        "label": str(item.get("label") or key).strip()[:120],
        "document_kind": str(item.get("document_kind") or "general").strip()[:80] or "general",
        "enabled": bool(item.get("enabled", True)),
        "content": content,
    }


def load_prompt_templates(db: Session) -> list[dict[str, Any]]:
    raw = get_setting(db, PROMPT_TEMPLATES_SETTING_KEY, "")
    try:
        parsed = json.loads(raw or "[]")
    except Exception:
        parsed = []
    rows = parsed if isinstance(parsed, list) else []
    if not rows:
        rows = DEFAULT_PROMPT_TEMPLATES
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            item = normalize_prompt_template(row)
        except ValueError:
            continue
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        result.append(item)
    return result or [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]


def _template_context_from_selected(selected: list[dict[str, Any]]) -> dict[str, Any]:
    selected = selected[:4]
    instructions = "\n".join(f"- {item.get('label') or item.get('key')}: {item.get('content')}" for item in selected if item.get("content"))
    return {
        "keys": [item.get("key") for item in selected],
        "labels": [item.get("label") for item in selected],
        "instructions": instructions,
        "count": len(selected),
    }


def prompt_template_context_for_keys(db: Session, keys: list[str]) -> dict[str, Any]:
    wanted = [str(key or "").strip() for key in keys if str(key or "").strip()]
    templates = [item for item in load_prompt_templates(db) if item.get("enabled")]
    by_key = {str(item.get("key") or ""): item for item in templates}
    selected: list[dict[str, Any]] = []
    for key in wanted:
        item = by_key.get(key)
        if item and all(str(existing.get("key") or "") != key for existing in selected):
            selected.append(item)
    return _template_context_from_selected(selected)


def recommended_prompt_template_keys_by_kind(db: Session) -> dict[str, list[dict[str, Any]]]:
    raw = get_setting(db, PROMPT_TEMPLATE_ADOPTIONS_SETTING_KEY, "")
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    rows = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}
    enabled_keys = {str(item.get("key") or "") for item in load_prompt_templates(db) if item.get("enabled")}
    counts: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        kinds = list(dict.fromkeys(str(kind or "general") for kind in (row.get("document_kinds") or []) if str(kind or "").strip())) or ["general"]
        selected_keys = list(dict.fromkeys(str(key or "") for key in (row.get("selected_template_keys") or []) if str(key or "") in enabled_keys))
        for kind in kinds:
            kind_counts = counts.setdefault(kind, {})
            for key in selected_keys:
                item = kind_counts.setdefault(key, {"key": key, "wins": 0, "latest_at": ""})
                item["wins"] += 1
                item["latest_at"] = max(str(item.get("latest_at") or ""), str(row.get("created_at") or ""))
    return {
        kind: sorted(items.values(), key=lambda item: (int(item.get("wins") or 0), str(item.get("latest_at") or "")), reverse=True)[:3]
        for kind, items in counts.items()
    }


def select_prompt_templates_for_contexts(db: Session, contexts: list[dict], *, table_answer_mode: bool = False, no_source: bool = False) -> dict[str, Any]:
    templates = [item for item in load_prompt_templates(db) if item.get("enabled")]
    by_key = {str(item.get("key") or ""): item for item in templates}
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for item in templates:
        by_kind.setdefault(str(item.get("document_kind") or "general"), []).append(item)

    selected: list[dict[str, Any]] = []
    applied_recommendations: list[dict[str, Any]] = []

    def add(item: dict[str, Any] | None) -> bool:
        if not item:
            return False
        key = str(item.get("key") or "")
        if key and all(str(existing.get("key") or "") != key for existing in selected):
            selected.append(item)
            return True
        return False

    if no_source:
        add(by_key.get("no_source"))

    if table_answer_mode:
        add(by_key.get("table"))
        for item in by_kind.get("table", []):
            add(item)

    kind_counts = Counter(str(context.get("document_kind") or "general") for context in contexts or [])
    recommended_by_kind = recommended_prompt_template_keys_by_kind(db)
    for kind, _count in kind_counts.most_common(3):
        # 每个文档类型只自动优先应用当前胜出次数最高的模板，避免过多推荐模板挤掉原有规则。
        for recommendation in recommended_by_kind.get(kind, [])[:1]:
            key = str(recommendation.get("key") or "")
            if add(by_key.get(key)):
                applied_recommendations.append(
                    {
                        "kind": kind,
                        "key": key,
                        "wins": int(recommendation.get("wins") or 0),
                        "latest_at": str(recommendation.get("latest_at") or ""),
                    }
                )

    for kind, _count in kind_counts.most_common(3):
        for item in by_kind.get(kind, []):
            add(item)

    add(by_key.get("general"))
    context = _template_context_from_selected(selected)
    selected_keys = {str(key or "") for key in context.get("keys") or []}
    context["recommended"] = [item for item in applied_recommendations if str(item.get("key") or "") in selected_keys]
    return context
