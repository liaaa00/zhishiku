from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.document_quality import build_document_quality_report, list_document_quality_reports
from app.models import BackgroundTask, Document, DocumentChunk, DocumentProcessingStatus, DocumentTableRow, User
from app.routers.admin_quality import router as admin_quality_router
from app.routers.deps import require_admin


def _db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    return Session()


def test_document_quality_report_detects_missing_text_chunks_for_pdf(tmp_path: Path) -> None:
    db = _db_session()
    try:
        source = tmp_path / "policy.pdf"
        source.write_bytes(b"%PDF fixture")
        doc = Document(
            id="doc-pdf-empty",
            title="policy",
            filename="policy.pdf",
            storage_path=str(source),
            source_type="pdf",
        )
        status = DocumentProcessingStatus(
            document_id=doc.id,
            status="ready",
            stage="indexed",
            message="",
            chunks=0,
            searchable=False,
        )
        db.add_all([doc, status])
        db.commit()

        report = build_document_quality_report(db, doc.id)

        assert report["document"]["storage_exists"] is True
        assert report["chunks"]["count"] == 0
        assert report["quality"]["grade"] == "blocked"
        assert any(issue["code"] == "no_chunks" and issue["severity"] == "critical" for issue in report["issues"])
        assert any(issue["code"] == "page_index_missing" for issue in report["issues"])
    finally:
        db.close()


def test_document_quality_report_summarizes_table_rows_and_semantics(tmp_path: Path) -> None:
    db = _db_session()
    try:
        source = tmp_path / "branches.xlsx"
        source.write_bytes(b"xlsx fixture")
        doc = Document(
            id="doc-table-good",
            title="branches",
            filename="branches.xlsx",
            storage_path=str(source),
            source_type="xlsx",
        )
        status = DocumentProcessingStatus(
            document_id=doc.id,
            status="ready",
            stage="indexed",
            message="",
            chunks=1,
            searchable=True,
        )
        chunk = DocumentChunk(
            id="chunk-1",
            document_id=doc.id,
            page_number=1,
            chunk_index=0,
            content="表格行：工作表=Sheet1 | Excel行=2 | 所在城市=上海 | 当前进度=已开通 | 机构主体=上海示例有限公司",
            embedding_json="[]",
        )
        row_payload = {"所在城市": "上海", "当前进度": "已开通", "机构主体": "上海示例有限公司"}
        row = DocumentTableRow(
            id="row-1",
            document_id=doc.id,
            sheet_name="Sheet1",
            row_number=2,
            row_key="Sheet1:2",
            row_json=json.dumps(row_payload, ensure_ascii=False),
            row_text=" | ".join(f"{key}={value}" for key, value in row_payload.items()),
            is_header=False,
        )
        db.add_all([doc, status, chunk, row])
        db.commit()

        report = build_document_quality_report(db, doc.id)

        assert report["quality"]["critical_count"] == 0
        assert report["table"]["data_rows"] == 1
        assert report["table"]["sheet_count"] == 1
        assert "city" in report["table"]["semantic_fields"]
        assert "status" in report["table"]["semantic_fields"]
        assert any(sheet["sheet_name"] == "Sheet1" and sheet["data_rows"] == 1 for sheet in report["table"]["sheets"])
    finally:
        db.close()


def test_document_quality_report_exposes_pdf_ocr_diagnostics(tmp_path: Path) -> None:
    db = _db_session()
    try:
        source = tmp_path / "scan.pdf"
        source.write_bytes(b"%PDF fixture")
        doc = Document(id="doc-pdf-ocr", title="scan", filename="scan.pdf", storage_path=str(source), source_type="pdf")
        status = DocumentProcessingStatus(
            document_id=doc.id,
            status="ready",
            stage="pdf_vision_ocr",
            message="PDF 文本抽取不足（原因=low_text:2；普通抽取=2 字；阈值=80 字）；OCR 后=36 字。",
            chunks=1,
            searchable=True,
        )
        chunk = DocumentChunk(id="chunk-ocr", document_id=doc.id, page_number=1, chunk_index=0, content="OCR 后正文", embedding_json="[]")
        db.add_all([doc, status, chunk])
        db.commit()

        report = build_document_quality_report(db, doc.id)

        assert report["processing"]["ocr_triggered"] is True
        assert report["processing"]["ocr_reason"] == "low_text:2"
        assert report["processing"]["extracted_chars"] == 2
        assert report["processing"]["ocr_threshold_chars"] == 80
        assert report["processing"]["ocr_chars"] == 36
    finally:
        db.close()


