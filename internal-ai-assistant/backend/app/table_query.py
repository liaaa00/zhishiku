from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Document, DocumentTableRow, User, document_group_link
from .table_plan import COLUMN_ALIASES, COLUMN_LABELS, clean as plan_clean, format_filter_condition, format_filter_groups, parse_table_query_plan
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
    "多少个",
    "有多少",
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
    "截止时间",
    "预计缴款时间",
    "操作规则",
    "缴费规则",
    "时间节点",
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
)

TABLE_TIME_TERMS = (
    "截止时间",
    "预计缴款时间",
    "操作规则",
    "时间节点",
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

    structure_hit = any(term in compact for term in TABLE_STRUCTURE_TERMS)
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
    if verb_hit and (structure_hit or business_hit):
        return True
    if structure_hit and business_hit:
        return True
    if any(key in compact for key in ("分公司", "公司名称", "开设公司")) and any(key in compact for key in ("哪些", "哪几个", "在哪", "列出", "名单", "范围")):
        return True
    return False


def _user_group_ids(user: User) -> list[str]:
    return [group.id for group in getattr(user, "groups", []) or []]


def _has_document_access(db: Session, doc: Document, user: User, group_ids: list[str] | None = None) -> bool:
    source_type = str(doc.source_type or "")
    if source_type.startswith("chat_"):
        return doc.created_by == user.id or bool(getattr(user, "is_admin", False))
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


def accessible_table_documents(db: Session, user: User, document_ids: list[str] | None = None) -> list[Document]:
    query = (
        select(Document)
        .join(DocumentTableRow, DocumentTableRow.document_id == Document.id)
        .distinct()
        .order_by(Document.created_at.desc())
    )
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    docs = db.execute(query).scalars().all()
    return [doc for doc in docs if _has_document_access(db, doc, user)]


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

    if any(word in question for word in ("有效网点", "网点", "开设", "有效")):
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

    return round(min(score, 1.0), 4)


def select_table_documents(db: Session, question: str, user: User, limit: int = 3, document_ids: list[str] | None = None) -> list[Document]:
    docs = accessible_table_documents(db, user, document_ids=document_ids)
    if not docs:
        return []
    scored: list[tuple[float, Document]] = []
    for doc in docs:
        sample_rows = _sample_rows(db, doc.id, limit=6)
        score = _score_document(question, doc, sample_rows)
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


AGGREGATE_LABELS = {
    "sum": "汇总",
    "avg": "平均值",
    "max": "最大值",
    "min": "最小值",
}


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


def build_table_answer(question: str, contexts: list[dict]) -> str:
    raw_data_rows = [item for item in contexts or [] if not item.get("is_header")]
    seen_rows: set[str] = set()
    data_rows: list[dict] = []
    for item in raw_data_rows:
        identity = _row_identity(item)
        if identity in seen_rows:
            continue
        seen_rows.add(identity)
        data_rows.append(item)
    if not data_rows:
        return "没有在表格里找到足够相关的记录。"

    compact_question = re.sub(r"\s+", "", question or "")
    plan = parse_table_query_plan(question, include_quoted_company=False)
    branch_completion = plan.branch_completion_filter
    group_by = plan.group_by
    distinct_by = plan.distinct_by
    query_op = plan.query_op
    value_filters = plan.filters
    filter_logic = plan.filter_logic
    filter_groups = plan.filter_groups
    aggregate_op = plan.aggregate_op
    measure_column = plan.measure_column
    select_columns = plan.select_columns
    count_unit = "家" if any(term in compact_question for term in ("公司", "分公司", "开设公司", "多少家")) else "条"
    distinct_values: list[str] = []
    group_counts: dict[str, int] = defaultdict(int)
    aggregate_values: list[float] = []
    group_aggregate_values: dict[str, list[float]] = defaultdict(list)
    for item in data_rows:
        row = item.get("table_row") if isinstance(item.get("table_row"), dict) else {}
        semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
        if distinct_by:
            value = _first_alias_value(row, distinct_by, semantic_map)
            if value and value not in distinct_values:
                distinct_values.append(value)
        group_value = ""
        if group_by:
            group_value = _first_alias_value(row, group_by, semantic_map) or "未标明"
            group_counts[group_value] += 1
        if aggregate_op and measure_column:
            measure_raw = _first_alias_value(row, measure_column, semantic_map)
            numeric = _numeric_value(measure_raw)
            if numeric is not None:
                aggregate_values.append(numeric)
                if group_by:
                    group_aggregate_values[group_value or "未标明"].append(numeric)

    docs: dict[tuple[str, str], list[dict]] = defaultdict(list)
    hit_columns: list[str] = []
    preferred_columns = (
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
    )

    for context in data_rows:
        key = (context.get("document_title") or context.get("filename") or "未知文档", context.get("sheet_name") or "")
        docs[key].append(context)
        row = context.get("table_row") or {}
        for column in preferred_columns:
            if column in row and _clean(row.get(column, "")) and column not in hit_columns:
                hit_columns.append(column)
        if len(hit_columns) < 12:
            for column, value in row.items():
                if _clean(value) and column not in hit_columns:
                    hit_columns.append(str(column))
                if len(hit_columns) >= 12:
                    break

    lines = ["## 表格统计结果"]
    measure_label = COLUMN_LABELS.get(measure_column, measure_column or "指标")
    aggregate_label = AGGREGATE_LABELS.get(aggregate_op, aggregate_op)
    aggregate_result = _aggregate_result(aggregate_op, aggregate_values) if aggregate_op else None
    if aggregate_op:
        result_text = _format_number(aggregate_result) if aggregate_result is not None else "无可计算结果"
        lines.append(f"结论：{measure_label}{aggregate_label}为 {result_text}，基于 {len(aggregate_values)} 条可计算记录；本次共命中 {len(data_rows)} 条记录。")
    elif distinct_by:
        unit = "个城市" if distinct_by == "city" else "家公司"
        lines.append(f"结论：共有 {len(distinct_values)} {unit}，涉及 {len(data_rows)} 条命中记录。")
        if distinct_values:
            lines.append(f"去重结果：{'、'.join(distinct_values[:30])}" + ("。" if len(distinct_values) <= 30 else f" 等，另有 {len(distinct_values) - 30} 项未展开。"))
    else:
        lines.append(f"结论：共有 {len(data_rows)} {count_unit}命中记录。")
    lines.append("")
    lines.append("### 统计口径")
    op_label = {
        "branch_completion_count": "分公司完成度统计",
        "group_count": "分组计数",
        "sum": "求和汇总",
        "sum_group": "分组求和",
        "avg": "平均值汇总",
        "avg_group": "分组平均",
        "max": "最大值汇总",
        "max_group": "分组最大值",
        "min": "最小值汇总",
        "min_group": "分组最小值",
        "distinct_count": "去重计数",
        "distinct_list": "去重列举",
        "list": "明细列举",
        "count": "命中行计数",
        "retrieve": "表格检索",
    }.get(query_op, query_op)
    lines.append(f"- 查询操作：{op_label}。")
    if branch_completion:
        lines.append("- 仅统计同时满足：银行账户完成、社保公积金账户完成、公积金比例有值、公司名称有值的表格数据行。")
    else:
        lines.append("- 仅统计本次表格检索命中的数据行，已排除表头行；同一表格行只计 1 次。")
    if value_filters:
        filter_text = format_filter_groups(filter_groups, filter_logic) or "；".join(format_filter_condition(item) for item in value_filters)
        lines.append(f"- 过滤条件：{filter_text}。")
    if aggregate_op:
        lines.append(f"- 聚合方式：{COLUMN_LABELS.get(measure_column, measure_column or '指标')} {aggregate_label}。")
    if select_columns:
        select_text = "、".join(COLUMN_LABELS.get(column, column) for column in select_columns)
        lines.append(f"- 展示字段：{select_text}。")
    if distinct_by:
        label = "城市" if distinct_by == "city" else "公司"
        lines.append(f"- 对命中的 `{label}` 列按非空值去重统计。")
    lines.append(f"- 来源范围：{len(docs)} 个文件/Sheet 分组。")
    if hit_columns:
        lines.append(f"- 命中列：{'、'.join(hit_columns[:12])}")
    lines.append("")

    group_aggregate_results = {
        value: result
        for value, values in group_aggregate_values.items()
        if (result := _aggregate_result(aggregate_op, values)) is not None
    }
    if group_aggregate_results:
        group_label = {"city": "城市", "province": "省份", "company": "公司"}.get(group_by, group_by)
        lines.append(f"### 按{group_label}{aggregate_label}{measure_label}")
        for value, result in sorted(group_aggregate_results.items(), key=lambda item: (-item[1], item[0]))[:30]:
            count = len(group_aggregate_values.get(value, []))
            lines.append(f"- {value}：{_format_number(result)}（{count} 条可计算记录）")
        if len(group_aggregate_results) > 30:
            lines.append(f"- 另有 {len(group_aggregate_results) - 30} 个分组未展开。")
        lines.append("")
    elif group_counts:
        group_label = {"city": "城市", "province": "省份", "company": "公司"}.get(group_by, group_by)
        lines.append(f"### 按{group_label}统计")
        for value, count in sorted(group_counts.items(), key=lambda item: (-item[1], item[0]))[:30]:
            lines.append(f"- {value}：{count} 条")
        if len(group_counts) > 30:
            lines.append(f"- 另有 {len(group_counts) - 30} 个分组未展开。")
        lines.append("")

    lines.append("### 来源明细")
    for (title, sheet), items in docs.items():
        lines.append(f"- {title}" + (f" / Sheet：{sheet}" if sheet else "") + f"：{len(items)} 行")
    lines.append("")

    lines.append("### 命中行预览")
    for (title, sheet), items in docs.items():
        lines.append(f"#### {title}" + (f" / {sheet}" if sheet else ""))
        for item in items[:20]:
            row = item.get("table_row") or {}
            semantic_map = item.get("table_semantic_map") if isinstance(item.get("table_semantic_map"), dict) else {}
            parts = []
            if select_columns:
                for column in select_columns:
                    value = _first_alias_value(row, column, semantic_map)
                    if value:
                        parts.append(f"{COLUMN_LABELS.get(column, column)}={value}")
            for key in preferred_columns:
                value = _clean(row.get(key, ""))
                if value:
                    parts.append(f"{key}={value}")
            if not parts:
                parts = [f"{k}={_clean(v)}" for k, v in list(row.items())[:8] if _clean(v)]
            row_no = item.get("row_number") or ""
            prefix = f"行{row_no}：" if row_no else "- "
            lines.append(prefix + " | ".join(list(dict.fromkeys(parts))[:12]))
        if len(items) > 20:
            lines.append(f"- 另有 {len(items) - 20} 行未在预览中展开。")
    return "\n".join(lines)
