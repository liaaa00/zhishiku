from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .graph_store import normalize_entity_name, relation_to_dict, search_entities
from .models import GraphRelation, User
from .retrieval import accessible_document_ids, user_group_ids


def retrieve_graph_contexts(db: Session, question: str, user: User, top_k: int = 8) -> list[dict]:
    text = str(question or "").strip()
    if not text:
        return []
    group_ids = user_group_ids(user)
    allowed_doc_ids = accessible_document_ids(db, user, group_ids)
    if not allowed_doc_ids:
        return []

    direct_entities = search_entities(db, text, limit=20)
    normalized_question = normalize_entity_name(text)
    matched_ids: list[str] = []
    for entity in direct_entities:
        normalized_name = normalize_entity_name(entity.name)
        if not normalized_name:
            continue
        if normalized_name in normalized_question or normalized_question in normalized_name or entity.name in text:
            matched_ids.append(entity.id)
    if not matched_ids:
        matched_ids = [item.id for item in direct_entities[:5]]
    if not matched_ids:
        return []

    rows = db.execute(
        select(GraphRelation)
        .options(
            selectinload(GraphRelation.source_entity),
            selectinload(GraphRelation.target_entity),
            selectinload(GraphRelation.document),
            selectinload(GraphRelation.chunk),
        )
        .where(
            GraphRelation.status.in_(["confirmed", "auto"]),
            GraphRelation.source_document_id.in_(allowed_doc_ids),
            or_(GraphRelation.source_entity_id.in_(matched_ids), GraphRelation.target_entity_id.in_(matched_ids)),
        )
        .order_by(GraphRelation.confidence.desc(), GraphRelation.updated_at.desc())
        .limit(max(1, top_k))
    ).scalars().all()

    contexts: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        doc = row.document
        source_name = row.source_entity.name if row.source_entity else ""
        target_name = row.target_entity.name if row.target_entity else ""
        evidence = row.evidence_text or row.description or ""
        content = f"{source_name} --{row.relation_type}--> {target_name}。证据：{evidence}".strip()
        contexts.append(
            {
                "document_id": row.source_document_id,
                "chunk_id": row.source_chunk_id,
                "document_title": doc.title if doc else "",
                "filename": doc.filename if doc else "",
                "page_number": row.source_page_number,
                "content": content,
                "source_type": "graph",
                "retrieval_channel": "graph",
                "score": row.confidence,
                "graph": relation_to_dict(row),
            }
        )
    return contexts
