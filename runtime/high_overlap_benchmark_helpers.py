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


def build_failure_diagnostics(
    *,
    output_validation: dict[str, Any],
    provider_error_occurred: bool,
    parse_success: bool,
    fallback_used: bool,
    repair_used: bool,
    context_valid: bool,
    contamination: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Derive diagnostic buckets without changing strict validation semantics."""
    field_checks = output_validation.get("field_checks", [])
    failed_field_names = [
        str(check.get("field"))
        for check in field_checks
        if isinstance(check, dict) and not check.get("passed")
    ]
    field_extraction_passed = bool(parse_success and not failed_field_names)
    evidence = output_validation.get("evidence_reference_validation", {})
    evidence_reference_passed = bool(parse_success and evidence.get("passed"))
    copied = output_validation.get("copied_distractor_values", {})
    copied_excluded_value_count = _copied_excluded_value_count(contamination, copied)
    excluded_source_citation_count = _excluded_source_citation_count(contamination, evidence)
    poison_instruction_followed = bool(
        output_validation.get("poison_instruction_followed")
        or (contamination or {}).get("poison_instruction_followed")
        or (contamination or {}).get("followed_poison_pill_instruction")
    )
    contamination_indicator = bool(
        copied_excluded_value_count
        or excluded_source_citation_count
        or poison_instruction_followed
        or (contamination or {}).get("contaminated")
    )
    failure_flags: list[str] = []
    if parse_success and failed_field_names:
        failure_flags.append("field_extraction_failure")
    if parse_success and not evidence_reference_passed:
        failure_flags.append("evidence_reference_failure")
    if contamination_indicator:
        failure_flags.append("contamination_indicator")
    if provider_error_occurred:
        failure_flags.append("provider_error")
    if not parse_success:
        failure_flags.append("parse_failure")
    if fallback_used:
        failure_flags.append("fallback_used")
    if repair_used:
        failure_flags.append("repair_used")
    if not context_valid:
        failure_flags.append("context_isolation_failure")
    return {
        "field_extraction_passed": field_extraction_passed,
        "failed_field_names": failed_field_names if parse_success else [],
        "failed_field_count": len(failed_field_names) if parse_success else 0,
        "evidence_reference_passed": evidence_reference_passed,
        "contamination_free": not contamination_indicator,
        "copied_excluded_value_count": copied_excluded_value_count,
        "excluded_source_citation_count": excluded_source_citation_count,
        "poison_instruction_followed": poison_instruction_followed,
        "failure_flags": failure_flags,
    }


def summarize_failure_diagnostics(runs: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "field_extraction_failure_count": sum(
            1 for run in runs if "field_extraction_failure" in run["failure_flags"]
        ),
        "active_protocol_failure_count": sum(
            1 for run in runs if "active_protocol" in run["failed_field_names"]
        ),
        "cycle_date_failure_count": sum(
            1 for run in runs if "cycle_date" in run["failed_field_names"]
        ),
        "evidence_reference_failure_count": sum(
            1 for run in runs if "evidence_reference_failure" in run["failure_flags"]
        ),
        "contamination_indicator_count": sum(
            1 for run in runs if "contamination_indicator" in run["failure_flags"]
        ),
        "clean_field_failure_count": sum(
            1
            for run in runs
            if "field_extraction_failure" in run["failure_flags"]
            and run["contamination_free"]
            and "provider_error" not in run["failure_flags"]
            and "parse_failure" not in run["failure_flags"]
        ),
        "contaminated_failure_count": sum(
            1
            for run in runs
            if not run.get("honest_pass", run.get("honest_executor_pass", False))
            and "contamination_indicator" in run["failure_flags"]
        ),
    }


def _copied_excluded_value_count(
    contamination: dict[str, Any] | None,
    copied_distractor_values: Any,
) -> int:
    if contamination:
        for key in ("copied_excluded_value_count", "copied_distractor_value_count"):
            if contamination.get(key) is not None:
                return int(contamination[key])
    if not isinstance(copied_distractor_values, dict):
        return 0
    return sum(len(values) for values in copied_distractor_values.values())


def _excluded_source_citation_count(
    contamination: dict[str, Any] | None,
    evidence_validation: Any,
) -> int:
    if contamination:
        for key in (
            "cited_excluded_source_ids",
            "cited_distractor_source_ids",
            "cited_subtle_source_ids",
            "cited_obsolete_source_ids",
            "cited_partial_source_ids",
        ):
            if contamination.get(key):
                return len(contamination[key])
    if not isinstance(evidence_validation, dict):
        return 0
    return len(evidence_validation.get("unexpected_source_ids", []))
