import json
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional

from .config import EMBEDDING_DIM, QDRANT_API_KEY, QDRANT_COLLECTION, QDRANT_URL, VECTOR_BACKEND
from .document_metadata import get_document_kind, get_document_scope, normalize_document_scope


def qdrant_enabled() -> bool:
    return VECTOR_BACKEND == "qdrant"


class QdrantUnavailable(RuntimeError):
    pass


def _request(method: str, path: str, body: Optional[dict] = None, timeout: float = 6.0) -> dict:
    url = QDRANT_URL.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if QDRANT_API_KEY:
        headers["api-key"] = QDRANT_API_KEY
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise QdrantUnavailable(f"Qdrant HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise QdrantUnavailable(str(exc)) from exc


def qdrant_health() -> dict:
    if not qdrant_enabled():
        return {
            "backend": "sqlite",
            "qdrant_enabled": False,
            "qdrant_ready": False,
            "degraded": False,
            "status": "local",
            "message": "当前 VECTOR_BACKEND=local，使用 SQLite 本地向量检索。",
        }
    try:
        data = _request("GET", f"/collections/{QDRANT_COLLECTION}", timeout=2.0)
        result = data.get("result") or {}
        points_count = result.get("points_count") or result.get("vectors_count") or 0
        return {
            "backend": "qdrant",
            "qdrant_enabled": True,
            "qdrant_ready": True,
            "degraded": False,
            "status": "ready",
            "collection": QDRANT_COLLECTION,
            "points_count": points_count,
            "message": f"Qdrant 连接正常，集合 {QDRANT_COLLECTION} 可用。",
        }
    except QdrantUnavailable as exc:
        return {
            "backend": "sqlite_fallback",
            "qdrant_enabled": True,
            "qdrant_ready": False,
            "degraded": True,
            "status": "degraded",
            "collection": QDRANT_COLLECTION,
            "message": f"Qdrant 暂不可用，系统已回退到 SQLite 本地向量检索：{exc}",
        }


def ensure_collection(vector_size: int = EMBEDDING_DIM):
    if not qdrant_enabled():
        return
    try:
        _request("GET", f"/collections/{QDRANT_COLLECTION}", timeout=3.0)
    except QdrantUnavailable:
        _request(
            "PUT",
            f"/collections/{QDRANT_COLLECTION}",
            {"vectors": {"size": vector_size, "distance": "Cosine"}},
            timeout=10.0,
        )


def document_payload(doc, chunk) -> dict:
    source_type = str(doc.source_type or "")
    visibility = "personal" if source_type.startswith("chat_") else "managed"
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": chunk.id,
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "content": chunk.content,
        "source_type": source_type,
        "knowledge_scope": get_document_scope(doc),
        "document_kind": get_document_kind(doc),
        "created_by": doc.created_by or "",
        "visibility": visibility,
        "group_ids": [g.id for g in getattr(doc, "groups", [])],
    }


def upsert_document_chunks(doc, chunks: Iterable[Any]):
    if not qdrant_enabled():
        return
    points = []
    for chunk in chunks:
        points.append(
            {
                "id": chunk.id,
                "vector": json.loads(chunk.embedding_json),
                "payload": document_payload(doc, chunk),
            }
        )
    if not points:
        return
    ensure_collection(len(points[0]["vector"]))
    _request("PUT", f"/collections/{QDRANT_COLLECTION}/points?wait=true", {"points": points}, timeout=20.0)


def delete_document_vectors(document_id: str):
    if not qdrant_enabled():
        return
    ensure_collection()
    _request(
        "POST",
        f"/collections/{QDRANT_COLLECTION}/points/delete?wait=true",
        {"filter": {"must": [{"key": "document_id", "match": {"value": document_id}}]}},
        timeout=15.0,
    )


def _condition(key: str, value: Any) -> dict:
    return {"key": key, "match": {"value": value}}


def permission_filter(user_id: str, is_admin: bool, group_ids: List[str], knowledge_scope: str = "production") -> dict:
    managed_scope = normalize_document_scope(knowledge_scope, "production")
    managed_scope_filter = [] if managed_scope == "all" else [_condition("knowledge_scope", managed_scope)]
    personal = {"must": [_condition("visibility", "personal"), _condition("created_by", user_id), *managed_scope_filter]}
    should = [personal]
    if is_admin:
        should.append({"must": [_condition("visibility", "managed"), *managed_scope_filter]})
    else:
        for group_id in group_ids:
            should.append({"must": [_condition("visibility", "managed"), _condition("group_ids", group_id), *managed_scope_filter]})
    return {"should": should}


def search_chunks(query_vector: List[float], user_id: str, is_admin: bool, group_ids: List[str], limit: int, knowledge_scope: str = "production") -> List[dict]:
    if not qdrant_enabled():
        raise QdrantUnavailable("Qdrant backend is not enabled")
    ensure_collection(len(query_vector))
    body = {
        "vector": query_vector,
        "limit": limit,
        "with_payload": True,
        "with_vector": False,
        "filter": permission_filter(user_id, is_admin, group_ids, knowledge_scope),
    }
    data = _request("POST", f"/collections/{QDRANT_COLLECTION}/points/search", body, timeout=10.0)
    result = data.get("result") or []
    rows = []
    for item in result:
        payload = item.get("payload") or {}
        rows.append(
            {
                "document_id": payload.get("document_id", ""),
                "document_title": payload.get("document_title", ""),
                "filename": payload.get("filename", ""),
                "chunk_id": payload.get("chunk_id", ""),
                "page_number": payload.get("page_number"),
                "chunk_index": payload.get("chunk_index"),
                "source_type": payload.get("source_type", ""),
                "knowledge_scope": payload.get("knowledge_scope", "production"),
                "document_kind": payload.get("document_kind", "general"),
                "content": payload.get("content", ""),
                "score": item.get("score", 0),
            }
        )
    return rows
