import json
import re
from typing import Any

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import GRAPH_AUTO_CONFIRM_THRESHOLD, GRAPH_MAX_CHARS_PER_CHUNK, GRAPH_MAX_CHUNKS_PER_DOCUMENT, GRAPH_PENDING_THRESHOLD
from .graph_prompts import build_graph_extraction_messages
from .graph_schema import normalize_entity_type, normalize_relation_type
from .graph_store import create_mention, create_relation, delete_document_graph, get_or_create_entity, refresh_extraction_counts, set_extraction_status
from .models import Document, DocumentChunk
from .settings_service import get_model_config


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _extract_json_object(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return {"entities": [], "relations": []}
        try:
            parsed = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return {"entities": [], "relations": []}
    return parsed if isinstance(parsed, dict) else {"entities": [], "relations": []}


def extract_graph_from_text(document_title: str, chunk_text: str, cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    api_key = cfg.get("api_key") or ""
    if not api_key:
        raise ValueError("未配置模型 API Key，无法自动抽取知识图谱")
    client = OpenAI(api_key=api_key, base_url=cfg.get("base_url") or "https://api.deepseek.com", timeout=60.0, max_retries=1)
    response = client.chat.completions.create(
        model=cfg.get("model") or "deepseek-chat",
        messages=build_graph_extraction_messages(document_title, chunk_text),
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content or "{}"
    return _extract_json_object(content)


def _entity_key(name: str, entity_type: str) -> tuple[str, str]:
    return (str(name or "").strip(), normalize_entity_type(entity_type))


def _parse_table_line(line: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in str(line or "").split("|"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and value:
            fields[key] = value
    return fields


def extract_graph_from_table_text(document_title: str, chunk_text: str) -> dict:
    """Deterministic graph extraction for table chunks.

    Spreadsheet chunks are already normalized as lines like:
    表格行 | 工作表=202603 | 城市=宁波 | 截止时间-社保=24号
    Calling an LLM for every table chunk is slow and can time out, so we create
    conservative city/unit/rule/deadline relations directly from structured rows.
    """
    entities: list[dict] = []
    relations: list[dict] = []
    seen_entities: set[tuple[str, str]] = set()

    def add_entity(name: str, entity_type: str, description: str = "") -> None:
        clean = str(name or "").strip()
        normalized_type = normalize_entity_type(entity_type)
        if not clean:
            return
        key = _entity_key(clean, normalized_type)
        if key in seen_entities:
            return
        seen_entities.add(key)
        entities.append({"name": clean, "type": normalized_type, "description": description, "confidence": 0.95})

    for raw_line in str(chunk_text or "").split("表格行 |"):
        fields = _parse_table_line(raw_line)
        if not fields:
            continue
        sheet = fields.get("工作表") or fields.get("sheet") or ""
        province = fields.get("省份") or ""
        city = fields.get("城市") or ""
        unit = fields.get("单位名称") or ""
        if not city and not unit:
            continue
        row_title = " / ".join(item for item in [sheet, province, city] if item)
        evidence = "表格行 | " + " | ".join(f"{key}={value}" for key, value in fields.items())
        city_name = f"{city}派单规则" if city else unit
        add_entity(city_name, "city", f"{document_title} 中 {row_title} 的派单规则")
        if unit:
            add_entity(unit, "role", f"{city or province} 对应单位")
            relations.append({
                "source": city_name,
                "target": unit,
                "relation_type": "handled_by",
                "evidence": evidence,
                "confidence": 0.95,
                "description": f"{city or province} 派单由 {unit} 处理",
            })
        for category in ["社保", "医保", "公积金"]:
            deadline = fields.get(f"截止时间-{category}") or fields.get(f"{category}截止时间")
            if deadline:
                deadline_name = f"{sheet}{city}{category}截止时间{deadline}" if sheet else f"{city}{category}截止时间{deadline}"
                add_entity(deadline_name, "deadline", f"{row_title} {category} 截止时间：{deadline}")
                relations.append({
                    "source": city_name,
                    "target": deadline_name,
                    "relation_type": "has_deadline",
                    "evidence": evidence,
                    "confidence": 0.95,
                    "description": f"{city or province} {category} 派单截止时间为 {deadline}",
                })
            rule = fields.get(f"操作规则-{category}") or fields.get(f"{category}操作规则")
            if rule:
                rule_name = f"{sheet}{city}{category}操作规则" if sheet else f"{city}{category}操作规则"
                add_entity(rule_name, "rule", rule)
                relations.append({
                    "source": city_name,
                    "target": rule_name,
                    "relation_type": "requires",
                    "evidence": evidence,
                    "confidence": 0.9,
                    "description": f"{city or province} {category} 操作规则：{rule}",
                })
    return {"entities": entities, "relations": relations}


def _looks_like_table_chunk(text: str) -> bool:
    value = str(text or "")
    return "表格行 |" in value and ("截止时间-" in value or "操作规则-" in value or "工作表=" in value)


def _save_chunk_graph(db: Session, doc: Document, chunk: DocumentChunk, payload: dict) -> tuple[int, int, int]:
    entities_by_name: dict[str, Any] = {}
    entity_count = 0
    relation_count = 0
    pending_count = 0

    raw_entities = payload.get("entities") if isinstance(payload, dict) else []
    if not isinstance(raw_entities, list):
        raw_entities = []
    for item in raw_entities[:80]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        entity_type = normalize_entity_type(item.get("type") or item.get("entity_type"))
        confidence = _safe_float(item.get("confidence"), 0.6)
        if not name or confidence < GRAPH_PENDING_THRESHOLD:
            continue
        entity = get_or_create_entity(db, name, entity_type, confidence, str(item.get("description") or ""))
        if not entity:
            continue
        entities_by_name[name] = entity
        create_mention(db, entity, doc.id, chunk.id, chunk.page_number, name, confidence)
        entity_count += 1

    raw_relations = payload.get("relations") if isinstance(payload, dict) else []
    if not isinstance(raw_relations, list):
        raw_relations = []
    for item in raw_relations[:120]:
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source") or item.get("source_entity") or "").strip()
        target_name = str(item.get("target") or item.get("target_entity") or "").strip()
        if not source_name or not target_name or source_name == target_name:
            continue
        confidence = _safe_float(item.get("confidence"), 0.6)
        if confidence < GRAPH_PENDING_THRESHOLD:
            continue
        relation_type = normalize_relation_type(item.get("relation_type") or item.get("type"))
        source = entities_by_name.get(source_name) or get_or_create_entity(db, source_name, "other", confidence)
        target = entities_by_name.get(target_name) or get_or_create_entity(db, target_name, "other", confidence)
        if not source or not target:
            continue
        status = "auto" if confidence >= GRAPH_AUTO_CONFIRM_THRESHOLD else "pending"
        relation = create_relation(
            db,
            source,
            target,
            relation_type,
            document_id=doc.id,
            chunk_id=chunk.id,
            page_number=chunk.page_number,
            evidence_text=str(item.get("evidence") or item.get("evidence_text") or ""),
            confidence=confidence,
            status=status,
            description=str(item.get("description") or ""),
        )
        if relation:
            relation_count += 1
            if relation.status == "pending":
                pending_count += 1
    return entity_count, relation_count, pending_count


def extract_graph_for_document(db: Session, document_id: str) -> dict:
    doc = db.get(Document, document_id)
    if not doc:
        raise ValueError("文档不存在")
    chunks = db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
        .limit(max(1, GRAPH_MAX_CHUNKS_PER_DOCUMENT))
    ).scalars().all()
    if not chunks:
        set_extraction_status(db, document_id, "failed", error_message="文档尚未解析出文本切片")
        db.flush()
        return {"status": "failed", "message": "文档尚未解析出文本切片", "entity_count": 0, "relation_count": 0, "pending_count": 0}

    set_extraction_status(db, document_id, "processing", "正在抽取知识图谱")
    db.flush()
    cfg = get_model_config(db)
    delete_document_graph(db, document_id)
    db.flush()

    total_entities = 0
    total_relations = 0
    total_pending = 0
    chunk_errors: list[str] = []
    for chunk in chunks:
        text = " ".join(str(chunk.content or "").split())[:GRAPH_MAX_CHARS_PER_CHUNK]
        if len(text) < 20:
            continue
        try:
            if _looks_like_table_chunk(text):
                payload = extract_graph_from_table_text(doc.title, text)
            else:
                payload = extract_graph_from_text(doc.title, text, cfg)
            e_count, r_count, p_count = _save_chunk_graph(db, doc, chunk, payload)
            total_entities += e_count
            total_relations += r_count
            total_pending += p_count
            db.flush()
        except Exception as exc:
            chunk_errors.append(f"chunk {chunk.chunk_index}: {exc}")
            db.rollback()
            set_extraction_status(db, document_id, "processing", "部分切片抽取失败，正在继续处理其余内容", error_message="；".join(chunk_errors[-3:]))
            db.flush()

    if total_entities == 0 and total_relations == 0 and chunk_errors:
        error_message = "；".join(chunk_errors[-5:])
        set_extraction_status(db, document_id, "failed", error_message=error_message)
        db.flush()
        raise RuntimeError(error_message)

    message = "知识图谱抽取完成"
    if chunk_errors:
        message = f"知识图谱抽取完成，{len(chunk_errors)} 个切片因超时或模型错误被跳过"
    row = refresh_extraction_counts(db, document_id, status="ready", message=message)
    db.flush()
    return {
        "status": row.status,
        "entity_count": row.entity_count,
        "relation_count": row.relation_count,
        "pending_count": row.pending_count,
        "skipped_chunks": len(chunk_errors),
    }
