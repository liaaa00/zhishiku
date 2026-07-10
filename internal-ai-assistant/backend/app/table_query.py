from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .document_metadata import document_matches_scope, get_document_kind, get_document_scope, normalize_document_scope
from .models import Document, DocumentTableRow, User, document_group_link
from .table_plan import AGGREGATE_OPERATION_LABELS, COLUMN_ALIASES, COLUMN_LABELS, QUERY_OPERATION_LABELS, clean as plan_clean, describe_table_query_plan, format_filter_condition, format_filter_groups, parse_table_query_plan, result_limit
from .table_schema import infer_column_semantics, semantic_value

TABLE_QUERY_VERBS = (
    "多少",
    "几个",
    "统计",
    "列出",
    "明细",
    "筛选",
    "汇总",
    "规则",
    "哪些",
    "有哪些",
    "多少个",
    "有多少",
    "什么时候",
    "哪天",
    "几号",
    "谁",
    "哪位",
    "是否",
    "有没有",
    "有无",
    "是什么",
    "是多少",
    "分别是",
    "分别怎样",
    "分别如何",
    "开具完成",
    "开好",
    "完成了吗",
)

TABLE_STRUCTURE_TERMS = (
    "表格",
    "清单",
    "名单",
    "列表",
    "明细",
    "数据",
    "记录",
    "行",
    "列",
    "工作表",
    "sheet",
    "excel",
    "xlsx",
    "csv",
)

TABLE_BUSINESS_TERMS = (
    "网点",
    "有效网点",
    "社保",
    "医保",
    "公积金",
    "缴费",
    "缴款",
    "账户",
    "银行账户",
    "社保账户",
    "公积金账户",
    "社保公积金账户",
    "当前进度",
    "比例",
    "补充公积金比例",
    "备注",
    "备注要求",
    "派单",
    "截止时间",
    "预计缴款时间",
    "操作规则",
    "缴费规则",
    "时间节点",
    "时间表",
    "后道对接人",
    "分公司",
    "公司名称",
    "开设公司",
    "开了分公司",
    "哪些城市",
    "城市",
)


NON_TABLE_PROCESS_TERMS = (
    "流程",
    "步骤",
    "怎么签",
    "如何签",
    "电子签",
    "签署",
    "劳动合同",
    "合同",
    "指南",
    "操作指南",
    "办理流程",
    # 页面/模块类问题通常来自 PDF/网页操作说明；不能仅因“列出/哪些/列”进入表格路由。
    "注册页",
    "页面",
    "模块",
    "主要模块",
    "个人注册",
    "平台注册",
)

TABLE_TIME_TERMS = (
    "派单",
    "截止时间",
    "预计缴款时间",
    "操作规则",
    "时间节点",
    "时间表",
    "后道对接人",
)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def _question_terms(question: str) -> list[str]:
    text = (question or "").strip().lower()
    compact = re.sub(r"\s+", "", text)
    terms: set[str] = set(re.findall(r"[a-z0-9_]{2,}", compact))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", compact):
        for size in (2, 3, 4, 5):
            for index in range(max(0, len(chunk) - size + 1)):
                terms.add(chunk[index : index + size])
    for year, month in re.findall(r"(20\d{2})年(\d{1,2})月", question or ""):
        month_no = int(month)
        terms.update({f"{year}{month_no:02d}", f"{year}-{month_no:02d}", f"{year}年{month_no:02d}月"})
    terms.update(re.findall(r"\d{4,6}", compact))
    return [term for term in sorted(terms, key=len, reverse=True) if len(term) >= 2][:120]


def _month_tokens(question: str) -> list[str]:
    tokens: list[str] = []
    for year, month in re.findall(r"(20\d{2})年(\d{1,2})月", question or ""):
        month_no = int(month)
        tokens.extend([f"{year}{month_no:02d}", f"{year}-{month_no:02d}", f"{year}年{month_no:02d}月"])
    for token in re.findall(r"\b\d{6}\b", question or ""):
        tokens.append(token)
    return list(dict.fromkeys(tokens))


def is_table_query(question: str) -> bool:
    text = (question or "").strip()
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)

    # Explicitly keep document/process questions out of the table pipeline.
    if any(term in compact for term in NON_TABLE_PROCESS_TERMS):
        return False

    explicit_structure_terms = tuple(term for term in TABLE_STRUCTURE_TERMS if term not in {"行", "列"})
    structure_hit = any(term in compact for term in explicit_structure_terms)
    row_column_hit = any(term in compact for term in ("第几行", "哪一行", "哪几行", "第几列", "哪一列", "哪几列", "行号", "列名", "字段"))
    business_hit = any(term in compact for term in TABLE_BUSINESS_TERMS)
    verb_hit = any(word in compact for word in TABLE_QUERY_VERBS)
    month_hit = bool(re.search(r"20\d{2}年\d{1,2}月", text))

    time_business_hit = any(term in compact for term in TABLE_TIME_TERMS) and any(
        term in compact for term in ("社保", "医保", "公积金")
    )

    if month_hit and business_hit:
        return True
    if time_business_hit:
        return True
    if verb_hit and (structure_hit or row_column_hit or business_hit):
        return True
    if (structure_hit or row_column_hit) and business_hit:
        return True
    if any(key in compact for key in ("分公司", "公司名称", "开设公司")) and any(key in compact for key in ("哪些", "哪几个", "在哪", "列出", "名单", "范围")):
        return True
    return False


