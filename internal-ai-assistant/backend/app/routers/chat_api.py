import json
import re
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..admin_schemas import ChatRequest, FeedbackCreate
from ..ai_client import chat_answer_v2, classify_chat_intent, conversational_answer, extractive_fallback_answer, stream_chat_answer_v2, stream_conversational_answer
from ..chat_interaction import (
    accessible_document_summary_contexts,
    append_interaction_footer,
    build_interaction_suggestions,
    is_accessible_summary_request,
    is_conversation_only_request,
    is_explicit_knowledge_request,
    is_followup_request,
    is_knowledge_intent,
    is_standalone_editing_request,
    recent_source_contexts,
)
from ..database import SessionLocal, get_db
from ..document_routing_config import get_document_routing_config, infer_document_kind_from_config
from ..grounding import compute_grounding_confidence, filter_relevant_contexts, grounding_reason_for_contexts, serialize_sources
from ..models import ChatMessage, ChatSession, Document, Feedback, User
from ..prompt_template_service import select_prompt_templates_for_contexts
from ..retrieval import adaptive_retrieve_contexts
from ..routers.admin_feedback import FEEDBACK_CATEGORIES
from ..settings_service import get_model_config
from ..structured_digest import build_structured_digest, should_use_structured_digest
from ..table_query import build_table_answer, build_table_structured_result, is_table_query
from ..task_service import enqueue_document_task
from ..upload_policy import CHAT_FILE_EXTENSIONS, IMAGE_EXTENSIONS
from ..upload_security import validate_upload_file
from ..upload_storage import save_upload
from .deps import LOW_CONFIDENCE_THRESHOLD, audit, new_id, parse_json_list, require_admin, require_user

router = APIRouter()


INLINE_SOURCE_MARKER_RE = re.compile(r"\s*[\[（(]来源\s*\d+[\]）)]")


def strip_inline_source_markers(answer: str) -> str:
    return INLINE_SOURCE_MARKER_RE.sub("", answer or "")


def _main_compat_callable(name: str):
    """Resolve legacy app.main monkeypatch hooks lazily to avoid router/main circular imports."""
    try:
        import app.main as app_main
    except ImportError:
        return None
    return getattr(app_main, name, None)


def _is_default_ai_client_callable(func, name: str) -> bool:
    """Return True for the default ai_client implementation imported by app.main.

    app.main imports the old chat_answer for backwards compatibility. Treat that
    default import as non-overridden so the router can use the newer v2 grounded
    answer path in real runtime, while still allowing tests to monkeypatch it.
    """
    module = str(getattr(func, "__module__", ""))
    return getattr(func, "__name__", "") == name and module.endswith("ai_client")


@router.post("/api/chat/attachments")
def upload_chat_attachment(file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(require_user)):
    _, ext = validate_upload_file(file, CHAT_FILE_EXTENSIONS, "聊天附件支持 PDF、Word(.docx)、PowerPoint(.pptx)、Excel(.xlsx)、CSV、TXT、Markdown、PNG、JPG、WEBP、GIF。")
    doc_id, storage_path, filename = save_upload(file, "chat")

    source_type = "chat_image" if ext in IMAGE_EXTENSIONS else f"chat_{ext.lstrip('.')}"
    title = Path(filename).stem
    classification = infer_document_kind_from_config(db, title, filename, source_type)
    confidence = float(classification.get("confidence") or 0.0)
    threshold = float(get_document_routing_config(db).get("classification", {}).get("low_confidence_threshold", 0.55) or 0.55)
    doc = Document(
        id=doc_id,
        title=title,
        filename=filename,
        storage_path=str(storage_path),
        source_type=source_type,
        knowledge_scope="production",
        document_kind=str(classification.get("kind") or "general"),
        document_kind_confidence=confidence,
        document_kind_reason="; ".join(str(item) for item in classification.get("reasons") or [])[:1000],
        document_kind_status="needs_review" if confidence < threshold else "auto",
        created_by=user.id,
    )
    db.add(doc)
    db.flush()
    task = enqueue_document_task(db, doc, "chat_attachment_parse", user)
    db.commit()
    return {"id": doc.id, "title": doc.title, "filename": filename, "kind": ext.lstrip("."), "searchable": False, "chunks": 0, "status": "queued", "task_id": task.id, "message": "附件已上传，正在后台解析/OCR。完成后会自动参与检索。"}


def retrieve_contexts(db: Session, question: str, user: User, top_k: int = 5, knowledge_scope: str = "production"):
    return adaptive_retrieve_contexts(db, question, user, top_k, knowledge_scope=knowledge_scope)


def summary_display_sources(contexts: list[dict], interaction_meta: dict, summary_mode: bool) -> list[dict]:
    if summary_mode:
        source_contexts = interaction_meta.get("source_contexts") or []
        if source_contexts:
            return serialize_sources(source_contexts)
    return serialize_sources(contexts)


GENERIC_ANSWER_MATCH_TERMS = {"公", "司", "公司", "员工", "标准", "模板", "资料", "材料", "信息", "字段", "需要", "提供", "是", "有", "在", "今年", "什么", "哪些", "多少", "是否", "吗"}


def _safe_context_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _looks_like_weak_generic_answer_context(context: dict, ranking: dict) -> bool:
    """Reject contexts that only match generic words such as 公司/是.

    Retrieval may still surface these as UI candidates, but sending them into the
    answer composer makes unrelated questions look grounded and can trigger slow
    model calls. Keep contexts with explicit intent signals, specific match terms,
    or strong semantic scores.
    """

    if ranking.get("positive_signals"):
        return False
    match_terms = [str(term).strip() for term in (context.get("match_terms") or []) if str(term).strip()]
    specific_terms = [term for term in match_terms if len(term) >= 2 and term not in GENERIC_ANSWER_MATCH_TERMS]
    lexical_coverage = _safe_context_float(ranking.get("lexical_coverage"), 0.0)
    best_score = max(_safe_context_float(context.get("rerank_score"), 0.0), _safe_context_float(context.get("score"), 0.0))
    if not specific_terms:
        return best_score < 0.58
    return lexical_coverage < 0.12 and best_score < 0.58


def _answer_context_is_relevant(context: dict) -> bool:
    source_quality = context.get("source_quality") if isinstance(context.get("source_quality"), dict) else {}
    if source_quality.get("grade") == "blocked":
        return False

    channel = context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "")
    if channel == "table" and context.get("is_header"):
        return False
    if channel in {"table", "graph"}:
        return True

    ranking = context.get("intent_ranking") if isinstance(context.get("intent_ranking"), dict) else {}
    if _looks_like_weak_generic_answer_context(context, ranking):
        return False
    if channel == "pageindex":
        return True
    if ranking.get("positive_signals"):
        return True

    for key in ("rerank_score", "score"):
        if context.get(key) is None:
            continue
        try:
            return float(context.get(key) or 0) > 0
        except (TypeError, ValueError):
            return True
    return False


