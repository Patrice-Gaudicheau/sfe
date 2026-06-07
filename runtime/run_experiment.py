"""Minimal mock experiment runner for sfe."""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from router.llm_router import (
    route_with_alibaba_api,
    route_with_codexcli,
    route_with_google,
    route_with_llm,
    route_with_openai_api,
)
from router.mock_router import route
from providers.codexcli import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_OPENAI_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_CODEXCLI_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_CODEXCLI_PROVIDER_NAME,
    CodexCLIProvider,
)
from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_OPENAI_API_EXECUTOR_MODEL,
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
from providers.google import (
    DEFAULT_MODEL as DEFAULT_GOOGLE_MODEL,
    PROVIDER_NAME as GOOGLE_API_PROVIDER_NAME,
    GoogleAPIProvider,
)
from providers.lemonade import LemonadeProvider
from runtime.logger import log_run
from runtime.metrics import estimated_token_usage
from sfe.env import load_repo_env


TASK = "Write a short technical plan for testing the spatial field engine."
MIXED_TASKS = [
    ("writing_short", "Write a concise project update about the spatial field engine experiment."),
    (
        "writing_long",
        "Write a detailed technical plan for evaluating spatial routing across local LLM providers, including setup, metrics, risks, and reporting.",
    ),
    ("coding_simple", "Write a Python function that validates a routing decision dictionary."),
    (
        "coding_debug",
        "Fix this Python bug: a function divides total_tokens by run_count, but run_count can be zero. Explain the minimal code change.",
    ),
    (
        "analysis",
        "Compare baseline prompting and spatial prompting as experimental methods for reducing token usage in local LLM systems.",
    ),
    (
        "multi_context",
        "Explain how token savings, cognitive routing, software architecture, and experiment reporting relate in sfe.",
    ),
]
DEFAULT_EXECUTION_MODEL = "Qwen3.5-35B-A3B-GGUF"
DEFAULT_LEMONADE_BASE_URL = "http://127.0.0.1:13305"
ZONE_BY_TASK_TYPE = {
    "writing": "writing",
    "coding": "coding",
    "analysis": "analysis",
    "planning": "planning",
    "review": "analysis",
    "multi_context": "architect",
}
ALL_ZONES = ("writing", "coding", "analysis", "planning", "architect")
ALLOWED_OPERATIONS_BY_ZONE = {
    "writing": ("draft_or_rewrite_text", "preserve_style_constraints", "produce_final_copy"),
    "coding": ("write_or_fix_code", "validate_logic", "include_code_when_requested"),
    "analysis": ("compare_evaluate_explain", "identify_tradeoffs", "check_correctness"),
    "planning": ("produce_requested_plan", "preserve_requested_format", "define_success_criteria"),
    "architect": ("integrate_multiple_domains", "coordinate_outputs", "preserve_report_format"),
}
FORBIDDEN_OPERATIONS_BY_ZONE = {
    "writing": ("write_code", "debug_code", "expand_into_plan", "route_task"),
    "coding": ("draft_marketing_copy", "produce_strategy_plan", "route_task"),
    "analysis": ("write_code", "draft_prose", "produce_roadmap", "route_task"),
    "planning": ("write_code", "debug_code", "draft_prose", "route_task"),
    "architect": ("route_task", "ignore_output_domains"),
}
FORBIDDEN_OPERATION_PATTERNS = {
    "write_code": (r"\bdef\s+\w+\(", r"```(?:python|js|javascript|ts|typescript)?", r"\bclass\s+\w+"),
    "debug_code": (r"\btraceback\b", r"\bstack trace\b", r"\bdebugger\b"),
    "expand_into_plan": (r"\broadmap\b", r"\bmilestone\b", r"\bphase\s+\d+\b"),
    "route_task": (r"\btask_type\b", r"\brouting decision\b", r"\bactive_zone\b"),
    "draft_marketing_copy": (r"\btagline\b", r"\bcall to action\b", r"\bmarketing\b"),
    "produce_strategy_plan": (r"\bstrategy\b", r"\broadmap\b", r"\bmilestone\b"),
    "draft_prose": (r"\brewrite\b", r"\bparagraph\b", r"\bsentence\b"),
    "produce_roadmap": (r"\broadmap\b", r"\bmilestone\b", r"\bphase\s+\d+\b"),
    "ignore_output_domains": (r"\bignore\b.*\bdomain",),
}


