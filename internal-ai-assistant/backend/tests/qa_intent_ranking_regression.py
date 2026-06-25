"""Regression for intent-aware retrieval ranking.

Run from internal-ai-assistant/backend:
    python tests/qa_intent_ranking_regression.py

Covers:
- employee-side e-sign process questions prefer employee flow evidence even if
  the document title is generic;
- internal workflow / work-order noise is not selected for employee e-sign questions;
- internal workflow questions can still retrieve internal workflow material;
- table routing regression remains separated in qa_table_routing_regression.py.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "qa_intent_ranking_regression.sqlite3"

os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_intent_rank_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def add_doc(db, models, app_main, admin, group, doc_id: str, title: str, filename: str, content: str, source_type: str = "txt"):
    file_path = UPLOAD_DIR / filename
    file_path.write_text(content, encoding="utf-8")
    doc = models.Document(id=doc_id, title=title, filename=filename, storage_path=str(file_path), source_type=source_type, created_by=admin.id)
    doc.groups.append(group)
    db.add(doc)
    db.flush()
    db.add(models.DocumentChunk(
        id=f"{doc_id}-chunk-0",
        document_id=doc.id,
        page_number=1,
        chunk_index=0,
        content=content,
        embedding_json=json.dumps(app_main.embed_texts([content])[0]),
    ))
    return doc


def ids(contexts: list[dict]) -> list[str]:
    return [str(item.get("document_id") or "") for item in contexts]


def main() -> None:
    reset_storage()

    app_main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    security = importlib.import_module("app.security")
    retrieval = importlib.import_module("app.retrieval")

    database.Base.metadata.drop_all(bind=database.engine)
    database.Base.metadata.create_all(bind=database.engine)
    app_main.ensure_runtime_schema()

    db = database.SessionLocal()
    try:
        admin = models.User(id="qa-intent-admin", username="qa_intent_admin", password_hash=security.hash_password("qa_intent_admin_password"), is_admin=True, is_active=True)
        employee = models.User(id="qa-intent-user", username="qa_intent_user", password_hash=security.hash_password("qa_intent_user_password"), is_admin=False, is_active=True)
        group = models.Group(id="qa-intent-group", name="QA Intent Group")
        employee.groups.append(group)
        db.add_all([admin, employee, group])

        add_doc(
            db,
            models,
            app_main,
            admin,
            group,
            "qa-intent-generic-employee-esign",
            "员工服务操作说明2026",
            "qa_intent_rank_generic_employee_esign.txt",
            "员工收到短信后，登录外服云或微助手进入员工服务入口，打开电子合同页面，核对劳动合同信息后点击签署。签署完成后系统提示完成。",
        )
        add_doc(
            db,
            models,
            app_main,
            admin,
            group,
            "qa-intent-workorder-internal",
            "劳动合同续签工单系统需求说明",
            "qa_intent_rank_workorder_internal.txt",
            "劳动合同续签工单系统需求说明：HR在工单系统中发起续签申请，合同组内部审核并盖章归档。该材料用于内部审批流配置。",
        )
        add_doc(
            db,
            models,
            app_main,
            admin,
            group,
            "qa-intent-form-noise",
            "全职员工入职人员信息表",
            "qa_intent_rank_form_noise.xlsx",
            "表格数据 A1:员工姓名 B1:劳动合同起始日 C1:劳动合同终止日。全职员工入职人员信息表。",
            source_type="xlsx",
        )
        db.commit()

        employee = db.get(models.User, "qa-intent-user")
        employee_question = "劳动合同电子签流程是什么？"
        contexts, backend, note, _candidate_count, meta = retrieval.adaptive_retrieve_contexts(db, employee_question, employee, top_k=8)
        ranked_ids = ids(contexts)
        if not ranked_ids or ranked_ids[0] != "qa-intent-generic-employee-esign":
            raise AssertionError(f"employee e-sign doc should rank first, got {ranked_ids}; backend={backend}; note={note}; meta={meta}")
        if "qa-intent-workorder-internal" in ranked_ids:
            raise AssertionError(f"internal workorder should not be selected for employee e-sign question, got {ranked_ids}")
        if "qa-intent-form-noise" in ranked_ids:
            raise AssertionError(f"form-like context should not be selected for process question, got {ranked_ids}")
        ranking = contexts[0].get("intent_ranking") or {}
        if not ranking.get("positive_signals") or ranking.get("intent_score", 0) <= 0:
            raise AssertionError(f"intent ranking signals missing on top context: {ranking}")
        if meta.get("query_profile", {}).get("task") != "esign_process":
            raise AssertionError(f"query_profile should identify e-sign process: {meta.get('query_profile')}")

        internal_question = "合同组内部审核和盖章归档流程是什么？"
        internal_contexts, *_ = retrieval.adaptive_retrieve_contexts(db, internal_question, employee, top_k=8)
        internal_ids = ids(internal_contexts)
        if "qa-intent-workorder-internal" not in internal_ids[:3]:
            raise AssertionError(f"internal workflow question should retrieve internal workorder evidence, got {internal_ids}")

    finally:
        db.close()

    print("Intent-aware retrieval ranking regression passed.")


if __name__ == "__main__":
    main()