def _cap_answer_contexts(contexts: list[dict], max_contexts: int, max_chars: int) -> list[dict]:
    selected: list[dict] = []
    used_chars = 0
    for context in contexts:
        if len(selected) >= max_contexts or used_chars >= max_chars:
            break
        content = str(context.get("content") or "")
        remaining_chars = max_chars - used_chars
        if len(content) > remaining_chars:
            if remaining_chars <= 0:
                break
            clipped = dict(context)
            clipped["content"] = content[:remaining_chars].rstrip() + "..."
            clipped["context_clipped_for_answer"] = True
            selected.append(clipped)
            used_chars += remaining_chars
            break
        selected.append(context)
        used_chars += len(content)
    return selected


def model_contexts_for_answer(contexts: list[dict], summary_mode: bool, max_contexts: int = 600, max_chars: int = 500000) -> list[dict]:
    if not summary_mode:
        relevant = [context for context in contexts if _answer_context_is_relevant(context)]
        # Normal chat turns should not send dozens of long chunks to the model. Keep
        # the strongest evidence, while the full source list remains available for UI citations.
        return _cap_answer_contexts(relevant, max_contexts=min(max_contexts, 8), max_chars=min(max_chars, 18000))
    selected = _cap_answer_contexts(contexts, max_contexts=max_contexts, max_chars=max_chars)
    return selected


def table_contexts_for_answer(contexts: list[dict]) -> list[dict]:
    """Use all relevant table data rows for deterministic table answers.

    The 8-context cap above protects LLM prompts, but table answers are composed
    locally from structured rows. Applying the model cap would truncate counts
    and distinct lists such as city lists.
    """
    return [context for context in contexts if _answer_context_is_relevant(context)]


_TABLE_LLM_ANALYSIS_TERMS = (
    "分析",
    "总结",
    "归纳",
    "建议",
    "风险",
    "异常",
    "原因",
    "为什么",
    "怎么看",
    "评估",
    "评价",
    "对比",
    "趋势",
    "优先级",
    "优先",
    "推进",
    "下一步",
    "洞察",
    "延伸",
    "进一步",
    "关注",
    "短板",
    "瓶颈",
    "缺口",
)


def should_use_table_llm_analysis(question: str) -> bool:
    """Route analytical table questions to the LLM with a full structured digest."""
    compact_question = re.sub(r"\s+", "", question or "")
    return any(term in compact_question for term in _TABLE_LLM_ANALYSIS_TERMS)


