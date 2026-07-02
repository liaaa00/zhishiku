import json
import re
import unicodedata
from typing import List, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .ai_client import embed_texts
from .document_metadata import (
    allowed_kinds_for_query_topic,
    document_matches_scope,
    enrich_context_metadata,
    filter_contexts_by_allowed_kinds,
    get_document_kind,
    get_document_scope,
    normalize_document_scope,
)
from .grounding import filter_relevant_contexts, relevance_terms
from .models import Document, DocumentChunk, DocumentPageIndex, DocumentProcessingStatus, User, document_group_link
from .pageindex_adapter import load_pageindex_payload
from .settings_service import get_model_config, get_reranker_config
from .table_query import is_table_query
from .table_retrieval import table_mode_contexts
from .vector_store import QdrantUnavailable, search_chunks

SQLITE_SCAN_LIMIT = 3000
ADAPTIVE_CANDIDATE_MAX = 120
ADAPTIVE_CONTEXT_MAX = 40
ADAPTIVE_FINAL_CONTEXT_MAX = 12
ADAPTIVE_FINAL_CONTEXT_MIN = 6
ADAPTIVE_NEIGHBOR_MAX = 18
PAGEINDEX_SUPPLEMENT_MAX = 12
PAGEINDEX_DOC_SCAN_MAX = 50
PAGEINDEX_PAGE_CHAR_LIMIT = 1800
PAGEINDEX_PAGE_NEIGHBOR_WINDOW = 1

# Lightweight Agentic RAG guardrails. This is intentionally bounded: simple
# questions keep the existing one-pass adaptive RAG path, while complex / multi-hop
# questions may trigger at most one rewritten retrieval pass before final rerank.
AGENTIC_MAX_EXTRA_ROUNDS = 1
AGENTIC_REWRITE_QUERY_LIMIT = 1
AGENTIC_EXTRA_CANDIDATE_MAX = 48
AGENTIC_MIN_QUALITY_SCORE = 0.46
AGENTIC_COMPLEX_MARKERS = (
    "分别",
    "同时",
    "对比",
    "比较",
    "差异",
    "区别",
    "如果",
    "失败",
    "异常",
    "无法",
    "收不到",
    "多个",
    "多份",
    "跨库",
    "跨文档",
    "多跳",
    "企业端",
    "员工端",
    "内部",
    "外部",
    "先",
    "再",
    "然后",
    "以及",
    "并且",
)
AGENTIC_REWRITE_EXPANSIONS = (
    ("esign_employee", ("员工", "微助手", "外服云", "短信", "登录", "注册", "入口", "劳动合同", "电子签", "签署")),
    ("esign_internal", ("企业端", "HR", "合同组", "工单", "内部审核", "盖章", "归档", "续签申请")),
    ("exception", ("失败", "异常", "无法登录", "收不到通知", "处理办法", "解决步骤")),
    ("comparison", ("对比", "差异", "适用场景", "处理流程", "注意事项")),
)

BROAD_QUERY_PATTERNS = (
    "总结",
    "归纳",
    "梳理",
    "整理",
    "概括",
    "流程",
    "步骤",
    "制度",
    "规则",
    "规范",
    "清单",
    "表格",
    "所有",
    "全部",
    "完整",
    "详细",
    "哪些",
    "有哪些",
    "怎么",
    "如何",
)
DEEP_QUERY_PATTERNS = (
    "风险",
    "问题",
    "隐患",
    "影响",
    "原因",
    "对比",
    "差异",
    "优缺点",
    "方案",
    "建议",
    "策略",
    "分析",
    "排查",
    "复盘",
    "跨文档",
    "多个文档",
)
PRECISE_QUERY_PATTERNS = (
    "多少",
    "几天",
    "日期",
    "时间",
    "电话",
    "邮箱",
    "编号",
    "金额",
    "比例",
    "谁",
    "是什么",
)

PROCESS_QUERY_TERMS = (
    "流程",
    "步骤",
    "怎么签",
    "如何签",
    "电子签",
    "签署",
    "签劳动合同",
    "签合同",
    "操作指南",
    "办理流程",
)

E_SIGN_QUERY_TERMS = (
    "电子签",
    "电子签署",
    "电子劳动合同",
    "电子合同",
    "签劳动合同",
    "签合同",
)

FORM_CONTEXT_MARKERS = (
    "表格数据",
    "```text",
    "a1:",
    "b1:",
    "c1:",
    "字段",
    "全职员工",
    "入职人员信息表",
    "劳动合同起始日",
    "劳动合同终止日",
)

ESIGN_SUBJECT_MARKERS = ("电子劳动合同", "电子合同", "电子签", "线上签署", "在线签署")
ESIGN_EMPLOYEE_ENTRY_MARKERS = ("员工", "本人", "微助手", "外服云", "员工服务", "短信", "入口", "登录", "注册", "手机")
ESIGN_SIGNING_ACTION_MARKERS = ("点击签署", "点击劳动合同", "签署", "确认签署", "核对", "签署完成")
ESIGN_INTERNAL_WORKFLOW_MARKERS = ("工单", "工单系统", "合同组", "内部审核", "hr发起", "归档", "盖章", "审批流", "续签申请")
ESIGN_STRONG_EMPLOYEE_FLOW_MARKERS = ("微助手", "外服云", "员工服务", "点击签署", "点击劳动合同", "核对", "短信")

PORTAL_QUERY_MARKERS = ("微助手", "外服云", "员工服务", "登录", "注册", "入口", "身份认证", "身份验证", "账号", "密码", "微信", "公众号")
PORTAL_CONTEXT_MARKERS = ("微助手", "外服云", "员工服务", "登录界面", "个人登录", "个人注册", "手机注册", "注册", "登录", "身份认证", "身份验证", "账号", "密码", "微信", "公众号")
WORKORDER_QUERY_MARKERS = ("工单", "工单系统", "合同组", "入职场景", "离职场景", "离职", "离职证明", "离职联系", "劳动合同续签", "线下交付", "交付完成", "自动派", "派出", "报岗", "商保投保", "待遇申报", "业务员")
WORKORDER_CONTEXT_MARKERS = ("工单系统", "工单", "合同组", "场景设定", "入职管理", "离职管理", "离职证明", "离职联系", "劳动合同签订", "入职联系", "劳动合同续签", "线下交付", "交付完成", "自动派", "派出", "报岗", "报岗集约录入", "商保投保", "待遇申报", "业务员", "任务分派")
WORKORDER_SPECIFIC_EVIDENCE_MARKERS = (
    "劳动合同签订", "入职联系", "商保投保", "报岗集约录入", "离职联系", "小程序", "离职证明", "线下交付", "交付完成",
    "待办工单", "信息表单", "材料附件", "回写", "权限登录", "导出办理",
)
EMPLOYEE_ESIGN_CONTEXT_MARKERS = (*ESIGN_SUBJECT_MARKERS, "电子签合同", "点击劳动合同", "点击签署", "签署完成", "实名认证", "支付宝", "下载保存", "短信链接")
FORM_QUERY_MARKERS = ("入职人员信息表", "全职员工", "表格", "字段", "银行帐号", "银行账号", "开户行", "合同字段", "劳动合同起始日", "劳动合同到期日")


def parse_embedding(value: str) -> List[float]:
    return json.loads(value)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb + 1e-8)


def user_group_ids(user: User) -> list[str]:
    return [g.id for g in user.groups]


def has_document_access(db: Session, doc: Document, user: User, group_ids: list[str] | None = None, knowledge_scope: str = "production") -> bool:
    source_type = str(doc.source_type or "")
    if source_type.startswith("chat_"):
        return document_matches_scope(doc, knowledge_scope) and (doc.created_by == user.id or bool(user.is_admin))
    if not document_matches_scope(doc, knowledge_scope):
        return False
    if user.is_admin:
        return True
    resolved_group_ids = group_ids if group_ids is not None else user_group_ids(user)
    if not resolved_group_ids:
        return False
    return bool(
        db.execute(
            select(document_group_link.c.group_id).where(
                document_group_link.c.document_id == doc.id,
                document_group_link.c.group_id.in_(resolved_group_ids),
            )
        ).first()
    )


def accessible_document_ids(db: Session, user: User, group_ids: list[str], knowledge_scope: str = "production") -> set[str]:
    # Personal attachment access is granted only to the owner, and still obeys knowledge_scope isolation.
    scope = normalize_document_scope(knowledge_scope, "production")
    scope_filter = [] if scope == "all" else [Document.knowledge_scope == scope]
    personal_rows = db.execute(select(Document.id).where(Document.source_type.like("chat_%"), Document.created_by == user.id, *scope_filter)).all()
    ids = {row[0] for row in personal_rows}

    if user.is_admin:
        managed_rows = db.execute(select(Document.id).where(~Document.source_type.like("chat_%"), *scope_filter)).all()
        ids.update(row[0] for row in managed_rows)
        return ids

    if group_ids:
        managed_rows = db.execute(
            select(Document.id)
            .join(document_group_link, document_group_link.c.document_id == Document.id)
            .where(~Document.source_type.like("chat_%"), document_group_link.c.group_id.in_(group_ids), *scope_filter)
            .distinct()
        ).all()
        ids.update(row[0] for row in managed_rows)
    return ids


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _context_key(context: dict) -> tuple[str, str]:
    return (
        str(context.get("document_id") or ""),
        str(context.get("chunk_id") or context.get("chunk_index") or ""),
    )


