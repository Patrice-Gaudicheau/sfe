"""Run repeated large/contextual benchmark iterations and report stability."""

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

from providers.lemonade import DEFAULT_BASE_URL, DEFAULT_TIMEOUT
from router.llm_router import DEFAULT_ROUTER_MODEL
from runtime.metrics import average, percent_reduction, success_rate, write_json_report, write_text_report
from runtime.run_experiment import DEFAULT_EXECUTION_MODEL
from runtime.run_large_contextual_benchmark import (
    BENCHMARK_TYPE,
    FINAL_PHASE_CONCLUSION,
    SELECTION_MODES,
    TASK_TIER_DESCRIPTIONS,
    TASK_TIER_STANDARD,
    TASK_TIERS,
    get_large_contextual_tasks,
    normalize_task_tier,
    run_benchmark,
)
from sfe.env import load_repo_env


DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "large_contextual_stability.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "large_contextual_stability.md"


def main() -> None:
    load_repo_env()
    args = _parse_args()
    tasks = get_large_contextual_tasks(args.task_tier)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1 when provided.")
        tasks = tasks[: args.limit]

    iteration_reports = []
    for index in range(1, args.iterations + 1):
        print(f"Running stability iteration {index}/{args.iterations}...")
        iteration_reports.append(
            run_benchmark(
                tasks=tasks,
                repeat=1,
                model=args.model,
                base_url=args.base_url,
                timeout_seconds=args.timeout_seconds,
                max_tokens=args.max_tokens,
                dry_run=args.dry_run,
                selection_mode=args.selection_mode,
                router_model=args.router_model,
                task_tier=args.task_tier,
            )
        )

    report = build_stability_report(
        iteration_reports=iteration_reports,
        selection_mode=args.selection_mode,
        model=args.model,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        max_tokens=args.max_tokens,
        dry_run=args.dry_run,
        router_model=args.router_model,
        task_tier=args.task_tier,
    )
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeated large/contextual benchmark iterations and aggregate stability."
    )
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--selection-mode",
        choices=SELECTION_MODES,
        default="both",
        help="Benchmark selection mode to repeat.",
    )
    parser.add_argument(
        "--task-tier",
        choices=TASK_TIERS,
        default=TASK_TIER_STANDARD,
        help=(
            "Task tier to repeat. Defaults to standard so existing scheduled "
            "stability runs remain on the 7-task reference benchmark. long is a "
            "backward-compatible alias for practical."
        ),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("SFE_EXECUTOR_MODEL") or DEFAULT_EXECUTION_MODEL,
        help="Lemonade executor model id.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("SFE_LEMONADE_BASE_URL") or DEFAULT_BASE_URL,
        help="Lemonade OpenAI-compatible base URL.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Lemonade request timeout.",
    )
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument(
        "--router-model",
        default=os.getenv("SFE_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL,
        help="Lemonade model id for router selection modes.",
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompts and deterministic metrics without calling Lemonade.",
    )
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("--iterations must be at least 1.")
    if args.timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than 0.")
    if args.max_tokens < 1:
        raise ValueError("--max-tokens must be at least 1.")
    return args


def build_stability_report(
    iteration_reports: list[dict[str, Any]],
    selection_mode: str,
    model: str,
    base_url: str = DEFAULT_BASE_URL,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    max_tokens: int = 160,
    dry_run: bool = False,
    router_model: str | None = None,
    task_tier: str = TASK_TIER_STANDARD,
) -> dict[str, Any]:
    if not iteration_reports:
        raise ValueError("At least one iteration report is required.")
    if selection_mode not in SELECTION_MODES:
        raise ValueError(f"Unknown selection mode: {selection_mode}")
    task_tier = normalize_task_tier(task_tier)

    runs = _runs_with_iteration_index(iteration_reports)
    task_labels = sorted({run["task_label"] for run in runs})
    router_runs = [run for run in runs if run["mode"] == "spatial_router"]
    summary = summarize_stability(iteration_reports, runs)
    per_task = summarize_per_task_stability(runs)
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_type": BENCHMARK_TYPE,
            "selection_mode": selection_mode,
            "task_tier": task_tier,
            "task_tier_description": TASK_TIER_DESCRIPTIONS[task_tier],
            "iteration_count": len(iteration_reports),
            "task_count": len(task_labels),
            "total_runs": len(runs),
            "executor": "lemonade",
            "executor_model": model,
            "router_model": router_model if selection_mode in ("router", "both") else None,
            "base_url": base_url,
            "timeout_seconds": timeout_seconds,
            "max_tokens": max_tokens,
            "dry_run": dry_run,
            "final_phase_conclusion": FINAL_PHASE_CONCLUSION,
        },
        "summary": summary,
        "per_task": per_task,
        "per_iteration": [
            {
                "iteration": index,
                "metadata": report["metadata"],
                "summary": report["summary"],
                "per_task": report["per_task"],
            }
            for index, report in enumerate(iteration_reports, start=1)
        ],
        "runs": runs,
    "router_runs": router_runs,
    }


