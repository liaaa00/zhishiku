from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai_client import chat_answer_v2, extractive_fallback_answer
from ..database import get_db
from ..document_metadata import get_document_kind
from ..document_quality import list_document_quality_reports, report_needs_reparse
from ..document_routing_config import get_document_routing_config
from ..models import ChatMessage, Document, DocumentProcessingStatus, Feedback, User
from ..prompt_template_service import (
    DEFAULT_PROMPT_TEMPLATES as SHARED_DEFAULT_PROMPT_TEMPLATES,
    PROMPT_TEMPLATES_SETTING_KEY as SHARED_PROMPT_TEMPLATES_SETTING_KEY,
    load_prompt_templates as shared_load_prompt_templates,
    normalize_prompt_template as shared_normalize_prompt_template,
    prompt_template_context_for_keys,
    recommended_prompt_template_keys_by_kind,
    select_prompt_templates_for_contexts,
)
from ..retrieval import adaptive_retrieve_contexts
from ..settings_service import get_model_config, get_setting, set_setting
from .chat_api import model_contexts_for_answer
from .deps import audit, new_id, parse_json_list, require_admin

router = APIRouter()

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


class PromptTemplateItem(BaseModel):
    key: str
    label: str = ""
    document_kind: str = "general"
    enabled: bool = True
    content: str


class PromptTemplatesPayload(BaseModel):
    templates: list[PromptTemplateItem]


class PromptTemplatePreviewRequest(BaseModel):
    question: str
    top_k: int = 8
    knowledge_scope: str = "production"


class PromptTemplateCompareRequest(BaseModel):
    question: str
    template_a_keys: list[str] = []
    template_b_keys: list[str] = []
    top_k: int = 8
    knowledge_scope: str = "production"
    dry_run: bool = False


class PromptTemplateAdoptionRequest(BaseModel):
    question: str
    selected_variant: str
    selected_template_keys: list[str]
    rejected_template_keys: list[str] = []
    document_kinds: list[str] = []
    source_document_ids: list[str] = []
    admin_note: str = ""
    dry_run: bool = False


def _safe_json_loads(value: str, fallback: Any) -> Any:
    try:
        parsed = json.loads(value or "")
        return parsed if parsed is not None else fallback
    except Exception:
        return fallback


def _normalize_prompt_template(item: dict[str, Any]) -> dict[str, Any]:
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


def _load_prompt_templates(db: Session) -> list[dict[str, Any]]:
    stored = _safe_json_loads(get_setting(db, PROMPT_TEMPLATES_SETTING_KEY, ""), [])
    if not isinstance(stored, list) or not stored:
        return [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in stored:
        if not isinstance(raw, dict):
            continue
        try:
            item = _normalize_prompt_template(raw)
        except ValueError:
            continue
        if item["key"] in seen:
            continue
        seen.add(item["key"])
        normalized.append(item)
    return normalized or [dict(item) for item in DEFAULT_PROMPT_TEMPLATES]


def _document_kind_label_map(db: Session) -> dict[str, str]:
    cfg = get_document_routing_config(db)
    result: dict[str, str] = {}
    for item in cfg.get("document_kinds") or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("value") or "").strip()
        if key:
            result[key] = str(item.get("label") or key)
    return result


def _status_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(DocumentProcessingStatus.status, func.count(DocumentProcessingStatus.document_id)).group_by(DocumentProcessingStatus.status)
    ).all()
    return {str(status or "unknown"): int(count or 0) for status, count in rows}


def _document_kind_counts(db: Session) -> list[dict[str, Any]]:
    labels = _document_kind_label_map(db)
    rows = db.execute(select(Document.document_kind, func.count(Document.id)).group_by(Document.document_kind)).all()
    items = []
    for kind, count in rows:
        key = str(kind or "general")
        items.append({"kind": key, "label": labels.get(key, key), "count": int(count or 0)})
    items.sort(key=lambda item: item["count"], reverse=True)
    return items


