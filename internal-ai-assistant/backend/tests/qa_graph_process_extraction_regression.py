"""Regression for deterministic process graph extraction without an LLM key.

Run from internal-ai-assistant/backend:
    python tests/qa_graph_process_extraction_regression.py
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
from app.graph_extraction import extract_graph_from_process_text  # noqa: E402
from app.graph_store import create_relation, get_or_create_entity  # noqa: E402
from app.models import Document, DocumentChunk, User  # noqa: E402
from app.rag.pipeline import retrieve_contexts  # noqa: E402

PROCESS_TEXT = """
浙江企服工单系统开发需求文档。由各业务员作为信息收集和工单发起的起点，将业务办理所需信息及材料附件上传工单系统后，
由工单系统自动完成任务识别和分发派单。后道交付团队可凭权限登录系统查询各类业务的待办工单，并导出办理所需的对应信息表单及材料附件，
推进后续业务办理和交付，并对交付结果回写至系统进行进度反馈。
完成采集后，业务员导入工单系统，由工单系统完成数据集散处理，分别派出劳动合同签订、入职联系、商保投保和报岗集约录入等多个工单，
传导至后道交付团队各职能模块。
待遇申报流程中，后道如审核信息或材料有问题的，可退回业务员重新修改和补充完善；如材料无问题，则确认回业务员，进行材料的用印申请。
"""


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_process_text_extractor_creates_workorder_relations() -> None:
    payload = extract_graph_from_process_text("浙江企服工单系统开发需求文档", PROCESS_TEXT)
    entity_names = {item["name"] for item in payload["entities"]}
    relation_pairs = {(item["source"], item["target"], item["relation_type"]) for item in payload["relations"]}

    assert "后道交付团队" in entity_names
    assert "待办工单" in entity_names
    assert "材料附件" in entity_names
    assert "入职联系" in entity_names
    assert "报岗集约录入" in entity_names
    assert ("后道交付团队", "待办工单", "requires") in relation_pairs
    assert ("工单系统", "报岗集约录入", "triggers") in relation_pairs
    assert ("待遇申报", "材料用印申请", "has_step") in relation_pairs


def test_process_graph_participates_in_pipeline() -> None:
    Session = make_session()
    db = Session()
    try:
        admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True)
        doc = Document(id="doc-workorder", title="浙江企服工单系统开发需求文档", filename="浙江企服工单系统开发需求文档.pdf", storage_path="x", source_type="pdf")
        chunk = DocumentChunk(id="chunk-workorder", document_id=doc.id, chunk_index=0, page_number=1, content=PROCESS_TEXT, embedding_json="[]")
        db.add_all([admin, doc, chunk])
        db.flush()

        payload = extract_graph_from_process_text(doc.title, PROCESS_TEXT)
        entities = {}
        for item in payload["entities"]:
            entity = get_or_create_entity(db, item["name"], item["type"], item.get("confidence", 0.9), item.get("description", ""))
            assert entity is not None
            entities[item["name"]] = entity
        for item in payload["relations"]:
            relation = create_relation(
                db,
                entities[item["source"]],
                entities[item["target"]],
                item["relation_type"],
                doc.id,
                chunk.id,
                1,
                item.get("evidence", ""),
                item.get("confidence", 0.9),
                "auto",
                item.get("description", ""),
            )
            assert relation is not None
        db.commit()
        db.refresh(admin)

        contexts, backend, note, _candidate_count, meta = retrieve_contexts(
            db,
            "后道交付团队登录后可以查询待办工单并导出哪些材料附件？",
            admin,
            top_k=5,
        )
        graph_meta = meta.get("graph_retrieval") or {}
        assert graph_meta.get("checked") is True
        assert graph_meta.get("matched") is True
        assert graph_meta.get("merged_into_contexts") is True
        assert any(item.get("retrieval_channel") == "graph" for item in contexts), contexts
        assert "待办工单" in "\n".join(item.get("content", "") for item in contexts)
        assert backend in {"hybrid+graph", "graph"}
        assert "graph_merged" in note
    finally:
        db.close()


if __name__ == "__main__":
    test_process_text_extractor_creates_workorder_relations()
    test_process_graph_participates_in_pipeline()
    print("Graph process extraction regression passed.")