def _is_process_query(question: str) -> bool:
    compact = re.sub(r"\s+", "", (question or "").lower())
    return any(term in compact for term in PROCESS_QUERY_TERMS)


def _is_esign_query(question: str) -> bool:
    compact = re.sub(r"\s+", "", (question or "").lower())
    if any(term in compact for term in E_SIGN_QUERY_TERMS):
        return True
    # 用户常会问“劳动合同签署入口/怎么签”，不一定写“电子签”三个字；
    # 这类问题仍应进入员工端电子签检索意图，而不是泛化成普通合同流程。
    contract_markers = ("劳动合同", "合同")
    signing_entry_markers = ("签署", "签约", "签字", "怎么签", "如何签", "入口", "微助手", "外服云")
    return any(marker in compact for marker in contract_markers) and any(marker in compact for marker in signing_entry_markers)


def _is_form_like_context(context: dict) -> bool:
    source_type = str(context.get("source_type") or "").lower()
    filename = str(context.get("filename") or "").lower()
    title = str(context.get("document_title") or "").lower()
    location = str(context.get("location") or "").lower()
    content = str(context.get("content") or "").lower()
    haystack = " ".join([filename, title, location, content])
    if source_type in {"xlsx", "csv", "chat_xlsx", "chat_csv"}:
        return True
    if filename.endswith((".xlsx", ".xls", ".csv")):
        return True
    return any(marker in haystack for marker in FORM_CONTEXT_MARKERS)


def _filter_process_contexts(question: str, contexts: list[dict]) -> list[dict]:
    """Remove only contexts that are structurally incompatible with process questions.

    The main decision of *which* evidence is best belongs to intent-aware reranking;
    this guard only prevents table rows and obvious internal workflow noise from
    crowding out process answers.
    """
    if not contexts or not _is_process_query(question):
        return contexts
    filtered = [context for context in contexts if not _is_form_like_context(context)]
    if _is_esign_query(question):
        aligned = [context for context in filtered if _is_direct_esign_context(question, context) or _is_esign_support_context(question, context)]
        if aligned:
            pruned = []
            for context in filtered:
                compact_text = re.sub(r"\s+", "", _context_full_text(context))
                if _is_internal_contract_workflow_context(compact_text):
                    continue
                pruned.append(context)
            filtered = pruned or aligned
    return filtered or contexts


def _dedupe_contexts(contexts: list[dict]) -> list[dict]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict] = []
    for context in contexts:
        key = _context_key(context)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(context)
    return deduped


def _context_title_text(context: dict) -> str:
    return " ".join(
        str(context.get(key) or "")
        for key in ("document_title", "filename", "section_title", "anchor", "location")
    )


def _context_full_text(context: dict) -> str:
    return " ".join([_context_title_text(context), str(context.get("content") or "")])


