from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Document, User, WikiCompileStatus, WikiPage
from ..wiki.compiler import compile_document_to_wiki, compile_ready_documents
from ..wiki.graph import build_wiki_graph
from ..wiki.health import evaluate_wiki_health
from ..wiki.search import retrieve_wiki_contexts
from .deps import audit, require_admin

router = APIRouter()


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
    audit(db, actor, "wiki.compile.document", "document", doc.id, result)
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
    return {"meta": meta, "contexts": contexts}