def build_table_fact_block(question: str, table_contexts: list[dict]) -> tuple[str, dict]:
    """Build deterministic table facts that the LLM may explain but must not recalculate differently."""
    if not table_contexts:
        return "", {}
    local_answer = build_table_answer(question, table_contexts)
    structured_result = build_table_structured_result(question, table_contexts)
    rows = structured_result.get("rows") if isinstance(structured_result, dict) else []
    columns = structured_result.get("columns") if isinstance(structured_result, dict) else []
    lines = [
        "## 规则计算结果（硬事实，必须保持一致）",
        "- 生成方式：系统已先按表格结构化行完成筛选、去重、计数和字段提取；LLM 只能解释、归纳和提出建议，不能改写这些数字或明细。",
        "- 如果用户追问风险/建议/原因，只能基于下方规则结果和表格证据做分析；表里没有的信息要明确说明“表格未提供”。",
        "",
        "### 规则回答",
        local_answer,
    ]
    if columns and rows:
        lines.extend(["", "### 结构化结果预览", "| " + " | ".join(str(item) for item in columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"])
        for row in rows[:40]:
            if isinstance(row, list):
                lines.append("| " + " | ".join(str(item or "") for item in row) + " |")
        if len(rows) > 40:
            lines.append(f"- 还有 {len(rows) - 40} 行结构化结果未在预览中展开。")
    return "\n".join(lines), structured_result if isinstance(structured_result, dict) else {}


def merge_table_fact_block(structured_digest: str, fact_block: str) -> str:
    if not fact_block:
        return structured_digest
    return f"{fact_block}\n\n{structured_digest}".strip() if structured_digest else fact_block


def digest_contexts_for_answer(contexts: list[dict], answer_contexts: list[dict], *, table_answer_mode: bool) -> list[dict]:
    if table_answer_mode:
        return table_contexts_for_answer(contexts)
    return answer_contexts


def should_use_fast_extractive_answer(question: str, contexts: list[dict], retrieval_meta: dict, *, summary_mode: bool, table_answer_mode: bool) -> bool:
    if summary_mode or table_answer_mode or not contexts:
        return False
    intent = str(retrieval_meta.get("intent") or "")
    if intent not in {"deep_analysis", "broad_business"}:
        return False
    total_chars = sum(len(str(context.get("content") or "")) for context in contexts)
    pageindex_count = sum(1 for context in contexts if context.get("pageindex_source") or context.get("retrieval_channel") == "pageindex")
    broad_markers = ("主要", "哪些", "有哪些", "总结", "概括", "功能", "需求", "流程")
    compact_question = re.sub(r"\s+", "", question or "")
    broad_question = any(marker in compact_question for marker in broad_markers)
    return len(contexts) >= 5 and (total_chars >= 7000 or (broad_question and pageindex_count >= 1))


LOW_SOURCE_QUALITY_GRADES = {"poor", "blocked"}
SOURCE_QUALITY_WARNING = "部分来源质量较低，请结合原文或后台体检结果核验答案。"


def build_source_quality_notice(sources: list[dict]) -> dict:
    grade_counts: dict[str, int] = {}
    reasons: set[str] = set()
    affected_documents: dict[str, str] = {}
    affected_source_count = 0

    for source in sources or []:
        if not isinstance(source, dict):
            continue
        quality = source.get("source_quality") or {}
        if not isinstance(quality, dict):
            quality = {}
        grade = str(quality.get("grade") or "").lower()
        if grade not in LOW_SOURCE_QUALITY_GRADES:
            continue

        affected_source_count += 1
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        doc_key = str(source.get("document_id") or source.get("filename") or source.get("document_title") or affected_source_count)
        doc_title = str(source.get("document_title") or source.get("title") or source.get("filename") or doc_key)
        affected_documents.setdefault(doc_key, doc_title)
        for reason in quality.get("reasons") or []:
            if reason:
                reasons.add(str(reason))

    has_low_quality = affected_source_count > 0
    return {
        "has_low_quality_sources": has_low_quality,
        "warning": SOURCE_QUALITY_WARNING if has_low_quality else "",
        "affected_source_count": affected_source_count,
        "affected_document_count": len(affected_documents),
        "grades": grade_counts,
        "reasons": sorted(reasons),
        "documents": list(affected_documents.values())[:6],
    }


def build_prompt_context_preview(contexts: list[dict], max_chars_per_source: int = 1200, max_total_chars: int = 12000) -> dict:
    blocks: list[str] = []
    total_chars = 0
    clipped_sources = 0
    for index, context in enumerate(contexts or [], start=1):
        content = str(context.get("content") or "")
        normalized = " ".join(content.split())
        clipped = len(normalized) > max_chars_per_source
        if clipped:
            clipped_sources += 1
            normalized = normalized[:max_chars_per_source].rstrip() + "…"
        block = (
            f"[来源{index}] 文档：{context.get('document_title') or context.get('filename') or '未知文档'}；"
            f"页码：{context.get('page_number') or '未知'}；"
            f"类型：{context.get('source_type') or 'document'}；"
            f"位置：{context.get('location') or context.get('chunk_index') or '-'}\n"
            f"{normalized}"
        )
        if total_chars + len(block) > max_total_chars:
            blocks.append("…后续来源因预览长度限制已省略")
            break
        blocks.append(block)
        total_chars += len(block)
    return {
        "text": "\n\n".join(blocks),
        "source_count": len(contexts or []),
        "previewed_source_count": len([block for block in blocks if block.startswith("[来源")]),
        "clipped_sources": clipped_sources,
        "max_chars_per_source": max_chars_per_source,
        "max_total_chars": max_total_chars,
    }


def build_retrieval_debug_summary(contexts: list[dict], candidate_count: int, confidence: float, quality_notice: dict) -> dict:
    document_ids = {str(c.get("document_id") or c.get("filename") or c.get("document_title") or "") for c in contexts or [] if c}
    channels: dict[str, int] = {}
    for context in contexts or []:
        channel = str(context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"))
        channels[channel] = channels.get(channel, 0) + 1
    warnings: list[str] = []
    if not contexts:
        warnings.append("没有命中可用于回答的片段")
    if candidate_count and len(contexts) < min(candidate_count, 3):
        warnings.append("候选被过滤较多，请检查关键词或权限范围")
    if confidence < LOW_CONFIDENCE_THRESHOLD and contexts:
        warnings.append("整体置信度偏低，请重点核验前几条来源")
    if quality_notice.get("has_low_quality_sources"):
        warnings.append(quality_notice.get("warning") or SOURCE_QUALITY_WARNING)
    return {
        "answer_context_count": len(contexts or []),
        "unique_document_count": len(document_ids),
        "candidate_count": candidate_count,
        "channel_counts": channels,
        "confidence": confidence,
        "warnings": warnings,
    }


def _call_knowledge_answer(question: str, contexts: list[dict], api_key: str | None, base_url: str | None, model: str | None, history: list[dict] | None = None, structured_digest: str = "", prompt_instructions: str = "") -> str:
    legacy_answer = _main_compat_callable("chat_answer")
    if callable(legacy_answer) and not _is_default_ai_client_callable(legacy_answer, "chat_answer"):
        try:
            return legacy_answer(question, contexts, api_key, base_url, model, history=history)
        except TypeError:
            return legacy_answer(question, contexts, api_key, base_url, model)
    return chat_answer_v2(question, contexts, api_key, base_url, model, history=history, structured_digest=structured_digest, prompt_instructions=prompt_instructions)


def recent_chat_history(db: Session, session_id: str, user: User, max_messages: int = 6) -> List[dict]:
    session = db.get(ChatSession, session_id)
    if not session or session.user_id != user.id:
        return []
    rows = db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc(), ChatMessage.role.desc(), ChatMessage.id.asc())
    ).scalars().all()
    items = [{"role": m.role, "content": m.content} for m in rows if m.role in ("user", "assistant") and m.content]
    return items[-max_messages:]


BUSINESS_KNOWLEDGE_ANCHORS = (
    "公司",
    "员工",
    "社保",
    "医保",
    "公积金",
    "合同",
    "工单",
    "制度",
    "政策",
    "流程",
    "资料",
    "文档",
    "表单",
    "年会",
    "抽奖",
    "一等奖",
)
BUSINESS_QUESTION_MARKERS = ("什么", "哪些", "多少", "是否", "怎么", "如何", "哪", "吗", "？", "?")


def is_business_knowledge_like_request(question: str) -> bool:
    text = re.sub(r"\s+", "", (question or "").strip().lower())
    if not text or is_conversation_only_request(text):
        return False
    if len(text) < 6:
        return False
    return any(anchor in text for anchor in BUSINESS_KNOWLEDGE_ANCHORS) and any(marker in text for marker in BUSINESS_QUESTION_MARKERS)


def decide_chat_route(question: str, history: list[dict], cfg: dict) -> dict:
    """Route a chat turn using fast rules first, then AI classification for ambiguous cases."""
    if is_standalone_editing_request(question, has_history=bool(history)):
        return {"intent": "chat", "should_retrieve": False, "summary_mode": False, "followup_mode": False, "source": "rule_standalone_editing", "reason": "editing_request_without_context"}
    if is_conversation_only_request(question):
        return {"intent": "chat", "should_retrieve": False, "summary_mode": False, "followup_mode": False, "source": "rule_conversation", "reason": "conversation_only"}
    if is_accessible_summary_request(question):
        return {"intent": "summary", "should_retrieve": True, "summary_mode": True, "followup_mode": False, "source": "rule_summary", "reason": "accessible_summary_request"}
    if is_followup_request(question):
        return {"intent": "followup", "should_retrieve": True, "summary_mode": False, "followup_mode": True, "source": "rule_followup", "reason": "followup_request"}
    if is_table_query(question):
        return {"intent": "knowledge", "should_retrieve": True, "summary_mode": False, "followup_mode": False, "source": "rule_table_query", "reason": "table_query_keyword"}
    if is_explicit_knowledge_request(question):
        return {"intent": "knowledge", "should_retrieve": True, "summary_mode": False, "followup_mode": False, "source": "rule_knowledge", "reason": "explicit_knowledge_keyword"}
    if is_business_knowledge_like_request(question):
        return {"intent": "knowledge", "should_retrieve": True, "summary_mode": False, "followup_mode": False, "source": "rule_business_knowledge", "reason": "business_question_keyword"}

    classified = classify_chat_intent(question, history, cfg.get("api_key"), cfg.get("base_url"), cfg.get("model"))
    intent = classified.get("intent") or "unknown"
    should = classified.get("should_retrieve")
    if should is None:
        should = is_knowledge_intent(question)
        source = "fallback_rule"
    else:
        source = "ai_classifier"
    return {
        "intent": intent if intent in {"chat", "knowledge", "summary", "followup"} else ("knowledge" if should else "chat"),
        "should_retrieve": bool(should),
        "summary_mode": intent == "summary",
        "followup_mode": intent == "followup",
        "source": source,
        "reason": classified.get("reason") or "classified",
        "confidence": classified.get("confidence", 0.0),
    }


@router.post("/api/chat")
def chat(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(require_user)):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入问题")
    if req.session_id:
        existing = db.get(ChatSession, req.session_id)
        if not existing or existing.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    limit = max(1, min(req.top_k, 10))
    cfg = get_model_config(db)
    history = recent_chat_history(db, req.session_id, user) if req.session_id else []
    route = decide_chat_route(question, history, cfg)
    summary_mode = bool(route.get("summary_mode"))
    followup_mode = bool(route.get("followup_mode"))
    should_retrieve = bool(route.get("should_retrieve"))
    conversation_only = not should_retrieve
    recent_context_used = False
    interaction_meta: dict = {}
    retrieval_meta: dict = {"route": route, "intent": route.get("intent"), "classifier_source": route.get("source"), "classifier_reason": route.get("reason")}
    if summary_mode:
        contexts, interaction_meta = accessible_document_summary_contexts(db, user, per_doc_chunks=None, max_docs=None)
        retrieval_backend = "accessible_documents"
        retrieval_note = "summary_intent_all_accessible_documents"
        candidate_count = int(interaction_meta.get("document_count") or len(contexts))
        retrieval_meta.update({"mode": "summary", "final_context_count": len(contexts), "candidate_count": candidate_count})
    elif not should_retrieve:
        contexts = []
        retrieval_backend = "none"
        retrieval_note = "conversation_only_intent"
        candidate_count = 0
        retrieval_meta.update({"mode": "chat", "final_context_count": 0, "candidate_count": 0})
    else:
        contexts, retrieval_backend, retrieval_note, candidate_count, retrieved_meta = retrieve_contexts(db, question, user, limit, knowledge_scope=req.knowledge_scope)
        retrieval_meta.update(retrieved_meta or {})
        if followup_mode:
            followup_limit = max(int(retrieval_meta.get("target_contexts") or limit), 6)
            recent_contexts = recent_source_contexts(db, req.session_id, user, limit=followup_limit)
            if recent_contexts:
                seen = {(c.get("document_id") or "", c.get("chunk_id") or str(c.get("chunk_index") or "")) for c in recent_contexts}
                contexts = recent_contexts + [
                    c for c in contexts
                    if (c.get("document_id") or "", c.get("chunk_id") or str(c.get("chunk_index") or "")) not in seen
                ]
                contexts = contexts[: followup_limit]
                retrieval_meta["recent_contexts_merged"] = len(recent_contexts)
                retrieval_meta["final_context_count"] = len(contexts)
                recent_context_used = True
        if recent_context_used:
            retrieval_note = f"{retrieval_note}; recent_context_used" if retrieval_note else "recent_context_used"
        elif contexts and retrieval_backend != "qdrant":
            retrieval_note = retrieval_note or "recent_context_or_sqlite"

    sources = summary_display_sources(contexts, interaction_meta, summary_mode)
    source_quality_notice = build_source_quality_notice(sources)
    answer_contexts = model_contexts_for_answer(contexts, summary_mode)
    retrieval_meta["answer_context_count"] = len(answer_contexts)
    retrieval_meta["answer_context_filtered_count"] = max(0, len(contexts) - len(answer_contexts))
    confidence = compute_grounding_confidence(answer_contexts)
    if summary_mode and answer_contexts:
        confidence = max(confidence, 0.72)
    if recent_context_used and answer_contexts:
        confidence = max(confidence, 0.62)
    grounded = bool(answer_contexts)
    grounding_reason = grounding_reason_for_contexts(answer_contexts, confidence)
    table_answer_mode = retrieval_meta.get("retrieval_route", {}).get("name") == "table"
    table_llm_analysis_mode = table_answer_mode and should_use_table_llm_analysis(question)
    suggestions = [] if conversation_only else build_interaction_suggestions(question, answer_contexts, summary_mode=summary_mode)
    digest_contexts = digest_contexts_for_answer(contexts, answer_contexts, table_answer_mode=table_answer_mode)
    retrieval_meta["structured_digest_context_count"] = len(digest_contexts)
    structured_digest = build_structured_digest(question, digest_contexts, summary_mode) if should_use_structured_digest(question, digest_contexts, summary_mode) else ""
    if not contexts or (should_retrieve and not summary_mode and not answer_contexts):
        if should_retrieve:
            if contexts and not answer_contexts:
                retrieval_note = f"{retrieval_note}; answer_evidence_filtered" if retrieval_note else "answer_evidence_filtered"
                retrieval_meta["candidate_source_count_before_answer_filter"] = len(sources)
                sources = []
                source_quality_notice = build_source_quality_notice(sources)
                answer = "未在知识库中找到充分依据：虽然检索到了一些候选片段，但没有达到可用于回答的证据门槛。请换一个更具体的问题，或让管理员检查文档解析、授权和检索配置。"
            else:
                sources = []
                source_quality_notice = build_source_quality_notice(sources)
                answer = "未在知识库中找到依据：当前没有检索到你有权限访问且与问题相关的资料。请换一个更具体的问题，或让管理员确认文档上传、解析和授权状态。"
        else:
            legacy_chat = _main_compat_callable("conversational_answer")
            if callable(legacy_chat):
                try:
                    answer = legacy_chat(question, history, cfg["api_key"], cfg["base_url"], cfg["model"])
                except TypeError:
                    answer = legacy_chat(question, history)
            else:
                answer = conversational_answer(question, history, cfg["api_key"], cfg["base_url"], cfg["model"])
        mode = "chat"
        retrieval_note = retrieval_note or ("no_relevant_knowledge_context" if should_retrieve else "conversation_only_intent")
        answer = append_interaction_footer(answer, suggestions)
    else:
        mode = "knowledge"
        prompt_template_context = select_prompt_templates_for_contexts(db, answer_contexts, table_answer_mode=table_answer_mode)
        retrieval_meta["prompt_template"] = {
            "keys": prompt_template_context.get("keys") or [],
            "labels": prompt_template_context.get("labels") or [],
            "count": prompt_template_context.get("count") or 0,
            "recommended": prompt_template_context.get("recommended") or [],
            "applied_to_answer": not table_answer_mode,
        }
        if table_answer_mode and not table_llm_analysis_mode:
            table_answer_contexts = table_contexts_for_answer(contexts)
            retrieval_meta["table_answer_context_count"] = len(table_answer_contexts)
            answer = build_table_answer(question, table_answer_contexts)
            retrieval_meta["table_structured_result"] = build_table_structured_result(question, table_answer_contexts)
            retrieval_meta["answer_composer"] = "table_local"
        elif table_llm_analysis_mode:
            retrieval_meta["table_llm_analysis"] = True
            table_answer_contexts = table_contexts_for_answer(contexts)
            retrieval_meta["table_answer_context_count"] = len(table_answer_contexts)
            fact_block, table_structured_result = build_table_fact_block(question, table_answer_contexts)
            retrieval_meta["table_structured_result"] = table_structured_result
            structured_digest = merge_table_fact_block(structured_digest, fact_block)
            answer = _call_knowledge_answer(question, answer_contexts, cfg["api_key"], cfg["base_url"], cfg["model"], history=history, structured_digest=structured_digest, prompt_instructions=prompt_template_context.get("instructions") or "")
            retrieval_meta["answer_composer"] = "table_llm_with_structured_digest"
        elif should_use_fast_extractive_answer(question, answer_contexts, retrieval_meta, summary_mode=summary_mode, table_answer_mode=table_answer_mode):
            answer = extractive_fallback_answer(question, answer_contexts, "large_context_fast_path")
            retrieval_meta["answer_composer"] = "extractive_fast_path"
        else:
            answer = _call_knowledge_answer(question, answer_contexts, cfg["api_key"], cfg["base_url"], cfg["model"], history=history, structured_digest=structured_digest, prompt_instructions=prompt_template_context.get("instructions") or "")
            retrieval_meta["answer_composer"] = "llm_grounded"
            if confidence < LOW_CONFIDENCE_THRESHOLD and not summary_mode and not recent_context_used:
                answer = "未在知识库中找到充分依据：以下仅根据检索到的知识库片段生成，请结合引用片段核验。\n\n" + answer
        answer = append_interaction_footer(answer, suggestions)
    answer = strip_inline_source_markers(answer)
    session_id = req.session_id or new_id()
    if not req.session_id:
        db.add(ChatSession(id=session_id, user_id=user.id))
        db.flush()
    user_message_id = new_id()
    assistant_message_id = new_id()
    message_created_at = datetime.utcnow()
    db.add(ChatMessage(id=user_message_id, session_id=session_id, role="user", content=question, created_at=message_created_at))
    db.add(ChatMessage(id=assistant_message_id, session_id=session_id, role="assistant", content=answer, sources_json=json.dumps(sources, ensure_ascii=False), mode=mode, created_at=message_created_at + timedelta(milliseconds=1)))
    audit(db, user, "chat.ask", "chat_session", session_id, {"retrieval_backend": retrieval_backend, "candidate_sources": candidate_count, "sources": len(sources), "grounded": grounded, "confidence": confidence, "summary_mode": summary_mode, "recent_context_used": recent_context_used, "interaction_meta": interaction_meta, "retrieval_meta": retrieval_meta})
    db.commit()
    return {
        "session_id": session_id,
        "message_id": assistant_message_id,
        "assistant_message_id": assistant_message_id,
        "user_message_id": user_message_id,
        "answer": answer,
        "retrieval_backend": retrieval_backend,
        "retrieval_note": retrieval_note,
        "sources": sources,
        "citations": sources,
        "source_count": len(sources),
        "source_quality_notice": source_quality_notice,
        "source_warning": source_quality_notice.get("warning") or "",
        "source_warnings": [source_quality_notice.get("warning")] if source_quality_notice.get("warning") else [],
        "prompt_template": retrieval_meta.get("prompt_template") or {},
        "document_count": int(interaction_meta.get("document_count") or len(sources) or 0),
        "citation_mode": "accessible_documents" if summary_mode else "matched_chunks",
        "grounded": grounded,
        "confidence": confidence,
        "grounding_confidence": confidence,
        "grounding_reason": grounding_reason,
        "mode": mode,
        "no_sources": len(sources) == 0,
        "suggestions": suggestions,
        "followups": suggestions,
        "summary_mode": summary_mode,
        "recent_context_used": recent_context_used,
        "interaction_meta": interaction_meta,
        "retrieval_meta": retrieval_meta,
    }


def _sse_event(event: str, data: dict | str) -> str:
    # Always JSON-encode payloads. This keeps newlines in streamed text safe for SSE parsers.
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/api/chat/stream")
def chat_stream(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(require_user)):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入问题")
    if req.session_id:
        existing = db.get(ChatSession, req.session_id)
        if not existing or existing.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")

    def generate():
        # StreamingResponse 会在依赖 db 关闭后才开始迭代；生成器内必须使用自己的会话，
        # 避免访问 user.groups 等懒加载关系时出现 DetachedInstanceError 并导致 SSE 断流。
        stream_db = SessionLocal()
        try:
            stream_user = stream_db.get(User, user.id)
            if not stream_user or not getattr(stream_user, "is_active", True):
                error_meta = {"stream": True, "error": True, "message": "登录已失效，请重新登录"}
                yield _sse_event("status", {"stage": "error", "message": error_meta["message"]})
                yield _sse_event("done", error_meta)
                return

            # 先判断意图，再决定是否检索；明确寒暄走对话，模糊问题交给模型做轻量分类。
            limit = max(1, min(req.top_k, 10))
            cfg = get_model_config(stream_db)
            history = recent_chat_history(stream_db, req.session_id, stream_user) if req.session_id else []
            route = decide_chat_route(question, history, cfg)
            summary_mode = bool(route.get("summary_mode"))
            followup_mode = bool(route.get("followup_mode"))
            should_retrieve = bool(route.get("should_retrieve"))
            conversation_only = not should_retrieve
            recent_context_used = False
            interaction_meta: dict = {}
            retrieval_meta: dict = {"route": route, "intent": route.get("intent"), "classifier_source": route.get("source"), "classifier_reason": route.get("reason")}
            if summary_mode:
                yield _sse_event("status", {"stage": "retrieving", "message": "正在读取你有权限访问的全部可读文档。"})
                contexts, interaction_meta = accessible_document_summary_contexts(stream_db, stream_user, per_doc_chunks=None, max_docs=None)
                retrieval_backend = "accessible_documents"
                retrieval_note = "summary_intent_all_accessible_documents"
                candidate_count = int(interaction_meta.get("document_count") or len(contexts))
                retrieval_meta.update({"mode": "summary", "final_context_count": len(contexts), "candidate_count": candidate_count})
            elif not should_retrieve:
                yield _sse_event("status", {"stage": "generating", "message": "正在回复。"})
                contexts = []
                retrieval_backend = "none"
                retrieval_note = "conversation_only_intent"
                candidate_count = 0
                retrieval_meta.update({"mode": "chat", "final_context_count": 0, "candidate_count": 0})
            else:
                yield _sse_event("status", {"stage": "retrieving", "message": "正在检索知识库并组织回答。"})
                contexts, retrieval_backend, retrieval_note, candidate_count, retrieved_meta = retrieve_contexts(stream_db, question, stream_user, limit, knowledge_scope=req.knowledge_scope)
                retrieval_meta.update(retrieved_meta or {})
                if followup_mode:
                    followup_limit = max(int(retrieval_meta.get("target_contexts") or limit), 6)
                    recent_contexts = recent_source_contexts(stream_db, req.session_id, stream_user, limit=followup_limit)
                    if recent_contexts:
                        seen = {(c.get("document_id") or "", c.get("chunk_id") or str(c.get("chunk_index") or "")) for c in recent_contexts}
                        contexts = recent_contexts + [
                            c for c in contexts
                            if (c.get("document_id") or "", c.get("chunk_id") or str(c.get("chunk_index") or "")) not in seen
                        ]
                        contexts = contexts[: followup_limit]
                        retrieval_meta["recent_contexts_merged"] = len(recent_contexts)
                        retrieval_meta["final_context_count"] = len(contexts)
                        recent_context_used = True
                if recent_context_used:
                    retrieval_note = f"{retrieval_note}; recent_context_used" if retrieval_note else "recent_context_used"
                elif contexts and retrieval_backend != "qdrant":
                    retrieval_note = retrieval_note or "recent_context_or_sqlite"

            sources = summary_display_sources(contexts, interaction_meta, summary_mode)
            source_quality_notice = build_source_quality_notice(sources)
            answer_contexts = model_contexts_for_answer(contexts, summary_mode)
            retrieval_meta["answer_context_count"] = len(answer_contexts)
            retrieval_meta["answer_context_filtered_count"] = max(0, len(contexts) - len(answer_contexts))
            confidence = compute_grounding_confidence(answer_contexts)
            if summary_mode and answer_contexts:
                confidence = max(confidence, 0.72)
            if recent_context_used and answer_contexts:
                confidence = max(confidence, 0.62)
            grounded = bool(answer_contexts)
            grounding_reason = grounding_reason_for_contexts(answer_contexts, confidence)
            table_answer_mode = retrieval_meta.get("retrieval_route", {}).get("name") == "table"
            table_llm_analysis_mode = table_answer_mode and should_use_table_llm_analysis(question)
            suggestions = [] if conversation_only else build_interaction_suggestions(question, answer_contexts, summary_mode=summary_mode)
            digest_contexts = digest_contexts_for_answer(contexts, answer_contexts, table_answer_mode=table_answer_mode)
            retrieval_meta["structured_digest_context_count"] = len(digest_contexts)
            structured_digest = build_structured_digest(question, digest_contexts, summary_mode) if should_use_structured_digest(question, digest_contexts, summary_mode) else ""
            no_answer_evidence = bool(should_retrieve and contexts and not summary_mode and not answer_contexts)
            if no_answer_evidence:
                retrieval_note = f"{retrieval_note}; answer_evidence_filtered" if retrieval_note else "answer_evidence_filtered"
            mode = "knowledge" if contexts and not no_answer_evidence else "chat"
            if not contexts:
                retrieval_note = retrieval_note or ("no_relevant_knowledge_context" if should_retrieve else "conversation_only_intent")
            session_id = req.session_id or new_id()
            user_message_id = new_id()
            assistant_message_id = new_id()
            meta = {
                "session_id": session_id,
                "message_id": assistant_message_id,
                "assistant_message_id": assistant_message_id,
                "user_message_id": user_message_id,
                "retrieval_backend": retrieval_backend if contexts else "none",
                "retrieval_note": retrieval_note if contexts else "",
                "sources": sources,
                "citations": sources,
                "source_count": len(sources),
                "source_quality_notice": source_quality_notice,
                "source_warning": source_quality_notice.get("warning") or "",
                "source_warnings": [source_quality_notice.get("warning")] if source_quality_notice.get("warning") else [],
                "document_count": int(interaction_meta.get("document_count") or len(sources) or 0),
                "citation_mode": "accessible_documents" if summary_mode else "matched_chunks",
                "grounded": grounded,
                "confidence": confidence,
                "grounding_confidence": confidence,
                "grounding_reason": grounding_reason,
                "mode": mode,
                "no_sources": len(sources) == 0,
                "suggestions": suggestions,
                "followups": suggestions,
                "summary_mode": summary_mode,
                "recent_context_used": recent_context_used,
                "interaction_meta": interaction_meta,
                "retrieval_meta": retrieval_meta,
                "stream": True,
            }
            yield _sse_event("meta", meta)
            if contexts and not no_answer_evidence:
                yield _sse_event("status", {
                    "stage": "generating",
                    "message": f"已整理 {len(sources)} 个来源，正在调用模型生成回答…",
                    "context_count": len(answer_contexts),
                    "source_count": len(sources),
                })

            answer_parts: list[str] = []
            if not contexts or no_answer_evidence:
                retrieval_note = retrieval_note or ("no_relevant_knowledge_context" if should_retrieve else "conversation_only_intent")
                if should_retrieve:
                    if no_answer_evidence:
                        answer_text = "未在知识库中找到充分依据：虽然检索到了一些候选片段，但没有达到可用于回答的证据门槛。请换一个更具体的问题，或让管理员检查文档解析、授权和检索配置。"
                    else:
                        answer_text = "未在知识库中找到依据：当前没有检索到你有权限访问且与问题相关的资料。请换一个更具体的问题，或让管理员确认文档上传、解析和授权状态。"
                    for piece in [answer_text[i : i + 24] for i in range(0, len(answer_text), 24)]:
                        answer_parts.append(piece)
                        yield _sse_event("delta", piece)
                else:
                    for piece in stream_conversational_answer(question, history, cfg["api_key"], cfg["base_url"], cfg["model"]):
                        answer_parts.append(piece)
                        yield _sse_event("delta", piece)
                mode = "chat"
                if suggestions:
                    footer = "\n\n你可以继续问：\n" + "\n".join(f"- {item}" for item in suggestions[:3])
                    answer_parts.append(footer)
                    yield _sse_event("delta", footer)
            else:
                prefix = ""
                prompt_template_context = select_prompt_templates_for_contexts(stream_db, answer_contexts, table_answer_mode=table_answer_mode)
                retrieval_meta["prompt_template"] = {
                    "keys": prompt_template_context.get("keys") or [],
                    "labels": prompt_template_context.get("labels") or [],
                    "count": prompt_template_context.get("count") or 0,
                    "recommended": prompt_template_context.get("recommended") or [],
                    "applied_to_answer": not table_answer_mode,
                }
                meta["prompt_template"] = retrieval_meta["prompt_template"]
                if confidence < LOW_CONFIDENCE_THRESHOLD and not summary_mode and not recent_context_used and not table_answer_mode:
                    prefix = "未在知识库中找到充分依据：以下仅根据检索到的知识库片段生成，请结合引用片段核验。\n\n"
                    answer_parts.append(prefix)
                    yield _sse_event("delta", prefix)
                if table_answer_mode and not table_llm_analysis_mode:
                    table_answer_contexts = table_contexts_for_answer(contexts)
                    retrieval_meta["table_answer_context_count"] = len(table_answer_contexts)
                    answer_text = build_table_answer(question, table_answer_contexts)
                    retrieval_meta["table_structured_result"] = build_table_structured_result(question, table_answer_contexts)
                    retrieval_meta["answer_composer"] = "table_local"
                    for piece in [answer_text[i : i + 24] for i in range(0, len(answer_text), 24)]:
                        answer_parts.append(piece)
                        yield _sse_event("delta", piece)
                elif table_llm_analysis_mode:
                    retrieval_meta["table_llm_analysis"] = True
                    retrieval_meta["answer_composer"] = "table_llm_with_structured_digest"
                    table_answer_contexts = table_contexts_for_answer(contexts)
                    retrieval_meta["table_answer_context_count"] = len(table_answer_contexts)
                    fact_block, table_structured_result = build_table_fact_block(question, table_answer_contexts)
                    retrieval_meta["table_structured_result"] = table_structured_result
                    structured_digest = merge_table_fact_block(structured_digest, fact_block)
                    for piece in stream_chat_answer_v2(question, answer_contexts, cfg["api_key"], cfg["base_url"], cfg["model"], history=history, structured_digest=structured_digest, prompt_instructions=prompt_template_context.get("instructions") or ""):
                        answer_parts.append(piece)
                        yield _sse_event("delta", piece)
                elif should_use_fast_extractive_answer(question, answer_contexts, retrieval_meta, summary_mode=summary_mode, table_answer_mode=table_answer_mode):
                    retrieval_meta["answer_composer"] = "extractive_fast_path"
                    answer_text = extractive_fallback_answer(question, answer_contexts, "large_context_fast_path")
                    for piece in [answer_text[i : i + 80] for i in range(0, len(answer_text), 80)]:
                        answer_parts.append(piece)
                        yield _sse_event("delta", piece)
                else:
                    retrieval_meta["answer_composer"] = "llm_grounded"
                    legacy_answer = _main_compat_callable("chat_answer")
                    if callable(legacy_answer) and not _is_default_ai_client_callable(legacy_answer, "chat_answer"):
                        try:
                            answer_text = legacy_answer(question, answer_contexts, cfg["api_key"], cfg["base_url"], cfg["model"], history=history)
                        except TypeError:
                            answer_text = legacy_answer(question, answer_contexts, cfg["api_key"], cfg["base_url"], cfg["model"])
                        for piece in [answer_text[i : i + 24] for i in range(0, len(answer_text), 24)]:
                            answer_parts.append(piece)
                            yield _sse_event("delta", piece)
                    else:
                        for piece in stream_chat_answer_v2(question, answer_contexts, cfg["api_key"], cfg["base_url"], cfg["model"], history=history, structured_digest=structured_digest, prompt_instructions=prompt_template_context.get("instructions") or ""):
                            answer_parts.append(piece)
                            yield _sse_event("delta", piece)
                footer = ""
                if suggestions:
                    footer = "\n\n你可以继续问：\n" + "\n".join(f"- {item}" for item in suggestions[:3])
                    answer_parts.append(footer)
                    yield _sse_event("delta", footer)

            answer = strip_inline_source_markers("".join(answer_parts))
            if not req.session_id:
                stream_db.add(ChatSession(id=session_id, user_id=stream_user.id))
            message_created_at = datetime.utcnow()
            stream_db.add(ChatMessage(id=user_message_id, session_id=session_id, role="user", content=question, created_at=message_created_at))
            stream_db.add(ChatMessage(id=assistant_message_id, session_id=session_id, role="assistant", content=answer, sources_json=json.dumps(sources, ensure_ascii=False), mode=mode, created_at=message_created_at + timedelta(milliseconds=1)))
            audit(stream_db, stream_user, "chat.ask", "chat_session", session_id, {"retrieval_backend": meta["retrieval_backend"], "candidate_sources": candidate_count if contexts else 0, "sources": len(sources), "grounded": grounded, "confidence": confidence, "summary_mode": summary_mode, "recent_context_used": recent_context_used, "stream": True, "interaction_meta": interaction_meta})
            stream_db.commit()
            meta["answer"] = answer
            meta["mode"] = mode
            meta["retrieval_backend"] = retrieval_backend if mode == "knowledge" and contexts else "none"
            meta["retrieval_note"] = retrieval_note if mode == "knowledge" and contexts else retrieval_note
            yield _sse_event("done", meta)
        except Exception as exc:
            stream_db.rollback()
            traceback.print_exc()
            # 安全：不向客户端泄露异常细节，仅记录到服务端日志
            error_meta = {
                "stream": True,
                "error": True,
                "summary_mode": is_accessible_summary_request(question),
                "message": "生成回答时发生错误，请稍后重试。",
            }
            yield _sse_event("status", {"stage": "error", "message": error_meta["message"]})
            yield _sse_event("done", error_meta)
        finally:
            stream_db.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/admin/search-test")
def search_test(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    question = req.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入测试问题")
    contexts, retrieval_backend, retrieval_note, candidate_count, retrieval_meta = retrieve_contexts(db, question, user, req.top_k, knowledge_scope=req.knowledge_scope)
    sources = serialize_sources(contexts)
    source_quality_notice = build_source_quality_notice(sources)
    answer_contexts = model_contexts_for_answer(contexts, False)
    retrieval_meta["answer_context_count"] = len(answer_contexts)
    retrieval_meta["answer_context_filtered_count"] = max(0, len(contexts) - len(answer_contexts))
    table_answer_mode = retrieval_meta.get("retrieval_route", {}).get("name") == "table"
    prompt_template_context = select_prompt_templates_for_contexts(db, answer_contexts, table_answer_mode=table_answer_mode)
    retrieval_meta["prompt_template"] = {
        "keys": prompt_template_context.get("keys") or [],
        "labels": prompt_template_context.get("labels") or [],
        "count": prompt_template_context.get("count") or 0,
        "recommended": prompt_template_context.get("recommended") or [],
        "applied_to_answer": not table_answer_mode,
    }
    confidence = compute_grounding_confidence(answer_contexts)
    prompt_context_preview = build_prompt_context_preview(answer_contexts)
    retrieval_debug_summary = build_retrieval_debug_summary(answer_contexts, candidate_count, confidence, source_quality_notice)
    if table_answer_mode:
        table_answer_contexts = table_contexts_for_answer(contexts)
        retrieval_meta["table_answer_context_count"] = len(table_answer_contexts)
        retrieval_meta["table_structured_result"] = build_table_structured_result(question, table_answer_contexts)
    source_diagnostics = []
    for index, context in enumerate(contexts, start=1):
        content = " ".join(str(context.get("content") or "").split())
        source_diagnostics.append({
            "rank": index,
            "document_id": context.get("document_id") or "",
            "document_title": context.get("document_title") or context.get("filename") or "未知文档",
            "filename": context.get("filename") or "",
            "page_number": context.get("page_number"),
            "chunk_id": context.get("chunk_id") or "",
            "chunk_index": context.get("chunk_index"),
            "source_type": context.get("source_type") or "document",
            "knowledge_scope": context.get("knowledge_scope") or retrieval_meta.get("knowledge_scope") or "production",
            "document_kind": context.get("document_kind") or "general",
            "score": context.get("score"),
            "rerank_score": context.get("rerank_score"),
            "llm_rerank_score": context.get("llm_rerank_score"),
            "llm_rerank_reason": context.get("llm_rerank_reason") or "",
            "source_quality": context.get("source_quality") or {},
            "quality_penalty": context.get("quality_penalty") or 0,
            "match_reason": context.get("match_reason") or "",
            "match_terms": context.get("match_terms") or [],
            "pageindex_source": bool(context.get("pageindex_source")),
            "retrieval_channel": context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"),
            "location": context.get("location") or "",
            "content_length": len(content),
            "preview": content[:1000],
            "full_content": content,
        })
    return {
        "question": question,
        "retrieval_backend": retrieval_backend,
        "retrieval_note": retrieval_note,
        "candidate_count": candidate_count,
        "confidence": confidence,
        "sources": sources,
        "source_diagnostics": source_diagnostics,
        "source_count": len(sources),
        "prompt_context_preview": prompt_context_preview,
        "retrieval_debug_summary": retrieval_debug_summary,
        "source_quality_notice": source_quality_notice,
        "source_warning": source_quality_notice.get("warning") or "",
        "source_warnings": [source_quality_notice.get("warning")] if source_quality_notice.get("warning") else [],
        "prompt_template": retrieval_meta.get("prompt_template") or {},
        "query_analysis": retrieval_meta.get("query_analysis") or {},
        "retrieval_route": retrieval_meta.get("retrieval_route") or {},
        "evidence_check": retrieval_meta.get("evidence_check") or {},
        "retrieval_meta": retrieval_meta,
    }


@router.post("/api/chat/feedback")
def submit_feedback(req: FeedbackCreate, db: Session = Depends(get_db), user: User = Depends(require_user)):
    content = (req.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="请输入反馈内容")
    if len(content) > 2000:
        raise HTTPException(status_code=400, detail="反馈内容不能超过 2000 字")
    rating = (req.rating or "").strip().lower()
    allowed_ratings = {"", "helpful", "unhelpful", "wrong", "unsafe", "other", "user_feedback"}
    if len(rating) > 30 or rating not in allowed_ratings:
        raise HTTPException(status_code=400, detail="反馈类型只能是 helpful/unhelpful/wrong/unsafe/other/user_feedback")
    category = ((req.category or req.feedback_category or "other") or "other").strip().lower()
    if category not in FEEDBACK_CATEGORIES:
        category = "other"
    session = None
    if req.session_id:
        session = db.get(ChatSession, req.session_id)
        if not session or session.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
    message = None
    if req.message_id:
        message = db.get(ChatMessage, req.message_id)
        if not message or message.role != "assistant":
            raise HTTPException(status_code=404, detail="要反馈的回答不存在")
        msg_session = db.get(ChatSession, message.session_id)
        if not msg_session or msg_session.user_id != user.id:
            raise HTTPException(status_code=404, detail="要反馈的回答不存在")
        if session and message.session_id != session.id:
            raise HTTPException(status_code=400, detail="反馈消息不属于当前会话")
        session = msg_session
    question_snapshot = ""
    answer_snapshot = message.content if message else ""
    sources = parse_json_list(getattr(message, "sources_json", "[]")) if message else []
    if session:
        previous_messages = db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
        ).scalars().all()
        if message:
            before = [m for m in previous_messages if m.created_at <= message.created_at]
            question_snapshot = next((m.content for m in reversed(before) if m.role == "user"), "")
        else:
            question_snapshot = next((m.content for m in reversed(previous_messages) if m.role == "user"), "")
            answer_snapshot = next((m.content for m in reversed(previous_messages) if m.role == "assistant"), "")
            last_assistant = next((m for m in reversed(previous_messages) if m.role == "assistant"), None)
            sources = parse_json_list(getattr(last_assistant, "sources_json", "[]")) if last_assistant else []
    item = Feedback(
        id=new_id(),
        user_id=user.id,
        username=user.username,
        session_id=session.id if session else None,
        message_id=message.id if message else None,
        rating=rating,
        category=category,
        content=content,
        question_snapshot=question_snapshot[:4000],
        answer_snapshot=answer_snapshot[:8000],
        sources_json=json.dumps(sources, ensure_ascii=False),
    )
    db.add(item)
    audit(db, user, "feedback.submit", "feedback", item.id, {"session_id": item.session_id, "message_id": item.message_id, "rating": item.rating, "category": item.category})
    db.commit()
    return {"ok": True, "id": item.id, "status": item.status, "category": item.category, "message": "反馈已提交给管理员"}