def _normalize_match_text(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    normalized = _normalize_match_text(text)
    return any(_normalize_match_text(marker) in normalized for marker in markers)


def _is_internal_contract_workflow_context(text: str) -> bool:
    if not _contains_any(text, ESIGN_INTERNAL_WORKFLOW_MARKERS):
        return False
    # “员工”一词可能出现在否定说明里（如“不是员工电子签署指南”），不能单独作为放行信号。
    return not _contains_any(text, ESIGN_STRONG_EMPLOYEE_FLOW_MARKERS)


def build_query_profile(question: str) -> dict:
    compact = re.sub(r"\s+", "", (question or "").lower())
    is_process = _is_process_query(question)
    is_esign = _is_esign_query(question)
    internal_intent = _contains_any(compact, ("工单", "合同组", "内部审核", "盖章", "归档", "审批", "hr", "续签申请"))
    employee_intent = _contains_any(compact, ("员工", "本人", "微助手", "外服云", "电子签", "签署", "怎么签", "如何签", "入口"))
    portal_intent = _contains_any(compact, PORTAL_QUERY_MARKERS)
    workorder_intent = _contains_any(compact, WORKORDER_QUERY_MARKERS) or internal_intent
    form_intent = _contains_any(compact, FORM_QUERY_MARKERS)
    if is_esign and internal_intent and not employee_intent:
        actor = "internal"
    elif is_esign:
        actor = "employee"
    else:
        actor = "unknown"

    if form_intent:
        topic = "form_fields"
    elif workorder_intent and not (portal_intent and not internal_intent):
        topic = "workorder"
    elif portal_intent and not workorder_intent:
        topic = "employee_portal"
    elif is_esign and actor == "employee":
        topic = "employee_esign"
    elif is_esign and actor == "internal":
        topic = "workorder"
    else:
        topic = "general"

    return {
        "domain": "labor_contract" if _contains_any(compact, ("劳动合同", "合同", "签署", "签")) else "general",
        "task": "esign_process" if is_esign and is_process else ("process" if is_process else "general"),
        "actor": actor,
        "topic": topic,
        "is_process": is_process,
        "is_esign": is_esign,
    }


def _matched_markers(text: str, markers: tuple[str, ...]) -> list[str]:
    normalized = _normalize_match_text(text)
    return [marker for marker in markers if _normalize_match_text(marker) in normalized]


def score_context_for_query_profile(profile: dict, context: dict) -> dict:
    title_text = _context_title_text(context)
    full_text = _context_full_text(context)
    compact_text = re.sub(r"\s+", "", full_text)
    source_type = str(context.get("source_type") or "").lower()

    positive: list[str] = []
    negative: list[str] = []
    intent_score = 0.0
    conflict_penalty = 0.0
    evidence_score = 0.0
    wrong_source_penalty = 0.0
    topic_penalty = 0.0

    if profile.get("is_process") and _is_form_like_context(context):
        wrong_source_penalty += 0.32
        negative.append("table_like_context")

    internal_hits = _matched_markers(compact_text, ESIGN_INTERNAL_WORKFLOW_MARKERS)
    strong_employee_hits = _matched_markers(compact_text, ESIGN_STRONG_EMPLOYEE_FLOW_MARKERS)
    portal_hits = _matched_markers(compact_text, PORTAL_CONTEXT_MARKERS)
    workorder_hits = _matched_markers(compact_text, WORKORDER_CONTEXT_MARKERS)
    workorder_specific_hits = _matched_markers(compact_text, WORKORDER_SPECIFIC_EVIDENCE_MARKERS)
    employee_esign_hits = _matched_markers(compact_text, EMPLOYEE_ESIGN_CONTEXT_MARKERS)
    form_hits = _matched_markers(compact_text, FORM_QUERY_MARKERS)
    title_portal_hits = _matched_markers(title_text, PORTAL_CONTEXT_MARKERS)
    title_workorder_hits = _matched_markers(title_text, WORKORDER_CONTEXT_MARKERS)
    title_form_hits = _matched_markers(title_text, FORM_QUERY_MARKERS)
    title_esign_hits = _matched_markers(title_text, EMPLOYEE_ESIGN_CONTEXT_MARKERS)

    topic = str(profile.get("topic") or "general")
    if topic == "employee_portal":
        positive.extend((title_portal_hits or portal_hits)[:5])
        if title_portal_hits:
            intent_score += 0.18
        if portal_hits:
            evidence_score += min(0.16, len(portal_hits) * 0.04)
        if workorder_hits and not portal_hits:
            topic_penalty += 0.42
            negative.append("topic_mismatch:workorder")
        if employee_esign_hits and not portal_hits:
            topic_penalty += 0.20
            negative.append("topic_mismatch:employee_esign")
        if _is_form_like_context(context):
            topic_penalty += 0.34
            negative.append("topic_mismatch:form")
    elif topic == "workorder":
        positive.extend((title_workorder_hits or workorder_specific_hits or workorder_hits)[:6])
        if title_workorder_hits:
            intent_score += 0.20
        if workorder_hits:
            evidence_score += min(0.18, len(workorder_hits) * 0.04)
        if workorder_specific_hits:
            intent_score += min(0.18, len(workorder_specific_hits) * 0.04)
            evidence_score += min(0.24, len(workorder_specific_hits) * 0.06)
        if portal_hits and not workorder_hits:
            topic_penalty += 0.36
            negative.append("topic_mismatch:portal")
        if employee_esign_hits and not workorder_hits:
            topic_penalty += 0.34
            negative.append("topic_mismatch:employee_esign")
        if _is_form_like_context(context) and not workorder_hits:
            topic_penalty += 0.34
            negative.append("topic_mismatch:form")
    elif topic == "employee_esign":
        positive.extend((title_esign_hits or employee_esign_hits or portal_hits)[:5])
        if title_esign_hits:
            intent_score += 0.16
        if employee_esign_hits:
            evidence_score += min(0.16, len(employee_esign_hits) * 0.04)
        if workorder_hits and not (employee_esign_hits or portal_hits):
            topic_penalty += 0.42
            negative.append("topic_mismatch:workorder")
        if _is_form_like_context(context):
            topic_penalty += 0.34
            negative.append("topic_mismatch:form")
    elif topic == "form_fields":
        form_like = _is_form_like_context(context)
        weak_form_hits = {"字段", "表格"}
        strong_form_hits = [hit for hit in form_hits if hit not in weak_form_hits]
        has_strong_form_evidence = bool(title_form_hits or strong_form_hits)
        workorder_mismatch_hits = workorder_hits or title_workorder_hits
        employee_esign_mismatch_hits = employee_esign_hits or title_esign_hits
        # “字段/表格”在需求文档里也很常见，只能作为弱命中；不能抵消明显的工单/电子签主题不匹配。
        structural_form_evidence = form_like and not workorder_mismatch_hits and not employee_esign_mismatch_hits
        positive.extend((title_form_hits or strong_form_hits or form_hits)[:5])
        if title_form_hits:
            intent_score += 0.28
        if strong_form_hits:
            evidence_score += min(0.24, len(strong_form_hits) * 0.06)
        elif form_hits:
            evidence_score += 0.04
        if form_like and (has_strong_form_evidence or structural_form_evidence):
            intent_score += 0.14
            evidence_score += 0.20
        if workorder_mismatch_hits and not has_strong_form_evidence:
            topic_penalty += 0.72
            negative.append("topic_mismatch:workorder")
        if employee_esign_mismatch_hits and not has_strong_form_evidence:
            topic_penalty += 0.34
            negative.append("topic_mismatch:employee_esign")

    if profile.get("actor") == "internal":
        negative.extend(strong_employee_hits[:5])
        positive.extend(internal_hits[:5])
        if internal_hits:
            intent_score += 0.28
            evidence_score += min(0.18, len(internal_hits) * 0.04)
        if _contains_any(title_text, ("工单", "工单系统", "合同组")):
            intent_score += 0.22
        if strong_employee_hits and not internal_hits:
            conflict_penalty += 0.28
        if source_type in {"xlsx", "csv", "chat_xlsx", "chat_csv"}:
            wrong_source_penalty += 0.16

    if profile.get("task") == "esign_process":
        subject_hits = _matched_markers(compact_text, ESIGN_SUBJECT_MARKERS)
        entry_hits = _matched_markers(compact_text, ESIGN_EMPLOYEE_ENTRY_MARKERS)
        action_hits = _matched_markers(compact_text, ESIGN_SIGNING_ACTION_MARKERS)
        internal_hits = _matched_markers(compact_text, ESIGN_INTERNAL_WORKFLOW_MARKERS)
        strong_employee_hits = _matched_markers(compact_text, ESIGN_STRONG_EMPLOYEE_FLOW_MARKERS)
        title_hits = _matched_markers(title_text, (*ESIGN_SUBJECT_MARKERS, "点击签署", "点击劳动合同"))

        positive.extend(title_hits[:4])
        positive.extend(subject_hits[:4])
        positive.extend(strong_employee_hits[:4])
        positive.extend(action_hits[:4])
        negative.extend(internal_hits[:5])

        if title_hits:
            intent_score += 0.24
        if subject_hits:
            intent_score += 0.18
            evidence_score += 0.08
        if entry_hits or strong_employee_hits:
            intent_score += 0.18
            evidence_score += 0.12
        if action_hits:
            intent_score += 0.22
            evidence_score += 0.12
        if subject_hits and (entry_hits or strong_employee_hits) and action_hits:
            intent_score += 0.20
            evidence_score += 0.12
        if _is_esign_support_context("电子签 签署 流程 注册 登录 入口", context):
            intent_score += 0.10

        if internal_hits and profile.get("actor") != "internal":
            conflict_penalty += 0.28 + min(0.30, len(internal_hits) * 0.08)
            if not strong_employee_hits and not action_hits:
                conflict_penalty += 0.26
            if _contains_any(title_text, ("工单", "工单系统", "合同组")):
                conflict_penalty += 0.18
        if source_type in {"xlsx", "csv", "chat_xlsx", "chat_csv"}:
            wrong_source_penalty += 0.18

    return {
        "intent_score": round(min(intent_score, 0.85), 4),
        "evidence_score": round(min(evidence_score, 0.36), 4),
        "conflict_penalty": round(min(conflict_penalty, 0.58), 4),
        "wrong_source_penalty": round(min(wrong_source_penalty, 0.42), 4),
        "topic_penalty": round(min(topic_penalty, 0.85), 4),
        "topic": str(profile.get("topic") or "general"),
        "positive_signals": list(dict.fromkeys(positive))[:8],
        "negative_signals": list(dict.fromkeys(negative))[:8],
    }


def _is_direct_esign_context(question: str, context: dict) -> bool:
    title_text = _context_title_text(context)
    full_text = _context_full_text(context)
    compact_full_text = re.sub(r"\s+", "", full_text)

    # 标题/章节/锚点命中仍然是强信号，但不是绑定某一份固定文档。
    title_direct_markers = (*ESIGN_SUBJECT_MARKERS, "点击签署", "点击劳动合同", "签署完成短信")
    if _contains_any(title_text, title_direct_markers):
        return True

    # 新增文档常见情况：标题不规范，但正文包含员工端电子签流程步骤。
    # 要求同时具备电子签主题、员工/入口信号和签署动作，避免只因正文偶然出现“电子签/合同”就放行工单材料。
    if (
        _contains_any(compact_full_text, ESIGN_SUBJECT_MARKERS)
        and _contains_any(compact_full_text, ESIGN_EMPLOYEE_ENTRY_MARKERS)
        and _contains_any(compact_full_text, ESIGN_SIGNING_ACTION_MARKERS)
        and not _is_internal_contract_workflow_context(compact_full_text)
    ):
        return True

    compact_question = re.sub(r"\s+", "", (question or "").lower())
    support_markers = ("微助手", "外服云", "员工服务")
    support_terms = ("电子签", "签署", "流程", "注册", "登录", "入口")
    if _contains_any(title_text, support_markers) and any(term in compact_question for term in support_terms):
        return True
    return False


def _is_esign_support_context(question: str, context: dict) -> bool:
    title_text = _context_title_text(context)
    full_text = _context_full_text(context)
    compact_question = re.sub(r"\s+", "", (question or "").lower())
    compact_full_text = re.sub(r"\s+", "", full_text)
    support_markers = ("微助手", "外服云", "员工服务")
    support_terms = ("电子签", "签署", "流程", "注册", "登录", "入口")
    if not any(term in compact_question for term in support_terms):
        return False
    return _contains_any(title_text, support_markers) or (
        _contains_any(compact_full_text, support_markers)
        and _contains_any(compact_full_text, ("注册", "登录", "入口", "绑定", "验证", "员工服务"))
        and not _is_internal_contract_workflow_context(compact_full_text)
    )


def _document_quality_grade(status: DocumentProcessingStatus | None, chunk_count: int, total_chars: int) -> tuple[str, list[str], float]:
    reasons: list[str] = []
    if status and status.status == "failed":
        reasons.append("processing_failed")
    if chunk_count <= 0:
        reasons.append("no_chunks")
    if total_chars < 80:
        reasons.append("very_low_text")
    if status and status.stage in {"file_missing", "parse_error", "need_ocr"}:
        reasons.append(status.stage)
    if any(reason in reasons for reason in ("processing_failed", "no_chunks", "file_missing", "parse_error", "need_ocr")):
        return "blocked", reasons, 0.45
    if "very_low_text" in reasons:
        return "poor", reasons, 0.18
    return "good", reasons, 0.0


def _quality_signal_by_document(db: Session, document_ids: set[str]) -> dict[str, dict]:
    if not document_ids:
        return {}
    statuses = {
        item.document_id: item
        for item in db.execute(select(DocumentProcessingStatus).where(DocumentProcessingStatus.document_id.in_(document_ids))).scalars().all()
    }
    rows = db.execute(
        select(DocumentChunk.document_id, func.count(DocumentChunk.id), func.coalesce(func.sum(func.length(DocumentChunk.content)), 0))
        .where(DocumentChunk.document_id.in_(document_ids))
        .group_by(DocumentChunk.document_id)
    ).all()
    stats = {str(doc_id): (int(count or 0), int(total or 0)) for doc_id, count, total in rows}
    result: dict[str, dict] = {}
    for doc_id in document_ids:
        chunk_count, total_chars = stats.get(doc_id, (0, 0))
        grade, reasons, penalty = _document_quality_grade(statuses.get(doc_id), chunk_count, total_chars)
        result[doc_id] = {
            "grade": grade,
            "reasons": reasons,
            "penalty": penalty,
            "chunk_count": chunk_count,
            "total_chars": total_chars,
        }
    return result


def _apply_context_quality_signal(context: dict, signal: dict | None) -> dict:
    enriched = dict(context)
    signal = signal or {"grade": "unknown", "reasons": [], "penalty": 0.0, "chunk_count": None, "total_chars": None}
    penalty = _safe_float(signal.get("penalty"), 0.0)
    original_score = _safe_float(enriched.get("score"), 0.0)
    enriched["source_quality"] = {
        "grade": signal.get("grade") or "unknown",
        "reasons": signal.get("reasons") or [],
        "penalty": penalty,
        "chunk_count": signal.get("chunk_count"),
        "total_chars": signal.get("total_chars"),
    }
    if penalty > 0:
        enriched["score"] = round(max(0.0, original_score - penalty), 4)
        enriched["quality_penalty"] = penalty
        reason_text = ",".join(signal.get("reasons") or []) or "low_quality_document"
        enriched["match_reason"] = f"{enriched.get('match_reason') or 'retrieval'}; quality_penalty:{reason_text}"
    return enriched


def apply_document_quality_signals(db: Session, contexts: list[dict]) -> list[dict]:
    doc_ids = {str(context.get("document_id") or "") for context in contexts if context.get("document_id")}
    signals = _quality_signal_by_document(db, doc_ids)
    return [_apply_context_quality_signal(context, signals.get(str(context.get("document_id") or ""))) for context in contexts]


def _chunk_context(doc: Document, chunk: DocumentChunk, score: float = 0.35, match_reason: str = "检索补充片段") -> dict:
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": chunk.id,
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "source_type": str(doc.source_type or ""),
        "knowledge_scope": get_document_scope(doc),
        "document_kind": get_document_kind(doc),
        "content": chunk.content,
        "score": score,
        "match_terms": [],
        "match_reason": match_reason,
    }


