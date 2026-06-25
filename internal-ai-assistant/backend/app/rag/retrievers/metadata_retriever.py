from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import Document, User
from ...retrieval import has_document_access, user_group_ids
from ..schemas import QueryAnalysis, RetrievalResult

MAX_METADATA_SCAN = 500


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _terms(question: str, analysis: QueryAnalysis) -> list[str]:
    terms: list[str] = []
    terms.extend(analysis.entities or [])
    text = question or ""
    quoted = re.findall(r"[《\"“](.*?)[》\"”]", text)
    terms.extend(item.strip() for item in quoted if item.strip())
    for chunk in re.findall(r"[\u4e00-\u9fffA-Za-z0-9_\-.]{2,}", text):
        if chunk not in {"哪个文件", "哪些文件", "文件名", "最新", "最近", "上传", "文档"}:
            terms.append(chunk)
    return list(dict.fromkeys(term for term in terms if term))[:40]


def _score_doc(doc: Document, terms: list[str], question: str) -> tuple[float, list[str]]:
    haystack = _compact(" ".join([doc.title or "", doc.filename or "", doc.source_type or ""]))
    hits: list[str] = []
    score = 0.18
    for term in terms:
        needle = _compact(term)
        if needle and needle in haystack:
            hits.append(term)
            score += 0.16 if len(needle) <= 4 else 0.24
    if any(word in question for word in ("最新", "最近", "最近上传", "最新上传")):
        score += 0.18
    if any(word in question.lower() for word in ("pdf", "xlsx", "excel", "csv", "docx", "word")):
        ext = (doc.filename or "").rsplit(".", 1)[-1].lower() if "." in (doc.filename or "") else ""
        if ext and ext in question.lower():
            score += 0.2
            hits.append(ext)
    return min(score, 1.0), hits[:12]


def _context_for_doc(doc: Document, score: float, hits: list[str]) -> dict:
    created_at = doc.created_at.isoformat() if isinstance(doc.created_at, datetime) else str(doc.created_at or "")
    content = "\n".join(
        [
            f"文档标题：{doc.title or ''}",
            f"文件名：{doc.filename or ''}",
            f"文件类型：{doc.source_type or ''}",
            f"上传时间：{created_at}",
        ]
    )
    return {
        "document_id": doc.id,
        "document_title": doc.title,
        "filename": doc.filename,
        "chunk_id": "",
        "page_number": None,
        "chunk_index": f"metadata:{doc.id}",
        "source_type": str(doc.source_type or ""),
        "content": content,
        "score": round(score, 4),
        "match_terms": hits,
        "match_reason": "文档元数据命中",
        "retrieval_channel": "metadata",
        "location": "metadata",
        "metadata_source": True,
        "created_at": created_at,
    }


def search(db: Session, question: str, user: User, analysis: QueryAnalysis, top_k: int = 5) -> RetrievalResult:
    group_ids = user_group_ids(user)
    docs = db.execute(select(Document).order_by(Document.created_at.desc()).limit(MAX_METADATA_SCAN)).scalars().all()
    accessible_docs = [doc for doc in docs if has_document_access(db, doc, user, group_ids)]
    terms = _terms(question, analysis)
    scored: list[tuple[float, Document, list[str]]] = []
    latest_bias = any(word in question for word in ("最新", "最近", "最近上传", "最新上传"))
    for doc in accessible_docs:
        score, hits = _score_doc(doc, terms, question)
        if hits or latest_bias or not terms:
            scored.append((score, doc, hits))
    scored.sort(key=lambda item: (item[0], item[1].created_at), reverse=True)
    contexts = [_context_for_doc(doc, score, hits) for score, doc, hits in scored[: max(1, min(top_k, 10))]]
    meta = {
        "mode": "metadata",
        "intent": "metadata_query",
        "candidate_count": len(accessible_docs),
        "filtered_count": len(scored),
        "final_context_count": len(contexts),
        "unique_document_count": len({c.get("document_id") for c in contexts if c.get("document_id")}),
        "best_score": max((float(item.get("score") or 0.0) for item in contexts), default=0.0),
        "backend": "metadata",
        "fallback_note": "metadata_query_mode",
        "query_analysis": analysis.to_dict(),
    }
    return RetrievalResult(contexts, "metadata", f"metadata_query_mode; docs={len(contexts)}", len(accessible_docs), meta)
