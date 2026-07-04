from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.graph_store import create_relation, get_or_create_entity
from app.models import Document, DocumentChunk, User
from app.rag.pipeline import retrieve_contexts


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_explicit_document_title_prevents_graph_primary_override() -> None:
    Session = make_session()
    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True)
        guide_doc = Document(
            id="doc-guide",
            title="电子劳动合同操作指南",
            filename="电子劳动合同操作指南.pdf",
            storage_path="x",
            source_type="pdf",
            knowledge_scope="test",
            document_kind="general",
        )
        workorder_doc = Document(
            id="doc-workorder",
            title="浙江企服工单系统开发需求文档",
            filename="浙江企服工单系统开发需求文档.pdf",
            storage_path="x",
            source_type="pdf",
            knowledge_scope="test",
            document_kind="workorder",
        )
        guide_chunk = DocumentChunk(
            id="chunk-guide",
            document_id=guide_doc.id,
            chunk_index=0,
            page_number=1,
            content="电子劳动合同操作指南：平台注册、实名认证、电子劳动合同签署流程。",
            embedding_json="[]",
        )
        workorder_chunk = DocumentChunk(
            id="chunk-workorder",
            document_id=workorder_doc.id,
            chunk_index=0,
            page_number=1,
            content="劳动合同续签由业务员采集信息后传导至合同组处理。",
            embedding_json="[]",
        )
        db.add_all([admin, guide_doc, workorder_doc, guide_chunk, workorder_chunk])
        db.flush()

        source = get_or_create_entity(db, "劳动合同续签", "process", 0.9)
        target = get_or_create_entity(db, "合同组", "team", 0.9)
        assert source and target
        create_relation(
            db,
            source,
            target,
            "handled_by",
            workorder_doc.id,
            workorder_chunk.id,
            1,
            "劳动合同续签由合同组处理。",
            0.9,
            "auto",
        )
        db.commit()

        contexts, backend, _note, _count, meta = retrieve_contexts(
            db,
            "电子劳动合同操作指南里，合同操作大致流程是什么？",
            admin,
            top_k=6,
            knowledge_scope="test",
        )

        assert backend != "graph"
        assert meta["graph_retrieval"]["title_match_protected_primary"] is True
        assert meta["graph_retrieval"]["direct_answer"] is False
        assert contexts[0]["document_id"] == guide_doc.id
        assert contexts[0].get("retrieval_channel") != "graph"
    finally:
        db.close()
