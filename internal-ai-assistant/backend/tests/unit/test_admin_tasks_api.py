from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models import BackgroundTask, Document, DocumentProcessingStatus, User
from app.routers.admin_tasks import router as admin_tasks_router
from app.routers.deps import require_admin


def test_admin_tasks_include_document_processing_message(tmp_path: Path) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Session()
    try:
        source = tmp_path / "scan.pdf"
        source.write_bytes(b"%PDF fixture")
        doc = Document(id="doc-task-ocr", title="scan", filename="scan.pdf", storage_path=str(source), source_type="pdf")
        status = DocumentProcessingStatus(
            document_id=doc.id,
            status="ready",
            stage="pdf_vision_ocr",
            message="PDF 文本抽取不足（原因=low_text:2；普通抽取=2 字；阈值=80 字）；OCR 后=36 字。",
            chunks=1,
            searchable=True,
        )
        task = BackgroundTask(id="task-ocr", task_type="document_parse", document_id=doc.id, status="success")
        db.add_all([doc, status, task])
        db.commit()
    finally:
        db.close()

    app = FastAPI()
    app.include_router(admin_tasks_router)

    def override_db():
        session = Session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin] = lambda: User(id="admin", username="admin", password_hash="", is_admin=True)

    client = TestClient(app)
    resp = client.get("/api/admin/tasks")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload[0]["document_stage"] == "pdf_vision_ocr"
    assert "OCR 后=36 字" in payload[0]["document_message"]
