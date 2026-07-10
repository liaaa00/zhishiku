from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

QueryIntent = Literal["text_qa", "table_query", "metadata_query", "summary_query", "unknown"]
RetrievalRouteName = Literal["wiki", "text", "table", "metadata", "summary", "fallback"]


@dataclass(slots=True)
class QueryAnalysis:
    """Structured result produced by the first-stage query analyzer."""

    query: str
    intent: QueryIntent
    confidence: float
    route_hint: RetrievalRouteName
    entities: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    time_filters: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalRoute:
    """Route selected for a query after analysis."""

    name: RetrievalRouteName
    intent: QueryIntent
    confidence: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RetrievalResult:
    """Normalized retriever output used by chat_api and admin search diagnostics."""

    contexts: list[dict[str, Any]]
    backend: str
    note: str
    candidate_count: int
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EvidenceCheck:
    """Lightweight evidence sufficiency check for first-stage routing."""

    sufficient: bool
    reason: str
    source_count: int
    document_count: int
    required_evidence: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    best_score: float = 0.0
    matched_term_count: int = 0
    source_quote_count: int = 0
    missing_terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