def sqlite_search_chunks(db: Session, query_vector: List[float], user: User, group_ids: list[str], limit: int, knowledge_scope: str = "production") -> List[dict]:
    doc_ids = accessible_document_ids(db, user, group_ids, knowledge_scope=knowledge_scope)
    if not doc_ids:
        return []

    rows = db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.document_id.in_(doc_ids))
        .order_by(Document.created_at.desc(), DocumentChunk.chunk_index.asc())
        .limit(SQLITE_SCAN_LIMIT)
    ).all()

    scored: list[dict] = []
    for chunk, doc in rows:
        scored.append(
            {
                "document_id": doc.id,
                "document_title": doc.title,
                "filename": doc.filename,
                "chunk_id": chunk.id,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "source_type": str(doc.source_type or ""),
                "knowledge_scope": get_document_scope(doc),
                "document_kind": get_document_kind(doc),
                "content": chunk.content,
                "score": cosine_similarity(query_vector, parse_embedding(chunk.embedding_json)),
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def keyword_terms_for_query(question: str) -> list[str]:
    text = _normalize_match_text(question).lower().strip()
    terms = set(re.findall(r"[a-z0-9_\-]{2,}", text))
    cjk_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for chunk in cjk_chunks:
        if len(chunk) <= 10:
            terms.add(chunk)
        for size in (2, 3, 4, 5, 6):
            for i in range(max(0, len(chunk) - size + 1)):
                terms.add(chunk[i : i + size])
    return sorted((term for term in terms if len(term) >= 2), key=len, reverse=True)[:80]


def _keyword_score(question_terms: list[str], title_text: str, content_text: str) -> tuple[float, list[str]]:
    if not question_terms:
        return 0.0, []
    title = _normalize_match_text(title_text).lower()
    content = _normalize_match_text(content_text).lower()
    hits: list[str] = []
    score = 0.0
    for term in question_terms:
        in_title = term in title
        in_content = term in content
        if not in_title and not in_content:
            continue
        if term not in hits:
            hits.append(term)
        length_boost = min(len(term), 12) / 12
        score += (0.12 + 0.10 * length_boost) if in_content else 0.0
        score += (0.18 + 0.12 * length_boost) if in_title else 0.0
    coverage = len(hits) / max(len(question_terms), 1)
    score += min(0.22, coverage * 0.35)
    return min(score, 0.96), hits[:12]


def keyword_search_chunks(db: Session, question: str, user: User, group_ids: list[str], limit: int, knowledge_scope: str = "production") -> List[dict]:
    doc_ids = accessible_document_ids(db, user, group_ids, knowledge_scope=knowledge_scope)
    if not doc_ids:
        return []
    terms = keyword_terms_for_query(question)
    if not terms:
        return []

    rows = db.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.document_id.in_(doc_ids))
        .order_by(Document.created_at.desc(), DocumentChunk.chunk_index.asc())
        .limit(SQLITE_SCAN_LIMIT)
    ).all()

    scored: list[dict] = []
    for chunk, doc in rows:
        title_text = " ".join(str(item or "") for item in [doc.title, doc.filename])
        score, hits = _keyword_score(terms, title_text, chunk.content or "")
        if score <= 0:
            continue
        context = _chunk_context(doc, chunk, score=score, match_reason="keyword_recall")
        context["match_terms"] = hits
        context["retrieval_channel"] = "keyword"
        scored.append(context)
    scored.sort(key=lambda x: _safe_float(x.get("score")), reverse=True)
    return scored[: max(1, min(limit, ADAPTIVE_CANDIDATE_MAX))]


def retrieval_plan_for_question(question: str, top_k: int = 5) -> dict:
    text = (question or "").strip()
    compact = re.sub(r"\s+", "", text.lower())
    hint = max(1, min(_safe_int(top_k, 5), ADAPTIVE_CONTEXT_MAX))
    cjk_len = len(re.findall(r"[\u4e00-\u9fff]", compact))
    ascii_terms = re.findall(r"[a-z0-9_]{2,}", compact)
    length_score = len(compact) + len(ascii_terms) * 3
    broad_hits = [item for item in BROAD_QUERY_PATTERNS if item in compact]
    deep_hits = [item for item in DEEP_QUERY_PATTERNS if item in compact]
    precise_hits = [item for item in PRECISE_QUERY_PATTERNS if item in compact]

    if deep_hits or length_score >= 90 or len(broad_hits) >= 2:
        intent = "deep_analysis"
        target_contexts = 24
        min_contexts = 12
        candidate_limit = 96
        adjacent_window = 1
        neighbor_budget = 16
        min_score = 0.12
    elif broad_hits or cjk_len >= 35 or length_score >= 58:
        intent = "broad_business"
        target_contexts = 16
        min_contexts = 8
        candidate_limit = 72
        adjacent_window = 1
        neighbor_budget = 12
        min_score = 0.14
    elif precise_hits and length_score <= 46:
        intent = "precise_lookup"
        target_contexts = 6
        min_contexts = 3
        candidate_limit = 30
        adjacent_window = 1
        neighbor_budget = 6
        min_score = 0.18
    else:
        intent = "balanced"
        target_contexts = 10
        min_contexts = 5
        candidate_limit = 48
        adjacent_window = 1
        neighbor_budget = 8
        min_score = 0.16

    target_contexts = max(target_contexts, hint)
    target_contexts = min(target_contexts, ADAPTIVE_CONTEXT_MAX)
    min_contexts = min(max(min_contexts, min(hint, target_contexts)), target_contexts)
    candidate_limit = min(max(candidate_limit, target_contexts * 3), ADAPTIVE_CANDIDATE_MAX)
    neighbor_budget = min(neighbor_budget, ADAPTIVE_NEIGHBOR_MAX)
    return {
        "mode": "adaptive",
        "intent": intent,
        "top_k_hint": hint,
        "target_contexts": target_contexts,
        "min_contexts": min_contexts,
        "candidate_limit": candidate_limit,
        "adjacent_window": adjacent_window,
        "neighbor_budget": neighbor_budget,
        "min_score": min_score,
        "broad_hits": broad_hits[:6],
        "deep_hits": deep_hits[:6],
        "precise_hits": precise_hits[:6],
    }


def agentic_route_for_question(question: str, plan: dict | None = None) -> dict:
    """Decide whether a question deserves the bounded Agentic RAG path.

    The router is deliberately heuristic and cheap. It does not call an LLM; it only
    decides whether a second retrieval pass is worth the cost.
    """
    text = (question or "").strip()
    compact = re.sub(r"\s+", "", text.lower())
    plan = plan or retrieval_plan_for_question(text)
    reasons: list[str] = []
    complexity = 0.0

    if plan.get("intent") == "deep_analysis":
        complexity += 2.0
        reasons.append("deep_analysis_plan")
    elif plan.get("intent") == "broad_business":
        complexity += 0.8
        reasons.append("broad_business_plan")

    marker_hits = [marker for marker in AGENTIC_COMPLEX_MARKERS if marker.lower() in compact]
    if marker_hits:
        complexity += min(2.4, len(marker_hits) * 0.45)
        reasons.append("complex_markers:" + ",".join(marker_hits[:6]))

    has_employee_side = _contains_any(compact, ("员工", "本人", "微助手", "外服云", "短信", "签署", "入口", "登录"))
    has_internal_side = _contains_any(compact, ("企业端", "hr", "合同组", "工单", "内部", "审核", "盖章", "归档"))
    has_exception = _contains_any(compact, ("失败", "异常", "无法", "收不到", "没收到", "不能", "报错"))
    if has_employee_side and has_internal_side:
        complexity += 1.2
        reasons.append("cross_actor")
    if has_exception:
        complexity += 0.8
        reasons.append("exception_handling")

    cjk_len = len(re.findall(r"[\u4e00-\u9fff]", compact))
    if cjk_len >= 55:
        complexity += 0.8
        reasons.append("long_question")

    enabled = complexity >= 2.0
    return {
        "enabled": bool(enabled),
        "complexity_score": round(complexity, 4),
        "reasons": reasons[:8],
        "max_extra_rounds": AGENTIC_MAX_EXTRA_ROUNDS if enabled else 0,
        "rewrite_query_limit": AGENTIC_REWRITE_QUERY_LIMIT if enabled else 0,
        "strategy": "bounded_rewrite_retrieve_rerank" if enabled else "single_pass_rag",
    }


