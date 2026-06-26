from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from .models import User
from .table_plan import CITY_TERMS, COLUMN_ALIASES, compact as _compact, parse_table_query_plan
from .table_query import row_to_context, select_table_documents, table_rows_for_documents
from .table_schema import infer_column_semantics, semantic_columns_debug, semantic_value

MONTH_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月")
MONTH_SEP_RE = re.compile(r"(20\d{2})\s*[-/]\s*(\d{1,2})")


def _clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def _question_tokens(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", (question or "").lower())
    tokens: set[str] = set(re.findall(r"[a-z0-9_\-]{2,}", compact))
    for chunk in re.findall(r"[\u4e00-\u9fff]+", compact):
        if len(chunk) <= 8:
            tokens.add(chunk)
        for size in (2, 3, 4):
            for index in range(max(0, len(chunk) - size + 1)):
                tokens.add(chunk[index : index + size])
    tokens.update(re.findall(r"\d{4,6}", compact))
    return [token for token in sorted(tokens, key=len, reverse=True) if len(token) >= 2][:80]


def _month_tokens(question: str) -> list[str]:
    text = _clean(question)
    tokens: set[str] = set(re.findall(r"\b20\d{4}\b", text))
    for year, month in MONTH_RE.findall(text):
        month_no = int(month)
        tokens.update(
            {
                f"{year}{month_no:02d}",
                f"{year}-{month_no:02d}",
                f"{year}年{month_no}月",
                f"{year}年{month_no:02d}月",
            }
        )
    for year, month in MONTH_SEP_RE.findall(text):
        month_no = int(month)
        tokens.update(
            {
                f"{year}{month_no:02d}",
                f"{year}-{month_no:02d}",
                f"{year}年{month_no}月",
                f"{year}年{month_no:02d}月",
            }
        )
    return [token for token in sorted(tokens, key=len, reverse=True) if len(token) >= 2]


def _sheet_matches_month(sheet_name: str, month_tokens: list[str]) -> bool:
    sheet = _clean(sheet_name)
    if not sheet or not month_tokens:
        return False
    return any(token == sheet or token in sheet or sheet in token for token in month_tokens)


def _year_tokens(question: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"20\d{2}", question or "")))


def _sheet_matches_year(sheet_name: str, year_tokens: list[str]) -> bool:
    sheet = _clean(sheet_name)
    if not sheet or not year_tokens:
        return False
    return any(year in sheet for year in year_tokens)


def _city_tokens(question: str) -> list[str]:
    compact = re.sub(r"\s+", "", question or "")
    return [city for city in CITY_TERMS if city in compact]


def _row_matches_city(context: dict, city_tokens: list[str]) -> bool:
    if not city_tokens:
        return True
    row = context.get("table_row") if isinstance(context.get("table_row"), dict) else {}
    focused_values: list[str] = []
    for key, value in row.items():
        key_text = str(key or "")
        if any(marker in key_text for marker in ("省", "城市", "地区", "单位名称", "公司名称", "分公司")):
            focused_values.append(str(value or ""))
    if not focused_values:
        focused_values = [str(value or "") for value in row.values()]
    haystack = " ".join(focused_values)
    return any(city in haystack for city in city_tokens)


def _column_matches(key: str, alias_group: str) -> bool:
    key_text = str(key or "")
    aliases = COLUMN_ALIASES.get(alias_group, ())
    return any(alias in key_text for alias in aliases)


def _row_values_for_alias(row: dict, alias_group: str) -> list[str]:
    values: list[str] = []
    for key, value in row.items():
        if _column_matches(str(key), alias_group):
            cleaned = _clean(value)
            if cleaned:
                values.append(cleaned)
    return values


def _row_text_for_aliases(row: dict, alias_groups: tuple[str, ...], semantic_map: dict | None = None) -> str:
    values: list[str] = []
    for group in alias_groups:
        mapped_value = semantic_value(row, group, semantic_map)
        if mapped_value:
            values.append(mapped_value)
        values.extend(_row_values_for_alias(row, group))
    if not values:
        values = [_clean(value) for value in row.values() if _clean(value)]
    return " ".join(dict.fromkeys(values))



def _row_matches_value_filters(context: dict, filters: list[dict[str, str]]) -> bool:
    if not filters:
        return True
    row = context.get("table_row") if isinstance(context.get("table_row"), dict) else {}
    semantic_map = context.get("table_semantic_map") if isinstance(context.get("table_semantic_map"), dict) else {}
    for item in filters:
        column = item.get("column") or ""
        value = item.get("value") or ""
        if not value:
            continue
        focused = _row_text_for_aliases(row, (column,), semantic_map)
        if value not in focused:
            return False
    return True