def _user_group_ids(user: User) -> list[str]:
    return [group.id for group in getattr(user, "groups", []) or []]


def _has_document_access(db: Session, doc: Document, user: User, group_ids: list[str] | None = None, knowledge_scope: str = "production") -> bool:
    source_type = str(doc.source_type or "")
    if source_type.startswith("chat_"):
        return document_matches_scope(doc, knowledge_scope) and (doc.created_by == user.id or bool(getattr(user, "is_admin", False)))
    if not document_matches_scope(doc, knowledge_scope):
        return False
    if getattr(user, "is_admin", False):
        return True
    resolved_group_ids = group_ids if group_ids is not None else _user_group_ids(user)
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


def _row_json(row: DocumentTableRow) -> dict[str, str]:
    try:
        parsed = json.loads(row.row_json or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _row_text(row: DocumentTableRow) -> str:
    return _clean(row.row_text or row.row_json or "")


def accessible_table_documents(db: Session, user: User, document_ids: list[str] | None = None, knowledge_scope: str = "production") -> list[Document]:
    scope = normalize_document_scope(knowledge_scope, "production")
    scope_filter = [] if scope == "all" else [Document.knowledge_scope == scope]
    query = (
        select(Document)
        .join(DocumentTableRow, DocumentTableRow.document_id == Document.id)
        .where(*scope_filter)
        .distinct()
        .order_by(Document.created_at.desc())
    )
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    docs = db.execute(query).scalars().all()
    return [doc for doc in docs if _has_document_access(db, doc, user, knowledge_scope=scope)]


def _sample_rows(db: Session, document_id: str, limit: int = 6) -> list[DocumentTableRow]:
    return db.execute(
        select(DocumentTableRow)
        .where(DocumentTableRow.document_id == document_id, DocumentTableRow.is_header == False)  # noqa: E712
        .order_by(DocumentTableRow.sheet_name.asc(), DocumentTableRow.row_number.asc(), DocumentTableRow.id.asc())
        .limit(limit)
    ).scalars().all()


def _score_document(question: str, doc: Document, sample_rows: list[DocumentTableRow]) -> float:
    terms = _question_terms(question)
    month_tokens = set(_month_tokens(question))
    title_text = f"{doc.title or ''} {doc.filename or ''}".lower()
    sample_text = " ".join(_row_text(row).lower() for row in sample_rows)
    row_values = []
    row_keys: set[str] = set()
    sample_payloads: list[dict[str, str]] = []
    for row in sample_rows:
        payload = _row_json(row)
        sample_payloads.append(payload)
        row_keys.update(payload.keys())
        row_values.extend(str(value) for value in payload.values())
    value_text = " ".join(row_values).lower()
    semantic_map = infer_column_semantics(sample_payloads)

    score = 0.04
    for term in terms:
        if term in title_text:
            score += 0.12 if len(term) <= 3 else 0.18
        if term in sample_text:
            score += 0.03 if len(term) <= 3 else 0.05

    if month_tokens and any(token in title_text or token in sample_text or token in value_text for token in month_tokens):
        score += 0.32

    if any(word in question for word in ("北京", "上海", "成都", "宁波", "北仑", "重庆", "杭州", "长沙", "西安", "郑州", "石家庄")):
        if any(city in value_text or city in title_text for city in ("北京", "上海", "成都", "宁波", "北仑", "重庆", "杭州", "长沙", "西安", "郑州", "石家庄")):
            score += 0.25

    if any(word in question for word in ("有效网点", "网点", "开设", "有效", "开了", "开分公司", "分公司")):
        if any("当前进度" in key or "开设公司名称" in key for key in row_keys):
            score += 0.6
        if {"city", "company"}.issubset(set(semantic_map.keys())):
            score += 0.45
        if "status" in semantic_map:
            score += 0.2

    if any(word in question for word in ("城市", "公司", "状态", "名单", "清单", "明细")):
        semantic_hits = sum(1 for key in ("city", "company", "status") if key in semantic_map)
        score += min(0.45, semantic_hits * 0.15)

    if any(word in question for word in ("社保", "公积金", "截止时间", "时间节点", "医保")):
        if any("截止时间" in key or "操作规则" in key or "预计缴款时间" in key for key in row_keys):
            score += 0.6

    if any(word in question for word in ("比例", "账户", "银行", "完成")):
        if any("比例" in key or "账户" in key or "完成" in key for key in row_keys):
            score += 0.2

    # 「名称含XX的条目」/「开了多少城市分公司」这类按公司名称过滤的问句缺少
    # 城市/月份/网点等既有关键词；改按“计划确实解析出 company/branch_company
    # 过滤 且 本文档确有对应列”来加分，使文档选择跟随真实查询意图而非固定词表。
    plan_columns = {item.get("column") for item in parse_table_query_plan(question).filters}
    if plan_columns & {"company", "branch_company"}:
        if "branch_company" in semantic_map or any("开设公司名称" in key for key in row_keys):
            score += 0.75
        elif "company" in semantic_map or any("公司名称" in key or "单位名称" in key for key in row_keys):
            score += 0.45

    return round(score, 4)


def _document_has_matching_month_sheet(db: Session, document_id: str, month_tokens: list[str]) -> bool:
    if not month_tokens:
        return False
    sheet_names = db.execute(
        select(DocumentTableRow.sheet_name)
        .where(DocumentTableRow.document_id == document_id)
        .distinct()
    ).scalars().all()
    for sheet_name in sheet_names:
        sheet = _clean(sheet_name)
        if sheet and any(token == sheet or token in sheet or sheet in token for token in month_tokens):
            return True
    return False


def select_table_documents(db: Session, question: str, user: User, limit: int = 3, document_ids: list[str] | None = None, knowledge_scope: str = "production") -> list[Document]:
    docs = accessible_table_documents(db, user, document_ids=document_ids, knowledge_scope=knowledge_scope)
    if not docs:
        return []
    scored: list[tuple[float, Document]] = []
    month_tokens = _month_tokens(question)
    for doc in docs:
        sample_rows = _sample_rows(db, doc.id, limit=6)
        score = _score_document(question, doc, sample_rows)
        # Multi-sheet Excel files may contain the requested month in a later sheet;
        # don't let a small leading-row sample discard the whole document before row-level filtering.
        if _document_has_matching_month_sheet(db, str(doc.id), month_tokens):
            score += 0.5
        scored.append((score, doc))
    scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
    min_score = 0.45
    selected = [doc for score, doc in scored if score >= min_score][: max(1, min(limit, 5))]
    return selected


def table_rows_for_documents(
    db: Session,
    document_ids: list[str],
    include_headers: bool = True,
    limit: int = 2000,
) -> list[tuple[DocumentTableRow, Document]]:
    if not document_ids:
        return []
    rows = db.execute(
        select(DocumentTableRow, Document)
        .join(Document, Document.id == DocumentTableRow.document_id)
        .where(DocumentTableRow.document_id.in_(document_ids))
        .order_by(
            DocumentTableRow.document_id.asc(),
            DocumentTableRow.sheet_name.asc(),
            DocumentTableRow.is_header.desc(),
            DocumentTableRow.row_number.asc(),
            DocumentTableRow.id.asc(),
        )
        .limit(limit)
    ).all()
    if include_headers:
        return rows
    return [(row, doc) for row, doc in rows if not row.is_header]


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _column_matches(key: str, alias_group: str) -> bool:
    return any(alias in str(key or "") for alias in COLUMN_ALIASES.get(alias_group, ()))


def _first_alias_value(row: dict, alias_group: str, semantic_map: dict | None = None) -> str:
    mapped_value = semantic_value(row, alias_group, semantic_map)
    if mapped_value:
        return mapped_value
    for key, value in row.items():
        if _column_matches(str(key), alias_group):
            cleaned = _clean(value)
            if cleaned:
                return cleaned
    return ""


def _row_identity(context: dict) -> str:
    return "|".join(
        str(context.get(key) or "")
        for key in ("document_id", "sheet_name", "row_number", "table_row_id")
    )


def _required_answer_columns(question: str, plan_select_columns: list[str]) -> list[str]:
    text = _compact(question)
    if any(term in text for term in ("统计", "平均", "均值", "汇总", "合计", "按城市", "按省", "按公司", "分城市", "分省", "分公司分别")):
        return []
    # 展示字段不等于过滤条件；这里只对用户明确要求必须存在的业务字段做二次过滤。
    required: list[str] = []
    if "银行账户" in text or ("银行" in text and "账户" in text):
        required.append("bank_account")
    if any(term in text for term in ("社保公积金账户", "社保账户", "公积金账户")):
        required.append("social_account")
    if any(term in text for term in ("公积金比例", "补充公积金比例")) or ("比例" in text and "公积金" in text):
        required.append("fund_ratio")
    if any(term in text for term in ("备注", "资料", "材料", "需提供", "需要提供", "提供哪些")):
        required.append("remark")
    return list(dict.fromkeys(column for column in required if column))


def _row_has_required_columns(context: dict, required_columns: list[str]) -> bool:
    if not required_columns:
        return True
    row = context.get("table_row") if isinstance(context.get("table_row"), dict) else {}
    semantic_map = context.get("table_semantic_map") if isinstance(context.get("table_semantic_map"), dict) else {}
    if not row:
        return False
    for column in required_columns:
        value = _first_alias_value(row, column, semantic_map)
        if not value:
            return False
    return True


def _filter_answer_rows(question: str, data_rows: list[dict]) -> list[dict]:
    plan = parse_table_query_plan(question, include_quoted_company=False)
    required_columns = _required_answer_columns(question, plan.select_columns)
    if not required_columns:
        return data_rows
    filtered = [item for item in data_rows if _row_has_required_columns(item, required_columns)]
    return filtered or data_rows


def _numeric_value(value: Any) -> float | None:
    text = plan_clean(value)
    if not text:
        return None
    normalized = text.replace(",", "").replace("，", "")
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")



def _aggregate_result(operation: str, values: list[float]) -> float | None:
    if not values:
        return None
    if operation == "sum":
        return sum(values)
    if operation == "avg":
        return sum(values) / len(values)
    if operation == "max":
        return max(values)
    if operation == "min":
        return min(values)
    return None


def _metric_key(metric: dict[str, str]) -> str:
    return f"{metric.get('op', '')}:{metric.get('column', '')}:{metric.get('label', '')}"


def _metric_result(metric: dict[str, str], values: list[float], count: int) -> float | int | None:
    op = metric.get("op") or ""
    if op == "count":
        return count
    return _aggregate_result(op, values)


PREFERRED_TABLE_PREVIEW_COLUMNS = (
    "省份",
    "城市",
    "单位名称",
    "开设公司名称",
    "公司名称",
    "当前进度-1.银行账户是否开具完成",
    "当前进度-2.社保公积金账户是否开具完成",
    "当前进度-3.公积金比例",
    "当前进度-4.开设公司名称",
    "银行账户",
    "社保公积金账户",
    "公积金比例",
    "操作规则-社保",
    "操作规则-医保",
    "操作规则-公积金",
    "截止时间-社保",
    "截止时间-医保",
    "截止时间-公积金",
    "预计缴款时间-社保",
    "预计缴款时间-公积金",
    "后道对接人",
    "备注",
)

IDENTITY_TABLE_COLUMNS = (
    "省份",
    "城市",
    "单位名称",
    "开设公司名称",
    "公司名称",
)


def _question_subject_markers(compact_question: str) -> tuple[str, ...]:
    markers: list[str] = []
    if "社保" in compact_question:
        markers.append("社保")
    if "医保" in compact_question:
        markers.append("医保")
    if "公积金" in compact_question:
        markers.append("公积金")
    return tuple(markers)


def _focus_key_markers(compact_question: str) -> tuple[str, ...]:
    markers: list[str] = []
    if any(term in compact_question for term in ("操作规则", "规则", "办理", "增减员", "增减")):
        markers.append("操作规则")
    if any(term in compact_question for term in ("截止时间", "截止日", "派单截止", "哪天", "几号", "什么时候")):
        markers.append("截止时间")
    if any(term in compact_question for term in ("预计缴款", "缴款时间")):
        markers.append("预计缴款时间")
    if any(term in compact_question for term in ("备注", "注意事项", "资料", "材料", "需提供", "需要提供", "提供哪些", "准备什么", "增减员", "增减")):
        markers.append("备注")
    if any(term in compact_question for term in ("同城转入", "谁来操作", "谁操作", "谁", "哪位", "操作人", "办理人", "经办人", "对接人", "后道")):
        markers.extend(["备注", "后道对接人", "对接人", "操作人", "办理人", "经办人"])
    if "银行账户" in compact_question or ("银行" in compact_question and "账户" in compact_question):
        markers.append("银行账户")
    if any(term in compact_question for term in ("社保公积金账户", "社保账户", "公积金账户")):
        markers.append("社保公积金账户")
    if "比例" in compact_question:
        markers.append("公积金比例")
    return tuple(dict.fromkeys(markers))


def _key_matches_focus(key: str, focus_markers: tuple[str, ...], subject_markers: tuple[str, ...]) -> bool:
    if not focus_markers:
        return False
    key_text = str(key or "")
    if not any(marker in key_text for marker in focus_markers):
        return False
    timed_or_rule = any(marker in key_text for marker in ("操作规则", "截止时间", "预计缴款时间"))
    if timed_or_rule and subject_markers:
        return any(subject in key_text for subject in subject_markers)
    return True


def _focused_preview_columns(row: dict[str, Any], compact_question: str, select_columns: list[str], semantic_map: dict | None = None) -> list[str]:
    columns: list[str] = []
    for key in IDENTITY_TABLE_COLUMNS:
        if key in row and _clean(row.get(key, "")):
            columns.append(key)

    focus_markers = _focus_key_markers(compact_question)
    subject_markers = _question_subject_markers(compact_question)
    if focus_markers:
        for key in row:
            if _key_matches_focus(str(key), focus_markers, subject_markers):
                columns.append(str(key))

    for column in select_columns:
        mapped = semantic_map.get(column).raw_name if semantic_map and column in semantic_map else ""
        if mapped and mapped in row:
            columns.append(mapped)
        for key in row:
            if _column_matches(str(key), column):
                columns.append(str(key))

    if not columns:
        columns.extend(key for key in PREFERRED_TABLE_PREVIEW_COLUMNS if key in row)
    return list(dict.fromkeys(columns))


def _wants_company_name_with_city_list(compact_question: str, select_columns: list[str]) -> bool:
    if not any(term in compact_question for term in ("名字", "名称", "叫什么", "叫啥", "分别")):
        return False
    return any(column in {"company", "branch_company"} for column in select_columns) or any(
        term in compact_question for term in ("公司", "分公司", "开设公司")
    )


def _city_company_detail_rows(data_rows: list[dict]) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in data_rows:
        row = item.get("table_row") if isinstance(item.get("table_row"), dict) else {}
        semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
        city = _first_alias_value(row, "city", semantic_map)
        company = _first_alias_value(row, "branch_company", semantic_map) or _first_alias_value(row, "company", semantic_map)
        if not city or not company:
            continue
        key = (city, company)
        if key in seen:
            continue
        seen.add(key)
        rows.append(key)
    return rows


@dataclass(slots=True)
class TableAnswerData:
    data_rows: list[dict]
    distinct_values: list[str] = field(default_factory=list)
    group_counts: dict[str, int] = field(default_factory=dict)
    aggregate_values: list[float] = field(default_factory=list)
    group_aggregate_values: dict[str, list[float]] = field(default_factory=dict)
    metric_values: dict[str, list[float]] = field(default_factory=dict)
    group_metric_values: dict[str, dict[str, list[float]]] = field(default_factory=dict)
    docs: dict[tuple[str, str], list[dict]] = field(default_factory=dict)
    hit_columns: list[str] = field(default_factory=list)


def row_to_context(doc: Document, row: DocumentTableRow) -> dict:
    payload = _row_json(row)
    location = f"table | {doc.filename or doc.title or ''} | {row.sheet_name or ''} | 行{row.row_number or ''}"
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": "",
        "chunk_index": f"table:{row.id}",
        "page_number": row.row_number,
        "source_type": doc.source_type or "xlsx",
        "knowledge_scope": get_document_scope(doc),
        "document_kind": get_document_kind(doc),
        "content": _row_text(row),
        "score": 0.82 if not row.is_header else 0.45,
        "match_terms": [],
        "match_reason": "表格结构化行命中",
        "retrieval_channel": "table",
        "table_row": payload,
        "table_row_id": row.id,
        "sheet_name": row.sheet_name,
        "row_number": row.row_number,
        "is_header": row.is_header,
        "location": location,
    }


