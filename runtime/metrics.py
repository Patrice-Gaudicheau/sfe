"""Shared metric helpers for benchmark and reporting scripts.

These helpers intentionally use a deterministic approximation instead of a
provider tokenizer. When a provider reports token usage, benchmark scripts
should prefer the provider values. When usage is missing, use the shared
chars/4 estimate below so approximate metrics remain comparable across reports.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


APPROX_CHARS_PER_TOKEN = 4


def estimate_text_tokens(text: str) -> int:
    """Return a rough deterministic token estimate for text.

    This is not a tokenizer. It is a stable chars/4 heuristic used only when
    exact provider token usage is unavailable.
    """

    if not text:
        return 0
    return max(1, int(len(text) / APPROX_CHARS_PER_TOKEN))


def estimate_char_count_tokens(size_chars: int) -> int:
    """Return the same chars/4 estimate when only a character count is known."""

    if size_chars <= 0:
        return 0
    return max(1, int(size_chars / APPROX_CHARS_PER_TOKEN))


def estimated_token_usage(prompt: str, response_text: str) -> dict[str, int]:
    """Return estimated input, output, and total token counts."""

    input_tokens = estimate_text_tokens(prompt)
    output_tokens = estimate_text_tokens(response_text)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


def average(values: Iterable[float | int]) -> float:
    numbers = [float(value) for value in values]
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def percentage(value: float, total: float) -> float:
    if total == 0:
        return 0.0
    return value / total * 100


def percent_reduction(baseline: float, reduced: float) -> float | None:
    if baseline <= 0:
        return None
    return ((baseline - reduced) / baseline) * 100


def success_rate(runs: list[dict[str, Any]]) -> float:
    if not runs:
        return 0.0
    return sum(1 for run in runs if bool(run.get("success"))) / len(runs)


def write_json_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
