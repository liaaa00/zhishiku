import re
import unicodedata
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .models import Document, GraphEntity, GraphExtractionStatus, GraphMention, GraphRelation
from .routers.deps import new_id


def normalize_entity_name(name: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(name or "")).strip().lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，。；：、,.!！?？()（）\[\]【】《》<>\"'“”‘’]", "", text)
    return text[:255]


def get_or_create_entity(
    db: Session,
    name: str,
    entity_type: str,
    confidence: float = 0.0,
    description: str = "",
) -> GraphEntity | None:
    clean_name = str(name or "").strip()[:255]
    normalized_name = normalize_entity_name(clean_name)
    if not clean_name or not normalized_name:
        return None
    row = db.execute(
        select(GraphEntity).where(
            GraphEntity.normalized_name == normalized_name,
            GraphEntity.entity_type == entity_type,
        )
    ).scalars().first()
    if row:
        row.name = row.name or clean_name
        row.description = row.description or (description or "")[:1000]
        row.confidence = max(float(row.confidence or 0.0), float(confidence or 0.0))
        row.updated_at = datetime.utcnow()
        return row
    row = GraphEntity(
        id=new_id(),
        name=clean_name,
        normalized_name=normalized_name,
        entity_type=entity_type,
        description=(description or "")[:1000],
        confidence=max(0.0, min(float(confidence or 0.0), 1.0)),
        status="confirmed",
    )
    db.add(row)
    db.flush()
    return row


def create_mention(
    db: Session,
    entity: GraphEntity,
    document_id: str,
    chunk_id: str | None,
    page_number: int | None,
    mention_text: str,
    confidence: float,
) -> GraphMention:
    row = GraphMention(
        id=new_id(),
        entity_id=entity.id,
        document_id=document_id,
        chunk_id=chunk_id,
        page_number=page_number,
        mention_text=(mention_text or entity.name or "")[:255],
        confidence=max(0.0, min(float(confidence or 0.0), 1.0)),
    )
    db.add(row)
    return row


def create_relation(
    db: Session,
    source_entity: GraphEntity,
    target_entity: GraphEntity,
    relation_type: str,
    document_id: str,
    chunk_id: str | None = None,
    page_number: int | None = None,
    evidence_text: str = "",
    confidence: float = 0.0,
    status: str = "pending",
    description: str = "",
) -> GraphRelation | None:
    if not source_entity or not target_entity or source_entity.id == target_entity.id:
        return None
    evidence = " ".join(str(evidence_text or "").split())[:1500]
    existing = db.execute(
        select(GraphRelation).where(
            GraphRelation.source_entity_id == source_entity.id,
            GraphRelation.target_entity_id == target_entity.id,
            GraphRelation.relation_type == relation_type,
            GraphRelation.source_document_id == document_id,
            GraphRelation.source_chunk_id == chunk_id,
            GraphRelation.evidence_text == evidence,
        )
    ).scalars().first()
    if existing:
        existing.confidence = max(float(existing.confidence or 0.0), float(confidence or 0.0))
        if status == "auto" and existing.status == "pending":
            existing.status = "auto"
        existing.updated_at = datetime.utcnow()
        return existing
    row = GraphRelation(
        id=new_id(),
        source_entity_id=source_entity.id,
        target_entity_id=target_entity.id,
        relation_type=relation_type,
        description=(description or "")[:1000],
        confidence=max(0.0, min(float(confidence or 0.0), 1.0)),
        source_document_id=document_id,
        source_chunk_id=chunk_id,
        source_page_number=page_number,
        evidence_text=evidence,
        status=status if status in {"pending", "confirmed", "ignored", "auto"} else "pending",
    )
    db.add(row)
    return row


def delete_document_graph(db: Session, document_id: str) -> None:
    db.query(GraphMention).filter(GraphMention.document_id == document_id).delete(synchronize_session=False)
    db.query(GraphRelation).filter(GraphRelation.source_document_id == document_id).delete(synchronize_session=False)


def set_extraction_status(
    db: Session,
    document_id: str,
    status: str,
    message: str = "",
    error_message: str = "",
    entity_count: int | None = None,
    relation_count: int | None = None,
    pending_count: int | None = None,
) -> GraphExtractionStatus:
    row = db.get(GraphExtractionStatus, document_id)
    if not row:
        row = GraphExtractionStatus(document_id=document_id)
        db.add(row)
    row.status = status
    row.message = message[:1500]
    row.error_message = error_message[:1500]
    if entity_count is not None:
        row.entity_count = entity_count
    if relation_count is not None:
        row.relation_count = relation_count
    if pending_count is not None:
        row.pending_count = pending_count
    row.updated_at = datetime.utcnow()
    return row


def refresh_extraction_counts(db: Session, document_id: str, status: str = "ready", message: str = "") -> GraphExtractionStatus:
    relation_count = db.scalar(select(func.count(GraphRelation.id)).where(GraphRelation.source_document_id == document_id)) or 0
    pending_count = db.scalar(
        select(func.count(GraphRelation.id)).where(GraphRelation.source_document_id == document_id, GraphRelation.status == "pending")
    ) or 0
    entity_count = db.scalar(
        select(func.count(func.distinct(GraphMention.entity_id))).where(GraphMention.document_id == document_id)
    ) or 0
    return set_extraction_status(
        db,
        document_id,
        status=status,
        message=message,
        entity_count=int(entity_count),
        relation_count=int(relation_count),
        pending_count=int(pending_count),
    )


def entity_to_dict(row: GraphEntity) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "normalized_name": row.normalized_name,
        "entity_type": row.entity_type,
        "description": row.description,
        "confidence": row.confidence,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def relation_to_dict(row: GraphRelation) -> dict:
    doc = row.document
    return {
        "id": row.id,
        "source_entity_id": row.source_entity_id,
        "source_entity_name": row.source_entity.name if row.source_entity else "",
        "target_entity_id": row.target_entity_id,
        "target_entity_name": row.target_entity.name if row.target_entity else "",
        "relation_type": row.relation_type,
        "description": row.description,
        "confidence": row.confidence,
        "source_document_id": row.source_document_id,
        "source_document_title": doc.title if doc else "",
        "source_document_filename": doc.filename if doc else "",
        "source_chunk_id": row.source_chunk_id,
        "source_page_number": row.source_page_number,
        "evidence_text": row.evidence_text,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def search_entities(db: Session, query: str, limit: int = 20) -> list[GraphEntity]:
    text = str(query or "").strip()
    normalized = normalize_entity_name(text)
    stmt = select(GraphEntity).where(GraphEntity.status != "ignored")
    if normalized:
        like = f"%{normalized}%"
        name_like = f"%{text}%"
        stmt = stmt.where(or_(GraphEntity.normalized_name.like(like), GraphEntity.name.like(name_like)))
    stmt = stmt.order_by(GraphEntity.confidence.desc(), GraphEntity.updated_at.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


def list_relations_with_entities(db: Session, stmt):
    return db.execute(
        stmt.options(
            selectinload(GraphRelation.source_entity),
            selectinload(GraphRelation.target_entity),
            selectinload(GraphRelation.document),
        )
    ).scalars().all()
