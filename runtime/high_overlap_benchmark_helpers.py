"""Mechanical helpers shared by high-overlap benchmark runners.

This module is intentionally limited to behavior-neutral response extraction,
aggregation, and report formatting helpers. Fixture content, prompts, selection
logic, and validators remain in the individual runners.
"""

from __future__ import annotations

import json
import os
from typing import Any


def extract_response_text(response: dict[str, Any]) -> str:
    choices = response.get("choices", [])
    if not isinstance(choices, list) or not choices:
        return ""
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        return ""
    message = first_choice.get("message", {})
    if isinstance(message, dict) and message.get("content") is not None:
        return str(message["content"]).strip()
    if first_choice.get("text") is not None:
        return str(first_choice["text"]).strip()
    return ""


def extract_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = optional_int(usage.get("prompt_tokens"))
    output_tokens = optional_int(usage.get("completion_tokens"))
    total_tokens = optional_int(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def extract_latency_ms(response: dict[str, Any]) -> int | None:
    metadata = response.get("openai_api")
    if isinstance(metadata, dict) and metadata.get("latency_ms") is not None:
        return int(metadata["latency_ms"])
    return None


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


def stringify_output_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value).strip()


def average(values: Any) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def rate(values: Any) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if bool(item)) / len(items)


def sum_usage(runs: list[dict[str, Any]], key: str) -> int | None:
    values = [run["usage"].get(key) for run in runs if run["usage"].get(key) is not None]
    if not values:
        return None
    return sum(int(value) for value in values)


def average_usage(runs: list[dict[str, Any]], key: str) -> float | None:
    return average(run["usage"].get(key) for run in runs)


def sum_latency(runs: list[dict[str, Any]]) -> int | None:
    values = [run["latency_ms"] for run in runs if run.get("latency_ms") is not None]
    if not values:
        return None
    return sum(int(value) for value in values)


def format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def format_optional_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def format_optional_int(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(int(value))
