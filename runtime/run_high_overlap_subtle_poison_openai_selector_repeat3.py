"""Run repeat-3 OpenAI selector smoke for the subtle-poison fixture.

This runner repeats the selector-only subtle-poison smoke path three times. It
does not run an executor, repair, fallback-as-success, full-context execution,
or selected-vs-full comparison.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import DEFAULT_ROUTER_MODEL, OpenAIAPIProvider
from runtime.metrics import write_json_report, write_text_report
from runtime.run_high_overlap_poison_pill_benchmark import PoisonPillTask
from runtime.run_high_overlap_subtle_poison_benchmark import get_high_overlap_subtle_poison_tasks
from runtime.run_high_overlap_subtle_poison_openai_selector_smoke import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    OPENAI_API_PROVIDER,
    OPENAI_SELECTOR_API_PATH,
    SelectorConfig,
    SelectorProvider,
    execute_selector_smoke,
)
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/high_overlap_subtle_poison_openai_selector_repeat3"
BENCHMARK_NAME = "high_overlap_subtle_poison_openai_selector_repeat3"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_subtle_poison_openai_selector_repeat3.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_subtle_poison_openai_selector_repeat3.md"
DEFAULT_REPEAT = 3


def main() -> None:
    args = _parse_args()
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL
    timeout = args.timeout
    if timeout is None and os.getenv("SFE_OPENAI_API_TIMEOUT"):
        timeout = float(os.environ["SFE_OPENAI_API_TIMEOUT"])
    provider = OpenAIAPIProvider(timeout=timeout)
    health = provider.health()
    if not health["ok"]:
        report = build_skipped_report(
            model=model,
            timeout=timeout,
            repeat=args.repeat,
            reason=health["error"],
        )
        write_json_report(args.json, report)
        write_skipped_markdown(args.md, report)
        print_skipped_report(report, args.json, args.md)
        return
    report = run_repeat_smoke(
        tasks=get_high_overlap_subtle_poison_tasks(),
        provider=provider,
        config=SelectorConfig(
            model=model,
            timeout=timeout,
            max_output_tokens=args.max_output_tokens,
        ),
        repeat=args.repeat,
    )
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run repeat-3 OpenAI selector smoke over the high-overlap "
            "subtle-poison fixture."
        )
    )
    parser.add_argument(
        "--model",
        help=(
            "OpenAI selector model. Defaults to SFE_OPENAI_ROUTER_MODEL, then the "
            "project OpenAI router default."
        ),
    )
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument(
        "--repeat",
        type=int,
        default=DEFAULT_REPEAT,
        choices=[DEFAULT_REPEAT],
        help="Selector-only repeat count. This runner is intentionally limited to repeat-3.",
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def run_repeat_smoke(
    *,
    tasks: list[PoisonPillTask],
    provider: SelectorProvider,
    config: SelectorConfig,
    repeat: int = DEFAULT_REPEAT,
) -> dict[str, Any]:
    if not tasks:
        raise ValueError("At least one high-overlap subtle-poison task is required.")
    if repeat != DEFAULT_REPEAT:
        raise ValueError("repeat must be exactly 3 for this smoke runner.")
    if not config.model:
        raise ValueError("OpenAI selector model is required.")
    if config.max_output_tokens < 1:
        raise ValueError("max_output_tokens must be at least 1.")

    task = tasks[0]
    runs: list[dict[str, Any]] = []
    for run_index in range(1, repeat + 1):
        run = execute_selector_smoke(task=task, provider=provider, config=config)
        run["run_index"] = run_index
        runs.append(run)
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "provider": OPENAI_API_PROVIDER,
            "api_path": OPENAI_SELECTOR_API_PATH,
            "router_model": config.model,
            "fixture_id": task.fixture_id,
            "repeat": repeat,
            "max_output_tokens": config.max_output_tokens,
            "timeout": config.timeout,
            "selector_scope": "source_selection_only",
            "executor": "not_tested",
            "comparison_scope": "not_tested",
            "fallback_policy": "no fallback; fallback counts as failure",
            "repair_policy": "no repair; repair is not supported",
            "evidence_level": "repeat-3 smoke observation; not statistical proof",
        },
        "summary": summarize_repeat_runs(runs),
        "runs": runs,
    }


def build_skipped_report(
    *,
    model: str,
    timeout: float | None,
    repeat: int,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "skip_reason": "missing OPENAI_API_KEY",
        "skip_detail": reason,
        "provider": OPENAI_API_PROVIDER,
        "selector_scope": "source_selection_only",
        "executor": "not_tested",
        "comparison_scope": "not_tested",
        "benchmark": "high_overlap_subtle_poison",
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_type": BENCHMARK_TYPE,
        "router_model": model,
        "api_path": OPENAI_SELECTOR_API_PATH,
        "timeout": timeout,
        "repeat": repeat,
        "skipped": True,
        "total_runs": 0,
        "honest_selector_pass": False,
        "runs": [],
    }


def summarize_repeat_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    total_runs = len(runs)
    honest_pass_count = sum(1 for run in runs if run["honest_selector_pass"])
    honest_fail_count = total_runs - honest_pass_count
    any_provider_error = any(run["selector_provider_error"] for run in runs)
    any_parse_failure = any(not run["parse_success"] for run in runs)
    any_fallback = any(run["fallback_used"] for run in runs)
    any_repair = any(run["repair_used"] for run in runs)
    return {
        "total_runs": total_runs,
        "run_count": total_runs,
        "skipped": False,
        "evidence_level": "repeat-3 smoke observation; not statistical proof",
        "honest_pass_count": honest_pass_count,
        "honest_fail_count": honest_fail_count,
        "honest_selector_pass_count": honest_pass_count,
        "honest_selector_pass_rate": _rate(run["honest_selector_pass"] for run in runs),
        "all_runs_honest_pass": bool(total_runs and honest_pass_count == total_runs),
        "any_selector_failure": honest_fail_count > 0,
        "any_provider_error": any_provider_error,
        "any_parse_failure": any_parse_failure,
        "any_fallback": any_fallback,
        "any_repair": any_repair,
        "fallback_count": sum(1 for run in runs if run["fallback_used"]),
        "repair_count": sum(1 for run in runs if run["repair_used"]),
        "provider_error_count": sum(1 for run in runs if run["selector_provider_error"]),
        "parse_failure_count": sum(1 for run in runs if not run["parse_success"]),
        "subtle_poison_selection_count": sum(
            1 for run in runs if run["selected_subtle_poison_source_ids"]
        ),
        "obsolete_selection_count": sum(
            1 for run in runs if run["selected_obsolete_source_ids"]
        ),
        "partial_selection_count": sum(
            1 for run in runs if run["selected_partial_source_ids"]
        ),
        "mixed_selection_count": sum(
            1
            for run in runs
            if run["authoritative_source_selected"] and run["extra_selected_source_ids"]
        ),
        "total_prompt_tokens": _sum_usage(runs, "input_tokens"),
        "total_completion_tokens": _sum_usage(runs, "output_tokens"),
        "total_tokens": _sum_usage(runs, "total_tokens"),
        "total_latency_ms": _sum_latency(runs),
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# High-Overlap Subtle-Poison OpenAI Selector Repeat-3 Smoke",
        "",
        "This is an OpenAI selector repeat-3 smoke for a controlled subtle-poison "
        "fixture. It is selector-only: no executor was tested, no full-context "
        "execution was tested, and no selected-vs-full comparison was tested.",
        "",
        "The fixture checks authority-gap reasoning. Selector failure is a valid "
        "observation. This repeat-3 smoke is not statistical proof and not a "
        "reliability benchmark.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Router model: `{report['metadata']['router_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"API path: `{report['metadata']['api_path']}`",
        f"Repeat count: {report['metadata']['repeat']}",
        "",
        "## Summary",
        "",
        f"Honest selector pass count: {summary['honest_pass_count']}/{summary['total_runs']}",
        f"Honest selector fail count: {summary['honest_fail_count']}",
        f"All runs honest pass: {summary['all_runs_honest_pass']}",
        f"Any selector failure: {summary['any_selector_failure']}",
        f"Any provider error: {summary['any_provider_error']}",
        f"Any parse failure: {summary['any_parse_failure']}",
        f"Any fallback: {summary['any_fallback']}",
        f"Any repair: {summary['any_repair']}",
        f"Subtle-poison selection count: {summary['subtle_poison_selection_count']}",
        f"Obsolete selection count: {summary['obsolete_selection_count']}",
        f"Partial selection count: {summary['partial_selection_count']}",
        f"Mixed selection count: {summary['mixed_selection_count']}",
        f"Total prompt tokens: {_format_optional_int(summary['total_prompt_tokens'])}",
        f"Total completion tokens: {_format_optional_int(summary['total_completion_tokens'])}",
        f"Total tokens: {_format_optional_int(summary['total_tokens'])}",
        f"Total latency ms: {_format_optional_int(summary['total_latency_ms'])}",
        "",
        "## Runs",
        "",
        "| Run | Honest pass | Selected candidate handles | Mapped source IDs | Fallback | Repair | Parse success | Provider error | Exact authoritative | Subtle selected | Obsolete selected | Partial selected | Tokens | Latency ms |",
        "| ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | ---: |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| {run['run_index']} | "
            f"{run['honest_selector_pass']} | "
            f"{', '.join(run['selected_prompt_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_source_ids']) or 'none'} | "
            f"{run['fallback_used']} | "
            f"{run['repair_used']} | "
            f"{run['parse_success']} | "
            f"{run['selector_provider_error']} | "
            f"{run['exact_authoritative_selection']} | "
            f"{', '.join(run['selected_subtle_poison_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_obsolete_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_partial_source_ids']) or 'none'} | "
            f"{_format_optional_int(run['usage'].get('total_tokens'))} | "
            f"{_format_optional_int(run['latency_ms'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def write_skipped_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# High-Overlap Subtle-Poison OpenAI Selector Repeat-3 Smoke",
        "",
        "Status: skipped",
        f"Reason: {report['skip_reason']}",
        "Scope: selector-only; no executor was run.",
        "No provider/API call was made.",
        "Skipped is not a pass or failure of selector behavior.",
        "",
        f"Benchmark type: `{report['benchmark_type']}`",
        f"Provider: `{report['provider']}`",
        f"Router model: `{report['router_model']}`",
        f"Repeat count: {report['repeat']}",
    ]
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap subtle-poison OpenAI selector repeat-3 smoke")
    print(f"router model: {report['metadata']['router_model']}")
    print(f"honest selector pass count: {summary['honest_pass_count']}/{summary['total_runs']}")
    print(f"all runs honest pass: {summary['all_runs_honest_pass']}")
    print(f"any selector failure: {summary['any_selector_failure']}")
    print(f"any provider error: {summary['any_provider_error']}")
    print(f"any parse failure: {summary['any_parse_failure']}")
    print(f"any fallback: {summary['any_fallback']}")
    print(f"any repair: {summary['any_repair']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def print_skipped_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    print("High-overlap subtle-poison OpenAI selector repeat-3 smoke")
    print("status: skipped")
    print(f"reason: {report['skip_reason']}")
    print("scope: selector-only; no executor was run")
    print("provider/API call made: false")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _rate(values: Any) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if bool(item)) / len(items)


def _sum_usage(runs: list[dict[str, Any]], key: str) -> int | None:
    values = [run["usage"].get(key) for run in runs if run["usage"].get(key) is not None]
    if not values:
        return None
    return sum(int(value) for value in values)


def _sum_latency(runs: list[dict[str, Any]]) -> int | None:
    values = [run["latency_ms"] for run in runs if run.get("latency_ms") is not None]
    if not values:
        return None
    return sum(int(value) for value in values)


def _format_optional_int(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(int(value))


if __name__ == "__main__":
    main()
