from __future__ import annotations

import re

from .schemas import QueryAnalysis

TABLE_STAT_TERMS = (
    "多少",
    "几个",
    "有多少",
    "统计",
    "汇总",
    "数量",
    "计数",
    "列出",
    "名单",
    "明细",
    "筛选",
    "什么时候",
    "哪天",
    "几号",
    "谁",
    "哪位",
    "是否",
    "有没有",
    "有无",
    "开具完成",
    "开好",
    "完成了吗",
)
TABLE_OBJECT_TERMS = (
    "表格",
    "清单",
    "名单",
    "明细",
    "数据",
    "记录",
    "行",
    "列",
    "sheet",
    "excel",
    "xlsx",
    "csv",
    "网点",
    "分公司",
    "社保",
    "医保",
    "公积金",
    "缴费",
    "缴款",
    "公司名称",
    "账户",
    "银行账户",
    "社保账户",
    "公积金账户",
    "社保公积金账户",
    "当前进度",
    "比例",
    "派单",
    "截止时间",
    "时间表",
    "预计缴款时间",
    "操作规则",
    "后道对接人",
)
METADATA_TERMS = (
    "哪个文件",
    "哪些文件",
    "文件名",
    "文档名",
    "标题",
    "上传时间",
    "最近上传",
    "最新上传",
    "最新文件",
    "可读文档",
    "有哪些文档",
)
SUMMARY_TERMS = (
    "总结我现在可读的文档",
    "可读的文档",
    "全部文档",
    "所有文档",
    "文档清单",
    "资料清单",
    "知识库里有哪些",
)
TEXT_QA_TERMS = (
    "是什么",
    "怎么",
    "如何",
    "为什么",
    "流程",
    "步骤",
    "规定",
    "制度",
    "要求",
    "说明",
    "指南",
)
FIELD_TERMS = (
    "日期",
    "时间",
    "金额",
    "比例",
    "电话",
    "邮箱",
    "编号",
    "甲方",
    "乙方",
    "谁",
)
NON_TABLE_PROCESS_TERMS = (
    "怎么签",
    "如何签",
    "电子签",
    "签署",
    "劳动合同",
    "合同流程",
    "操作指南",
)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").lower()


def _matched_terms(compact: str, terms: tuple[str, ...]) -> list[str]:
    return [term for term in terms if term.lower() in compact]


def _extract_time_filters(query: str) -> list[str]:
    filters: list[str] = []
    patterns = (
        r"20\d{2}\s*年\s*\d{1,2}\s*月",
        r"20\d{2}[-/]\d{1,2}",
        r"20\d{2}",
        r"\d{6}",
        r"最新|最近|本月|上月|今年|去年",
    )
    for pattern in patterns:
        filters.extend(match.group(0) for match in re.finditer(pattern, query or ""))
    return list(dict.fromkeys(filters))


def _extract_entities(query: str) -> list[str]:
    compact = _compact(query)
    known_terms = sorted(
        set(TABLE_OBJECT_TERMS + FIELD_TERMS + METADATA_TERMS),
        key=len,
        reverse=True,
    )
    entities = [term for term in known_terms if term.lower() in compact]
    quoted = re.findall(r"[《\"“](.*?)[》\"”]", query or "")
    entities.extend(item.strip() for item in quoted if item.strip())
    return list(dict.fromkeys(entities))[:20]


def analyze_query(query: str) -> QueryAnalysis:
    """Rule-based first-stage query analysis.

    This intentionally stays deterministic and cheap. Later phases can replace or
    augment it with model classification without changing retriever interfaces.
    """

    text = (query or "").strip()
    compact = _compact(text)
    reasons: list[str] = []
    entities = _extract_entities(text)
    time_filters = _extract_time_filters(text)

    summary_hits = _matched_terms(compact, SUMMARY_TERMS)
    metadata_hits = _matched_terms(compact, METADATA_TERMS)
    table_stat_hits = _matched_terms(compact, TABLE_STAT_TERMS)
    table_object_hits = _matched_terms(compact, TABLE_OBJECT_TERMS)
    text_hits = _matched_terms(compact, TEXT_QA_TERMS)
    field_hits = _matched_terms(compact, FIELD_TERMS)
    non_table_process_hits = _matched_terms(compact, NON_TABLE_PROCESS_TERMS)

    if summary_hits:
        reasons.append(f"summary_terms:{','.join(summary_hits[:4])}")
        return QueryAnalysis(
            query=text,
            intent="summary_query",
            confidence=0.88,
            route_hint="summary",
            entities=entities,
            time_filters=time_filters,
            reasons=reasons,
        )

    if metadata_hits and not table_object_hits:
        reasons.append(f"metadata_terms:{','.join(metadata_hits[:4])}")
        return QueryAnalysis(
            query=text,
            intent="metadata_query",
            confidence=0.82,
            route_hint="metadata",
            entities=entities,
            time_filters=time_filters,
            reasons=reasons,
        )

    # Table questions require both an operation signal and a table/business object
    # signal. This prevents standalone editing prompts such as “把内容整理成表格”
    # from entering knowledge retrieval; chat_api already filters those earlier.
    if table_object_hits and (table_stat_hits or time_filters) and not non_table_process_hits:
        reasons.append(f"table_terms:{','.join((table_object_hits + table_stat_hits)[:6])}")
        return QueryAnalysis(
            query=text,
            intent="table_query",
            confidence=0.86,
            route_hint="table",
            entities=entities,
            conditions=table_object_hits[:12],
            metrics=table_stat_hits[:8],
            time_filters=time_filters,
            reasons=reasons,
        )

    if field_hits and metadata_hits:
        reasons.append(f"metadata_field_terms:{','.join((field_hits + metadata_hits)[:6])}")
        return QueryAnalysis(
            query=text,
            intent="metadata_query",
            confidence=0.72,
            route_hint="metadata",
            entities=entities,
            conditions=field_hits[:8],
            time_filters=time_filters,
            reasons=reasons,
        )

    if text_hits or field_hits:
        reasons.append(f"text_terms:{','.join((text_hits + field_hits)[:6])}")
        return QueryAnalysis(
            query=text,
            intent="text_qa",
            confidence=0.72 if text_hits else 0.62,
            route_hint="text",
            entities=entities,
            conditions=field_hits[:8],
            time_filters=time_filters,
            reasons=reasons,
        )

    reasons.append("fallback:text_qa")
    return QueryAnalysis(
        query=text,
        intent="text_qa",
        confidence=0.52,
        route_hint="text",
        entities=entities,
        time_filters=time_filters,
        reasons=reasons,
    )
