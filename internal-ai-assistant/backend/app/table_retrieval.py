from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from .models import User
from .table_plan import CITY_EQUIVALENTS, CITY_TERMS, COLUMN_ALIASES, clean as plan_clean, compact as _compact, describe_table_query_plan, parse_table_query_plan
from .table_query import row_to_context, select_table_documents, table_rows_for_documents
from .table_schema import infer_column_semantics, semantic_columns_debug, semantic_schema_suggestions, semantic_value
from .table_schema_aliases import apply_confirmed_schema_aliases, load_table_schema_aliases, merge_schema_suggestion_status

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
    for month in re.findall(r"(?<!\d)(\d{1,2})\s*月", text):
        month_no = int(month)
        if 1 <= month_no <= 12:
            tokens.add(f"{month_no:02d}")
    return [token for token in sorted(tokens, key=len, reverse=True) if len(token) >= 2]


def _sheet_matches_month(sheet_name: str, month_tokens: list[str]) -> bool:
    sheet = _clean(sheet_name)
    if not sheet or not month_tokens:
        return False
    return any(token == sheet or token in sheet or sheet in token for token in month_tokens)


def _document_month_tokens(context: dict) -> list[str]:
    text = _context_document_text(context)
    tokens: set[str] = set()
    for year, month in re.findall(r"(20\d{2})(\d{2})", re.sub(r"\s+", "", text)):
        month_no = int(month)
        if 1 <= month_no <= 12:
            tokens.add(f"{year}{month_no:02d}")
            tokens.add(f"{year}-{month_no:02d}")
            tokens.add(f"{year}年{month_no}月")
            tokens.add(f"{year}年{month_no:02d}月")
    return [token for token in sorted(tokens, key=len, reverse=True) if len(token) >= 2]


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


def _city_equivalents(city: str) -> tuple[str, ...]:
    return CITY_EQUIVALENTS.get(city, (city,))


def _context_document_text(context: dict) -> str:
    return " ".join(
        str(context.get(key) or "")
        for key in ("document_title", "filename", "document_id")
    )


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
    return any(alias in haystack for city in city_tokens for alias in _city_equivalents(city))


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


def _row_values_for_aliases(row: dict, alias_groups: tuple[str, ...], semantic_map: dict | None = None) -> list[str]:
    values: list[str] = []
    for group in alias_groups:
        if semantic_map and group in semantic_map:
            raw_name = getattr(semantic_map[group], "raw_name", "")
            if raw_name in row:
                values.append(_clean(row.get(raw_name, "")))
        values.extend(_row_values_for_alias(row, group))
    if not values:
        values = [_clean(value) for value in row.values()]
    return list(dict.fromkeys(values))


def _row_text_for_aliases(row: dict, alias_groups: tuple[str, ...], semantic_map: dict | None = None) -> str:
    return " ".join(value for value in _row_values_for_aliases(row, alias_groups, semantic_map) if value)


def _to_comparable(value: str) -> float | str:
    text = plan_clean(value)
    numeric = re.sub(r"[^0-9.\-]", "", text)
    if numeric and numeric not in {"-", ".", "-."}:
        try:
            return float(numeric)
        except ValueError:
            pass
    return text


def _compare_values(row_value: str, expected: str, operator: str) -> bool:
    row_clean = plan_clean(row_value)
    expected_clean = plan_clean(expected)
    if operator == "eq":
        return row_clean == expected_clean
    if operator == "ne":
        return row_clean != expected_clean
    if operator == "contains":
        return expected_clean in row_clean
    if operator == "not_contains":
        return expected_clean not in row_clean
    if operator == "is_empty":
        return not row_clean
    if operator == "is_not_empty":
        return bool(row_clean)
    if operator in {"gt", "gte", "lt", "lte"}:
        left = _to_comparable(row_clean)
        right = _to_comparable(expected_clean)
        if isinstance(left, float) and isinstance(right, float):
            if operator == "gt":
                return left > right
            if operator == "gte":
                return left >= right
            if operator == "lt":
                return left < right
            return left <= right
        left_text = str(left)
        right_text = str(right)
        if operator == "gt":
            return left_text > right_text
        if operator == "gte":
            return left_text >= right_text
        if operator == "lt":
            return left_text < right_text
        return left_text <= right_text
    return expected_clean in row_clean


def _row_matches_single_filter(context: dict, item: dict[str, str]) -> bool:
    row = context.get("table_row") if isinstance(context.get("table_row"), dict) else {}
    semantic_map = context.get("table_semantic_map") if isinstance(context.get("table_semantic_map"), dict) else {}
    column = item.get("column") or ""
    operator = item.get("operator") or "contains"
    value = item.get("value") or ""
    focused_values = _row_values_for_aliases(row, (column,), semantic_map)
    combined = " ".join(value for value in focused_values if value)
    if column == "city" and operator in {"contains", "eq"} and value:
        return any(alias in combined for alias in _city_equivalents(value))
    if column == "city" and operator == "not_contains" and value:
        return not any(alias in combined for alias in _city_equivalents(value))
    if operator in {"contains", "not_contains"}:
        return _compare_values(combined, value, operator)
    if operator == "is_empty":
        return all(_compare_values(candidate, value, operator) for candidate in focused_values) if focused_values else True
    if operator == "is_not_empty":
        return any(_compare_values(candidate, value, operator) for candidate in focused_values)
    if operator == "ne":
        return all(_compare_values(candidate, value, operator) for candidate in focused_values) if focused_values else True
    return any(_compare_values(candidate, value, operator) for candidate in focused_values)


