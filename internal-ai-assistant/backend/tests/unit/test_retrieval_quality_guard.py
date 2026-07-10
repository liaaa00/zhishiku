from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import retrieval
from app.database import Base
from app.models import Document, DocumentChunk, DocumentProcessingStatus
from app.retrieval import apply_document_quality_signals, rerank_contexts


def _db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_retrieval_quality_guard_penalizes_low_quality_document(tmp_path: Path) -> None:
    db = _db_session()
    try:
        good_path = tmp_path / "good.txt"
        poor_path = tmp_path / "poor.pdf"
        good_path.write_text("good", encoding="utf-8")
        poor_path.write_bytes(b"%PDF poor")
        good_doc = Document(id="doc-good", title="制度正文", filename="good.txt", storage_path=str(good_path), source_type="txt")
        poor_doc = Document(id="doc-poor", title="制度扫描件", filename="poor.pdf", storage_path=str(poor_path), source_type="pdf")
        good_text = "报销制度要求员工提交发票，并由部门经理审批后付款。" * 4
        poor_text = "报销制度"
        db.add_all([
            good_doc,
            poor_doc,
            DocumentChunk(id="chunk-good", document_id=good_doc.id, page_number=1, chunk_index=0, content=good_text, embedding_json=json.dumps([0.1])),
            DocumentChunk(id="chunk-poor", document_id=poor_doc.id, page_number=1, chunk_index=0, content=poor_text, embedding_json=json.dumps([0.1])),
            DocumentProcessingStatus(document_id=good_doc.id, status="ready", stage="indexed", message="", chunks=1, searchable=True),
            DocumentProcessingStatus(document_id=poor_doc.id, status="failed", stage="parse_error", message="解析失败", chunks=1, searchable=False),
        ])
        db.commit()

        contexts = [
            {"document_id": poor_doc.id, "document_title": poor_doc.title, "filename": poor_doc.filename, "content": poor_text, "score": 0.95, "match_reason": "semantic"},
            {"document_id": good_doc.id, "document_title": good_doc.title, "filename": good_doc.filename, "content": good_text, "score": 0.72, "match_reason": "semantic"},
        ]

        guarded = apply_document_quality_signals(db, contexts)
        ranked, _pageindex_selected = rerank_contexts("报销制度需要什么审批", guarded, limit=2)

        poor = next(item for item in guarded if item["document_id"] == poor_doc.id)
        assert poor["source_quality"]["grade"] == "blocked"
        assert poor["quality_penalty"] >= 0.45
        assert "quality_penalty" in poor["match_reason"]
        assert ranked[0]["document_id"] == good_doc.id
        assert ranked[1]["document_id"] == poor_doc.id
    finally:
        db.close()


def test_pageindex_supplement_stays_off_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(retrieval, "PAGEINDEX_ENABLED", False)

    contexts = retrieval.retrieve_pageindex_contexts(None, "报销流程", None, [])

    assert contexts == []
