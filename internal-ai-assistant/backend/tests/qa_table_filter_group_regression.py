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
from app.table_query import build_table_answer  # noqa: E402
from app.table_retrieval import table_mode_contexts  # noqa: E402


def _row(
    row_id: str,
    row_number: int,
    city: str,
    company: str,
    status: str = "有效",
    bank_account: str = "已开通",
    fund_ratio: str = "8",
) -> DocumentTableRow:
    payload = {
        "城市": city,
        "公司名称": company,
        "网点状态": status,
        "当前进度": "已完成",
        "银行账户": bank_account,
        "公积金比例": fund_ratio,
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
                _row("row-sh-1", 2, "上海", "上海一号网点", bank_account="已开通", fund_ratio="8"),
                _row("row-sh-2", 3, "上海", "上海二号网点", bank_account="", fund_ratio=""),
                _row("row-sh-disabled", 4, "上海", "上海停用网点", "停用", bank_account="已开通", fund_ratio="3"),
                _row("row-bj-1", 5, "北京", "北京一号网点", bank_account="已开通", fund_ratio="5"),
                _row("row-cd-1", 6, "成都", "成都一号网点", bank_account="", fund_ratio=""),
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
        if "过滤条件：城市 等于 上海；状态 等于 有效" not in multi_answer:
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

        group_question = "有效网点按城市统计分别有多少个？"
        group_contexts, group_meta = table_mode_contexts(db, group_question, user, top_k=10)
        if group_meta.get("query_op") != "group_count":
            raise AssertionError(f"group query should be query_op=group_count, got {group_meta}")
        answer = build_table_answer(group_question, group_contexts)
        if "按城市统计" not in answer or "上海：5 条" not in answer or "北京：2 条" not in answer:
            raise AssertionError(f"grouped answer missing expected city counts; meta={group_meta}; answer={answer}")
        if "查询操作：分组计数" not in answer:
            raise AssertionError(f"answer should explain group_count operation; answer={answer}")

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