def _row_value_by_key_markers(row: dict, markers: tuple[str, ...]) -> str:
    for key, value in row.items():
        key_text = str(key or "")
        if any(marker in key_text for marker in markers):
            cleaned = _clean(value)
            if cleaned:
                return cleaned
    return ""


def _looks_complete(value: Any) -> bool:
    text = _compact(value)
    if not text:
        return False
    if any(term in text for term in ("否", "未", "待", "暂无", "无", "不")):
        return False
    return any(term in text for term in ("是", "已", "完成", "开具完成", "已开具", "开设完成", "已开设", "开户"))


def _has_concrete_value(value: Any) -> bool:
    text = _compact(value)
    if not text:
        return False
    if text in {"-", "--", "/", "无", "暂无", "否"}:
        return False
    if any(term in text for term in ("未开设", "未完成", "待定", "暂无", "无")):
        return False
    return True


def _row_matches_branch_completion(context: dict) -> bool:
    if context.get("is_header"):
        return False
    row = context.get("table_row") if isinstance(context.get("table_row"), dict) else {}
    if not row:
        return False
    bank = _row_value_by_key_markers(row, ("银行账户",))
    social = _row_value_by_key_markers(row, ("社保公积金账户", "社保账户", "公积金账户"))
    ratio = _row_value_by_key_markers(row, ("公积金比例",))
    company = _row_value_by_key_markers(row, ("开设公司名称", "公司名称"))
    return _looks_complete(bank) and _looks_complete(social) and _has_concrete_value(ratio) and _has_concrete_value(company)


def _row_score(question: str, context: dict, doc_rank: int) -> float:
    if context.get("is_header"):
        return -1.0

    row = context.get("table_row") if isinstance(context.get("table_row"), dict) else {}
    semantic_map = context.get("table_semantic_map") if isinstance(context.get("table_semantic_map"), dict) else {}
    sheet = _clean(context.get("sheet_name"))
    row_text = _clean(context.get("content") or "")
    row_keys = _clean(" ".join(str(key) for key in row.keys())) if row else ""
    row_values = _clean(" ".join(str(value) for value in row.values())) if row else ""
    semantic_values = _clean(" ".join(semantic_value(row, key, semantic_map) for key in ("city", "company", "status") if semantic_value(row, key, semantic_map)))
    combined = " ".join(part for part in [sheet, row_text, row_keys, row_values, semantic_values] if part).lower()

    score = 0.4 - doc_rank * 0.05
    month_tokens = _month_tokens(question)
    if month_tokens:
        if _sheet_matches_month(sheet, month_tokens):
            score += 8.0
        elif any(token.lower() in combined for token in month_tokens):
            score += 1.5
        else:
            score -= 1.25

    for token in _question_tokens(question):
        needle = token.lower()
        if needle in combined:
            score += 0.18 if len(token) <= 3 else 0.28

    if any(word in question for word in ("社保", "公积金", "医保", "时间节点", "截止时间", "操作规则")):
        if any(word in row_keys for word in ("截止时间", "操作规则", "预计缴款时间")):
            score += 1.2

    if any(word in question for word in ("分公司", "公司名称", "开设", "名单", "哪些城市", "城市")):
        if any(word in row_keys for word in ("单位名称", "开设公司名称", "公司名称")):
            score += 1.0
        if "city" in semantic_map or "company" in semantic_map:
            score += 0.9

    if any(word in question for word in ("状态", "有效", "启用", "停用")) and "status" in semantic_map:
        score += 0.7

    return round(score, 4)


