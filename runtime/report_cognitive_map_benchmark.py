"""Generate a Markdown report for Cognitive Map real benchmark JSONL results."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT_PATH = PROJECT_ROOT / "logs" / "cognitive_map_real_benchmark.jsonl"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "logs" / "cognitive_map_benchmark_report.md"


def main() -> None:
    args = _parse_args()
    rows = read_jsonl(args.input)
    report = render_report(
        rows=rows,
        input_path=args.input,
        generated_at=_timestamp(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"wrote_report: {args.output}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT_PATH,
        help="Path to Cognitive Map real benchmark JSONL results.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for the generated Markdown report.",
    )
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected JSON object on line {line_number}.")
            rows.append(row)
    return rows


def aggregate_by_mode(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for mode in sorted({_comparison_mode(row) for row in rows}):
        mode_rows = [row for row in rows if _comparison_mode(row) == mode]
        prompt_tokens = _numeric_values(mode_rows, "provider_reported_prompt_tokens")
        completion_tokens = _numeric_values(
            mode_rows, "provider_reported_completion_tokens"
        )
        total_tokens = _numeric_values(mode_rows, "provider_reported_total_tokens")
        latencies = _numeric_values(mode_rows, "latency_ms", missing_as_zero=True)
        zone_builder_tokens = _numeric_values(
            mode_rows, "zone_builder_total_tokens", missing_as_zero=True
        )
        zone_builder_latencies = _numeric_values(
            mode_rows, "zone_builder_latency_ms", missing_as_zero=True
        )
        combined_prompt_tokens = _combined_numeric_values(
            mode_rows,
            "combined_prompt_tokens",
            "provider_reported_prompt_tokens",
            "zone_builder_prompt_tokens",
        )
        combined_completion_tokens = _combined_numeric_values(
            mode_rows,
            "combined_completion_tokens",
            "provider_reported_completion_tokens",
            "zone_builder_completion_tokens",
        )
        combined_total_tokens = _combined_numeric_values(
            mode_rows,
            "combined_total_tokens",
            "provider_reported_total_tokens",
            "zone_builder_total_tokens",
        )
        combined_latencies = _combined_numeric_values(
            mode_rows,
            "combined_latency_ms",
            "latency_ms",
            "zone_builder_latency_ms",
            missing_as_zero=True,
        )
        builder_rows = [
            row
            for row in mode_rows
            if str(row.get("zone_builder_mode", "not_applicable")) != "not_applicable"
        ]
        fallback_count = sum(
            1 for row in builder_rows if bool(row.get("zone_builder_fallback_used"))
        )
        summary[mode] = {
            "runs": len(mode_rows),
            "success_count": sum(1 for row in mode_rows if bool(row.get("success"))),
            "failure_count": sum(1 for row in mode_rows if not bool(row.get("success"))),
            "verification_passed_count": sum(
                1 for row in mode_rows if row.get("verification_passed") is True
            ),
            "verification_failed_count": sum(
                1 for row in mode_rows if row.get("verification_passed") is False
            ),
            "verification_unavailable_count": sum(
                1 for row in mode_rows if row.get("verification_passed") is None
            ),
            "prompt_token_sum": sum(prompt_tokens),
            "completion_token_sum": sum(completion_tokens),
            "total_token_sum": sum(total_tokens),
            "mean_total_tokens": _mean(total_tokens),
            "latency_ms_sum": sum(latencies),
            "mean_latency_ms": _mean(latencies),
            "min_latency_ms": min(latencies) if latencies else 0,
            "max_latency_ms": max(latencies) if latencies else 0,
            "zone_builder_runs": len(builder_rows),
            "zone_builder_success_count": sum(
                1 for row in builder_rows if row.get("zone_builder_success") is True
            ),
            "zone_builder_fallback_count": fallback_count,
            "zone_builder_fallback_rate_pct": (
                (fallback_count / len(builder_rows)) * 100 if builder_rows else 0.0
            ),
            "zone_builder_total_token_sum": sum(zone_builder_tokens),
            "zone_builder_mean_total_tokens": _mean(zone_builder_tokens),
            "zone_builder_latency_ms_sum": sum(zone_builder_latencies),
            "zone_builder_mean_latency_ms": _mean(zone_builder_latencies),
            "combined_prompt_token_sum": sum(combined_prompt_tokens),
            "combined_completion_token_sum": sum(combined_completion_tokens),
            "combined_total_token_sum": sum(combined_total_tokens),
            "combined_mean_total_tokens": _mean(combined_total_tokens),
            "combined_latency_ms_sum": sum(combined_latencies),
            "combined_mean_latency_ms": _mean(combined_latencies),
            "reflection_triggered_count": sum(
                1 for row in mode_rows if bool(row.get("reflection_triggered"))
            ),
            "reflection_attempts_used": sum(
                _numeric_values(mode_rows, "reflection_attempts_used")
            ),
        }
    return summary


def comparative_ratios(
    summary: dict[str, dict[str, float | int]]
) -> dict[str, float | None]:
    explicit = summary.get("explicit_metadata")
    cognitive = (
        summary.get("cognitive_map")
        or summary.get("cognitive_map_deterministic")
        or summary.get("cognitive_map_llm_intent")
    )
    if explicit is None or cognitive is None:
        return {}

    return {
        "total_token_reduction_pct": _reduction_pct(
            explicit["total_token_sum"], cognitive["total_token_sum"]
        ),
        "prompt_token_reduction_pct": _reduction_pct(
            explicit["prompt_token_sum"], cognitive["prompt_token_sum"]
        ),
        "completion_token_reduction_pct": _reduction_pct(
            explicit["completion_token_sum"], cognitive["completion_token_sum"]
        ),
        "latency_reduction_pct": _reduction_pct(
            explicit["latency_ms_sum"], cognitive["latency_ms_sum"]
        ),
        "mean_token_difference": float(explicit["mean_total_tokens"])
        - float(cognitive["mean_total_tokens"]),
        "mean_latency_difference_ms": float(explicit["mean_latency_ms"])
        - float(cognitive["mean_latency_ms"]),
    }


def combined_comparative_ratios(
    summary: dict[str, dict[str, float | int]]
) -> dict[str, dict[str, float | None]]:
    explicit = summary.get("explicit_metadata")
    if explicit is None:
        return {}

    ratios = {}
    for mode in sorted(summary):
        if not mode.startswith("cognitive_map"):
            continue
        cognitive = summary[mode]
        ratios[mode] = {
            "combined_total_token_reduction_pct": _reduction_pct(
                explicit["combined_total_token_sum"],
                cognitive["combined_total_token_sum"],
            ),
            "combined_prompt_token_reduction_pct": _reduction_pct(
                explicit["combined_prompt_token_sum"],
                cognitive["combined_prompt_token_sum"],
            ),
            "combined_completion_token_reduction_pct": _reduction_pct(
                explicit["combined_completion_token_sum"],
                cognitive["combined_completion_token_sum"],
            ),
            "combined_latency_reduction_pct": _reduction_pct(
                explicit["combined_latency_ms_sum"],
                cognitive["combined_latency_ms_sum"],
            ),
            "combined_mean_token_difference": float(
                explicit["combined_mean_total_tokens"]
            )
            - float(cognitive["combined_mean_total_tokens"]),
            "combined_mean_latency_difference_ms": float(
                explicit["combined_mean_latency_ms"]
            )
            - float(cognitive["combined_mean_latency_ms"]),
        }
    return ratios


def combined_comparison_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compare Cognitive Map variants against explicit_metadata using combined metrics."""

    explicit_rows = [
        row for row in rows if _comparison_mode(row) == "explicit_metadata"
    ]
    if not explicit_rows:
        return []

    explicit_tokens = _strict_combined_sum(
        explicit_rows,
        combined_key="combined_total_tokens",
        executor_key="provider_reported_total_tokens",
        zone_builder_key="zone_builder_total_tokens",
    )
    explicit_latency = _strict_combined_sum(
        explicit_rows,
        combined_key="combined_latency_ms",
        executor_key="latency_ms",
        zone_builder_key="zone_builder_latency_ms",
    )

    comparison_rows = []
    for mode in sorted({_comparison_mode(row) for row in rows}):
        if not mode.startswith("cognitive_map"):
            continue
        mode_rows = [row for row in rows if _comparison_mode(row) == mode]
        variant_tokens = _strict_combined_sum(
            mode_rows,
            combined_key="combined_total_tokens",
            executor_key="provider_reported_total_tokens",
            zone_builder_key="zone_builder_total_tokens",
        )
        variant_latency = _strict_combined_sum(
            mode_rows,
            combined_key="combined_latency_ms",
            executor_key="latency_ms",
            zone_builder_key="zone_builder_latency_ms",
        )
        comparison_rows.append(
            {
                "variant": mode,
                "combined_tokens": variant_tokens,
                "token_delta": _delta(variant_tokens, explicit_tokens),
                "token_change_pct": _percentage_change(
                    variant_tokens, explicit_tokens
                ),
                "combined_latency_ms": variant_latency,
                "latency_delta_ms": _delta(variant_latency, explicit_latency),
                "latency_change_pct": _percentage_change(
                    variant_latency, explicit_latency
                ),
            }
        )
    return comparison_rows


