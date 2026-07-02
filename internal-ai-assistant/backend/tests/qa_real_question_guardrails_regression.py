"""Guardrail regressions for real uploaded-document QA failures.

Run from internal-ai-assistant/backend:
    python tests/qa_real_question_guardrails_regression.py

These cases are intentionally grouped by failure mode, not by one-off wording,
so fixes reduce the chance of "A is fixed but B breaks".
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "qa_real_question_guardrails.sqlite3"
if DB_PATH.exists():
    DB_PATH.unlink()
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Document, DocumentTableRow, User  # noqa: E402
from app.rag.query_analyzer import analyze_query  # noqa: E402
from app.rag.retrieval_router import select_route  # noqa: E402
from app.table_plan import parse_table_query_plan  # noqa: E402
from app.table_query import build_table_answer, is_table_query  # noqa: E402
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


def _row_ids(contexts: list[dict]) -> set[str]:
    return {str(item.get("table_row_id")) for item in contexts if not item.get("is_header")}


def _assert_contains(text: str, *terms: str) -> None:
    missing = [term for term in terms if term not in text]
    if missing:
        raise AssertionError(f"missing terms {missing} in answer:\n{text}")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = User(id="admin", username="admin", password_hash="x", is_admin=True, is_active=True)
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
        text_doc = Document(
            id="doc-text",
            title="外服云平台个人注册操作指南",
            filename="外服云平台个人注册操作指南.pdf",
            storage_path="register.pdf",
            source_type="pdf",
            created_by="admin",
        )
        db.add_all([user, dispatch_doc, progress_doc, text_doc])
        db.add_all(
            [
                # Keep several earlier-sheet rows before the target 202512 row. This guards against
                # document prefiltering that only samples leading rows and misses later month sheets.
                _row("doc-dispatch", "early-202510-1", "202510", 1, {"省份": "浙江", "城市": "杭州", "单位名称": "杭州分公司", "截止时间-社保": "20号"}),
                _row("doc-dispatch", "early-202510-2", "202510", 2, {"省份": "浙江", "城市": "宁波", "单位名称": "宁波分公司", "截止时间-社保": "20号"}),
                _row("doc-dispatch", "early-202510-3", "202510", 3, {"省份": "广东", "城市": "深圳", "单位名称": "深圳分公司", "截止时间-社保": "20号"}),
                _row("doc-dispatch", "early-202510-4", "202510", 4, {"省份": "上海", "城市": "上海", "单位名称": "上海分公司", "截止时间-社保": "20号"}),
                _row("doc-dispatch", "early-202510-5", "202510", 5, {"省份": "四川", "城市": "成都", "单位名称": "成都分公司", "截止时间-社保": "20号"}),
                _row("doc-dispatch", "early-202510-6", "202510", 6, {"省份": "河南", "城市": "郑州", "单位名称": "郑州分公司", "截止时间-社保": "20号"}),
                _row("doc-dispatch", "bj-202512", "202512", 7, {
                    "省份": "北京",
                    "城市": "北京",
                    "单位名称": "外服（浙江）企业服务有限公司北京分公司",
                    "截止时间-社保": "25号",
                    "截止时间-医保": "25号",
                    "截止时间-公积金": "25号",
                    "后道对接人": "北京后道",
                    "备注": "工伤原单位仍在保时，新单位参保会产生工伤无法撤销风险。",
                }),
                _row("doc-dispatch", "sjz-202511", "202511", 9, {
                    "省份": "河北",
                    "城市": "石家庄",
                    "单位名称": "外服（浙江）企业服务有限公司石家庄分公司",
                    "截止时间-社保": "20号",
                    "截止时间-医保": "20号",
                    "截止时间-公积金": "18号",
                    "后道对接人": "石家庄后道",
                    "备注": "公积金同城转入需要原单位或者员工本人操作。",
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
                _row("doc-progress", "beijing-progress", "Sheet1", 7, {
                    "省份": "北京",
                    "城市": "北京",
                    "当前进度-1.银行账户是否开具完成": "是",
                    "当前进度-2.社保公积金账户是否开具完成": "是",
                    "当前进度-3.公积金比例": "5%+5%",
                    "当前进度-4.开设公司名称": "外服（浙江）企业服务有限公司北京分公司",
                }),
                _row("doc-progress", "hangzhou-unopened", "Sheet1", 10, {
                    "省份": "浙江",
                    "城市": "杭州",
                    "当前进度-1.银行账户是否开具完成": "否",
                    "当前进度-2.社保公积金账户是否开具完成": "否",
                    "当前进度-3.公积金比例": "未开设",
                    "当前进度-4.开设公司名称": "未开设",
                }),
                _row("doc-progress", "guiyang-unopened", "Sheet1", 11, {
                    "省份": "贵州", "城市": "贵阳", "当前进度-4.开设公司名称": "未开设",
                }),
                _row("doc-progress", "nanjing-unopened", "Sheet1", 12, {
                    "省份": "江苏", "城市": "南京", "当前进度-4.开设公司名称": "未开设",
                }),
                _row("doc-progress", "urumqi-unopened", "Sheet1", 13, {
                    "省份": "新疆", "城市": "乌鲁木齐", "当前进度-4.开设公司名称": "未开设",
                }),
            ]
        )
        db.commit()

        # Guardrail 1: text module/list questions should stay in text route, not table route.
        text_question = "外服云平台个人注册页列出了哪些主要模块？"
        if is_table_query(text_question):
            raise AssertionError("个人注册页模块问题不应进入 table 规则")
        route = select_route(analyze_query(text_question))
        if route.name == "table":
            raise AssertionError(f"个人注册页模块问题不应路由到 table，got {route}")

        # Guardrail 2: concrete city + completion/status fields should not turn into global branch-completion statistics.
        city_question = "成都分公司的银行账户、社保公积金账户是否已完成？公积金比例范围是什么？"
        contexts, meta = table_mode_contexts(db, city_question, user, top_k=10)
        if meta.get("branch_completion_filter"):
            raise AssertionError(f"具体城市问题不应触发全局分公司完成度过滤，meta={meta}")
        if _row_ids(contexts) != {"chengdu"}:
            raise AssertionError(f"成都问题应只命中成都行，got rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(city_question, contexts)
        _assert_contains(answer, "成都", "5%-12%全比例")
        if "共有 28 家" in answer or "银行账户、社保公积金账户、公积金比例、公司名称均已完成" in answer:
            raise AssertionError(f"成都问题不应输出全局完成度文案，answer={answer}")

        # Guardrail 3: multi-field city questions should keep the city row even when account status + ratio are both requested.
        shanghai_question = "上海分公司的银行账户和社保公积金账户状态是什么？公积金比例里补充公积金是多少？"
        contexts, meta = table_mode_contexts(db, shanghai_question, user, top_k=10)
        if _row_ids(contexts) != {"shanghai"}:
            raise AssertionError(f"上海多字段问题应命中上海进度行，got rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(shanghai_question, contexts)
        _assert_contains(answer, "上海", "银行账户", "社保公积金账户", "补充公积金2%+2%")

        shanghai_completion_question = "上海分公司当前银行账户和社保公积金账户是否完成？开设公司名称是什么？补充公积金比例是多少？"
        contexts, meta = table_mode_contexts(db, shanghai_completion_question, user, top_k=10)
        if meta.get("branch_completion_filter") or _row_ids(contexts) != {"shanghai"}:
            raise AssertionError(f"上海具体完成度问题不应触发全局完成度，rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(shanghai_completion_question, contexts)
        _assert_contains(answer, "银行账户=是", "社保公积金账户=是", "外服（浙江）企业服务有限公司上海分公司", "补充公积金2%+2%")

        beijing_detail_question = "北京分公司当前银行账户、社保公积金账户、公积金比例和开设公司名称分别是什么？"
        contexts, meta = table_mode_contexts(db, beijing_detail_question, user, top_k=10)
        if _row_ids(contexts) != {"beijing-progress"}:
            raise AssertionError(f"北京分别是什么问题应保留北京明细行，rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(beijing_detail_question, contexts)
        _assert_contains(answer, "银行账户=是", "社保公积金账户=是", "公积金比例=5%+5%", "北京分公司")
        if "统计结果" in answer:
            raise AssertionError(f"北京明细问题不应输出分组统计，answer={answer}")

        # Guardrail 4: city aliases and company + ratio fields should work together.
        beilun_question = "宁波北仑对应的开设公司名称是什么？公积金比例有哪些档位？"
        contexts, meta = table_mode_contexts(db, beilun_question, user, top_k=10)
        if _row_ids(contexts) != {"beilun"}:
            raise AssertionError(f"宁波北仑问题应命中北仑进度行，got rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(beilun_question, contexts)
        _assert_contains(answer, "宁波北仑", "外服（浙江）企业服务有限公司", "5%+5%")

        # Guardrail 5: quoted Chinese values should become value filters, including curly quotes.
        unopened_question = "开设公司名称为“未开设”的城市有哪些？"
        plan = parse_table_query_plan(unopened_question)
        if not any(item.get("column") == "company" and item.get("value") == "未开设" for item in plan.filters):
            raise AssertionError(f"应解析开设公司名称=未开设过滤条件，plan={plan.to_dict()}")
        contexts, meta = table_mode_contexts(db, unopened_question, user, top_k=10)
        if "hangzhou-unopened" not in _row_ids(contexts):
            raise AssertionError(f"未开设城市问题应命中未开设行，got rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(unopened_question, contexts)
        _assert_contains(answer, "杭州", "未开设")

        unopened_contains_question = "开设公司名称为未开设的城市里，是否包含贵阳、南京和乌鲁木齐？"
        contexts, meta = table_mode_contexts(db, unopened_contains_question, user, top_k=10)
        row_ids = _row_ids(contexts)
        if not {"guiyang-unopened", "nanjing-unopened", "urumqi-unopened"}.issubset(row_ids):
            raise AssertionError(f"未开设多城市包含问题应按 OR 命中多个城市，got rows={row_ids}, meta={meta}")
        answer = build_table_answer(unopened_contains_question, contexts)
        _assert_contains(answer, "贵阳", "南京", "乌鲁木齐", "未开设")

        # Guardrail 6: deadline/rule questions that ask who operates should preserve remark and backend-contact evidence.
        sjz_question = "2025年11月石家庄公积金同城转入需要谁来操作？同时给出公积金截止时间。"
        contexts, meta = table_mode_contexts(db, sjz_question, user, top_k=10)
        if _row_ids(contexts) != {"sjz-202511"}:
            raise AssertionError(f"石家庄同城转入问题应命中石家庄 202511 行，got rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(sjz_question, contexts)
        _assert_contains(answer, "原单位或者员工本人操作", "截止时间-公积金=18号")

        # Guardrail 7: risk-in-remark questions should not lose rows just because remark is requested.
        bj_question = "2025年12月北京的备注里，原单位仍在保时新单位参保会产生什么风险？"
        contexts, meta = table_mode_contexts(db, bj_question, user, top_k=10)
        if _row_ids(contexts) != {"bj-202512"}:
            raise AssertionError(f"北京备注风险问题应命中北京 202512 行，got rows={_row_ids(contexts)}, meta={meta}")
        answer = build_table_answer(bj_question, contexts)
        _assert_contains(answer, "工伤", "无法撤销", "备注")

        print("Real question guardrail regression passed.")
    finally:
        db.close()
        engine.dispose()
        try:
            DB_PATH.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()
