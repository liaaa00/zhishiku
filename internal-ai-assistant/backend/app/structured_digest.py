import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Iterable

FIELD_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("人员信息", ("姓名", "手机号", "电话", "证件号", "身份证", "性别", "出生日期", "年龄", "户籍", "民族", "邮箱", "电子邮箱", "邮编", "现住地址", "地址", "编号")),
    ("岗位与客户", ("业务模式", "客户名称", "客户代码", "外包类型", "岗位", "工作城市", "工时制", "工作制", "人员类型", "部门", "项目")),
    ("薪资社保", ("工资形式", "基本工资", "其他工资", "试用期工资", "发薪周期", "发薪日期", "起始月", "社保基数", "公积金基数", "公积金比例", "开户银行", "银行卡", "账号", "薪资", "工资")),
    ("合同流程", ("劳动合同", "合同期限", "试用期", "入职材料", "催办", "是否企服发薪", "发薪税盘", "流程状态", "申请人", "申请时间", "更新时间", "是否为转移", "审批", "签署", "合同主体", "合同模板")),
    ("备注风险", ("备注", "特殊", "风险", "异常", "缺失", "是否需要催办", "问题", "逾期")),
]

STRUCTURE_INTENT_WORDS = (
    "整理", "表格", "分组", "字段", "结构", "展开", "总结", "汇总", "归纳", "梳理", "分类", "清单", "重点", "对比"
)
RISK_FIELD_WORDS = ("催办", "特殊", "备注", "风险", "缺失", "异常", "逾期", "失败", "待", "错误", "补充")
PROCESS_WORDS = ("流程", "步骤", "审批", "申请", "提交", "审核", "签署", "入职", "离职", "办理", "需要", "必须", "应当", "完成")
RANGE_WORDS = ("适用", "范围", "对象", "岗位", "客户", "部门", "人员", "城市", "条件", "场景")
MONEY_TIME_WORDS = ("工资", "薪资", "金额", "费用", "社保", "公积金", "日期", "时间", "周期", "期限", "月份", "年", "月", "日")
KNOWN_FIELD_KEYWORDS = tuple(sorted({kw for _, group in FIELD_GROUPS for kw in group}, key=len, reverse=True))
MAX_RECORDS_IN_DIGEST = 30
MAX_DETAIL_RECORDS = 10


def _clean(value: str, max_len: int | None = None) -> str:
    text = " ".join(str(value or "").replace("\u3000", " ").split()).strip()
    if max_len and len(text) > max_len:
        return text[: max_len - 1].rstrip() + "…"
    return text


def _split_cells(content: str) -> list[tuple[str, str]]:
    text = _clean(content)
    # Chunks sometimes drop the separator before the next cell, e.g. "BA1: 字段 A2: 值".
    pattern = re.compile(r"([A-Z]{1,3}\d+)\s*[:：]\s*(.*?)(?=\s*(?:\|\s*)?[A-Z]{1,3}\d+\s*[:：]|$)")
    return [(m.group(1), _clean(m.group(2))) for m in pattern.finditer(text) if _clean(m.group(2))]


def _row_col(cell: str) -> tuple[int, str]:
    match = re.match(r"([A-Z]{1,3})(\d+)", cell)
    if not match:
        return 0, cell
    return int(match.group(2)), match.group(1)


def _doc_key(context: dict) -> str:
    return str(context.get("document_id") or context.get("document_title") or context.get("filename") or "unknown")


def _doc_title(context: dict) -> str:
    return context.get("document_title") or context.get("filename") or "未知文档"


def _chunk_sort_key(context: dict) -> tuple[int, str]:
    value = context.get("chunk_index")
    try:
        return int(value or 0), ""
    except (TypeError, ValueError):
        text = str(value or "")
        match = re.search(r"(\d+)", text)
        return (int(match.group(1)) if match else 0), text


def _excel_serial_to_text(value: str) -> str:
    try:
        serial = float(str(value).strip())
    except (TypeError, ValueError):
        return value
    if not (20000 <= serial <= 80000):
        return value
    dt = datetime(1899, 12, 30) + timedelta(days=serial)
    if abs(serial - int(serial)) < 0.000001:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M")


