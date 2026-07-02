"""Regression coverage for graph retrieval participation in the main RAG pipeline.

Run from internal-ai-assistant/backend:
    python tests/qa_graph_pipeline_regression.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import Base  # noqa: E402
from app.graph_store import create_relation, get_or_create_entity  # noqa: E402
from app.models import Document, DocumentChunk, User  # noqa: E402
from app.rag.pipeline import retrieve_contexts  # noqa: E402


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_graph_context_is_checked_and_merged_for_text_question() -> None:
    Session = make_session()
    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True)
        doc = Document(id="doc-onboarding", title="工单系统入职场景", filename="工单系统入职场景.txt", storage_path="x", source_type="txt")
        chunk = DocumentChunk(
            id="chunk-onboarding",
            document_id=doc.id,
            chunk_index=0,
            page_number=1,
            content="工单系统中，入职联系后需要进行报岗集约录入。",
            embedding_json="[]",
        )
        db.add_all([admin, doc, chunk])
        db.flush()

        source = get_or_create_entity(db, "入职联系", "process", 0.95)
        target = get_or_create_entity(db, "报岗集约录入", "process", 0.95)
        assert source is not None and target is not None
        relation = create_relation(
            db,
            source,
            target,
            "requires_step",
            doc.id,
            chunk.id,
            1,
            "入职联系后需要进行报岗集约录入。",
            0.93,
            "auto",
        )
        assert relation is not None
        db.commit()
        db.refresh(admin)

        contexts, backend, note, candidate_count, meta = retrieve_contexts(
            db,
            "入职联系和报岗集约录入有什么关系？",
            admin,
            top_k=5,
        )

        graph_meta = meta.get("graph_retrieval") or {}
        assert meta["retrieval_route"]["name"] == "text"
        assert graph_meta.get("checked") is True
        assert graph_meta.get("matched") is True
        assert graph_meta.get("context_count", 0) >= 1
        assert graph_meta.get("merged_into_contexts") is True
        assert any(item.get("retrieval_channel") == "graph" for item in contexts), contexts
        assert "报岗集约录入" in "\n".join(item.get("content", "") for item in contexts)
        assert backend in {"hybrid+graph", "graph"}
        assert "graph_merged" in note
        assert candidate_count >= 1
    finally:
        db.close()


if __name__ == "__main__":
    test_graph_context_is_checked_and_merged_for_text_question()
    print("Graph pipeline regression passed.")