def main() -> None:
    load_repo_env()
    args = _parse_args()
    router_name = args.router
    executor_name = args.executor
    _configure_lemonade_base_url(router_name, executor_name)
    task_type_distribution: Counter[str] = Counter()

    for task_label, task in _select_tasks(args):
        routing_decision = _route_task(
            task,
            router_name,
            router_model=args.router_model,
            executor_model=args.executor_model,
            timeout_seconds=args.timeout_seconds,
        )

        for mode in ("baseline", "spatial"):
            execution = _execute_task(
                task,
                task_label,
                routing_decision,
                mode,
                router_name,
                executor_name,
                args.executor_model,
                args.timeout_seconds,
                args.debug_raw_response,
            )
            run_data = execution["run_data"]
            run_id = log_run(run_data)
            task_type_distribution[run_data["task_type"]] += 1

            print(f"task label: {task_label}")
            print(f"task: {task}")
            print(f"router: {router_name}")
            print(f"executor: {executor_name}")
            print(f"router model: {_router_model_for_display(routing_decision)}")
            print(f"executor model: {execution['executor_model']}")
            print(f"routing decision: {routing_decision}")
            print(f"response text: {execution['response_text']}")
            if execution["error_marker"]:
                print(f"error marker: {execution['error_marker']}")
            print(f"tokens: {execution['tokens']}")
            print(f"latency_ms: {execution['latency_ms']}")
            print(f"run_id: {run_id}")

    print(f"router task_type distribution: {dict(task_type_distribution)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a minimal sfe experiment simulation.")
    parser.add_argument(
        "--router",
        choices=(
            "mock",
            "llm",
            OPENAI_CODEXCLI_PROVIDER_NAME,
            OPENAI_API_PROVIDER_NAME,
            ALIBABA_API_PROVIDER_NAME,
            GOOGLE_API_PROVIDER_NAME,
        ),
        default="mock",
    )
    parser.add_argument(
        "--executor",
        choices=(
            "mock",
            "lemonade",
            OPENAI_CODEXCLI_PROVIDER_NAME,
            OPENAI_API_PROVIDER_NAME,
            ALIBABA_API_PROVIDER_NAME,
            GOOGLE_API_PROVIDER_NAME,
        ),
        default="mock",
    )
    parser.add_argument(
        "--router-model",
        default=None,
        help=(
            "Router model for provider backends. Defaults by backend env/default: "
            f"{OPENAI_API_PROVIDER_NAME}={DEFAULT_OPENAI_API_ROUTER_MODEL}, "
            f"{OPENAI_CODEXCLI_PROVIDER_NAME}={DEFAULT_CODEXCLI_ROUTER_MODEL}, "
            f"{ALIBABA_API_PROVIDER_NAME}={DEFAULT_ALIBABA_ROUTER_MODEL}, "
            f"{GOOGLE_API_PROVIDER_NAME}={DEFAULT_GOOGLE_MODEL}."
        ),
    )
    parser.add_argument(
        "--executor-model",
        default=None,
        help="Executor model for provider runs. Defaults to the provider-specific env var.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=300,
        help="Transport safeguard for direct API provider calls.",
    )
    parser.add_argument("--task")
    parser.add_argument("--task-set", choices=("basic", "mixed"), default="basic")
    parser.add_argument("--debug-raw-response", action="store_true")
    return parser.parse_args()


def _select_tasks(args: argparse.Namespace) -> list[tuple[str, str]]:
    if args.task:
        return [("custom", args.task)]

    if args.task_set == "mixed":
        return MIXED_TASKS

    return [("basic", TASK)]