def _normalize_field_value(field: str, value: str) -> str:
    value = _clean(value, 180)
    if not value:
        return value
    if "日期" in field or "时间" in field:
        return _excel_serial_to_text(value)
    if field in {"公积金比例"}:
        try:
            number = float(value)
            if number <= 1:
                return f"{number * 100:g}%"
            return f"{number:g}%"
        except ValueError:
            return value
    return value


def _dedupe_records(records: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen: set[str] = set()
    for record in records:
        natural = record.get("编号") or record.get("数据ID") or record.get("姓名") or ""
        key = natural or "|".join(f"{k}={v}" for k, v in sorted(record.items()) if not k.startswith("__"))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def parse_excel_like_records(contexts: Iterable[dict]) -> list[dict]:
    """Parse Excel-like chunks and merge rows across overlapping chunks of the same document."""
    doc_state: dict[str, dict] = {}
    for context in sorted(list(contexts), key=lambda c: (_doc_key(c), _chunk_sort_key(c))):
        cells = _split_cells(context.get("content") or "")
        if not cells:
            continue
        key = _doc_key(context)
        state = doc_state.setdefault(key, {"title": _doc_title(context), "headers": {}, "rows": defaultdict(dict)})
        for cell, value in cells:
            row, col = _row_col(cell)
            if row == 1:
                # Prefer the cleanest/shorter header when overlapping chunks repeat a header cell.
                current = state["headers"].get(col)
                if not current or len(value) < len(current) + 8:
                    state["headers"][col] = value
            elif row > 1 and value:
                state["rows"][row][col] = value

    records: list[dict] = []
    for state in doc_state.values():
        headers: dict[str, str] = state["headers"]
        if not headers:
            continue
        for row_no, values in sorted(state["rows"].items()):
            record = {"__source_title": state["title"], "__row": row_no}
            for col, value in sorted(values.items()):
                field = headers.get(col, col)
                if value and field:
                    record[field] = _normalize_field_value(field, value)
            # Require at least a few real fields to avoid treating broken chunk prefixes as records.
            if len([k for k in record if not k.startswith("__")]) >= 4:
                records.append(record)
    return _dedupe_records(records)


def _parse_key_value_records(contexts: Iterable[dict]) -> list[dict]:
    records: list[dict] = []
    kv_pattern = re.compile(r"([\u4e00-\u9fffA-Za-z0-9_（）()\-/]{2,24})\s*[:：]\s*([^；;，,。\n\r|]{1,120})")
    for context in contexts:
        pairs: dict[str, str] = {}
        for raw_field, raw_value in kv_pattern.findall(context.get("content") or ""):
            field = _clean(raw_field)
            value = _normalize_field_value(field, raw_value)
            if field and value and any(keyword in field for keyword in KNOWN_FIELD_KEYWORDS):
                pairs[field] = value
        if len(pairs) >= 3:
            pairs["__source_title"] = _doc_title(context)
            records.append(pairs)
    return _dedupe_records(records)


def _group_fields(record: dict) -> dict[str, list[tuple[str, str]]]:
    grouped: dict[str, list[tuple[str, str]]] = {name: [] for name, _ in FIELD_GROUPS}
    grouped["其他字段"] = []
    for field, value in record.items():
        if field.startswith("__") or not value:
            continue
        target = "其他字段"
        for group, keywords in FIELD_GROUPS:
            if any(keyword in field for keyword in keywords):
                target = group
                break
        grouped[target].append((field, _clean(value, 180)))
    return {k: v for k, v in grouped.items() if v}


def _record_title(record: dict, index: int) -> str:
    name = record.get("姓名") or record.get("申请人") or record.get("人员姓名") or f"记录{index}"
    customer = record.get("客户名称") or record.get("客户") or ""
    job = record.get("岗位") or record.get("职位") or ""
    extras = " / ".join(x for x in (customer, job) if x)
    return f"{name}（{extras}）" if extras else str(name)


def _unique_doc_titles(contexts: list[dict]) -> list[str]:
    titles: list[str] = []
    for context in contexts:
        title = _doc_title(context)
        if title not in titles:
            titles.append(title)
    return titles


def _source_range(items: list[dict]) -> str:
    pages = []
    for item in items:
        page = item.get("page_number") or item.get("page") or item.get("chunk_index")
        if page is not None and str(page) not in pages:
            pages.append(str(page))
    return "、".join(pages[:8]) if pages else "未标注页码/位置"


def _split_sentences(content: str) -> list[str]:
    text = _clean(content)
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?；;])\s*|\n+", text)
    sentences = [_clean(part, 220) for part in parts if len(_clean(part)) >= 12]
    if not sentences and text:
        sentences = [_clean(text, 220)]
    return sentences