def metric_availability(rows: list[dict[str, Any]]) -> dict[str, int | bool]:
    token_fields = (
        "provider_reported_prompt_tokens",
        "provider_reported_completion_tokens",
        "provider_reported_total_tokens",
    )
    rows_with_any_token_field = sum(
        1
        for row in rows
        if any(row.get(field) is not None for field in token_fields)
    )
    rows_with_nonzero_tokens = sum(
        1
        for row in rows
        if any(_positive_number(row.get(field)) for field in token_fields)
    )
    rows_with_nonzero_latency = sum(
        1 for row in rows if _positive_number(row.get("latency_ms"))
    )
    dry_run_rows = sum(1 for row in rows if row.get("dry_run") is True)
    return {
        "total_rows": len(rows),
        "dry_run_rows": dry_run_rows,
        "rows_with_any_token_field": rows_with_any_token_field,
        "rows_with_nonzero_tokens": rows_with_nonzero_tokens,
        "rows_with_nonzero_latency": rows_with_nonzero_latency,
        "appears_token_free": rows_with_nonzero_tokens == 0,
        "appears_dry_run_or_token_free": (
            dry_run_rows == len(rows) if rows else False
        )
        or rows_with_nonzero_tokens == 0
        or rows_with_nonzero_latency == 0,
    }


