from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import WikiPage, WikiPageLink
from .citations import extract_wikilinks
from .compiler import _slugify_title

SIGNAL_WEIGHTS = {
    "direct_link": 3.0,
    "source_overlap": 4.0,
    "common_neighbor": 1.5,
    "type_affinity": 1.0,
}

TYPE_AFFINITY: dict[str, dict[str, float]] = {
    "entity": {"concept": 1.2, "entity": 0.8, "source": 1.0, "rule": 1.0, "overview": 0.8},
    "concept": {"entity": 1.2, "concept": 0.8, "source": 1.0, "rule": 1.2, "overview": 1.0},
    "source": {"entity": 1.0, "concept": 1.0, "source": 0.5, "rule": 1.0, "overview": 0.8},
    "rule": {"concept": 1.2, "entity": 1.0, "source": 1.0, "rule": 0.8, "overview": 1.0},
    "overview": {"concept": 1.0, "entity": 0.8, "source": 0.8, "rule": 1.0, "overview": 0.5},
}

STRUCTURAL_SLUGS = {"index", "overview", "log", "schema", "purpose"}
STRUCTURAL_PAGE_TYPES = {"overview"}


def _compact_title(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def _strip_anchor(value: str) -> str:
    return (value or "").split("#", 1)[0].strip()


def _page_keys(page: WikiPage) -> set[str]:
    keys = {
        str(page.slug or "").lower(),
        _slugify_title(str(page.title or ""), str(page.slug or page.id or "page")).lower(),
        _compact_title(str(page.title or "")),
    }
    return {key for key in keys if key}


def _link_keys(link: str) -> set[str]:
    target = _strip_anchor(link)
    if not target:
        return set()
    keys = {
        target.lower(),
        _slugify_title(target, target).lower(),
        _compact_title(target),
    }
    return {key for key in keys if key}


def _page_source_ids(page: WikiPage) -> set[str]:
    return {str(source.document_id) for source in (page.sources or []) if source.document_id}


def _page_node(page: WikiPage) -> dict[str, Any]:
    source_document_ids = sorted(_page_source_ids(page))
    return {
        "id": page.slug,
        "page_id": page.id,
        "slug": page.slug,
        "title": page.title,
        "page_type": page.page_type,
        "status": page.status,
        "summary": page.summary,
        "confidence": page.confidence,
        "source_count": len(page.sources or []),
        "source_document_ids": source_document_ids[:20],
        "link_count": 0,
        "outgoing_link_count": 0,
        "incoming_link_count": 0,
        "broken_link_count": 0,
        "community": 0,
        "community_label": "社区 1",
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


def _type_affinity(source_type: str | None, target_type: str | None) -> float:
    left = str(source_type or "source").lower()
    right = str(target_type or "source").lower()
    return TYPE_AFFINITY.get(left, {}).get(right, 0.5)


def _edge_strength(weight: float) -> str:
    if weight >= 8:
        return "strong"
    if weight >= 5:
        return "medium"
    return "weak"


def _adamic_adar(edge_key: tuple[str, str], adjacency: dict[str, set[str]]) -> tuple[int, float]:
    left, right = edge_key
    common = adjacency.get(left, set()) & adjacency.get(right, set())
    score = 0.0
    for slug in common:
        degree = len(adjacency.get(slug, set()))
        score += 1 / math.log(max(degree, 2))
    return len(common), score


def _edge_payload(
    left: WikiPage,
    right: WikiPage,
    *,
    mentions: int,
    raw_targets: list[str],
    directions: set[tuple[str, str]],
    adjacency: dict[str, set[str]],
    source_ids_by_slug: dict[str, set[str]],
) -> dict[str, Any]:
    edge_key = (left.slug, right.slug)
    direction_count = len(directions)
    shared_source_count = len(source_ids_by_slug.get(left.slug, set()) & source_ids_by_slug.get(right.slug, set()))
    common_neighbor_count, common_neighbor_score = _adamic_adar(edge_key, adjacency)
    signals = {
        "direct_link": round(direction_count * SIGNAL_WEIGHTS["direct_link"] + max(0, mentions - direction_count) * 0.25, 4),
        "source_overlap": round(shared_source_count * SIGNAL_WEIGHTS["source_overlap"], 4),
        "common_neighbor": round(common_neighbor_score * SIGNAL_WEIGHTS["common_neighbor"], 4),
        "type_affinity": round(_type_affinity(left.page_type, right.page_type) * SIGNAL_WEIGHTS["type_affinity"], 4),
    }
    weight = round(sum(signals.values()), 4)
    return {
        "id": f"{left.slug}--{right.slug}",
        "source": left.slug,
        "target": right.slug,
        "source_page_id": left.id,
        "target_page_id": right.id,
        "source_title": left.title,
        "target_title": right.title,
        "relation_type": "wikilink",
        "mentions": mentions,
        "raw_targets": sorted(set(raw_targets))[:12],
        "directed": False,
        "direction_count": direction_count,
        "shared_source_count": shared_source_count,
        "common_neighbor_count": common_neighbor_count,
        "weight": weight,
        "strength": _edge_strength(weight),
        "signals": signals,
    }


def _weighted_median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _detect_communities(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parent = {str(node["slug"]): str(node["slug"]) for node in nodes}

    def find(slug: str) -> str:
        root = parent[slug]
        if root != slug:
            parent[slug] = find(root)
        return parent[slug]

    def union(left: str, right: str) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if left_root > right_root:
            left_root, right_root = right_root, left_root
        parent[right_root] = left_root

    if edges:
        threshold = max(3.5, _weighted_median([float(edge.get("weight") or 0) for edge in edges]))
        for edge in edges:
            if float(edge.get("weight") or 0) >= threshold:
                union(str(edge["source"]), str(edge["target"]))

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        groups[find(str(node["slug"]))].append(node)

    edge_pairs = {(str(edge["source"]), str(edge["target"])) for edge in edges}
    edge_pairs |= {(right, left) for left, right in list(edge_pairs)}

    grouped = sorted(groups.values(), key=lambda items: (-len(items), -sum(int(item.get("link_count") or 0) for item in items), str(items[0].get("title") or "")))
    communities: list[dict[str, Any]] = []
    for idx, members in enumerate(grouped):
        slugs = {str(item["slug"]) for item in members}
        for item in members:
            item["community"] = idx
            item["community_label"] = f"社区 {idx + 1}"
        intra_edges = 0
        for left in slugs:
            for right in slugs:
                if left < right and (left, right) in edge_pairs:
                    intra_edges += 1
        possible_edges = len(slugs) * (len(slugs) - 1) / 2 if len(slugs) > 1 else 1
        top_nodes = sorted(members, key=lambda item: (-int(item.get("link_count") or 0), str(item.get("title") or item.get("slug") or "")))[:5]
        page_type_counts = Counter(str(item.get("page_type") or "unknown") for item in members)
        communities.append(
            {
                "id": idx,
                "label": f"社区 {idx + 1}",
                "node_count": len(members),
                "edge_count": intra_edges,
                "cohesion": round(intra_edges / possible_edges, 4),
                "top_nodes": [str(item.get("title") or item.get("slug")) for item in top_nodes],
                "page_type_counts": dict(sorted(page_type_counts.items())),
            }
        )
    return communities


def _is_structural_node(node: dict[str, Any]) -> bool:
    slug = str(node.get("slug") or "").lower()
    page_type = str(node.get("page_type") or "").lower()
    return slug in STRUCTURAL_SLUGS or page_type in STRUCTURAL_PAGE_TYPES


def _build_graph_insights(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    communities: list[dict[str, Any]],
    broken_links: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    node_by_slug = {str(node["slug"]): node for node in nodes}
    max_degree = max([int(node.get("link_count") or 0) for node in nodes] or [1])
    surprising: list[dict[str, Any]] = []

    for edge in edges:
        source = node_by_slug.get(str(edge.get("source")))
        target = node_by_slug.get(str(edge.get("target")))
        if not source or not target or _is_structural_node(source) or _is_structural_node(target):
            continue
        score = 0
        reasons: list[str] = []
        if source.get("community") != target.get("community"):
            score += 3
            reasons.append("跨社区连接")
        if source.get("page_type") != target.get("page_type"):
            score += 2
            reasons.append(f"跨类型：{source.get('page_type') or 'unknown'} ↔ {target.get('page_type') or 'unknown'}")
        min_degree = min(int(source.get("link_count") or 0), int(target.get("link_count") or 0))
        pair_max_degree = max(int(source.get("link_count") or 0), int(target.get("link_count") or 0))
        if min_degree <= 1 and pair_max_degree >= max(2, max_degree * 0.5):
            score += 2
            reasons.append("边缘页面连接到高连接页面")
        if str(edge.get("strength")) == "weak":
            score += 1
            reasons.append("弱连接但已被显式引用")
        if int(edge.get("shared_source_count") or 0) > 0 and source.get("page_type") != target.get("page_type"):
            score += 1
            reasons.append("共享来源支撑跨类型关系")
        if score >= 2 and reasons:
            surprising.append(
                {
                    "key": ":::".join(sorted([str(edge["source"]), str(edge["target"])])),
                    "source": edge["source"],
                    "target": edge["target"],
                    "source_title": source.get("title") or edge["source"],
                    "target_title": target.get("title") or edge["target"],
                    "score": score,
                    "weight": edge.get("weight"),
                    "reasons": reasons,
                }
            )

    surprising.sort(key=lambda item: (-int(item["score"]), -float(item.get("weight") or 0), str(item["source_title"])))

    gaps: list[dict[str, Any]] = []
    low_link_nodes = [node for node in nodes if int(node.get("link_count") or 0) <= 1 and not _is_structural_node(node)]
    if low_link_nodes:
        sample = low_link_nodes[:5]
        gaps.append(
            {
                "type": "isolated-node",
                "title": f"{len(low_link_nodes)} 个低连接 Wiki 页面",
                "description": "、".join(str(node.get("title") or node.get("slug")) for node in sample),
                "node_ids": [str(node["slug"]) for node in low_link_nodes],
                "suggestion": "这些页面缺少 WikiLink 连接。建议补充 [[相关页面]]，或将同主题页面合并为更强的知识簇。",
            }
        )
    if broken_links:
        sample_targets = "、".join(str(item.get("target")) for item in broken_links[:5])
        gaps.append(
            {
                "type": "broken-link",
                "title": f"{len(broken_links)} 个 WikiLink 断链",
                "description": sample_targets,
                "node_ids": sorted({str(item.get("source")) for item in broken_links if item.get("source")}),
                "suggestion": "请修正目标标题/slug，或补建对应 Wiki 页面，避免问答引用不可达节点。",
            }
        )
    for community in communities:
        if int(community.get("node_count") or 0) >= 3 and float(community.get("cohesion") or 0) < 0.15:
            gaps.append(
                {
                    "type": "sparse-community",
                    "title": f"稀疏社区：{(community.get('top_nodes') or [community.get('label')])[0]}",
                    "description": f"{community.get('node_count')} 个页面，内部连接密度 {community.get('cohesion')}。",
                    "node_ids": [str(node["slug"]) for node in nodes if node.get("community") == community.get("id")],
                    "suggestion": "这个主题簇内部交叉引用偏弱，建议增加页面之间的上下游、规则、概念和来源链接。",
                }
            )

    community_neighbors: dict[str, set[int]] = {str(node["slug"]): set() for node in nodes}
    for edge in edges:
        source = node_by_slug.get(str(edge.get("source")))
        target = node_by_slug.get(str(edge.get("target")))
        if not source or not target:
            continue
        community_neighbors[str(source["slug"])].add(int(target.get("community") or 0))
        community_neighbors[str(target["slug"])].add(int(source.get("community") or 0))
    bridge_nodes = sorted(
        [node for node in nodes if len(community_neighbors.get(str(node["slug"]), set()) - {int(node.get("community") or 0)}) >= 2 and not _is_structural_node(node)],
        key=lambda node: (-len(community_neighbors.get(str(node["slug"]), set())), -int(node.get("link_count") or 0), str(node.get("title") or "")),
    )[:3]
    for node in bridge_nodes:
        external_count = len(community_neighbors.get(str(node["slug"]), set()) - {int(node.get("community") or 0)})
        gaps.append(
            {
                "type": "bridge-node",
                "title": f"关键桥接页：{node.get('title') or node.get('slug')}",
                "description": f"连接 {external_count} 个其他知识社区，是 Wiki 结构中的关键跳转点。",
                "node_ids": [str(node["slug"])],
                "suggestion": "请重点维护该页摘要、来源和出入链，避免关键主题路径断裂。",
            }
        )

    return {"surprising_connections": surprising[:8], "knowledge_gaps": gaps[:8]}


def build_wiki_graph(
    db: Session,
    *,
    knowledge_scope: str = "production",
    status: str = "published",
    limit: int = 500,
) -> dict[str, Any]:
    """Build the live Wiki page relationship graph from current Wiki pages.

    The graph follows the LLM Wiki design at an architecture level: Wiki pages
    are nodes, `[[wikilink]]` references are graph edges, and each edge receives
    a multi-signal relevance weight from direct links, shared source documents,
    common neighbors and page-type affinity. It is computed from database state
    so the admin UI always reflects the latest compiled Wiki rather than the old
    entity-extraction graph.
    """

    stmt = select(WikiPage).where(WikiPage.knowledge_scope == knowledge_scope).order_by(WikiPage.updated_at.desc()).limit(limit)
    if status != "all":
        stmt = stmt.where(WikiPage.status == status)
    pages = db.execute(stmt).scalars().all()

    page_by_key: dict[str, WikiPage] = {}
    page_by_slug: dict[str, WikiPage] = {}
    page_by_id: dict[str, WikiPage] = {}
    for page in pages:
        page_by_slug[str(page.slug)] = page
        page_by_id[str(page.id)] = page
        for key in _page_keys(page):
            page_by_key.setdefault(key, page)

    node_by_slug: dict[str, dict[str, Any]] = {str(page.slug): _page_node(page) for page in pages}
    source_ids_by_slug: dict[str, set[str]] = {str(page.slug): _page_source_ids(page) for page in pages}
    edge_mentions: Counter[tuple[str, str]] = Counter()
    edge_raw_targets: dict[tuple[str, str], list[str]] = defaultdict(list)
    edge_directions: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    broken_links: list[dict[str, Any]] = []
    outgoing_targets: dict[str, set[str]] = defaultdict(set)
    incoming_sources: dict[str, set[str]] = defaultdict(set)

    def record_edge(source: WikiPage, target: WikiPage, raw_target: str) -> None:
        if not source.slug or not target.slug or target.id == source.id:
            return
        left_slug, right_slug = sorted([str(source.slug), str(target.slug)])
        edge_key = (left_slug, right_slug)
        edge_mentions[edge_key] += 1
        if raw_target:
            edge_raw_targets[edge_key].append(raw_target)
        edge_directions[edge_key].add((str(source.slug), str(target.slug)))
        outgoing_targets[str(source.slug)].add(str(target.slug))
        incoming_sources[str(target.slug)].add(str(source.slug))

    for page in pages:
        for raw_link in extract_wikilinks(page.content_md or ""):
            keys = _link_keys(raw_link)
            target = next((page_by_key[key] for key in keys if key in page_by_key), None)
            if not target:
                node_by_slug[str(page.slug)]["broken_link_count"] += 1
                broken_links.append(
                    {
                        "source": page.slug,
                        "source_page_id": page.id,
                        "source_title": page.title,
                        "target": raw_link,
                    }
                )
                continue
            record_edge(page, target, raw_link)

    page_ids = [str(page.id) for page in pages]
    if page_ids:
        persisted_links = db.execute(
            select(WikiPageLink)
            .where(WikiPageLink.source_page_id.in_(page_ids))
            .where(WikiPageLink.target_page_id.in_(page_ids))
        ).scalars().all()
        for link in persisted_links:
            source = page_by_id.get(str(link.source_page_id))
            target = page_by_id.get(str(link.target_page_id))
            if source and target:
                record_edge(source, target, link.anchor_text or link.link_type or "wikilink")

    adjacency: dict[str, set[str]] = {str(page.slug): set() for page in pages}
    for left_slug, right_slug in edge_mentions:
        adjacency[left_slug].add(right_slug)
        adjacency[right_slug].add(left_slug)

    edges: list[dict[str, Any]] = []
    degree: Counter[str] = Counter()
    for edge_key, mentions in edge_mentions.items():
        left_slug, right_slug = edge_key
        left_page = page_by_slug[left_slug]
        right_page = page_by_slug[right_slug]
        degree[left_slug] += 1
        degree[right_slug] += 1
        edges.append(
            _edge_payload(
                left_page,
                right_page,
                mentions=mentions,
                raw_targets=edge_raw_targets[edge_key],
                directions=edge_directions[edge_key],
                adjacency=adjacency,
                source_ids_by_slug=source_ids_by_slug,
            )
        )

    for slug, node in node_by_slug.items():
        node["link_count"] = int(degree[slug])
        node["outgoing_link_count"] = len(outgoing_targets.get(slug, set()))
        node["incoming_link_count"] = len(incoming_sources.get(slug, set()))

    edges.sort(key=lambda item: (-float(item["weight"]), -int(item["mentions"]), item["source_title"] or "", item["target_title"] or ""))
    nodes = list(node_by_slug.values())
    communities = _detect_communities(nodes, edges)
    nodes.sort(key=lambda item: (-int(item["link_count"]), int(item.get("community") or 0), item["title"] or item["slug"]))
    page_type_counts = Counter(str(node["page_type"] or "unknown") for node in nodes)

    return {
        "knowledge_scope": knowledge_scope,
        "status": status,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "community_count": len(communities),
        "orphan_count": sum(1 for node in nodes if int(node["link_count"]) == 0),
        "broken_link_count": len(broken_links),
        "page_type_counts": dict(sorted(page_type_counts.items())),
        "signal_weights": SIGNAL_WEIGHTS,
        "nodes": nodes,
        "edges": edges,
        "communities": communities,
        "insights": _build_graph_insights(nodes, edges, communities, broken_links),
        "broken_links": broken_links[:200],
        "truncated": len(pages) >= limit,
    }