def _sentence_score(sentence: str) -> int:
    score = 0
    if any(word in sentence for word in RISK_FIELD_WORDS):
        score += 4
    if any(word in sentence for word in PROCESS_WORDS):
        score += 3
    if any(word in sentence for word in RANGE_WORDS):
        score += 2
    if any(word in sentence for word in MONEY_TIME_WORDS) or re.search(r"\d", sentence):
        score += 2
    if 24 <= len(sentence) <= 180:
        score += 1
    return score


def _important_sentences(content: str, limit: int = 3) -> list[str]:
    seen: set[str] = set()
    sentences = []
    for sentence in _split_sentences(content):
        if sentence in seen:
            continue
        seen.add(sentence)
        sentences.append(sentence)
    sentences.sort(key=lambda item: (_sentence_score(item), -len(item)), reverse=True)
    return sentences[:limit]


def _add_unique(bucket: list[str], item: str, limit: int = 12) -> None:
    clean = _clean(item, 220)
    if clean and clean not in bucket and len(bucket) < limit:
        bucket.append(clean)


def _build_record_digest(records: list[dict], contexts: list[dict]) -> list[str]:
    lines: list[str] = []
    lines.append(f"- 识别记录数：{len(records)}")
    lines.append("- 整理方式：先跨分片合并同一张表的行列，再按人员/记录去重，并按人员、客户岗位、薪资社保、合同流程、风险备注分组。")

    lines.append("\n## 记录总览")
    lines.append("| 序号 | 人员/记录 | 客户 | 岗位 | 城市 | 薪资/工资 | 流程状态 | 来源 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for idx, record in enumerate(records[:MAX_RECORDS_IN_DIGEST], 1):
        title = _record_title(record, idx)
        customer = record.get("客户名称") or record.get("客户") or ""
        job = record.get("岗位") or record.get("职位") or ""
        city = record.get("工作城市") or record.get("城市") or ""
        salary = record.get("基本工资") or record.get("薪资") or record.get("工资") or record.get("试用期工资") or ""
        status = record.get("流程状态") or record.get("当前流程状态") or record.get("审批状态") or ""
        source = record.get("__source_title") or "未知文档"
        lines.append(f"| {idx} | {_clean(title, 60)} | {_clean(customer, 50)} | {_clean(job, 50)} | {_clean(city, 30)} | {_clean(salary, 50)} | {_clean(status, 50)} | {_clean(source, 60)} |")

    if len(records) > MAX_RECORDS_IN_DIGEST:
        lines.append(f"- 还有 {len(records) - MAX_RECORDS_IN_DIGEST} 条记录未在总览表中展开。")

    lines.append("\n## 分组明细")
    for idx, record in enumerate(records[:MAX_DETAIL_RECORDS], 1):
        lines.append(f"### {idx}. {_record_title(record, idx)}")
        grouped = _group_fields(record)
        for group_name, items in grouped.items():
            lines.append(f"**{group_name}**")
            for field, value in items[:16]:
                lines.append(f"- {field}：{value}")

    risk_lines = []
    for record in records:
        name = record.get("姓名") or record.get("申请人") or "未命名记录"
        for field, value in record.items():
            if field.startswith("__"):
                continue
            text = f"{field}{value}"
            if any(keyword in text for keyword in RISK_FIELD_WORDS) and value:
                risk_lines.append(f"- {name}：{field}={_clean(str(value), 160)}")
    lines.append("\n## 需要关注的事项")
    if risk_lines:
        lines.extend(risk_lines[:16])
    else:
        lines.append("- 暂未从结构化字段中识别到明确的催办、异常、缺失或风险备注。")
    return lines


def _build_generic_digest(contexts: list[dict], summary_mode: bool = False) -> list[str]:
    lines: list[str] = []
    lines.append("- 整理方式：按文档去重汇总，再按对象范围、流程要求、时间金额、风险例外进行主题归类。")

    grouped: dict[str, list[dict]] = defaultdict(list)
    for context in contexts:
        grouped[_doc_title(context)].append(context)

    lines.append("\n## 文档总览")
    for index, (title, items) in enumerate(list(grouped.items())[:10], 1):
        combined = "\n".join(_clean(item.get("content") or "", 1200) for item in items[:6])
        points = _important_sentences(combined, limit=4)
        lines.append(f"### {index}. {title}")
        lines.append(f"- 命中片段：{len(items)}；位置：{_source_range(items)}")
        if points:
            lines.append("- 关键信息：")
            for point in points:
                lines.append(f"  - {point}")
        else:
            lines.append("- 关键信息：命中片段为空或暂无法抽取稳定句子，请查看引用原文核验。")

    categories: dict[str, list[str]] = {
        "对象/适用范围": [],
        "流程/操作要求": [],
        "时间/金额/数量": [],
        "风险/例外/缺口": [],
        "其他重点": [],
    }
    for context in contexts:
        title = _doc_title(context)
        for sentence in _important_sentences(context.get("content") or "", limit=5):
            tagged = f"{sentence}（来源：{title}）"
            if any(word in sentence for word in RISK_FIELD_WORDS):
                _add_unique(categories["风险/例外/缺口"], tagged)
            elif any(word in sentence for word in PROCESS_WORDS):
                _add_unique(categories["流程/操作要求"], tagged)
            elif any(word in sentence for word in MONEY_TIME_WORDS) or re.search(r"\d", sentence):
                _add_unique(categories["时间/金额/数量"], tagged)
            elif any(word in sentence for word in RANGE_WORDS):
                _add_unique(categories["对象/适用范围"], tagged)
            else:
                _add_unique(categories["其他重点"], tagged)

    lines.append("\n## 分类整理")
    for category, items in categories.items():
        if not items:
            continue
        lines.append(f"### {category}")
        for item in items[:8]:
            lines.append(f"- {item}")

    lines.append("\n## 需要关注的事项")
    risks = categories.get("风险/例外/缺口") or []
    if risks:
        for item in risks[:8]:
            lines.append(f"- {item}")
    else:
        lines.append("- 当前命中片段未明确暴露风险/例外；若要用于决策，建议继续追问缺失字段、异常值、依据不足点。")
    if len(contexts) < 2 and not summary_mode:
        lines.append("- 命中片段较少，回答置信度可能受限，建议补充关键词或上传/授权更多文档。")
    return lines


def build_structured_digest(question: str, contexts: list[dict], summary_mode: bool = False) -> str:
    if not contexts:
        return ""

    records = parse_excel_like_records(contexts) or _parse_key_value_records(contexts)
    doc_titles = _unique_doc_titles(contexts)

    lines: list[str] = []
    lines.append("## 结构化整理结果")
    if doc_titles:
        lines.append(f"- 文档范围：{'、'.join(doc_titles[:12])}" + ("等" if len(doc_titles) > 12 else ""))
    lines.append(f"- 命中片段数：{len(contexts)}")
    if question:
        lines.append(f"- 用户问题：{_clean(question, 120)}")

    if records:
        lines.extend(_build_record_digest(records, contexts))
    else:
        lines.extend(_build_generic_digest(contexts, summary_mode=summary_mode))

    lines.append("\n## 可追问方向")
    if records:
        lines.append("- 按某个人员/记录展开完整字段。")
        lines.append("- 按薪资社保、合同流程、客户岗位分别整理成表格。")
        lines.append("- 检查缺失字段、异常值或需要催办的事项。")
    else:
        lines.append("- 按文档逐份展开关键条款和适用范围。")
        lines.append("- 整理成表格：主题、要求、依据来源、风险点。")
        lines.append("- 指出依据不足、冲突信息或需要补充授权的资料。")
    return "\n".join(lines)


def should_use_structured_digest(question: str, contexts: list[dict], summary_mode: bool = False) -> bool:
    if not contexts:
        return False
    if summary_mode:
        return True
    text = question or ""
    if any(word in text for word in STRUCTURE_INTENT_WORDS):
        return True
    if parse_excel_like_records(contexts):
        return True
    return True
