from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Document, DocumentTableRow, User
from app.rag.query_analyzer import analyze_query
from app.rag.retrieval_router import select_route
from app.table_plan import parse_table_query_plan
from app.table_retrieval import table_mode_contexts


def _db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def _row(row_id: str, row_number: int, city: str, *, sheet: str = "202603", contact: str = "杨杰") -> DocumentTableRow:
    payload = {
        "序号": str(row_number - 2),
        "省份": "浙江" if city in {"宁波", "宁波北仑", "杭州"} else "上海",
        "城市": city,
        "后道对接人": contact,
        "单位名称": "外服（浙江）企业服务有限公司" if city in {"宁波", "宁波北仑"} else f"外服（浙江）企业服务有限公司{city}分公司",
        "操作规则-社保": "增减当月",
        "操作规则-医保": "增减当月",
        "操作规则-公积金": "增减当月",
        "截止时间-社保": "26号" if city in {"宁波", "宁波北仑", "杭州"} else "25号",
        "截止时间-医保": "26号" if city in {"宁波", "宁波北仑", "杭州"} else "25号",
        "截止时间-公积金": "18号" if city in {"宁波", "宁波北仑"} else "20号",
        "预计缴款时间-社保": "次月12号",
        "预计缴款时间-公积金": "当月20号" if city in {"宁波", "宁波北仑"} else "当月24号",
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-beilun-dispatch",
        sheet_name=sheet,
        row_number=row_number,
        row_key=f"{sheet}:{row_number}",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text=" | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=False,
    )


def _header(row_id: str, *, sheet: str = "202603") -> DocumentTableRow:
    payload = {
        "列1": "序号",
        "列2": "省份",
        "列3": "城市",
        "列4": "后道对接人",
        "列5": "单位名称",
        "列6": "操作规则-社保",
        "列7": "操作规则-医保",
        "列8": "操作规则-公积金",
        "列9": "截止时间-社保",
        "列10": "截止时间-医保",
        "列11": "截止时间-公积金",
        "列12": "预计缴款时间-社保",
        "列13": "预计缴款时间-公积金",
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-beilun-dispatch",
        sheet_name=sheet,
        row_number=None,
        row_key=f"{sheet}:header",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text="表头 | " + " | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=True,
    )


def test_beilun_dispatch_deadline_routes_to_table_and_matches_ningbo_row() -> None:
    db = _db_session()
    try:
        user = User(id="admin", username="admin", password_hash="x", is_admin=True, is_active=True)
        doc = Document(
            id="doc-beilun-dispatch",
            title="202603北仑派单截止时间",
            filename="202603北仑派单截止时间.xlsx",
            storage_path="fixture.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        db.add_all([
            user,
            doc,
            _header("row-header-202603"),
            _row("row-ningbo-202603", 3, "宁波"),
            _row("row-hangzhou-202603", 4, "杭州"),
            _row("row-shanghai-202603", 5, "上海"),
            _header("row-header-202510", sheet="202510"),
            _row("row-ningbo-202510", 3, "宁波", sheet="202510"),
        ])
        db.commit()

        question = "2026年3月北仑派单截止时间是什么时候？"
        analysis = analyze_query(question)
        route = select_route(analysis)
        assert route.name == "table"

        plan = parse_table_query_plan(question)
        assert plan.time_value == "2026-03"
        assert {"column": "city", "operator": "contains", "value": "北仑"} in plan.filters

        contexts, meta = table_mode_contexts(db, question, user, top_k=8)
        data_rows = [item for item in contexts if not item.get("is_header")]
        row_ids = [str(item.get("table_row_id")) for item in data_rows]
        assert row_ids == ["row-ningbo-202603"]
        assert meta["value_filter_matched_rows"] == 1
        assert meta["time_tokens"] == ["202603", "2026-03", "2026年3月", "2026年03月"]
    finally:
        db.close()