def task_level_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    task_rows = []
    task_labels = sorted({str(row.get("task_label", "unknown")) for row in rows})
    for task_label in task_labels:
        for mode in sorted(
            {
                _comparison_mode(row)
                for row in rows
                if str(row.get("task_label", "unknown")) == task_label
            }
        ):
            matching = [
                row
                for row in rows
                if str(row.get("task_label", "unknown")) == task_label
                and _comparison_mode(row) == mode
            ]
            task_rows.append(
                {
                    "task_label": task_label,
                    "mode": mode,
                    "total_tokens": sum(
                        _numeric_values(matching, "provider_reported_total_tokens")
                    ),
                    "latency_ms": sum(
                        _numeric_values(matching, "latency_ms", missing_as_zero=True)
                    ),
                    "success_count": sum(1 for row in matching if bool(row.get("success"))),
                    "failure_count": sum(
                        1 for row in matching if not bool(row.get("success"))
                    ),
                    "reflection_attempts": sum(
                        _numeric_values(matching, "reflection_attempts_used")
                    )
                    if mode.startswith("cognitive_map")
                    else 0,
                }
            )
    return task_rows


def reflection_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not any("reflection_triggered" in row for row in rows):
        return {"fields_present": False}

    cognitive_rows = [row for row in rows if row.get("mode") == "cognitive_map"]
    triggered_rows = [
        row for row in cognitive_rows if bool(row.get("reflection_triggered"))
    ]
    verification_rows = [
        row for row in cognitive_rows if row.get("verification_passed") is not None
    ]
    return {
        "fields_present": True,
        "cognitive_map_rows": len(cognitive_rows),
        "reflection_triggered_rows": len(triggered_rows),
        "triggered_labels": sorted(
            {str(row.get("task_label", "unknown")) for row in triggered_rows}
        ),
        "total_reflection_attempts_used": sum(
            _numeric_values(cognitive_rows, "reflection_attempts_used")
        ),
        "verification_passed_count": sum(
            1 for row in verification_rows if bool(row.get("verification_passed"))
        ),
        "verification_failed_count": sum(
            1 for row in verification_rows if row.get("verification_passed") is False
        ),
    }


