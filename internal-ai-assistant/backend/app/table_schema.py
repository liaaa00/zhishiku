from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

SEMANTIC_ALIASES: dict[str, tuple[str, ...]] = {
    "city": ("城市", "所在城市", "服务城市", "业务城市", "地市", "地区", "区域", "所属地", "所在地", "属地", "省市"),
    "province": ("省份", "省", "所在省份", "所属省份"),
    "company": ("公司名称", "开设公司名称", "单位名称", "法人公司", "主体公司", "机构主体", "公司主体", "分公司", "网点名称", "机构名称", "门店名称"),
    "status": ("当前进度", "状态", "网点状态", "门店状态", "启用状态", "是否启用", "是否有效", "是否完成", "完成情况", "进度"),
    "bank_account": ("银行账户", "开户银行", "银行账号", "账户状态"),
    "social_account": ("社保公积金账户", "社保账户", "公积金账户", "社保公积金"),
    "fund_ratio": ("公积金比例", "比例", "缴存比例"),
}

SEMANTIC_LABELS = {
    "city": "城市",
    "province": "省份",
    "company": "公司",
    "status": "状态",
    "bank_account": "银行账户",
    "social_account": "社保公积金账户",
    "fund_ratio": "公积金比例",
}

CITY_VALUE_HINTS = (
    "北京",
    "上海",
    "广州",
    "深圳",
    "成都",
    "宁波",
    "北仑",
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
)

STATUS_VALUE_HINTS = (
    "有效",
    "无效",
    "启用",
    "停用",
    "正常",
    "关闭",
    "完成",
    "未完成",
    "是",
    "否",
    "已开通",
    "未开通",
)

COMPANY_VALUE_HINTS = (
    "公司",
    "分公司",
    "有限",
    "集团",
    "网点",
    "门店",
    "机构",
)


@dataclass
class ColumnSemanticMatch:
    raw_name: str
    semantic_name: str
    score: float
    reasons: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)


def clean_value(value: Any) -> str:
    return " ".join(str(value or "").replace("\u3000", " ").split()).strip()


def compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def unique_clean_values(values: Iterable[Any], limit: int = 8) -> list[str]:
    result: list[str] = []
    for value in values:
        cleaned = clean_value(value)
        if cleaned and cleaned not in result:
            result.append(cleaned)
        if len(result) >= limit:
            break
    return result


def score_column_semantic(raw_name: str, values: Iterable[Any], semantic_name: str) -> ColumnSemanticMatch:
    key = compact(raw_name)
    samples = unique_clean_values(values, limit=8)
    sample_text = " ".join(samples)
    score = 0.0
    reasons: list[str] = []

    for alias in SEMANTIC_ALIASES.get(semantic_name, ()):
        alias_text = compact(alias)
        if not alias_text:
            continue
        if alias_text == key:
            score += 3.0
            reasons.append(f"列名精确匹配 {alias}")
        elif alias_text in key or key in alias_text:
            score += 1.6
            reasons.append(f"列名包含 {alias}")

    if semantic_name == "city" and any(city in sample_text for city in CITY_VALUE_HINTS):
        score += 1.0
        reasons.append("样例值像城市")
    elif semantic_name == "status" and any(status in sample_text for status in STATUS_VALUE_HINTS):
        score += 1.0
        reasons.append("样例值像状态")
    elif semantic_name == "company" and any(marker in sample_text for marker in COMPANY_VALUE_HINTS):
        score += 0.9
        reasons.append("样例值像公司/机构")

    return ColumnSemanticMatch(
        raw_name=str(raw_name),
        semantic_name=semantic_name,
        score=round(score, 4),
        reasons=reasons,
        samples=samples,
    )


def infer_column_semantics(rows: Iterable[dict[str, Any]], min_score: float = 1.0) -> dict[str, ColumnSemanticMatch]:
    column_values: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        if not isinstance(row, dict):
            continue
        for key, value in row.items():
            if key is None:
                continue
            column_values[str(key)].append(value)

    best_by_semantic: dict[str, ColumnSemanticMatch] = {}
    for raw_name, values in column_values.items():
        for semantic_name in SEMANTIC_ALIASES:
            match = score_column_semantic(raw_name, values, semantic_name)
            if match.score < min_score:
                continue
            current = best_by_semantic.get(semantic_name)
            if current is None or match.score > current.score:
                best_by_semantic[semantic_name] = match
    return best_by_semantic


def semantic_value(row: dict[str, Any], semantic_name: str, semantic_map: dict[str, ColumnSemanticMatch] | None = None) -> str:
    if semantic_map and semantic_name in semantic_map:
        raw_name = semantic_map[semantic_name].raw_name
        value = clean_value(row.get(raw_name, ""))
        if value:
            return value
    for raw_name, value in row.items():
        key = str(raw_name or "")
        if any(alias in key for alias in SEMANTIC_ALIASES.get(semantic_name, ())):
            cleaned = clean_value(value)
            if cleaned:
                return cleaned
    return ""


def semantic_columns_debug(semantic_map: dict[str, ColumnSemanticMatch] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for semantic_name, match in (semantic_map or {}).items():
        result.append(
            {
                "semantic_name": semantic_name,
                "label": SEMANTIC_LABELS.get(semantic_name, semantic_name),
                "raw_name": match.raw_name,
                "score": match.score,
                "reasons": match.reasons,
                "samples": match.samples[:5],
            }
        )
    return sorted(result, key=lambda item: str(item.get("semantic_name") or ""))
