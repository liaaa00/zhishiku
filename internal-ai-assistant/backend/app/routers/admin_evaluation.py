from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..admin_schemas import ChatRequest
from ..citation_utils import bounded_limit
from ..database import get_db
from ..grounding import compute_grounding_confidence, serialize_sources
from ..models import Document, DocumentProcessingStatus, Feedback, User
from ..retrieval import adaptive_retrieve_contexts
from .chat_api import build_retrieval_debug_summary, build_source_quality_notice, model_contexts_for_answer
from .deps import require_admin

router = APIRouter()

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_REAL_CASES_PATH = ROOT_DIR / "tests" / "retrieval_eval_real_cases.json"
LOW_CONFIDENCE_THRESHOLD = 0.35


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"\s+", "", text)


def _load_real_eval_cases() -> list[dict[str, Any]]:
    if not DEFAULT_REAL_CASES_PATH.exists():
        return []
    try:
        payload = json.loads(DEFAULT_REAL_CASES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    return [case for case in payload.get("cases") or [] if isinstance(case, dict)]


def _context_title_text(context: dict[str, Any]) -> str:
    return " ".join(str(context.get(key) or "") for key in ("document_title", "filename", "document_id"))


def _context_full_text(context: dict[str, Any]) -> str:
    return " ".join(
        str(context.get(key) or "")
        for key in (
            "document_title",
            "filename",
            "document_id",
            "content",
            "location",
            "section_title",
            "anchor",
            "sheet_name",
            "row_number",
        )
    )


def _expected_groups(value: Any) -> list[list[str]]:
    if not value:
        return []
    groups: list[list[str]] = []
    for item in value:
        if isinstance(item, list):
            terms = [str(term) for term in item if str(term).strip()]
        else:
            terms = [str(item)] if str(item).strip() else []
        if terms:
            groups.append(terms)
    return groups


def _any_context_matches(contexts: list[dict[str, Any]], terms: list[str], *, scope: str = "full") -> bool:
    if not terms:
        return True
    for context in contexts:
        haystack = _context_title_text(context) if scope == "title" else _context_full_text(context)
        normalized = _normalize_text(haystack)
        if all(_normalize_text(term) in normalized for term in terms):
            return True
    return False


def _validate_case(case: dict[str, Any], contexts: list[dict[str, Any]], backend: str, meta: dict[str, Any]) -> list[str]:
    expected = case.get("expected") or {}
    errors: list[str] = []
    ranked_ids = [str(context.get("document_id") or "") for context in contexts]
    top_n = int(expected.get("top_n") or 0)
    top_contexts = contexts[:top_n] if top_n > 0 else contexts
    normalized_text = _normalize_text("\n".join(_context_full_text(context) for context in contexts))

    if expected.get("backend") and backend != expected.get("backend"):
        errors.append(f"期望检索通道 {expected.get('backend')}，实际 {backend}")
    if expected.get("top_doc") and (not ranked_ids or ranked_ids[0] != str(expected.get("top_doc"))):
        errors.append(f"首位文档应为 {expected.get('top_doc')}，实际 {ranked_ids[:5]}")
    for doc_id in expected.get("must_include_docs") or []:
        if str(doc_id) not in ranked_ids:
            errors.append(f"应命中文档 {doc_id}")
    for doc_id in expected.get("must_not_include_docs") or []:
        if str(doc_id) in ranked_ids:
            errors.append(f"不应命中文档 {doc_id}")
    if top_n > 0:
        top_ids = ranked_ids[:top_n]
        for doc_id in expected.get("top_n_must_include_docs") or []:
            if str(doc_id) not in top_ids:
                errors.append(f"前 {top_n} 条应包含文档 {doc_id}")
    for terms in _expected_groups(expected.get("must_match_titles")):
        if not _any_context_matches(contexts, terms, scope="title"):
            errors.append(f"标题应匹配 {'/'.join(terms)}")
    for terms in _expected_groups(expected.get("must_not_match_titles")):
        if _any_context_matches(contexts, terms, scope="title"):
            errors.append(f"标题不应匹配 {'/'.join(terms)}")
    for terms in _expected_groups(expected.get("top_n_must_match_titles")):
        if not _any_context_matches(top_contexts, terms, scope="title"):
            errors.append(f"前 {top_n or len(contexts)} 条标题应匹配 {'/'.join(terms)}")
    for terms in _expected_groups(expected.get("top_n_must_not_match_titles")):
        if _any_context_matches(top_contexts, terms, scope="title"):
            errors.append(f"前 {top_n or len(contexts)} 条标题不应匹配 {'/'.join(terms)}")
    for terms in _expected_groups(expected.get("must_match_contexts")):
        if not _any_context_matches(contexts, terms, scope="full"):
            errors.append(f"内容应匹配 {'/'.join(terms)}")
    for terms in _expected_groups(expected.get("must_not_match_contexts")):
        if _any_context_matches(contexts, terms, scope="full"):
            errors.append(f"内容不应匹配 {'/'.join(terms)}")
    for term in expected.get("must_include_terms") or []:
        if _normalize_text(term) not in normalized_text:
            errors.append(f"内容应包含 {term}")
    for term in expected.get("must_not_include_terms") or []:
        if _normalize_text(term) in normalized_text:
            errors.append(f"内容不应包含 {term}")
    if "max_contexts" in expected and len(contexts) > int(expected.get("max_contexts") or 0):
        errors.append(f"命中片段数应不超过 {expected.get('max_contexts')}，实际 {len(contexts)}")

    profile_expected = expected.get("query_profile") or {}
    profile = meta.get("query_profile") or {}
    for key, value in profile_expected.items():
        if profile.get(key) != value:
            errors.append(f"query_profile.{key} 应为 {value!r}，实际 {profile.get(key)!r}")
    positive_required = expected.get("must_have_positive_signals") or []
    if positive_required:
        signals: list[str] = []
        for context in contexts:
            ranking = context.get("intent_ranking") or {}
            signals.extend(str(item) for item in ranking.get("positive_signals") or [])
        for signal in positive_required:
            if str(signal) not in signals:
                errors.append(f"缺少正向信号 {signal}")
    return errors


def _summarize_case(case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected") or {}
    return {
        "id": case.get("id"),
        "category": case.get("category") or "未分类",
        "question": case.get("question") or "",
        "why": case.get("why") or "",
        "top_k": case.get("top_k") or 8,
        "expected_summary": {
            "backend": expected.get("backend") or "",
            "top_n": expected.get("top_n") or None,
            "must_match_titles": expected.get("must_match_titles") or expected.get("top_n_must_match_titles") or [],
            "must_not_match_titles": expected.get("must_not_match_titles") or expected.get("top_n_must_not_match_titles") or [],
            "must_include_terms": expected.get("must_include_terms") or [],
        },
    }


def _feedback_stats(db: Session, since: datetime) -> dict[str, Any]:
    rows = db.execute(select(Feedback).where(Feedback.created_at >= since)).scalars().all()
    by_status: dict[str, int] = {}
    by_root_cause: dict[str, int] = {}
    for row in rows:
        status = str(row.status or "new")
        root = str(getattr(row, "root_cause", "") or "unclassified")
        by_status[status] = by_status.get(status, 0) + 1
        by_root_cause[root] = by_root_cause.get(root, 0) + 1
    return {
        "total": len(rows),
        "new": by_status.get("new", 0),
        "resolved": by_status.get("resolved", 0),
        "by_status": by_status,
        "by_root_cause": by_root_cause,
    }


def _document_stats(db: Session) -> dict[str, Any]:
    total = db.scalar(select(func.count(Document.id))) or 0
    status_rows = db.execute(select(DocumentProcessingStatus.status, func.count(DocumentProcessingStatus.document_id)).group_by(DocumentProcessingStatus.status)).all()
    by_status = {str(status or "unknown"): int(count or 0) for status, count in status_rows}
    searchable = db.scalar(select(func.count(DocumentProcessingStatus.document_id)).where(DocumentProcessingStatus.searchable == True)) or 0  # noqa: E712
    return {
        "total": int(total),
        "searchable": int(searchable),
        "ready": by_status.get("ready", 0),
        "processing": by_status.get("processing", 0) + by_status.get("pending", 0),
        "failed": by_status.get("failed", 0),
        "by_status": by_status,
    }


@router.get("/api/admin/evaluation/overview")
def evaluation_overview(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db), _: User = Depends(require_admin)):
    since = datetime.utcnow() - timedelta(days=days)
    cases = _load_real_eval_cases()
    feedback = _feedback_stats(db, since)
    documents = _document_stats(db)
    risk_signals: list[str] = []
    if feedback["new"]:
        risk_signals.append(f"还有 {feedback['new']} 条新反馈待处理")
    if documents["failed"]:
        risk_signals.append(f"有 {documents['failed']} 份文档解析失败，可能影响检索")
    if documents["total"] and not documents["searchable"]:
        risk_signals.append("当前没有可检索文档")
    if not cases:
        risk_signals.append("尚未配置真实检索评测用例")
    return {
        "ok": True,
        "days": days,
        "case_count": len(cases),
        "feedback": feedback,
        "documents": documents,
        "risk_signals": risk_signals,
        "cases": [_summarize_case(case) for case in cases],
        "automation_note": "评测面板不会盲目相信自动生成问题；优先使用人工维护用例和用户反馈沉淀的问题。",
    }


@router.post("/api/admin/evaluation/run-case")
def run_evaluation_case(req: ChatRequest, db: Session = Depends(get_db), user: User = Depends(require_admin)):
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入评测问题")
    top_k = max(1, min(int(req.top_k or 8), 20))
    contexts, retrieval_backend, retrieval_note, candidate_count, retrieval_meta = adaptive_retrieve_contexts(db, question, user, top_k)
    sources = serialize_sources(contexts)
    source_quality_notice = build_source_quality_notice(sources)
    answer_contexts = model_contexts_for_answer(contexts, False)
    retrieval_meta["answer_context_count"] = len(answer_contexts)
    retrieval_meta["answer_context_filtered_count"] = max(0, len(contexts) - len(answer_contexts))
    confidence = compute_grounding_confidence(answer_contexts)
    retrieval_debug_summary = build_retrieval_debug_summary(answer_contexts, candidate_count, confidence, source_quality_notice)
    source_diagnostics = []
    for index, context in enumerate(contexts, start=1):
        content = " ".join(str(context.get("content") or "").split())
        source_diagnostics.append({
            "rank": index,
            "document_id": context.get("document_id") or "",
            "document_title": context.get("document_title") or context.get("filename") or "未知文档",
            "filename": context.get("filename") or "",
            "page_number": context.get("page_number"),
            "chunk_id": context.get("chunk_id") or "",
            "chunk_index": context.get("chunk_index"),
            "score": context.get("score"),
            "rerank_score": context.get("rerank_score"),
            "retrieval_channel": context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"),
            "location": context.get("location") or "",
            "preview": content[:1000],
        })
    return {
        "question": question,
        "retrieval_backend": retrieval_backend,
        "retrieval_note": retrieval_note,
        "candidate_count": candidate_count,
        "confidence": confidence,
        "source_count": len(sources),
        "sources": sources,
        "source_diagnostics": source_diagnostics,
        "retrieval_debug_summary": retrieval_debug_summary,
        "source_quality_notice": source_quality_notice,
        "source_warning": source_quality_notice.get("warning") or "",
        "query_analysis": retrieval_meta.get("query_analysis") or {},
        "retrieval_route": retrieval_meta.get("retrieval_route") or {},
        "evidence_check": retrieval_meta.get("evidence_check") or {},
        "retrieval_meta": retrieval_meta,
        "prompt_context_preview": {
            "text": "\n\n".join(item["preview"] for item in source_diagnostics[:5]),
            "source_count": len(contexts),
        },
    }


@router.post("/api/admin/evaluation/run-suite")
def run_evaluation_suite(limit: int = Query(20, ge=1, le=100), db: Session = Depends(get_db), user: User = Depends(require_admin)):
    cases = _load_real_eval_cases()[: bounded_limit(limit, 20, 100)]
    results: list[dict[str, Any]] = []
    failures = 0
    for case in cases:
        question = str(case.get("question") or "").strip()
        if not question:
            continue
        top_k = int(case.get("top_k") or 8)
        contexts, backend, note, candidate_count, meta = adaptive_retrieve_contexts(db, question, user, top_k)
        errors = _validate_case(case, contexts, backend, meta)
        ok = not errors
        failures += 0 if ok else 1
        confidence = compute_grounding_confidence(contexts)
        results.append({
            "id": case.get("id"),
            "category": case.get("category") or "未分类",
            "question": question,
            "ok": ok,
            "errors": errors,
            "retrieval_backend": backend,
            "retrieval_note": note,
            "candidate_count": candidate_count,
            "confidence": confidence,
            "ranked_doc_ids": [str(context.get("document_id") or "") for context in contexts],
            "top_contexts": [
                {
                    "rank": index + 1,
                    "document_id": context.get("document_id") or "",
                    "title": context.get("document_title") or context.get("filename") or "未知文档",
                    "channel": context.get("retrieval_channel") or ("pageindex" if context.get("pageindex_source") else "semantic"),
                    "score": context.get("score"),
                    "rerank_score": context.get("rerank_score"),
                    "snippet": " ".join(str(context.get("content") or "").split())[:220],
                }
                for index, context in enumerate(contexts[:5])
            ],
        })
    total = len(results)
    return {
        "ok": failures == 0,
        "total": total,
        "passed": total - failures,
        "failed": failures,
        "pass_rate": (total - failures) / total if total else 0,
        "results": results,
    }
