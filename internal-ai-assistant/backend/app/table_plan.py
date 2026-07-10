from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

CITY_TERMS = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "成都",
    "宁波",
    "北仑",
    "宁波北仑",
    "重庆",
    "杭州",
    "长沙",
    "西安",
    "郑州",
    "石家庄",
    "南京",
    "苏州",
    "武汉",
    "天津",
    "合肥",
    "南昌",
    "厦门",
    "福州",
    "青岛",
    "济南",
    "太原",
    "沈阳",
    "大连",
    "长春",
    "哈尔滨",
    "昆明",
    "贵阳",
    "海口",
    "三亚",
    "兰州",
    "乌鲁木齐",
    "呼和浩特",
)

CITY_EQUIVALENTS: dict[str, tuple[str, ...]] = {
    # 业务资料里“北仑派单截止时间”文件的表内城市写作“宁波”，
    # 另一个北仑进度表写作“宁波北仑”；检索时按同一业务区域处理。
    "北仑": ("北仑", "宁波北仑", "宁波"),
    "宁波北仑": ("宁波北仑", "北仑", "宁波"),
}

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "city": ("城市", "所在城市", "地市", "地区", "省市"),
    "province": ("省份", "省", "所在省份"),
    "company": ("公司名称", "开设公司名称", "单位名称", "分公司", "网点名称", "机构名称", "名称"),
    "branch_company": ("开设公司名称", "当前进度-4.开设公司名称", "分公司名称"),
    "bank_account": ("银行账户", "银行账户是否开具完成", "开户状态"),
    "social_account": ("社保公积金账户", "社保账户", "公积金账户", "社保公积金账户是否开具完成"),
    "fund_ratio": ("公积金比例", "补充公积金比例", "缴存比例", "比例"),
    "remark": ("备注", "备注要求", "说明", "注意事项", "资料", "材料", "需提供", "需要提供", "提供哪些"),
    "backend_contact": ("后道对接人", "对接人", "操作人", "办理人", "经办人"),
    "social_rule": ("操作规则-社保", "社保操作规则", "社保规则"),
    "medical_rule": ("操作规则-医保", "医保操作规则", "医保规则"),
    "fund_rule": ("操作规则-公积金", "公积金操作规则", "公积金规则"),
    "social_deadline": ("截止时间-社保", "社保截止时间", "社保截止", "社保派单截止"),
    "medical_deadline": ("截止时间-医保", "医保截止时间", "医保截止", "医保派单截止"),
    "fund_deadline": ("截止时间-公积金", "公积金截止时间", "公积金截止", "公积金派单截止"),
    "social_payment_time": ("预计缴款时间-社保", "社保预计缴款时间", "社保缴款时间"),
    "fund_payment_time": ("预计缴款时间-公积金", "公积金预计缴款时间", "公积金缴款时间"),
    "amount": ("缴费金额", "金额", "费用", "应缴金额", "实缴金额", "付款金额", "缴款金额"),
    "status": ("当前进度", "状态", "是否完成", "完成情况", "网点状态"),
}

QUESTION_COLUMN_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("city", ("城市", "地市", "地区")),
    ("province", ("省份", "省")),
    ("company", ("公司名称", "开设公司名称", "单位名称", "分公司", "网点")),
    ("bank_account", ("银行账户",)),
    ("social_account", ("社保公积金账户", "社保账户", "公积金账户")),
    ("fund_ratio", ("公积金比例", "补充公积金比例", "比例")),
    ("remark", ("备注", "备注要求", "说明", "注意事项", "资料", "材料", "需提供", "需要提供", "提供哪些")),
    ("backend_contact", ("后道对接人", "对接人", "操作人", "办理人", "经办人")),
    ("social_rule", ("社保操作规则", "操作规则-社保")),
    ("medical_rule", ("医保操作规则", "操作规则-医保")),
    ("fund_rule", ("公积金操作规则", "操作规则-公积金")),
    ("social_deadline", ("社保截止时间", "截止时间-社保")),
    ("medical_deadline", ("医保截止时间", "截止时间-医保")),
    ("fund_deadline", ("公积金截止时间", "截止时间-公积金")),
    ("social_payment_time", ("社保预计缴款时间", "预计缴款时间-社保")),
    ("fund_payment_time", ("公积金预计缴款时间", "预计缴款时间-公积金")),
    ("amount", ("缴费金额", "金额", "费用", "应缴金额", "实缴金额", "付款金额", "缴款金额")),
    ("status", ("当前进度", "状态", "是否完成", "完成情况", "网点状态")),
)