def rewrite_query_for_agentic(question: str, route: dict | None = None) -> list[str]:
    """Build bounded rewrite queries for a complex question.

    This is a deterministic rewrite, not an LLM rewrite. It appends likely domain
    terms so the second pass can recall adjacent evidence without changing the
    user's original intent.
    """
    text = (question or "").strip()
    if not text:
        return []
    route = route or agentic_route_for_question(text)
    if not route.get("enabled"):
        return []

    compact = re.sub(r"\s+", "", text.lower())
    expansions: list[str] = []

    def add_terms(terms: tuple[str, ...]) -> None:
        for term in terms:
            if term and term not in expansions:
                expansions.append(term)

    if _is_esign_query(text) or _contains_any(compact, ("劳动合同", "合同", "电子签", "签署", "微助手", "外服云")):
        add_terms(dict(AGENTIC_REWRITE_EXPANSIONS)["esign_employee"])
    if _contains_any(compact, ("企业端", "hr", "合同组", "工单", "内部", "审核", "盖章", "归档", "续签")):
        add_terms(dict(AGENTIC_REWRITE_EXPANSIONS)["esign_internal"])
    if _contains_any(compact, ("失败", "异常", "无法", "收不到", "没收到", "报错", "不能")):
        add_terms(dict(AGENTIC_REWRITE_EXPANSIONS)["exception"])
    if _contains_any(compact, ("对比", "比较", "差异", "区别", "分别")):
        add_terms(dict(AGENTIC_REWRITE_EXPANSIONS)["comparison"])
    if not expansions:
        add_terms(("流程", "规则", "处理办法", "注意事项"))

    # Keep the original question first and only add missing terms. This prevents a
    # rewrite from drifting away from the user's actual question.
    missing_terms = [term for term in expansions if term.lower() not in compact]
    rewritten = " ".join([text, *missing_terms[:18]]).strip()
    if rewritten == text:
        return []
    return [rewritten[:360]][: int(route.get("rewrite_query_limit") or AGENTIC_REWRITE_QUERY_LIMIT)]


def evaluate_agentic_evidence(question: str, contexts: list[dict], plan: dict | None = None) -> dict:
    """Score whether retrieved evidence is good enough to stop.

    The score mixes lexical coverage, rerank/source scores and document diversity.
    It is not exposed as answer confidence; it only controls whether to spend an
    extra retrieval pass.
    """
    if not contexts:
        return {
            "enough": False,
            "quality_score": 0.0,
            "reason": "no_contexts",
            "context_count": 0,
            "unique_document_count": 0,
            "top_score": 0.0,
            "lexical_coverage": 0.0,
        }

    plan = plan or retrieval_plan_for_question(question)
    top_contexts = contexts[: min(6, len(contexts))]
    question_terms = relevance_terms(question)
    evidence_text = " ".join(_context_full_text(context) for context in top_contexts)
    evidence_terms = relevance_terms(evidence_text)
    overlap = question_terms.intersection(evidence_terms) if question_terms and evidence_terms else set()
    lexical_coverage = len(overlap) / max(len(question_terms), 1)

    scores = [
        max(
            _safe_float(context.get("llm_rerank_score"), 0.0),
            _safe_float(context.get("rerank_score"), 0.0),
            _safe_float(context.get("profile_score"), 0.0),
            _safe_float(context.get("score"), 0.0),
        )
        for context in top_contexts
    ]
    top_score = max(scores or [0.0])
    avg_top3 = sum(scores[:3]) / max(len(scores[:3]), 1)
    unique_docs = {str(context.get("document_id") or "") for context in top_contexts if context.get("document_id")}
    diversity = min(len(unique_docs), 3) / 3
    quality = min(1.0, top_score * 0.45 + avg_top3 * 0.25 + min(lexical_coverage, 0.45) * 0.45 + diversity * 0.12)

    threshold = AGENTIC_MIN_QUALITY_SCORE
    if plan.get("intent") == "precise_lookup":
        threshold = 0.42
    elif plan.get("intent") == "deep_analysis":
        threshold = 0.52
    enough = quality >= threshold and len(top_contexts) >= min(3, max(1, int(plan.get("min_contexts") or 3) // 2))
    reason = "enough" if enough else "low_quality_or_sparse"
    return {
        "enough": bool(enough),
        "quality_score": round(quality, 4),
        "threshold": round(threshold, 4),
        "reason": reason,
        "context_count": len(contexts),
        "unique_document_count": len(unique_docs),
        "top_score": round(top_score, 4),
        "avg_top3_score": round(avg_top3, 4),
        "lexical_coverage": round(lexical_coverage, 4),
        "matched_terms": sorted(overlap, key=len, reverse=True)[:12],
    }


def retrieve_candidate_contexts(db: Session, question: str, user: User, top_k: int = 5, candidate_limit: int | None = None, knowledge_scope: str = "production") -> Tuple[List[dict], str, str, int]:
    if candidate_limit is None:
        limit = max(1, min(int(top_k or 5), 10))
        candidate_limit = max(limit * 3, limit)
    else:
        candidate_limit = max(1, min(int(candidate_limit or top_k or 5), ADAPTIVE_CANDIDATE_MAX))
    query_vector = embed_texts([question])[0]
    group_ids = user_group_ids(user)
    retrieval_backend = "sqlite"
    retrieval_note = ""
    try:
        candidate_contexts = search_chunks(query_vector, user.id, bool(user.is_admin), group_ids, candidate_limit, knowledge_scope=knowledge_scope)
        retrieval_backend = "qdrant"
        if not candidate_contexts:
            raise QdrantUnavailable("Qdrant returned no matches; falling back to SQLite")
    except QdrantUnavailable as exc:
        retrieval_note = str(exc)
        candidate_contexts = sqlite_search_chunks(db, query_vector, user, group_ids, candidate_limit, knowledge_scope=knowledge_scope)
    return candidate_contexts, retrieval_backend, retrieval_note, len(candidate_contexts)


def _merge_unique_contexts(primary: list[dict], supplement: list[dict], limit: int) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for context in [*primary, *supplement]:
        key = _context_key(context)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        merged.append(context)
        if len(merged) >= limit:
            break
    return merged


def _rerank_context_score(question: str, question_terms: set[str], context: dict, original_rank: int, profile: dict | None = None) -> tuple[float, dict]:
    text = " ".join(
        str(item or "")
        for item in [
            context.get("document_title"),
            context.get("filename"),
            context.get("section_title"),
            context.get("anchor"),
            context.get("match_reason"),
            context.get("content"),
        ]
    )
    terms = relevance_terms(text)
    overlap = question_terms.intersection(terms)
    title_terms = relevance_terms(" ".join(str(context.get(item) or "") for item in ["document_title", "filename", "section_title", "anchor"]))
    title_overlap = question_terms.intersection(title_terms)
    coverage = len(overlap) / max(len(question_terms), 1)
    title_boost = min(0.22, len(title_overlap) * 0.07)
    pageindex_boost = 0.16 if context.get("pageindex_source") else 0.0
    source_score = min(_safe_float(context.get("score"), 0.0), 1.0) * 0.35
    lexical_score = min(0.30, coverage * 0.30)
    rank_penalty = min(0.08, original_rank * 0.004)
    profile_features = score_context_for_query_profile(profile or build_query_profile(question), context)
    quality_penalty = _safe_float(context.get("quality_penalty"), _safe_float((context.get("source_quality") or {}).get("penalty"), 0.0))
    score = (
        source_score
        + lexical_score
        + title_boost
        + pageindex_boost
        + _safe_float(profile_features.get("intent_score"), 0.0)
        + _safe_float(profile_features.get("evidence_score"), 0.0)
        - _safe_float(profile_features.get("conflict_penalty"), 0.0)
        - _safe_float(profile_features.get("wrong_source_penalty"), 0.0)
        - _safe_float(profile_features.get("topic_penalty"), 0.0)
        - quality_penalty
        - rank_penalty
    )
    profile_features.update({
        "lexical_coverage": round(coverage, 4),
        "title_boost": round(title_boost, 4),
        "quality_penalty": round(quality_penalty, 4),
    })
    return score, profile_features


def profile_rank_contexts(question: str, contexts: list[dict], profile: dict | None = None) -> list[dict]:
    if not contexts:
        return []
    profile = profile or build_query_profile(question)
    question_terms = relevance_terms(question)
    scored: list[tuple[float, int, dict]] = []
    for idx, context in enumerate(contexts):
        if question_terms:
            score, features = _rerank_context_score(question, question_terms, context, idx, profile)
        else:
            features = score_context_for_query_profile(profile, context)
            score = _safe_float(context.get("score"), 0.0) + _safe_float(features.get("intent_score"), 0.0) - _safe_float(features.get("conflict_penalty"), 0.0)
        enriched = dict(context)
        enriched["intent_ranking"] = features
        enriched["profile_score"] = round(score, 4)
        scored.append((score, idx, enriched))
    scored.sort(key=lambda item: (item[0], bool(item[2].get("pageindex_source"))), reverse=True)
    return [item[2] for item in scored]


def rerank_contexts(question: str, contexts: list[dict], limit: int, profile: dict | None = None) -> tuple[list[dict], int]:
    if not contexts:
        return [], 0
    limit = max(1, min(int(limit or ADAPTIVE_FINAL_CONTEXT_MAX), ADAPTIVE_CONTEXT_MAX))
    profile = profile or build_query_profile(question)
    question_terms = relevance_terms(question)
    scored: list[tuple[float, int, dict]] = []
    for idx, context in enumerate(contexts):
        if question_terms:
            score, features = _rerank_context_score(question, question_terms, context, idx, profile)
        else:
            features = score_context_for_query_profile(profile, context)
            score = _safe_float(context.get("score"), 0.0) + _safe_float(features.get("intent_score"), 0.0) - _safe_float(features.get("conflict_penalty"), 0.0)
        enriched = dict(context)
        enriched["intent_ranking"] = features
        scored.append((score, idx, enriched))
    scored.sort(key=lambda item: (item[0], bool(item[2].get("pageindex_source"))), reverse=True)

    selected: list[dict] = []
    per_doc_count: dict[str, int] = {}
    seen: set[tuple[str, str]] = set()
    pageindex_selected = 0
    strict_topic = str(profile.get("topic") or "") in {"form_fields", "employee_portal", "employee_esign"}
    # First pass: keep diversity and prefer at most a few contexts from the same document.
    # Do not let very weak topic-mismatch items enter early just to satisfy diversity;
    # they may be used only as last-resort filler below.
    for score, _idx, context in scored:
        key = _context_key(context)
        doc_id = key[0]
        if not doc_id or key in seen:
            continue
        ranking = context.get("intent_ranking") or {}
        if _safe_float(ranking.get("topic_penalty"), 0.0) >= 0.28 and (score < 0.45 or strict_topic):
            continue
        if per_doc_count.get(doc_id, 0) >= 3:
            continue
        context = dict(context)
        context["rerank_score"] = round(score, 4)
        selected.append(context)
        seen.add(key)
        per_doc_count[doc_id] = per_doc_count.get(doc_id, 0) + 1
        if context.get("pageindex_source"):
            pageindex_selected += 1
        if len(selected) >= limit:
            break

    # Second pass: if diversity filtering made the result too small, fill with next best items.
    # For strong topic queries, do not re-introduce severe topic-mismatch noise merely to pad Top-N.
    min_fill = min(ADAPTIVE_FINAL_CONTEXT_MIN, limit)
    enough_strict_evidence = strict_topic and len(selected) >= 3
    if len(selected) < min_fill:
        for score, _idx, context in scored:
            key = _context_key(context)
            if not key[0] or key in seen:
                continue
            ranking = context.get("intent_ranking") or {}
            if enough_strict_evidence and _safe_float(ranking.get("topic_penalty"), 0.0) >= 0.28:
                continue
            context = dict(context)
            context["rerank_score"] = round(score, 4)
            selected.append(context)
            seen.add(key)
            if context.get("pageindex_source"):
                pageindex_selected += 1
            if len(selected) >= min_fill:
                break
    return selected[:limit], pageindex_selected


def _extract_json_object(text: str) -> dict:
    content = (text or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content, flags=re.I).strip()
        content = re.sub(r"\s*```$", "", content).strip()
    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        match = re.search(r"\{.*\}", content, re.S)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}


def llm_rerank_contexts(db: Session, question: str, contexts: list[dict], limit: int) -> tuple[list[dict], dict]:
    """Optionally rerank retrieval candidates with the configured chat model.

    The LLM reranker is intentionally best-effort: if disabled, unconfigured, or failed,
    callers keep the rule-reranked order so Q&A availability is not affected.
    """
    meta = {
        "enabled": False,
        "used": False,
        "model": "",
        "candidate_count": len(contexts),
        "reranked_count": 0,
        "error": "",
    }
    if not contexts:
        return [], meta

    cfg = get_reranker_config(db)
    meta["enabled"] = bool(cfg.get("enabled"))
    if not meta["enabled"]:
        return contexts[:limit], meta

    model_cfg = get_model_config(db)
    api_key = str(model_cfg.get("api_key") or "")
    if not api_key:
        meta["error"] = "未配置聊天模型 API Key"
        return contexts[:limit], meta

    model = str(cfg.get("model") or model_cfg.get("model") or "deepseek-chat")
    meta["model"] = model
    max_candidates = max(4, min(_safe_int(cfg.get("max_candidates"), 24), 60, len(contexts)))
    candidates = contexts[:max_candidates]
    payload = []
    for idx, context in enumerate(candidates, start=1):
        content = " ".join(str(context.get("content") or "").split())[:700]
        payload.append({
            "id": idx,
            "title": context.get("document_title") or context.get("filename") or "未知文档",
            "location": context.get("location") or f"chunk {context.get('chunk_index', '-')}",
            "channel": context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"),
            "score": round(_safe_float(context.get("rerank_score"), _safe_float(context.get("score"))), 4),
            "content": content,
        })

    system = (
        "你是企业内部知识库问答系统的检索精排器，只能输出 JSON。"
        "根据用户问题判断候选片段是否能直接支持回答，优先选择事实相关、字段命中、同义表达相关、上下文完整的片段。"
        "不要因为候选排在前面就盲目保留；也不要编造候选中没有的信息。"
        "输出格式：{\"ranking\":[{\"id\":1,\"score\":0.95,\"reason\":\"...\"}]}，score 为 0 到 1。"
    )
    user_payload = json.dumps({"question": question, "candidates": payload}, ensure_ascii=False)
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key,
            base_url=str(model_cfg.get("base_url") or "https://api.deepseek.com"),
            timeout=45.0,
            max_retries=1,
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user_payload}],
            temperature=0.0,
            max_tokens=900,
        )
        parsed = _extract_json_object(response.choices[0].message.content or "")
        ranking = parsed.get("ranking") if isinstance(parsed, dict) else None
        if not isinstance(ranking, list):
            raise ValueError("reranker 返回格式不是 ranking 数组")

        by_id = {idx: dict(context) for idx, context in enumerate(candidates, start=1)}
        ordered: list[tuple[float, int, dict]] = []
        seen_ids: set[int] = set()
        for item in ranking:
            if not isinstance(item, dict):
                continue
            cid = _safe_int(item.get("id"), 0)
            if cid not in by_id or cid in seen_ids:
                continue
            score = max(0.0, min(_safe_float(item.get("score"), 0.0), 1.0))
            context = by_id[cid]
            context["llm_rerank_score"] = round(score, 4)
            context["llm_rerank_reason"] = str(item.get("reason") or "")[:160]
            ordered.append((score, cid, context))
            seen_ids.add(cid)
        if not ordered:
            raise ValueError("reranker 未返回有效候选")

        ordered.sort(key=lambda item: item[0], reverse=True)
        selected = [item[2] for item in ordered]
        for idx, context in enumerate(candidates, start=1):
            if idx not in seen_ids:
                fallback = dict(context)
                fallback["llm_rerank_score"] = 0.0
                selected.append(fallback)
        meta["used"] = True
        meta["reranked_count"] = len(ordered)
        return selected[:limit], meta
    except Exception as exc:
        meta["error"] = str(exc)[:240]
        return contexts[:limit], meta