def _route_task(
    task: str,
    router_name: str,
    router_model: str | None = None,
    executor_model: str | None = None,
    timeout_seconds: float | None = None,
) -> dict:
    if router_name == "llm":
        return route_with_llm(task)
    if router_name == OPENAI_CODEXCLI_PROVIDER_NAME:
        return route_with_codexcli(
            task,
            router_model=router_model,
            executor_model=executor_model,
            timeout_seconds=timeout_seconds,
        )
    if router_name == OPENAI_API_PROVIDER_NAME:
        return route_with_openai_api(
            task,
            router_model=router_model,
            executor_model=executor_model,
            timeout_seconds=timeout_seconds,
        )
    if router_name == ALIBABA_API_PROVIDER_NAME:
        return route_with_alibaba_api(
            task,
            router_model=router_model,
            executor_model=_alibaba_executor_model_or_none(executor_model),
            timeout_seconds=timeout_seconds,
        )
    if router_name == GOOGLE_API_PROVIDER_NAME:
        return route_with_google(
            task,
            router_model=router_model,
            executor_model=_google_model_or_none(executor_model),
            timeout_seconds=timeout_seconds,
        )
    return route(task)


def _configure_lemonade_base_url(router_name: str, executor_name: str) -> None:
    if router_name == "llm" or executor_name == "lemonade":
        os.environ.setdefault("SFE_LEMONADE_BASE_URL", DEFAULT_LEMONADE_BASE_URL)


