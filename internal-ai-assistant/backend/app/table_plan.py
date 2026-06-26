from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

CITY_TERMS = (
    "北京",
    "上海",
    "成都",
    "宁波",
    "北仑",
    "重庆",
    "杭州",
    "长沙",
    "西安",
    "郑州",
    "石家庄",
)

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "city": ("城市", "所在城市", "地市", "地区", "省市"),
    "province": ("省份", "省", "所在省份"),
    "company": ("公司名称", "开设公司名称", "单位名称", "分公司", "网点名称", "机构名称"),
    "bank_account": ("银行账户",),
    "social_account": ("社保公积金账户", "社保账户", "公积金账户"),
    "fund_ratio": ("公积金比例", "比例"),
    "amount": ("缴费金额", "金额", "费用", "应缴金额", "实缴金额", "付款金额", "缴款金额"),
    "status": ("当前进度", "状态", "是否完成", "完成情况", "网点状态"),
}

QUESTION_COLUMN_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("city", ("城市", "地市", "地区")),
    ("province", ("省份", "省")),
    ("company", ("公司名称", "开设公司名称", "单位名称", "分公司", "网点")),
    ("bank_account", ("银行账户",)),
    ("social_account", ("社保公积金账户", "社保账户", "公积金账户")),
    ("fund_ratio", ("公积金比例", "比例")),
    ("amount", ("缴费金额", "金额", "费用", "应缴金额", "实缴金额", "付款金额", "缴款金额")),
    ("status", ("当前进度", "状态", "是否完成", "完成情况", "网点状态")),
)

COLUMN_LABELS = {
    "city": "城市",
    "province": "省份",
    "company": "公司",
    "bank_account": "银行账户",
    "social_account": "社保公积金账户",
    "fund_ratio": "公积金比例",
    "amount": "金额",
    "status": "状态",
}

FILTER_OPERATOR_LABELS = {
    "eq": "等于",
    "ne": "不等于",
    "contains": "包含",
    "not_contains": "不包含",
    "is_empty": "为空",
    "is_not_empty": "非空",
    "gt": "大于",
    "gte": "大于等于",
    "lt": "小于",
    "lte": "小于等于",
}

_VALUE_OPERATORS: tuple[tuple[str, str], ...] = (
    ("!=", "ne"),
    ("<>", "ne"),
    ("不等于", "ne"),
    ("不是", "ne"),
    ("不为", "ne"),
    ("不包含", "not_contains"),
    ("包含", "contains"),
    (">=", "gte"),
    ("大于等于", "gte"),
    ("不小于", "gte"),
    ("<=", "lte"),
    ("小于等于", "lte"),
    ("不大于", "lte"),
    (">", "gt"),
    ("大于", "gt"),
    ("<", "lt"),
    ("小于", "lt"),
    ("=", "eq"),
    ("是", "eq"),
    ("为", "eq"),
)

_EMPTY_OPERATORS: tuple[tuple[str, str], ...] = (
    ("不能为空", "is_not_empty"),
    ("不为空", "is_not_empty"),
    ("非空", "is_not_empty"),
    ("有值", "is_not_empty"),
    ("为空", "is_empty"),
    ("空值", "is_empty"),
    ("没有值", "is_empty"),
    ("无值", "is_empty"),
)

_STOP_WORDS = (
    "并且",
    "同时",
    "而且",
    "以及",
    "且",
    "的",
    "清单",
    "名单",
    "列表",
    "明细",
    "统计",
    "有多少",
    "多少",
    "按",
    "列出",
    "展示",
)


@dataclass(slots=True)
class TableQueryPlan:
    query_op: str = "retrieve"
    filters: list[dict[str, str]] = field(default_factory=list)
    filter_logic: str = "and"
    filter_groups: list[list[dict[str, str]]] = field(default_factory=list)
    select_columns: list[str] = field(default_factory=list)
    group_by: str = ""
    distinct_by: str = ""
    aggregate_op: str = ""
    measure_column: str = ""
    sort_by: str = ""
    limit: int = 20
    branch_completion_filter: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def legacy_meta(self) -> dict[str, Any]:
        return {
            "value_filters": self.filters,
            "filter_logic": self.filter_logic,
            "filter_groups": self.filter_groups,
            "group_by": self.group_by,
            "distinct_by": self.distinct_by,
            "aggregate_op": self.aggregate_op,
            "measure_column": self.measure_column,
            "select_columns": self.select_columns,
            "query_op": self.query_op,
            "branch_completion_filter": self.branch_completion_filter,
        }