def summarize_stability(
    iteration_reports: list[dict[str, Any]], runs: list[dict[str, Any]]
) -> dict[str, Any]:
    by_mode = {
        mode: [run for run in runs if run["mode"] == mode]
        for mode in ("baseline", "spatial", "spatial_fixture", "spatial_router")
    }
    router_runs = by_mode["spatial_router"]
    valid_router_runs = [
        run for run in router_runs if run.get("router_valid_selection") is True
    ]
    matched_router_runs = [
        run for run in router_runs if run.get("router_selection_matches_fixture") is True
    ]
    valid_matched_router_runs = [
        run for run in valid_router_runs if run.get("router_selection_matches_fixture") is True
    ]
    fallback_runs = [
        run for run in router_runs if run.get("executor_used_fallback") is True
    ]
    comparison_mode = _comparison_mode(by_mode)
    baseline_input = average(run["input_tokens"] for run in by_mode["baseline"])
    comparison_input = average(run["input_tokens"] for run in by_mode[comparison_mode])
    baseline_latency_ms = _optional_average(run["latency_ms"] for run in by_mode["baseline"])
    baseline_total_tokens = _optional_average(run["total_tokens"] for run in by_mode["baseline"])
    spatial_fixture_runs = by_mode["spatial_fixture"] or by_mode["spatial"]
    spatial_fixture_latency_ms = _optional_average(
        run["latency_ms"] for run in spatial_fixture_runs
    )
    spatial_fixture_total_tokens = _optional_average(
        run["total_tokens"] for run in spatial_fixture_runs
    )
    spatial_router_executor_latency_ms = _optional_average(
        run["latency_ms"] for run in router_runs
    )
    spatial_router_executor_total_tokens = _optional_average(
        run["total_tokens"] for run in router_runs
    )
    spatial_router_end_to_end_latency_ms = _optional_average(
        run["router_end_to_end_latency_ms"]
        for run in router_runs
        if run.get("router_end_to_end_latency_ms") is not None
    )
    spatial_router_end_to_end_total_tokens = _optional_average(
        run["router_end_to_end_total_tokens"]
        for run in router_runs
        if run.get("router_end_to_end_total_tokens") is not None
    )
    per_task = summarize_per_task_stability(runs)
    return {
        "iteration_count": len(iteration_reports),
        "task_count": len({run["task_label"] for run in runs}),
        "total_runs": len(runs),
        "baseline_success_rate": _success_rate_or_none(by_mode["baseline"]),
        "spatial_success_rate": _success_rate_or_none(by_mode["spatial"]),
        "spatial_fixture_success_rate": _success_rate_or_none(
            by_mode["spatial_fixture"] or by_mode["spatial"]
        ),
        "spatial_router_success_rate": _success_rate_or_none(by_mode["spatial_router"]),
        "router_valid_selection_rate": _ratio(len(valid_router_runs), len(router_runs)),
        "router_match_rate": _ratio(len(matched_router_runs), len(router_runs)),
        "router_match_rate_valid_selections": _ratio(
            len(valid_matched_router_runs), len(valid_router_runs)
        ),
        "fallback_count": len(fallback_runs),
        "fallback_rate": _ratio(len(fallback_runs), len(router_runs)),
        "per_task_router_match_count": {
            row["task_label"]: row["router_match_count"]
            for row in per_task
        },
        "per_task_fallback_count": {
            row["task_label"]: row["fallback_count"]
            for row in per_task
        },
        "average_router_latency_ms": _optional_average(
            run["router_latency_ms"]
            for run in router_runs
            if run.get("router_latency_ms") is not None
        ),
        "average_router_total_tokens": _optional_average(
            run["router_total_tokens"]
            for run in router_runs
            if run.get("router_total_tokens") is not None
        ),
        "average_baseline_latency_ms": baseline_latency_ms,
        "average_baseline_total_tokens": baseline_total_tokens,
        "average_spatial_fixture_latency_ms": spatial_fixture_latency_ms,
        "average_spatial_fixture_total_tokens": spatial_fixture_total_tokens,
        "average_spatial_router_executor_latency_ms": spatial_router_executor_latency_ms,
        "average_spatial_router_executor_total_tokens": spatial_router_executor_total_tokens,
        "average_spatial_router_router_executor_latency_ms": spatial_router_end_to_end_latency_ms,
        "average_spatial_router_router_executor_total_tokens": spatial_router_end_to_end_total_tokens,
        "average_router_executor_latency_ms": spatial_router_end_to_end_latency_ms,
        "average_router_executor_total_tokens": spatial_router_end_to_end_total_tokens,
        "router_inclusive_token_reduction_vs_baseline": _optional_percent_reduction(
            baseline_total_tokens, spatial_router_end_to_end_total_tokens
        ),
        "router_inclusive_latency_reduction_vs_baseline": _optional_percent_reduction(
            baseline_latency_ms, spatial_router_end_to_end_latency_ms
        ),
        "average_input_token_reduction": percent_reduction(
            baseline_input, comparison_input
        ),
        "average_iteration_input_token_reduction": average(
            report["summary"]["token_reduction_percent"] for report in iteration_reports
        ),
    }