def _execute_task(
    task: str,
    task_label: str,
    routing_decision: dict,
    mode: str,
    router_name: str,
    executor_name: str,
    executor_model: str,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict:
    if executor_name == "lemonade":
        return _execute_with_lemonade(
            task,
            task_label,
            routing_decision,
            mode,
            router_name,
            executor_name,
            debug_raw_response,
        )
    if executor_name == OPENAI_CODEXCLI_PROVIDER_NAME:
        return _execute_with_codexcli(
            task,
            task_label,
            routing_decision,
            mode,
            router_name,
            executor_name,
            executor_model,
            timeout_seconds,
            debug_raw_response,
        )
    if executor_name == OPENAI_API_PROVIDER_NAME:
        return _execute_with_openai_api(
            task,
            task_label,
            routing_decision,
            mode,
            router_name,
            executor_name,
            executor_model,
            timeout_seconds,
            debug_raw_response,
        )
    if executor_name == ALIBABA_API_PROVIDER_NAME:
        return _execute_with_alibaba_api(
            task,
            task_label,
            routing_decision,
            mode,
            router_name,
            executor_name,
            executor_model,
            timeout_seconds,
            debug_raw_response,
        )
    if executor_name == GOOGLE_API_PROVIDER_NAME:
        return _execute_with_google(
            task,
            task_label,
            routing_decision,
            mode,
            router_name,
            executor_name,
            executor_model,
            timeout_seconds,
            debug_raw_response,
        )
    return _simulate_run(task, task_label, routing_decision, mode, router_name, executor_name)


def _simulate_run(
    task: str,
    task_label: str,
    routing_decision: dict,
    mode: str,
    router_name: str,
    executor_name: str,
) -> dict:
    prompt = _build_execution_prompt(task, routing_decision, mode)
    prompt_style = _prompt_style(mode, routing_decision)
    zone_path = _zone_path(routing_decision["task_type"])
    input_tokens = estimated_token_usage(prompt, "")["input_tokens"]
    output_tokens = random.randint(50, 150)
    total_tokens = input_tokens + output_tokens
    latency_ms = random.randint(200, 1000)

    return {
        "executor_model": routing_decision["model"],
        "error_marker": "",
        "response_text": "mock execution response",
        "tokens": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
        },
        "latency_ms": latency_ms,
        "run_data": {
            "task_type": routing_decision["task_type"],
            "mode": mode,
            "provider": routing_decision["provider"],
            "model": routing_decision["model"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "latency_ms": latency_ms,
            "success": True,
            "router": router_name,
            "executor": executor_name,
            "router_model": routing_decision.get("router_model") or routing_decision.get("model"),
            "executor_model": routing_decision["model"],
            **_router_metrics_for_log(routing_decision),
            "prompt_style": prompt_style,
            "task_label": task_label,
            "error": "",
            "zone_path": zone_path,
            "notes": _build_notes(router_name, executor_name, prompt_style, task_label, zone_path=zone_path),
        },
    }


def _execute_with_lemonade(
    task: str,
    task_label: str,
    routing_decision: dict,
    mode: str,
    router_name: str,
    executor_name: str,
    debug_raw_response: bool,
) -> dict:
    provider = LemonadeProvider()
    model = _select_lemonade_executor_model()
    prompt = _build_execution_prompt(task, routing_decision, mode)
    prompt_style = _prompt_style(mode, routing_decision)
    zone_path = _zone_path(routing_decision["task_type"])

    started = time.perf_counter()
    response = provider.chat(
        [{"role": "user", "content": prompt}],
        model=model,
        max_tokens=96,
        temperature=0.2,
    )
    latency_ms = int((time.perf_counter() - started) * 1000)

    if debug_raw_response:
        print(f"raw response diagnostics: {_raw_response_diagnostics(response)}")

    response_text = _extract_response_text(response)
    tokens = _extract_token_usage(response, prompt, response_text)
    error_marker = _executor_error_marker(response_text)

    return {
        "executor_model": model,
        "error_marker": error_marker,
        "response_text": response_text,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "run_data": {
            "task_type": routing_decision["task_type"],
            "mode": mode,
            "provider": "lemonade",
            "model": model,
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "total_tokens": tokens["total_tokens"],
            "latency_ms": latency_ms,
            "success": not error_marker,
            "router": router_name,
            "executor": executor_name,
            "router_model": routing_decision.get("router_model") or routing_decision.get("model"),
            "executor_model": model,
            **_router_metrics_for_log(routing_decision),
            "prompt_style": prompt_style,
            "task_label": task_label,
            "error": error_marker,
            "zone_path": zone_path,
            "notes": _build_notes(
                router_name,
                executor_name,
                prompt_style,
                task_label,
                error_marker,
                zone_path=zone_path,
            ),
        },
    }


def _execute_with_codexcli(
    task: str,
    task_label: str,
    routing_decision: dict,
    mode: str,
    router_name: str,
    executor_name: str,
    executor_model: str,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict:
    provider = CodexCLIProvider(timeout=timeout_seconds)
    model = (
        executor_model
        or os.getenv("SFE_CODEXCLI_EXECUTOR_MODEL")
        or DEFAULT_OPENAI_EXECUTOR_MODEL
    )
    prompt = _build_execution_prompt(task, routing_decision, mode)
    prompt_style = _prompt_style(mode, routing_decision)
    zone_path = _zone_path(routing_decision["task_type"])
    response: dict = {}
    response_text = ""
    latency_ms = 0
    error_marker = ""

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=160,
            temperature=0.2,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = _extract_response_text(response)
        error_marker = _executor_error_marker(response_text)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        error_marker = str(exc)

    if debug_raw_response:
        print(f"raw response diagnostics: {_raw_response_diagnostics(response)}")

    tokens = _extract_token_usage(response, prompt, response_text)
    openai_metadata = response.get("openai_api", {})
    if not isinstance(openai_metadata, dict):
        openai_metadata = {}

    return {
        "executor_model": model,
        "error_marker": error_marker,
        "response_text": response_text,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "run_data": {
            "task_type": routing_decision["task_type"],
            "mode": mode,
            "provider": OPENAI_CODEXCLI_PROVIDER_NAME,
            "model": model,
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "total_tokens": tokens["total_tokens"],
            "latency_ms": latency_ms,
            "success": not error_marker,
            "router": router_name,
            "executor": executor_name,
            "router_model": routing_decision.get("router_model") or _default_router_model_for_backend(executor_name),
            "executor_model": model,
            "api_error_status": openai_metadata.get("api_error_status"),
            "api_error_type": openai_metadata.get("api_error_type"),
            "api_error_code": openai_metadata.get("api_error_code"),
            "api_error_message": openai_metadata.get("api_error_message"),
            "api_error_retry_count": int(openai_metadata.get("api_error_retry_count") or 0),
            "api_error_attempts": openai_metadata.get("api_error_attempts") or [],
            **_router_metrics_for_log(routing_decision),
            "prompt_style": prompt_style,
            "task_label": task_label,
            "error": error_marker,
            "zone_path": zone_path,
            "notes": _build_notes(
                router_name,
                executor_name,
                prompt_style,
                task_label,
                error_marker,
                zone_path=zone_path,
            ),
        },
    }


def _execute_with_openai_api(
    task: str,
    task_label: str,
    routing_decision: dict,
    mode: str,
    router_name: str,
    executor_name: str,
    executor_model: str,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict:
    provider = OpenAIAPIProvider(timeout=timeout_seconds)
    model = (
        executor_model
        or os.getenv("SFE_OPENAI_EXECUTOR_MODEL")
        or DEFAULT_OPENAI_EXECUTOR_MODEL
    )
    prompt = _build_execution_prompt(task, routing_decision, mode)
    prompt_style = _prompt_style(mode, routing_decision)
    zone_path = _zone_path(routing_decision["task_type"])
    response: dict = {}
    response_text = ""
    latency_ms = 0
    error_marker = ""

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=160,
            temperature=0.2,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = _extract_response_text(response)
        error_marker = _executor_error_marker(response_text)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        error_marker = str(exc)

    if debug_raw_response:
        print(f"raw response diagnostics: {_raw_response_diagnostics(response)}")

    tokens = _extract_token_usage(response, prompt, response_text)

    return {
        "executor_model": model,
        "error_marker": error_marker,
        "response_text": response_text,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "run_data": {
            "task_type": routing_decision["task_type"],
            "mode": mode,
            "provider": OPENAI_API_PROVIDER_NAME,
            "model": model,
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "total_tokens": tokens["total_tokens"],
            "latency_ms": latency_ms,
            "success": not error_marker,
            "router": router_name,
            "executor": executor_name,
            "router_model": routing_decision.get("router_model") or _default_router_model_for_backend(executor_name),
            "executor_model": model,
            **_router_metrics_for_log(routing_decision),
            "prompt_style": prompt_style,
            "task_label": task_label,
            "error": error_marker,
            "zone_path": zone_path,
            "notes": _build_notes(
                router_name,
                executor_name,
                prompt_style,
                task_label,
                error_marker,
                zone_path=zone_path,
            ),
        },
    }


def _execute_with_alibaba_api(
    task: str,
    task_label: str,
    routing_decision: dict,
    mode: str,
    router_name: str,
    executor_name: str,
    executor_model: str,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict:
    provider = AlibabaAPIProvider(timeout=timeout_seconds)
    model = (
        _alibaba_executor_model_or_none(executor_model)
        or os.getenv("SFE_ALIBABA_EXECUTOR_MODEL")
        or DEFAULT_ALIBABA_EXECUTOR_MODEL
    )
    prompt = _build_execution_prompt(task, routing_decision, mode)
    prompt_style = _prompt_style(mode, routing_decision)
    zone_path = _zone_path(routing_decision["task_type"])
    response: dict = {}
    response_text = ""
    latency_ms = 0
    error_marker = ""

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=160,
            temperature=0.2,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = _extract_response_text(response)
        error_marker = _executor_error_marker(response_text)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        error_marker = str(exc)

    if debug_raw_response:
        print(f"raw response diagnostics: {_raw_response_diagnostics(response)}")

    tokens = _extract_token_usage(response, prompt, response_text)

    return {
        "executor_model": model,
        "error_marker": error_marker,
        "response_text": response_text,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "run_data": {
            "task_type": routing_decision["task_type"],
            "mode": mode,
            "provider": ALIBABA_API_PROVIDER_NAME,
            "model": model,
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "total_tokens": tokens["total_tokens"],
            "latency_ms": latency_ms,
            "success": not error_marker,
            "router": router_name,
            "executor": executor_name,
            "router_model": routing_decision.get("router_model") or _default_router_model_for_backend(executor_name),
            "executor_model": model,
            **_router_metrics_for_log(routing_decision),
            "prompt_style": prompt_style,
            "task_label": task_label,
            "error": error_marker,
            "zone_path": zone_path,
            "notes": _build_notes(
                router_name,
                executor_name,
                prompt_style,
                task_label,
                error_marker,
                zone_path=zone_path,
            ),
        },
    }


def _execute_with_google(
    task: str,
    task_label: str,
    routing_decision: dict,
    mode: str,
    router_name: str,
    executor_name: str,
    executor_model: str,
    timeout_seconds: float,
    debug_raw_response: bool,
) -> dict:
    provider = GoogleAPIProvider(timeout=timeout_seconds)
    model = _google_model_or_none(executor_model) or os.getenv("SFE_GOOGLE_MODEL") or DEFAULT_GOOGLE_MODEL
    prompt = _build_execution_prompt(task, routing_decision, mode)
    prompt_style = _prompt_style(mode, routing_decision)
    zone_path = _zone_path(routing_decision["task_type"])
    response: dict = {}
    response_text = ""
    latency_ms = 0
    error_marker = ""

    started = time.perf_counter()
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=160,
            temperature=0.2,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        response_text = _extract_response_text(response)
        error_marker = _executor_error_marker(response_text)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        error_marker = str(exc)

    if debug_raw_response:
        print(f"raw response diagnostics: {_raw_response_diagnostics(response)}")

    tokens = _extract_token_usage(response, prompt, response_text)

    return {
        "executor_model": model,
        "error_marker": error_marker,
        "response_text": response_text,
        "tokens": tokens,
        "latency_ms": latency_ms,
        "run_data": {
            "task_type": routing_decision["task_type"],
            "mode": mode,
            "provider": GOOGLE_API_PROVIDER_NAME,
            "model": model,
            "input_tokens": tokens["input_tokens"],
            "output_tokens": tokens["output_tokens"],
            "total_tokens": tokens["total_tokens"],
            "latency_ms": latency_ms,
            "success": not error_marker,
            "router": router_name,
            "executor": executor_name,
            "router_model": routing_decision.get("router_model") or _default_router_model_for_backend(executor_name),
            "executor_model": model,
            **_router_metrics_for_log(routing_decision),
            "prompt_style": prompt_style,
            "task_label": task_label,
            "error": error_marker,
            "zone_path": zone_path,
            "notes": _build_notes(
                router_name,
                executor_name,
                prompt_style,
                task_label,
                error_marker,
                zone_path=zone_path,
            ),
        },
    }


def _select_lemonade_executor_model() -> str:
    return os.getenv("SFE_EXECUTOR_MODEL") or DEFAULT_EXECUTION_MODEL


def _alibaba_executor_model_or_none(executor_model: str | None) -> str | None:
    if not executor_model or _is_openai_executor_model(executor_model):
        return None
    return executor_model


def _google_model_or_none(model: str | None) -> str | None:
    if not model or _is_openai_executor_model(model):
        return None
    return model


def _is_openai_executor_model(model: str) -> bool:
    return model in {
        DEFAULT_OPENAI_EXECUTOR_MODEL,
        DEFAULT_OPENAI_API_EXECUTOR_MODEL,
    }


def _router_model_for_display(routing_decision: dict) -> str:
    return str(routing_decision.get("router_model") or routing_decision.get("model") or "")


def _default_router_model_for_backend(backend_name: str) -> str:
    if backend_name == ALIBABA_API_PROVIDER_NAME:
        return DEFAULT_ALIBABA_ROUTER_MODEL
    if backend_name == GOOGLE_API_PROVIDER_NAME:
        return DEFAULT_GOOGLE_MODEL
    if backend_name == OPENAI_API_PROVIDER_NAME:
        return DEFAULT_OPENAI_API_ROUTER_MODEL
    return DEFAULT_CODEXCLI_ROUTER_MODEL


def _router_metrics_for_log(routing_decision: dict) -> dict:
    return {
        "router_latency_ms": routing_decision.get("router_latency_ms"),
        "router_input_tokens": routing_decision.get("router_input_tokens"),
        "router_output_tokens": routing_decision.get("router_output_tokens"),
        "router_total_tokens": routing_decision.get("router_total_tokens"),
        "router_error": routing_decision.get("router_error"),
        "router_api_error_status": routing_decision.get("api_error_status"),
        "router_api_error_type": routing_decision.get("api_error_type"),
        "router_api_error_code": routing_decision.get("api_error_code"),
        "router_api_error_message": routing_decision.get("api_error_message"),
        "router_api_error_retry_count": routing_decision.get("api_error_retry_count", 0),
    }


def _build_execution_prompt(task: str, routing_decision: dict, mode: str) -> str:
    answer_only = (
        "/no_think\n"
        "Output a visible final answer in message.content. Hidden reasoning is not useful unless it is followed "
        "by a visible final answer. Do not output analysis, reasoning, thoughts, scratchpad, chain-of-thought, "
        "thinking traces, or step-by-step deliberation. Answer directly in the final response. Keep the answer "
        "concise unless the task requires detail."
    )

    if mode == "baseline":
        return (
            f"{answer_only}\n\n"
            "You are a general-purpose assistant. Analyze the task carefully and produce a complete answer. "
            "Consider relevant context, constraints, implementation implications, evaluation criteria, and any "
            "important caveats before responding. Provide a clear, useful, and self-contained response.\n\n"
            f"Task: {task}"
        )

    if routing_decision["task_type"] == "planning":
        return _build_planning_spatial_prompt(task, routing_decision)

    return (
        f"{answer_only}\n\n"
        f"Role: {routing_decision['role']}\n"
        f"Task type: {routing_decision['task_type']}\n"
        f"{_build_spatial_context_block(routing_decision)}\n"
        f"Task: {task}\n"
        "Produce only the final answer."
    )


def _build_planning_spatial_prompt(task: str, routing_decision: dict) -> str:
    numbered_list_instruction = _numbered_list_instruction(task)
    output_instruction = numbered_list_instruction or "Return only the requested plan."

    return (
        "/no_think\n"
        f"Role: {routing_decision['role']}\n"
        "Task type: planning\n"
        f"{_build_spatial_context_block(routing_decision)}\n"
        "Preserve objective, constraints, requested format, and success criteria.\n"
        "No extra sections unless requested.\n"
        f"Task: {task}\n"
        f"{output_instruction}"
    )


def _build_spatial_context_block(routing_decision: dict) -> str:
    context = _spatial_context(routing_decision)
    return (
        "SPATIAL CONTEXT:\n"
        f"active_zone: {context['active_zone']}\n"
        f"memory_zones: {_format_list(context['memory_zones'])}\n"
        f"suppressed_zones: {_format_list(context['suppressed_zones'])}\n"
        f"allowed_operations: {_format_list(context['allowed_operations'])}\n"
        f"forbidden_operations: {_format_list(context['forbidden_operations'])}"
    )


def _spatial_context(routing_decision: dict) -> dict:
    task_type = str(routing_decision.get("task_type", "multi_context"))
    active_zone = _active_zone(task_type)
    memory_zones = [
        str(zone)
        for zone in routing_decision.get("memory_zones", [])
        if str(zone).strip()
    ]
    active_and_memory_zones = {active_zone, *memory_zones}
    suppressed_zones = [
        zone for zone in ALL_ZONES if zone not in active_and_memory_zones
    ]

    return {
        "active_zone": active_zone,
        "memory_zones": memory_zones,
        "suppressed_zones": suppressed_zones,
        "allowed_operations": list(ALLOWED_OPERATIONS_BY_ZONE[active_zone]),
        "forbidden_operations": list(FORBIDDEN_OPERATIONS_BY_ZONE[active_zone]),
        "zone_path": _zone_path(task_type),
    }


def _active_zone(task_type: str) -> str:
    return ZONE_BY_TASK_TYPE.get(task_type, "architect")


def _zone_path(task_type: str) -> str:
    return f"sfe/{_active_zone(task_type)}"


def _format_list(values: list[str] | tuple[str, ...]) -> str:
    if not values:
        return "none"
    return ", ".join(values)


def _interference_score(output: str, routing_decision: dict) -> tuple[float, list[str]]:
    context = _spatial_context(routing_decision)
    hits = []
    for operation in context["forbidden_operations"]:
        patterns = FORBIDDEN_OPERATION_PATTERNS.get(operation, ())
        if any(re.search(pattern, output, flags=re.IGNORECASE) for pattern in patterns):
            hits.append(operation)

    forbidden_count = len(context["forbidden_operations"])
    if forbidden_count == 0:
        return 0.0, hits
    return len(hits) / forbidden_count, hits


def _numbered_list_instruction(task: str) -> str:
    count = _requested_item_count(task)
    if count is None:
        return ""
    return f"Return only a numbered list with exactly {count} items."


def _requested_item_count(task: str) -> int | None:
    normalized = task.lower()
    word_numbers = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }

    numeric_match = re.search(r"\b(?:exactly|next)\s+(\d+)\s+(?:items?|milestones?|steps?)\b", normalized)
    if numeric_match:
        return int(numeric_match.group(1))

    word_match = re.search(
        r"\b(?:exactly|next)\s+("
        + "|".join(word_numbers)
        + r")\s+(?:items?|milestones?|steps?)\b",
        normalized,
    )
    if word_match:
        return word_numbers[word_match.group(1)]

    return None


def _prompt_style(mode: str, routing_decision: dict | None = None) -> str:
    if mode == "baseline":
        return "baseline_direct"
    if routing_decision and routing_decision.get("task_type") == "planning":
        return "spatial_planning"
    return "spatial_compact"


def _executor_error_marker(response_text: str) -> str:
    if response_text.strip():
        return ""
    return "empty_executor_content"


def _build_notes(
    router_name: str,
    executor_name: str,
    prompt_style: str,
    task_label: str,
    error_marker: str = "",
    zone_path: str = "",
) -> str:
    notes = f"run; router={router_name}; executor={executor_name}; prompt_style={prompt_style}; task={task_label}"
    if zone_path:
        notes = f"{notes}; zone_path={zone_path}"
    if error_marker:
        notes = f"{notes}; error={error_marker}"
    return notes


def _extract_response_text(response: dict) -> str:
    choices = response.get("choices", [])
    if not choices or not isinstance(choices[0], dict):
        return ""

    first_choice = choices[0]
    message = first_choice.get("message", {})

    if isinstance(message, dict) and message.get("content") is not None:
        content = str(message["content"]).strip()
        if content:
            return content

    if first_choice.get("text") is not None:
        return str(first_choice["text"]).strip()

    return ""


def _raw_response_diagnostics(response: dict) -> dict:
    choices = response.get("choices", [])
    first_choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = first_choice.get("message", {})
    if not isinstance(message, dict):
        message = {}

    content = message.get("content")
    reasoning_content = message.get("reasoning_content")

    return {
        "finish_reason": first_choice.get("finish_reason"),
        "message_keys": sorted(message.keys()),
        "content_exists": content is not None,
        "content_length": len(str(content or "")),
        "reasoning_content_exists": reasoning_content is not None,
        "reasoning_content_length": len(str(reasoning_content or "")),
    }


def _extract_token_usage(response: dict, prompt: str, response_text: str) -> dict:
    usage = response.get("usage", {})
    if isinstance(usage, dict):
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")

        if prompt_tokens is not None and completion_tokens is not None:
            input_tokens = int(prompt_tokens)
            output_tokens = int(completion_tokens)
            if total_tokens is None:
                total_tokens = input_tokens + output_tokens

            return {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": int(total_tokens),
            }

    return estimated_token_usage(prompt, response_text)


if __name__ == "__main__":
    main()
