"""Regression coverage for backend-configurable document kind and routing rules.

Run from internal-ai-assistant/backend:
    python -X utf8 tests/qa_configurable_routing_rules_regression.py
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
DB_PATH = DATA_DIR / "qa_configurable_routing.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH.as_posix()}"
os.environ["VECTOR_BACKEND"] = "local"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ.setdefault("DEFAULT_ADMIN_USERNAME", "routing_admin")
os.environ.setdefault("DEFAULT_ADMIN_PASSWORD", "routing_admin_password")

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import main as app_main  # noqa: E402
from app import models, security  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.document_routing_config import (  # noqa: E402
    allowed_kinds_for_query_topic_config,
    default_document_routing_config,
    infer_document_kind_from_config,
    set_document_routing_config,
)
from app.routers.admin_routing_rules import ReclassifyPayload, reclassify_documents  # noqa: E402
from app.retrieval import adaptive_retrieve_contexts  # noqa: E402


def reset_storage() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        path = Path(str(DB_PATH) + suffix)
        if path.exists():
            path.unlink()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in UPLOAD_DIR.glob("qa_routing_*"):
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
    for path in UPLOAD_DIR.glob("qa_routing_*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def add_doc(db, admin, *, doc_id: str, title: str, filename: str, content: str, kind: str = "general"):
    file_path = UPLOAD_DIR / f"qa_routing_{filename}"
    file_path.write_text(content, encoding="utf-8")
    doc = models.Document(
        id=doc_id,
        title=title,
        filename=filename,
        storage_path=str(file_path),
        source_type=filename.rsplit(".", 1)[-1] if "." in filename else "txt",
        knowledge_scope="production",
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
            id="routing-admin",
            username="routing_admin",
            password_hash=security.hash_password("routing_admin_password"),
            is_admin=True,
            is_active=True,
        )
        db.add(admin)
        db.flush()

        default_allowed = allowed_kinds_for_query_topic_config(db, "employee_portal", "text")
        if not {"employee_guide", "general", "policy"}.issubset(default_allowed):
            raise AssertionError(f"default route rules changed unexpectedly: {default_allowed}")

        config = default_document_routing_config()
        config["document_kinds"].insert(0, {"value": "finance", "label": "财务制度", "extensions": [], "markers": ["报销", "发票", "付款审批"]})
        config["route_rules"].insert(0, {"topic": "employee_portal", "route": "text", "allowed_kinds": ["finance"]})
        set_document_routing_config(db, config)
        db.commit()

        inferred = infer_document_kind_from_config(db, "费用报销制度", "finance_policy.txt", "txt", "报销流程、发票要求和付款审批规则。")
        if inferred.get("kind") != "finance" or float(inferred.get("confidence") or 0) < 0.5:
            raise AssertionError(f"custom kind should classify finance document: {inferred}")

        finance_doc = add_doc(db, admin, doc_id="finance-doc", title="费用报销制度", filename="finance_policy.txt", content="费用报销制度说明：报销流程、发票要求和付款审批规则。", kind="general")
        guide_doc = add_doc(db, admin, doc_id="guide-doc", title="员工服务指南", filename="employee_guide.txt", content="员工通过外服云员工服务入口查看实名认证页面。", kind="employee_guide")
        db.commit()

        result = reclassify_documents(ReclassifyPayload(knowledge_scope="production"), db=db, actor=admin)
        db.refresh(finance_doc)
        if result.get("total") != 2 or finance_doc.document_kind != "finance":
            raise AssertionError(f"reclassify should update finance doc: result={result}; kind={finance_doc.document_kind}")

        contexts, _backend, _note, _count, meta = adaptive_retrieve_contexts(db, "员工服务入口怎么查看？", admin, top_k=8, knowledge_scope="production")
        ids = [context.get("document_id") for context in contexts]
        if "guide-doc" in ids:
            raise AssertionError(f"configured hard route should filter employee_guide when only finance allowed: ids={ids}; meta={meta}")
        if meta.get("allowed_document_kinds") != ["finance"]:
            raise AssertionError(f"meta should expose configured allowed kinds: {meta.get('allowed_document_kinds')}")

        print("Configurable routing rules regression passed.")
    finally:
        db.close()
        cleanup_storage()


if __name__ == "__main__":
    main()