class TableAnswerComposer:
    """Compose deterministic answers for structured table retrieval contexts."""

    def __init__(self, question: str, contexts: list[dict] | None) -> None:
        self.question = question
        self.contexts = contexts or []

    def render(self) -> str:
        data_rows = self._unique_data_rows()
        if not data_rows:
            return "没有在表格里找到足够相关的记录。"
        return _render_table_answer(self.question, data_rows)

    def structured_result(self) -> dict:
        data_rows = self._unique_data_rows()
        if not data_rows:
            return {"columns": [], "rows": [], "row_count": 0, "type": "empty"}
        return _build_table_structured_result(self.question, data_rows)

    def _unique_data_rows(self) -> list[dict]:
        raw_data_rows = [item for item in self.contexts if not item.get("is_header")]
        seen_rows: set[str] = set()
        data_rows: list[dict] = []
        for item in raw_data_rows:
            identity = _row_identity(item)
            if identity in seen_rows:
                continue
            seen_rows.add(identity)
            data_rows.append(item)
        return _filter_answer_rows(self.question, data_rows)


def build_table_answer(question: str, contexts: list[dict]) -> str:
    return TableAnswerComposer(question, contexts).render()


def build_table_structured_result(question: str, contexts: list[dict]) -> dict:
    return TableAnswerComposer(question, contexts).structured_result()


