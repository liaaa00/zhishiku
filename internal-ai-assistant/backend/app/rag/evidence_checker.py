from __future__ import annotations

from .schemas import EvidenceCheck, QueryAnalysis, RetrievalRoute


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
