"""Run repeat-3 OpenAI selector smoke for the high-overlap poison-pill fixture.

This runner repeats selector-only execution over the same deterministic fixture.
It does not run an executor and does not treat repeat-3 as statistical proof.
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
from runtime.high_overlap_benchmark_helpers import (
    format_optional_int as _format_optional_int,
    format_percent as _format_percent,
    rate as _rate,
    sum_latency as _sum_latency,
    sum_usage as _sum_usage,
)
from runtime.metrics import write_json_report, write_text_report
from runtime.run_high_overlap_poison_pill_benchmark import (
    PoisonPillTask,
    get_high_overlap_poison_pill_tasks,
)
from runtime.run_high_overlap_poison_pill_openai_selector_smoke import (
    OPENAI_API_PROVIDER,
    OPENAI_SELECTOR_API_PATH,
    DEFAULT_MAX_OUTPUT_TOKENS,
    SelectorConfig,
    SelectorProvider,
    execute_selector_smoke,
)
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/high_overlap_poison_pill_openai_selector_repeat3"
BENCHMARK_NAME = "high_overlap_poison_pill_openai_selector_repeat3"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_poison_pill_openai_selector_repeat3.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_poison_pill_openai_selector_repeat3.md"
DEFAULT_REPEAT = 3


def main() -> None:
    args = _parse_args()
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL
    timeout = args.timeout
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
        tasks=get_high_overlap_poison_pill_tasks(),
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
        description="Run repeat-3 OpenAI selector smoke over the high-overlap poison-pill fixture."
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
        help=(
            "Selector-only repeat count. This runner is intentionally limited "
            "to repeat-3."
        ),
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
        raise ValueError("At least one high-overlap poison-pill task is required.")
    if repeat < 1:
        raise ValueError("repeat must be at least 1.")
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
            "executor": "deterministic_validator_only",
            "fallback_policy": "no oracle fallback; fallback counts as failure",
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
        "benchmark": "high_overlap_poison_pill",
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_type": BENCHMARK_TYPE,
        "router_model": model,
        "api_path": OPENAI_SELECTOR_API_PATH,
        "timeout": timeout,
        "repeat": repeat,
        "run_count": 0,
        "honest_selector_pass": False,
        "runs": [],
    }


def summarize_repeat_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_count": len(runs),
        "evidence_level": "repeat-3 smoke observation; not statistical proof",
        "honest_selector_pass_count": sum(1 for run in runs if run["honest_selector_pass"]),
        "honest_selector_pass_rate": _rate(run["honest_selector_pass"] for run in runs),
        "fallback_count": sum(1 for run in runs if run["fallback_used"]),
        "parse_failure_count": sum(1 for run in runs if not run["parse_success"]),
        "poison_selection_count": sum(
            1 for run in runs if run["selected_poison_pill_source_ids"]
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
        "# High-Overlap Poison-Pill OpenAI Selector Repeat-3 Smoke",
        "",
        "This is a selector-only repeat-3 smoke observation. It does not run an "
        "executor and does not provide statistical proof of selector robustness.",
        "",
        "Deterministic validation is the source of truth. No oracle fallback is "
        "counted as success.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Router model: `{report['metadata']['router_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"API path: `{report['metadata']['api_path']}`",
        f"Repeat count: {report['metadata']['repeat']}",
        "",
        "## Summary",
        "",
        f"Honest selector pass count: {summary['honest_selector_pass_count']}/{summary['run_count']}",
        f"Honest selector pass rate: {_format_percent(summary['honest_selector_pass_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Parse failure count: {summary['parse_failure_count']}",
        f"Poison selection count: {summary['poison_selection_count']}",
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
        "| Run | Honest pass | Selected sources | Fallback | Parse success | Exact authoritative | Poison selected | Obsolete selected | Partial selected | Tokens | Latency ms |",
        "| ---: | ---: | --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| {run['run_index']} | "
            f"{run['honest_selector_pass']} | "
            f"{', '.join(run['selected_source_ids']) or 'none'} | "
            f"{run['fallback_used']} | "
            f"{run['parse_success']} | "
            f"{run['exact_authoritative_selection']} | "
            f"{', '.join(run['selected_poison_pill_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_obsolete_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_partial_source_ids']) or 'none'} | "
            f"{_format_optional_int(run['usage'].get('total_tokens'))} | "
            f"{_format_optional_int(run['latency_ms'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def write_skipped_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# High-Overlap Poison-Pill OpenAI Selector Repeat-3 Smoke",
        "",
        "Status: skipped",
        f"Reason: {report['skip_reason']}",
        "Scope: selector-only; no executor was run.",
        "No provider/API call was made.",
        "Skipped is not a pass or failure of selector robustness.",
        "",
        f"Benchmark type: `{report['benchmark_type']}`",
        f"Provider: `{report['provider']}`",
        f"Router model: `{report['router_model']}`",
        f"Repeat count: {report['repeat']}",
    ]
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap poison-pill OpenAI selector repeat-3 smoke")
    print(f"router model: {report['metadata']['router_model']}")
    print(
        "honest selector pass count: "
        f"{summary['honest_selector_pass_count']}/{summary['run_count']}"
    )
    print(f"honest selector pass rate: {_format_percent(summary['honest_selector_pass_rate'])}")
    print(f"fallback count: {summary['fallback_count']}")
    print(f"parse failure count: {summary['parse_failure_count']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def print_skipped_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    print("High-overlap poison-pill OpenAI selector repeat-3 smoke")
    print("status: skipped")
    print(f"reason: {report['skip_reason']}")
    print("scope: selector-only; no executor was run")
    print("provider/API call made: false")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


if __name__ == "__main__":
    main()
