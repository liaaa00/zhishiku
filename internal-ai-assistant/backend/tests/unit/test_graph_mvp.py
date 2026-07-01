from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.graph_retrieval import retrieve_graph_contexts
from app.graph_schema import normalize_relation_type
from app.graph_extraction import extract_graph_for_document
from app.graph_store import create_relation, get_or_create_entity, normalize_entity_name, set_extraction_status
from app import task_service
from app.models import BackgroundTask, Document, DocumentChunk, GraphExtractionStatus, GraphRelation, Group, User
from app.routers.admin_graph import router as admin_graph_router
from app.routers.deps import require_admin


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session


def test_graph_entity_normalization_and_relation_create() -> None:
    Session = make_session()
    db = Session()
    try:
        doc = Document(id="doc1", title="入职流程", filename="入职流程.txt", storage_path="x", source_type="txt")
        chunk = DocumentChunk(id="chunk1", document_id="doc1", chunk_index=0, page_number=1, content="入职需要派出工单", embedding_json="[]")
        db.add_all([doc, chunk])
        db.flush()

        assert normalize_entity_name(" 入 职（流程） ") == "入职流程"
        source = get_or_create_entity(db, "入职", "process", 0.9)
        duplicate = get_or_create_entity(db, " 入 职 ", "process", 0.8)
        target = get_or_create_entity(db, "工单系统", "system", 0.9)
        assert source is not None and duplicate is not None and target is not None
        assert source.id == duplicate.id

        relation = create_relation(
            db,
            source,
            target,
            normalize_relation_type("uses_system"),
            document_id=doc.id,
            chunk_id=chunk.id,
            page_number=1,
            evidence_text="入职流程使用工单系统派单",
            confidence=0.9,
            status="auto",
        )
        db.commit()
        assert relation is not None
        rows = db.execute(select(GraphRelation)).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == "auto"
    finally:
        db.close()


def test_graph_retrieval_filters_inaccessible_documents() -> None:
    Session = make_session()
    db = Session()
    try:
        allowed_group = Group(id="g1", name="人事")
        denied_group = Group(id="g2", name="财务")
        user = User(id="u1", username="u", password_hash="", is_admin=False, is_active=True)
        user.groups.append(allowed_group)
        allowed_doc = Document(id="doc-allow", title="入职", filename="入职.txt", storage_path="x", source_type="txt")
        denied_doc = Document(id="doc-deny", title="离职", filename="离职.txt", storage_path="x", source_type="txt")
        allowed_doc.groups.append(allowed_group)
        denied_doc.groups.append(denied_group)
        db.add_all([allowed_group, denied_group, user, allowed_doc, denied_doc])
        db.flush()
        chunk1 = DocumentChunk(id="c1", document_id=allowed_doc.id, chunk_index=0, page_number=1, content="入职使用工单系统", embedding_json="[]")
        chunk2 = DocumentChunk(id="c2", document_id=denied_doc.id, chunk_index=0, page_number=1, content="入职使用保密系统", embedding_json="[]")
        db.add_all([chunk1, chunk2])
        db.flush()

        source = get_or_create_entity(db, "入职", "process", 0.9)
        target1 = get_or_create_entity(db, "工单系统", "system", 0.9)
        target2 = get_or_create_entity(db, "保密系统", "system", 0.9)
        assert source and target1 and target2
        create_relation(db, source, target1, "uses_system", allowed_doc.id, chunk1.id, 1, "入职使用工单系统", 0.9, "auto")
        create_relation(db, source, target2, "uses_system", denied_doc.id, chunk2.id, 1, "入职使用保密系统", 0.9, "auto")
        db.commit()

        db.refresh(user)
        contexts = retrieve_graph_contexts(db, "入职", user, top_k=10)
        assert len(contexts) == 1
        assert contexts[0]["document_id"] == allowed_doc.id
        assert "保密系统" not in contexts[0]["content"]
    finally:
        db.close()


