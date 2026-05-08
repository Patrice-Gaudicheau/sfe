"""Run reproducible sfe router and prompt-shape benchmarks."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from router.llm_router import (
    DEFAULT_ROUTER_MODEL,
    route_with_llm,
    route_with_llm_raw_diagnostics,
)
from router.mock_router import route
from providers.lemonade import DEFAULT_TIMEOUT
from runtime.run_experiment import DEFAULT_LEMONADE_BASE_URL, _build_execution_prompt
from runtime.metrics import estimate_text_tokens, percentage, write_json_report


DEFAULT_TASKS_PATH = PROJECT_ROOT / "benchmarks" / "tasks.json"


def main() -> None:
    args = _parse_args()
    if args.router in ("llm", "llm_raw"):
        os.environ.setdefault("SFE_LEMONADE_BASE_URL", DEFAULT_LEMONADE_BASE_URL)
    router_model = _resolve_router_model(args.router, args.router_model)
    router_timeout_seconds = _resolve_router_timeout_seconds(
        args.router, args.router_timeout_seconds
    )
    router_disable_thinking = _resolve_router_disable_thinking(
        args.router, args.router_disable_thinking
    )
    tasks = _load_tasks(args.tasks)
    results = _run_benchmark(
        tasks,
        args.router,
        args.repeats,
        router_model,
        router_timeout_seconds,
        router_disable_thinking,
    )
    summary = _summarize(results)

    _print_report(
        args.router,
        router_model,
        router_timeout_seconds,
        router_disable_thinking,
        args.repeats,
        summary,
        results,
    )

    if args.json:
        _write_json(
            args.json,
            args.router,
            router_model,
            router_timeout_seconds,
            router_disable_thinking,
            args.repeats,
            summary,
            results,
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run sfe benchmark tasks.")
    parser.add_argument("--router", choices=("mock", "llm", "llm_raw"), default="mock")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--router-model",
        help=(
            "Model used by llm and llm_raw routers. Defaults to SFE_ROUTER_MODEL "
            f"or {DEFAULT_ROUTER_MODEL}."
        ),
    )
    parser.add_argument(
        "--router-timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Lemonade timeout for llm and llm_raw router calls.",
    )
    router_thinking_group = parser.add_mutually_exclusive_group()
    router_thinking_group.add_argument(
        "--router-disable-thinking",
        dest="router_disable_thinking",
        action="store_true",
        help="Disable thinking for llm and llm_raw router calls.",
    )
    router_thinking_group.add_argument(
        "--no-router-disable-thinking",
        dest="router_disable_thinking",
        action="store_false",
        help="Allow thinking for llm and llm_raw router calls.",
    )
    parser.set_defaults(router_disable_thinking=True)
    parser.add_argument("--json", type=Path, help="Optional path for a JSON benchmark report.")
    return parser.parse_args()


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        tasks = json.load(file)

    if not isinstance(tasks, list):
        raise ValueError("Benchmark tasks file must contain a JSON list.")

    normalized_tasks = []
    required_fields = {"id", "task", "expected_task_type"}
    for task in tasks:
        task = dict(task)
        if "task" not in task and "prompt" in task:
            task["task"] = task["prompt"]
        if "expected_task_type" not in task and "task_type_expected" in task:
            task["expected_task_type"] = task["task_type_expected"]

        missing = sorted(required_fields - set(task))
        if missing:
            raise ValueError(f"Benchmark task is missing field(s): {', '.join(missing)}")
        normalized_tasks.append(task)

    return normalized_tasks


def _run_benchmark(
    tasks: list[dict[str, Any]],
    router_name: str,
    repeats: int,
    router_model: str | None,
    router_timeout_seconds: float | None,
    router_disable_thinking: bool,
) -> list[dict[str, Any]]:
    if repeats < 1:
        raise ValueError("--repeats must be at least 1.")
    if router_timeout_seconds is not None and router_timeout_seconds <= 0:
        raise ValueError("--router-timeout-seconds must be greater than 0.")

    results = []
    for task in tasks:
        attempts = [
            _route_once(
                task["task"],
                router_name,
                router_model,
                router_timeout_seconds,
                router_disable_thinking,
            )
            for _ in range(repeats)
        ]
        first_successful_decision = _first_successful_decision(attempts)
        expected_task_type = str(task["expected_task_type"])

        if first_successful_decision:
            baseline_tokens = _estimated_prompt_tokens(
                task["task"], first_successful_decision, "baseline"
            )
            spatial_tokens = _estimated_prompt_tokens(
                task["task"], first_successful_decision, "spatial"
            )
            actual_task_types = [attempt["decision"]["task_type"] for attempt in attempts if attempt["ok"]]
            actual_roles = [attempt["decision"]["role"] for attempt in attempts if attempt["ok"]]
            route_observations = [
                {
                    "task_type": attempt["decision"]["task_type"],
                    "role": attempt["decision"]["role"],
                }
                for attempt in attempts
                if attempt["ok"]
            ]
            accuracy = _accuracy(actual_task_types, expected_task_type)
            consistency = _consistency(actual_task_types)
        else:
            baseline_tokens = 0
            spatial_tokens = 0
            actual_task_types = []
            actual_roles = []
            route_observations = []
            accuracy = 0.0
            consistency = 0.0

        latencies = [attempt["latency_ms"] for attempt in attempts]
        results.append(
            {
                "id": task["id"],
                "expected_task_type": expected_task_type,
                "actual_task_types": actual_task_types,
                "actual_roles": actual_roles,
                "route_observations": route_observations,
                "accuracy": accuracy,
                "consistency": consistency,
                "mean_router_latency_ms": statistics.fmean(latencies),
                "baseline_prompt_tokens": baseline_tokens,
                "spatial_prompt_tokens": spatial_tokens,
                "prompt_token_savings": baseline_tokens - spatial_tokens,
                "prompt_token_savings_percent": _percentage(
                    baseline_tokens - spatial_tokens, baseline_tokens
                ),
                "errors": [attempt["error"] for attempt in attempts if attempt["error"]],
            }
        )

    return results


def _resolve_router_model(router_name: str, router_model: str | None) -> str | None:
    if router_name not in ("llm", "llm_raw"):
        return None
    return router_model or os.getenv("SFE_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL


def _resolve_router_timeout_seconds(
    router_name: str, router_timeout_seconds: float
) -> float | None:
    if router_name not in ("llm", "llm_raw"):
        return None
    return router_timeout_seconds


def _resolve_router_disable_thinking(
    router_name: str, router_disable_thinking: bool
) -> bool:
    if router_name not in ("llm", "llm_raw"):
        return False
    return router_disable_thinking


def _route_once(
    task: str,
    router_name: str,
    router_model: str | None,
    router_timeout_seconds: float | None,
    router_disable_thinking: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        if router_name == "llm":
            decision = route_with_llm(
                task,
                model=router_model,
                timeout_seconds=router_timeout_seconds,
                disable_thinking=router_disable_thinking,
            )
        elif router_name == "llm_raw":
            decision, _diagnostics = route_with_llm_raw_diagnostics(
                task,
                model=router_model,
                timeout_seconds=router_timeout_seconds,
                disable_thinking=router_disable_thinking,
            )
        else:
            decision = route(task)
        return {
            "ok": True,
            "decision": decision,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "error": "",
        }
    except Exception as exc:
        return {
            "ok": False,
            "decision": {},
            "latency_ms": (time.perf_counter() - started) * 1000,
            "error": str(exc),
        }


def _first_successful_decision(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    for attempt in attempts:
        if attempt["ok"]:
            return attempt["decision"]
    return None


def _estimated_prompt_tokens(task: str, routing_decision: dict[str, Any], mode: str) -> int:
    prompt = _build_execution_prompt(task, routing_decision, mode)
    return estimate_text_tokens(prompt)


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    routed_task_type_counts = _routed_task_type_counts(results)
    collapse_warning = _router_collapse_warning(routed_task_type_counts, len(results))
    return {
        "task_count": float(len(results)),
        "mean_accuracy": _mean(result["accuracy"] for result in results),
        "mean_consistency": _mean(result["consistency"] for result in results),
        "mean_router_latency_ms": _mean(result["mean_router_latency_ms"] for result in results),
        "mean_baseline_prompt_tokens": _mean(
            result["baseline_prompt_tokens"] for result in results
        ),
        "mean_spatial_prompt_tokens": _mean(result["spatial_prompt_tokens"] for result in results),
        "mean_prompt_token_savings_percent": _mean(
            result["prompt_token_savings_percent"] for result in results
        ),
        "error_count": float(sum(len(result["errors"]) for result in results)),
        "role_by_task_type": _role_by_task_type(results),
        "routed_task_type_counts": routed_task_type_counts,
        "possible_router_collapse": bool(collapse_warning),
        "router_collapse_warning": collapse_warning,
    }


def _print_report(
    router_name: str,
    router_model: str | None,
    router_timeout_seconds: float | None,
    router_disable_thinking: bool,
    repeats: int,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    print("SFE Benchmark Report")
    print("====================")
    print(f"Router: {router_name}")
    print(f"Router model: {router_model}")
    print(f"Router timeout seconds: {router_timeout_seconds}")
    print(f"Router disable thinking: {router_disable_thinking}")
    print(f"Tasks: {int(summary['task_count'])}")
    print(f"Repeats: {repeats}")
    print(f"Mean task-type accuracy: {summary['mean_accuracy']:.2%}")
    print(f"Mean routing consistency: {summary['mean_consistency']:.2%}")
    print(f"Mean router latency: {summary['mean_router_latency_ms']:.2f} ms")
    print(f"Mean baseline prompt tokens: {summary['mean_baseline_prompt_tokens']:.2f}")
    print(f"Mean spatial prompt tokens: {summary['mean_spatial_prompt_tokens']:.2f}")
    print(f"Mean prompt token savings: {summary['mean_prompt_token_savings_percent']:.2f}%")
    print(f"Errors: {int(summary['error_count'])}")
    if summary["router_collapse_warning"]:
        print(f"WARNING: {summary['router_collapse_warning']}")
    print()
    print("Role handling by task_type:")
    for task_type, role_counts in summary["role_by_task_type"].items():
        roles = ", ".join(f"{role}={count}" for role, count in role_counts.items())
        print(f"- {task_type}: {roles}")
    print()
    print("Per-task results:")

    for result in results:
        actual = ", ".join(result["actual_task_types"]) or "error"
        roles = ", ".join(result["actual_roles"]) or "error"
        print(
            f"- {result['id']}: expected={result['expected_task_type']} actual={actual} "
            f"roles={roles} "
            f"accuracy={result['accuracy']:.0%} consistency={result['consistency']:.0%} "
            f"savings={result['prompt_token_savings_percent']:.2f}%"
        )


def _write_json(
    path: Path,
    router_name: str,
    router_model: str | None,
    router_timeout_seconds: float | None,
    router_disable_thinking: bool,
    repeats: int,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
) -> None:
    payload = {
        "router": router_name,
        "router_model": router_model,
        "router_timeout_seconds": router_timeout_seconds,
        "router_disable_thinking": router_disable_thinking,
        "repeats": repeats,
        "summary": summary,
        "results": results,
    }
    write_json_report(path, payload)


def _accuracy(actual_task_types: list[str], expected_task_type: str) -> float:
    if not actual_task_types:
        return 0.0
    matches = sum(1 for task_type in actual_task_types if task_type == expected_task_type)
    return matches / len(actual_task_types)


def _role_by_task_type(results: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    role_counts: dict[str, dict[str, int]] = {}
    for result in results:
        for observation in result["route_observations"]:
            task_type = observation["task_type"]
            role = observation["role"]
            role_counts.setdefault(task_type, {})
            role_counts[task_type][role] = role_counts[task_type].get(role, 0) + 1
    return {
        task_type: dict(sorted(counts.items()))
        for task_type, counts in sorted(role_counts.items())
    }


def _routed_task_type_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        for task_type in result["actual_task_types"]:
            counts[task_type] = counts.get(task_type, 0) + 1
    return dict(sorted(counts.items()))


def _router_collapse_warning(routed_task_type_counts: dict[str, int], task_count: int) -> str:
    total = sum(routed_task_type_counts.values())
    denominator = total or task_count
    if denominator == 0:
        return ""
    for task_type, count in routed_task_type_counts.items():
        if count / denominator > 0.70:
            return f"possible router collapse: {task_type} handled {count}/{denominator} routed tasks"
    return ""


def _consistency(values: list[str]) -> float:
    if not values:
        return 0.0
    most_common_count = max(values.count(value) for value in set(values))
    return most_common_count / len(values)


def _mean(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return statistics.fmean(values)


def _percentage(value: float, total: float) -> float:
    return percentage(value, total)


if __name__ == "__main__":
    main()
