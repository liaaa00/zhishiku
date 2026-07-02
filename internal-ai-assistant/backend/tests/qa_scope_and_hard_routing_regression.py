"""Regression coverage for knowledge-scope isolation and document-kind hard routing.

Run from internal-ai-assistant/backend:
    python -X utf8 tests/qa_scope_and_hard_routing_regression.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "qa_scope_and_hard_routing.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ.setdefault("DEFAULT_ADMIN_USERNAME", "scope_admin")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "scope_admin_password")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import main as app_main  # noqa: E402
from app import models, security  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.retrieval import adaptive_retrieve_contexts  # noqa: E402


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_scope_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def cleanup_storage() -> None:
    engine.dispose()
    for path in [DB_PATH, Path(str(DB_PATH) + "-wal"), Path(str(DB_PATH) + "-shm")]:
        if path.exists():
            try:
                path.unlink()
            except PermissionError:
                pass
    for path in UPLOAD_DIR.glob("qa_scope_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def add_doc(db, admin, *, doc_id: str, title: str, filename: str, content: str, scope: str, kind: str, source_type: str = "txt"):
    file_path = UPLOAD_DIR / f"qa_scope_{filename}"
    file_path.write_text(content, encoding="utf-8")
    doc = models.Document(
        id=doc_id,
        title=title,
        filename=filename,
        storage_path=str(file_path),
        source_type=source_type,
        knowledge_scope=scope,
        document_kind=kind,
        created_by=admin.id,
    )
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


def main() -> None:
    reset_storage()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    app_main.ensure_runtime_schema()

    db = SessionLocal()
    try:
        admin = models.User(
            id="scope-admin",
            username="scope_admin",
            password_hash=security.hash_password("scope_admin_password"),
            is_admin=True,
            is_active=True,
        )
        db.add(admin)
        db.flush()
        add_doc(
            db,
            admin,
            doc_id="scope-test-only",
            title="测试库员工指南",
            filename="scope_test_employee_guide.txt",
            content="员工通过微助手进入身份认证页面，完成个人注册和登录。",
            scope="test",
            kind="employee_guide",
        )
        add_doc(
            db,
            admin,
            doc_id="scope-test-personal",
            title="测试库个人附件身份认证表",
            filename="scope_test_personal.xlsx",
            content="[测试附件] 身份认证页面字段、微助手登录字段、个人注册字段。",
            scope="test",
            kind="form",
            source_type="chat_xlsx",
        )
        add_doc(
            db,
            admin,
            doc_id="scope-prod-guide",
            title="正式库员工指南",
            filename="scope_prod_employee_guide.txt",
            content="正式员工通过外服云员工服务入口查看电子签署提醒。",
            scope="production",
            kind="employee_guide",
        )
        add_doc(
            db,
            admin,
            doc_id="scope-prod-workorder",
            title="正式库工单系统需求",
            filename="scope_prod_workorder.txt",
            content="工单系统支持业务员配置字段、提交派单，并由合同组处理交付。",
            scope="production",
            kind="workorder",
        )
        db.commit()

        question = "员工怎么进入身份认证页面？"
        production_contexts, _backend, _note, _count, production_meta = adaptive_retrieve_contexts(db, question, admin, top_k=8)
        production_ids = [context.get("document_id") for context in production_contexts]
        if "scope-test-only" in production_ids or "scope-test-personal" in production_ids:
            raise AssertionError(f"production scope leaked test document: {production_ids}")
        if "scope-prod-guide" not in production_ids:
            raise AssertionError(f"production scope should find production guide: {production_ids}; meta={production_meta}")

        test_contexts, *_ = adaptive_retrieve_contexts(db, question, admin, top_k=8, knowledge_scope="test")
        test_ids = [context.get("document_id") for context in test_contexts]
        if not {"scope-test-only", "scope-test-personal"}.intersection(set(test_ids)) or "scope-prod-guide" in test_ids:
            raise AssertionError(f"test scope should only use test documents: {test_ids}")

        all_contexts, *_ = adaptive_retrieve_contexts(db, question, admin, top_k=8, knowledge_scope="all")
        all_ids = [context.get("document_id") for context in all_contexts]
        if "scope-prod-guide" not in all_ids or not {"scope-test-only", "scope-test-personal"}.intersection(set(all_ids)):
            raise AssertionError(f"all scope should include both test and production documents: {all_ids}")

        form_question = "员工信息表里需要填写哪些字段？"
        form_contexts, _backend, _note, _count, form_meta = adaptive_retrieve_contexts(db, form_question, admin, top_k=8, knowledge_scope="production")
        form_ids = [context.get("document_id") for context in form_contexts]
        if "scope-prod-workorder" in form_ids and form_meta.get("document_kind_filtered_count", 0) <= 0:
            raise AssertionError(f"workorder should be filtered for form_fields route: ids={form_ids}; meta={form_meta}")
        print("Scope and hard-routing regression passed.")
    finally:
        db.close()
        cleanup_storage()


if __name__ == "__main__":
    main()
