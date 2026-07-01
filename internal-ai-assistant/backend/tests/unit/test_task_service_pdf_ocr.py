from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.document_status import status_to_dict
from app.models import Document, DocumentProcessingStatus
from app import task_service


def _db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_pdf_low_text_triggers_ocr_fallback(monkeypatch, tmp_path: Path) -> None:
    db = _db_session()
    try:
        pdf_path = tmp_path / "scan.pdf"
        pdf_path.write_bytes(b"%PDF low text fixture")
        doc = Document(id="doc-low-text-pdf", title="scan", filename="scan.pdf", storage_path=str(pdf_path), source_type="pdf")
        db.add(doc)
        db.commit()

        calls: dict[str, object] = {}

        def fake_extract(path: str):
            calls["extract_path"] = path
            return [(1, "页眉")]

        def fake_ocr(path: Path, cfg: dict):
            calls["ocr_path"] = str(path)
            calls["ocr_cfg"] = cfg
            return [(1, "这是 OCR 后得到的完整正文内容，包含足够用于检索的制度条款和业务字段。")]

        def fake_model_config(_db):
            return {"api_key": "key", "base_url": "url", "model": "vision"}

        def fake_add_chunks(_db, document_id: str, pages):
            calls["indexed_pages"] = pages
            return len(pages)

        monkeypatch.setattr(task_service, "extract_supported_document", fake_extract)
        monkeypatch.setattr(task_service, "_ocr_pdf_pages", fake_ocr)
        monkeypatch.setattr(task_service, "get_model_config", fake_model_config)
        monkeypatch.setattr(task_service, "add_chunks", fake_add_chunks)
        monkeypatch.setattr(task_service, "_maybe_build_pageindex", lambda _db, _doc, _pages: None)

        chunks = task_service.parse_document_to_chunks(db, doc)

        assert chunks == 1
        assert calls["extract_path"] == str(pdf_path)
        assert calls["ocr_path"] == str(pdf_path)
        assert calls["indexed_pages"] == [(1, "这是 OCR 后得到的完整正文内容，包含足够用于检索的制度条款和业务字段。")]
        status = status_to_dict(db.get(DocumentProcessingStatus, doc.id))
        assert status["stage"] == "pdf_vision_ocr"
        assert "原因=low_text" in status["message"]
        assert "普通抽取=2 字" in status["message"]
        assert "OCR 后=37 字" in status["message"]
    finally:
        db.close()


def test_pdf_enough_text_skips_ocr(monkeypatch, tmp_path: Path) -> None:
    db = _db_session()
    try:
        pdf_path = tmp_path / "text.pdf"
        pdf_path.write_bytes(b"%PDF text fixture")
        doc = Document(id="doc-text-pdf", title="text", filename="text.pdf", storage_path=str(pdf_path), source_type="pdf")
        db.add(doc)
        db.commit()

        enough_text = "这是普通 PDF 抽取出的足量正文。" * 10
        calls: dict[str, object] = {"ocr_called": False}

        monkeypatch.setattr(task_service, "extract_supported_document", lambda _path: [(1, enough_text)])
        monkeypatch.setattr(task_service, "_ocr_pdf_pages", lambda _path, _cfg: calls.update({"ocr_called": True}) or [])
        monkeypatch.setattr(task_service, "add_chunks", lambda _db, _document_id, pages: calls.update({"indexed_pages": pages}) or len(pages))
        monkeypatch.setattr(task_service, "_maybe_build_pageindex", lambda _db, _doc, _pages: None)

        chunks = task_service.parse_document_to_chunks(db, doc)

        assert chunks == 1
        assert calls["ocr_called"] is False
        assert calls["indexed_pages"] == [(1, enough_text)]
    finally:
        db.close()
