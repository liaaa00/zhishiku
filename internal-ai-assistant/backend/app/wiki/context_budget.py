from __future__ import annotations

import copy
from typing import Any

APPROX_CHARS_PER_TOKEN = 4
DEFAULT_WIKI_CONTEXT_BUDGET_TOKENS = 2400
TRUNCATION_SUFFIX = "..."
TRIM_ORDER = ["source_quotes", "content", "contexts"]


def estimate_tokens(value: Any) -> int:
    if value is None:
        return 0
    text = value if isinstance(value, str) else str(value)
    if not text:
        return 0
    return max(1, (len(text) + APPROX_CHARS_PER_TOKEN - 1) // APPROX_CHARS_PER_TOKEN)


def estimate_context_tokens(contexts: list[dict[str, Any]]) -> int:
    return estimate_tokens(contexts)


def apply_context_budget(
    contexts: list[dict[str, Any]],
    *,
    requested_tokens: int = DEFAULT_WIKI_CONTEXT_BUDGET_TOKENS,
    min_content_chars: int = 900,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Deterministically trim Wiki contexts to a pack-level token budget.

    Ported from the reference projects' context-pack budgeting idea, but adapted
    to our flat RAG context list. Trimming order is intentionally conservative:
    drop auxiliary quotes first, then shorten lower-ranked content, and only drop
    whole contexts as a last resort. Input contexts are never mutated.
    """

    packed = copy.deepcopy(contexts)
    before_tokens = estimate_context_tokens(packed)
    trimmed: set[str] = set()
    if before_tokens <= requested_tokens:
        return packed, {
            "requested_tokens": requested_tokens,
            "estimated_tokens_before": before_tokens,
            "estimated_tokens_after": before_tokens,
            "truncated": False,
            "trimmed_sections": [],
        }

    _trim_source_quotes(packed, requested_tokens, trimmed)
    _trim_content(packed, requested_tokens, min_content_chars, trimmed)
    _trim_contexts(packed, requested_tokens, trimmed)
    after_tokens = estimate_context_tokens(packed)
    return packed, {
        "requested_tokens": requested_tokens,
        "estimated_tokens_before": before_tokens,
        "estimated_tokens_after": after_tokens,
        "truncated": after_tokens < before_tokens,
        "trimmed_sections": [section for section in TRIM_ORDER if section in trimmed],
    }


def _fits(contexts: list[dict[str, Any]], budget: int) -> bool:
    return estimate_context_tokens(contexts) <= budget


def _trim_source_quotes(contexts: list[dict[str, Any]], budget: int, trimmed: set[str]) -> None:
    for index in range(len(contexts) - 1, -1, -1):
        quotes = contexts[index].get("source_quotes")
        if not isinstance(quotes, list):
            continue
        while quotes and not _fits(contexts, budget):
            quotes.pop()
            trimmed.add("source_quotes")
        if _fits(contexts, budget):
            return


def _shorten_content_once(content: str, min_content_chars: int) -> str | None:
    suffix_len = len(TRUNCATION_SUFFIX)
    min_body_chars = max(0, min_content_chars - suffix_len)
    scaled_body_chars = int(len(content) * 0.72)
    body_limit = max(min_body_chars, scaled_body_chars)
    body_limit = min(body_limit, max(0, len(content) - suffix_len - 1))
    if body_limit <= 0 or body_limit >= len(content):
        return None
    shortened = content[:body_limit].rstrip() + TRUNCATION_SUFFIX
    if len(shortened) >= len(content):
        return None
    return shortened


def _trim_content(contexts: list[dict[str, Any]], budget: int, min_content_chars: int, trimmed: set[str]) -> None:
    for index in range(len(contexts) - 1, -1, -1):
        if _fits(contexts, budget):
            return
        content = str(contexts[index].get("content") or "")
        while len(content) > min_content_chars and not _fits(contexts, budget):
            shortened = _shorten_content_once(content, min_content_chars)
            if not shortened:
                break
            content = shortened
            contexts[index]["content"] = content
            contexts[index]["wiki_context_char_count"] = len(content)
            trimmed.add("content")


def _trim_contexts(contexts: list[dict[str, Any]], budget: int, trimmed: set[str]) -> None:
    while len(contexts) > 1 and not _fits(contexts, budget):
        contexts.pop()
        trimmed.add("contexts")
