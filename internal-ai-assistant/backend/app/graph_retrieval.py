import re

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .graph_store import normalize_entity_name, relation_to_dict, search_entities
from .models import GraphRelation, User
from .retrieval import accessible_document_ids, user_group_ids


CITY_TERMS = (
    "北京", "上海", "深圳", "广州", "宁波", "北仑", "宁波北仑", "杭州", "成都", "郑州", "石家庄", "贵阳", "南京", "乌鲁木齐",
)
BUSINESS_TERMS = (
    "社保", "医保", "公积金", "银行账户", "社保公积金账户", "截止时间", "操作规则", "预计缴款时间", "开设公司", "公司名称", "公积金比例",
    "劳动合同", "电子劳动合同", "入职", "入职联系", "报岗", "报岗集约录入", "商保投保", "待遇申报", "材料用印申请", "合同组",
)


def _month_tokens(text: str) -> list[str]:
    tokens: list[str] = []
    for year, month in re.findall(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", text or ""):
        try:
            tokens.append(f"{year}{int(month):02d}")
        except ValueError:
            pass
    tokens.extend(re.findall(r"\b20\d{4}\b", text or ""))
    return list(dict.fromkeys(tokens))


def _query_entity_terms(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", text or "")
    months = _month_tokens(text)
    cities = [city for city in CITY_TERMS if city in compact]
    businesses = [term for term in BUSINESS_TERMS if term in compact]
    terms: list[str] = []
    terms.extend(months)
    terms.extend(cities)
    terms.extend(businesses)
    for city in cities:
        terms.append(f"{city}派单规则")
    for month in months:
        for city in cities:
            terms.append(f"{month}{city}")
            for biz in businesses[:4]:
                terms.append(f"{month}{city}{biz}")
    for phrase in re.findall(r"[\u4e00-\u9fff]{2,12}", compact):
        if any(marker in phrase for marker in ("劳动合同", "待遇申报", "入职", "账号注销", "薪酬查询")):
            terms.append(phrase)
    return list(dict.fromkeys(term for term in terms if term))[:40]


def _candidate_entities(db: Session, text: str, limit: int = 30):
    entities = []
    for query in [text, *_query_entity_terms(text)]:
        for entity in search_entities(db, query, limit=max(3, min(10, limit))):
            if entity.id not in {item.id for item in entities}:
                entities.append(entity)
            if len(entities) >= limit:
                return entities
    return entities


def retrieve_graph_contexts(db: Session, question: str, user: User, top_k: int = 8) -> list[dict]:
    text = str(question or "").strip()
    if not text:
        return []
    group_ids = user_group_ids(user)
    allowed_doc_ids = accessible_document_ids(db, user, group_ids)
    if not allowed_doc_ids:
        return []

    direct_entities = _candidate_entities(db, text, limit=30)
    matched_ids = [item.id for item in direct_entities[:12]]
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