def _build_table_answer_data(data_rows: list[dict], *, question: str, query_op: str, distinct_by: str, group_by: str, aggregate_op: str, measure_column: str, metrics: list[dict[str, str]]) -> TableAnswerData:
    answer_data = TableAnswerData(
        data_rows=data_rows,
        group_counts=defaultdict(int),
        group_aggregate_values=defaultdict(list),
        metric_values=defaultdict(list),
        group_metric_values=defaultdict(lambda: defaultdict(list)),
        docs=defaultdict(list),
    )
    # 检测是否为分公司计数查询（需要按城市+分公司名称去重）
    is_branch_count_query = (
        query_op in ("count", "distinct_count")
        and any(term in plan_clean(question) for term in ("分公司", "公司", "网点"))
        and not distinct_by
        and not group_by
    )

    # 分公司去重：先过滤重复记录
    if is_branch_count_query:
        seen_branches: set[tuple[str, str]] = set()
        deduplicated_rows: list[dict] = []
        for item in data_rows:
            row = item.get("table_row") if isinstance(item.get("table_row"), dict) else {}
            semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
            city = _first_alias_value(row, "city", semantic_map) or ""
            branch = _first_alias_value(row, "branch_company", semantic_map) or _first_alias_value(row, "company", semantic_map) or ""
            if city and branch:
                key = (city, branch)
                if key not in seen_branches:
                    seen_branches.add(key)
                    deduplicated_rows.append(item)
            else:
                deduplicated_rows.append(item)  # 保留缺少城市或分公司名称的行
        data_rows = deduplicated_rows  # 使用去重后的数据
        answer_data.data_rows = deduplicated_rows  # 更新answer_data中的数据行

    for item in data_rows:
        row = item.get("table_row") if isinstance(item.get("table_row"), dict) else {}
        semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
        if distinct_by:
            value = _first_alias_value(row, distinct_by, semantic_map)
            if value and value not in answer_data.distinct_values:
                answer_data.distinct_values.append(value)
        group_value = ""
        if group_by:
            group_value = _first_alias_value(row, group_by, semantic_map) or "未标明"
            answer_data.group_counts[group_value] += 1
        if aggregate_op and measure_column:
            measure_raw = _first_alias_value(row, measure_column, semantic_map)
            numeric = _numeric_value(measure_raw)
            if numeric is not None:
                answer_data.aggregate_values.append(numeric)
                if group_by:
                    answer_data.group_aggregate_values[group_value or "未标明"].append(numeric)
        for metric in metrics:
            if metric.get("op") == "count":
                continue
            metric_column = metric.get("column") or ""
            if not metric_column:
                continue
            metric_raw = _first_alias_value(row, metric_column, semantic_map)
            metric_numeric = _numeric_value(metric_raw)
            if metric_numeric is None:
                continue
            metric_key = _metric_key(metric)
            answer_data.metric_values[metric_key].append(metric_numeric)
            if group_by:
                answer_data.group_metric_values[group_value or "未标明"][metric_key].append(metric_numeric)

    for context in data_rows:
        key = (context.get("document_title") or context.get("filename") or "未知文档", context.get("sheet_name") or "")
        answer_data.docs[key].append(context)
        row = context.get("table_row") or {}
        for column in PREFERRED_TABLE_PREVIEW_COLUMNS:
            if column in row and _clean(row.get(column, "")) and column not in answer_data.hit_columns:
                answer_data.hit_columns.append(column)
        if len(answer_data.hit_columns) < 12:
            for column, value in row.items():
                if _clean(value) and column not in answer_data.hit_columns:
                    answer_data.hit_columns.append(str(column))
                if len(answer_data.hit_columns) >= 12:
                    break
    return answer_data