def _row_matches_filter_plan(context: dict, filters: list[dict[str, str]], logic: str = "and", groups: list[list[dict[str, str]]] | None = None) -> bool:
    resolved_groups = groups or ([filters] if filters else [])
    if not resolved_groups:
        return True
    if logic == "or":
        return any(all(_row_matches_single_filter(context, item) for item in group) for group in resolved_groups)
    return all(_row_matches_single_filter(context, item) for item in filters)


def _required_column_groups(question: str, select_columns: list[str]) -> list[str]:
    compact_question = _compact(question)
    if any(term in compact_question for term in ("统计", "平均", "均值", "汇总", "合计", "按城市", "按省", "按公司", "分城市", "分省", "分公司分别")):
        return []
    # 展示字段不等于过滤条件；这里只收窄到用户明确要求必须存在的业务字段，避免统计类问题误删记录。
    required: list[str] = []
    if "银行账户" in compact_question:
        required.append("bank_account")
    if any(term in compact_question for term in ("社保公积金账户", "社保账户", "公积金账户")):
        required.append("social_account")
    if any(term in compact_question for term in ("公积金比例", "补充公积金比例")) or ("比例" in compact_question and "公积金" in compact_question):
        required.append("fund_ratio")
    if "备注" in compact_question:
        required.append("remark")
    return list(dict.fromkeys(column for column in required if column))


def _row_has_alias_column_value(context: dict, alias_group: str) -> bool:
    row = context.get("table_row") if isinstance(context.get("table_row"), dict) else {}
    semantic_map = context.get("table_semantic_map") if isinstance(context.get("table_semantic_map"), dict) else {}
    if not row:
        return False
    if semantic_map and alias_group in semantic_map:
        raw_name = getattr(semantic_map[alias_group], "raw_name", "")
        if raw_name in row and _clean(row.get(raw_name, "")):
            return True
    for key, value in row.items():
        if _column_matches(str(key), alias_group) and _clean(value):
            return True
    return False


def _row_has_required_columns(context: dict, required_columns: list[str]) -> bool:
    return all(_row_has_alias_column_value(context, column) for column in required_columns)



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
    combined = " ".join(part for part in [sheet, row_text, row_keys, row_values, semantic_values, _context_document_text(context)] if part).lower()

    score = 0.4 - doc_rank * 0.05
    for city in _city_tokens(question):
        if any(alias.lower() in combined for alias in _city_equivalents(city)):
            score += 0.6
    month_tokens = _month_tokens(question)
    if month_tokens:
        if _sheet_matches_month(sheet, month_tokens):
            score += 8.0
        elif any(token.lower() in combined for token in month_tokens):
            score += 1.5
        else:
            score -= 1.25
    else:
        document_month_tokens = _document_month_tokens(context)
        if document_month_tokens and _sheet_matches_month(sheet, document_month_tokens):
            score += 0.35

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


