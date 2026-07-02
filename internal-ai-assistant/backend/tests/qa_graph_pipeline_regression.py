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


def seed_admin_doc(db, *, doc_id: str, title: str, chunk_text: str):
    admin = User(id=f"admin-{doc_id}", username=f"admin-{doc_id}", password_hash="", is_admin=True, is_active=True)
    doc = Document(id=doc_id, title=title, filename=f"{title}.txt", storage_path="x", source_type="txt")
    chunk = DocumentChunk(
        id=f"chunk-{doc_id}",
        document_id=doc.id,
        chunk_index=0,
        page_number=1,
        content=chunk_text,
        embedding_json="[]",
    )
    db.add_all([admin, doc, chunk])
    db.flush()
    return admin, doc, chunk


def test_graph_context_is_checked_and_merged_for_text_question() -> None:
    Session = make_session()
    db = Session()
    try:
        admin, doc, chunk = seed_admin_doc(
            db,
            doc_id="doc-onboarding",
            title="工单系统入职场景",
            chunk_text="工单系统中，入职联系后需要进行报岗集约录入。",
        )

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
        assert "graph_merged" in note or "graph_direct" in note
        assert candidate_count >= 1
    finally:
        db.close()


def test_plain_user_question_with_team_handler_uses_graph_without_graph_word() -> None:
    Session = make_session()
    db = Session()
    try:
        admin, doc, chunk = seed_admin_doc(
            db,
            doc_id="doc-handler-team",
            title="工单系统处理团队",
            chunk_text="报岗集约录入由后道交付团队处理。",
        )

        source = get_or_create_entity(db, "报岗集约录入", "process", 0.95)
        target = get_or_create_entity(db, "后道交付团队", "team", 0.95)
        assert source is not None and target is not None
        relation = create_relation(
            db,
            source,
            target,
            "handled_by",
            doc.id,
            chunk.id,
            1,
            "报岗集约录入由后道交付团队处理。",
            0.94,
            "auto",
        )
        assert relation is not None
        db.commit()
        db.refresh(admin)

        contexts, backend, note, _candidate_count, meta = retrieve_contexts(
            db,
            "报岗集约录入由哪个团队处理？",
            admin,
            top_k=5,
        )

        joined = "\n".join(item.get("content", "") for item in contexts)
        graph_meta = meta.get("graph_retrieval") or {}
        assert backend == "graph"
        assert "graph_direct" in note
        assert graph_meta.get("checked") is True
        assert graph_meta.get("matched") is True
        assert graph_meta.get("direct_answer") is True
        assert contexts and all(item.get("retrieval_channel") == "graph" for item in contexts)
        assert "后道交付团队" in joined
    finally:
        db.close()


def test_natural_relationship_question_uses_graph_context_as_primary_answer_context() -> None:
    Session = make_session()
    db = Session()
    try:
        admin, doc, chunk = seed_admin_doc(
            db,
            doc_id="doc-qingdao-rules",
            title="202603派单规则图谱",
            chunk_text="202603青岛派单规则需要青岛社保操作规则、青岛医保操作规则和青岛公积金操作规则。",
        )

        source = get_or_create_entity(db, "202603青岛派单规则", "rule", 0.96)
        social_rule = get_or_create_entity(db, "202603青岛社保操作规则", "rule", 0.95)
        medical_rule = get_or_create_entity(db, "202603青岛医保操作规则", "rule", 0.95)
        fund_rule = get_or_create_entity(db, "202603青岛公积金操作规则", "rule", 0.95)
        assert source and social_rule and medical_rule and fund_rule
        for target in (social_rule, medical_rule, fund_rule):
            relation = create_relation(
                db,
                source,
                target,
                "requires",
                doc.id,
                chunk.id,
                1,
                f"202603青岛派单规则需要{target.name}。",
                0.94,
                "auto",
            )
            assert relation is not None
        db.commit()
        db.refresh(admin)

        contexts, backend, note, _candidate_count, meta = retrieve_contexts(
            db,
            "202603青岛派单规则需要哪些操作规则？",
            admin,
            top_k=5,
        )

        joined = "\n".join(item.get("content", "") for item in contexts)
        graph_meta = meta.get("graph_retrieval") or {}
        assert backend == "graph"
        assert "graph_direct" in note
        assert meta["retrieval_route"]["name"] == "text"
        assert meta["retrieval_route"]["reason"].startswith("graph_primary_query_overrode_")
        assert graph_meta.get("checked") is True
        assert graph_meta.get("matched") is True
        assert graph_meta.get("direct_answer") is True
        assert graph_meta.get("merged_into_contexts") is True
        assert contexts and all(item.get("retrieval_channel") == "graph" for item in contexts)
        assert "关系：需要" in joined
        assert "202603青岛社保操作规则" in joined
        assert "202603青岛医保操作规则" in joined
        assert "202603青岛公积金操作规则" in joined
    finally:
        db.close()


def test_graph_entity_without_accessible_relations_does_not_return_unrelated_relations() -> None:
    Session = make_session()
    db = Session()
    try:
        admin, doc, chunk = seed_admin_doc(
            db,
            doc_id="doc-nanjing-empty-graph",
            title="202603派单规则图谱",
            chunk_text="南京派单规则已作为资料事项出现，但当前没有已确认的社保、医保、公积金关系。",
        )

        nanjing = get_or_create_entity(db, "南京派单规则", "city", 0.92)
        shanghai = get_or_create_entity(db, "上海派单规则", "rule", 0.95)
        shanghai_deadline = get_or_create_entity(db, "202603上海社保截止时间", "deadline", 0.95)
        assert nanjing and shanghai and shanghai_deadline
        unrelated = create_relation(
            db,
            shanghai,
            shanghai_deadline,
            "has_deadline",
            doc.id,
            chunk.id,
            1,
            "202603上海派单规则关联上海社保截止时间。",
            0.95,
            "auto",
        )
        assert unrelated is not None
        db.commit()
        db.refresh(admin)

        contexts, backend, note, _candidate_count, meta = retrieve_contexts(
            db,
            "南京派单规则在当前图谱里是否有关联的社保医保公积金关系？",
            admin,
            top_k=5,
        )

        joined = "\n".join(item.get("content", "") for item in contexts)
        graph_meta = meta.get("graph_retrieval") or {}
        assert backend == "graph"
        assert "graph_direct" in note
        assert graph_meta.get("checked") is True
        assert graph_meta.get("matched") is True
        assert graph_meta.get("direct_answer") is True
        assert contexts and all(item.get("retrieval_channel") == "graph" for item in contexts)
        assert "已识别到“南京派单规则”" in joined
        assert "未找到它关联的已确认关系记录" in joined
        assert "图谱实体" not in joined
        assert "自动关系" not in joined
        assert "上海派单规则" not in joined
        assert "202603上海社保截止时间" not in joined
    finally:
        db.close()


if __name__ == "__main__":
    test_graph_context_is_checked_and_merged_for_text_question()
    test_plain_user_question_with_team_handler_uses_graph_without_graph_word()
    test_natural_relationship_question_uses_graph_context_as_primary_answer_context()
    test_graph_entity_without_accessible_relations_does_not_return_unrelated_relations()
    print("Graph pipeline regression passed.")
