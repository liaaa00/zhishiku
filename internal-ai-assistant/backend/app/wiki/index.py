from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WikiPage
from .graph import build_wiki_graph
from .health import evaluate_wiki_health

DEFAULT_INDEX_LIMIT = 500
INDEX_RECOMMENDATION_LIMIT = 4


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _source_document_ids(page: WikiPage) -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for source in sorted(page.sources or [], key=lambda item: item.source_order or 0):
        document_id = str(source.document_id or "")
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        ids.append(document_id)
    return ids[:20]


def _recommendations(page: WikiPage, findings: list[dict[str, Any]], node: dict[str, Any]) -> list[str]:
    rules = {str(item.get("rule") or "") for item in findings}
    recommendations: list[str] = []
    if "stale-page" in rules:
        recommendations.append("重新编译页面，确保 Wiki 内容与原始文档一致")
    if "missing-source" in rules:
        recommendations.append("补充来源映射或重新从原始文档编译")
    if "source-marker-out-of-range" in rules or "low-citation-coverage" in rules:
        recommendations.append("补齐或修正 [Sx] 来源标记，提高可核验性")
    if "broken-wikilink" in rules or "broken-page-link" in rules:
        recommendations.append("修复断开的 WikiLink，或补建目标页面")
    if "orphan-page" in rules:
        recommendations.append("为孤页增加出链，并从相关主题页补入链")
    elif "no-backlink" in rules:
        recommendations.append("从相关页面增加反链，让该页进入知识路径")
    if "low-confidence" in rules:
        recommendations.append("人工复核低置信度内容，必要时补充来源")
    if str(page.status or "") == "draft":
        recommendations.append("审核草稿页，决定发布、重编译或归档")
    if not recommendations and int(node.get("link_count") or 0) <= 1 and str(page.status or "") == "published":
        recommendations.append("补充更多上下游 WikiLink，增强页面可发现性")
    return recommendations[:INDEX_RECOMMENDATION_LIMIT]


def _page_index_item(page: WikiPage, findings: list[dict[str, Any]], node: dict[str, Any]) -> dict[str, Any]:
    rule_counts = Counter(str(item.get("rule") or "unknown") for item in findings)
    severity_counts = Counter(str(item.get("severity") or "info") for item in findings)
    return {
        "id": page.id,
        "slug": page.slug,
        "title": page.title,
        "page_type": page.page_type,
        "status": page.status,
        "knowledge_scope": page.knowledge_scope,
        "summary": page.summary,
        "confidence": page.confidence,
        "source_count": len(page.sources or []),
        "source_document_ids": _source_document_ids(page),
        "updated_at": _iso(page.updated_at),
        "created_at": _iso(page.created_at),
        "health": {
            "finding_count": len(findings),
            "rule_counts": dict(sorted(rule_counts.items())),
            "severity_counts": dict(sorted(severity_counts.items())),
            "findings": findings[:10],
        },
        "graph": {
            "link_count": int(node.get("link_count") or 0),
            "incoming_link_count": int(node.get("incoming_link_count") or 0),
            "outgoing_link_count": int(node.get("outgoing_link_count") or 0),
            "broken_link_count": int(node.get("broken_link_count") or 0),
            "community": node.get("community", 0),
            "community_label": node.get("community_label", ""),
        },
        "recommendations": _recommendations(page, findings, node),
    }


def build_wiki_index(
    db: Session,
    *,
    knowledge_scope: str = "production",
    status: str = "published",
    limit: int = DEFAULT_INDEX_LIMIT,
) -> dict[str, Any]:
    """Build a live page-level Wiki index for admin inspection.

    The index is intentionally computed from current Wiki pages, health findings
    and graph signals instead of stored as a separate table. This keeps the first
    LLM-Wiki index iteration migration-free while still exposing the key page
    inventory needed by the next Ingest/Query/Lint loop.
    """

    safe_limit = max(1, min(int(limit or DEFAULT_INDEX_LIMIT), 1000))
    stmt = select(WikiPage).where(WikiPage.knowledge_scope == knowledge_scope).order_by(WikiPage.updated_at.desc()).limit(safe_limit)
    if status != "all":
        stmt = stmt.where(WikiPage.status == status)
    pages = db.execute(stmt).scalars().all()

    health = evaluate_wiki_health(db, knowledge_scope=knowledge_scope, include_findings=True)
    graph = build_wiki_graph(db, knowledge_scope=knowledge_scope, status=status, limit=safe_limit)
    node_by_slug = {str(node.get("slug") or ""): node for node in graph.get("nodes", [])}

    findings_by_page_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    findings_by_slug: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in health.get("findings", []):
        page_id = str(finding.get("page_id") or "")
        slug = str(finding.get("slug") or "")
        if page_id:
            findings_by_page_id[page_id].append(finding)
        if slug:
            findings_by_slug[slug].append(finding)

    items = []
    for page in pages:
        findings = findings_by_page_id.get(str(page.id)) or findings_by_slug.get(str(page.slug), [])
        node = node_by_slug.get(str(page.slug), {})
        items.append(_page_index_item(page, findings, node))

    page_type_counts = Counter(str(item.get("page_type") or "unknown") for item in items)
    status_counts = Counter(str(item.get("status") or "unknown") for item in items)
    return {
        "knowledge_scope": knowledge_scope,
        "status": status,
        "count": len(items),
        "limit": safe_limit,
        "truncated": len(items) >= safe_limit,
        "summary": {
            "page_type_counts": dict(sorted(page_type_counts.items())),
            "status_counts": dict(sorted(status_counts.items())),
            "health_score": health.get("score"),
            "health_finding_count": health.get("finding_count"),
            "orphan_page_count": health.get("orphan_page_count", 0),
            "no_backlink_page_count": health.get("no_backlink_page_count", 0),
            "broken_link_count": health.get("broken_link_count", health.get("broken_wikilink_count", 0)),
            "community_count": graph.get("community_count", 0),
            "edge_count": graph.get("edge_count", 0),
        },
        "items": items,
    }