def test_beilun_alias_also_handles_short_month_and_field_question() -> None:
    db = _db_session()
    try:
        user = User(id="admin", username="admin", password_hash="x", is_admin=True, is_active=True)
        doc = Document(
            id="doc-beilun-dispatch",
            title="202603北仑派单截止时间",
            filename="202603北仑派单截止时间.xlsx",
            storage_path="fixture.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        db.add_all([
            user,
            doc,
            _header("row-header-202603"),
            _row("row-ningbo-202603", 3, "宁波"),
            _row("row-hangzhou-202603", 4, "杭州"),
            _header("row-header-202602", sheet="202602"),
            _row("row-ningbo-202602", 3, "宁波", sheet="202602"),
        ])
        db.commit()

        for question in [
            "北仑3月社保截止时间是哪天？",
            "北仑派单表里后道对接人是谁？",
        ]:
            analysis = analyze_query(question)
            route = select_route(analysis)
            assert route.name == "table"
            contexts, _meta = table_mode_contexts(db, question, user, top_k=8)
            data_rows = [item for item in contexts if not item.get("is_header")]
            assert data_rows
            assert str(data_rows[0].get("table_row_id")) == "row-ningbo-202603"
            assert all("杭州" not in str(item.get("content") or "") for item in data_rows)
    finally:
        db.close()


def _progress_row(row_id: str, row_number: int, city: str) -> DocumentTableRow:
    payload = {
        "省份": "浙江" if city in {"宁波北仑", "杭州"} else "北京",
        "城市": city,
        "当前进度-1.银行账户是否开具完成": "是",
        "当前进度-2.社保公积金账户是否开具完成": "是",
        "当前进度-3.公积金比例": "5%+5%、8%+8%、12+12%" if city == "宁波北仑" else "5%+5%",
        "当前进度-4.开设公司名称": "外服（浙江）企业服务有限公司" if city == "宁波北仑" else f"外服（浙江）企业服务有限公司{city}分公司",
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-beilun-progress",
        sheet_name="Sheet1",
        row_number=row_number,
        row_key=f"Sheet1:{row_number}",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text=" | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=False,
    )


def _progress_header(row_id: str) -> DocumentTableRow:
    payload = {
        "列1": "省份",
        "列2": "城市",
        "列3": "当前进度-1.银行账户是否开具完成",
        "列4": "当前进度-2.社保公积金账户是否开具完成",
        "列5": "当前进度-3.公积金比例",
        "列6": "当前进度-4.开设公司名称",
    }
    return DocumentTableRow(
        id=row_id,
        document_id="doc-beilun-progress",
        sheet_name="Sheet1",
        row_number=None,
        row_key="Sheet1:header",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text="表头 | " + " | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=True,
    )


def test_beilun_progress_questions_route_to_table_without_question_word_filters() -> None:
    for question, expected_select in [
        ("宁波北仑分公司的银行账户是否开具完成？", "bank_account"),
        ("北仑分公司的公积金比例是多少？", "fund_ratio"),
        ("宁波北仑社保公积金账户开好了吗？", "social_account"),
    ]:
        analysis = analyze_query(question)
        route = select_route(analysis)
        plan = parse_table_query_plan(question)
        assert route.name == "table"
        assert plan.query_op == "retrieve"
        assert expected_select in plan.select_columns
        assert not any(item.get("column") == expected_select for item in plan.filters)


def test_beilun_progress_alias_matches_ningbo_beilun_row() -> None:
    db = _db_session()
    try:
        user = User(id="admin", username="admin", password_hash="x", is_admin=True, is_active=True)
        doc = Document(
            id="doc-beilun-progress",
            title="北仑分公司开设最新进度表0310",
            filename="北仑分公司开设最新进度表0310.xlsx",
            storage_path="progress.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        db.add_all([
            user,
            doc,
            _progress_header("progress-header"),
            _progress_row("progress-ningbo-beilun", 3, "宁波北仑"),
            _progress_row("progress-beijing", 4, "北京"),
            _progress_row("progress-hangzhou", 5, "杭州"),
        ])
        db.commit()

        for question in [
            "宁波北仑分公司的银行账户是否开具完成？",
            "北仑分公司的公积金比例是多少？",
            "宁波北仑社保公积金账户开好了吗？",
        ]:
            contexts, _meta = table_mode_contexts(db, question, user, top_k=8)
            data_rows = [item for item in contexts if not item.get("is_header")]
            assert data_rows
            assert str(data_rows[0].get("table_row_id")) == "progress-ningbo-beilun"
            assert "城市=宁波北仑" in str(data_rows[0].get("content") or "")
    finally:
        db.close()