def test_document_quality_list_skips_chat_sources_by_default(tmp_path: Path) -> None:
    db = _db_session()
    try:
        normal_path = tmp_path / "normal.txt"
        chat_path = tmp_path / "chat.txt"
        normal_path.write_text("normal", encoding="utf-8")
        chat_path.write_text("chat", encoding="utf-8")
        normal_doc = Document(id="doc-normal", title="normal", filename="normal.txt", storage_path=str(normal_path), source_type="txt")
        chat_doc = Document(id="doc-chat", title="chat", filename="chat.txt", storage_path=str(chat_path), source_type="chat_upload")
        db.add_all([normal_doc, chat_doc])
        db.commit()

        default_reports = list_document_quality_reports(db)
        all_reports = list_document_quality_reports(db, include_chat=True)

        assert default_reports["total"] == 1
        assert default_reports["reports"][0]["document"]["id"] == "doc-normal"
        assert all_reports["total"] == 2
    finally:
        db.close()


def test_document_quality_admin_api_returns_report(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        source = tmp_path / "api.txt"
        source.write_text("hello quality", encoding="utf-8")
        doc = Document(id="doc-api", title="api", filename="api.txt", storage_path=str(source), source_type="txt")
        chunk = DocumentChunk(id="chunk-api", document_id=doc.id, page_number=1, chunk_index=0, content="hello quality content", embedding_json="[]")
        db.add_all([doc, chunk])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_quality_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True)

    client = TestClient(app)
    one = client.get("/api/admin/documents/doc-api/quality")
    listing = client.get("/api/admin/document-quality")

    assert one.status_code == 200
    assert one.json()["document"]["id"] == "doc-api"
    assert one.json()["chunks"]["count"] == 1
    assert listing.status_code == 200
    assert listing.json()["total"] == 1


def test_document_quality_report_recommends_reparse_for_missing_chunks(tmp_path: Path) -> None:
    db = _db_session()
    try:
        source = tmp_path / "broken.docx"
        source.write_bytes(b"docx fixture")
        doc = Document(id="doc-reparse-suggestion", title="broken", filename="broken.docx", storage_path=str(source), source_type="docx")
        status = DocumentProcessingStatus(document_id=doc.id, status="ready", stage="indexed", message="", chunks=0, searchable=False)
        db.add_all([doc, status])
        db.commit()

        report = build_document_quality_report(db, doc.id)

        assert any(action["code"] == "reparse" and action["available"] for action in report["recommended_actions"])
        assert any(issue["code"] == "no_chunks" for issue in report["issues"])
    finally:
        db.close()


def test_document_quality_bulk_reparse_enqueues_reparse_task(tmp_path: Path) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        source = tmp_path / "broken.pdf"
        source.write_bytes(b"%PDF fixture")
        doc = Document(id="doc-bulk-reparse", title="broken", filename="broken.pdf", storage_path=str(source), source_type="pdf")
        status = DocumentProcessingStatus(document_id=doc.id, status="failed", stage="parse_error", message="解析失败", chunks=0, searchable=False)
        db.add_all([doc, status])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_quality_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True)

    client = TestClient(app)
    resp = client.post("/api/admin/document-quality/reparse", json={"document_ids": ["doc-bulk-reparse"]})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["queued_count"] == 1
    assert payload["queued"][0]["document_id"] == "doc-bulk-reparse"

    verify_db = Session()
    try:
        task = verify_db.query(BackgroundTask).filter(BackgroundTask.document_id == "doc-bulk-reparse").one()
        assert task.task_type == "document_reparse"
        assert task.status == "pending"
    finally:
        verify_db.close()
