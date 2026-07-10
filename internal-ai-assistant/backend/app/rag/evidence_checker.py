from __future__ import annotations

import re
from typing import Any

from .schemas import EvidenceCheck, QueryAnalysis, RetrievalRoute

WIKI_DIRECT_MIN_SCORE = 0.60
WIKI_DIRECT_MIN_MATCH_TERMS = 2


def _compact(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def check_wiki_evidence(contexts: list[dict], analysis: QueryAnalysis, wiki_meta: dict[str, Any]) -> EvidenceCheck:
    source_count = len(contexts or [])
    document_ids = {str(item.get("document_id") or "") for item in contexts or [] if item.get("document_id")}
    document_count = len(document_ids)
    best_score = float(wiki_meta.get("best_score") or 0.0)
    matched_terms = {
        _compact(term)
        for item in contexts or []
        for term in item.get("match_terms") or []
        if _compact(term)
    }
    source_quote_count = sum(len(item.get("source_quotes") or []) for item in contexts or [])
    required: list[str] = []
    warnings: list[str] = []
    missing_terms: list[str] = []

    if source_count <= 0:
        required.append("至少 1 个 Wiki 上下文")
        return EvidenceCheck(False, "wiki_no_contexts", source_count, document_count, required, warnings)

    if best_score < WIKI_DIRECT_MIN_SCORE:
        required.append(f"Wiki 最佳分数至少 {WIKI_DIRECT_MIN_SCORE:.2f}")
        warnings.append("中等强度 Wiki 命中需要混合检索复核")
        return EvidenceCheck(
            False,
            "wiki_score_below_direct_threshold",
            source_count,
            document_count,
            required,
            warnings,
            best_score=best_score,
            matched_term_count=len(matched_terms),
            source_quote_count=source_quote_count,
        )

    if len(matched_terms) < WIKI_DIRECT_MIN_MATCH_TERMS:
        required.append(f"至少 {WIKI_DIRECT_MIN_MATCH_TERMS} 个有效匹配词")
        return EvidenceCheck(
            False,
            "wiki_match_terms_too_weak",
            source_count,
            document_count,
            required,
            warnings,
            best_score=best_score,
            matched_term_count=len(matched_terms),
            source_quote_count=source_quote_count,
        )

    if source_quote_count <= 0 or not any(int(item.get("wiki_source_count") or 0) > 0 for item in contexts or []):
        required.append("至少 1 条可核验 Wiki 来源摘录")
        return EvidenceCheck(
            False,
            "wiki_sources_missing",
            source_count,
            document_count,
            required,
            warnings,
            best_score=best_score,
            matched_term_count=len(matched_terms),
            source_quote_count=source_quote_count,
        )

    strong_score = float(wiki_meta.get("threshold") or WIKI_DIRECT_MIN_SCORE)
    document_best_scores: dict[str, float] = {}
    for item in contexts or []:
        document_id = str(item.get("document_id") or "")
        if document_id:
            document_best_scores[document_id] = max(
                document_best_scores.get(document_id, 0.0),
                float(item.get("score") or 0.0),
            )
    if len(document_best_scores) > 1 and any(score < strong_score for score in document_best_scores.values()):
        required.append(f"每份 Wiki 文档的最佳分数至少 {strong_score:.2f}")
        warnings.append("Wiki 上下文混入弱相关文档，需要混合检索复核")
        return EvidenceCheck(
            False,
            "wiki_mixed_document_confidence",
            source_count,
            document_count,
            required,
            warnings,
            best_score=best_score,
            matched_term_count=len(matched_terms),
            source_quote_count=source_quote_count,
        )

    if document_count < 2 and any(term in analysis.query for term in ("对比", "比较", "多个", "多份", "跨文档")):
        required.append("多文档问题至少命中 2 份文档")
        return EvidenceCheck(
            False,
            "wiki_multi_document_evidence_missing",
            source_count,
            document_count,
            required,
            warnings,
            best_score=best_score,
            matched_term_count=len(matched_terms),
            source_quote_count=source_quote_count,
        )

    evidence_text = _compact(" ".join(
        str(value or "")
        for item in contexts or []
        for value in [item.get("content"), *(item.get("source_quotes") or [])]
    ))
    critical_terms = list(dict.fromkeys(re.findall(r"\d+(?:\.\d+)?%?", analysis.query or "")))
    missing_terms = [term for term in critical_terms if _compact(term) not in evidence_text]
    if missing_terms:
        required.append("问题中的数字、日期或比例必须出现在证据中")
        return EvidenceCheck(
            False,
            "wiki_critical_terms_missing",
            source_count,
            document_count,
            required,
            warnings,
            best_score=best_score,
            matched_term_count=len(matched_terms),
            source_quote_count=source_quote_count,
            missing_terms=missing_terms,
        )

    return EvidenceCheck(
        True,
        "wiki_evidence_sufficient",
        source_count,
        document_count,
        required,
        warnings,
        best_score=best_score,
        matched_term_count=len(matched_terms),
        source_quote_count=source_quote_count,
    )


def check_evidence(contexts: list[dict], analysis: QueryAnalysis, route: RetrievalRoute) -> EvidenceCheck:
    source_count = len(contexts or [])
    document_ids = {str(item.get("document_id") or "") for item in contexts or [] if item.get("document_id")}
    document_count = len(document_ids)
    warnings: list[str] = []
    required: list[str] = []

    if route.name == "table":
        data_rows = [item for item in contexts or [] if not item.get("is_header")]
        if not data_rows:
            required.append("至少 1 行匹配的表格数据")
            return EvidenceCheck(False, "table_route_no_data_rows", source_count, document_count, required, warnings)
        if not any(item.get("sheet_name") for item in data_rows):
            warnings.append("表格结果缺少 sheet 信息")
        return EvidenceCheck(True, "table_rows_found", source_count, document_count, required, warnings)

    if route.name == "metadata":
        if source_count <= 0:
            required.append("至少 1 个匹配文档或元数据记录")
            return EvidenceCheck(False, "metadata_route_no_sources", source_count, document_count, required, warnings)
        return EvidenceCheck(True, "metadata_sources_found", source_count, document_count, required, warnings)

    if route.name == "summary":
        if source_count <= 0:
            required.append("当前用户可访问文档清单")
            return EvidenceCheck(False, "summary_route_no_accessible_documents", source_count, document_count, required, warnings)
        return EvidenceCheck(True, "summary_sources_found", source_count, document_count, required, warnings)

    if source_count <= 0:
        required.append("至少 1 个知识库片段")
        return EvidenceCheck(False, "text_route_no_contexts", source_count, document_count, required, warnings)
    if document_count == 1 and any(term in analysis.query for term in ("对比", "比较", "多个", "多份", "跨文档")):
        warnings.append("问题像多文档问题，但当前只命中 1 个文档")
    return EvidenceCheck(True, "text_contexts_found", source_count, document_count, required, warnings)
