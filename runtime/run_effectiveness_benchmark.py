"""Run baseline vs spatial execution effectiveness benchmarks for sfe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.codexcli import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_OPENAI_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_CODEXCLI_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_CODEXCLI_PROVIDER_NAME,
    CodexCLIProvider,
)
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_API_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_API_PROVIDER_NAME,
    OpenAIAPIProvider,
)
from providers.alibaba import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_ALIBABA_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_ALIBABA_ROUTER_MODEL,
    PROVIDER_NAME as ALIBABA_API_PROVIDER_NAME,
    AlibabaAPIProvider,
)
from providers.lemonade import DEFAULT_TIMEOUT, LemonadeProvider
from router.llm_router import (
    DEFAULT_ROUTER_MODEL,
    route_with_alibaba_api_diagnostics,
    route_with_codexcli_diagnostics,
    route_with_openai_api_diagnostics,
    route_with_llm_diagnostics,
    route_with_llm_raw_diagnostics,
)
from router.mock_router import route
from runtime.run_experiment import (
    DEFAULT_LEMONADE_BASE_URL,
    _build_execution_prompt,
    _extract_response_text,
    _extract_token_usage,
    _interference_score,
    _select_lemonade_executor_model,
    _spatial_context,
)
from runtime.metrics import estimate_text_tokens, percentage, write_json_report, write_text_report
from sfe.env import load_repo_env


DEFAULT_TASKS_PATH = PROJECT_ROOT / "benchmarks" / "tasks.json"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "effectiveness_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "effectiveness_benchmark.md"
QUALITY_PRESERVATION_RATIO = 0.95
TARGET_TOKEN_SAVINGS_PERCENT = 15.0


def main() -> None:
    load_repo_env()
    args = _parse_args()
    tasks = _load_tasks(args.tasks)

    if args.router in ("llm", "llm_raw") or args.executor == "lemonade":
        os.environ.setdefault("SFE_LEMONADE_BASE_URL", DEFAULT_LEMONADE_BASE_URL)

    report = _run_benchmark(
        tasks=tasks,
        tasks_path=args.tasks,
        executor_name=args.executor,
        executor_model=args.executor_model,
        router_name=args.router,
        repeat=args.repeat,
        max_tokens=args.max_tokens,
        timeout_seconds=args.timeout_seconds,
        router_model=args.router_model,
        router_timeout_seconds=args.router_timeout_seconds,
        router_disable_thinking=args.router_disable_thinking,
        strict=args.strict,
        debug_raw_response=args.debug_raw_response,
    )

    _write_json(args.json, report)
    _write_markdown(args.md, report)
    _print_console_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare baseline execution against sfe spatial execution."
    )
    parser.add_argument(
        "--executor",
        choices=(
            "mock",
            "lemonade",
            OPENAI_CODEXCLI_PROVIDER_NAME,
            OPENAI_API_PROVIDER_NAME,
            ALIBABA_API_PROVIDER_NAME,
        ),
        default="mock",
    )
    parser.add_argument(
        "--router",
        choices=(
            "mock",
            "llm",
            "llm_raw",
            OPENAI_CODEXCLI_PROVIDER_NAME,
            OPENAI_API_PROVIDER_NAME,
            ALIBABA_API_PROVIDER_NAME,
        ),
        default="mock",
    )
    parser.add_argument(
        "--executor-model",
        default=os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or DEFAULT_OPENAI_EXECUTOR_MODEL,
        help="Executor model for OpenAI/CodexCLI runs.",
    )
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    parser.add_argument("--repeat", "--repeats", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Lemonade executor timeout for both baseline and spatial runs.",
    )
    parser.add_argument(
        "--router-model",
        help=(
            "Model used by llm, llm_raw, and OpenAI/CodexCLI routers. Lemonade "
            f"defaults to SFE_ROUTER_MODEL or {DEFAULT_ROUTER_MODEL}; "
            f"{OPENAI_API_PROVIDER_NAME} defaults to {DEFAULT_OPENAI_API_ROUTER_MODEL}; "
            f"{OPENAI_CODEXCLI_PROVIDER_NAME} defaults to {DEFAULT_CODEXCLI_ROUTER_MODEL}; "
            f"{ALIBABA_API_PROVIDER_NAME} defaults to {DEFAULT_ALIBABA_ROUTER_MODEL}."
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
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exclude invalid spatial runs from effectiveness scoring while still counting failures.",
    )
    parser.add_argument("--debug-raw-response", action="store_true")
    return parser.parse_args()


def _load_tasks(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        loaded = json.load(file)

    if not isinstance(loaded, list):
        raise ValueError("Benchmark tasks file must contain a JSON list.")

    tasks = [_normalize_task(task) for task in loaded]

    ids = [task["id"] for task in tasks]
    duplicate_ids = sorted({task_id for task_id in ids if ids.count(task_id) > 1})
    if duplicate_ids:
        raise ValueError(f"Duplicate benchmark task id(s): {', '.join(duplicate_ids)}")

    return tasks


def _normalize_task(task: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(task, dict):
        raise ValueError("Each benchmark task must be a JSON object.")

    normalized = dict(task)
    if "prompt" not in normalized and "task" in normalized:
        normalized["prompt"] = normalized["task"]
    if "task_type_expected" not in normalized and "expected_task_type" in normalized:
        normalized["task_type_expected"] = normalized["expected_task_type"]

    required = {"id", "prompt", "task_type_expected"}
    missing = sorted(required - set(normalized))
    if missing:
        raise ValueError(f"Benchmark task is missing field(s): {', '.join(missing)}")

    normalized.setdefault("evaluation_criteria", [])
    normalized.setdefault("expected_constraints", {})
    normalized.setdefault("difficulty", "unknown")
    normalized.setdefault("requires_code", False)
    normalized.setdefault("requires_reasoning", False)
    normalized.setdefault("scoring_mode", "heuristic")
    return normalized


def _run_benchmark(
    tasks: list[dict[str, Any]],
    tasks_path: Path,
    executor_name: str,
    executor_model: str | None,
    router_name: str,
    repeat: int,
    max_tokens: int,
    timeout_seconds: float,
    router_model: str | None,
    router_timeout_seconds: float,
    router_disable_thinking: bool,
    strict: bool,
    debug_raw_response: bool,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than 0.")
    if router_timeout_seconds <= 0:
        raise ValueError("--router-timeout-seconds must be greater than 0.")

    effective_executor_model = _resolve_executor_model(executor_name, executor_model)
    effective_router_model = _resolve_router_model(router_name, router_model)
    effective_router_timeout_seconds = _resolve_router_timeout_seconds(
        router_name, router_timeout_seconds
    )
    effective_router_disable_thinking = _resolve_router_disable_thinking(
        router_name, router_disable_thinking
    )

    pairs = []
    for task in tasks:
        for repeat_index in range(1, repeat + 1):
            pairs.append(
                _run_pair(
                    task=task,
                    executor_name=executor_name,
                    executor_model=effective_executor_model,
                    router_name=router_name,
                    repeat_index=repeat_index,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                    router_model=effective_router_model,
                    router_timeout_seconds=effective_router_timeout_seconds,
                    router_disable_thinking=effective_router_disable_thinking,
                    debug_raw_response=debug_raw_response,
                )
            )

    summary = _summarize(pairs, strict)
    task_type_breakdown = _task_type_breakdown(pairs, strict)
    role_by_task_type = _role_by_task_type(pairs)
    successful_pairs_only = _successful_pairs_only_report(pairs)

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "executor": executor_name,
            "executor_model": effective_executor_model,
            "router": router_name,
            "router_model": effective_router_model,
            "router_timeout_seconds": effective_router_timeout_seconds,
            "router_disable_thinking": effective_router_disable_thinking,
            "timeout_seconds": timeout_seconds,
            "repeat": repeat,
            "strict": strict,
            "tasks_path": str(tasks_path),
            "task_count": len(tasks),
            "paired_run_count": len(pairs),
            "quality_preservation_ratio": QUALITY_PRESERVATION_RATIO,
            "target_token_savings_percent": TARGET_TOKEN_SAVINGS_PERCENT,
            "success_metric": (
                "SFE is effective if it preserves at least 95% of baseline quality "
                "while reducing total tokens by at least 15% across the mixed task set."
            ),
        },
        "summary": summary,
        "task_type_breakdown": task_type_breakdown,
        "role_by_task_type": role_by_task_type,
        "successful_pairs_only": successful_pairs_only,
        "pairs": pairs,
    }


def _run_pair(
    task: dict[str, Any],
    executor_name: str,
    executor_model: str | None,
    router_name: str,
    repeat_index: int,
    max_tokens: int,
    timeout_seconds: float,
    router_model: str | None,
    router_timeout_seconds: float | None,
    router_disable_thinking: bool,
    debug_raw_response: bool,
) -> dict[str, Any]:
    baseline_decision = _baseline_routing_decision(executor_name, executor_model)
    routing_started = time.perf_counter()
    spatial_decision, routing_info = _route_for_spatial(
        task["prompt"],
        router_name,
        router_model,
        executor_model,
        router_timeout_seconds,
        router_disable_thinking,
    )
    routing_latency_ms = int((time.perf_counter() - routing_started) * 1000)

    baseline = _execute_and_score(
        task=task,
        routing_decision=baseline_decision,
        mode="baseline",
        executor_name=executor_name,
        executor_model=executor_model,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        debug_raw_response=debug_raw_response,
    )

    routing_errors = routing_info.get("errors", [])
    if not spatial_decision:
        spatial = _failed_execution("; ".join(routing_errors) or "router returned no decision")
    else:
        spatial = _execute_and_score(
            task=task,
            routing_decision=spatial_decision,
            mode="spatial",
            executor_name=executor_name,
            executor_model=executor_model,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            debug_raw_response=debug_raw_response,
        )

    deltas = _compute_deltas(baseline, spatial, routing_latency_ms, spatial_decision)
    outcome = _classify_outcome(deltas, baseline, spatial)

    return {
        "task_id": task["id"],
        "task_type_expected": task["task_type_expected"],
        "routed_task_type": _routed_task_type(spatial_decision),
        "routing_correct": task["task_type_expected"] == _routed_task_type(spatial_decision),
        "difficulty": task["difficulty"],
        "requires_code": bool(task["requires_code"]),
        "requires_reasoning": bool(task["requires_reasoning"]),
        "scoring_mode": task["scoring_mode"],
        "repeat_index": repeat_index,
        "prompt": task["prompt"],
        "routing": {
            "router": router_name,
            "latency_ms": routing_latency_ms,
            "router_latency_ms": spatial_decision.get("router_latency_ms"),
            "router_input_tokens": spatial_decision.get("router_input_tokens"),
            "router_output_tokens": spatial_decision.get("router_output_tokens"),
            "router_total_tokens": spatial_decision.get("router_total_tokens"),
            "api_error_status": spatial_decision.get("api_error_status"),
            "api_error_type": spatial_decision.get("api_error_type"),
            "api_error_code": spatial_decision.get("api_error_code"),
            "api_error_message": spatial_decision.get("api_error_message"),
            "api_error_retry_count": spatial_decision.get("api_error_retry_count", 0),
            "api_error_attempts": spatial_decision.get("api_error_attempts", []),
            "decision": spatial_decision or None,
            "error": spatial_decision.get("router_error") or "; ".join(routing_errors),
            "success": bool(routing_info.get("success")),
            "json_valid": bool(routing_info.get("json_valid")),
            "used_fallback": bool(routing_info.get("used_fallback")),
            "real_routing_evaluated": _real_routing_evaluated(routing_info),
            "decision_source": routing_info.get("decision_source", ""),
            "attempt_count": int(routing_info.get("attempt_count", 0)),
            "diagnostics": routing_info,
        },
        **_pair_cost_fields(deltas),
        "baseline": baseline,
        "spatial": spatial,
        "deltas": deltas,
        "outcome": outcome,
    }


def _pair_cost_fields(deltas: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline_total_tokens": deltas["baseline_total_tokens"],
        "spatial_executor_total_tokens": deltas["spatial_executor_total_tokens"],
        "spatial_router_total_tokens": deltas["spatial_router_total_tokens"],
        "spatial_end_to_end_total_tokens": deltas["spatial_end_to_end_total_tokens"],
        "spatial_end_to_end_total_tokens_estimated": deltas[
            "spatial_end_to_end_total_tokens_estimated"
        ],
        "executor_only_token_delta": deltas["executor_only_token_delta"],
        "executor_only_token_savings_pct": deltas["executor_only_token_savings_pct"],
        "end_to_end_token_delta": deltas["end_to_end_token_delta"],
        "end_to_end_token_savings_pct": deltas["end_to_end_token_savings_pct"],
        "baseline_latency_ms": deltas["baseline_latency_ms"],
        "spatial_executor_latency_ms": deltas["spatial_executor_latency_ms"],
        "spatial_router_latency_ms": deltas["spatial_router_latency_ms"],
        "spatial_end_to_end_latency_ms": deltas["spatial_end_to_end_latency_ms"],
        "executor_only_latency_delta_ms": deltas["executor_only_latency_delta_ms"],
        "end_to_end_latency_delta_ms": deltas["end_to_end_latency_delta_ms"],
    }


def _baseline_routing_decision(
    executor_name: str = "lemonade",
    executor_model: str | None = None,
) -> dict[str, Any]:
    return {
        "task_type": "baseline",
        "role": "generalist",
        "provider": executor_name,
        "model": _baseline_model_for_executor(executor_name, executor_model),
        "memory_zones": [],
        "execution_mode": "direct",
        "max_input_tokens": 4000,
        "max_output_tokens": 1000,
        "requires_review": False,
        "confidence": 1.0,
        "rationale": "Baseline execution uses the general-purpose prompt.",
    }


def _resolve_router_model(router_name: str, router_model: str | None) -> str | None:
    if router_name == ALIBABA_API_PROVIDER_NAME:
        return router_model or os.getenv("SFE_ALIBABA_ROUTER_MODEL") or DEFAULT_ALIBABA_ROUTER_MODEL
    if router_name == OPENAI_API_PROVIDER_NAME:
        return router_model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_OPENAI_API_ROUTER_MODEL
    if router_name == OPENAI_CODEXCLI_PROVIDER_NAME:
        return router_model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_CODEXCLI_ROUTER_MODEL
    if router_name not in ("llm", "llm_raw"):
        return None
    return router_model or os.getenv("SFE_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL


def _resolve_executor_model(executor_name: str, executor_model: str | None) -> str | None:
    if executor_name == ALIBABA_API_PROVIDER_NAME:
        return (
            _alibaba_executor_model_or_none(executor_model)
            or os.getenv("SFE_ALIBABA_EXECUTOR_MODEL")
            or DEFAULT_ALIBABA_EXECUTOR_MODEL
        )
    if executor_name in (OPENAI_CODEXCLI_PROVIDER_NAME, OPENAI_API_PROVIDER_NAME):
        return executor_model or os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or DEFAULT_OPENAI_EXECUTOR_MODEL
    if executor_name == "lemonade":
        return _select_lemonade_executor_model()
    return None


def _baseline_model_for_executor(executor_name: str, executor_model: str | None) -> str:
    if executor_model:
        return executor_model
    if executor_name == "lemonade":
        return _select_lemonade_executor_model()
    if executor_name in (OPENAI_CODEXCLI_PROVIDER_NAME, OPENAI_API_PROVIDER_NAME):
        return DEFAULT_OPENAI_EXECUTOR_MODEL
    if executor_name == ALIBABA_API_PROVIDER_NAME:
        return DEFAULT_ALIBABA_EXECUTOR_MODEL
    return "mock-executor"


def _alibaba_executor_model_or_none(executor_model: str | None) -> str | None:
    if not executor_model or executor_model == DEFAULT_OPENAI_EXECUTOR_MODEL:
        return None
    return executor_model


def _resolve_router_timeout_seconds(
    router_name: str, router_timeout_seconds: float
) -> float | None:
    if router_name not in (
        "llm",
        "llm_raw",
        OPENAI_CODEXCLI_PROVIDER_NAME,
        OPENAI_API_PROVIDER_NAME,
        ALIBABA_API_PROVIDER_NAME,
    ):
        return None
    return router_timeout_seconds


def _resolve_router_disable_thinking(
    router_name: str, router_disable_thinking: bool
) -> bool:
    if router_name not in ("llm", "llm_raw"):
        return False
    return router_disable_thinking


def _route_for_spatial(
    prompt: str,
    router_name: str,
    router_model: str | None,
    executor_model: str | None,
    router_timeout_seconds: float | None,
    router_disable_thinking: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        if router_name == "llm":
            decision, diagnostics = route_with_llm_diagnostics(
                prompt,
                model=router_model,
                timeout_seconds=router_timeout_seconds,
                disable_thinking=router_disable_thinking,
            )
        elif router_name == "llm_raw":
            decision, diagnostics = route_with_llm_raw_diagnostics(
                prompt,
                model=router_model,
                timeout_seconds=router_timeout_seconds,
                disable_thinking=router_disable_thinking,
            )
        elif router_name == OPENAI_CODEXCLI_PROVIDER_NAME:
            decision, diagnostics = route_with_codexcli_diagnostics(
                prompt,
                router_model=router_model,
                executor_model=executor_model or DEFAULT_OPENAI_EXECUTOR_MODEL,
                timeout_seconds=router_timeout_seconds,
            )
        elif router_name == OPENAI_API_PROVIDER_NAME:
            decision, diagnostics = route_with_openai_api_diagnostics(
                prompt,
                router_model=router_model,
                executor_model=executor_model or DEFAULT_OPENAI_EXECUTOR_MODEL,
                timeout_seconds=router_timeout_seconds,
            )
        elif router_name == ALIBABA_API_PROVIDER_NAME:
            decision, diagnostics = route_with_alibaba_api_diagnostics(
                prompt,
                router_model=router_model,
                executor_model=executor_model or DEFAULT_ALIBABA_EXECUTOR_MODEL,
                timeout_seconds=router_timeout_seconds,
            )
        else:
            decision = route(prompt)
            diagnostics = {
                "router": "mock",
                "attempt_count": 1,
                "success": True,
                "json_valid": True,
                "used_fallback": False,
                "decision_source": "mock",
                "errors": [],
            }
        return decision, diagnostics
    except Exception as exc:
        return {}, {
            "router": router_name,
            "attempt_count": 1,
            "success": False,
            "json_valid": False,
            "used_fallback": False,
            "decision_source": "",
            "errors": [str(exc)],
        }


def _execute_and_score(
    task: dict[str, Any],
    routing_decision: dict[str, Any],
    mode: str,
    executor_name: str,
    executor_model: str | None,
    max_tokens: int,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict[str, Any]:
    execution = _execute(
        task=task,
        routing_decision=routing_decision,
        mode=mode,
        executor_name=executor_name,
        executor_model=executor_model,
        max_tokens=max_tokens,
        timeout_seconds=timeout_seconds,
        debug_raw_response=debug_raw_response,
    )
    scores = _score_output(task, execution["output"])
    interference_score, interference_hits = _interference_score(
        execution["output"], routing_decision
    )
    spatial_context = _spatial_context(routing_decision)
    success = execution["error"] == "" and bool(scores["success"])

    return {
        "mode": mode,
        "executor": executor_name,
        "model": execution["model"],
        "prompt_tokens": execution["prompt_tokens"],
        "completion_tokens": execution["completion_tokens"],
        "total_tokens": execution["total_tokens"],
        "token_usage_source": execution.get("token_usage_source", "unknown"),
        "token_usage_scientific": bool(execution.get("token_usage_scientific")),
        "api_error_status": execution.get("api_error_status"),
        "api_error_type": execution.get("api_error_type"),
        "api_error_code": execution.get("api_error_code"),
        "api_error_message": execution.get("api_error_message"),
        "api_error_retry_count": execution.get("api_error_retry_count", 0),
        "api_error_attempts": execution.get("api_error_attempts", []),
        "latency_ms": execution["latency_ms"],
        "success": success,
        "error": execution["error"],
        "output": execution["output"],
        "output_quality_score": scores["output_quality_score"],
        "constraint_following_score": scores["constraint_following_score"],
        "factuality_or_correctness_score": scores["factuality_or_correctness_score"],
        "interference_score": interference_score,
        "interference_hits": interference_hits,
        "zone_path": spatial_context["zone_path"],
        "score_checks": scores["checks"],
    }


def _execute(
    task: dict[str, Any],
    routing_decision: dict[str, Any],
    mode: str,
    executor_name: str,
    executor_model: str | None,
    max_tokens: int,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict[str, Any]:
    if executor_name == "lemonade":
        return _execute_with_lemonade(
            task=task,
            routing_decision=routing_decision,
            mode=mode,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            debug_raw_response=debug_raw_response,
        )
    if executor_name == OPENAI_CODEXCLI_PROVIDER_NAME:
        return _execute_with_codexcli(
            task=task,
            routing_decision=routing_decision,
            mode=mode,
            model=executor_model or DEFAULT_OPENAI_EXECUTOR_MODEL,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            debug_raw_response=debug_raw_response,
        )
    if executor_name == OPENAI_API_PROVIDER_NAME:
        return _execute_with_openai_api(
            task=task,
            routing_decision=routing_decision,
            mode=mode,
            model=executor_model or DEFAULT_OPENAI_EXECUTOR_MODEL,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            debug_raw_response=debug_raw_response,
        )
    if executor_name == ALIBABA_API_PROVIDER_NAME:
        return _execute_with_alibaba_api(
            task=task,
            routing_decision=routing_decision,
            mode=mode,
            model=executor_model or DEFAULT_ALIBABA_EXECUTOR_MODEL,
            max_tokens=max_tokens,
            timeout_seconds=timeout_seconds,
            debug_raw_response=debug_raw_response,
        )

    return _execute_with_mock(task, routing_decision, mode)


def _execute_with_mock(
    task: dict[str, Any],
    routing_decision: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    prompt = _build_execution_prompt(task["prompt"], routing_decision, mode)
    output = _mock_output(task)
    prompt_tokens = _estimate_tokens(prompt)
    completion_tokens = _estimate_tokens(output)
    latency_ms = _deterministic_latency_ms(task["id"], mode, prompt_tokens, completion_tokens)

    return {
        "model": "mock-executor",
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "token_usage_source": "deterministic_mock",
        "token_usage_scientific": True,
        "latency_ms": latency_ms,
        "output": output,
        "error": "",
    }


def _execute_with_lemonade(
    task: dict[str, Any],
    routing_decision: dict[str, Any],
    mode: str,
    max_tokens: int,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict[str, Any]:
    provider = LemonadeProvider()
    provider.timeout = timeout_seconds
    model = _select_lemonade_executor_model()
    prompt = _build_execution_prompt(task["prompt"], routing_decision, mode)

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens = _estimate_tokens(prompt)
        api_error = getattr(exc, "diagnostics", {})
        return {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 0,
            "total_tokens": prompt_tokens,
            "token_usage_source": "estimated_after_error",
            "token_usage_scientific": False,
            "api_error_status": api_error.get("api_error_status"),
            "api_error_type": api_error.get("api_error_type"),
            "api_error_code": api_error.get("api_error_code"),
            "api_error_message": api_error.get("api_error_message"),
            "api_error_retry_count": api_error.get("api_error_retry_count", 0),
            "api_error_attempts": api_error.get("api_error_attempts", []),
            "latency_ms": latency_ms,
            "output": "",
            "error": str(exc),
        }

    if debug_raw_response:
        print(json.dumps({"mode": mode, "task_id": task["id"], "raw_response": response}, indent=2))

    output = _extract_response_text(response)
    tokens = _extract_token_usage(response, prompt, output)

    return {
        "model": model,
        "prompt_tokens": int(tokens["input_tokens"]),
        "completion_tokens": int(tokens["output_tokens"]),
        "total_tokens": int(tokens["total_tokens"]),
        "token_usage_source": _provider_token_usage_source(response),
        "token_usage_scientific": _has_provider_token_usage(response),
        **_openai_api_metadata_for_report(response),
        "latency_ms": latency_ms,
        "output": output,
        "error": "" if output.strip() else "empty_executor_content",
    }


def _execute_with_codexcli(
    task: dict[str, Any],
    routing_decision: dict[str, Any],
    mode: str,
    model: str,
    max_tokens: int,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict[str, Any]:
    provider = CodexCLIProvider(timeout=timeout_seconds)
    prompt = _build_execution_prompt(task["prompt"], routing_decision, mode)

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens = _estimate_tokens(prompt)
        return {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 0,
            "total_tokens": prompt_tokens,
            "token_usage_source": "estimated_after_error",
            "token_usage_scientific": False,
            "latency_ms": latency_ms,
            "output": "",
            "error": str(exc),
        }

    if debug_raw_response:
        print(json.dumps({"mode": mode, "task_id": task["id"], "raw_response": response}, indent=2))

    output = _extract_response_text(response)
    tokens = _extract_token_usage(response, prompt, output)

    return {
        "model": model,
        "prompt_tokens": int(tokens["input_tokens"]),
        "completion_tokens": int(tokens["output_tokens"]),
        "total_tokens": int(tokens["total_tokens"]),
        "token_usage_source": _provider_token_usage_source(response),
        "token_usage_scientific": _has_provider_token_usage(response),
        "latency_ms": latency_ms,
        "output": output,
        "error": "" if output.strip() else "empty_executor_content",
    }


def _execute_with_openai_api(
    task: dict[str, Any],
    routing_decision: dict[str, Any],
    mode: str,
    model: str,
    max_tokens: int,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict[str, Any]:
    provider = OpenAIAPIProvider(timeout=timeout_seconds)
    prompt = _build_execution_prompt(task["prompt"], routing_decision, mode)

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens = _estimate_tokens(prompt)
        return {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 0,
            "total_tokens": prompt_tokens,
            "token_usage_source": "estimated_after_error",
            "token_usage_scientific": False,
            "latency_ms": latency_ms,
            "output": "",
            "error": str(exc),
        }

    if debug_raw_response:
        print(json.dumps({"mode": mode, "task_id": task["id"], "raw_response": response}, indent=2))

    output = _extract_response_text(response)
    tokens = _extract_token_usage(response, prompt, output)

    return {
        "model": model,
        "prompt_tokens": int(tokens["input_tokens"]),
        "completion_tokens": int(tokens["output_tokens"]),
        "total_tokens": int(tokens["total_tokens"]),
        "token_usage_source": _provider_token_usage_source(response),
        "token_usage_scientific": _has_provider_token_usage(response),
        "latency_ms": latency_ms,
        "output": output,
        "error": "" if output.strip() else "empty_executor_content",
    }


def _execute_with_alibaba_api(
    task: dict[str, Any],
    routing_decision: dict[str, Any],
    mode: str,
    model: str,
    max_tokens: int,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict[str, Any]:
    provider = AlibabaAPIProvider(timeout=timeout_seconds)
    prompt = _build_execution_prompt(task["prompt"], routing_decision, mode)

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=max_tokens,
            temperature=0.0,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        prompt_tokens = _estimate_tokens(prompt)
        api_error = getattr(exc, "diagnostics", {})
        return {
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 0,
            "total_tokens": prompt_tokens,
            "token_usage_source": "estimated_after_error",
            "token_usage_scientific": False,
            "api_error_status": api_error.get("api_error_status"),
            "api_error_type": api_error.get("api_error_type"),
            "api_error_code": api_error.get("api_error_code"),
            "api_error_message": api_error.get("api_error_message"),
            "api_error_retry_count": api_error.get("api_error_retry_count", 0),
            "api_error_attempts": api_error.get("api_error_attempts", []),
            "latency_ms": latency_ms,
            "output": "",
            "error": str(exc),
        }

    if debug_raw_response:
        print(json.dumps({"mode": mode, "task_id": task["id"], "raw_response": response}, indent=2))

    output = _extract_response_text(response)
    tokens = _extract_token_usage(response, prompt, output)

    return {
        "model": model,
        "prompt_tokens": int(tokens["input_tokens"]),
        "completion_tokens": int(tokens["output_tokens"]),
        "total_tokens": int(tokens["total_tokens"]),
        "token_usage_source": _provider_token_usage_source(response),
        "token_usage_scientific": _has_provider_token_usage(response),
        **_api_metadata_for_report(response, "alibaba_api"),
        "latency_ms": latency_ms,
        "output": output,
        "error": "" if output.strip() else "empty_executor_content",
    }


def _failed_execution(error: str) -> dict[str, Any]:
    return {
        "mode": "spatial",
        "executor": "",
        "model": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "token_usage_source": "not_available",
        "token_usage_scientific": False,
        "latency_ms": 0,
        "success": False,
        "error": error,
        "output": "",
        "output_quality_score": 0.0,
        "constraint_following_score": 0.0,
        "factuality_or_correctness_score": None,
        "interference_score": 0.0,
        "interference_hits": [],
        "zone_path": "",
        "score_checks": [{"name": "execution_error", "passed": False, "weight": 1.0}],
    }


def _has_provider_token_usage(response: dict[str, Any]) -> bool:
    usage = response.get("usage", {})
    return (
        isinstance(usage, dict)
        and usage.get("prompt_tokens") is not None
        and usage.get("completion_tokens") is not None
    )


def _provider_token_usage_source(response: dict[str, Any]) -> str:
    if _has_provider_token_usage(response):
        return "provider_reported"
    return "estimated_missing_provider_usage"


def _openai_api_metadata_for_report(response: dict[str, Any]) -> dict[str, Any]:
    return _api_metadata_for_report(response, "openai_api")


def _api_metadata_for_report(response: dict[str, Any], metadata_key: str) -> dict[str, Any]:
    metadata = response.get("openai_api", {})
    if metadata_key != "openai_api":
        metadata = response.get(metadata_key, {})
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "api_error_status": metadata.get("api_error_status"),
        "api_error_type": metadata.get("api_error_type"),
        "api_error_code": metadata.get("api_error_code"),
        "api_error_message": metadata.get("api_error_message"),
        "api_error_retry_count": int(metadata.get("api_error_retry_count") or 0),
        "api_error_attempts": metadata.get("api_error_attempts") or [],
    }


def _real_routing_evaluated(routing_info: dict[str, Any]) -> bool:
    return (
        bool(routing_info.get("success"))
        and bool(routing_info.get("json_valid"))
        and not bool(routing_info.get("used_fallback"))
    )


def _mock_output(task: dict[str, Any]) -> str:
    constraints = task["expected_constraints"]

    if constraints.get("requires_json"):
        payload = {
            "metric": "total_tokens",
            "target": "reduce by 15 percent",
            "rationale": "efficiency",
        }
        return json.dumps(payload, separators=(",", ":"))

    if constraints.get("requires_code_block"):
        if "run_count" in task["prompt"]:
            return (
                "Use a guard before dividing so run_count zero returns a safe average.\n\n"
                "```python\n"
                "def average_tokens(total_tokens, run_count):\n"
                "    if run_count == 0:\n"
                "        return 0\n"
                "    return total_tokens / run_count\n"
                "```"
            )

        return (
            "```python\n"
            "def validate_routing_decision(decision):\n"
            "    required = {\"task_type\", \"role\", \"provider\", \"model\", \"confidence\"}\n"
            "    if not isinstance(decision, dict):\n"
            "        return False\n"
            "    if not required.issubset(decision):\n"
            "        return False\n"
            "    confidence = decision[\"confidence\"]\n"
            "    return isinstance(confidence, (int, float)) and 0 <= confidence <= 1\n"
            "```"
        )

    numbered_items = constraints.get("expected_numbered_items")
    required_keywords = [str(keyword) for keyword in constraints.get("required_keywords", [])]
    if numbered_items:
        lines = []
        for index in range(1, int(numbered_items) + 1):
            keyword_text = ", ".join(required_keywords)
            lines.append(
                f"{index}. Milestone {index}: use {keyword_text} to make the experiment measurable and reportable."
            )
        return "\n".join(lines)

    keyword_text = ", ".join(required_keywords)
    if task["id"] == "writing_edit":
        return "The router selects the execution model and compacts the prompt for the task."

    return (
        f"This response addresses {keyword_text}. It keeps the answer concrete, explains the relevant "
        "tradeoff, names the next action, and avoids unsupported claims while staying concise."
    )


def _score_output(task: dict[str, Any], output: str) -> dict[str, Any]:
    constraints = task["expected_constraints"]
    checks: list[dict[str, Any]] = []

    _add_check(checks, "non_empty_output", bool(output.strip()), 2.0)
    _add_check(checks, "not_reasoning_metadata_only", not _is_reasoning_metadata_only(output), 1.0)
    _add_keyword_checks(checks, output, constraints.get("required_keywords", []))
    _add_forbidden_pattern_checks(checks, output, constraints.get("forbidden_patterns", []))
    _add_length_checks(checks, output, constraints)
    _add_format_checks(checks, output, constraints)

    output_quality_score = _weighted_score(checks)
    constraint_checks = [check for check in checks if check["name"] != "non_empty_output"]
    constraint_following_score = _weighted_score(constraint_checks)
    factuality_or_correctness_score = _factuality_score(task, output)

    return {
        "success": output_quality_score >= 0.65 and constraint_following_score >= 0.6,
        "output_quality_score": output_quality_score,
        "constraint_following_score": constraint_following_score,
        "factuality_or_correctness_score": factuality_or_correctness_score,
        "checks": checks,
    }


def _add_keyword_checks(checks: list[dict[str, Any]], output: str, keywords: list[str]) -> None:
    normalized = output.lower()
    for keyword in keywords:
        _add_check(
            checks,
            f"required_keyword:{keyword}",
            str(keyword).lower() in normalized,
            1.0,
        )


def _add_forbidden_pattern_checks(
    checks: list[dict[str, Any]], output: str, forbidden_patterns: list[str]
) -> None:
    for pattern in forbidden_patterns:
        _add_check(
            checks,
            f"forbidden_pattern_absent:{pattern}",
            not re.search(str(pattern), output, flags=re.IGNORECASE),
            1.0,
        )


def _add_length_checks(
    checks: list[dict[str, Any]], output: str, constraints: dict[str, Any]
) -> None:
    word_count = len(output.split())
    if "min_words" in constraints:
        _add_check(checks, "min_words", word_count >= int(constraints["min_words"]), 1.0)
    if "max_words" in constraints:
        _add_check(checks, "max_words", word_count <= int(constraints["max_words"]), 1.0)


def _add_format_checks(
    checks: list[dict[str, Any]], output: str, constraints: dict[str, Any]
) -> None:
    if constraints.get("requires_code_block"):
        _add_check(checks, "requires_code_block", "```" in output, 1.0)

    if constraints.get("requires_python_code"):
        _add_check(
            checks,
            "requires_python_code",
            "```python" in output.lower() or re.search(r"\bdef\s+\w+\(", output) is not None,
            1.0,
        )

    if constraints.get("requires_json"):
        parsed_json = _parse_json_output(output)
        _add_check(checks, "requires_json", parsed_json is not None, 2.0)
        for key in constraints.get("required_json_keys", []):
            _add_check(
                checks,
                f"required_json_key:{key}",
                isinstance(parsed_json, dict) and key in parsed_json,
                1.0,
            )

    if "expected_numbered_items" in constraints:
        expected = int(constraints["expected_numbered_items"])
        actual = len(re.findall(r"(?m)^\s*\d+[\.\)]\s+", output))
        _add_check(checks, "expected_numbered_items", actual == expected, 1.0)


def _factuality_score(task: dict[str, Any], output: str) -> float | None:
    constraints = task["expected_constraints"]

    if "exact_match" in constraints:
        return 1.0 if output.strip() == str(constraints["exact_match"]).strip() else 0.0

    factual_keywords = constraints.get("factual_keywords")
    if not factual_keywords:
        return None

    normalized = output.lower()
    matches = sum(1 for keyword in factual_keywords if str(keyword).lower() in normalized)
    return matches / len(factual_keywords)


def _add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    weight: float,
) -> None:
    checks.append({"name": name, "passed": bool(passed), "weight": float(weight)})


def _weighted_score(checks: list[dict[str, Any]]) -> float:
    if not checks:
        return 1.0

    total_weight = sum(check["weight"] for check in checks)
    if total_weight == 0:
        return 0.0

    passed_weight = sum(check["weight"] for check in checks if check["passed"])
    return passed_weight / total_weight


def _parse_json_output(output: str) -> Any:
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def _is_reasoning_metadata_only(output: str) -> bool:
    stripped = output.strip()
    if not stripped:
        return False

    lowered = stripped.lower()
    metadata_markers = ("analysis:", "reasoning:", "scratchpad:", "<think>", "thought:")
    if lowered.startswith(metadata_markers) and len(stripped.split()) < 20:
        return True

    visible = re.sub(r"(?is)<think>.*?</think>", "", stripped).strip()
    return bool(stripped) and not visible


def _compute_deltas(
    baseline: dict[str, Any],
    spatial: dict[str, Any],
    routing_latency_ms: int = 0,
    routing_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    routing_decision = routing_decision or {}
    token_usage_scientific = _scientific_token_usage_available(baseline, spatial)
    baseline_total_tokens = int(baseline["total_tokens"])
    spatial_executor_total_tokens = int(spatial["total_tokens"])
    spatial_router_total_tokens = _nullable_int(
        routing_decision.get("router_total_tokens")
    )
    raw_spatial_end_to_end_total_tokens = _nullable_sum(
        spatial_router_total_tokens, spatial_executor_total_tokens
    )
    spatial_end_to_end_total_tokens = (
        raw_spatial_end_to_end_total_tokens if token_usage_scientific else None
    )

    baseline_latency_ms = int(baseline["latency_ms"])
    spatial_executor_latency_ms = int(spatial["latency_ms"])
    spatial_router_latency_ms = _nullable_int(
        routing_decision.get("router_latency_ms")
    )
    if spatial_router_latency_ms is None:
        spatial_router_latency_ms = routing_latency_ms
    spatial_end_to_end_latency_ms = spatial_router_latency_ms + spatial_executor_latency_ms

    token_savings = (
        baseline_total_tokens - spatial_executor_total_tokens
        if token_usage_scientific
        else None
    )
    prompt_token_savings = (
        baseline["prompt_tokens"] - spatial["prompt_tokens"]
        if token_usage_scientific
        else None
    )
    completion_token_savings = (
        baseline["completion_tokens"] - spatial["completion_tokens"]
        if token_usage_scientific
        else None
    )
    end_to_end_token_delta = (
        _nullable_delta(baseline_total_tokens, spatial_end_to_end_total_tokens)
        if token_usage_scientific
        else None
    )
    quality_delta = spatial["output_quality_score"] - baseline["output_quality_score"]
    constraint_delta = spatial["constraint_following_score"] - baseline["constraint_following_score"]
    factuality_delta = _optional_delta(
        baseline["factuality_or_correctness_score"],
        spatial["factuality_or_correctness_score"],
    )

    return {
        "baseline_total_tokens": baseline_total_tokens,
        "spatial_executor_total_tokens": spatial_executor_total_tokens,
        "spatial_router_total_tokens": spatial_router_total_tokens,
        "spatial_end_to_end_total_tokens": spatial_end_to_end_total_tokens,
        "spatial_end_to_end_total_tokens_estimated": (
            raw_spatial_end_to_end_total_tokens if not token_usage_scientific else None
        ),
        "token_usage_scientific": token_usage_scientific,
        "executor_only_token_delta": (
            spatial_executor_total_tokens - baseline_total_tokens
            if token_usage_scientific
            else None
        ),
        "executor_only_token_savings_pct": (
            _percentage(token_savings, baseline_total_tokens)
            if token_savings is not None
            else None
        ),
        "end_to_end_token_delta": end_to_end_token_delta,
        "end_to_end_token_savings_pct": (
            _nullable_savings_pct(baseline_total_tokens, spatial_end_to_end_total_tokens)
            if token_usage_scientific
            else None
        ),
        "baseline_latency_ms": baseline_latency_ms,
        "spatial_executor_latency_ms": spatial_executor_latency_ms,
        "spatial_router_latency_ms": spatial_router_latency_ms,
        "spatial_end_to_end_latency_ms": spatial_end_to_end_latency_ms,
        "executor_only_latency_delta_ms": spatial_executor_latency_ms - baseline_latency_ms,
        "end_to_end_latency_delta_ms": spatial_end_to_end_latency_ms - baseline_latency_ms,
        "prompt_token_savings": prompt_token_savings,
        "prompt_token_savings_percent": (
            _percentage(prompt_token_savings, baseline["prompt_tokens"])
            if prompt_token_savings is not None
            else None
        ),
        "completion_token_savings": completion_token_savings,
        "completion_token_savings_percent": (
            _percentage(completion_token_savings, baseline["completion_tokens"])
            if completion_token_savings is not None
            else None
        ),
        "total_token_savings": token_savings,
        "total_token_savings_percent": (
            _percentage(token_savings, baseline["total_tokens"])
            if token_savings is not None
            else None
        ),
        "latency_delta_ms": spatial_executor_latency_ms - baseline_latency_ms,
        "quality_delta": quality_delta,
        "constraint_following_delta": constraint_delta,
        "factuality_or_correctness_delta": factuality_delta,
        "quality_preservation_ratio": _quality_ratio(
            baseline["output_quality_score"], spatial["output_quality_score"]
        ),
    }


def _classify_outcome(
    deltas: dict[str, Any],
    baseline: dict[str, Any],
    spatial: dict[str, Any],
) -> str:
    quality_preserved = deltas["quality_preservation_ratio"] >= QUALITY_PRESERVATION_RATIO
    token_savings = deltas["total_token_savings_percent"]

    if token_savings is None:
        return "loss" if not spatial["success"] or not quality_preserved else "tie"
    if spatial["success"] and quality_preserved and token_savings > 0:
        return "win"
    if not spatial["success"] or not quality_preserved or token_savings < 0:
        return "loss"
    if baseline["success"] == spatial["success"] and token_savings == 0:
        return "tie"
    return "tie"


def _summarize(pairs: list[dict[str, Any]], strict: bool) -> dict[str, Any]:
    scoring_pairs = _scoring_pairs(pairs, strict)
    token_savings_pairs = _token_savings_pairs(pairs)
    total_savings = [
        pair["deltas"]["executor_only_token_savings_pct"] for pair in token_savings_pairs
    ]
    end_to_end_savings = [
        pair["deltas"]["end_to_end_token_savings_pct"]
        for pair in token_savings_pairs
        if pair["deltas"]["end_to_end_token_savings_pct"] is not None
    ]
    quality_deltas = [pair["deltas"]["quality_delta"] for pair in scoring_pairs]
    latency_deltas = [
        pair["deltas"]["executor_only_latency_delta_ms"] for pair in scoring_pairs
    ]
    end_to_end_latency_deltas = [
        pair["deltas"]["end_to_end_latency_delta_ms"] for pair in scoring_pairs
    ]
    spatial_interference_scores = [
        pair["spatial"]["interference_score"] for pair in scoring_pairs
    ]
    outcomes = [pair["outcome"] for pair in pairs]
    quality_preserving_savings = [
        pair
        for pair in scoring_pairs
        if pair["deltas"]["quality_preservation_ratio"] >= QUALITY_PRESERVATION_RATIO
        and pair["spatial"]["success"]
        and pair["deltas"]["total_token_savings_percent"] is not None
        and pair["deltas"]["total_token_savings_percent"] >= TARGET_TOKEN_SAVINGS_PERCENT
    ]

    baseline_failures = sum(1 for pair in pairs if not pair["baseline"]["success"])
    spatial_failures = sum(1 for pair in pairs if not pair["spatial"]["success"])
    pair_count = len(pairs)
    scoring_count = len(scoring_pairs)
    router_metrics = _router_metrics(pairs)
    routed_task_type_counts = _routed_task_type_counts(pairs)
    router_collapse_warning = _router_collapse_warning(routed_task_type_counts, pair_count)

    mean_quality_ratio = _mean(
        pair["deltas"]["quality_preservation_ratio"] for pair in scoring_pairs
    )
    mean_token_savings = _mean_or_none(total_savings)
    effective = (
        scoring_count > 0
        and len(token_savings_pairs) > 0
        and mean_quality_ratio >= QUALITY_PRESERVATION_RATIO
        and mean_token_savings is not None
        and mean_token_savings >= TARGET_TOKEN_SAVINGS_PERCENT
    )

    return {
        "paired_run_count": pair_count,
        "scoring_paired_run_count": scoring_count,
        "token_savings_sample_count": len(token_savings_pairs),
        "strict": strict,
        "excluded_spatial_failure_count": spatial_failures if strict else 0,
        "router_success_rate": router_metrics["router_success_rate"],
        "json_valid_rate": router_metrics["json_valid_rate"],
        "fallback_rate": router_metrics["fallback_rate"],
        "routing_accuracy": _real_routing_accuracy(pairs),
        "real_routing_accuracy": _real_routing_accuracy(pairs),
        "real_routing_sample_count": len(_real_routing_pairs(pairs)),
        "fallback_assisted_routing_accuracy": _routing_accuracy(pairs),
        "fallback_assisted_routing_sample_count": len(pairs),
        "openai_api_failure_count": _openai_api_failure_count(pairs),
        "openai_api_retry_count": _openai_api_retry_count(pairs),
        "fallback_used_count": sum(1 for pair in pairs if pair["routing"].get("used_fallback")),
        "estimated_token_usage_count": _estimated_token_usage_count(pairs),
        "routed_task_type_counts": routed_task_type_counts,
        "possible_router_collapse": bool(router_collapse_warning),
        "router_collapse_warning": router_collapse_warning,
        "mean_total_token_savings_percent": mean_token_savings,
        "median_total_token_savings_percent": _median_or_none(total_savings),
        "mean_executor_only_token_savings_pct": mean_token_savings,
        "median_executor_only_token_savings_pct": _median_or_none(total_savings),
        "mean_end_to_end_token_savings_pct": _mean_or_none(end_to_end_savings),
        "median_end_to_end_token_savings_pct": _median_or_none(end_to_end_savings),
        "mean_prompt_token_savings_percent": _mean_or_none(
            pair["deltas"]["prompt_token_savings_percent"] for pair in token_savings_pairs
        ),
        "mean_completion_token_savings_percent": _mean_or_none(
            pair["deltas"]["completion_token_savings_percent"] for pair in token_savings_pairs
        ),
        "mean_quality_delta": _mean(quality_deltas),
        "mean_constraint_following_delta": _mean(
            pair["deltas"]["constraint_following_delta"] for pair in scoring_pairs
        ),
        "mean_spatial_interference_score": _mean(spatial_interference_scores),
        "mean_quality_preservation_ratio": mean_quality_ratio,
        "win_count": outcomes.count("win"),
        "loss_count": outcomes.count("loss"),
        "tie_count": outcomes.count("tie"),
        "quality_preserving_savings_rate": _ratio(
            len(quality_preserving_savings), scoring_count
        ),
        "baseline_failure_rate": _ratio(baseline_failures, pair_count),
        "spatial_failure_rate": _ratio(spatial_failures, pair_count),
        "mean_latency_delta_ms": _mean(latency_deltas),
        "median_latency_delta_ms": _median(latency_deltas),
        "mean_executor_only_latency_delta_ms": _mean(latency_deltas),
        "median_executor_only_latency_delta_ms": _median(latency_deltas),
        "mean_end_to_end_latency_delta_ms": _mean(end_to_end_latency_deltas),
        "median_end_to_end_latency_delta_ms": _median(end_to_end_latency_deltas),
        "effective": effective,
    }


def _task_type_breakdown(pairs: list[dict[str, Any]], strict: bool) -> dict[str, Any]:
    task_types = sorted({pair["task_type_expected"] for pair in pairs})
    breakdown = {}

    for task_type in task_types:
        subset = [pair for pair in pairs if pair["task_type_expected"] == task_type]
        scoring_subset = _scoring_pairs(subset, strict)
        token_savings_subset = _token_savings_pairs(subset)
        breakdown[task_type] = {
            "paired_run_count": len(subset),
            "scoring_paired_run_count": len(scoring_subset),
            "token_savings_sample_count": len(token_savings_subset),
            "role_counts": _role_counts(subset),
            "routing_accuracy": _routing_accuracy(subset),
            "real_routing_accuracy": _real_routing_accuracy(subset),
            "real_routing_sample_count": len(_real_routing_pairs(subset)),
            "mean_total_token_savings_percent": _mean_or_none(
                pair["deltas"]["executor_only_token_savings_pct"]
                for pair in token_savings_subset
            ),
            "median_total_token_savings_percent": _median_or_none(
                pair["deltas"]["executor_only_token_savings_pct"]
                for pair in token_savings_subset
            ),
            "mean_end_to_end_token_savings_pct": _mean_or_none(
                pair["deltas"]["end_to_end_token_savings_pct"]
                for pair in token_savings_subset
                if pair["deltas"]["end_to_end_token_savings_pct"] is not None
            ),
            "mean_quality_delta": _mean(
                pair["deltas"]["quality_delta"] for pair in scoring_subset
            ),
            "mean_spatial_interference_score": _mean(
                pair["spatial"]["interference_score"] for pair in scoring_subset
            ),
            "mean_quality_preservation_ratio": _mean(
                pair["deltas"]["quality_preservation_ratio"] for pair in scoring_subset
            ),
            "mean_latency_delta_ms": _mean(
                pair["deltas"]["executor_only_latency_delta_ms"]
                for pair in scoring_subset
            ),
            "mean_end_to_end_latency_delta_ms": _mean(
                pair["deltas"]["end_to_end_latency_delta_ms"]
                for pair in scoring_subset
            ),
            "win_count": sum(1 for pair in subset if pair["outcome"] == "win"),
            "loss_count": sum(1 for pair in subset if pair["outcome"] == "loss"),
            "tie_count": sum(1 for pair in subset if pair["outcome"] == "tie"),
        }

    return breakdown


def _successful_pairs_only_report(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    successful_pairs = [
        pair for pair in pairs if pair["baseline"]["success"] and pair["spatial"]["success"]
    ]
    return {
        "summary": _pair_subset_summary(successful_pairs),
        "task_type_breakdown": _successful_pair_task_type_breakdown(successful_pairs),
    }


def _pair_subset_summary(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [pair["outcome"] for pair in pairs]
    token_pairs = [pair for pair in pairs if pair["deltas"].get("token_usage_scientific")]
    quality_preserving_savings = [
        pair
        for pair in token_pairs
        if pair["deltas"]["quality_preservation_ratio"] >= QUALITY_PRESERVATION_RATIO
        and pair["deltas"]["executor_only_token_savings_pct"] is not None
        and pair["deltas"]["executor_only_token_savings_pct"] >= TARGET_TOKEN_SAVINGS_PERCENT
    ]

    return {
        "paired_run_count": len(pairs),
        "mean_total_token_savings_percent": _mean_or_none(
            pair["deltas"]["executor_only_token_savings_pct"] for pair in token_pairs
        ),
        "median_total_token_savings_percent": _median_or_none(
            pair["deltas"]["executor_only_token_savings_pct"] for pair in token_pairs
        ),
        "mean_end_to_end_token_savings_pct": _mean_or_none(
            pair["deltas"]["end_to_end_token_savings_pct"]
            for pair in token_pairs
            if pair["deltas"]["end_to_end_token_savings_pct"] is not None
        ),
        "mean_quality_delta": _mean(pair["deltas"]["quality_delta"] for pair in pairs),
        "quality_preserving_savings_rate": _ratio(
            len(quality_preserving_savings), len(pairs)
        ),
        "win_count": outcomes.count("win"),
        "loss_count": outcomes.count("loss"),
        "tie_count": outcomes.count("tie"),
    }


def _successful_pair_task_type_breakdown(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    task_types = sorted({pair["task_type_expected"] for pair in pairs})
    breakdown = {}

    for task_type in task_types:
        subset = [pair for pair in pairs if pair["task_type_expected"] == task_type]
        breakdown[task_type] = _pair_subset_summary(subset)

    return breakdown


def _scoring_pairs(pairs: list[dict[str, Any]], strict: bool) -> list[dict[str, Any]]:
    if not strict:
        return pairs
    return [pair for pair in pairs if pair["spatial"]["success"]]


def _token_savings_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        pair
        for pair in pairs
        if pair["baseline"]["success"]
        and pair["spatial"]["success"]
        and pair["deltas"].get("token_usage_scientific")
    ]


def _router_metrics(pairs: list[dict[str, Any]]) -> dict[str, float]:
    count = len(pairs)
    return {
        "router_success_rate": _ratio(
            sum(1 for pair in pairs if pair["routing"].get("success")), count
        ),
        "json_valid_rate": _ratio(
            sum(1 for pair in pairs if pair["routing"].get("json_valid")), count
        ),
        "fallback_rate": _ratio(
            sum(1 for pair in pairs if pair["routing"].get("used_fallback")), count
        ),
    }


def _real_routing_pairs(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [pair for pair in pairs if pair["routing"].get("real_routing_evaluated")]


def _real_routing_accuracy(pairs: list[dict[str, Any]]) -> float | None:
    real_pairs = _real_routing_pairs(pairs)
    if not real_pairs:
        return None
    return _routing_accuracy(real_pairs)


def _openai_api_failure_count(pairs: list[dict[str, Any]]) -> int:
    count = 0
    api_providers = {OPENAI_API_PROVIDER_NAME, ALIBABA_API_PROVIDER_NAME}
    for pair in pairs:
        if pair["routing"].get("router") in api_providers and pair["routing"].get("error"):
            count += 1
        count += len(pair["routing"].get("api_error_attempts") or [])
        if pair["baseline"].get("executor") in api_providers and pair["baseline"].get("error"):
            count += 1
        count += len(pair["baseline"].get("api_error_attempts") or [])
        if pair["spatial"].get("executor") in api_providers and pair["spatial"].get("error"):
            count += 1
        count += len(pair["spatial"].get("api_error_attempts") or [])
    return count


def _estimated_token_usage_count(pairs: list[dict[str, Any]]) -> int:
    count = 0
    for pair in pairs:
        for key in ("baseline", "spatial"):
            if not pair[key].get("token_usage_scientific"):
                count += 1
    return count


def _openai_api_retry_count(pairs: list[dict[str, Any]]) -> int:
    count = 0
    for pair in pairs:
        count += int(pair["routing"].get("api_error_retry_count") or 0)
        count += int(pair["baseline"].get("api_error_retry_count") or 0)
        count += int(pair["spatial"].get("api_error_retry_count") or 0)
    return count


def _scientific_token_usage_available(
    baseline: dict[str, Any], spatial: dict[str, Any]
) -> bool:
    return (
        bool(baseline.get("success"))
        and bool(spatial.get("success"))
        and bool(baseline.get("token_usage_scientific"))
        and bool(spatial.get("token_usage_scientific"))
    )


def _routed_task_type(decision: dict[str, Any]) -> str:
    return str((decision or {}).get("task_type") or "unrouted")


def _routing_accuracy(pairs: list[dict[str, Any]]) -> float:
    if not pairs:
        return 0.0
    matches = sum(
        1 for pair in pairs if pair["task_type_expected"] == pair["routed_task_type"]
    )
    return matches / len(pairs)


def _routed_task_type_counts(pairs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        task_type = pair["routed_task_type"]
        counts[task_type] = counts.get(task_type, 0) + 1
    return dict(sorted(counts.items()))


def _router_collapse_warning(routed_task_type_counts: dict[str, int], total: int) -> str:
    if total == 0:
        return ""
    for task_type, count in routed_task_type_counts.items():
        if count / total > 0.70:
            return f"possible router collapse: {task_type} handled {count}/{total} routed tasks"
    return ""


def _role_by_task_type(pairs: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    grouped: dict[str, dict[str, int]] = {}
    for pair in pairs:
        decision = pair["routing"].get("decision") or {}
        task_type = str(decision.get("task_type") or "unrouted")
        role = str(decision.get("role") or "unrouted")
        grouped.setdefault(task_type, {})
        grouped[task_type][role] = grouped[task_type].get(role, 0) + 1
    return {
        task_type: dict(sorted(role_counts.items()))
        for task_type, role_counts in sorted(grouped.items())
    }


def _role_counts(pairs: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for pair in pairs:
        decision = pair["routing"].get("decision") or {}
        role = str(decision.get("role") or "unrouted")
        counts[role] = counts.get(role, 0) + 1
    return dict(sorted(counts.items()))


def _format_role_counts(role_counts: dict[str, int]) -> str:
    if not role_counts:
        return ""
    return ", ".join(f"{role}={count}" for role, count in role_counts.items())


def _write_json(path: Path, report: dict[str, Any]) -> None:
    write_json_report(path, report)


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    write_text_report(path, _render_markdown(report))


def _render_markdown(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    summary = report["summary"]
    lines = [
        "# SFE Effectiveness Benchmark",
        "",
        f"- Generated at: `{metadata['generated_at']}`",
        f"- Executor: `{metadata['executor']}`",
        f"- Router: `{metadata['router']}`",
        f"- Router model: `{metadata['router_model']}`",
        f"- Router timeout seconds: `{metadata['router_timeout_seconds']}`",
        f"- Router disable thinking: `{metadata['router_disable_thinking']}`",
        f"- Timeout seconds: `{metadata['timeout_seconds']}`",
        f"- Repeat count: `{metadata['repeat']}`",
        f"- Strict scoring: `{metadata['strict']}`",
        f"- Success metric: {metadata['success_metric']}",
        f"- Effective: `{summary['effective']}`",
        "",
        "## Aggregate Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Paired runs | {summary['paired_run_count']} |",
        f"| Scoring paired runs | {summary['scoring_paired_run_count']} |",
        f"| Token-savings sample count | {summary['token_savings_sample_count']} |",
        f"| OpenAI API retry count | {summary.get('openai_api_retry_count', 0)} |",
        f"| Router success rate | {_format_ratio(summary['router_success_rate'])} |",
        f"| JSON valid rate | {_format_ratio(summary['json_valid_rate'])} |",
        f"| Fallback rate | {_format_ratio(summary['fallback_rate'])} |",
        f"| Real routing accuracy | {_format_ratio(summary['real_routing_accuracy'])} |",
        f"| Real routing sample count | {summary['real_routing_sample_count']} |",
        f"| Fallback-assisted routing accuracy | {_format_ratio(summary['fallback_assisted_routing_accuracy'])} |",
        f"| Mean quality delta | {summary['mean_quality_delta']:.3f} |",
        f"| Mean spatial interference score | {summary['mean_spatial_interference_score']:.3f} |",
        f"| Mean quality preservation ratio | {summary['mean_quality_preservation_ratio']:.3f} |",
        f"| Quality-preserving savings rate | {_format_ratio(summary['quality_preserving_savings_rate'])} |",
        f"| Baseline failure rate | {_format_ratio(summary['baseline_failure_rate'])} |",
        f"| Spatial failure rate | {_format_ratio(summary['spatial_failure_rate'])} |",
        f"| Wins / losses / ties | {summary['win_count']} / {summary['loss_count']} / {summary['tie_count']} |",
    ]

    if summary["router_collapse_warning"]:
        lines.extend(["", f"> Warning: {summary['router_collapse_warning']}"])

    report_warnings = _report_warnings(report)
    if report_warnings:
        lines.extend(["", "## Report Warnings", ""])
        lines.extend(f"> Warning: {warning}" for warning in report_warnings)

    if _uses_codexcli(metadata):
        lines.extend(
            [
                "",
                "> Note: CodexCLI appears to add a large fixed context overhead. "
                "Use this path for OpenAI integration validation and routing/execution "
                "behavior checks; treat token-cost comparisons as instrument-dependent.",
            ]
        )

    lines.extend(
        [
            "",
            "## Executor-Only Comparison",
            "",
            "This compares baseline executor tokens/latency against spatial executor tokens/latency only.",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Mean token savings | {_format_percent(summary['mean_executor_only_token_savings_pct'])} |",
            f"| Median token savings | {_format_percent(summary['median_executor_only_token_savings_pct'])} |",
            f"| Mean latency delta, spatial executor minus baseline | {summary['mean_executor_only_latency_delta_ms']:.2f} ms |",
            f"| Median latency delta, spatial executor minus baseline | {summary['median_executor_only_latency_delta_ms']:.2f} ms |",
            "",
            "## End-to-End Comparison",
            "",
            "This compares baseline executor cost against spatial router plus spatial executor cost.",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Mean token savings | {_format_percent(summary['mean_end_to_end_token_savings_pct'])} |",
            f"| Median token savings | {_format_percent(summary['median_end_to_end_token_savings_pct'])} |",
            f"| Mean latency delta, router plus spatial executor minus baseline | {summary['mean_end_to_end_latency_delta_ms']:.2f} ms |",
            f"| Median latency delta, router plus spatial executor minus baseline | {summary['median_end_to_end_latency_delta_ms']:.2f} ms |",
        ]
    )

    lines.extend(
        [
            "",
            "## Role Handling",
            "",
            "| Routed task type | Roles |",
            "| --- | --- |",
        ]
    )

    for task_type, role_counts in report["role_by_task_type"].items():
        lines.append(f"| `{task_type}` | {_format_role_counts(role_counts)} |")

    lines.extend(
        [
        "",
        "## Task-Type Breakdown",
        "",
        "| Task type | Runs | Roles | Real routing accuracy | Real routing sample | Savings sample | Executor-only token savings | End-to-end token savings | Mean quality delta | Mean interference | Executor-only latency delta | End-to-end latency delta | W/L/T |",
        "| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for task_type, data in report["task_type_breakdown"].items():
        lines.append(
            f"| `{task_type}` | {data['paired_run_count']} | "
            f"{_format_role_counts(data['role_counts'])} | "
            f"{_format_ratio(data['real_routing_accuracy'])} | "
            f"{data['real_routing_sample_count']} | "
            f"{data['token_savings_sample_count']} | "
            f"{_format_percent(data['mean_total_token_savings_percent'])} | "
            f"{_format_percent(data['mean_end_to_end_token_savings_pct'])} | "
            f"{data['mean_quality_delta']:.3f} | "
            f"{data['mean_spatial_interference_score']:.3f} | "
            f"{data['mean_latency_delta_ms']:.2f} ms | "
            f"{data['mean_end_to_end_latency_delta_ms']:.2f} ms | "
            f"{data['win_count']}/{data['loss_count']}/{data['tie_count']} |"
        )

    successful = report["successful_pairs_only"]
    successful_summary = successful["summary"]
    lines.extend(
        [
            "",
            "## Successful Pairs Only",
            "",
            "Pairs where both `baseline.success` and `spatial.success` are true.",
            "",
            "| Metric | Value |",
            "| --- | ---: |",
            f"| Paired count | {successful_summary['paired_run_count']} |",
            f"| Mean executor-only token savings | {_format_percent(successful_summary['mean_total_token_savings_percent'])} |",
            f"| Median executor-only token savings | {_format_percent(successful_summary['median_total_token_savings_percent'])} |",
            f"| Mean end-to-end token savings | {_format_percent(successful_summary['mean_end_to_end_token_savings_pct'])} |",
            f"| Mean quality delta | {successful_summary['mean_quality_delta']:.3f} |",
            f"| Quality-preserving savings rate | {_format_ratio(successful_summary['quality_preserving_savings_rate'])} |",
            f"| Wins / losses / ties | {successful_summary['win_count']} / {successful_summary['loss_count']} / {successful_summary['tie_count']} |",
            "",
            "### Successful Pairs By Task Type",
            "",
            "| Task type | Paired count | Mean token savings | Median token savings | Mean quality delta | Quality-preserving savings rate | W/L/T |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for task_type, data in successful["task_type_breakdown"].items():
        lines.append(
            f"| `{task_type}` | {data['paired_run_count']} | "
            f"{_format_percent(data['mean_total_token_savings_percent'])} | "
            f"{_format_percent(data['median_total_token_savings_percent'])} | "
            f"{data['mean_quality_delta']:.3f} | "
            f"{_format_ratio(data['quality_preserving_savings_rate'])} | "
            f"{data['win_count']}/{data['loss_count']}/{data['tie_count']} |"
        )

    lines.extend(
        [
            "",
            "## Per-Task Means",
            "",
            "| Task | Type | Runs | Executor-only token savings | End-to-end token savings | Mean quality delta | Mean constraint delta | W/L/T |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )

    for task_id, task_pairs in _pairs_by_task(report["pairs"]).items():
        strict = bool(summary["strict"])
        scoring_pairs = _scoring_pairs(task_pairs, strict)
        token_savings_pairs = _token_savings_pairs(task_pairs)
        lines.append(
            f"| `{task_id}` | `{task_pairs[0]['task_type_expected']}` | {len(task_pairs)} | "
            f"{_format_percent(_mean_or_none(pair['deltas']['executor_only_token_savings_pct'] for pair in token_savings_pairs))} | "
            f"{_format_percent(_mean_or_none(pair['deltas']['end_to_end_token_savings_pct'] for pair in token_savings_pairs if pair['deltas']['end_to_end_token_savings_pct'] is not None))} | "
            f"{_mean(pair['deltas']['quality_delta'] for pair in scoring_pairs):.3f} | "
            f"{_mean(pair['deltas']['constraint_following_delta'] for pair in scoring_pairs):.3f} | "
            f"{sum(1 for pair in task_pairs if pair['outcome'] == 'win')}/"
            f"{sum(1 for pair in task_pairs if pair['outcome'] == 'loss')}/"
            f"{sum(1 for pair in task_pairs if pair['outcome'] == 'tie')} |"
        )

    lines.append("")
    return "\n".join(lines)


def _print_console_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("SFE Effectiveness Benchmark")
    print("===========================")
    print(f"Executor: {report['metadata']['executor']}")
    print(f"Router: {report['metadata']['router']}")
    print(f"Router model: {report['metadata']['router_model']}")
    print(f"Router timeout seconds: {report['metadata']['router_timeout_seconds']}")
    print(f"Router disable thinking: {report['metadata']['router_disable_thinking']}")
    print(f"Timeout seconds: {report['metadata']['timeout_seconds']}")
    print(f"Paired runs: {summary['paired_run_count']}")
    print(f"Scoring paired runs: {summary['scoring_paired_run_count']}")
    print(f"Token-savings sample count: {summary['token_savings_sample_count']}")
    print(f"OpenAI API retry count: {summary.get('openai_api_retry_count', 0)}")
    print(f"Router success rate: {summary['router_success_rate']:.2%}")
    print(f"JSON valid rate: {summary['json_valid_rate']:.2%}")
    print(f"Fallback rate: {summary['fallback_rate']:.2%}")
    print(f"Real routing accuracy: {_format_ratio(summary['real_routing_accuracy'])}")
    print(
        "Fallback-assisted routing accuracy: "
        f"{_format_ratio(summary['fallback_assisted_routing_accuracy'])}"
    )
    for warning in _report_warnings(report):
        print(f"WARNING: {warning}")
    if summary["router_collapse_warning"]:
        print(f"WARNING: {summary['router_collapse_warning']}")
    print("Role handling by routed task_type:")
    for task_type, role_counts in report["role_by_task_type"].items():
        print(f"- {task_type}: {_format_role_counts(role_counts)}")
    if _uses_codexcli(report["metadata"]):
        print(
            "NOTE: CodexCLI appears to add a large fixed context overhead; "
            "treat token-cost comparisons as instrument-dependent."
        )
    print(
        "Mean executor-only token savings: "
        f"{_format_percent(summary['mean_executor_only_token_savings_pct'])}"
    )
    print(
        "Median executor-only token savings: "
        f"{_format_percent(summary['median_executor_only_token_savings_pct'])}"
    )
    print(
        "Mean end-to-end token savings: "
        f"{_format_percent(summary['mean_end_to_end_token_savings_pct'])}"
    )
    print(f"Mean quality delta: {summary['mean_quality_delta']:.3f}")
    print(f"Mean spatial interference score: {summary['mean_spatial_interference_score']:.3f}")
    print(f"Quality-preserving savings rate: {summary['quality_preserving_savings_rate']:.2%}")
    print(f"Wins/losses/ties: {summary['win_count']}/{summary['loss_count']}/{summary['tie_count']}")
    print(
        "Mean executor-only latency delta, spatial minus baseline: "
        f"{summary['mean_executor_only_latency_delta_ms']:.2f} ms"
    )
    print(
        "Mean end-to-end latency delta, spatial minus baseline: "
        f"{summary['mean_end_to_end_latency_delta_ms']:.2f} ms"
    )
    successful_summary = report["successful_pairs_only"]["summary"]
    print("Successful pairs only:")
    print(f"- paired count: {successful_summary['paired_run_count']}")
    print(
        "- mean/median executor-only token savings: "
        f"{_format_percent(successful_summary['mean_total_token_savings_percent'])}/"
        f"{_format_percent(successful_summary['median_total_token_savings_percent'])}"
    )
    print(
        "- mean end-to-end token savings: "
        f"{_format_percent(successful_summary['mean_end_to_end_token_savings_pct'])}"
    )
    print(
        "- wins/losses/ties: "
        f"{successful_summary['win_count']}/"
        f"{successful_summary['loss_count']}/"
        f"{successful_summary['tie_count']}"
    )
    print(f"Effective by target metric: {summary['effective']}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {md_path}")


def _pairs_by_task(pairs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        grouped.setdefault(pair["task_id"], []).append(pair)
    return grouped


def _estimate_tokens(text: str) -> int:
    return estimate_text_tokens(text)


def _deterministic_latency_ms(
    task_id: str,
    mode: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> int:
    seed = int(hashlib.sha256(f"{task_id}:{mode}".encode("utf-8")).hexdigest()[:8], 16)
    jitter = seed % 17
    return int(50 + (prompt_tokens + completion_tokens) * 0.35 + jitter)


def _percentage(value: float, total: float) -> float:
    return percentage(value, total)


def _quality_ratio(baseline_quality: float, spatial_quality: float) -> float:
    if baseline_quality == 0:
        return 1.0 if spatial_quality == 0 else 0.0
    return spatial_quality / baseline_quality


def _optional_delta(baseline_value: float | None, spatial_value: float | None) -> float | None:
    if baseline_value is None or spatial_value is None:
        return None
    return spatial_value - baseline_value


def _nullable_delta(baseline_value: int, spatial_value: int | None) -> int | None:
    if spatial_value is None:
        return None
    return spatial_value - baseline_value


def _nullable_sum(first: int | None, second: int | None) -> int | None:
    if first is None or second is None:
        return None
    return first + second


def _nullable_savings_pct(baseline_value: int, spatial_value: int | None) -> float | None:
    if spatial_value is None:
        return None
    return _percentage(baseline_value - spatial_value, baseline_value)


def _nullable_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _mean(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return statistics.fmean(values)


def _median(values) -> float:
    values = list(values)
    if not values:
        return 0.0
    return float(statistics.median(values))


def _mean_or_none(values) -> float | None:
    values = list(values)
    if not values:
        return None
    return statistics.fmean(values)


def _median_or_none(values) -> float | None:
    values = list(values)
    if not values:
        return None
    return float(statistics.median(values))


def _ratio(value: int, total: int) -> float:
    if total == 0:
        return 0.0
    return value / total


def _format_percent(value: float) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_ratio(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _report_warnings(report: dict[str, Any]) -> list[str]:
    summary = report["summary"]
    warnings = []
    if int(summary.get("openai_api_failure_count") or 0) > 0:
        warnings.append(
            "At least one OpenAI API call failed; this report is not a valid scientific benchmark result."
        )
        for marker in _openai_api_error_markers(report):
            warnings.append(f"OpenAI API error marker: {marker}.")
    if int(summary.get("fallback_used_count") or 0) > 0:
        warnings.append(
            "Fallback routing was used; fallback-assisted routing accuracy is reported separately from real router accuracy."
        )
    if int(summary.get("estimated_token_usage_count") or 0) > 0:
        warnings.append(
            "Some token fields are estimates rather than provider-reported usage; token savings are n/a unless both paired executor calls have scientific token usage."
        )
    return warnings


def _openai_api_error_markers(report: dict[str, Any]) -> list[str]:
    markers = []
    for pair in report.get("pairs", []):
        for error in (
            pair.get("routing", {}).get("error", ""),
            pair.get("baseline", {}).get("error", ""),
            pair.get("spatial", {}).get("error", ""),
            pair.get("routing", {}).get("api_error_type", ""),
            pair.get("baseline", {}).get("api_error_type", ""),
            pair.get("spatial", {}).get("api_error_type", ""),
            pair.get("routing", {}).get("api_error_code", ""),
            pair.get("baseline", {}).get("api_error_code", ""),
            pair.get("spatial", {}).get("api_error_code", ""),
        ):
            if "insufficient_quota" in str(error) and "insufficient_quota" not in markers:
                markers.append("insufficient_quota")
            if (
                "unsupported temperature parameter" in str(error).lower()
                and "unsupported temperature parameter" not in markers
            ):
                markers.append("unsupported temperature parameter")
            if "rate_limit" in str(error) and "rate_limit" not in markers:
                markers.append("rate_limit")
    return markers


def _uses_codexcli(metadata: dict[str, Any]) -> bool:
    return (
        metadata.get("executor") == OPENAI_CODEXCLI_PROVIDER_NAME
        or metadata.get("router") == OPENAI_CODEXCLI_PROVIDER_NAME
    )


if __name__ == "__main__":
    main()
