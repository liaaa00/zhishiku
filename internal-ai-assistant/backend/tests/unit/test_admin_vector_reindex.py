from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Document, DocumentChunk, User
from app.routers import admin_vector


def test_reindex_vectors_regenerates_embeddings_before_qdrant_rebuild(monkeypatch) -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    try:
        doc = Document(id="doc-vector", title="向量测试", filename="vector.txt", storage_path="x", source_type="txt")
        chunks = [
            DocumentChunk(id="chunk-1", document_id=doc.id, chunk_index=0, content="第一段", embedding_json=json.dumps([0.0] * 512)),
            DocumentChunk(id="chunk-2", document_id=doc.id, chunk_index=1, content="第二段", embedding_json=json.dumps([0.0] * 512)),
        ]
        db.add_all([doc, *chunks])
        db.commit()

        rebuilt_dimensions: list[int] = []
        uploaded_vectors: list[list[float]] = []
        strict_modes: list[bool] = []
        monkeypatch.setattr(admin_vector, "qdrant_enabled", lambda: True)
        monkeypatch.setattr(admin_vector, "get_embedding_config", lambda _db: {"provider": "remote", "model": "test-embedding"})
        monkeypatch.setattr(
            admin_vector,
            "embed_texts",
            lambda texts, *, strict: strict_modes.append(strict)
            or [[float(index + 1), 0.5, 0.25] for index, _text in enumerate(texts)],
        )
        monkeypatch.setattr(admin_vector, "recreate_collection", rebuilt_dimensions.append)
        monkeypatch.setattr(
            admin_vector,
            "upsert_document_chunks",
            lambda _doc, rows: uploaded_vectors.extend(json.loads(row.embedding_json) for row in rows),
        )
        monkeypatch.setattr(admin_vector, "audit", lambda *_args, **_kwargs: None)

        result = admin_vector.reindex_vectors(
            db,
            User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True),
        )

        db.expire_all()
        stored = db.query(DocumentChunk).order_by(DocumentChunk.chunk_index).all()
        assert result == {
            "ok": True,
            "chunks": 2,
            "documents": 1,
            "dimension": 3,
            "provider": "remote",
            "model": "test-embedding",
        }
        assert rebuilt_dimensions == [3]
        assert strict_modes == [True]
        assert [json.loads(row.embedding_json) for row in stored] == [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]]
        assert uploaded_vectors == [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]]
    finally:
        db.close()


def _seed_vector_db(embeddings: list[list[float]]):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = Session()
    doc = Document(id="doc-vector-failure", title="回滚测试", filename="rollback.txt", storage_path="x", source_type="txt")
    chunks = [
        DocumentChunk(
            id=f"failure-chunk-{index}",
            document_id=doc.id,
            chunk_index=index,
            content=f"第{index + 1}段",
            embedding_json=json.dumps(vector),
        )
        for index, vector in enumerate(embeddings)
    ]
    db.add_all([doc, *chunks])
    db.commit()
    return db


def test_reindex_vectors_rejects_invalid_embeddings_before_rebuild(monkeypatch) -> None:
    db = _seed_vector_db([[0.1, 0.2]])
    rebuilt_dimensions: list[int] = []
    try:
        monkeypatch.setattr(admin_vector, "qdrant_enabled", lambda: True)
        monkeypatch.setattr(admin_vector, "get_embedding_config", lambda _db: {"provider": "remote", "model": "bad"})
        monkeypatch.setattr(admin_vector, "embed_texts", lambda _texts, *, strict: [[float("nan"), 0.5]])
        monkeypatch.setattr(admin_vector, "recreate_collection", rebuilt_dimensions.append)
        monkeypatch.setattr(
            admin_vector,
            "upsert_document_chunks",
            lambda *_args, **_kwargs: pytest.fail("无效向量不得写入 Qdrant"),
        )

        with pytest.raises(admin_vector.HTTPException) as raised:
            admin_vector.reindex_vectors(
                db,
                User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True),
            )

        db.expire_all()
        stored = db.query(DocumentChunk).one()
        assert raised.value.status_code == 502
        assert "非数字或非有限值" in raised.value.detail
        assert rebuilt_dimensions == []
        assert json.loads(stored.embedding_json) == [0.1, 0.2]
    finally:
        db.close()


@pytest.mark.parametrize("restoration_fails", [False, True])
def test_reindex_vectors_restores_previous_collection_after_qdrant_failure(monkeypatch, restoration_fails: bool) -> None:
    old_vectors = [[0.1, 0.2], [0.3, 0.4]]
    new_vectors = [[1.0, 0.5, 0.25], [2.0, 0.5, 0.25]]
    db = _seed_vector_db(old_vectors)
    rebuilt_dimensions: list[int] = []
    uploaded_vectors: list[list[list[float]]] = []

    def fail_then_restore(_doc, rows) -> None:
        uploaded_vectors.append([json.loads(row.embedding_json) for row in rows])
        if len(uploaded_vectors) == 1 or restoration_fails:
            raise admin_vector.QdrantUnavailable("模拟写入失败")

    try:
        monkeypatch.setattr(admin_vector, "qdrant_enabled", lambda: True)
        monkeypatch.setattr(admin_vector, "get_embedding_config", lambda _db: {"provider": "remote", "model": "test"})
        monkeypatch.setattr(admin_vector, "embed_texts", lambda _texts, *, strict: new_vectors)
        monkeypatch.setattr(admin_vector, "recreate_collection", rebuilt_dimensions.append)
        monkeypatch.setattr(admin_vector, "upsert_document_chunks", fail_then_restore)

        with pytest.raises(admin_vector.HTTPException) as raised:
            admin_vector.reindex_vectors(
                db,
                User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True),
            )

        db.expire_all()
        stored = db.query(DocumentChunk).order_by(DocumentChunk.chunk_index).all()
        assert raised.value.status_code == 503
        assert ("旧集合恢复失败" in raised.value.detail) is restoration_fails
        assert rebuilt_dimensions == [3, 2]
        assert uploaded_vectors == [new_vectors, old_vectors]
        assert [json.loads(row.embedding_json) for row in stored] == old_vectors
    finally:
        db.close()