def table_mode_contexts(db: Session, question: str, user: User, top_k: int = 10) -> tuple[list[dict], dict]:
    docs = select_table_documents(db, question, user, limit=2)
    if not docs:
        return [], {"mode": "table", "matched_rows": 0, "matched_documents": 0, "enabled": True}

    max_contexts = max(20, min(120, top_k * 12))
    per_doc_limit = max(80, (max_contexts // max(len(docs), 1)) * 3)
    scored_contexts: list[tuple[float, int, int, dict]] = []
    header_contexts_by_doc: dict[str, list[dict]] = {}
    table_schema_by_doc: dict[str, list[dict]] = {}
    month_tokens = _month_tokens(question)
    year_tokens = _year_tokens(question)
    plan = parse_table_query_plan(question)
    branch_completion_query = plan.branch_completion_filter
    city_tokens = [] if branch_completion_query else _city_tokens(question)
    value_filters = plan.filters
    group_by = plan.group_by
    distinct_by = plan.distinct_by
    select_columns = plan.select_columns
    query_op = plan.query_op
    plan_meta = plan.to_dict()

    for doc_rank, doc in enumerate(docs):
        rows = table_rows_for_documents(db, [doc.id], include_headers=True, limit=1000)
        raw_contexts = [row_to_context(row_doc, row) for row, row_doc in rows]
        raw_data_rows = [item for item in raw_contexts if not item.get("is_header")]
        semantic_map = infer_column_semantics(
            [item.get("table_row") for item in raw_data_rows if isinstance(item.get("table_row"), dict)]
        )
        table_schema_by_doc[str(doc.id)] = semantic_columns_debug(semantic_map)
        row_contexts = []
        for item in raw_contexts:
            enriched = dict(item)
            enriched["table_semantic_map"] = semantic_map
            enriched["table_schema"] = table_schema_by_doc[str(doc.id)]
            row_contexts.append(enriched)
        data_rows = [item for item in row_contexts if not item.get("is_header")]
        headers = [item for item in row_contexts if item.get("is_header")]
        # If the question names a month, score the whole table first so later
        # worksheets such as 202603 are not dropped by an early per-doc limit.
        candidate_rows = data_rows if month_tokens else data_rows[:per_doc_limit]
        for order, context in enumerate(candidate_rows):
            score = _row_score(question, context, doc_rank)
            if score >= 0.75:
                scored_contexts.append((score, doc_rank, order, context))
        header_contexts_by_doc[str(doc.id)] = headers[:2]

    if month_tokens:
        month_matched = [
            item
            for item in scored_contexts
            if _sheet_matches_month(str(item[3].get("sheet_name") or ""), month_tokens)
        ]
        if month_matched:
            scored_contexts = month_matched
        else:
            scored_contexts = []
    elif year_tokens:
        year_matched = [
            item
            for item in scored_contexts
            if _sheet_matches_year(str(item[3].get("sheet_name") or ""), year_tokens)
        ]
        if year_matched:
            scored_contexts = year_matched
        else:
            scored_contexts = []

    if city_tokens:
        city_matched = [item for item in scored_contexts if _row_matches_city(item[3], city_tokens)]
        if city_matched:
            scored_contexts = city_matched

    value_filter_matched_rows = 0
    if value_filters:
        value_matched = [item for item in scored_contexts if _row_matches_value_filters(item[3], value_filters)]
        value_filter_matched_rows = len(value_matched)
        scored_contexts = value_matched

    branch_completion_matched_rows = 0
    if branch_completion_query:
        branch_matched = [item for item in scored_contexts if _row_matches_branch_completion(item[3])]
        branch_completion_matched_rows = len(branch_matched)
        scored_contexts = branch_matched

    scored_contexts.sort(key=lambda item: (item[0], -item[1], -item[2]), reverse=True)
    selected = [item[3] for item in scored_contexts[:max_contexts]]
    if not selected:
        return [], {
            "mode": "table",
            "matched_rows": 0,
            "matched_documents": len(docs),
            "enabled": True,
            "document_ids": [doc.id for doc in docs],
            "table_schema": table_schema_by_doc,
            "table_query_plan": plan_meta,
            "branch_completion_filter": branch_completion_query,
            "branch_completion_matched_rows": branch_completion_matched_rows,
            "value_filters": value_filters,
            "value_filter_matched_rows": value_filter_matched_rows,
            "group_by": group_by,
            "distinct_by": distinct_by,
            "select_columns": select_columns,
            "query_op": query_op,
        }
    if len(selected) < max_contexts:
        selected_doc_ids = list(dict.fromkeys(str(item.get("document_id") or "") for item in selected if item.get("document_id")))
        selected_headers: list[dict] = []
        seen_header_keys: set[str] = set()
        for doc_id in selected_doc_ids:
            for header in header_contexts_by_doc.get(doc_id, []):
                header_key = str(header.get("content") or header.get("sheet_name") or "")
                if header_key in seen_header_keys:
                    continue
                seen_header_keys.add(header_key)
                selected_headers.append(header)
        selected.extend(selected_headers[: max_contexts - len(selected)])

    return selected, {
        "mode": "table",
        "matched_rows": len([item for item in selected if not item.get("is_header")]),
        "matched_documents": len(docs),
        "enabled": True,
        "document_ids": [doc.id for doc in docs],
        "table_schema": table_schema_by_doc,
        "table_query_plan": plan_meta,
        "branch_completion_filter": branch_completion_query,
        "branch_completion_matched_rows": branch_completion_matched_rows,
        "value_filters": value_filters,
        "value_filter_matched_rows": value_filter_matched_rows,
        "group_by": group_by,
        "distinct_by": distinct_by,
        "select_columns": select_columns,
        "query_op": query_op,
    }