def render_report(rows: list[dict[str, Any]], input_path: Path, generated_at: str) -> str:
    mode_summary = aggregate_by_mode(rows)
    ratios = comparative_ratios(mode_summary)
    combined_ratios = combined_comparative_ratios(mode_summary)
    combined_comparison = combined_comparison_summary(rows)
    availability = metric_availability(rows)
    reflection = reflection_summary(rows)
    modes = sorted(mode_summary)
    task_labels = sorted({str(row.get("task_label", "unknown")) for row in rows})
    repeat_values = sorted(
        {
            int(row["repeat_index"])
            for row in rows
            if row.get("repeat_index") is not None
        }
    )

    sections = [
        "# Cognitive Map Real Benchmark Report",
        "",
        "This is an exploratory benchmark report, not a scientific evaluation. "
        "Quality was not judged semantically unless separately inspected.",
        "",
        "## Metadata",
        "",
        f"- input file: `{input_path}`",
        f"- generated timestamp: `{generated_at}`",
        f"- total rows: {len(rows)}",
        f"- detected modes: {_comma_list(modes)}",
        f"- detected task labels: {_comma_list(task_labels)}",
        f"- repeat count: {len(repeat_values) if repeat_values else 'not detected'}",
        f"- dry-run rows: {availability['dry_run_rows']}",
        f"- rows with provider token fields: {availability['rows_with_any_token_field']}",
        f"- rows with non-zero provider tokens: {availability['rows_with_nonzero_tokens']}",
        f"- rows with non-zero latency: {availability['rows_with_nonzero_latency']}",
        "",
        "## Methodological Caveat",
        "",
        "The `cognitive_map_deterministic` mode has free deterministic Cognitive "
        "Map construction. The `cognitive_map_llm_intent` mode includes the "
        "measured cost of one model-populated zone: `user_intent_zone`. If a "
        "Lemonade-compatible router response omits token usage, builder token "
        "fields are recorded as `0`, which can undercount router cost while "
        "still preserving measured latency.",
        "",
        "## Aggregate Executor Summary by Mode",
        "",
        _render_aggregate_table(mode_summary),
        "",
        "## Aggregate Zone-Builder Summary by Mode",
        "",
        _render_zone_builder_table(mode_summary),
        "",
        "## Aggregate Combined Summary by Mode",
        "",
        _render_combined_table(mode_summary),
        "",
        "## Combined Comparison Versus Explicit Metadata",
        "",
        _render_combined_comparison_table(combined_comparison),
        "",
        "## Executor-Only Comparative Ratios",
        "",
        _render_comparative_ratios(ratios, availability),
        "",
        "## Combined Comparative Ratios",
        "",
        _render_combined_comparative_ratios(combined_ratios, availability),
        "",
        "## Task-Level Summary",
        "",
        _render_task_table(task_level_summary(rows)),
        "",
        "## Reflection Summary",
        "",
        _render_reflection_summary(reflection),
        "",
        "## Quality Caveats",
        "",
        "- Token and latency metrics do not prove answer quality.",
        "- Deterministic verification only checks narrow constraints.",
        "- Future LLM-as-a-judge or human evaluation is needed for semantic quality.",
        "",
        "## Interpretation",
        "",
        _interpret(mode_summary, availability),
        "",
    ]
    return "\n".join(sections)