COLUMN_LABELS = {
    "city": "城市",
    "province": "省份",
    "company": "公司",
    "branch_company": "分公司名称",
    "bank_account": "银行账户",
    "social_account": "社保公积金账户",
    "fund_ratio": "公积金比例",
    "remark": "备注",
    "backend_contact": "后道对接人",
    "social_rule": "社保操作规则",
    "medical_rule": "医保操作规则",
    "fund_rule": "公积金操作规则",
    "social_deadline": "社保截止时间",
    "medical_deadline": "医保截止时间",
    "fund_deadline": "公积金截止时间",
    "social_payment_time": "社保预计缴款时间",
    "fund_payment_time": "公积金预计缴款时间",
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
    "is_concrete": "为有效值",
    "gt": "大于",
    "gte": "大于等于",
    "lt": "小于",
    "lte": "小于等于",
}

QUERY_OPERATION_LABELS = {
    "branch_completion_count": "分公司完成度统计",
    "group_count": "分组计数",
    "multi_metric_group": "分组多指标统计",
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
}

AGGREGATE_OPERATION_LABELS = {
    "sum": "汇总",
    "avg": "平均值",
    "max": "最大值",
    "min": "最小值",
}

_VALUE_OPERATORS: tuple[tuple[str, str], ...] = (
    ("!=", "ne"),
    ("<>", "ne"),
    ("不等于", "ne"),
    ("不是", "ne"),
    ("不为", "ne"),
    ("不包含", "not_contains"),
    ("不含", "not_contains"),
    ("包含", "contains"),
    ("含有", "contains"),
    ("含", "contains"),
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
    metrics: list[dict[str, str]] = field(default_factory=list)
    sort_by: str = ""
    limit: int = 20
    time_grain: str = ""
    time_value: str = ""
    time_tokens: list[str] = field(default_factory=list)
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
            "metrics": self.metrics,
            "select_columns": self.select_columns,
            "sort_by": self.sort_by,
            "limit": self.limit,
            "time_grain": self.time_grain,
            "time_value": self.time_value,
            "time_tokens": self.time_tokens,
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
    global_intent = any(term in text for term in ("多少家", "多少个", "有多少", "几家", "几个", "哪些", "哪几", "列出", "名单", "清单", "统计", "全部分公司", "所有分公司", "各分公司"))
    concrete_city_hit = any(city in text for city in CITY_TERMS)
    strong_completion_count_intent = global_intent and any(term in text for term in ("多少家分公司", "开设了多少家", "统计", "为准"))
    if concrete_city_hit and not ("北仑" in text and strong_completion_count_intent):
        return False
    return branch_hit and bank_hit and social_hit and ratio_hit and complete_hit


def _filter_key(column: str, operator: str, value: str) -> tuple[str, str, str]:
    return (column, operator, clean(value))


_QUESTION_VALUE_WORDS = (
    "多少",
    "多少？",
    "是多少",
    "是多少？",
    "是什么",
    "是什么？",
    "什么",
    "什么？",
    "哪天",
    "哪天？",
    "几号",
    "几号？",
    "什么时候",
    "什么时候？",
    "谁",
    "谁？",
    "哪位",
    "哪位？",
    "吗",
    "吗？",
)


def _is_question_value(value: str) -> bool:
    text = clean(value).strip(" ？?")
    if not text:
        return True
    normalized_words = {item.strip(" ？?") for item in _QUESTION_VALUE_WORDS}
    if text in normalized_words:
        return True
    # “状态是什么？公积金比例...”这类疑问句里，“是/为”不是过滤操作符。
    if text.startswith(("什么", "多少", "哪", "谁", "几", "是否", "是不是", "有没有", "有无")):
        return True
    if any(mark in text for mark in ("?", "？")) and any(word in text for word in normalized_words):
        return True
    return False


def _normalize_filter(column: str, value: str = "", operator: str = "contains") -> dict[str, str]:
    normalized = {"column": column, "operator": operator}
    cleaned_value = clean(value).strip(" \t\r\n'\"‘’“”《》")
    if operator not in {"is_empty", "is_not_empty", "is_concrete"}:
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
            # “是否/是不是” are yes-no question words, not equality filters like 字段=否...
            if tail.startswith(("是否", "是不是")):
                parsed = None
            else:
                for phrase, operator in _VALUE_OPERATORS:
                    if not tail.startswith(phrase):
                        continue
                    value = _extract_value_after_operator(tail, len(phrase))
                    if value and not _is_question_value(value):
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
        if item.get("operator") not in {"is_empty", "is_not_empty", "is_concrete"} and not item.get("value"):
            continue
        seen.add(key)
        result.append(item)
    return result


def _split_or_segments(text: str) -> list[str]:
    return [segment for segment in re.split(r"(?:或者|或|OR|or)", text) if segment]


_BRANCH_OPENING_TERMS = (
    "开了分公司",
    "开设了分公司",
    "开设分公司",
    "分公司开设",
    "开分公司",
    "有分公司",
    "设立分公司",
    "成立分公司",
)

_CITY_LIST_INTENT_TERMS = (
    "哪些城市",
    "哪几个城市",
    "几个城市",
    "多少个城市",
    "多少座城市",
    "在哪些城市",
)

_CURRENT_OPENING_TERMS = (
    "目前",
    "现在",
    "当前",
    "已开设",
    "已开通",
    "已经开设",
    "已经开通",
    "开设完成",
    "开具完成",
)

_TABLE_ANALYSIS_SCOPE_TERMS = (
    "分析",
    "总结",
    "归纳",
    "建议",
    "风险",
    "异常",
    "原因",
    "为什么",
    "评估",
    "评价",
    "对比",
    "趋势",
    "推进",
    "下一步",
)

_BRANCH_PROGRESS_SCOPE_TERMS = (
    "分公司开设进度",
    "分公司开设情况",
    "开设进度",
    "开设情况",
    "开设最新进度表",
)


def _has_branch_opening_intent(text: str) -> bool:
    compact_text = compact(text)
    if any(term in compact_text for term in _BRANCH_OPENING_TERMS):
        return True
    # “开了多少个城市的分公司 / 开了哪些城市的分公司”中，“开了”和“分公司”
    # 往往被城市数量词隔开，不能只依赖连续短语“开了分公司”。
    return "分公司" in compact_text and any(term in compact_text for term in ("开了", "开设", "已开", "开通", "设立", "成立"))


def city_terms_are_scope(question: str) -> bool:
    """Return True when city-like words name the business scope rather than row city filters."""
    compact_text = compact(question)
    if not compact_text:
        return False
    has_city_list_intent = any(term in compact_text for term in _CITY_LIST_INTENT_TERMS)
    if has_city_list_intent and _has_branch_opening_intent(compact_text):
        return True
    has_analysis_intent = any(term in compact_text for term in _TABLE_ANALYSIS_SCOPE_TERMS)
    has_progress_scope = any(term in compact_text for term in _BRANCH_PROGRESS_SCOPE_TERMS)
    return has_analysis_intent and has_progress_scope and _has_branch_opening_intent(compact_text)


def _requires_opened_branch_status(text: str) -> bool:
    compact_text = compact(text)
    if not compact_text or not _has_branch_opening_intent(compact_text):
        return False
    # 「多少个城市开设了分公司」这类城市清单/范围问句里，「开设了」描述的是业务范围
    # （已设分公司的城市），而非要求银行+社保均完成；此时口径为名称有效即计入，
    # 不叠加完成度过滤，否则会把 Q1(应 36) 收窄成 Q2(银行+社保都办好=29)。
    if city_terms_are_scope(compact_text):
        return False
    return any(term in compact_text for term in _CURRENT_OPENING_TERMS) or any(term in compact_text for term in ("开了", "开设了"))


def _text_for_city_detection(text: str) -> str:
    if city_terms_are_scope(text):
        return ""
    # “北仑分公司/北仑进度表/北仑表” often refers to the document name, not a row city.
    cleaned = text
    for pattern in (r"北仑分公司", r"北仑(?:开设)?(?:最新)?进度表", r"北仑表"):
        cleaned = re.sub(pattern, "", cleaned)
    return cleaned


def _collapse_city_filters(filters: list[dict[str, str]]) -> list[dict[str, str]]:
    city_filters = [item for item in filters if item.get("column") == "city" and item.get("operator") == "contains"]
    if len(city_filters) <= 1:
        return filters
    values = [str(item.get("value") or "") for item in city_filters]
    redundant = {value for value in values if any(value != other and value in other for other in values)}
    if not redundant:
        return filters
    return [item for item in filters if not (item.get("column") == "city" and item.get("operator") == "contains" and str(item.get("value") or "") in redundant)]


_EXPLICIT_BRANCH_NAME_BASIS_TERMS = (
    "以有分公司名称为准",
    "以有分公司名称的为准",
    "有分公司名称为准",
    "有分公司名称的为准",
    "分公司名称为准",
    "以有开设公司名称为准",
    "有开设公司名称",
    "开设公司名称为准",
)


def _has_explicit_branch_name_basis(text: str) -> bool:
    """用户显式声明「以有分公司名称为准」时，判定口径仅为名称有效，不叠加银行/社保状态。"""
    return any(term in compact(text) for term in _EXPLICIT_BRANCH_NAME_BASIS_TERMS)


def _requires_concrete_branch_company_name(text: str) -> bool:
    compact_text = compact(text)
    if not compact_text:
        return False
    if city_terms_are_scope(compact_text) and any(term in compact_text for term in _CITY_LIST_INTENT_TERMS):
        return True
    if _has_explicit_branch_name_basis(compact_text):
        return True
    has_analysis_intent = any(term in compact_text for term in _TABLE_ANALYSIS_SCOPE_TERMS)
    has_progress_scope = any(term in compact_text for term in _BRANCH_PROGRESS_SCOPE_TERMS)
    has_opened_basis = any(term in compact_text for term in (*_CURRENT_OPENING_TERMS, "开了", "开设了", "为准"))
    if has_analysis_intent and has_progress_scope and not has_opened_basis:
        return False
    return _has_branch_opening_intent(compact_text)


_NAME_FILL_NEGATIVE_TERMS = ("还没填", "还未填", "没有填", "尚未填", "没填", "未填")


def _requires_empty_branch_company_name(text: str) -> bool:
    """'还没填开设公司名称' 这类否定填写口径，映射为 branch_company is_empty。
    与 _requires_branch_company_name(正向已填=非空) 互斥，避免 Q3(已填)/Q4(没填) 撞车。"""
    compact_text = compact(text)
    if not compact_text:
        return False
    branch_name = any(term in compact_text for term in ("分公司名称", "开设公司名称", "公司名称"))
    return branch_name and any(term in compact_text for term in _NAME_FILL_NEGATIVE_TERMS)


def _requires_branch_company_name(text: str) -> bool:
    compact_text = compact(text)
    if not compact_text:
        return False
    if _requires_empty_branch_company_name(compact_text):
        return False
    if _requires_concrete_branch_company_name(compact_text):
        return True
    branch_name = any(term in compact_text for term in ("分公司名称", "开设公司名称"))
    return branch_name and any(term in compact_text for term in ("有", "非空", "不为空", "为准"))


_COMPLETION_POSITIVE_TERMS = ("办好", "办了", "办完", "完成", "开好", "开具完成", "开通", "搞定", "弄好")
_COMPLETION_NEGATIVE_TERMS = ("还没", "没办", "未办", "没有办", "没完成", "未完成", "没开", "未开", "尚未", "还未")
_COMPLETION_SUBJECTS: tuple[tuple[str, str], ...] = (
    ("bank_account", "银行"),
    ("social_account", "社保"),
)


_COMPLETION_CLAUSE_BREAKS = ("但是", "但", "可是", "然而", "却", "不过")


def _trim_at_clause_break(segment: str) -> str:
    """在转折连词处截断，使银行/社保完成度只读本从句。
    '银行社保都办好了但还没填名称' 中，'还没' 属于名称从句，不能污染前半完成度极性。"""
    cut = len(segment)
    for brk in _COMPLETION_CLAUSE_BREAKS:
        index = segment.find(brk)
        if index >= 0:
            cut = min(cut, index)
    return segment[:cut]


def _completion_polarity(segment: str) -> str | None:
    """否定优先：'还没办好' 里既含'还没'又含'办好'，判为 ne。"""
    if any(term in segment for term in _COMPLETION_NEGATIVE_TERMS):
        return "ne"
    if any(term in segment for term in _COMPLETION_POSITIVE_TERMS):
        return "eq"
    return None


def _parse_completion_status_filters(text: str) -> list[dict[str, str]]:
    """解析'银行/社保 办好了/还没办好'这类完成度口径，映射为 bank_account/social_account 的 eq/ne 是。"""
    # “银行账户是否开具完成？/社保开好了吗？”是询问单条状态的疑问句，不是把状态当过滤条件；
    # 命中 是否/吗/是不是/有没有 时按查询处理，避免把 retrieve 误当成 eq 是 过滤。
    if any(term in text for term in ("是否", "是不是", "有没有", "有无")) or text.rstrip(" ？?").endswith("吗"):
        return []
    present = [(column, marker, text.find(marker)) for column, marker in _COMPLETION_SUBJECTS]
    present = [item for item in present if item[2] >= 0]
    if not present:
        return []
    if not any(term in text for term in _COMPLETION_POSITIVE_TERMS + _COMPLETION_NEGATIVE_TERMS):
        return []
    present.sort(key=lambda item: item[2])
    trailing = _completion_polarity(_trim_at_clause_break(text[present[-1][2]:]))
    result: list[dict[str, str]] = []
    for index, (column, marker, position) in enumerate(present):
        start = position + len(marker)
        end = present[index + 1][2] if index + 1 < len(present) else len(text)
        window = _trim_at_clause_break(text[start:end])
        before_start = present[index - 1][2] if index > 0 else 0
        before = _trim_at_clause_break(text[before_start:position])
        polarity = _completion_polarity(window) or _completion_polarity(before) or trailing
        if polarity:
            result.append(_normalize_filter(column, "是", polarity))
    return result


def _parse_filters_from_text(text: str, include_city_tokens: bool = True) -> list[dict[str, str]]:
    filters: list[dict[str, str]] = []
    for alias, markers in QUESTION_COLUMN_TERMS:
        for marker in markers:
            filters.extend(_parse_marker_filters(text, alias, marker))

    for completion_filter in _parse_completion_status_filters(text):
        if not any(item.get("column") == completion_filter.get("column") for item in filters):
            filters.append(completion_filter)

    if include_city_tokens:
        city_text = _text_for_city_detection(text)
        for city in sorted(CITY_TERMS, key=len, reverse=True):
            if city in city_text and not any(item.get("column") == "city" and item.get("value") == city for item in filters):
                filters.append(_normalize_filter("city", city, "contains"))
    if _requires_empty_branch_company_name(text):
        filters.append(_normalize_filter("branch_company", operator="is_empty"))
    elif _requires_branch_company_name(text):
        operator = "is_concrete" if _requires_concrete_branch_company_name(text) else "is_not_empty"
        filters.append(_normalize_filter("branch_company", operator=operator))
    if _requires_opened_branch_status(text) and not _has_explicit_branch_name_basis(text):
        filters.append(_normalize_filter("bank_account", "是", "eq"))
        filters.append(_normalize_filter("social_account", "是", "eq"))
    return _collapse_city_filters(_dedupe_filters(filters))


def parse_value_filters(question: str, include_quoted_company: bool = True) -> list[dict[str, str]]:
    filters, _logic, _groups = parse_filter_expression(question, include_quoted_company=include_quoted_company)
    return filters


def parse_filter_expression(
    question: str,
    include_quoted_company: bool = True,
) -> tuple[list[dict[str, str]], str, list[list[dict[str, str]]]]:
    text = compact(question)
    groups: list[list[dict[str, str]]] = []

    # 引号内公司名 + 或/或者：必须在 _split_or_segments 之前处理，
    # 否则 '或' 会把 "总部"/"企业服务" 拆成两段，引号被割裂后无法匹配。
    if include_quoted_company:
        quoted_values = re.findall(r"['\"‘’“”]([^'\"‘’“”]{1,30})['\"‘’“”]", question or "")
        has_company_context = any(marker in text for marker in ("公司", "单位", "网点", "分公司", "名称"))
        has_or_logic = any(term in text for term in ("或者", "或"))
        if quoted_values and has_company_context and has_or_logic and len(quoted_values) > 1:
            base_filters = _parse_filters_from_text(text, include_city_tokens=True)
            base_filters = [item for item in base_filters if item.get("column") != "company"]
            or_groups = [_dedupe_filters(base_filters + [_normalize_filter("company", value, "contains")]) for value in quoted_values]
            all_filters = _dedupe_filters([item for group in or_groups for item in group])
            return all_filters, "or", or_groups

    # “名称含A或B”这类未加引号的字段包含列举：同样必须在 _split_or_segments 之前处理，
    # 否则 '或' 会把 A、B 拆成两段，第二段丢失字段上下文（'企业服务' 落不到 company）。
    if include_quoted_company:
        company_markers = tuple(dict.fromkeys(COLUMN_ALIASES["company"] + COLUMN_ALIASES["branch_company"]))
        marker_pattern = "|".join(re.escape(marker) for marker in sorted(company_markers, key=len, reverse=True))
        contains_match = re.search(rf"(?:{marker_pattern})(?:含|包含)([^，。；;、?？]+)", text)
        if contains_match:
            raw_values = _extract_value_after_operator(contains_match.group(1), 0)
            parts = [clean(part).strip(" \t\r\n'\"‘’“”《》") for part in _split_or_segments(raw_values)]
            parts = [part for part in parts if part]
            base_filters = _parse_filters_from_text(text, include_city_tokens=True)
            base_filters = [item for item in base_filters if item.get("column") != "company"]
            if len(parts) > 1 and any(term in text for term in ("或者", "或")):
                or_groups = [_dedupe_filters(base_filters + [_normalize_filter("company", value, "contains")]) for value in parts]
                all_filters = _dedupe_filters([item for group in or_groups for item in group])
                return all_filters, "or", or_groups
            if len(parts) == 1:
                merged = _dedupe_filters(base_filters + [_normalize_filter("company", parts[0], "contains")])
                return merged, "and", [merged] if merged else []

    or_segments = _split_or_segments(text)
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
    city_filters = [item for item in filters if item.get("column") == "city" and item.get("operator") == "contains"]
    if len(city_filters) > 1 and any(term in text for term in ("是否包含", "是否包括", "有没有", "是否有", "包含")):
        shared = [item for item in filters if item.get("column") != "city"]
        groups = [_dedupe_filters(shared + [city_filter]) for city_filter in city_filters]
        filters = _dedupe_filters([item for group in groups for item in group])
        return filters, "or", groups

    if include_quoted_company:
        quoted_values = re.findall(r"['\"‘’“”]([^'\"‘’“”]{1,30})['\"‘’“”]", question or "")
        if quoted_values:
            # Check if question mentions company/name fields
            has_company_context = any(marker in text for marker in ("公司", "单位", "网点", "分公司", "名称"))
            # Check if question has OR logic (或/或者)
            has_or_logic = any(term in text for term in ("或", "或者"))

            if has_company_context:
                if has_or_logic and len(quoted_values) > 1:
                    # Multiple quoted values with OR logic: create separate filter groups
                    or_groups = []
                    base_filters = [f for f in filters if f.get("column") != "company"]
                    for value in quoted_values:
                        group = base_filters + [_normalize_filter("company", value, "contains")]
                        or_groups.append(group)
                    if or_groups:
                        all_filters = _dedupe_filters([item for group in or_groups for item in group])
                        return all_filters, "or", or_groups
                else:
                    # Single quoted value or multiple without OR: add as AND conditions
                    for value in quoted_values:
                        filters.append(_normalize_filter("company", value, "contains"))

    filters = _dedupe_filters(filters)
    return filters, "and", [filters] if filters else []


def group_by_column(question: str) -> str:
    text = compact(question)
    ranking_intent = any(term in text for term in ("最多", "最少", "倒数", "top", "bottom")) or bool(re.search(r"(?:排名)?前(?:\d+|几|十|[一二三四五六七八九])", text))
    if any(term in text for term in ("按城市", "各城市", "每个城市", "分城市", "城市分布", "城市分别")) or (ranking_intent and "城市" in text):
        return "city"
    if any(term in text for term in ("按省份", "各省", "每个省", "分省", "省份分布")) or (ranking_intent and "省" in text):
        return "province"
    if any(term in text for term in ("按公司", "各公司", "每家公司")) or (ranking_intent and any(term in text for term in ("公司", "单位", "网点", "机构"))):
        return "company"
    return ""


def distinct_column(question: str) -> str:
    text = compact(question)
    if any(term in text for term in ("多少个城市", "多少座城市", "几个城市", "哪些城市", "城市有多少", "城市有几")):
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
            if operator in {"is_empty", "is_not_empty", "is_concrete"}:
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
    selected = [group for _position, group in candidates[:8]]
    if "银行" in text and "账户" in text and "bank_account" not in selected:
        selected.append("bank_account")
    shared_deadline = any(term in text for term in ("三项截止", "三项派单截止")) or (
        any(term in text for term in ("截止日", "截止时间", "派单截止"))
        and sum(subject in text for subject in ("社保", "医保", "公积金")) >= 2
    )
    if shared_deadline:
        selected = [
            *[group for group in selected if group not in {"social_deadline", "medical_deadline", "fund_deadline"}],
            "social_deadline",
            "medical_deadline",
            "fund_deadline",
        ]
    return selected[:8]


def aggregate_operation(question: str) -> str:
    text = compact(question)
    if any(term in text for term in ("平均值", "平均", "均值", "avg", "average")):
        return "avg"
    if any(term in text for term in ("最大值", "最大", "最高值", "最高", "max", "maximum")):
        return "max"
    if any(term in text for term in ("最小值", "最小", "最低值", "最低", "min", "minimum")):
        return "min"
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


def metric_specs(question: str, aggregate_op: str = "", measure: str = "") -> list[dict[str, str]]:
    text = compact(question).lower()
    metrics: list[dict[str, str]] = []

    def add_metric(op: str, column: str = "", label: str = "") -> None:
        item = {"op": op, "column": column, "label": label or COLUMN_LABELS.get(column, column or "数量")}
        if item not in metrics:
            metrics.append(item)

    count_terms = ("公司数", "公司数量", "网点数", "网点数量", "机构数", "机构数量", "数量", "多少个", "多少家")
    if any(term in text for term in count_terms):
        add_metric("count", "", "数量")
    if any(term in text for term in ("缴费金额总和", "金额总和", "金额合计", "缴费金额合计", "汇总金额", "金额汇总")):
        add_metric("sum", "amount", "金额汇总")
    if any(term in text for term in ("平均公积金比例", "公积金比例平均", "公积金比例平均值", "平均比例", "比例平均")):
        add_metric("avg", "fund_ratio", "公积金比例平均值")
    if any(term in text for term in ("缴费金额最大", "金额最大", "最高金额", "最大金额")):
        add_metric("max", "amount", "金额最大值")
    if any(term in text for term in ("缴费金额最小", "金额最小", "最低金额", "最小金额")):
        add_metric("min", "amount", "金额最小值")
    if not metrics and aggregate_op:
        add_metric(aggregate_op, measure, COLUMN_LABELS.get(measure, measure or aggregate_op))
    return metrics


def query_operation(question: str, group_by: str = "", distinct_by: str = "", aggregate_op: str = "", metrics: list[dict[str, str]] | None = None, select_cols: list[str] | None = None) -> str:
    text = compact(question)
    if group_by and metrics and len(metrics) > 1:
        return "multi_metric_group"
    if aggregate_op:
        return f"{aggregate_op}_group" if group_by else aggregate_op
    if group_by:
        return "group_count"
    if distinct_by:
        return "distinct_count" if any(term in text for term in ("多少", "几个", "几家")) else "distinct_list"
    if select_cols and any(term in text for term in ("多少", "是什么", "是多少", "哪天", "几号", "什么时候", "谁", "哪位")):
        return "retrieve"
    if any(term in text for term in ("列出", "清单", "名单", "明细", "有哪些", "哪些")):
        return "list"
    if any(term in text for term in ("多少", "几个", "几家", "统计", "汇总", "总数", "数量")):
        return "count"
    return "retrieve"


def sort_direction(question: str) -> str:
    text = compact(question).lower()
    if any(term in text for term in ("最少", "倒数", "升序", "asc", "bottom")):
        return "asc"
    if any(term in text for term in ("最多", "前", "降序", "top", "desc")):
        return "desc"
    return "desc"


def result_limit(question: str, default: int = 20) -> int:
    text = compact(question).lower()
    patterns = (
        r"前(\d{1,3})(?:个|名|条|家)?",
        r"top(\d{1,3})",
        r"limit(\d{1,3})",
        r"最多(?:展示|显示|列出)?(\d{1,3})(?:个|名|条|家)?",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return max(1, min(100, int(match.group(1))))
    return default


def time_dimension(question: str) -> tuple[str, str, list[str]]:
    text = clean(question)
    compact_text = compact(text)
    matches: list[tuple[str, str]] = []

    def add_match(year: str, month: str) -> None:
        try:
            month_no = int(month)
        except ValueError:
            return
        if 1 <= month_no <= 12 and (year, str(month_no)) not in matches:
            matches.append((year, str(month_no)))

    for year, month in re.findall(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", text):
        add_match(year, month)
    for year, month in re.findall(r"(20\d{2})\s*[-/]\s*(\d{1,2})", text):
        add_match(year, month)
    for year, month in re.findall(r"(20\d{2})(\d{2})", compact_text):
        add_match(year, month)

    # 支持“2025年10月和11月”“2025年10、11月”这类省略年份的多月份对比问法。
    anchor_year = matches[0][0] if matches else ""
    if anchor_year:
        explicit_months = {int(month) for _year, month in matches}
        for month in re.findall(r"(?<!\d)(\d{1,2})\s*月", text):
            month_no = int(month)
            if 1 <= month_no <= 12 and month_no not in explicit_months:
                add_match(anchor_year, str(month_no))
                explicit_months.add(month_no)
        for month in re.findall(r"(?:和|与|、|,|，)(\d{1,2})(?=月|的|和|与|、|,|，)", text):
            month_no = int(month)
            if 1 <= month_no <= 12 and month_no not in explicit_months:
                add_match(anchor_year, str(month_no))
                explicit_months.add(month_no)

    if not matches:
        return "", "", []

    values: list[str] = []
    tokens: list[str] = []
    for year, month in matches:
        month_no = int(month)
        value = f"{year}-{month_no:02d}"
        values.append(value)
        tokens.extend([f"{year}{month_no:02d}", value, f"{year}年{month_no}月", f"{year}年{month_no:02d}月"])
    return "month", ",".join(dict.fromkeys(values)), list(dict.fromkeys(tokens))


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


def describe_table_query_plan(plan: TableQueryPlan) -> dict[str, Any]:
    group_label = COLUMN_LABELS.get(plan.group_by, plan.group_by) if plan.group_by else ""
    distinct_label = COLUMN_LABELS.get(plan.distinct_by, plan.distinct_by) if plan.distinct_by else ""
    measure_label = COLUMN_LABELS.get(plan.measure_column, plan.measure_column) if plan.measure_column else ""
    metric_labels = [item.get("label") or COLUMN_LABELS.get(item.get("column", ""), item.get("op", "")) for item in plan.metrics]
    time_label = plan.time_value if plan.time_grain == "month" else ""
    select_labels = [COLUMN_LABELS.get(column, column) for column in plan.select_columns]
    filter_text = format_filter_groups(plan.filter_groups, plan.filter_logic) or "；".join(
        format_filter_condition(item) for item in plan.filters
    )
    sort_label = "升序" if plan.sort_by == "asc" else "降序"
    operation_label = QUERY_OPERATION_LABELS.get(plan.query_op, plan.query_op or "表格检索")
    aggregate_label = AGGREGATE_OPERATION_LABELS.get(plan.aggregate_op, plan.aggregate_op)
    parts = [f"识别为：{operation_label}"]
    if time_label:
        parts.append(f"时间范围：{time_label}")
    if filter_text:
        parts.append(f"过滤条件：{filter_text}")
    if group_label:
        parts.append(f"分组字段：{group_label}")
    if distinct_label:
        parts.append(f"去重字段：{distinct_label}")
    if metric_labels:
        parts.append(f"指标：{'、'.join(metric_labels)}")
    elif measure_label:
        parts.append(f"指标字段：{measure_label}")
    if select_labels:
        parts.append(f"展示字段：{'、'.join(select_labels)}")
    if plan.group_by or plan.aggregate_op:
        parts.append(f"排序：{sort_label}")
        parts.append(f"展开：前 {plan.limit} 项")
    return {
        "operation": operation_label,
        "operation_code": plan.query_op,
        "filters": filter_text,
        "filter_logic": plan.filter_logic,
        "time_grain": plan.time_grain,
        "time_value": plan.time_value,
        "time_tokens": plan.time_tokens,
        "group_by": group_label,
        "distinct_by": distinct_label,
        "aggregate": aggregate_label,
        "measure": measure_label,
        "metrics": metric_labels,
        "metric_specs": plan.metrics,
        "select_columns": select_labels,
        "sort": sort_label if plan.group_by or plan.aggregate_op else "",
        "limit": plan.limit if plan.group_by or plan.aggregate_op else "",
        "summary": "；".join(parts),
    }


def parse_table_query_plan(question: str, *, branch_completion: bool | None = None, include_quoted_company: bool = True) -> TableQueryPlan:
    branch = is_branch_completion_query(question) if branch_completion is None else branch_completion
    if branch:
        return TableQueryPlan(query_op="branch_completion_count", branch_completion_filter=True)

    filters, filter_logic, filter_groups = parse_filter_expression(question, include_quoted_company=include_quoted_company)
    group_by = group_by_column(question)
    distinct_by = distinct_column(question)
    aggregate_op = aggregate_operation(question)
    measure = measure_column(question) if aggregate_op else ""
    metrics = metric_specs(question, aggregate_op, measure)
    time_grain, time_value, time_tokens = time_dimension(question)
    selected = select_columns(question, filters)
    return TableQueryPlan(
        query_op=query_operation(question, group_by, distinct_by, aggregate_op, metrics, selected),
        filters=filters,
        filter_logic=filter_logic,
        filter_groups=filter_groups,
        select_columns=selected,
        group_by=group_by,
        distinct_by=distinct_by,
        aggregate_op=aggregate_op,
        measure_column=measure,
        metrics=metrics,
        sort_by=sort_direction(question),
        limit=result_limit(question),
        time_grain=time_grain,
        time_value=time_value,
        time_tokens=time_tokens,
    )
