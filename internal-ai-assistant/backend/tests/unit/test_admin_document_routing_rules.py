from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai_client import embed_texts
from app.database import Base, get_db
from app.models import Document, DocumentChunk, User
from app.routers.admin_documents import router as admin_documents_router
from app.routers.admin_routing_rules import router as admin_routing_rules_router
from app.routers.deps import require_admin


def make_client(tmp_path: Path):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True, approval_status="approved")
        source = tmp_path / "finance_policy.txt"
        source.write_text("报销流程、发票要求和付款审批规则。", encoding="utf-8")
        doc = Document(
            id="finance-doc",
            title="费用报销制度",
            filename="finance_policy.txt",
            storage_path=str(source),
            source_type="txt",
            knowledge_scope="production",
            document_kind="general",
            created_by=admin.id,
        )
        chunk = DocumentChunk(
            id="finance-doc-chunk-0",
            document_id=doc.id,
            page_number=1,
            chunk_index=0,
            content="报销流程、发票要求和付款审批规则。",
            embedding_json=json.dumps(embed_texts(["报销流程、发票要求和付款审批规则。"])[0]),
        )
        db.add_all([admin, doc, chunk])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_routing_rules_router)
    app.include_router(admin_documents_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True, approval_status="approved")
    return TestClient(app), Session


def test_admin_can_configure_reclassify_and_confirm_document_kind(tmp_path: Path) -> None:
    client, Session = make_client(tmp_path)

    config_resp = client.get("/api/admin/document-routing/config")
    assert config_resp.status_code == 200
    config = config_resp.json()["config"]
    config["document_kinds"].insert(0, {"value": "finance", "label": "财务制度", "extensions": [], "markers": ["报销", "发票", "付款审批"]})

    save_resp = client.put("/api/admin/document-routing/config", json={"config": config})
    assert save_resp.status_code == 200
    assert any(item["value"] == "finance" for item in save_resp.json()["document_kind_options"])

    reclassify_resp = client.post("/api/admin/document-routing/reclassify", json={"knowledge_scope": "production"})
    assert reclassify_resp.status_code == 200
    assert reclassify_resp.json()["changed"] == 1

    db = Session()
    try:
        doc = db.execute(select(Document).where(Document.id == "finance-doc")).scalar_one()
        assert doc.document_kind == "finance"
        assert doc.document_kind_status in {"auto", "needs_review"}
    finally:
        db.close()

    confirm_resp = client.put("/api/admin/documents/finance-doc/classification", json={"document_kind": "general"})
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["document_kind"] == "general"
    assert confirm_resp.json()["document_kind_status"] == "confirmed"



def test_disabled_document_kind_is_persisted_but_excluded_from_options_classification_and_routes(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)

    config_resp = client.get("/api/admin/document-routing/config")
    assert config_resp.status_code == 200
    config = config_resp.json()["config"]
    config["document_kinds"] = [
        {"value": "finance", "label": "财务制度", "extensions": [], "markers": ["报销", "发票", "付款审批"], "disabled": True},
        {"value": "general", "label": "通用/其他文档", "extensions": [], "markers": [], "disabled": True},
    ]
    config["route_rules"] = [
        {"topic": "form_fields", "route": "text", "allowed_kinds": ["finance", "general"]},
    ]

    save_resp = client.put("/api/admin/document-routing/config", json={"config": config})
    assert save_resp.status_code == 200
    saved = save_resp.json()["config"]
    options = save_resp.json()["document_kind_options"]

    finance_kind = next(item for item in saved["document_kinds"] if item["value"] == "finance")
    general_kind = next(item for item in saved["document_kinds"] if item["value"] == "general")
    assert finance_kind["disabled"] is True
    assert general_kind["disabled"] is False
    assert all(item["value"] != "finance" for item in options)
    assert any(item["value"] == "general" for item in options)
    assert saved["route_rules"] == [{"allowed_kinds": ["general"], "topic": "form_fields", "route": "text"}]

    reclassify_resp = client.post("/api/admin/document-routing/reclassify", json={"knowledge_scope": "production"})
    assert reclassify_resp.status_code == 200
    first_result = reclassify_resp.json()["results"][0]
    assert first_result["document_kind"] == "general"


def test_document_diagnostics_returns_classification_quality_and_chunks(tmp_path: Path) -> None:
    client, _ = make_client(tmp_path)

    resp = client.get("/api/admin/documents/finance-doc/diagnostics")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["document"]["id"] == "finance-doc"
    assert payload["classification"]["kind"] == "general"
    assert "processing" in payload
    assert payload["quality"] is not None
    assert payload["chunk_preview"]
