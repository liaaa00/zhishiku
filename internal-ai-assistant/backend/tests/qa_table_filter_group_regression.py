"""Regression for table value filters, grouping, and distinct counting.

Run from internal-ai-assistant/backend:
    python tests/qa_table_filter_group_regression.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_table_filter_group.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Document, DocumentTableRow, User  # noqa: E402
from app.table_plan import parse_table_query_plan  # noqa: E402
from app.table_query import build_table_answer, build_table_structured_result  # noqa: E402
from app.table_retrieval import table_mode_contexts  # noqa: E402


def _row(
    row_id: str,
    row_number: int,
    city: str,
    company: str,
    status: str = "有效",
    bank_account: str = "已开通",
    fund_ratio: str = "8",
    amount: str = "0",
) -> DocumentTableRow:
    payload = {
        "城市": city,
        "公司名称": company,
        "网点状态": status,
        "当前进度": "已完成",
        "银行账户": bank_account,
        "公积金比例": fund_ratio,
        "缴费金额": amount,
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-table-filter-group",
        sheet_name="202606",
        row_number=row_number,
        row_key=f"202606:{row_number}",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text=" | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=False,
    )


def _nonstandard_row(row_id: str, row_number: int, city: str, company: str, status: str = "有效") -> DocumentTableRow:
    payload = {
        "所属地": city,
        "机构主体": company,
        "是否启用": status,
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-table-nonstandard",
        sheet_name="门店清单",
        row_number=row_number,
        row_key=f"门店清单:{row_number}",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text=" | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=False,
    )


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(id="admin", username="admin", password_hash="x", is_admin=True)
        doc = Document(
            id="doc-table-filter-group",
            title="有效网点清单202606",
            filename="有效网点清单202606.xlsx",
            storage_path="fixture.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        nonstandard_doc = Document(
            id="doc-table-nonstandard",
            title="新上传门店台账202606",
            filename="新上传门店台账202606.xlsx",
            storage_path="fixture2.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        db.add(user)
        db.add(doc)
        db.add(nonstandard_doc)
        db.add_all(
            [
                _row("row-sh-1", 2, "上海", "上海一号网点", bank_account="已开通", fund_ratio="8", amount="1000"),
                _row("row-sh-2", 3, "上海", "上海二号网点", bank_account="", fund_ratio="", amount="2500"),
                _row("row-sh-disabled", 4, "上海", "上海停用网点", "停用", bank_account="已开通", fund_ratio="3", amount="300"),
                _row("row-bj-1", 5, "北京", "北京一号网点", bank_account="已开通", fund_ratio="5", amount="800"),
                _row("row-cd-1", 6, "成都", "成都一号网点", bank_account="", fund_ratio="", amount="200"),
                _nonstandard_row("row-ns-sh-1", 2, "上海", "上海新表机构", "有效"),
                _nonstandard_row("row-ns-sh-off", 3, "上海", "上海新表停用机构", "停用"),
                _nonstandard_row("row-ns-bj-1", 4, "北京", "北京新表机构", "有效"),
            ]
        )
        db.commit()

        filter_question = "列出城市=上海的有效网点清单"
        contexts, meta = table_mode_contexts(db, filter_question, user, top_k=10)
        row_ids = {str(item.get("table_row_id")) for item in contexts if not item.get("is_header")}
        if row_ids != {"row-sh-1", "row-sh-2", "row-sh-disabled", "row-ns-sh-1", "row-ns-sh-off"}:
            raise AssertionError(f"city filter should keep only Shanghai rows across standard/nonstandard schemas, got {sorted(row_ids)}; meta={meta}")
        if meta.get("value_filter_matched_rows") != 5:
            raise AssertionError(f"expected 5 value-filter matches, got {meta}")
        schema_entries = meta.get("table_schema", {}).get("doc-table-nonstandard") or []
        schema_pairs = {(item.get("semantic_name"), item.get("raw_name")) for item in schema_entries}
        if not {("city", "所属地"), ("company", "机构主体"), ("status", "是否启用")}.issubset(schema_pairs):
            raise AssertionError(f"nonstandard table schema should map semantic columns, got {schema_entries}")
        if meta.get("query_op") != "list":
            raise AssertionError(f"city filter list query should be query_op=list, got {meta}")

        multi_filter_question = "列出城市=上海且状态=有效的网点清单"
        multi_contexts, multi_meta = table_mode_contexts(db, multi_filter_question, user, top_k=10)
        multi_row_ids = {str(item.get("table_row_id")) for item in multi_contexts if not item.get("is_header")}
        if multi_row_ids != {"row-sh-1", "row-sh-2", "row-ns-sh-1"}:
            raise AssertionError(f"multi filters should keep only active Shanghai rows across schemas, got {sorted(multi_row_ids)}; meta={multi_meta}")
        if multi_meta.get("query_op") != "list":
            raise AssertionError(f"multi filter list query should be query_op=list, got {multi_meta}")
        multi_answer = build_table_answer(multi_filter_question, multi_contexts)
        if "过滤条件：城市 等于 上海 且 状态 等于 有效" not in multi_answer:
            raise AssertionError(f"answer should explain multi filters; answer={multi_answer}")
        if "查询操作：明细列举" not in multi_answer:
            raise AssertionError(f"answer should explain list operation; answer={multi_answer}")

        projection_question = "列出城市=上海且状态=有效的公司名称、城市、状态"
        parsed_plan = parse_table_query_plan(projection_question).to_dict()
        if parsed_plan.get("query_op") != "list":
            raise AssertionError(f"plan should detect list operation, got {parsed_plan}")
        if parsed_plan.get("filters") != [
            {"column": "city", "operator": "eq", "value": "上海"},
            {"column": "status", "operator": "eq", "value": "有效"},
        ]:
            raise AssertionError(f"plan should detect city/status filters, got {parsed_plan}")
        if parsed_plan.get("filter_logic") != "and" or parsed_plan.get("filter_groups") != [parsed_plan.get("filters")]:
            raise AssertionError(f"plan should expose AND filter group, got {parsed_plan}")
        if parsed_plan.get("select_columns") != ["company", "city", "status"]:
            raise AssertionError(f"plan should detect company/city/status projection, got {parsed_plan}")
        projection_contexts, projection_meta = table_mode_contexts(db, projection_question, user, top_k=10)
        if projection_meta.get("table_query_plan") != parsed_plan:
            raise AssertionError(f"retrieval meta should expose unified table query plan, got {projection_meta}")
        if projection_meta.get("select_columns") != ["company", "city", "status"]:
            raise AssertionError(f"projection should detect company/city/status, got {projection_meta}")
        projection_answer = build_table_answer(projection_question, projection_contexts)
        if "展示字段：公司、城市、状态" not in projection_answer:
            raise AssertionError(f"answer should explain selected columns; answer={projection_answer}")
        if "公司=上海一号网点 | 城市=上海 | 状态=有效" not in projection_answer:
            raise AssertionError(f"preview should prioritize projected fields; answer={projection_answer}")
        if "公司=上海新表机构 | 城市=上海 | 状态=有效" not in projection_answer:
            raise AssertionError(f"preview should project fields through nonstandard schema; answer={projection_answer}")

        or_question = "列出城市=上海或城市=北京的网点清单"
        or_plan = parse_table_query_plan(or_question).to_dict()
        if or_plan.get("filter_logic") != "or" or len(or_plan.get("filter_groups") or []) != 2:
            raise AssertionError(f"OR plan should expose two filter groups, got {or_plan}")
        or_contexts, or_meta = table_mode_contexts(db, or_question, user, top_k=10)
        or_row_ids = {str(item.get("table_row_id")) for item in or_contexts if not item.get("is_header")}
        if or_row_ids != {"row-sh-1", "row-sh-2", "row-sh-disabled", "row-bj-1", "row-ns-sh-1", "row-ns-sh-off", "row-ns-bj-1"}:
            raise AssertionError(f"OR city filter should keep Shanghai or Beijing rows, got {sorted(or_row_ids)}; meta={or_meta}")
        if or_meta.get("filter_logic") != "or":
            raise AssertionError(f"retrieval meta should expose OR logic, got {or_meta}")

        inherited_or_question = "列出城市=上海且状态=有效或状态=停用的公司名称、城市、状态"
        inherited_or_plan = parse_table_query_plan(inherited_or_question).to_dict()
        if inherited_or_plan.get("filter_logic") != "or" or len(inherited_or_plan.get("filter_groups") or []) != 2:
            raise AssertionError(f"inherited OR plan should expose two filter groups, got {inherited_or_plan}")
        inherited_or_contexts, inherited_or_meta = table_mode_contexts(db, inherited_or_question, user, top_k=10)
        inherited_or_row_ids = {str(item.get("table_row_id")) for item in inherited_or_contexts if not item.get("is_header")}
        if inherited_or_row_ids != {"row-sh-1", "row-sh-2", "row-sh-disabled", "row-ns-sh-1", "row-ns-sh-off"}:
            raise AssertionError(f"inherited OR should stay within Shanghai and include active/stopped rows, got {sorted(inherited_or_row_ids)}; meta={inherited_or_meta}")
        inherited_or_answer = build_table_answer(inherited_or_question, inherited_or_contexts)
        if "或" not in inherited_or_answer or "状态 等于 停用" not in inherited_or_answer:
            raise AssertionError(f"answer should explain OR filter groups; answer={inherited_or_answer}")

        not_equal_question = "列出城市=上海且状态!=停用的公司名称、城市、状态"
        not_equal_contexts, not_equal_meta = table_mode_contexts(db, not_equal_question, user, top_k=10)
        not_equal_row_ids = {str(item.get("table_row_id")) for item in not_equal_contexts if not item.get("is_header")}
        if not_equal_row_ids != {"row-sh-1", "row-sh-2", "row-ns-sh-1"}:
            raise AssertionError(f"not-equal filter should exclude stopped rows, got {sorted(not_equal_row_ids)}; meta={not_equal_meta}")
        if {"column": "status", "operator": "ne", "value": "停用"} not in not_equal_meta.get("value_filters", []):
            raise AssertionError(f"not-equal operator should be in meta filters, got {not_equal_meta}")
        not_equal_answer = build_table_answer(not_equal_question, not_equal_contexts)
        if "状态 不等于 停用" not in not_equal_answer:
            raise AssertionError(f"answer should explain not-equal filter; answer={not_equal_answer}")

        non_empty_question = "列出银行账户非空的公司名称、银行账户"
        non_empty_contexts, non_empty_meta = table_mode_contexts(db, non_empty_question, user, top_k=10)
        non_empty_row_ids = {str(item.get("table_row_id")) for item in non_empty_contexts if not item.get("is_header")}
        if not {"row-sh-1", "row-sh-disabled", "row-bj-1"}.issubset(non_empty_row_ids):
            raise AssertionError(f"non-empty filter should keep rows with bank account, got {sorted(non_empty_row_ids)}; meta={non_empty_meta}")
        if {"column": "bank_account", "operator": "is_not_empty"} not in non_empty_meta.get("value_filters", []):
            raise AssertionError(f"non-empty operator should be in meta filters, got {non_empty_meta}")

        empty_question = "列出公积金比例为空的公司名称、公积金比例"
        empty_contexts, empty_meta = table_mode_contexts(db, empty_question, user, top_k=10)
        empty_row_ids = {str(item.get("table_row_id")) for item in empty_contexts if not item.get("is_header")}
        if not {"row-sh-2", "row-cd-1"}.issubset(empty_row_ids):
            raise AssertionError(f"empty filter should keep rows with blank fund ratio, got {sorted(empty_row_ids)}; meta={empty_meta}")
        if {"column": "fund_ratio", "operator": "is_empty"} not in empty_meta.get("value_filters", []):
            raise AssertionError(f"empty operator should be in meta filters, got {empty_meta}")

        greater_question = "列出公积金比例>5的公司名称、公积金比例"
        greater_contexts, greater_meta = table_mode_contexts(db, greater_question, user, top_k=10)
        greater_row_ids = {str(item.get("table_row_id")) for item in greater_contexts if not item.get("is_header")}
        if "row-sh-1" not in greater_row_ids or "row-sh-disabled" in greater_row_ids or "row-bj-1" in greater_row_ids:
            raise AssertionError(f"greater-than filter should keep only ratio above 5, got {sorted(greater_row_ids)}; meta={greater_meta}")
        if {"column": "fund_ratio", "operator": "gt", "value": "5"} not in greater_meta.get("value_filters", []):
            raise AssertionError(f"greater-than operator should be in meta filters, got {greater_meta}")

        sum_question = "按城市统计缴费金额总和"
        sum_plan = parse_table_query_plan(sum_question).to_dict()
        if sum_plan.get("query_op") != "sum_group" or sum_plan.get("aggregate_op") != "sum" or sum_plan.get("measure_column") != "amount":
            raise AssertionError(f"sum plan should detect grouped amount sum, got {sum_plan}")
        sum_contexts, sum_meta = table_mode_contexts(db, sum_question, user, top_k=10)
        if sum_meta.get("aggregate_op") != "sum" or sum_meta.get("measure_column") != "amount":
            raise AssertionError(f"sum retrieval meta should expose aggregate plan, got {sum_meta}")
        sum_explanation = sum_meta.get("table_query_explanation") or {}
        if "识别为：分组求和" not in sum_explanation.get("summary", "") or sum_explanation.get("group_by") != "城市" or sum_explanation.get("measure") != "金额":
            raise AssertionError(f"sum retrieval meta should expose plan explanation, got {sum_meta}")
        sum_answer = build_table_answer(sum_question, sum_contexts)
        if "查询操作：分组求和" not in sum_answer or "按城市汇总金额" not in sum_answer or "计划解释：识别为：分组求和" not in sum_answer:
            raise AssertionError(f"sum answer should explain grouped sum; meta={sum_meta}; answer={sum_answer}")
        if "上海：3800" not in sum_answer or "北京：800" not in sum_answer or "成都：200" not in sum_answer:
            raise AssertionError(f"sum answer should include expected city totals; meta={sum_meta}; answer={sum_answer}")

        month_sum_question = "2026年6月按城市统计缴费金额总和"
        month_sum_plan = parse_table_query_plan(month_sum_question).to_dict()
        if month_sum_plan.get("time_grain") != "month" or month_sum_plan.get("time_value") != "2026-06" or "202606" not in month_sum_plan.get("time_tokens", []):
            raise AssertionError(f"month sum plan should parse 2026-06 time dimension, got {month_sum_plan}")
        month_sum_contexts, month_sum_meta = table_mode_contexts(db, month_sum_question, user, top_k=10)
        if month_sum_meta.get("time_value") != "2026-06" or "时间范围：2026-06" not in (month_sum_meta.get("table_query_explanation") or {}).get("summary", ""):
            raise AssertionError(f"month sum meta should expose time dimension, got {month_sum_meta}")
        month_sum_answer = build_table_answer(month_sum_question, month_sum_contexts)
        if "时间范围：2026-06" not in month_sum_answer or "上海：3800" not in month_sum_answer:
            raise AssertionError(f"month sum answer should explain time range and totals; meta={month_sum_meta}; answer={month_sum_answer}")

        multi_metric_question = "按城市统计公司数、缴费金额总和、平均公积金比例"
        multi_metric_plan = parse_table_query_plan(multi_metric_question).to_dict()
        multi_metric_labels = [item.get("label") for item in multi_metric_plan.get("metrics", [])]
        if multi_metric_plan.get("query_op") != "multi_metric_group" or multi_metric_plan.get("group_by") != "city" or not {"数量", "金额汇总", "公积金比例平均值"}.issubset(set(multi_metric_labels)):
            raise AssertionError(f"multi metric plan should detect grouped count/sum/avg metrics, got {multi_metric_plan}")
        multi_metric_contexts, multi_metric_meta = table_mode_contexts(db, multi_metric_question, user, top_k=10)
        if len(multi_metric_meta.get("metrics", [])) < 3 or "指标：数量、金额汇总、公积金比例平均值" not in (multi_metric_meta.get("table_query_explanation") or {}).get("summary", ""):
            raise AssertionError(f"multi metric meta should expose metric specs and explanation, got {multi_metric_meta}")
        multi_metric_answer = build_table_answer(multi_metric_question, multi_metric_contexts)
        if "查询操作：分组多指标统计" not in multi_metric_answer or "按城市多指标统计" not in multi_metric_answer:
            raise AssertionError(f"multi metric answer should explain multi metric grouping; meta={multi_metric_meta}; answer={multi_metric_answer}")
        if "城市=上海 | 数量=5 | 金额汇总=3800 | 公积金比例平均值=5.5" not in multi_metric_answer or "城市=北京 | 数量=2 | 金额汇总=800 | 公积金比例平均值=5" not in multi_metric_answer:
            raise AssertionError(f"multi metric answer should include expected grouped metrics; meta={multi_metric_meta}; answer={multi_metric_answer}")
        structured = build_table_structured_result(multi_metric_question, multi_metric_contexts)
        if structured.get("columns") != ["城市", "数量", "金额汇总", "公积金比例平均值"]:
            raise AssertionError(f"structured result should expose multi metric columns, got {structured}")
        if ["上海", 5, 3800.0, 5.5] not in structured.get("rows", []) or ["北京", 2, 800.0, 5.0] not in structured.get("rows", []):
            raise AssertionError(f"structured result should expose grouped metric rows, got {structured}")

        avg_question = "按城市统计公积金比例平均值"
        avg_plan = parse_table_query_plan(avg_question).to_dict()
        if avg_plan.get("query_op") != "avg_group" or avg_plan.get("aggregate_op") != "avg" or avg_plan.get("measure_column") != "fund_ratio":
            raise AssertionError(f"avg plan should detect grouped fund ratio average, got {avg_plan}")
        avg_contexts, avg_meta = table_mode_contexts(db, avg_question, user, top_k=10)
        if avg_meta.get("aggregate_op") != "avg" or avg_meta.get("measure_column") != "fund_ratio":
            raise AssertionError(f"avg retrieval meta should expose aggregate plan, got {avg_meta}")
        avg_answer = build_table_answer(avg_question, avg_contexts)
        if "查询操作：分组平均" not in avg_answer or "按城市平均值公积金比例" not in avg_answer:
            raise AssertionError(f"avg answer should explain grouped average; meta={avg_meta}; answer={avg_answer}")
        if "上海：5.5" not in avg_answer or "北京：5" not in avg_answer:
            raise AssertionError(f"avg answer should include expected city averages; meta={avg_meta}; answer={avg_answer}")

        max_question = "按城市统计缴费金额最大值"
        max_plan = parse_table_query_plan(max_question).to_dict()
        if max_plan.get("query_op") != "max_group" or max_plan.get("aggregate_op") != "max" or max_plan.get("measure_column") != "amount":
            raise AssertionError(f"max plan should detect grouped amount max, got {max_plan}")
        max_contexts, max_meta = table_mode_contexts(db, max_question, user, top_k=10)
        max_answer = build_table_answer(max_question, max_contexts)
        if "查询操作：分组最大值" not in max_answer or "上海：2500" not in max_answer or "北京：800" not in max_answer or "成都：200" not in max_answer:
            raise AssertionError(f"max answer should include expected city maximums; meta={max_meta}; answer={max_answer}")

        min_question = "按城市统计缴费金额最小值"
        min_plan = parse_table_query_plan(min_question).to_dict()
        if min_plan.get("query_op") != "min_group" or min_plan.get("aggregate_op") != "min" or min_plan.get("measure_column") != "amount":
            raise AssertionError(f"min plan should detect grouped amount min, got {min_plan}")
        min_contexts, min_meta = table_mode_contexts(db, min_question, user, top_k=10)
        min_answer = build_table_answer(min_question, min_contexts)
        if "查询操作：分组最小值" not in min_answer or "上海：300" not in min_answer or "北京：800" not in min_answer or "成都：200" not in min_answer:
            raise AssertionError(f"min answer should include expected city minimums; meta={min_meta}; answer={min_answer}")

        group_question = "有效网点按城市统计分别有多少个？"
        group_contexts, group_meta = table_mode_contexts(db, group_question, user, top_k=10)
        if group_meta.get("query_op") != "group_count":
            raise AssertionError(f"group query should be query_op=group_count, got {group_meta}")
        answer = build_table_answer(group_question, group_contexts)
        if "按城市统计" not in answer or "上海：5 条" not in answer or "北京：2 条" not in answer:
            raise AssertionError(f"grouped answer missing expected city counts; meta={group_meta}; answer={answer}")
        if "查询操作：分组计数" not in answer:
            raise AssertionError(f"answer should explain group_count operation; answer={answer}")

        top_question = "有效网点最多的前2个城市"
        top_plan = parse_table_query_plan(top_question).to_dict()
        if top_plan.get("query_op") != "group_count" or top_plan.get("group_by") != "city" or top_plan.get("sort_by") != "desc" or top_plan.get("limit") != 2:
            raise AssertionError(f"topN plan should detect grouped count, desc sort, and limit=2, got {top_plan}")
        top_contexts, top_meta = table_mode_contexts(db, top_question, user, top_k=10)
        if top_meta.get("sort_by") != "desc" or top_meta.get("limit") != 2:
            raise AssertionError(f"topN retrieval meta should expose sort/limit, got {top_meta}")
        top_explanation = top_meta.get("table_query_explanation") or {}
        if top_explanation.get("sort") != "降序" or top_explanation.get("limit") != 2 or "展开：前 2 项" not in top_explanation.get("summary", ""):
            raise AssertionError(f"topN retrieval meta should explain sort/limit, got {top_meta}")
        top_answer = build_table_answer(top_question, top_contexts)
        if "结果排序：按结果值降序，最多展开 2 项" not in top_answer:
            raise AssertionError(f"topN answer should explain desc limit; meta={top_meta}; answer={top_answer}")
        if "上海：5 条" not in top_answer or "北京：2 条" not in top_answer or "成都：1 条" in top_answer or "另有 1 个分组未展开" not in top_answer:
            raise AssertionError(f"topN answer should include only top 2 cities; meta={top_meta}; answer={top_answer}")

        bottom_question = "有效网点最少的前1个城市"
        bottom_plan = parse_table_query_plan(bottom_question).to_dict()
        if bottom_plan.get("query_op") != "group_count" or bottom_plan.get("group_by") != "city" or bottom_plan.get("sort_by") != "asc" or bottom_plan.get("limit") != 1:
            raise AssertionError(f"bottomN plan should detect grouped count, asc sort, and limit=1, got {bottom_plan}")
        bottom_contexts, bottom_meta = table_mode_contexts(db, bottom_question, user, top_k=10)
        bottom_answer = build_table_answer(bottom_question, bottom_contexts)
        if "结果排序：按结果值升序，最多展开 1 项" not in bottom_answer or "成都：1 条" not in bottom_answer or "北京：2 条" in bottom_answer:
            raise AssertionError(f"bottomN answer should include only the least city; meta={bottom_meta}; answer={bottom_answer}")

        distinct_question = "有效网点覆盖多少个城市？"
        distinct_contexts, distinct_meta = table_mode_contexts(db, distinct_question, user, top_k=10)
        if distinct_meta.get("query_op") != "distinct_count":
            raise AssertionError(f"distinct query should be query_op=distinct_count, got {distinct_meta}")
        distinct_answer = build_table_answer(distinct_question, distinct_contexts)
        if "共有 3 个城市" not in distinct_answer:
            raise AssertionError(f"distinct city answer should count 3 cities; meta={distinct_meta}; answer={distinct_answer}")
        if "查询操作：去重计数" not in distinct_answer:
            raise AssertionError(f"answer should explain distinct_count operation; answer={distinct_answer}")

        print("Table filter/group regression passed.")
    finally:
        db.close()
        engine.dispose()
        try:
            DB_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