def _build_table_structured_result(question: str, data_rows: list[dict]) -> dict:
    plan = parse_table_query_plan(question, include_quoted_company=False)
    answer_data = _build_table_answer_data(
        data_rows,
        question=question,
        query_op=plan.query_op,
        distinct_by=plan.distinct_by,
        group_by=plan.group_by,
        aggregate_op=plan.aggregate_op,
        measure_column=plan.measure_column,
        metrics=plan.metrics,
    )
    result_limit = max(1, min(100, int(plan.limit or 20)))
    sort_by = plan.sort_by or "desc"
    result_sort_key = (lambda item: (item[1], item[0])) if sort_by == "asc" else (lambda item: (-item[1], item[0]))
    group_label = COLUMN_LABELS.get(plan.group_by, plan.group_by or "分组")

    base = {
        "type": plan.query_op,
        "time_grain": plan.time_grain,
        "time_value": plan.time_value,
        "group_by": plan.group_by,
        "metrics": plan.metrics,
        "columns": [],
        "rows": [],
        "row_count": 0,
    }

    if plan.metrics and len(plan.metrics) > 1 and plan.group_by:
        columns = [group_label] + [metric.get("label") or COLUMN_LABELS.get(metric.get("column", ""), metric.get("op", "")) for metric in plan.metrics]
        rows: list[list[Any]] = []
        for value, count in sorted(answer_data.group_counts.items(), key=result_sort_key)[:result_limit]:
            row_values: list[Any] = [value]
            for metric in plan.metrics:
                if metric.get("op") == "count":
                    row_values.append(count)
                    continue
                metric_key = _metric_key(metric)
                metric_values = answer_data.group_metric_values.get(value, {}).get(metric_key, [])
                row_values.append(_metric_result(metric, metric_values, count))
            rows.append(row_values)
        return {**base, "columns": columns, "rows": rows, "row_count": len(rows)}

    group_aggregate_results = {
        value: result
        for value, values in answer_data.group_aggregate_values.items()
        if (result := _aggregate_result(plan.aggregate_op, values)) is not None
    }
    if group_aggregate_results and plan.group_by:
        measure_label = COLUMN_LABELS.get(plan.measure_column, plan.measure_column or "指标")
        aggregate_label = AGGREGATE_OPERATION_LABELS.get(plan.aggregate_op, plan.aggregate_op)
        rows = [[value, result, len(answer_data.group_aggregate_values.get(value, []))] for value, result in sorted(group_aggregate_results.items(), key=result_sort_key)[:result_limit]]
        return {**base, "columns": [group_label, f"{measure_label}{aggregate_label}", "可计算记录数"], "rows": rows, "row_count": len(rows)}

    if answer_data.group_counts and plan.group_by:
        rows = [[value, count] for value, count in sorted(answer_data.group_counts.items(), key=result_sort_key)[:result_limit]]
        return {**base, "columns": [group_label, "数量"], "rows": rows, "row_count": len(rows)}

    selected_columns = plan.select_columns or []
    if selected_columns:
        columns = [COLUMN_LABELS.get(column, column) for column in selected_columns]
        rows = []
        for item in data_rows[:result_limit]:
            row = item.get("table_row") if isinstance(item.get("table_row"), dict) else {}
            semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
            rows.append([_first_alias_value(row, column, semantic_map) for column in selected_columns])
        return {**base, "type": "list", "columns": columns, "rows": rows, "row_count": len(rows)}

    return base