def expand_contexts_with_adjacent_chunks(
    db: Session,
    contexts: list[dict],
    user: User,
    group_ids: list[str],
    window: int = 1,
    max_added: int = 8,
    knowledge_scope: str = "production",
) -> tuple[list[dict], int]:
    if not contexts or window <= 0 or max_added <= 0:
        return contexts, 0

    result: list[dict] = []
    seen: set[tuple[str, str]] = set()
    added = 0
    for context in contexts:
        key = _context_key(context)
        if key not in seen:
            result.append(context)
            seen.add(key)
        if added >= max_added:
            continue
        document_id = str(context.get("document_id") or "")
        chunk_index = _safe_int(context.get("chunk_index"), -1)
        if not document_id or chunk_index < 0:
            continue
        indices = [idx for idx in range(chunk_index - window, chunk_index + window + 1) if idx >= 0 and idx != chunk_index]
        if not indices:
            continue
        rows = db.execute(
            select(DocumentChunk, Document)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.document_id == document_id, DocumentChunk.chunk_index.in_(indices))
            .order_by(DocumentChunk.chunk_index.asc())
        ).all()
        base_score = _safe_float(context.get("score"), 0.35)
        for chunk, doc in rows:
            if added >= max_added:
                break
            if not has_document_access(db, doc, user, group_ids, knowledge_scope=knowledge_scope):
                continue
            neighbor_key = (doc.id, chunk.id)
            if neighbor_key in seen:
                continue
            distance = abs(_safe_int(chunk.chunk_index) - chunk_index)
            neighbor_score = max(min(base_score - 0.03 * distance, base_score), 0.1)
            result.append(_chunk_context(doc, chunk, score=neighbor_score, match_reason="相邻片段补全文档上下文"))
            seen.add(neighbor_key)
            added += 1
    return result, added


def _flatten_pageindex_nodes(nodes: list[dict], parent_title: str = "") -> list[dict]:
    flattened: list[dict] = []
    for node in nodes or []:
        title = str(node.get("title") or "").strip()
        section_title = " / ".join(part for part in [parent_title, title] if part)
        item = dict(node)
        item["section_title"] = section_title or title
        flattened.append(item)
        children = node.get("nodes") or []
        if isinstance(children, list) and children:
            flattened.extend(_flatten_pageindex_nodes(children, section_title))
    return flattened