def table_mode_contexts(db: Session, question: str, user: User, top_k: int = 10, knowledge_scope: str = "production") -> tuple[list[dict], dict]:
    docs = select_table_documents(db, question, user, limit=2, knowledge_scope=knowledge_scope)
    if not docs:
        return [], {
            "mode": "table",
            "matched_rows": 0,
            "matched_documents": 0,
            "enabled": True,
            "knowledge_scope": knowledge_scope,
            "table_schema": {},
            "table_schema_suggestions": {},
        }

    max_contexts = max(20, min(120, top_k * 12))
    per_doc_limit = max(80, (max_contexts // max(len(docs), 1)) * 3)
    scored_contexts: list[tuple[float, int, int, dict]] = []
    header_contexts_by_doc: dict[str, list[dict]] = {}
    table_schema_by_doc: dict[str, list[dict]] = {}
    table_schema_suggestions_by_doc: dict[str, list[dict]] = {}
    plan = parse_table_query_plan(question)
    month_tokens = plan.time_tokens or _month_tokens(question)
    year_tokens = _year_tokens(question)
    branch_completion_query = plan.branch_completion_filter
    city_tokens = [] if branch_completion_query else _city_tokens(question)
    value_filters = plan.filters
    filter_logic = plan.filter_logic
    filter_groups = plan.filter_groups
    group_by = plan.group_by
    distinct_by = plan.distinct_by
    aggregate_op = plan.aggregate_op
    measure_column = plan.measure_column
    metrics = plan.metrics
    select_columns = plan.select_columns
    sort_by = plan.sort_by
    result_limit = plan.limit
    time_grain = plan.time_grain
    time_value = plan.time_value
    query_op = plan.query_op
    required_columns = _required_column_groups(question, select_columns)
    plan_meta = plan.to_dict()
    plan_explanation = describe_table_query_plan(plan)
    aliases_by_doc: dict[str, list] = {}
    for alias in load_table_schema_aliases(db, [str(doc.id) for doc in docs]):
        aliases_by_doc.setdefault(str(alias.document_id), []).append(alias)

    for doc_rank, doc in enumerate(docs):
        rows = table_rows_for_documents(db, [doc.id], include_headers=True, limit=1000)
        raw_contexts = [row_to_context(row_doc, row) for row, row_doc in rows]
        raw_data_rows = [item for item in raw_contexts if not item.get("is_header")]
        semantic_rows = [item.get("table_row") for item in raw_data_rows if isinstance(item.get("table_row"), dict)]
        semantic_map = infer_column_semantics(semantic_rows)
        doc_id = str(doc.id)
        doc_aliases = aliases_by_doc.get(doc_id, [])
        semantic_map = apply_confirmed_schema_aliases(semantic_map, doc_aliases, semantic_rows)
        table_schema_by_doc[doc_id] = semantic_columns_debug(semantic_map)
        table_schema_suggestions_by_doc[doc_id] = merge_schema_suggestion_status(
            semantic_schema_suggestions(
                semantic_map,
                document_id=doc_id,
                document_title=getattr(doc, "title", "") or "",
            ),
            doc_aliases,
        )
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
        min_row_score = 0.2 if value_filters or aggregate_op or metrics else 0.75
        for order, context in enumerate(candidate_rows):
            score = _row_score(question, context, doc_rank)
            if score >= min_row_score:
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
        value_matched = [
            item
            for item in scored_contexts
            if _row_matches_filter_plan(item[3], value_filters, filter_logic, filter_groups)
        ]
        value_filter_matched_rows = len(value_matched)
        scored_contexts = value_matched

    branch_completion_matched_rows = 0
    if branch_completion_query:
        branch_matched = [item for item in scored_contexts if _row_matches_branch_completion(item[3])]
        branch_completion_matched_rows = len(branch_matched)
        scored_contexts = branch_matched

    required_column_matched_rows = 0
    if required_columns:
        required_matched = [item for item in scored_contexts if _row_has_required_columns(item[3], required_columns)]
        required_column_matched_rows = len(required_matched)
        if required_matched:
            scored_contexts = required_matched

    scored_contexts.sort(key=lambda item: (item[0], -item[1], -item[2]), reverse=True)
    selected = [item[3] for item in scored_contexts[:max_contexts]]
    if not selected:
        return [], {
            "mode": "table",
            "matched_rows": 0,
            "matched_documents": len(docs),
            "enabled": True,
            "knowledge_scope": knowledge_scope,
            "document_ids": [doc.id for doc in docs],
            "table_schema": table_schema_by_doc,
            "table_schema_suggestions": table_schema_suggestions_by_doc,
            "table_query_plan": plan_meta,
            "table_query_explanation": plan_explanation,
            "branch_completion_filter": branch_completion_query,
            "branch_completion_matched_rows": branch_completion_matched_rows,
            "value_filters": value_filters,
            "filter_logic": filter_logic,
            "filter_groups": filter_groups,
            "value_filter_matched_rows": value_filter_matched_rows,
            "group_by": group_by,
            "distinct_by": distinct_by,
            "aggregate_op": aggregate_op,
            "measure_column": measure_column,
            "metrics": metrics,
            "select_columns": select_columns,
            "required_columns": required_columns,
            "required_column_matched_rows": required_column_matched_rows,
            "sort_by": sort_by,
            "limit": result_limit,
            "time_grain": time_grain,
            "time_value": time_value,
            "time_tokens": month_tokens,
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
        "knowledge_scope": knowledge_scope,
        "document_ids": [doc.id for doc in docs],
        "table_schema": table_schema_by_doc,
        "table_schema_suggestions": table_schema_suggestions_by_doc,
        "table_query_plan": plan_meta,
        "table_query_explanation": plan_explanation,
        "branch_completion_filter": branch_completion_query,
        "branch_completion_matched_rows": branch_completion_matched_rows,
        "value_filters": value_filters,
        "filter_logic": filter_logic,
        "filter_groups": filter_groups,
        "value_filter_matched_rows": value_filter_matched_rows,
        "group_by": group_by,
        "distinct_by": distinct_by,
        "aggregate_op": aggregate_op,
        "measure_column": measure_column,
        "metrics": metrics,
        "select_columns": select_columns,
        "required_columns": required_columns,
        "required_column_matched_rows": required_column_matched_rows,
        "sort_by": sort_by,
        "limit": result_limit,
        "time_grain": time_grain,
        "time_value": time_value,
        "time_tokens": month_tokens,
        "query_op": query_op,
    }
