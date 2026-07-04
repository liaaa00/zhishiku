from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.ai_client import embed_texts
from app.database import Base, get_db
from app.models import ChatMessage, ChatSession, Document, DocumentChunk, DocumentProcessingStatus, Feedback, User
from app.routers.admin_operations import router as admin_operations_router
from app.routers.deps import require_admin


def make_client() -> TestClient:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True, approval_status="approved")
        doc = Document(
            id="doc-ops",
            title="报销制度",
            filename="policy.txt",
            storage_path="/tmp/policy.txt",
            source_type="txt",
            document_kind="policy",
            document_kind_confidence=0.42,
            document_kind_status="needs_review",
            created_by="admin",
        )
        status = DocumentProcessingStatus(document_id="doc-ops", user_id="admin", status="ready", stage="indexed", searchable=True, message="ready", chunks=1)
        chunk_text = "报销制度要求员工提交发票、审批单和付款信息，财务会按制度流程复核。"
        chunk = DocumentChunk(
            id="doc-ops-chunk-1",
            document_id="doc-ops",
            page_number=1,
            chunk_index=0,
            content=chunk_text,
            embedding_json=json.dumps(embed_texts([chunk_text])[0]),
        )
        session = ChatSession(id="session-1", user_id="admin")
        question = ChatMessage(id="msg-q", session_id="session-1", role="user", content="报销要什么材料？")
        answer = ChatMessage(id="msg-a", session_id="session-1", role="assistant", content="未在知识库中找到可靠依据。", sources_json="[]")
        feedback = Feedback(id="fb-ops", user_id="admin", username="admin", rating="unhelpful", category="not_helpful", content="没有答出来", status="new", root_cause="retrieval_miss")
        db.add_all([admin, doc, status, chunk, session, question, answer, feedback])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_operations_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True, approval_status="approved")
    return TestClient(app)


def test_operations_overview_reports_risks_and_unanswered_questions() -> None:
    client = make_client()

    resp = client.get("/api/admin/operations/overview")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["documents"]["total"] == 1
    assert payload["documents"]["searchable"] == 1
    assert payload["documents"]["needs_review_classification"] == 1
    assert payload["feedback"]["new"] == 1
    assert payload["chat"]["recent_unanswered"]
    assert payload["risk_signals"]
    assert payload["recommendations"]


def test_prompt_templates_can_be_saved_and_reset() -> None:
    client = make_client()

    initial = client.get("/api/admin/prompt-templates")
    assert initial.status_code == 200
    assert initial.json()["templates"]

    save_resp = client.put(
        "/api/admin/prompt-templates",
        json={"templates": [{"key": "policy_custom", "label": "制度回答", "document_kind": "policy", "enabled": True, "content": "必须引用制度来源。"}]},
    )
    assert save_resp.status_code == 200
    assert save_resp.json()["templates"][0]["key"] == "policy_custom"

    reloaded = client.get("/api/admin/prompt-templates")
    assert reloaded.status_code == 200
    assert reloaded.json()["templates"][0]["content"] == "必须引用制度来源。"

    reset_resp = client.post("/api/admin/prompt-templates/reset")
    assert reset_resp.status_code == 200
    assert len(reset_resp.json()["templates"]) >= 1


def test_prompt_template_preview_returns_matched_templates_rules_and_sources() -> None:
    client = make_client()

    resp = client.post(
        "/api/admin/prompt-templates/preview",
        json={"question": "报销需要提交哪些材料？", "top_k": 5, "knowledge_scope": "production"},
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["prompt_template"]["count"] >= 1
    assert payload["rules_preview"]["template_instructions"]
    assert payload["matched_document_kinds"]
    assert payload["source_diagnostics"]


def test_prompt_template_compare_returns_two_variants_in_dry_run() -> None:
    client = make_client()

    resp = client.post(
        "/api/admin/prompt-templates/compare",
        json={
            "question": "报销需要提交哪些材料？",
            "template_a_keys": ["general"],
            "template_b_keys": ["policy"],
            "top_k": 5,
            "knowledge_scope": "production",
            "dry_run": True,
        },
    )

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["dry_run"] is True
    assert payload["variant_a"]["prompt_template"]["keys"] == ["general"]
    assert payload["variant_b"]["prompt_template"]["keys"] == ["policy"]
    assert payload["variant_a"]["answer"]
    assert payload["variant_b"]["answer"]
    assert payload["source_diagnostics"]


def test_prompt_template_adoption_is_recorded_summarized_and_used_as_recommendation() -> None:
    client = make_client()

    save_resp = client.put(
        "/api/admin/prompt-templates",
        json={
            "templates": [
                {"key": "policy", "label": "制度默认回答", "document_kind": "policy", "enabled": True, "content": "按制度流程回答。"},
                {"key": "policy_concise", "label": "制度简洁回答", "document_kind": "general", "enabled": True, "content": "先给结论，再列材料清单。"},
                {"key": "general", "label": "通用知识库问答", "document_kind": "general", "enabled": True, "content": "只基于知识库回答。"},
            ]
        },
    )
    assert save_resp.status_code == 200

    create_resp = client.post(
        "/api/admin/prompt-templates/adoptions",
        json={
            "question": "报销需要提交哪些材料？",
            "selected_variant": "a",
            "selected_template_keys": ["policy_concise"],
            "rejected_template_keys": ["policy"],
            "document_kinds": ["policy"],
            "source_document_ids": ["doc-ops"],
            "admin_note": "A 更清晰",
            "dry_run": True,
        },
    )
    assert create_resp.status_code == 200
    item = create_resp.json()["item"]
    assert item["selected_variant"] == "a"
    assert item["selected_template_keys"] == ["policy_concise"]

    list_resp = client.get("/api/admin/prompt-templates/adoptions")
    assert list_resp.status_code == 200
    stats = list_resp.json()["stats"]
    assert stats["total"] == 1
    assert stats["by_template"][0]["key"] == "policy_concise"
    assert stats["by_template"][0]["wins"] == 1
    assert stats["recommended_by_document_kind"][0]["kind"] == "policy"
    assert stats["recommended_by_document_kind"][0]["template"] == "policy_concise"

    preview_resp = client.post(
        "/api/admin/prompt-templates/preview",
        json={"question": "报销需要提交哪些材料？", "top_k": 5, "knowledge_scope": "production"},
    )
    assert preview_resp.status_code == 200
    prompt_template = preview_resp.json()["prompt_template"]
    assert prompt_template["keys"][:2] == ["policy_concise", "policy"]
    assert prompt_template["recommended"][0]["kind"] == "policy"
    assert prompt_template["recommended"][0]["key"] == "policy_concise"

    overview_resp = client.get("/api/admin/operations/overview")
    assert overview_resp.status_code == 200
    prompt_adoptions = overview_resp.json()["prompt_adoptions"]
    assert prompt_adoptions["total"] == 1
    assert prompt_adoptions["recommended_by_document_kind"][0]["template"] == "policy_concise"