def _pageindex_node_score(question_terms: set[str], node: dict, doc: Document, payload: dict) -> tuple[float, list[str]]:
    # Score a structural node by its own title/content, not by the full
    # breadcrumb. Otherwise every child of a document inherits generic document
    # title terms and specific sections such as “入职管理” can be buried by the
    # root/overview node.
    title = str(node.get("title") or "")
    node_haystack = " ".join(
        str(item or "")
        for item in [
            title,
            node.get("summary") or node.get("prefix_summary"),
            node.get("text"),
        ]
    )
    doc_haystack = " ".join(str(item or "") for item in [doc.title, doc.filename])
    node_terms = relevance_terms(node_haystack)
    doc_terms = relevance_terms(doc_haystack)
    node_overlap = sorted((term for term in question_terms.intersection(node_terms) if len(term) >= 2), key=len, reverse=True)
    doc_overlap = sorted((term for term in question_terms.intersection(doc_terms) if len(term) >= 2), key=len, reverse=True)
    if not node_overlap and not doc_overlap:
        return 0.0, []
    title_terms = relevance_terms(title)
    title_overlap = question_terms.intersection(title_terms)
    node_long_hits = sum(1 for term in node_overlap if len(term) >= 2)
    doc_long_hits = sum(1 for term in doc_overlap if len(term) >= 2)
    score = 0.18 + min(0.56, node_long_hits * 0.08) + min(0.22, len(title_overlap) * 0.07) + min(0.12, doc_long_hits * 0.03)
    return min(score, 0.92), (node_overlap + [term for term in doc_overlap if term not in node_overlap])[:12]


def _pageindex_node_content(payload: dict, node: dict) -> tuple[str, int | None, str]:
    start = _safe_int(node.get("start_index") or node.get("line_num") or node.get("page"), 0)
    end = _safe_int(node.get("end_index") or node.get("start_index") or node.get("line_num") or node.get("page"), start)
    if end < start:
        end = start
    title = str(node.get("section_title") or node.get("title") or "").strip()
    location = f"页/行 {start}-{end}" if start and end and start != end else (f"页/行 {start}" if start else "结构节点")

    content_parts: list[str] = []
    node_summary = str(node.get("summary") or node.get("prefix_summary") or "").strip()
    if node_summary:
        content_parts.append(f"[章节摘要]\n{node_summary}")
    pages = payload.get("pages") or []
    if isinstance(pages, list) and pages:
        page_by_no = {
            _safe_int(page.get("page"), 0): page
            for page in pages
            if isinstance(page, dict) and _safe_int(page.get("page"), 0)
        }
        if start:
            primary_pages = list(range(start, end + 1))
            neighbor_pages: list[int] = []
            for distance in range(1, PAGEINDEX_PAGE_NEIGHBOR_WINDOW + 1):
                if end + distance in page_by_no:
                    neighbor_pages.append(end + distance)
                if start - distance in page_by_no:
                    neighbor_pages.append(start - distance)
            page_numbers = list(dict.fromkeys(primary_pages + neighbor_pages))
        else:
            page_numbers = list(page_by_no.keys())
        for page_no in page_numbers:
            page = page_by_no.get(page_no)
            if not page:
                continue
            text = str(page.get("content") or "")
            if text.strip():
                content_parts.append(f"[第 {page_no} 页]\n{text.strip()}")
            if sum(len(part) for part in content_parts) >= PAGEINDEX_PAGE_CHAR_LIMIT:
                break
    if not content_parts:
        fallback = str(node.get("text") or node.get("summary") or node.get("prefix_summary") or payload.get("doc_description") or "")
        if fallback.strip():
            content_parts.append(fallback.strip())
    content = "\n\n".join(content_parts)
    if len(content) > PAGEINDEX_PAGE_CHAR_LIMIT:
        content = content[:PAGEINDEX_PAGE_CHAR_LIMIT].rstrip() + "..."
    if title:
        content = f"[高级结构索引] {title}（{location}）\n{content}"
    return content.strip(), (start or None), location


def _pageindex_context(doc: Document, node: dict, payload: dict, score: float, match_terms: list[str]) -> dict | None:
    content, page_number, location = _pageindex_node_content(payload, node)
    if not content:
        return None
    node_id = str(node.get("node_id") or node.get("section_title") or node.get("title") or page_number or "node")
    title = str(node.get("section_title") or node.get("title") or "")
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": "",
        "page_number": page_number,
        "chunk_index": f"pageindex:{node_id}",
        "source_type": str(doc.source_type or ""),
        "knowledge_scope": get_document_scope(doc),
        "document_kind": get_document_kind(doc),
        "content": content,
        "score": score,
        "match_terms": match_terms,
        "match_reason": "高级结构索引命中章节/页面",
        "section_title": title,
        "anchor": title,
        "location": f"pageindex | {location}" + (f" | {title}" if title else ""),
        "pageindex_source": True,
    }


def retrieve_pageindex_contexts(
    db: Session,
    question: str,
    user: User,
    group_ids: list[str],
    base_contexts: list[dict] | None = None,
    max_contexts: int = PAGEINDEX_SUPPLEMENT_MAX,
    knowledge_scope: str = "production",
) -> list[dict]:
    question_terms = relevance_terms(question)
    if not question_terms or max_contexts <= 0:
        return []
    accessible_ids = accessible_document_ids(db, user, group_ids, knowledge_scope=knowledge_scope)
    if not accessible_ids:
        return []

    preferred_ids: list[str] = []
    for context in base_contexts or []:
        doc_id = str(context.get("document_id") or "")
        if doc_id and doc_id in accessible_ids and doc_id not in preferred_ids:
            preferred_ids.append(doc_id)

    rows = db.execute(
        select(DocumentPageIndex, Document)
        .join(Document, Document.id == DocumentPageIndex.document_id)
        .where(DocumentPageIndex.status == "ready", DocumentPageIndex.document_id.in_(accessible_ids))
        .order_by(Document.created_at.desc())
        .limit(PAGEINDEX_DOC_SCAN_MAX)
    ).all()
    row_by_doc = {doc.id: (row, doc) for row, doc in rows}
    ordered_pairs: list[tuple[DocumentPageIndex, Document]] = []
    for doc_id in preferred_ids:
        pair = row_by_doc.pop(doc_id, None)
        if pair:
            ordered_pairs.append(pair)
    ordered_pairs.extend(row_by_doc.values())

    scored_contexts: list[dict] = []
    for row, doc in ordered_pairs:
        _, payload = load_pageindex_payload(db, doc.id)
        if not payload:
            continue
        nodes = _flatten_pageindex_nodes(payload.get("structure") or [])
        scored_nodes: list[tuple[float, list[str], dict]] = []
        for node in nodes:
            score, terms = _pageindex_node_score(question_terms, node, doc, payload)
            if score > 0:
                scored_nodes.append((score, terms, node))
        scored_nodes.sort(key=lambda item: item[0], reverse=True)
        if not scored_nodes and doc.id in preferred_ids:
            # If vector retrieval already selected this document, add the first structural node
            # as a lightweight context even when lexical overlap is weak.
            for node in nodes[:1]:
                scored_nodes.append((0.26, [], node))
        for score, terms, node in scored_nodes[:2]:
            context = _pageindex_context(doc, node, payload, score, terms)
            if context:
                scored_contexts.append(context)
    scored_contexts.sort(key=lambda item: _safe_float(item.get("score")), reverse=True)
    return scored_contexts[:max_contexts]


def adaptive_retrieve_contexts(db: Session, question: str, user: User, top_k: int = 5, knowledge_scope: str = "production") -> Tuple[List[dict], str, str, int, dict]:
    # Phase-1 RAG router entrypoint. The original adaptive text retrieval logic is
    # kept below in _adaptive_text_retrieve_contexts and used by the text route.
    from .rag.pipeline import retrieve_contexts

    return retrieve_contexts(db, question, user, top_k=top_k, knowledge_scope=knowledge_scope)