def _sheet_month_label(item: dict) -> str:
    sheet = _clean(item.get("sheet_name") or "")
    match = re.search(r"(20\d{2})(\d{2})", sheet)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    match = re.search(r"(20\d{2})[-/](\d{1,2})", sheet)
    if match:
        return f"{match.group(1)}-{int(match.group(2)):02d}"
    return sheet or "未标明月份"


def _comparison_key_values(item: dict, compact_question: str, select_columns: list[str]) -> dict[str, str]:
    row = item.get("table_row") if isinstance(item.get("table_row"), dict) else {}
    semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
    values: dict[str, str] = {}
    for key in _focused_preview_columns(row, compact_question, select_columns, semantic_map):
        if key in IDENTITY_TABLE_COLUMNS:
            continue
        value = _clean(row.get(key, ""))
        if value:
            values[str(key)] = value
    if not values:
        for key in PREFERRED_TABLE_PREVIEW_COLUMNS:
            if key in IDENTITY_TABLE_COLUMNS:
                continue
            value = _clean(row.get(key, ""))
            if value:
                values[str(key)] = value
    return values


def _render_month_comparison(question: str, data_rows: list[dict], plan, select_columns: list[str]) -> list[str] | None:
    compact_question = _compact(question)
    if not data_rows or "," not in (plan.time_value or ""):
        return None
    if not any(term in compact_question for term in ("变化", "对比", "比较", "分别", "差异")):
        return None
    by_month: dict[str, dict] = {}
    for item in data_rows:
        label = _sheet_month_label(item)
        by_month.setdefault(label, item)
    if len(by_month) < 2:
        return None

    lines = [f"结论：已按月份对比 {len(by_month)} 条记录。"]
    if plan.filters:
        filter_text = format_filter_groups(plan.filter_groups, plan.filter_logic) or "；".join(format_filter_condition(item) for item in plan.filters)
        if filter_text:
            lines.append(f"条件：{filter_text}。")
    lines.extend(["", "### 对比结果"])
    month_values: dict[str, dict[str, str]] = {}
    for month, item in sorted(by_month.items()):
        values = _comparison_key_values(item, compact_question, select_columns)
        month_values[month] = values
        detail = " | ".join(f"{key}={value}" for key, value in values.items()) or "未找到可对比字段"
        lines.append(f"- {month}：{detail}")

    all_keys = list(dict.fromkeys(key for values in month_values.values() for key in values))
    changed: list[str] = []
    unchanged: list[str] = []
    for key in all_keys:
        observed = {values.get(key, "") for values in month_values.values()}
        observed.discard("")
        if len(observed) > 1:
            changed.append(key)
        elif observed:
            unchanged.append(key)
    if changed:
        lines.append("变化字段：" + "、".join(changed) + "。")
    elif unchanged:
        lines.append("变化字段：未发现上述字段变化。")
    return lines