def clean(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def is_branch_completion_query(question: str) -> bool:
    text = compact(question)
    branch_hit = any(term in text for term in ("北仑", "分公司", "开设公司", "公司名称", "开了多少", "开设了多少"))
    bank_hit = any(term in text for term in ("银行账户", "银行"))
    social_hit = any(term in text for term in ("社保公积金账户", "社保公积金", "社保账户", "公积金账户"))
    ratio_hit = any(term in text for term in ("公积金比例", "比例"))
    complete_hit = any(term in text for term in ("全部", "全都", "都", "完成", "开设完成", "开具完成"))
    return branch_hit and bank_hit and social_hit and ratio_hit and complete_hit


def _filter_key(column: str, operator: str, value: str) -> tuple[str, str, str]:
    return (column, operator, clean(value))


def _normalize_filter(column: str, value: str = "", operator: str = "contains") -> dict[str, str]:
    normalized = {"column": column, "operator": operator}
    cleaned_value = clean(value)
    if operator not in {"is_empty", "is_not_empty"}:
        normalized["value"] = cleaned_value
    return normalized


def _extract_value_after_operator(text: str, start_index: int) -> str:
    value = clean(text[start_index:])
    cut_at = len(value)
    for stop_word in _STOP_WORDS:
        index = value.find(stop_word)
        if index > 0:
            cut_at = min(cut_at, index)
    return clean(value[:cut_at])


def literal_after_marker(compact_question: str, marker: str) -> str:
    match = re.search(rf"{re.escape(marker)}(?:是|为|=|：|:)([^，。；;、?？]+)", compact_question)
    if not match:
        return ""
    return _extract_value_after_operator(match.group(1), 0)


def _parse_marker_filters(text: str, alias: str, marker: str) -> list[dict[str, str]]:
    filters: list[dict[str, str]] = []
    start = 0
    while True:
        marker_index = text.find(marker, start)
        if marker_index < 0:
            return filters
        start = marker_index + len(marker)
        tail = text[start:]

        parsed: dict[str, str] | None = None
        for phrase, operator in _EMPTY_OPERATORS:
            if tail.startswith(phrase):
                parsed = _normalize_filter(alias, operator=operator)
                break

        if parsed is None:
            for phrase, operator in _VALUE_OPERATORS:
                if not tail.startswith(phrase):
                    continue
                value = _extract_value_after_operator(tail, len(phrase))
                if value:
                    parsed = _normalize_filter(alias, value, operator)
                break
        if parsed:
            filters.append(parsed)
        # A marker appearing as a selected/display column should not become a filter.


def _dedupe_filters(filters: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in filters:
        key = _filter_key(item.get("column", ""), item.get("operator", "contains"), item.get("value", ""))
        if key in seen:
            continue
        if item.get("operator") not in {"is_empty", "is_not_empty"} and not item.get("value"):
            continue
        seen.add(key)
        result.append(item)
    return result


def _split_or_segments(text: str) -> list[str]:
    return [segment for segment in re.split(r"(?:或者|或|OR|or)", text) if segment]


def _parse_filters_from_text(text: str, include_city_tokens: bool = True) -> list[dict[str, str]]:
    filters: list[dict[str, str]] = []
    for alias, markers in QUESTION_COLUMN_TERMS:
        for marker in markers:
            filters.extend(_parse_marker_filters(text, alias, marker))

    if include_city_tokens:
        for city in CITY_TERMS:
            if city in text and not any(item.get("column") == "city" and item.get("value") == city for item in filters):
                filters.append(_normalize_filter("city", city, "contains"))
    return _dedupe_filters(filters)


def parse_value_filters(question: str, include_quoted_company: bool = True) -> list[dict[str, str]]:
    filters, _logic, _groups = parse_filter_expression(question, include_quoted_company=include_quoted_company)
    return filters


def parse_filter_expression(
    question: str,
    include_quoted_company: bool = True,
) -> tuple[list[dict[str, str]], str, list[list[dict[str, str]]]]:
    text = compact(question)
    or_segments = _split_or_segments(text)
    groups: list[list[dict[str, str]]] = []
    if len(or_segments) > 1:
        previous_context: list[dict[str, str]] = []
        for segment in or_segments:
            current = _parse_filters_from_text(segment, include_city_tokens=True)
            inherited: list[dict[str, str]] = []
            current_columns = {item.get("column") for item in current}
            for item in previous_context:
                if item.get("column") not in current_columns:
                    inherited.append(item)
            group = _dedupe_filters(inherited + current)
            if group:
                groups.append(group)
            previous_context = group or previous_context
        filters = _dedupe_filters([item for group in groups for item in group])
        return filters, "or", groups

    filters = _parse_filters_from_text(text, include_city_tokens=True)

    if include_quoted_company:
        quoted_values = re.findall(r"[‘'\"]([^‘’'\"]{1,30})[’'\"]", question or "")
        for value in quoted_values:
            if any(marker in text for marker in ("公司", "单位", "网点", "分公司")):
                filters.append(_normalize_filter("company", value, "contains"))

    filters = _dedupe_filters(filters)
    return filters, "and", [filters] if filters else []


def group_by_column(question: str) -> str:
    text = compact(question)
    if any(term in text for term in ("按城市", "各城市", "每个城市", "分城市", "城市分布", "城市分别")):
        return "city"
    if any(term in text for term in ("按省份", "各省", "每个省", "分省", "省份分布")):
        return "province"
    if any(term in text for term in ("按公司", "各公司", "每家公司", "分公司分别")):
        return "company"
    return ""


def distinct_column(question: str) -> str:
    text = compact(question)
    if any(term in text for term in ("多少个城市", "多少座城市", "几个城市", "哪些城市")):
        return "city"
    if any(term in text for term in ("多少家公司", "多少个公司", "几家公司")):
        return "company"
    return ""


def select_columns(question: str, value_filters: list[dict[str, str]] | None = None) -> list[str]:
    text = compact(question)
    for item in value_filters or []:
        column = item.get("column") or ""
        value = item.get("value") or ""
        operator = item.get("operator") or "contains"
        if not column:
            continue
        for alias in COLUMN_ALIASES.get(column, ()):  # remove filter expressions before detecting projections
            if operator in {"is_empty", "is_not_empty"}:
                for phrase, empty_operator in _EMPTY_OPERATORS:
                    if empty_operator == operator:
                        text = text.replace(f"{alias}{phrase}", "")
                continue
            if not value:
                continue
            for phrase, value_operator in _VALUE_OPERATORS:
                if value_operator == operator:
                    text = re.sub(rf"{re.escape(alias)}{re.escape(phrase)}{re.escape(value)}", "", text)

    candidates: list[tuple[int, str]] = []
    seen: set[str] = set()
    for group, aliases in COLUMN_ALIASES.items():
        positions = [text.find(alias) for alias in aliases if alias and text.find(alias) >= 0]
        if positions and group not in seen:
            seen.add(group)
            candidates.append((min(positions), group))
    candidates.sort(key=lambda item: item[0])
    return [group for _position, group in candidates[:8]]


def aggregate_operation(question: str) -> str:
    text = compact(question)
    if any(term in text for term in ("总和", "合计", "求和", "汇总金额", "金额汇总", "sum")):
        return "sum"
    return ""


def measure_column(question: str) -> str:
    text = compact(question)
    measure_candidates = ("amount", "fund_ratio")
    best: tuple[int, str] | None = None
    for column in measure_candidates:
        for alias in COLUMN_ALIASES.get(column, ()):
            position = text.find(compact(alias))
            if position >= 0 and (best is None or position < best[0]):
                best = (position, column)
    return best[1] if best else ""


def query_operation(question: str, group_by: str = "", distinct_by: str = "", aggregate_op: str = "") -> str:
    text = compact(question)
    if aggregate_op:
        return f"{aggregate_op}_group" if group_by else aggregate_op
    if group_by:
        return "group_count"
    if distinct_by:
        return "distinct_count" if any(term in text for term in ("多少", "几个", "几家")) else "distinct_list"
    if any(term in text for term in ("列出", "清单", "名单", "明细", "有哪些", "哪些")):
        return "list"
    if any(term in text for term in ("多少", "几个", "几家", "统计", "汇总", "总数", "数量")):
        return "count"
    return "retrieve"


def format_filter_condition(item: dict[str, Any]) -> str:
    column = str(item.get("column") or "")
    operator = str(item.get("operator") or "contains")
    value = clean(item.get("value", ""))
    label = COLUMN_LABELS.get(column, column or "字段")
    op_label = FILTER_OPERATOR_LABELS.get(operator, operator)
    if operator in {"is_empty", "is_not_empty"}:
        return f"{label} {op_label}"
    return f"{label} {op_label} {value}"


def format_filter_groups(groups: list[list[dict[str, Any]]] | None, logic: str = "and") -> str:
    resolved_groups = groups or []
    if not resolved_groups:
        return ""
    formatted_groups: list[str] = []
    for group in resolved_groups:
        parts = [format_filter_condition(item) for item in group]
        if parts:
            formatted_groups.append(" 且 ".join(parts))
    if logic == "or" and len(formatted_groups) > 1:
        return "；或 ".join(formatted_groups)
    return "；".join(formatted_groups)


def parse_table_query_plan(question: str, *, branch_completion: bool | None = None, include_quoted_company: bool = True) -> TableQueryPlan:
    branch = is_branch_completion_query(question) if branch_completion is None else branch_completion
    if branch:
        return TableQueryPlan(query_op="branch_completion_count", branch_completion_filter=True)

    filters, filter_logic, filter_groups = parse_filter_expression(question, include_quoted_company=include_quoted_company)
    group_by = group_by_column(question)
    distinct_by = distinct_column(question)
    aggregate_op = aggregate_operation(question)
    measure = measure_column(question) if aggregate_op else ""
    selected = select_columns(question, filters)
    return TableQueryPlan(
        query_op=query_operation(question, group_by, distinct_by, aggregate_op),
        filters=filters,
        filter_logic=filter_logic,
        filter_groups=filter_groups,
        select_columns=selected,
        group_by=group_by,
        distinct_by=distinct_by,
        aggregate_op=aggregate_op,
        measure_column=measure,
    )