def summarize_per_task_stability(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for label in sorted({run["task_label"] for run in runs}):
        task_runs = [run for run in runs if run["task_label"] == label]
        router_runs = [run for run in task_runs if run["mode"] == "spatial_router"]
        router_selected_ids = [
            str(run.get("router_selected_block_id") or "n/a") for run in router_runs
        ]
        rows.append(
            {
                "task_label": label,
                "baseline_success_rate": _success_rate_or_none(
                    [run for run in task_runs if run["mode"] == "baseline"]
                ),
                "spatial_fixture_success_rate": _success_rate_or_none(
                    [run for run in task_runs if run["mode"] in ("spatial", "spatial_fixture")]
                ),
                "spatial_router_success_rate": _success_rate_or_none(router_runs),
                "router_run_count": len(router_runs),
                "router_valid_selection_count": sum(
                    1 for run in router_runs if run.get("router_valid_selection") is True
                ),
                "router_match_count": sum(
                    1
                    for run in router_runs
                    if run.get("router_selection_matches_fixture") is True
                ),
                "router_mismatch_count": sum(
                    1
                    for run in router_runs
                    if run.get("router_selection_matches_fixture") is False
                ),
                "fallback_count": sum(
                    1 for run in router_runs if run.get("executor_used_fallback") is True
                ),
                "router_selected_block_counts": {
                    block_id: router_selected_ids.count(block_id)
                    for block_id in sorted(set(router_selected_ids))
                },
                "average_router_latency_ms": _optional_average(
                    run["router_latency_ms"]
                    for run in router_runs
                    if run.get("router_latency_ms") is not None
                ),
                "average_router_total_tokens": _optional_average(
                    run["router_total_tokens"]
                    for run in router_runs
                    if run.get("router_total_tokens") is not None
                ),
            }
        )
    return rows


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Large Contextual Stability Report",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Selection mode: `{report['metadata']['selection_mode']}`",
        f"Task tier: `{report['metadata']['task_tier']}` ({report['metadata']['task_tier_description']})",
        f"Iterations: {summary['iteration_count']}",
        f"Task count: {summary['task_count']}",
        f"Total runs: {summary['total_runs']}",
        f"Dry run: `{report['metadata']['dry_run']}`",
        "",
        "## Aggregate Stability",
        "",
        f"Baseline success rate: {_format_optional_percent(summary['baseline_success_rate'])}",
        f"Spatial fixture success rate: {_format_optional_percent(summary['spatial_fixture_success_rate'])}",
        f"Spatial router success rate: {_format_optional_percent(summary['spatial_router_success_rate'])}",
        f"Router valid selection rate: {_format_optional_percent(summary['router_valid_selection_rate'])}",
        f"Router match rate: {_format_optional_percent(summary['router_match_rate'])}",
        f"Router match rate among valid selections: {_format_optional_percent(summary['router_match_rate_valid_selections'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Fallback rate: {_format_optional_percent(summary['fallback_rate'])}",
        f"Average baseline latency ms: {_format_optional_number(summary['average_baseline_latency_ms'])}",
        f"Average baseline total tokens: {_format_optional_number(summary['average_baseline_total_tokens'])}",
        f"Average spatial fixture latency ms: {_format_optional_number(summary['average_spatial_fixture_latency_ms'])}",
        f"Average spatial fixture total tokens: {_format_optional_number(summary['average_spatial_fixture_total_tokens'])}",
        f"Average spatial_router executor latency ms: {_format_optional_number(summary['average_spatial_router_executor_latency_ms'])}",
        f"Average spatial_router executor total tokens: {_format_optional_number(summary['average_spatial_router_executor_total_tokens'])}",
        f"Average router latency ms: {_format_optional_number(summary['average_router_latency_ms'])}",
        f"Average router total tokens: {_format_optional_number(summary['average_router_total_tokens'])}",
        f"Average spatial_router router+executor latency ms: {_format_optional_number(summary['average_spatial_router_router_executor_latency_ms'])}",
        f"Average spatial_router router+executor total tokens: {_format_optional_number(summary['average_spatial_router_router_executor_total_tokens'])}",
        f"Router-inclusive token reduction vs baseline: {_format_optional_reduction(summary['router_inclusive_token_reduction_vs_baseline'])}",
        f"Router-inclusive latency reduction vs baseline: {_format_optional_reduction(summary['router_inclusive_latency_reduction_vs_baseline'])}",
        f"Average input token reduction: {_format_optional_reduction(summary['average_input_token_reduction'])}",
        "",
        "## Per Task Stability",
        "",
        "| Task | Router runs | Valid | Matches | Mismatches | Fallbacks | Avg router latency ms | Avg router tokens | Selected block counts |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in report["per_task"]:
        lines.append(
            f"| `{row['task_label']}` | {row['router_run_count']} | "
            f"{row['router_valid_selection_count']} | {row['router_match_count']} | "
            f"{row['router_mismatch_count']} | {row['fallback_count']} | "
            f"{_format_optional_number(row['average_router_latency_ms'])} | "
            f"{_format_optional_number(row['average_router_total_tokens'])} | "
            f"{_format_counts(row['router_selected_block_counts'])} |"
        )

    lines.extend(["", "## Per Iteration", ""])
    lines.extend(
        [
            "| Iteration | Runs | Baseline success | Fixture success | Router success | Router valid | Router match | Fallbacks | Input reduction |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in report["per_iteration"]:
        item_summary = item["summary"]
        modes = item_summary["modes"]
        router_selection = item_summary["router_selection"]
        lines.append(
            f"| {item['iteration']} | {item['metadata']['run_count']} | "
            f"{_format_optional_percent(modes['baseline']['success_rate'])} | "
            f"{_format_optional_percent(_fixture_mode_success(modes))} | "
            f"{_format_optional_percent(_mode_success(modes, 'spatial_router'))} | "
            f"{_format_optional_percent(router_selection['valid_selection_rate'])} | "
            f"{_format_optional_percent(router_selection['match_rate'])} | "
            f"{router_selection['fallback_count']} | "
            f"{_format_optional_reduction(item_summary['token_reduction_percent'])} |"
        )

    lines.extend(["", "## Conclusion", "", FINAL_PHASE_CONCLUSION, ""])
    write_text_report(path, "\n".join(lines))


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Large/contextual stability")
    print(
        f"task tier: {report['metadata']['task_tier']} "
        f"({report['metadata']['task_tier_description']})"
    )
    print(f"iterations: {summary['iteration_count']}")
    print(f"task count: {summary['task_count']}")
    print(f"total runs: {summary['total_runs']}")
    print(f"router match rate: {_format_optional_percent(summary['router_match_rate'])}")
    print(f"router valid selection rate: {_format_optional_percent(summary['router_valid_selection_rate'])}")
    print(f"fallback count: {summary['fallback_count']}")
    print(f"fallback rate: {_format_optional_percent(summary['fallback_rate'])}")
    print(f"average input token reduction: {_format_optional_reduction(summary['average_input_token_reduction'])}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _runs_with_iteration_index(iteration_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs = []
    for index, report in enumerate(iteration_reports, start=1):
        for run in report["runs"]:
            runs.append({**run, "stability_iteration": index})
    return runs


def _comparison_mode(by_mode: dict[str, list[dict[str, Any]]]) -> str:
    if by_mode["spatial_fixture"]:
        return "spatial_fixture"
    if by_mode["spatial"]:
        return "spatial"
    if by_mode["spatial_router"]:
        return "spatial_router"
    raise ValueError("No spatial mode found.")


def _success_rate_or_none(runs: list[dict[str, Any]]) -> float | None:
    return success_rate(runs) if runs else None


def _optional_average(values: Any) -> float | None:
    numbers = [float(value) for value in values]
    return average(numbers) if numbers else None


def _optional_percent_reduction(
    baseline: float | None, reduced: float | None
) -> float | None:
    if baseline is None or reduced is None:
        return None
    return percent_reduction(baseline, reduced)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _mode_success(modes: dict[str, dict[str, Any]], mode: str) -> float | None:
    data = modes.get(mode)
    return None if data is None else data["success_rate"]


def _fixture_mode_success(modes: dict[str, dict[str, Any]]) -> float | None:
    fixture_success = _mode_success(modes, "spatial_fixture")
    if fixture_success is not None:
        return fixture_success
    return _mode_success(modes, "spatial")


def _format_optional_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_optional_reduction(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_optional_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "n/a"
    return ", ".join(f"`{block_id}`: {count}" for block_id, count in counts.items())


if __name__ == "__main__":
    main()