def _adaptive_text_retrieve_contexts(db: Session, question: str, user: User, top_k: int = 5, knowledge_scope: str = "production") -> Tuple[List[dict], str, str, int, dict]:
    plan = retrieval_plan_for_question(question, top_k)
    query_profile = build_query_profile(question)
    candidate_contexts, retrieval_backend, retrieval_note, candidate_count = retrieve_candidate_contexts(
        db,
        question,
        user,
        top_k=top_k,
        candidate_limit=int(plan["candidate_limit"]),
        knowledge_scope=knowledge_scope,
    )
    group_ids = user_group_ids(user)
    keyword_contexts = keyword_search_chunks(db, question, user, group_ids, max(int(plan["candidate_limit"]) // 2, int(plan["target_contexts"])), knowledge_scope=knowledge_scope)
    keyword_candidate_count = len(keyword_contexts)
    if keyword_contexts:
        candidate_contexts = _merge_unique_contexts(candidate_contexts, keyword_contexts, ADAPTIVE_CANDIDATE_MAX)
        if retrieval_backend == "qdrant":
            retrieval_backend = "hybrid"
        elif retrieval_backend == "sqlite":
            retrieval_backend = "sqlite+keyword"
    candidate_contexts = apply_document_quality_signals(db, candidate_contexts)
    filtered = filter_relevant_contexts(candidate_contexts, question, min_score=float(plan["min_score"]))
    filtered = profile_rank_contexts(question, filtered, query_profile)
    candidate_contexts = profile_rank_contexts(question, candidate_contexts, query_profile)

    target_contexts = int(plan["target_contexts"])
    min_contexts = int(plan["min_contexts"])

    agentic_route = agentic_route_for_question(question, plan)
    agentic_initial_quality = evaluate_agentic_evidence(question, filtered[:target_contexts] or candidate_contexts[:target_contexts], plan)
    agentic_rewrites: list[str] = []
    agentic_extra_candidate_count = 0
    agentic_extra_filtered_count = 0
    agentic_notes: list[str] = []
    if agentic_route.get("enabled") and not agentic_initial_quality.get("enough"):
        agentic_rewrites = rewrite_query_for_agentic(question, agentic_route)
        extra_limit = min(
            AGENTIC_EXTRA_CANDIDATE_MAX,
            max(int(plan["target_contexts"]) * 3, int(plan["candidate_limit"]) // 2, 12),
        )
        for rewrite_query in agentic_rewrites[:AGENTIC_REWRITE_QUERY_LIMIT]:
            extra_contexts, extra_backend, extra_note, extra_count = retrieve_candidate_contexts(
                db,
                rewrite_query,
                user,
                top_k=top_k,
                candidate_limit=extra_limit,
                knowledge_scope=knowledge_scope,
            )
            agentic_extra_candidate_count += extra_count
            extra_keywords = keyword_search_chunks(db, rewrite_query, user, group_ids, max(extra_limit // 2, int(plan["target_contexts"])), knowledge_scope=knowledge_scope)
            if extra_keywords:
                extra_contexts = _merge_unique_contexts(extra_contexts, extra_keywords, extra_limit)
            extra_filtered = filter_relevant_contexts(extra_contexts, rewrite_query, min_score=max(0.10, float(plan["min_score"]) - 0.04))
            extra_ranked = profile_rank_contexts(question, extra_filtered or extra_contexts, query_profile)
            tagged_extra: list[dict] = []
            for context in extra_ranked:
                tagged = dict(context)
                tagged["agentic_rewrite_query"] = rewrite_query
                tagged["agentic_retrieval_round"] = 1
                if not tagged.get("retrieval_channel"):
                    tagged["retrieval_channel"] = "agentic_rewrite"
                tagged_extra.append(tagged)
            agentic_extra_filtered_count += len(extra_filtered)
            if tagged_extra:
                candidate_contexts = _merge_unique_contexts(candidate_contexts, tagged_extra, ADAPTIVE_CANDIDATE_MAX)
                if retrieval_backend in ("qdrant", "sqlite", "sqlite+keyword"):
                    retrieval_backend = "hybrid"
            agentic_notes.append(f"rewrite_backend={extra_backend}; extra={extra_count}; filtered={len(extra_filtered)}" + (f"; note={extra_note}" if extra_note else ""))

        if agentic_extra_candidate_count:
            candidate_contexts = apply_document_quality_signals(db, candidate_contexts)
            filtered = filter_relevant_contexts(candidate_contexts, question, min_score=float(plan["min_score"]))
            filtered = profile_rank_contexts(question, filtered, query_profile)
            candidate_contexts = profile_rank_contexts(question, candidate_contexts, query_profile)

    agentic_final_quality = evaluate_agentic_evidence(question, filtered[:target_contexts] or candidate_contexts[:target_contexts], plan)
    best_score = max((_safe_float(item.get("score"), 0.0) for item in filtered), default=max((_safe_float(item.get("score"), 0.0) for item in candidate_contexts), default=0.0))
    final_contexts = filtered[:target_contexts]
    if len(final_contexts) < min_contexts and filtered and best_score >= max(0.18, float(plan["min_score"])):
        # 低命中时不要直接放弃：用候选池中分数最高的片段补足最小上下文，随后仍会由置信度逻辑提示风险。
        final_contexts = _merge_unique_contexts(final_contexts, candidate_contexts, min_contexts)

    expand_allowed = bool(final_contexts) and best_score >= max(0.22, float(plan["min_score"]))
    expanded_contexts, adjacent_added = expand_contexts_with_adjacent_chunks(
        db,
        final_contexts if expand_allowed else [],
        user,
        group_ids,
        window=int(plan["adjacent_window"]),
        max_added=int(plan["neighbor_budget"]),
        knowledge_scope=knowledge_scope,
    ) if expand_allowed else (final_contexts, 0)
    expanded_contexts = _filter_process_contexts(question, expanded_contexts)
    pageindex_base_contexts = _filter_process_contexts(question, expanded_contexts or final_contexts or candidate_contexts)
    pageindex_contexts = retrieve_pageindex_contexts(
        db,
        question,
        user,
        group_ids,
        base_contexts=pageindex_base_contexts,
        max_contexts=PAGEINDEX_SUPPLEMENT_MAX,
        knowledge_scope=knowledge_scope,
    )
    pageindex_added = len(pageindex_contexts)
    if pageindex_contexts:
        # PageIndex carries the document structure/tree and should be the primary context.
        # Vector/SQLite chunks are kept only as supplemental evidence after structural hits.
        expanded_contexts = _merge_unique_contexts(pageindex_contexts, expanded_contexts, ADAPTIVE_CONTEXT_MAX)
    expanded_contexts = _filter_process_contexts(question, expanded_contexts)
    allowed_doc_kinds = allowed_kinds_for_query_topic(query_profile.get("topic"), "text")
    filtered_by_kind, document_kind_dropped = filter_contexts_by_allowed_kinds(expanded_contexts, allowed_doc_kinds)
    if filtered_by_kind:
        expanded_contexts = filtered_by_kind
    expanded_contexts = expanded_contexts[:ADAPTIVE_CONTEXT_MAX]
    pre_rerank_count = len(expanded_contexts)
    final_limit = min(ADAPTIVE_FINAL_CONTEXT_MAX, max(ADAPTIVE_FINAL_CONTEXT_MIN, int(plan["target_contexts"])))
    rule_limit = min(ADAPTIVE_CONTEXT_MAX, max(final_limit, get_reranker_config(db).get("max_candidates", 24)))
    expanded_contexts, pageindex_selected = rerank_contexts(question, expanded_contexts, rule_limit, query_profile)
    expanded_contexts, llm_reranker_meta = llm_rerank_contexts(db, question, expanded_contexts, final_limit)
    pageindex_selected = sum(1 for item in expanded_contexts if item.get("pageindex_source"))

    best_score = max((_safe_float(item.get("score"), 0.0) for item in [*candidate_contexts, *pageindex_contexts]), default=0.0)
    unique_docs = {str(item.get("document_id") or "") for item in expanded_contexts if item.get("document_id")}
    meta = {
        **plan,
        "candidate_count": candidate_count,
        "query_profile": query_profile,
        "knowledge_scope": normalize_document_scope(knowledge_scope, "production"),
        "allowed_document_kinds": sorted(allowed_doc_kinds),
        "document_kind_filtered_count": document_kind_dropped,
        "keyword_candidate_count": keyword_candidate_count,
        "merged_candidate_count": len(candidate_contexts),
        "filtered_count": len(filtered),
        "final_context_count": len(expanded_contexts),
        "pre_rerank_context_count": pre_rerank_count,
        "rerank_limit": final_limit,
        "rule_rerank_limit": rule_limit,
        "llm_reranker_enabled": bool(llm_reranker_meta.get("enabled")),
        "llm_reranker_used": bool(llm_reranker_meta.get("used")),
        "llm_reranker_model": llm_reranker_meta.get("model") or "",
        "llm_reranker_error": llm_reranker_meta.get("error") or "",
        "llm_reranked_count": llm_reranker_meta.get("reranked_count") or 0,
        "agentic_enabled": bool(agentic_route.get("enabled")),
        "agentic_strategy": agentic_route.get("strategy") or "single_pass_rag",
        "agentic_complexity_score": agentic_route.get("complexity_score") or 0.0,
        "agentic_reasons": agentic_route.get("reasons") or [],
        "agentic_initial_quality": agentic_initial_quality,
        "agentic_final_quality": agentic_final_quality,
        "agentic_rewrite_queries": agentic_rewrites,
        "agentic_extra_rounds": 1 if agentic_extra_candidate_count else 0,
        "agentic_extra_candidate_count": agentic_extra_candidate_count,
        "agentic_extra_filtered_count": agentic_extra_filtered_count,
        "adjacent_added": adjacent_added,
        "pageindex_added": pageindex_added,
        "pageindex_selected": pageindex_selected,
        "unique_document_count": len(unique_docs),
        "best_score": round(best_score, 4),
        "backend": "hybrid" if pageindex_added else retrieval_backend,
        "fallback_note": retrieval_note,
    }
    note_parts = [
        retrieval_note,
        f"adaptive:{plan['intent']}",
        f"candidates={candidate_count}",
        f"keyword={keyword_candidate_count}",
        f"filtered={len(filtered)}",
        f"contexts={len(expanded_contexts)}",
        f"rerank={pre_rerank_count}->{len(expanded_contexts)}",
        f"agentic={'on' if agentic_route.get('enabled') else 'off'}",
        f"agentic_rounds={1 if agentic_extra_candidate_count else 0}",
    ]
    if agentic_rewrites:
        note_parts.append(f"agentic_rewrites={len(agentic_rewrites)}")
    if agentic_notes:
        note_parts.extend(agentic_notes[:2])
    if llm_reranker_meta.get("used"):
        note_parts.append("llm_reranker=used")
    elif llm_reranker_meta.get("enabled"):
        note_parts.append("llm_reranker=failed")
    else:
        note_parts.append("llm_reranker=disabled")
    if adjacent_added:
        note_parts.append(f"adjacent_added={adjacent_added}")
    if pageindex_added:
        note_parts.append(f"pageindex_added={pageindex_added}")
        retrieval_backend = "hybrid"
    retrieval_note = "; ".join(part for part in note_parts if part)
    return expanded_contexts, retrieval_backend, retrieval_note, candidate_count, meta
