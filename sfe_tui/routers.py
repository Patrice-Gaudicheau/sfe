"""Provider-free segment routing previews for the SFE-aware TUI."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .contracts import ContextSegment


LOCAL_LEXICAL_PREVIEW_MODE = "local_lexical_preview"
NO_MATCHING_CONTEXT_TERMS = "no_matching_context_terms"
NO_REDUCIBLE_CONTEXT_SEGMENTS = "no_reducible_context_segments"
MAX_LOCAL_ROUTER_SEGMENTS = 3

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "based",
    "but",
    "can",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "not",
    "only",
    "read",
    "should",
    "that",
    "the",
    "this",
    "use",
    "what",
    "when",
    "where",
    "why",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class RouterSelectionResult:
    router_mode: str
    router_available: bool
    provider_calls_made: int
    input_segment_count: int
    eligible_segment_count: int
    selected_segment_ids: list[str]
    selected_segment_count: int
    estimated_input_tokens: int
    estimated_selected_tokens: int
    estimated_reduction_pct: float | None
    fallback_reason: str | None
    score_category_counts: dict[str, int]
    score_categories_by_segment_id: dict[str, str]
    router_input_segment_ids: list[str]


class LocalSegmentRouter:
    """A deterministic lexical router for explicit reducible context segments."""

    mode = LOCAL_LEXICAL_PREVIEW_MODE

    def route(
        self,
        task: str,
        context_segments: list[ContextSegment],
    ) -> RouterSelectionResult:
        eligible = [
            segment
            for segment in context_segments
            if segment.reducible and bool(segment.text)
        ]
        task_terms = _tokenize(task)
        scored: list[tuple[int, int, ContextSegment]] = []
        score_category_counts = {"high": 0, "medium": 0, "low": 0, "zero": 0}
        score_categories_by_segment_id: dict[str, str] = {}
        for index, segment in enumerate(eligible):
            segment_terms = _tokenize(segment.text)
            segment_terms.update(_tokenize(segment.source_ref))
            score = len(task_terms.intersection(segment_terms))
            score_category = _score_category(score)
            score_category_counts[score_category] += 1
            score_categories_by_segment_id[segment.id] = score_category
            scored.append((score, index, segment))

        selected = [
            segment
            for score, _index, segment in sorted(
                scored,
                key=lambda item: (-item[0], item[1]),
            )
            if score > 0
        ][:MAX_LOCAL_ROUTER_SEGMENTS]
        input_tokens = sum(segment.approx_tokens for segment in context_segments)
        selected_tokens = sum(segment.approx_tokens for segment in selected)
        fallback_reason = _fallback_reason(eligible=eligible, selected=selected)
        return RouterSelectionResult(
            router_mode=self.mode,
            router_available=True,
            provider_calls_made=0,
            input_segment_count=len(context_segments),
            eligible_segment_count=len(eligible),
            selected_segment_ids=[segment.id for segment in selected],
            selected_segment_count=len(selected),
            estimated_input_tokens=input_tokens,
            estimated_selected_tokens=selected_tokens,
            estimated_reduction_pct=_estimated_reduction_pct(
                input_tokens,
                selected_tokens,
            ),
            fallback_reason=fallback_reason,
            score_category_counts=score_category_counts,
            score_categories_by_segment_id=score_categories_by_segment_id,
            router_input_segment_ids=[segment.id for segment in eligible],
        )


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in (match.group(0).lower() for match in _TOKEN_RE.finditer(text))
        if len(token) >= 3 and token not in _STOP_WORDS
    }


def _score_category(score: int) -> str:
    if score <= 0:
        return "zero"
    if score == 1:
        return "low"
    if score <= 4:
        return "medium"
    return "high"


def _fallback_reason(
    *,
    eligible: list[ContextSegment],
    selected: list[ContextSegment],
) -> str | None:
    if selected:
        return None
    if not eligible:
        return NO_REDUCIBLE_CONTEXT_SEGMENTS
    return NO_MATCHING_CONTEXT_TERMS


def _estimated_reduction_pct(
    input_tokens: int,
    selected_tokens: int,
) -> float | None:
    if input_tokens <= 0:
        return None
    return round((1 - (selected_tokens / input_tokens)) * 100, 2)