def _render_aggregate_table(summary: dict[str, dict[str, float | int]]) -> str:
    lines = [
        "| mode | runs | provider success | failure | verif pass | verif fail | verif n/a | executor prompt tokens | executor completion tokens | executor total tokens | mean executor total tokens | executor latency sum ms | mean executor latency ms | min executor latency ms | max executor latency ms | reflections |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, metrics in summary.items():
        lines.append(
            f"| {mode} | {metrics['runs']} | {metrics['success_count']} | "
            f"{metrics['failure_count']} | {metrics['verification_passed_count']} | "
            f"{metrics['verification_failed_count']} | "
            f"{metrics['verification_unavailable_count']} | "
            f"{metrics['prompt_token_sum']} | "
            f"{metrics['completion_token_sum']} | {metrics['total_token_sum']} | "
            f"{_fmt_float(metrics['mean_total_tokens'])} | "
            f"{metrics['latency_ms_sum']} | {_fmt_float(metrics['mean_latency_ms'])} | "
            f"{metrics['min_latency_ms']} | {metrics['max_latency_ms']} | "
            f"{metrics['reflection_triggered_count']} |"
        )
    return "\n".join(lines)


def _render_zone_builder_table(summary: dict[str, dict[str, float | int]]) -> str:
    lines = [
        "| mode | runs | builder runs | builder success | fallback count | fallback rate | builder total tokens | mean builder tokens | builder latency sum ms | mean builder latency ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, metrics in summary.items():
        lines.append(
            f"| {mode} | {metrics['runs']} | "
            f"{metrics['zone_builder_runs']} | "
            f"{metrics['zone_builder_success_count']} | "
            f"{metrics['zone_builder_fallback_count']} | "
            f"{_fmt_pct(float(metrics['zone_builder_fallback_rate_pct']))} | "
            f"{metrics['zone_builder_total_token_sum']} | "
            f"{_fmt_float(metrics['zone_builder_mean_total_tokens'])} | "
            f"{metrics['zone_builder_latency_ms_sum']} | "
            f"{_fmt_float(metrics['zone_builder_mean_latency_ms'])} |"
        )
    return "\n".join(lines)


def _render_combined_table(summary: dict[str, dict[str, float | int]]) -> str:
    lines = [
        "| mode | runs | combined prompt tokens | combined completion tokens | combined total tokens | mean combined total tokens | combined latency sum ms | mean combined latency ms | verification pass | provider success | reflections |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode, metrics in summary.items():
        lines.append(
            f"| {mode} | {metrics['runs']} | "
            f"{metrics['combined_prompt_token_sum']} | "
            f"{metrics['combined_completion_token_sum']} | "
            f"{metrics['combined_total_token_sum']} | "
            f"{_fmt_float(metrics['combined_mean_total_tokens'])} | "
            f"{metrics['combined_latency_ms_sum']} | "
            f"{_fmt_float(metrics['combined_mean_latency_ms'])} | "
            f"{metrics['verification_passed_count']} | "
            f"{metrics['success_count']} | "
            f"{metrics['reflection_triggered_count']} |"
        )
    return "\n".join(lines)


def _render_combined_comparison_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return (
            "Combined comparison requires `explicit_metadata` and at least one "
            "Cognitive Map variant. Comparisons use combined metrics, including "
            "zone-builder cost when present."
        )

    lines = [
        "Comparisons use combined metrics, including zone-builder cost when present. "
        "They are cost measurements for this benchmark run, not quality claims.",
        "",
        "| Variant | Combined Tokens | Token Delta | Token Change | Combined Latency (ms) | Latency Delta (ms) | Latency Change |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['variant']} | "
            f"{_fmt_optional_int(row['combined_tokens'])} | "
            f"{_fmt_signed_int(row['token_delta'])} | "
            f"{_fmt_change(row['token_delta'], row['token_change_pct'])} | "
            f"{_fmt_optional_int(row['combined_latency_ms'])} | "
            f"{_fmt_signed_int(row['latency_delta_ms'])} | "
            f"{_fmt_change(row['latency_delta_ms'], row['latency_change_pct'])} |"
        )
    return "\n".join(lines)


def _render_comparative_ratios(
    ratios: dict[str, float | None], availability: dict[str, int | bool]
) -> str:
    if not ratios:
        return (
            "Comparative ratios require both `explicit_metadata` and "
            "`cognitive_map` modes."
        )
    lines = ["Observed in this run:", ""]
    if availability.get("appears_dry_run_or_token_free"):
        lines.extend(
            [
                "Token or latency reduction ratios are `n/a` where the explicit "
                "metadata baseline is zero. This input appears to be a dry-run "
                "or token-free file because provider token fields are missing, "
                "null, or zero and latency may be zero.",
                "",
            ]
        )
    lines.extend(
        [
            f"- total token reduction percentage: {_fmt_pct(ratios['total_token_reduction_pct'])}",
            f"- prompt token reduction percentage: {_fmt_pct(ratios['prompt_token_reduction_pct'])}",
            f"- completion token reduction percentage: {_fmt_pct(ratios['completion_token_reduction_pct'])}",
            f"- latency reduction percentage: {_fmt_pct(ratios['latency_reduction_pct'])}",
            f"- mean token difference: {_fmt_float(ratios['mean_token_difference'])}",
            f"- mean latency difference: {_fmt_float(ratios['mean_latency_difference_ms'])} ms",
        ]
    )
    return "\n".join(lines)


def _render_combined_comparative_ratios(
    ratios_by_mode: dict[str, dict[str, float | None]],
    availability: dict[str, int | bool],
) -> str:
    if not ratios_by_mode:
        return (
            "Combined comparative ratios require `explicit_metadata` and at "
            "least one Cognitive Map mode."
        )

    lines = ["Observed in this run:", ""]
    if availability.get("appears_dry_run_or_token_free"):
        lines.extend(
            [
                "Combined token or latency reduction ratios are `n/a` where "
                "the explicit metadata baseline is zero. This input appears "
                "to be a dry-run or token-free file.",
                "",
            ]
        )
    for mode, ratios in ratios_by_mode.items():
        lines.extend(
            [
                f"- {mode} combined total token reduction percentage: "
                f"{_fmt_pct(ratios['combined_total_token_reduction_pct'])}",
                f"- {mode} combined prompt token reduction percentage: "
                f"{_fmt_pct(ratios['combined_prompt_token_reduction_pct'])}",
                f"- {mode} combined completion token reduction percentage: "
                f"{_fmt_pct(ratios['combined_completion_token_reduction_pct'])}",
                f"- {mode} combined latency reduction percentage: "
                f"{_fmt_pct(ratios['combined_latency_reduction_pct'])}",
                f"- {mode} combined mean token difference: "
                f"{_fmt_float(ratios['combined_mean_token_difference'])}",
                f"- {mode} combined mean latency difference: "
                f"{_fmt_float(ratios['combined_mean_latency_difference_ms'])} ms",
            ]
        )
    return "\n".join(lines)


def _render_task_table(task_rows: list[dict[str, Any]]) -> str:
    lines = [
        "| task label | mode | total tokens | latency ms | success | failure | reflection attempts |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in task_rows:
        lines.append(
            f"| {row['task_label']} | {row['mode']} | {row['total_tokens']} | "
            f"{row['latency_ms']} | {row['success_count']} | "
            f"{row['failure_count']} | {row['reflection_attempts']} |"
        )
    return "\n".join(lines)


def _render_reflection_summary(summary: dict[str, Any]) -> str:
    if not summary.get("fields_present"):
        return "Reflection fields were not detected in this input."

    labels = _comma_list(summary["triggered_labels"])
    return "\n".join(
        [
            f"- cognitive_map rows: {summary['cognitive_map_rows']}",
            f"- rows where reflection_triggered is true: {summary['reflection_triggered_rows']}",
            f"- labels that triggered reflection: {labels}",
            f"- total reflection attempts used: {summary['total_reflection_attempts_used']}",
            f"- verification passed count: {summary['verification_passed_count']}",
            f"- verification failed count: {summary['verification_failed_count']}",
        ]
    )


def _interpret(
    summary: dict[str, dict[str, float | int]],
    availability: dict[str, int | bool] | None = None,
) -> str:
    ratios_by_mode = combined_comparative_ratios(summary)
    if not ratios_by_mode:
        return (
            "This report could not compare Cognitive Map with explicit metadata "
            "because both modes were not present."
        )

    usable_ratios = [
        ratios
        for ratios in ratios_by_mode.values()
        if ratios["combined_total_token_reduction_pct"] is not None
        and ratios["combined_latency_reduction_pct"] is not None
    ]
    if not usable_ratios:
        if availability and availability.get("appears_dry_run_or_token_free"):
            return (
                "In this run, comparative reduction ratios were not available "
                "because the input appears to be a dry-run or token-free file. "
                "Use a live benchmark run with provider-reported tokens and "
                "latency for cost interpretation."
            )
        return (
            "In this run, comparative reduction ratios were not available because "
            "one or more explicit metadata baseline totals were zero. Use a live "
            "benchmark run with provider-reported tokens and latency for cost "
            "interpretation."
        )

    if any(
        float(ratios["combined_total_token_reduction_pct"]) > 0
        and float(ratios["combined_latency_reduction_pct"]) > 0
        for ratios in usable_ratios
    ):
        return (
            "In this run, at least one Cognitive Map mode reduced combined "
            "token usage and latency compared with explicit metadata. This is "
            "a cost measurement for the tested payloads and zone-builder setup; "
            "it does not prove answer quality, semantic improvement, or a "
            "brain-like cognitive mechanism."
        )

    return (
        "In this run, Cognitive Map did not reduce both combined token usage "
        "and latency. Treat this as a cost measurement for one injected "
        "intelligence step, not as a quality result."
    )


def _comparison_mode(row: dict[str, Any]) -> str:
    return str(row.get("comparison_mode") or row.get("mode", "unknown"))


def _numeric_values(
    rows: list[dict[str, Any]], key: str, missing_as_zero: bool = False
) -> list[int]:
    values = []
    for row in rows:
        value = row.get(key)
        if value is None:
            if missing_as_zero:
                values.append(0)
            continue
        values.append(int(value))
    return values


def _combined_numeric_values(
    rows: list[dict[str, Any]],
    combined_key: str,
    executor_key: str,
    zone_builder_key: str,
    missing_as_zero: bool = False,
) -> list[int]:
    values = []
    for row in rows:
        if combined_key in row:
            value = row.get(combined_key)
            if value is None:
                if missing_as_zero:
                    values.append(0)
                continue
            values.append(int(value))
            continue

        executor_value = row.get(executor_key)
        zone_builder_value = row.get(zone_builder_key)
        if executor_value is None and zone_builder_value is None:
            if missing_as_zero:
                values.append(0)
            continue
        values.append(int(executor_value or 0) + int(zone_builder_value or 0))
    return values


def _strict_combined_sum(
    rows: list[dict[str, Any]],
    combined_key: str,
    executor_key: str,
    zone_builder_key: str,
) -> int | None:
    values = []
    for row in rows:
        if combined_key in row:
            value = row.get(combined_key)
            if value is None:
                return None
            values.append(int(value))
            continue

        executor_value = row.get(executor_key)
        if executor_value is None:
            return None
        values.append(int(executor_value) + int(row.get(zone_builder_key) or 0))
    return sum(values)


def _delta(value: int | None, baseline: int | None) -> int | None:
    if value is None or baseline is None:
        return None
    return value - baseline


def _percentage_change(value: int | None, baseline: int | None) -> float | None:
    if value is None or baseline is None or baseline == 0:
        return None
    return ((value - baseline) / baseline) * 100


def _mean(values: list[int]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _reduction_pct(baseline: float | int, comparison: float | int) -> float | None:
    baseline_value = float(baseline)
    if baseline_value == 0:
        return None
    return ((baseline_value - float(comparison)) / baseline_value) * 100


def _positive_number(value: Any) -> bool:
    if value is None:
        return False
    return float(value) > 0


def _fmt_float(value: float | int | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2f}"


def _fmt_optional_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


def _fmt_signed_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    if value > 0:
        return f"+{value}"
    return str(value)


def _fmt_change(delta: int | None, percentage: float | None) -> str:
    if delta is None or percentage is None:
        return "n/a"
    if delta < 0:
        label = "lower"
    elif delta > 0:
        label = "higher"
    else:
        label = "equal"
    sign = "+" if percentage > 0 else ""
    return f"{sign}{percentage:.2f}% {label}"


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _comma_list(values: list[str]) -> str:
    return ", ".join(values) if values else "none"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
