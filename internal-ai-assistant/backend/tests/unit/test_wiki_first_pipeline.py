from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Document, DocumentChunk, DocumentProcessingStatus, User, WikiPage, WikiPageSource
from app.rag.pipeline import retrieve_contexts
from app.wiki.compiler import compile_document_to_wiki
from app.wiki.context_budget import apply_context_budget
from app.wiki.graph import build_wiki_graph
from app.wiki.health import evaluate_wiki_health
from app.wiki.search import retrieve_wiki_contexts


def make_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed_esign_document(db):
    admin = User(id="admin", username="admin", password_hash="", is_admin=True, is_active=True)
    doc = Document(
        id="doc-esign",
        title="电子劳动合同操作指南",
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
        content="电子劳动合同流程包括员工实名认证、发起签署、员工确认和合同归档。",
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
    return admin, doc, chunk


def test_compiled_wiki_page_becomes_primary_answer_context() -> None:
    Session = make_session()
    db = Session()
    try:
        admin, doc, _chunk = _seed_esign_document(db)

        result = compile_document_to_wiki(db, doc.id, publish=True)
        db.commit()

        assert result["ok"] is True
        assert result["compiler_version"] == "deterministic-source-v2"
        page = db.query(WikiPage).one()
        assert "[S1]" in page.content_md
        assert "关键事实" in page.content_md
        assert "来源索引" in page.content_md

        contexts, backend, note, candidate_count, meta = retrieve_contexts(
            db,
            "电子劳动合同流程是什么？",
            admin,
            top_k=5,
            knowledge_scope="test",
        )

        assert backend == "wiki"
        assert candidate_count >= 1
        assert "wiki_first=used" in note
        assert meta["retrieval_route"]["name"] == "wiki"
        assert meta["wiki_first"]["used"] is True
        assert meta["wiki_first"]["context_pack"] == "matched_snippets_v3_budgeted"
        assert meta["wiki_first"]["budget"]["requested_tokens"] > 0
        assert contexts[0]["retrieval_channel"] == "wiki"
        assert contexts[0]["document_id"] == doc.id
        assert contexts[0]["wiki_context_pack"] == "matched_snippets_v3_budgeted"
        assert contexts[0]["wiki_context_char_count"] <= 3600
        assert contexts[0]["source_quotes"]
        assert "结构化笔记" in contexts[0]["content"]
    finally:
        db.close()


def test_wiki_search_does_not_expose_sourceless_page_to_non_admin() -> None:
    Session = make_session()
    db = Session()
    try:
        user = User(id="user-1", username="user", password_hash="", is_admin=False, is_active=True)
        page = WikiPage(
            id="wiki-secret",
            slug="secret-policy",
            title="保密制度",
            page_type="source",
            status="published",
            knowledge_scope="test",
            summary="保密制度摘要",
            content_md="# 保密制度\n\n保密制度要求员工不得外传文档。",
            confidence=0.8,
        )
        db.add_all([user, page])
        db.commit()

        contexts, meta = retrieve_wiki_contexts(
            db,
            "保密制度是什么",
            user,
            top_k=5,
            knowledge_scope="test",
        )

        assert contexts == []
        assert meta["used"] is False
        assert meta["skipped_for_access"] == 1
    finally:
        db.close()


def test_wiki_health_reports_stale_and_missing_source_pages() -> None:
    Session = make_session()
    db = Session()
    try:
        _admin, doc, chunk = _seed_esign_document(db)
        compile_document_to_wiki(db, doc.id, publish=True)
        sourceless = WikiPage(
            id="wiki-sourceless",
            slug="sourceless",
            title="无来源页",
            page_type="concept",
            status="published",
            knowledge_scope="test",
            summary="",
            content_md="# 无来源页\n\n这是一个没有来源映射的页面。",
            confidence=0.2,
        )
        db.add(sourceless)
        db.commit()

        chunk.content = chunk.content + "后续补充了新的归档要求。"
        db.commit()

        health = evaluate_wiki_health(db, knowledge_scope="test")
        rules = {finding["rule"] for finding in health["findings"]}

        assert health["score"] < 100
        assert "stale-page" in rules
        assert "missing-source" in rules
        assert "missing-summary" in rules
        assert "low-confidence" in rules
    finally:
        db.close()


def test_wiki_health_reports_invalid_citations_and_broken_wikilinks() -> None:
    Session = make_session()
    db = Session()
    try:
        _admin, doc, chunk = _seed_esign_document(db)
        page = WikiPage(
            id="wiki-citation-risk",
            slug="citation-risk",
            title="引用风险页",
            page_type="source",
            status="published",
            knowledge_scope="test",
            summary="用于验证引用健康检查。",
            content_md=(
                "# 引用风险页\n\n"
                "已标注的事实来自原始资料 [S1]。\n\n"
                "未标注的事实需要被健康检查发现。\n\n"
                "第二条未标注事实也需要被健康检查发现。\n\n"
                "越界引用会导致错误 [S99]。\n\n"
                "链接到 [[不存在页面]] 的说明也应该报告。"
            ),
            confidence=0.8,
        )
        source = WikiPageSource(
            id="wps-citation-risk-1",
            page_id=page.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            page_number=chunk.page_number,
            source_order=0,
            quote=chunk.content,
        )
        db.add_all([page, source])
        db.commit()

        health = evaluate_wiki_health(db, knowledge_scope="test")
        rules = {finding["rule"] for finding in health["findings"]}

        assert "source-marker-out-of-range" in rules
        assert "low-citation-coverage" in rules
        assert "broken-wikilink" in rules
        assert health["broken_wikilink_count"] == 1
        assert health["citation_coverage"] < 1

        out_of_range = next(finding for finding in health["findings"] if finding["rule"] == "source-marker-out-of-range")
        assert out_of_range["invalid_markers"][0]["index"] == 99
        broken_link = next(finding for finding in health["findings"] if finding["rule"] == "broken-wikilink")
        assert broken_link["target"] == "不存在页面"
    finally:
        db.close()


def test_wiki_context_budget_trims_context_pack_without_mutating_input() -> None:
    contexts = [
        {
            "content": "A" * 2600,
            "source_quotes": ["q" * 1600, "r" * 1600],
            "score": 0.9,
        },
        {
            "content": "B" * 2600,
            "source_quotes": ["s" * 1600],
            "score": 0.4,
        },
    ]

    packed, meta = apply_context_budget(contexts, requested_tokens=500, min_content_chars=300)

    assert meta["truncated"] is True
    assert meta["estimated_tokens_after"] <= 500
    assert "source_quotes" in meta["trimmed_sections"]
    assert "content" in meta["trimmed_sections"]
    assert packed[0]["content"].endswith("...")
    assert len(contexts[0]["source_quotes"]) == 2
    assert contexts[0]["content"] == "A" * 2600


def test_wiki_graph_builds_weighted_wikilink_network_with_insights() -> None:
    Session = make_session()
    db = Session()
    try:
        doc = Document(
            id="doc-shared",
            title="Shared Source",
            filename="shared.pdf",
            storage_path="/tmp/shared.pdf",
            source_type="pdf",
            knowledge_scope="test",
        )
        page_a = WikiPage(
            id="wiki-a",
            slug="page-a",
            title="Page A",
            page_type="concept",
            status="published",
            knowledge_scope="test",
            summary="Page A summary",
            content_md="# Page A\n\nLinks to [[Page B]], [[page-b]], [[Page A]], and [[Missing Page]].",
            confidence=0.8,
        )
        page_b = WikiPage(
            id="wiki-b",
            slug="page-b",
            title="Page B",
            page_type="rule",
            status="published",
            knowledge_scope="test",
            summary="Page B summary",
            content_md="# Page B\n\nLinks back to [[Page A]].",
            confidence=0.7,
        )
        page_c = WikiPage(
            id="wiki-c",
            slug="page-c",
            title="Page C",
            page_type="source",
            status="published",
            knowledge_scope="test",
            summary="Orphan page",
            content_md="# Page C\n\nNo links here.",
            confidence=0.6,
        )
        db.add_all([doc, page_a, page_b, page_c])
        db.flush()
        db.add_all(
            [
                WikiPageSource(id="wps-a", page_id=page_a.id, document_id=doc.id, source_order=0, quote="shared quote a"),
                WikiPageSource(id="wps-b", page_id=page_b.id, document_id=doc.id, source_order=0, quote="shared quote b"),
            ]
        )
        db.commit()

        graph = build_wiki_graph(db, knowledge_scope="test")

        assert graph["node_count"] == 3
        assert graph["edge_count"] == 1
        assert graph["community_count"] == 2
        assert graph["broken_link_count"] == 1
        assert graph["orphan_count"] == 1
        assert graph["signal_weights"]["source_overlap"] == 4.0
        edge = graph["edges"][0]
        assert {edge["source"], edge["target"]} == {"page-a", "page-b"}
        assert edge["mentions"] == 3
        assert edge["direction_count"] == 2
        assert edge["shared_source_count"] == 1
        assert edge["signals"]["source_overlap"] == 4.0
        assert edge["weight"] > edge["signals"]["direct_link"]
        assert edge["strength"] == "strong"
        nodes = {node["slug"]: node for node in graph["nodes"]}
        assert nodes["page-a"]["link_count"] == 1
        assert nodes["page-b"]["link_count"] == 1
        assert nodes["page-c"]["link_count"] == 0
        assert nodes["page-a"]["source_count"] == 1
        assert nodes["page-b"]["source_document_ids"] == ["doc-shared"]
        assert nodes["page-a"]["community"] == nodes["page-b"]["community"]
        assert nodes["page-c"]["community"] != nodes["page-a"]["community"]
        assert nodes["page-a"]["broken_link_count"] == 1
        assert graph["broken_links"][0]["target"] == "Missing Page"
        assert graph["communities"][0]["node_count"] == 2
        assert graph["insights"]["surprising_connections"]
        assert graph["insights"]["knowledge_gaps"]
        assert any(gap["type"] == "broken-link" for gap in graph["insights"]["knowledge_gaps"])
    finally:
        db.close()