def _feedback_stats(db: Session, since: datetime) -> dict[str, Any]:
    rows = db.execute(select(Feedback).where(Feedback.created_at >= since)).scalars().all()
    by_status: dict[str, int] = {}
    by_root_cause: dict[str, int] = {}
    by_category: dict[str, int] = {}
    recent = []
    for item in rows:
        status = str(item.status or "new")
        root = str(item.root_cause or "unclassified")
        category = str(item.category or "other")
        by_status[status] = by_status.get(status, 0) + 1
        by_root_cause[root] = by_root_cause.get(root, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
    for item in sorted(rows, key=lambda row: row.created_at or datetime.min, reverse=True)[:8]:
        recent.append(
            {
                "id": item.id,
                "status": item.status,
                "root_cause": item.root_cause or "",
                "category": item.category,
                "rating": item.rating,
                "question": (item.question_snapshot or "")[:220],
                "content": (item.content or "")[:220],
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
        )
    return {
        "total": len(rows),
        "new": by_status.get("new", 0),
        "unresolved": by_status.get("new", 0) + by_status.get("reviewed", 0),
        "by_status": by_status,
        "by_root_cause": by_root_cause,
        "by_category": by_category,
        "recent": recent,
    }


def _recent_unanswered_questions(db: Session, since: datetime, limit: int = 10) -> list[dict[str, Any]]:
    assistants = db.execute(
        select(ChatMessage)
        .where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
        .order_by(ChatMessage.created_at.desc())
        .limit(200)
    ).scalars().all()
    result: list[dict[str, Any]] = []
    for answer in assistants:
        sources = parse_json_list(answer.sources_json)
        low_source = not sources
        no_evidence_text = "未在知识库" in (answer.content or "") or "未找到" in (answer.content or "")
        if not low_source and not no_evidence_text:
            continue
        question = db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == answer.session_id,
                ChatMessage.role == "user",
                ChatMessage.created_at <= answer.created_at,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        result.append(
            {
                "session_id": answer.session_id,
                "message_id": answer.id,
                "question": (question.content if question else "")[:300],
                "answer_preview": (answer.content or "")[:300],
                "source_count": len(sources),
                "created_at": answer.created_at.isoformat() if answer.created_at else None,
            }
        )
        if len(result) >= limit:
            break
    return result


def _chat_stats(db: Session, since: datetime) -> dict[str, Any]:
    total_questions = db.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.role == "user", ChatMessage.created_at >= since)
    ) or 0
    total_answers = db.scalar(
        select(func.count(ChatMessage.id)).where(ChatMessage.role == "assistant", ChatMessage.created_at >= since)
    ) or 0
    sessions = db.scalar(select(func.count(func.distinct(ChatMessage.session_id))).where(ChatMessage.created_at >= since)) or 0
    unanswered = _recent_unanswered_questions(db, since)
    return {
        "question_count": int(total_questions),
        "answer_count": int(total_answers),
        "session_count": int(sessions),
        "recent_unanswered": unanswered,
        "unanswered_count_sample": len(unanswered),
    }


def _load_prompt_template_adoptions(db: Session) -> list[dict[str, Any]]:
    raw = get_setting(db, PROMPT_TEMPLATE_ADOPTIONS_SETTING_KEY, "")
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return []
    rows = payload.get("items") if isinstance(payload, dict) else payload
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


def _save_prompt_template_adoptions(db: Session, items: list[dict[str, Any]]) -> None:
    set_setting(db, PROMPT_TEMPLATE_ADOPTIONS_SETTING_KEY, json.dumps({"items": items[:300]}, ensure_ascii=False, indent=2))


def _prompt_template_adoption_stats(db: Session) -> dict[str, Any]:
    items = _load_prompt_template_adoptions(db)
    by_template: dict[str, dict[str, Any]] = {}
    by_kind: dict[str, int] = {}
    for item in items:
        for key in item.get("selected_template_keys") or []:
            key = str(key or "")
            if not key:
                continue
            row = by_template.setdefault(key, {"key": key, "wins": 0, "latest_at": ""})
            row["wins"] += 1
            row["latest_at"] = max(str(row.get("latest_at") or ""), str(item.get("created_at") or ""))
        for kind in item.get("document_kinds") or []:
            kind = str(kind or "general")
            by_kind[kind] = by_kind.get(kind, 0) + 1

    template_labels = {str(item.get("key") or ""): str(item.get("label") or item.get("key") or "") for item in shared_load_prompt_templates(db)}
    kind_labels = _document_kind_label_map(db)
    recommended_by_document_kind: list[dict[str, Any]] = []
    for kind, rows in recommended_prompt_template_keys_by_kind(db).items():
        if not rows:
            continue
        candidates = []
        for index, row in enumerate(rows):
            key = str(row.get("key") or "")
            candidates.append(
                {
                    "key": key,
                    "label": template_labels.get(key, key),
                    "wins": int(row.get("wins") or 0),
                    "latest_at": str(row.get("latest_at") or ""),
                    "is_recommended": index == 0,
                }
            )
        top = candidates[0]
        recommended_by_document_kind.append(
            {
                "kind": kind,
                "label": kind_labels.get(kind, kind),
                "template": top.get("key"),
                "template_label": top.get("label"),
                "wins": top.get("wins") or 0,
                "latest_at": top.get("latest_at") or "",
                "candidates": candidates,
            }
        )
    recommended_by_document_kind.sort(key=lambda item: (int(item.get("wins") or 0), str(item.get("latest_at") or "")), reverse=True)

    return {
        "total": len(items),
        "by_template": sorted(by_template.values(), key=lambda row: row.get("wins", 0), reverse=True)[:12],
        "by_document_kind": [{"kind": key, "count": value, "label": kind_labels.get(key, key)} for key, value in sorted(by_kind.items(), key=lambda row: row[1], reverse=True)[:12]],
        "recommended_by_document_kind": recommended_by_document_kind[:12],
        "recent": items[:10],
    }


