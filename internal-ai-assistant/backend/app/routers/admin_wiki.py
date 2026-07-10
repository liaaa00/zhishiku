from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditLog, Document, User, WikiCompileStatus, WikiPage
from ..wiki.compiler import compile_document_to_wiki, compile_ready_documents
from ..wiki.graph import build_wiki_graph
from ..wiki.health import evaluate_wiki_health
from ..wiki.search import retrieve_wiki_contexts
from .deps import audit, require_admin

router = APIRouter()

WIKI_AUDIT_ACTIONS = (
    "wiki.compile.document",
    "wiki.compile.all",
    "wiki.lint",
    "wiki.search_test",
)


def _parse_detail(raw: str) -> dict:
    try:
        parsed = json.loads(raw or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _wiki_log_scope(row: AuditLog, detail: dict) -> str:
    if row.resource_type == "wiki" and row.resource_id:
        return row.resource_id
    return str(detail.get("knowledge_scope") or "")


def _wiki_log_payload(row: AuditLog) -> dict:
    detail = _parse_detail(row.detail_json)
    return {
        "id": row.id,
        "action": row.action,
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "knowledge_scope": _wiki_log_scope(row, detail),
        "actor_user_id": row.actor_user_id,
        "actor_username": row.actor_username,
        "detail": detail,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _wiki_lint_audit_detail(result: dict) -> dict:
    keys = (
        "knowledge_scope",
        "report_type",
        "score",
        "page_count",
        "published_count",
        "finding_count",
        "orphan_page_count",
        "no_backlink_page_count",
        "broken_link_count",
        "failed_document_count",
        "rule_counts",
        "severity_counts",
    )
    return {key: result.get(key) for key in keys if key in result}


def _page_payload(page: WikiPage) -> dict:
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
        "created_at": page.created_at.isoformat() if page.created_at else None,
        "updated_at": page.updated_at.isoformat() if page.updated_at else None,
    }


@router.get("/api/admin/wiki/pages")
def list_wiki_pages(
    knowledge_scope: str = Query("production"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    pages = db.execute(
        select(WikiPage)
        .where(WikiPage.knowledge_scope == knowledge_scope)
        .order_by(WikiPage.updated_at.desc())
        .limit(limit)
    ).scalars().all()
    return {"items": [_page_payload(page) for page in pages], "count": len(pages)}


@router.get("/api/admin/wiki/pages/{page_id}")
def get_wiki_page(page_id: str, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    page = db.get(WikiPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Wiki page not found")
    payload = _page_payload(page)
    payload["content_md"] = page.content_md
    payload["sources"] = [
        {
            "document_id": source.document_id,
            "document_title": source.document.title if source.document else "",
            "chunk_id": source.chunk_id,
            "page_number": source.page_number,
            "source_order": source.source_order,
            "quote": source.quote,
        }
        for source in sorted(page.sources or [], key=lambda item: item.source_order or 0)
    ]
    return payload


@router.post("/api/admin/wiki/documents/{document_id}/compile")
def compile_document(document_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    result = compile_document_to_wiki(db, doc.id, publish=True)
    audit(
        db,
        actor,
        "wiki.compile.document",
        "document",
        doc.id,
        {"knowledge_scope": getattr(doc, "knowledge_scope", "production") or "production", **result},
    )
    db.commit()
    return result


@router.post("/api/admin/wiki/compile-all")
def compile_all_ready_documents(
    knowledge_scope: str = Query("production"),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    result = compile_ready_documents(db, knowledge_scope=knowledge_scope, limit=limit, publish=True)
    audit(db, actor, "wiki.compile.all", "wiki", knowledge_scope, {"limit": limit, **result})
    db.commit()
    return result


@router.get("/api/admin/wiki/logs")
def wiki_logs(
    knowledge_scope: str = Query("production"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    fetch_limit = limit if knowledge_scope == "all" else min(500, max(limit, limit * 5))
    rows = db.execute(
        select(AuditLog)
        .where(AuditLog.action.in_(list(WIKI_AUDIT_ACTIONS)))
        .order_by(AuditLog.created_at.desc())
        .limit(fetch_limit)
    ).scalars().all()
    items: list[dict] = []
    for row in rows:
        payload = _wiki_log_payload(row)
        if knowledge_scope != "all" and payload["knowledge_scope"] != knowledge_scope:
            continue
        items.append(payload)
        if len(items) >= limit:
            break
    return {
        "knowledge_scope": knowledge_scope,
        "count": len(items),
        "items": items,
        "actions": list(WIKI_AUDIT_ACTIONS),
    }


@router.get("/api/admin/wiki/status")
def wiki_status(
    knowledge_scope: str = Query("production"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    pages = db.execute(select(WikiPage).where(WikiPage.knowledge_scope == knowledge_scope)).scalars().all()
    statuses = db.execute(select(WikiCompileStatus)).scalars().all()
    health = evaluate_wiki_health(db, knowledge_scope=knowledge_scope, include_findings=False)
    return {
        "knowledge_scope": knowledge_scope,
        "page_count": len(pages),
        "compiled_document_count": sum(1 for item in statuses if item.status == "ready"),
        "failed_document_count": sum(1 for item in statuses if item.status == "failed"),
        "draft_count": sum(1 for item in pages if item.status == "draft"),
        "published_count": sum(1 for item in pages if item.status == "published"),
        "health_score": health["score"],
        "health_finding_count": health["finding_count"],
        "health_rule_counts": health["rule_counts"],
    }


@router.get("/api/admin/wiki/health")
def wiki_health(
    knowledge_scope: str = Query("production"),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return evaluate_wiki_health(db, knowledge_scope=knowledge_scope, include_findings=True)


@router.get("/api/admin/wiki/lint")
def wiki_lint(
    knowledge_scope: str = Query("production"),
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    result = evaluate_wiki_health(db, knowledge_scope=knowledge_scope, include_findings=True)
    audit(db, actor, "wiki.lint", "wiki", knowledge_scope, _wiki_lint_audit_detail(result))
    db.commit()
    return result


@router.get("/api/admin/wiki/graph")
def wiki_graph(
    knowledge_scope: str = Query("production"),
    status: str = Query("published", pattern="^(published|draft|archived|all)$"),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return build_wiki_graph(db, knowledge_scope=knowledge_scope, status=status, limit=limit)


@router.get("/api/admin/wiki/search-test")
def wiki_search_test(
    q: str = Query(..., min_length=1),
    knowledge_scope: str = Query("production"),
    top_k: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    contexts, meta = retrieve_wiki_contexts(db, q, actor, top_k=top_k, knowledge_scope=knowledge_scope)
    audit(
        db,
        actor,
        "wiki.search_test",
        "wiki",
        knowledge_scope,
        {
            "knowledge_scope": knowledge_scope,
            "query": q[:200],
            "top_k": top_k,
            "used": meta.get("used"),
            "candidate_count": meta.get("candidate_count"),
            "context_count": meta.get("context_count"),
            "best_score": meta.get("best_score"),
            "reason": meta.get("reason"),
        },
    )
    db.commit()
    return {"meta": meta, "contexts": contexts}
