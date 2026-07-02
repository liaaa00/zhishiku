"""Regression for real table QA issues found in uploaded documents.

Run from internal-ai-assistant/backend:
    python tests/qa_table_real_question_regression.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_table_real_question.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Document, DocumentTableRow, User  # noqa: E402
from app.rag.query_analyzer import analyze_query  # noqa: E402
from app.rag.retrieval_router import select_route  # noqa: E402
from app.table_query import build_table_answer  # noqa: E402
from app.table_retrieval import table_mode_contexts  # noqa: E402


def _row(doc_id: str, row_id: str, sheet: str, row_number: int, payload: dict[str, str]) -> DocumentTableRow:
    return DocumentTableRow(
        id=row_id,
        document_id=doc_id,
        sheet_name=sheet,
        row_number=row_number,
        row_key=f"{sheet}:{row_number}",
        row_json=json.dumps(payload, ensure_ascii=False),
        row_text=" | ".join(f"{key}={value}" for key, value in payload.items()),
        is_header=False,
    )


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(id="admin", username="admin", password_hash="x", is_admin=True)
        dispatch_doc = Document(
            id="doc-dispatch",
            title="202603北仑派单截止时间",
            filename="202603北仑派单截止时间.xlsx",
            storage_path="dispatch.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        progress_doc = Document(
            id="doc-progress",
            title="北仑分公司开设最新进度表0310",
            filename="北仑分公司开设最新进度表0310.xlsx",
            storage_path="progress.xlsx",
            source_type="xlsx",
            created_by="admin",
        )
        db.add_all([user, dispatch_doc, progress_doc])
        db.add_all(
            [
                _row("doc-dispatch", "sz-202512", "202512", 17, {
                    "省份": "广东",
                    "城市": "深圳",
                    "单位名称": "外服（浙江）企业服务有限公司深圳分公司",
                    "截止时间-社保": "26号",
                    "截止时间-医保": "26号",
                    "截止时间-公积金": "24号",
                    "备注": "若原单位停保至当月底，新单位参保过程中不会有任何提示",
                }),
                _row("doc-dispatch", "bj-202512", "202512", 7, {
                    "省份": "北京",
                    "城市": "北京",
                    "单位名称": "外服（浙江）企业服务有限公司北京分公司",
                    "截止时间-社保": "25号",
                    "截止时间-医保": "25号",
                    "截止时间-公积金": "25号",
                }),
                _row("doc-dispatch", "xa-202510", "202510", 12, {
                    "省份": "陕西",
                    "城市": "西安",
                    "单位名称": "外服（浙江）企业服务有限公司西安分公司",
                    "截止时间-社保": "22号",
                    "截止时间-医保": "22号",
                    "截止时间-公积金": "24号",
                }),
                _row("doc-dispatch", "xa-202511", "202511", 12, {
                    "省份": "陕西",
                    "城市": "西安",
                    "单位名称": "外服（浙江）企业服务有限公司西安分公司",
                    "截止时间-社保": "23号",
                    "截止时间-医保": "23号",
                    "截止时间-公积金": "25号",
                }),
                _row("doc-progress", "beilun", "Sheet1", 3, {
                    "省份": "浙江",
                    "城市": "宁波北仑",
                    "当前进度-1.银行账户是否开具完成": "是",
                    "当前进度-2.社保公积金账户是否开具完成": "是",
                    "当前进度-3.公积金比例": "5%+5%",
                    "当前进度-4.开设公司名称": "外服（浙江）企业服务有限公司",
                }),
                _row("doc-progress", "chengdu", "Sheet1", 8, {
                    "省份": "四川",
                    "城市": "成都",
                    "当前进度-1.银行账户是否开具完成": "是",
                    "当前进度-2.社保公积金账户是否开具完成": "是",
                    "当前进度-3.公积金比例": "5%-12%全比例",
                    "当前进度-4.开设公司名称": "外服（浙江）企业服务有限公司成都分公司",
                }),
                _row("doc-progress", "shanghai", "Sheet1", 6, {
                    "省份": "上海",
                    "城市": "上海",
                    "当前进度-1.银行账户是否开具完成": "是",
                    "当前进度-2.社保公积金账户是否开具完成": "是",
                    "当前进度-3.公积金比例": "5%+5%（补充公积金2%+2%）",
                    "当前进度-4.开设公司名称": "外服（浙江）企业服务有限公司上海分公司",
                }),
            ]
        )
        db.commit()

        shenzhen_q = "2025年12月深圳社保、医保、公积金截止时间分别是哪天？有什么备注？"
        contexts, meta = table_mode_contexts(db, shenzhen_q, user, top_k=10)
        row_ids = {item.get("table_row_id") for item in contexts if not item.get("is_header")}
        if row_ids != {"sz-202512"}:
            raise AssertionError(f"深圳多条件过滤应只保留深圳行，got {row_ids}; meta={meta}")
        answer = build_table_answer(shenzhen_q, contexts)
        if "深圳" not in answer or "北京" in answer or "备注=" not in answer:
            raise AssertionError(f"深圳答案应只含深圳和备注，answer={answer}")

        compare_q = "西安在2025年10月和11月的社保、医保、公积金截止时间有什么变化？"
        contexts, meta = table_mode_contexts(db, compare_q, user, top_k=10)
        row_ids = {item.get("table_row_id") for item in contexts if not item.get("is_header")}
        if not {"xa-202510", "xa-202511"}.issubset(row_ids):
            raise AssertionError(f"跨月份对比应命中 10/11 两个月，got {row_ids}; meta={meta}")
        answer = build_table_answer(compare_q, contexts)
        if "2025-10" not in answer or "2025-11" not in answer or "变化字段" not in answer:
            raise AssertionError(f"跨月份答案应按月份对比，answer={answer}")

        account_q = "北仑分公司银行账户和社保公积金账户是否都已开具完成？"
        contexts, meta = table_mode_contexts(db, account_q, user, top_k=10)
        row_ids = {item.get("table_row_id") for item in contexts if not item.get("is_header")}
        if row_ids != {"beilun"}:
            raise AssertionError(f"账户问题应过滤掉派单表，只保留进度表，got {row_ids}; meta={meta}")

        ratio_q = "成都分公司的公积金比例范围是多少？"
        contexts, meta = table_mode_contexts(db, ratio_q, user, top_k=10)
        row_ids = {item.get("table_row_id") for item in contexts if not item.get("is_header")}
        if row_ids != {"chengdu"}:
            raise AssertionError(f"比例问题应只保留有公积金比例的进度表行，got {row_ids}; meta={meta}")

        shanghai_q = "上海分公司的公积金比例和补充公积金比例是什么？"
        route = select_route(analyze_query(shanghai_q))
        if route.name != "table":
            raise AssertionError(f"上海公积金比例问题应进入 table 路由，got {route}")
        contexts, meta = table_mode_contexts(db, shanghai_q, user, top_k=10)
        row_ids = {item.get("table_row_id") for item in contexts if not item.get("is_header")}
        answer = build_table_answer(shanghai_q, contexts)
        if row_ids != {"shanghai"} or "补充公积金2%+2%" not in answer:
            raise AssertionError(f"上海补充公积金比例应命中进度表并输出补充比例，got {row_ids}; answer={answer}; meta={meta}")

        print("Real table question regression passed.")
    finally:
        db.close()
        engine.dispose()
        try:
            DB_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