def test_admin_graph_api_overview_relation_review_and_search() -> None:
    Session = make_session()
    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True)
        doc = Document(id="doc1", title="入职流程", filename="入职.txt", storage_path="x", source_type="txt")
        chunk = DocumentChunk(id="c1", document_id=doc.id, chunk_index=0, page_number=1, content="入职使用工单系统", embedding_json="[]")
        db.add_all([admin, doc, chunk])
        db.flush()
        source = get_or_create_entity(db, "入职", "process", 0.9)
        target = get_or_create_entity(db, "工单系统", "system", 0.9)
        assert source and target
        relation = create_relation(db, source, target, "uses_system", doc.id, chunk.id, 1, "入职使用工单系统", 0.7, "pending")
        assert relation is not None
        set_extraction_status(db, doc.id, "ready", entity_count=2, relation_count=1, pending_count=1)
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_graph_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True)

    client = TestClient(app)
    overview = client.get("/api/admin/graph/overview")
    assert overview.status_code == 200
    assert overview.json()["pending_count"] == 1

    relations = client.get("/api/admin/graph/relations?status=pending")
    assert relations.status_code == 200
    relation_id = relations.json()[0]["id"]

    updated = client.put(f"/api/admin/graph/relations/{relation_id}", json={"status": "confirmed"})
    assert updated.status_code == 200
    assert updated.json()["status"] == "confirmed"

    search = client.post("/api/admin/graph/search-test", json={"question": "入职", "top_k": 5})
    assert search.status_code == 200
    assert search.json()["count"] == 1
    assert search.json()["contexts"][0]["retrieval_channel"] == "graph"


def test_spreadsheet_graph_extract_uses_rule_based_rows(monkeypatch) -> None:
    Session = make_session()
    db = Session()
    try:
        doc = Document(id="doc-xlsx", title="202603北仑派单截止时间", filename="202603北仑派单截止时间.xlsx", storage_path="x", source_type="xlsx")
        chunk = DocumentChunk(
            id="chunk-xlsx",
            document_id=doc.id,
            chunk_index=0,
            page_number=1,
            content="表格行 | 工作表=202603 | Excel行=3 | 省份=浙江 | 城市=宁波 | 单位名称=外服（浙江）企业服务有限公司 | 操作规则-社保=增减当月 | 操作规则-医保=增减当月 | 截止时间-社保=24号 | 截止时间-医保=24号 | 截止时间-公积金=17号",
            embedding_json="[]",
        )
        db.add_all([doc, chunk])
        db.commit()

        def fail_llm(*_args, **_kwargs):
            raise AssertionError("spreadsheet chunks should not call LLM graph extraction")

        monkeypatch.setattr("app.graph_extraction.extract_graph_from_text", fail_llm)
        result = extract_graph_for_document(db, doc.id)
        db.commit()

        assert result["status"] == "ready"
        assert result["entity_count"] >= 5
        assert result["relation_count"] >= 5
        descriptions = [row.description for row in db.execute(select(GraphRelation).where(GraphRelation.source_document_id == doc.id)).scalars().all()]
        assert any("宁波 社保 派单截止时间为 24号" in item for item in descriptions)
        assert any("宁波 派单由 外服（浙江）企业服务有限公司 处理" in item for item in descriptions)
    finally:
        db.close()



def test_document_parse_success_enqueues_graph_extract(monkeypatch) -> None:
    Session = make_session()
    monkeypatch.setattr(task_service, "SessionLocal", Session)
    monkeypatch.setattr(task_service, "parse_document_to_chunks", lambda _db, _doc: 2)

    db = Session()
    try:
        doc = Document(id="doc-parse", title="测试文档", filename="测试.txt", storage_path="x", source_type="txt")
        task = BackgroundTask(id="task-parse", task_type="document_parse", document_id=doc.id, status="pending")
        db.add_all([doc, task])
        db.commit()
    finally:
        db.close()

    task_service.process_task_once("task-parse")

    db = Session()
    try:
        original = db.get(BackgroundTask, "task-parse")
        assert original is not None
        assert original.status == "success"
        graph_task = db.execute(select(BackgroundTask).where(BackgroundTask.task_type == "graph_extract")).scalars().first()
        assert graph_task is not None
        assert graph_task.document_id == "doc-parse"
        graph_status = db.get(GraphExtractionStatus, "doc-parse")
        assert graph_status is not None
        assert graph_status.status == "pending"
    finally:
        db.close()
