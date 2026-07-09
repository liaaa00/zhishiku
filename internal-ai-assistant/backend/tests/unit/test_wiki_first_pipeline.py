from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Document, DocumentChunk, DocumentProcessingStatus, User, WikiPage
from app.rag.pipeline import retrieve_contexts
from app.wiki.compiler import compile_document_to_wiki


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _u(value: str) -> str:
    return value.encode("utf-8").decode("unicode_escape")


def test_compiled_wiki_page_becomes_primary_answer_context() -> None:
    Session = make_session()
    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True)
        doc = Document(
            id="doc-esign",
            title=_u("\\u7535\\u5b50\\u52b3\\u52a8\\u5408\\u540c\\u64cd\\u4f5c\\u6307\\u5357"),
            filename="esign.pdf",
            storage_path="x",
            source_type="pdf",
            knowledge_scope="test",
            document_kind="employee_guide",
        )
        chunk = DocumentChunk(
            id="chunk-esign-1",
            document_id=doc.id,
            chunk_index=0,
            page_number=1,
            content=_u(
                "\\u7535\\u5b50\\u52b3\\u52a8\\u5408\\u540c\\u6d41\\u7a0b\\u5305\\u62ec"
                "\\u5458\\u5de5\\u5b9e\\u540d\\u8ba4\\u8bc1\\u3001\\u53d1\\u8d77\\u7b7e\\u7f72\\u3001"
                "\\u5458\\u5de5\\u786e\\u8ba4\\u548c\\u5408\\u540c\\u5f52\\u6863\\u3002"
            ),
            embedding_json="[]",
        )
        status = DocumentProcessingStatus(
            document_id=doc.id,
            user_id=admin.id,
            status="ready",
            stage="indexed",
            message="ready",
            chunks=1,
            searchable=True,
        )
        db.add_all([admin, doc, chunk, status])
        db.commit()

        result = compile_document_to_wiki(db, doc.id, publish=True)
        db.commit()

        assert result["ok"] is True
        assert db.query(WikiPage).count() == 1

        contexts, backend, note, candidate_count, meta = retrieve_contexts(
            db,
            _u("\\u7535\\u5b50\\u52b3\\u52a8\\u5408\\u540c\\u6d41\\u7a0b\\u662f\\u4ec0\\u4e48\\uff1f"),
            admin,
            top_k=5,
            knowledge_scope="test",
        )

        assert backend == "wiki"
        assert candidate_count >= 1
        assert "wiki_first=used" in note
        assert meta["retrieval_route"]["name"] == "wiki"
        assert meta["wiki_first"]["used"] is True
        assert contexts[0]["retrieval_channel"] == "wiki"
        assert contexts[0]["document_id"] == doc.id
        assert _u("\\u7ed3\\u6784\\u5316\\u7b14\\u8bb0") in contexts[0]["content"]
    finally:
        db.close()
