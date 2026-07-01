from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ..citation_utils import bounded_limit
from ..database import get_db
from ..graph_retrieval import retrieve_graph_contexts
from ..graph_store import entity_to_dict, list_relations_with_entities, refresh_extraction_counts, relation_to_dict, search_entities, set_extraction_status
from ..models import BackgroundTask, Document, GraphEntity, GraphExtractionStatus, GraphMention, GraphRelation, User
from .deps import audit, new_id, require_admin

router = APIRouter()


class RelationStatusUpdate(BaseModel):
    status: str


class GraphSearchTestRequest(BaseModel):
    question: str
    top_k: int = 8


def _status_to_dict(row: GraphExtractionStatus | None) -> dict:
    if not row:
        return {
            "status": "not_started",
            "message": "",
            "entity_count": 0,
            "relation_count": 0,
            "pending_count": 0,
            "error_message": "",
            "updated_at": None,
        }
    return {
        "status": row.status,
        "message": row.message,
        "entity_count": row.entity_count,
        "relation_count": row.relation_count,
        "pending_count": row.pending_count,
        "error_message": row.error_message,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("/api/admin/graph/overview")
def graph_overview(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    entity_count = db.scalar(select(func.count(GraphEntity.id)).where(GraphEntity.status != "ignored")) or 0
    relation_count = db.scalar(select(func.count(GraphRelation.id)).where(GraphRelation.status.in_(["confirmed", "auto", "pending"]))) or 0
    pending_count = db.scalar(select(func.count(GraphRelation.id)).where(GraphRelation.status == "pending")) or 0
    ready_docs = db.scalar(select(func.count(GraphExtractionStatus.document_id)).where(GraphExtractionStatus.status == "ready")) or 0
    failed_docs = db.scalar(select(func.count(GraphExtractionStatus.document_id)).where(GraphExtractionStatus.status == "failed")) or 0
    return {
        "entity_count": int(entity_count),
        "relation_count": int(relation_count),
        "pending_count": int(pending_count),
        "ready_document_count": int(ready_docs),
        "failed_document_count": int(failed_docs),
    }


@router.get("/api/admin/graph/documents")
def graph_documents(
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row_limit = bounded_limit(limit, 200, 500)
    docs = db.execute(
        select(Document).where(~Document.source_type.like("chat_%")).order_by(Document.created_at.desc()).limit(row_limit)
    ).scalars().all()
    statuses = {row.document_id: row for row in db.execute(select(GraphExtractionStatus)).scalars().all()}
    return [
        {
            "id": doc.id,
            "title": doc.title,
            "filename": doc.filename,
            "source_type": doc.source_type,
            "created_at": doc.created_at.isoformat() if doc.created_at else None,
            "graph": _status_to_dict(statuses.get(doc.id)),
        }
        for doc in docs
    ]


@router.get("/api/admin/graph/entities")
def graph_entities(
    q: str = "",
    limit: int = Query(100, ge=1, le=300),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row_limit = bounded_limit(limit, 100, 300)
    rows = search_entities(db, q, limit=row_limit)
    mention_counts = dict(
        db.execute(select(GraphMention.entity_id, func.count(GraphMention.id)).group_by(GraphMention.entity_id)).all()
    )
    result = []
    for row in rows:
        item = entity_to_dict(row)
        item["mention_count"] = int(mention_counts.get(row.id, 0))
        result.append(item)
    return result


@router.get("/api/admin/graph/relations")
def graph_relations(
    status: str = Query("", description="pending/confirmed/ignored/auto"),
    document_id: str = "",
    q: str = "",
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row_limit = bounded_limit(limit, 200, 500)
    stmt = select(GraphRelation)
    if status:
        stmt = stmt.where(GraphRelation.status == status)
    if document_id:
        stmt = stmt.where(GraphRelation.source_document_id == document_id)
    if q:
        matched = search_entities(db, q, limit=50)
        ids = [item.id for item in matched]
        if ids:
            stmt = stmt.where((GraphRelation.source_entity_id.in_(ids)) | (GraphRelation.target_entity_id.in_(ids)))
        else:
            stmt = stmt.where(GraphRelation.evidence_text.like(f"%{q}%"))
    stmt = stmt.order_by(GraphRelation.updated_at.desc(), GraphRelation.created_at.desc()).limit(row_limit)
    rows = list_relations_with_entities(db, stmt)
    return [relation_to_dict(row) for row in rows]


@router.put("/api/admin/graph/relations/{relation_id}")
def update_graph_relation(
    relation_id: str,
    req: RelationStatusUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_admin),
):
    status = (req.status or "").strip().lower()
    if status not in {"pending", "confirmed", "ignored", "auto"}:
        raise HTTPException(status_code=400, detail="不支持的关系状态")
    row = db.get(GraphRelation, relation_id)
    if not row:
        raise HTTPException(status_code=404, detail="关系不存在")
    row.status = status
    row.updated_at = datetime.utcnow()
    audit(db, actor, "graph.relation.update", "graph_relation", row.id, {"status": status, "document_id": row.source_document_id})
    refresh_extraction_counts(db, row.source_document_id, status="ready", message="关系状态已更新")
    db.commit()
    return relation_to_dict(row)


@router.post("/api/admin/documents/{document_id}/graph/rebuild")
def rebuild_document_graph(document_id: str, db: Session = Depends(get_db), actor: User = Depends(require_admin)):
    doc = db.get(Document, document_id)
    if not doc or str(doc.source_type or "").startswith("chat_"):
        raise HTTPException(status_code=404, detail="文档不存在")
    db.query(BackgroundTask).filter(
        BackgroundTask.document_id == doc.id,
        BackgroundTask.task_type.in_(["graph_extract", "graph_rebuild"]),
        BackgroundTask.status.in_(["pending", "running"]),
    ).delete(synchronize_session=False)
    task = BackgroundTask(id=new_id(), task_type="graph_rebuild", document_id=doc.id, status="pending", created_by=actor.id)
    db.add(task)
    set_extraction_status(db, doc.id, "pending", "已进入知识图谱重建队列")
    audit(db, actor, "graph.rebuild.enqueue", "document", doc.id, {"task_id": task.id})
    db.commit()
    return {"ok": True, "task_id": task.id, "status": "queued"}


@router.post("/api/admin/graph/search-test")
def graph_search_test(req: GraphSearchTestRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")
    contexts = retrieve_graph_contexts(db, question, user, top_k=max(1, min(req.top_k or 8, 20)))
    return {"question": question, "count": len(contexts), "contexts": contexts}