@router.get("/api/admin/operations/overview")
def operations_overview(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    since = datetime.utcnow() - timedelta(days=days)
    total_docs = db.scalar(select(func.count(Document.id)).where(~Document.source_type.like("chat_%"))) or 0
    status_counts = _status_counts(db)
    searchable = db.scalar(select(func.count(DocumentProcessingStatus.document_id)).where(DocumentProcessingStatus.searchable == True)) or 0  # noqa: E712
    needs_review = db.scalar(select(func.count(Document.id)).where(Document.document_kind_status == "needs_review")) or 0
    low_confidence = db.scalar(select(func.count(Document.id)).where(Document.document_kind_confidence < 0.55)) or 0
    quality_payload = list_document_quality_reports(db, limit=300, include_chat=False)
    grade_counts: dict[str, int] = {}
    reparse_candidates: list[dict[str, Any]] = []
    for report in quality_payload.get("reports") or []:
        grade = str((report.get("quality") or {}).get("grade") or "unknown")
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        if report_needs_reparse(report):
            doc = report.get("document") or {}
            reparse_candidates.append(
                {
                    "document_id": doc.get("id"),
                    "title": doc.get("title") or doc.get("filename"),
                    "grade": grade,
                    "reasons": (report.get("quality") or {}).get("reasons") or [],
                }
            )
    feedback = _feedback_stats(db, since)
    chat = _chat_stats(db, since)
    prompt_adoptions = _prompt_template_adoption_stats(db)
    routing = get_document_routing_config(db)
    enabled_kinds = [item for item in routing.get("document_kinds") or [] if isinstance(item, dict) and not item.get("disabled")]
    disabled_kinds = [item for item in routing.get("document_kinds") or [] if isinstance(item, dict) and item.get("disabled")]

    risks: list[str] = []
    if status_counts.get("failed", 0):
        risks.append(f"有 {status_counts.get('failed', 0)} 份文档解析失败，可能影响回答命中。")
    if needs_review:
        risks.append(f"有 {needs_review} 份文档分类待复核。")
    if reparse_candidates:
        risks.append(f"有 {len(reparse_candidates)} 份文档质量建议重新解析。")
    if feedback["new"]:
        risks.append(f"有 {feedback['new']} 条新反馈待处理。")
    if chat["recent_unanswered"]:
        risks.append(f"最近有 {len(chat['recent_unanswered'])} 条无可靠来源回答样本。")
    if not enabled_kinds:
        risks.append("当前没有启用的文档类型，自动分类和路由会退化。")

    recommendations: list[str] = []
    if reparse_candidates:
        recommendations.append("先批量重新解析 blocked/poor 文档，再重新运行评测套件。")
    if needs_review or low_confidence:
        recommendations.append("优先复核低置信度文档类型，避免路由命中错误分类。")
    if feedback["by_root_cause"].get("retrieval_miss"):
        recommendations.append("对检索命中错误的反馈问题执行检索诊断，并沉淀为评测用例。")
    if chat["recent_unanswered"]:
        recommendations.append("把无来源高频问题补充到知识库或新增对应分类关键词。")
    if not recommendations:
        recommendations.append("当前运营风险较低，建议定期运行评测套件并查看新增反馈。")

    return {
        "ok": True,
        "days": days,
        "generated_at": datetime.utcnow().isoformat(),
        "documents": {
            "total": int(total_docs),
            "searchable": int(searchable),
            "failed": int(status_counts.get("failed", 0)),
            "processing": int(status_counts.get("processing", 0) + status_counts.get("pending", 0)),
            "needs_review_classification": int(needs_review),
            "low_confidence_classification": int(low_confidence),
            "by_status": status_counts,
            "by_kind": _document_kind_counts(db),
        },
        "quality": {
            "grade_counts": grade_counts,
            "reparse_candidate_count": len(reparse_candidates),
            "reparse_candidates": reparse_candidates[:10],
        },
        "routing": {
            "enabled_kind_count": len(enabled_kinds),
            "disabled_kind_count": len(disabled_kinds),
            "enabled_kinds": [{"value": item.get("value"), "label": item.get("label")} for item in enabled_kinds],
            "disabled_kinds": [{"value": item.get("value"), "label": item.get("label")} for item in disabled_kinds],
        },
        "chat": chat,
        "feedback": feedback,
        "prompt_adoptions": prompt_adoptions,
        "risk_signals": risks,
        "recommendations": recommendations,
    }


@router.get("/api/admin/prompt-templates")
def get_prompt_templates(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {
        "ok": True,
        "templates": shared_load_prompt_templates(db),
        "defaults": SHARED_DEFAULT_PROMPT_TEMPLATES,
        "note": "当前为后台可维护模板配置；后续可按文档类型接入回答生成链路。",
    }


@router.post("/api/admin/prompt-templates/preview")
def preview_prompt_templates(req: PromptTemplatePreviewRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入要预览的测试问题")
    top_k = max(1, min(int(req.top_k or 8), 20))
    contexts, retrieval_backend, retrieval_note, candidate_count, retrieval_meta = adaptive_retrieve_contexts(
        db,
        question,
        user,
        top_k,
        knowledge_scope=req.knowledge_scope,
    )
    answer_contexts = model_contexts_for_answer(contexts, False)
    table_answer_mode = retrieval_meta.get("retrieval_route", {}).get("name") == "table"
    template_context = select_prompt_templates_for_contexts(
        db,
        answer_contexts,
        table_answer_mode=table_answer_mode,
        no_source=not bool(answer_contexts),
    )
    kind_labels = _document_kind_label_map(db)
    kind_counts: dict[str, int] = {}
    for context in answer_contexts or contexts or []:
        kind = str(context.get("document_kind") or "general")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
    matched_kinds = [
        {"kind": kind, "label": kind_labels.get(kind, kind), "count": count}
        for kind, count in sorted(kind_counts.items(), key=lambda item: item[1], reverse=True)
    ]
    source_diagnostics = []
    for index, context in enumerate((answer_contexts or contexts)[:8], start=1):
        content = " ".join(str(context.get("content") or "").split())
        kind = str(context.get("document_kind") or "general")
        source_diagnostics.append(
            {
                "rank": index,
                "document_id": context.get("document_id") or "",
                "document_title": context.get("document_title") or context.get("filename") or "未知文档",
                "filename": context.get("filename") or "",
                "document_kind": kind,
                "document_kind_label": kind_labels.get(kind, kind),
                "retrieval_channel": context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"),
                "score": context.get("score"),
                "rerank_score": context.get("rerank_score"),
                "location": context.get("location") or f"chunk {context.get('chunk_index') if context.get('chunk_index') is not None else '-'}",
                "preview": content[:700],
            }
        )
    return {
        "ok": True,
        "question": question,
        "top_k": top_k,
        "knowledge_scope": req.knowledge_scope,
        "retrieval_backend": retrieval_backend,
        "retrieval_note": retrieval_note,
        "candidate_count": candidate_count,
        "answer_context_count": len(answer_contexts),
        "source_count": len(contexts),
        "retrieval_route": retrieval_meta.get("retrieval_route") or {},
        "query_analysis": retrieval_meta.get("query_analysis") or {},
        "matched_document_kinds": matched_kinds,
        "prompt_template": {
            "keys": template_context.get("keys") or [],
            "labels": template_context.get("labels") or [],
            "count": template_context.get("count") or 0,
            "recommended": template_context.get("recommended") or [],
            "applied_to_answer": bool(answer_contexts) and not table_answer_mode,
        },
        "rules_preview": {
            "base_rules": [
                "保留系统原有知识库问答基础规则。",
                "仅把以下模板作为附加规则追加到模型系统提示词。",
                "检索不到可用证据时不会调用知识回答模型。",
            ],
            "template_instructions": template_context.get("instructions") or "",
        },
        "source_diagnostics": source_diagnostics,
        "retrieval_meta": retrieval_meta,
    }


def _answer_quality_heuristics(answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    text = str(answer or "")
    has_structure = any(marker in text for marker in ["\n-", "\n1.", "|", "###", "**"])
    no_evidence = "未找到" in text or "未在知识库" in text or "不足" in text[:120]
    source_terms = []
    for source in sources[:6]:
        title = str(source.get("document_title") or source.get("filename") or "").strip()
        if title:
            source_terms.append(title)
    cited_source_hint = any(term and term in text for term in source_terms)
    return {
        "length": len(text),
        "has_structure": has_structure,
        "mentions_no_evidence": no_evidence,
        "mentions_source_title": cited_source_hint,
        "source_count": len(sources),
    }


def _compare_variant_answer(
    question: str,
    contexts: list[dict[str, Any]],
    template_context: dict[str, Any],
    cfg: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    instructions = template_context.get("instructions") or ""
    if dry_run:
        answer = extractive_fallback_answer(question, contexts, "dry_run_prompt_compare")
        generated = False
    else:
        answer = chat_answer_v2(
            question,
            contexts,
            cfg.get("api_key"),
            cfg.get("base_url"),
            cfg.get("model"),
            prompt_instructions=instructions,
        )
        generated = True
    return {
        "prompt_template": {
            "keys": template_context.get("keys") or [],
            "labels": template_context.get("labels") or [],
            "count": template_context.get("count") or 0,
            "instructions": instructions,
        },
        "answer": answer,
        "generated": generated,
        "quality_signals": _answer_quality_heuristics(answer, contexts),
    }


@router.post("/api/admin/prompt-templates/compare")
def compare_prompt_templates(req: PromptTemplateCompareRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入要对比的测试问题")
    top_k = max(1, min(int(req.top_k or 8), 20))
    contexts, retrieval_backend, retrieval_note, candidate_count, retrieval_meta = adaptive_retrieve_contexts(
        db,
        question,
        user,
        top_k,
        knowledge_scope=req.knowledge_scope,
    )
    answer_contexts = model_contexts_for_answer(contexts, False)
    if not answer_contexts:
        raise HTTPException(status_code=400, detail="当前问题没有命中可用于回答的来源片段，请先补充文档或调整问题")
    template_a = prompt_template_context_for_keys(db, req.template_a_keys)
    template_b = prompt_template_context_for_keys(db, req.template_b_keys)
    if not template_a.get("count") or not template_b.get("count"):
        raise HTTPException(status_code=400, detail="请选择 A/B 两组有效且启用的 Prompt 模板")
    cfg = get_model_config(db)
    variant_a = _compare_variant_answer(question, answer_contexts, template_a, cfg, dry_run=bool(req.dry_run))
    variant_b = _compare_variant_answer(question, answer_contexts, template_b, cfg, dry_run=bool(req.dry_run))
    source_diagnostics = []
    for index, context in enumerate(answer_contexts[:8], start=1):
        content = " ".join(str(context.get("content") or "").split())
        source_diagnostics.append(
            {
                "rank": index,
                "document_id": context.get("document_id") or "",
                "document_title": context.get("document_title") or context.get("filename") or "未知文档",
                "filename": context.get("filename") or "",
                "document_kind": context.get("document_kind") or "general",
                "retrieval_channel": context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"),
                "score": context.get("score"),
                "rerank_score": context.get("rerank_score"),
                "location": context.get("location") or f"chunk {context.get('chunk_index') if context.get('chunk_index') is not None else '-'}",
                "preview": content[:700],
            }
        )
    return {
        "ok": True,
        "question": question,
        "dry_run": bool(req.dry_run),
        "retrieval_backend": retrieval_backend,
        "retrieval_note": retrieval_note,
        "candidate_count": candidate_count,
        "answer_context_count": len(answer_contexts),
        "retrieval_route": retrieval_meta.get("retrieval_route") or {},
        "variant_a": variant_a,
        "variant_b": variant_b,
        "source_diagnostics": source_diagnostics,
        "retrieval_meta": retrieval_meta,
        "comparison_tips": [
            "优先选择结构清晰、没有无依据扩写、能说明来源依据的版本。",
            "如果两版都不理想，先检查命中文档和切片质量，再调整模板。",
            "dry_run 只使用抽取式预览；关闭 dry_run 才会调用模型生成真实回答。",
        ],
    }


@router.get("/api/admin/prompt-templates/adoptions")
def list_prompt_template_adoptions(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return {"ok": True, "stats": _prompt_template_adoption_stats(db)}


@router.post("/api/admin/prompt-templates/adoptions")
def create_prompt_template_adoption(req: PromptTemplateAdoptionRequest, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    question = (req.question or "").strip()
    selected_variant = str(req.selected_variant or "").strip().lower()
    selected_keys = list(dict.fromkeys(str(key).strip() for key in req.selected_template_keys if str(key).strip()))
    rejected_keys = list(dict.fromkeys(str(key).strip() for key in req.rejected_template_keys if str(key).strip()))
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    if selected_variant not in {"a", "b"}:
        raise HTTPException(status_code=400, detail="selected_variant 只能是 a 或 b")
    if not selected_keys:
        raise HTTPException(status_code=400, detail="请选择被采用的模板")
    known_keys = {str(item.get("key") or "") for item in shared_load_prompt_templates(db)}
    invalid_keys = [key for key in selected_keys + rejected_keys if key not in known_keys]
    if invalid_keys:
        raise HTTPException(status_code=400, detail=f"模板不存在或未启用：{', '.join(invalid_keys)}")
    item = {
        "id": new_id(),
        "question": question[:1000],
        "selected_variant": selected_variant,
        "selected_template_keys": selected_keys[:8],
        "rejected_template_keys": rejected_keys[:8],
        "document_kinds": list(dict.fromkeys(str(kind).strip() for kind in req.document_kinds if str(kind).strip()))[:12],
        "source_document_ids": list(dict.fromkeys(str(doc_id).strip() for doc_id in req.source_document_ids if str(doc_id).strip()))[:20],
        "admin_note": (req.admin_note or "").strip()[:1000],
        "dry_run": bool(req.dry_run),
        "created_by": actor.username,
        "created_at": datetime.utcnow().isoformat(),
    }
    items = _load_prompt_template_adoptions(db)
    items.insert(0, item)
    _save_prompt_template_adoptions(db, items)
    audit(db, actor, "prompt_template.adopt", "setting", PROMPT_TEMPLATE_ADOPTIONS_SETTING_KEY, {"id": item["id"], "selected_variant": selected_variant, "selected_template_keys": selected_keys})
    db.commit()
    return {"ok": True, "item": item, "stats": _prompt_template_adoption_stats(db)}


@router.put("/api/admin/prompt-templates")
def save_prompt_templates(req: PromptTemplatesPayload, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in req.templates:
        try:
            item = shared_normalize_prompt_template(raw.dict())
        except ValueError as exc:
            code = str(exc)
            if code == "template_key_required":
                raise HTTPException(status_code=400, detail="模板 key 不能为空") from exc
            if code == "template_content_required":
                raise HTTPException(status_code=400, detail="模板内容不能为空") from exc
            if code == "template_content_too_long":
                raise HTTPException(status_code=400, detail="单个模板内容不能超过 4000 字") from exc
            raise
        if item["key"] in seen:
            raise HTTPException(status_code=400, detail=f"模板 key 重复：{item['key']}")
        seen.add(item["key"])
        normalized.append(item)
    if not normalized:
        raise HTTPException(status_code=400, detail="至少保留一个 Prompt 模板")
    set_setting(db, SHARED_PROMPT_TEMPLATES_SETTING_KEY, json.dumps(normalized, ensure_ascii=False, indent=2))
    audit(db, actor, "prompt_templates.update", "setting", SHARED_PROMPT_TEMPLATES_SETTING_KEY, {"count": len(normalized)})
    db.commit()
    return {"ok": True, "templates": normalized}


@router.post("/api/admin/prompt-templates/reset")
def reset_prompt_templates(db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    templates = [dict(item) for item in SHARED_DEFAULT_PROMPT_TEMPLATES]
    set_setting(db, SHARED_PROMPT_TEMPLATES_SETTING_KEY, json.dumps(templates, ensure_ascii=False, indent=2))
    audit(db, actor, "prompt_templates.reset", "setting", SHARED_PROMPT_TEMPLATES_SETTING_KEY, {"count": len(templates)})
    db.commit()
    return {"ok": True, "templates": templates}