def _render_table_answer(question: str, data_rows: list[dict]) -> str:
    compact_question = re.sub(r"\s+", "", question or "")
    plan = parse_table_query_plan(question, include_quoted_company=False)
    branch_completion = plan.branch_completion_filter
    group_by = plan.group_by
    distinct_by = plan.distinct_by
    aggregate_op = plan.aggregate_op
    measure_column = plan.measure_column
    metrics = plan.metrics
    time_grain = plan.time_grain
    time_value = plan.time_value
    select_columns = plan.select_columns
    sort_by = plan.sort_by or "desc"
    explicit_limit = result_limit(question, default=0)
    count_unit = "家" if any(term in compact_question for term in ("公司", "分公司", "开设公司", "多少家")) else "条"
    comparison_lines = _render_month_comparison(question, data_rows, plan, select_columns)
    if comparison_lines:
        return "\n".join(comparison_lines).strip()

    answer_data = _build_table_answer_data(
        data_rows,
        question=question,
        query_op=plan.query_op,
        distinct_by=distinct_by,
        group_by=group_by,
        aggregate_op=aggregate_op,
        measure_column=measure_column,
        metrics=metrics,
    )

    def limited(items: list[Any]) -> list[Any]:
        return items[:explicit_limit] if explicit_limit else items

    def append_notice_if_limited(total: int) -> None:
        if explicit_limit and total > explicit_limit:
            lines.append(f"说明：已按你的要求只显示前 {explicit_limit} 项，其余可通过下方溯源查看。")

    def row_parts(item: dict) -> list[str]:
        row = item.get("table_row") or {}
        semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
        parts: list[str] = []
        if select_columns:
            for column in select_columns:
                value = _first_alias_value(row, column, semantic_map)
                if value:
                    parts.append(f"{COLUMN_LABELS.get(column, column)}={value}")
        for key in _focused_preview_columns(row, compact_question, select_columns, semantic_map):
            value = _clean(row.get(key, ""))
            if value:
                parts.append(f"{key}={value}")
        if not parts:
            parts = [f"{k}={_clean(v)}" for k, v in list(row.items())[:8] if _clean(v)]
        limit = 18 if _focus_key_markers(compact_question) else 12
        return list(dict.fromkeys(parts))[:limit]

    lines = []
    measure_label = COLUMN_LABELS.get(measure_column, measure_column or "指标")
    aggregate_label = AGGREGATE_OPERATION_LABELS.get(aggregate_op, aggregate_op)
    aggregate_result = _aggregate_result(aggregate_op, answer_data.aggregate_values) if aggregate_op else None

    if metrics and len(metrics) > 1:
        lines.append(f"结论：已按 {COLUMN_LABELS.get(group_by, group_by or '分组')} 生成 {len(metrics)} 个统计指标，共命中 {len(data_rows)} 条记录。")
    elif aggregate_op:
        result_text = _format_number(aggregate_result) if aggregate_result is not None else "无可计算结果"
        lines.append(f"结论：{measure_label}{aggregate_label}为 {result_text}，基于 {len(answer_data.aggregate_values)} 条可计算记录。")
    elif distinct_by:
        unit = "个城市" if distinct_by == "city" else "家公司"
        lines.append(f"结论：共有 {len(answer_data.distinct_values)} {unit}。")
    else:
        lines.append(f"结论：共有 {len(data_rows)} {count_unit}命中记录。")

    short_notes: list[str] = []
    if branch_completion:
        short_notes.append("条件：银行账户、社保公积金账户、公积金比例、公司名称均已完成/有值。")
    if plan.filters:
        filter_text = format_filter_groups(plan.filter_groups, plan.filter_logic) or "；".join(format_filter_condition(item) for item in plan.filters)
        if filter_text:
            short_notes.append(f"条件：{filter_text}。")
    if time_grain and time_value:
        short_notes.append(f"时间范围：{time_value}。")
    if short_notes:
        lines.append(short_notes[0])
    lines.append("")

    group_aggregate_results = {
        value: result
        for value, values in answer_data.group_aggregate_values.items()
        if (result := _aggregate_result(aggregate_op, values)) is not None
    }
    result_sort_key = (lambda item: (item[1], item[0])) if sort_by == "asc" else (lambda item: (-item[1], item[0]))

    if metrics and len(metrics) > 1 and group_by:
        group_label = {"city": "城市", "province": "省份", "company": "公司"}.get(group_by, group_by)
        ranked_groups = sorted(answer_data.group_counts.items(), key=result_sort_key)
        lines.append("### 统计结果")
        for value, count in limited(ranked_groups):
            metric_parts = [f"{group_label}={value}", f"数量={count}"]
            for metric in metrics:
                if metric.get("op") == "count":
                    continue
                metric_key = _metric_key(metric)
                metric_values = answer_data.group_metric_values.get(value, {}).get(metric_key, [])
                result = _metric_result(metric, metric_values, count)
                if result is None:
                    continue
                metric_label = metric.get("label") or COLUMN_LABELS.get(metric.get("column", ""), metric.get("op", ""))
                formatted = _format_number(float(result)) if isinstance(result, float) else str(result)
                metric_parts.append(f"{metric_label}={formatted}")
            lines.append("- " + " | ".join(metric_parts))
        append_notice_if_limited(len(ranked_groups))
        lines.append("")
    elif group_aggregate_results:
        group_label = {"city": "城市", "province": "省份", "company": "公司"}.get(group_by, group_by)
        ranked_results = sorted(group_aggregate_results.items(), key=result_sort_key)
        lines.append("### 统计结果")
        for value, result in limited(ranked_results):
            count = len(answer_data.group_aggregate_values.get(value, []))
            lines.append(f"- {group_label}={value} | {measure_label}{aggregate_label}={_format_number(result)} | 可计算记录数={count}")
        append_notice_if_limited(len(ranked_results))
        lines.append("")
    elif answer_data.group_counts and group_by:
        group_label = {"city": "城市", "province": "省份", "company": "公司"}.get(group_by, group_by)
        ranked_counts = sorted(answer_data.group_counts.items(), key=result_sort_key)
        lines.append("### 统计结果")
        for value, count in limited(ranked_counts):
            lines.append(f"- {group_label}={value} | 数量={count}")
        append_notice_if_limited(len(ranked_counts))
        lines.append("")
    elif distinct_by and answer_data.distinct_values:
        label = "城市" if distinct_by == "city" else "公司"
        lines.append("### 明细列表")
        if distinct_by == "city" and _wants_company_name_with_city_list(compact_question, select_columns):
            detail_rows = _city_company_detail_rows(answer_data.data_rows)
            for city, company in limited(detail_rows):
                lines.append(f"- 城市={city} | 开设公司名称={company}")
            append_notice_if_limited(len(detail_rows))
        else:
            for value in limited(answer_data.distinct_values):
                lines.append(f"- {label}={value}")
            append_notice_if_limited(len(answer_data.distinct_values))
        lines.append("")

    detail_intent = any(term in compact_question for term in ("列出", "明细", "清单", "名单", "哪些", "哪几", "详情", "全部"))
    show_detail = bool(branch_completion or plan.query_op in {"list", "retrieve"} or (select_columns and detail_intent))
    if show_detail and data_rows:
        lines.append("### 明细列表")
        for item in data_rows:
            parts = row_parts(item)
            if parts:
                lines.append("- " + " | ".join(parts))

    return "\n".join(line for line in lines if line is not None).strip()
