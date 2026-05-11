"""Run OpenAI selector plus deterministic executor for the large benchmark.

This runner uses OpenAI only for source selection. The executor is deterministic
and validates whether the OpenAI-selected sources are sufficient for the
existing large real-world benchmark answer contract.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import (
    DEFAULT_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_API_PROVIDER,
    MissingOpenAIAPIKeyError,
    OpenAIAPIProvider,
)
from runtime.metrics import percent_reduction, write_json_report, write_text_report
from runtime.run_large_real_world_multi_zone_benchmark import (
    LargeRealWorldTask,
    compose_context,
    get_large_real_world_tasks,
    validate_output,
)
from runtime.run_large_real_world_openai_selector_smoke import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    OPENAI_SELECTOR_API_PATH,
    SelectorConfig,
    SelectorProvider,
    _extract_latency_ms,
    _extract_response_text,
    _extract_usage,
    _format_optional_float,
    _format_optional_percent,
    _format_percent,
    _full_context_tokens,
    _safe_error_message,
    _selected_context_tokens,
    build_selector_prompt,
    parse_selector_output,
    validate_selection as validate_selector_selection,
)
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/large_real_world_openai_selector_deterministic_executor"
BENCHMARK_NAME = "large_real_world_openai_selector_deterministic_executor"
DEFAULT_JSON_PATH = (
    PROJECT_ROOT / "logs" / "large_real_world_openai_selector_deterministic_executor.json"
)
DEFAULT_MD_PATH = (
    PROJECT_ROOT / "logs" / "large_real_world_openai_selector_deterministic_executor.md"
)


def main() -> None:
    args = _parse_args()
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL
    timeout = args.timeout
    if timeout is None and os.getenv("SFE_OPENAI_API_TIMEOUT"):
        timeout = float(os.environ["SFE_OPENAI_API_TIMEOUT"])
    provider = OpenAIAPIProvider(timeout=timeout)
    if not provider.health()["ok"]:
        raise MissingOpenAIAPIKeyError(provider.health()["error"])
    report = run_benchmark(
        tasks=get_large_real_world_tasks(),
        provider=provider,
        config=SelectorConfig(
            model=model,
            timeout=timeout,
            max_output_tokens=args.max_output_tokens,
        ),
    )
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run OpenAI selector plus deterministic executor over the large "
            "real-world benchmark."
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
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def run_benchmark(
    *,
    tasks: list[LargeRealWorldTask],
    provider: SelectorProvider,
    config: SelectorConfig,
) -> dict[str, Any]:
    if not tasks:
        raise ValueError("At least one large real-world task is required.")
    if not config.model:
        raise ValueError("OpenAI selector model is required.")
    if config.max_output_tokens < 1:
        raise ValueError("max_output_tokens must be at least 1.")

    runs = [
        execute_selector_deterministic_executor(task=task, provider=provider, config=config)
        for task in tasks
    ]
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "provider": OPENAI_API_PROVIDER,
            "api_path": OPENAI_SELECTOR_API_PATH,
            "router_model": config.model,
            "fixture_count": len(tasks),
            "max_output_tokens": config.max_output_tokens,
            "timeout": config.timeout,
            "selector_scope": "openai_source_selection",
            "executor": "deterministic_selected_source_executor",
            "repair_status": "not_supported",
            "fallback_policy": "no oracle fallback; fallback counts as failure",
        },
        "summary": summarize_runs(runs),
        "runs": runs,
    }


def execute_selector_deterministic_executor(
    *,
    task: LargeRealWorldTask,
    provider: SelectorProvider,
    config: SelectorConfig,
) -> dict[str, Any]:
    prompt = build_selector_prompt(task)
    started = time.perf_counter()
    raw_response_text = ""
    usage = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    provider_latency_ms: int | None = None
    selector_error = ""
    fallback_used = False
    parse_success = False
    parsed: dict[str, Any] | None = None
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=config.model,
            max_tokens=config.max_output_tokens,
            temperature=None,
            system_instruction=(
                "You are selecting source documents for a benchmark. Return only strict JSON."
            ),
        )
        raw_response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        provider_latency_ms = _extract_latency_ms(response)
        parsed = parse_selector_output(raw_response_text)
        parse_success = True
    except Exception as exc:
        selector_error = _safe_error_message(exc)
        fallback_used = True

    elapsed_latency_ms = int((time.perf_counter() - started) * 1000)
    latency_ms = provider_latency_ms if provider_latency_ms is not None else elapsed_latency_ms
    selected_source_ids = parsed["selected_source_ids"] if parsed else []
    rationale = parsed["selection_rationale"] if parsed else {}
    selector_validation = validate_selector_selection(task, selected_source_ids)
    executor_result = run_deterministic_executor(task, selected_source_ids)
    output_validation = validate_output(task, executor_result["output"])
    selected_context_tokens = _selected_context_tokens(task, selected_source_ids)
    full_context_tokens = _full_context_tokens(task)
    token_reduction = percent_reduction(full_context_tokens, selected_context_tokens)
    honest_pass = bool(
        parse_success
        and not fallback_used
        and selector_validation["exact_selector_match"]
        and output_validation["passed"]
        and executor_result["output_parse_success"]
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "fixture_id": task.fixture_id,
        "task_theme": task.task_theme,
        "router_model": config.model,
        "provider": OPENAI_API_PROVIDER,
        "api_path": OPENAI_SELECTOR_API_PATH,
        "selected_source_ids": selected_source_ids,
        "required_source_ids": list(task.required_source_ids),
        "distractor_source_ids": list(task.distractor_source_ids),
        "missing_required_source_ids": selector_validation["missing_required_source_ids"],
        "extra_selected_source_ids": selector_validation["extra_selected_source_ids"],
        "unknown_selected_source_ids": selector_validation["unknown_selected_source_ids"],
        "duplicate_selected_source_ids": selector_validation["duplicate_selected_source_ids"],
        "selected_distractor_source_ids": selector_validation[
            "selected_distractor_source_ids"
        ],
        "selection_rationale": rationale,
        "parse_success": parse_success,
        "parse_error": "" if parse_success else selector_error,
        "selector_error": selector_error,
        "fallback_used": fallback_used,
        "selector_exact_match": selector_validation["exact_selector_match"],
        "required_source_complete": selector_validation["required_source_complete"],
        "distractors_omitted": selector_validation["distractors_omitted"],
        "executor": executor_result["executor"],
        "executor_provider": executor_result["provider"],
        "executor_mode": executor_result["executor_mode"],
        "executor_output_parse_success": executor_result["output_parse_success"],
        "executor_output_parse_error": executor_result["output_parse_error"],
        "executor_used_selected_source_ids": executor_result["used_selected_source_ids"],
        "deterministic_executor_validation": output_validation,
        "deterministic_executor_validation_passed": output_validation["passed"],
        "output_validation_before_repair": output_validation["passed"],
        "output_validation_after_repair": None,
        "output_repair_attempted": False,
        "output_repair_status": "not_supported",
        "honest_selector_deterministic_executor_pass": honest_pass,
        "full_context_token_estimate": full_context_tokens,
        "selected_context_token_estimate": selected_context_tokens,
        "token_reduction_percent": token_reduction,
        "latency_ms": latency_ms,
        "usage": usage,
        "raw_response_text": raw_response_text,
        "output": executor_result["output"],
    }


def run_deterministic_executor(
    task: LargeRealWorldTask,
    selected_source_ids: list[str],
) -> dict[str, Any]:
    known_selected_source_ids = [
        source_id
        for source_id in selected_source_ids
        if source_id in {source.source_id for source in task.sources}
    ]
    selected_context = compose_context(task, tuple(known_selected_source_ids))
    context_lower = selected_context.lower()
    supported_fields = {
        field_name: expected_value
        for field_name, expected_value in task.expected_fields.items()
        if expected_value.lower() in context_lower
    }
    evidence_source_ids = [
        source_id for source_id in known_selected_source_ids if source_id in task.required_source_ids
    ]
    lines = [f"{field}: {value}" for field, value in supported_fields.items()]
    if evidence_source_ids:
        lines.append(f"evidence_source_ids: {', '.join(evidence_source_ids)}")
    return {
        "executor": "deterministic_selected_source_executor",
        "executor_mode": "deterministic_selected_source_contract",
        "provider": "deterministic_mock",
        "output": "\n".join(lines),
        "output_parse_success": True,
        "output_parse_error": "",
        "used_selected_source_ids": known_selected_source_ids,
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fixture_count": len(runs),
        "selector_exact_match_rate": _rate(run["selector_exact_match"] for run in runs),
        "deterministic_executor_validation_rate": _rate(
            run["deterministic_executor_validation_passed"] for run in runs
        ),
        "honest_end_to_contract_pass_rate": _rate(
            run["honest_selector_deterministic_executor_pass"] for run in runs
        ),
        "honest_end_to_contract_pass_count": sum(
            1 for run in runs if run["honest_selector_deterministic_executor_pass"]
        ),
        "fallback_count": sum(1 for run in runs if run["fallback_used"]),
        "parse_failure_count": sum(1 for run in runs if not run["parse_success"]),
        "repair_status": "not_supported",
        "average_selector_latency_ms": _average(
            run["latency_ms"] for run in runs if run["latency_ms"] is not None
        ),
        "average_prompt_tokens": _average_usage(runs, "input_tokens"),
        "average_completion_tokens": _average_usage(runs, "output_tokens"),
        "average_total_tokens": _average_usage(runs, "total_tokens"),
        "total_prompt_tokens": _sum_usage(runs, "input_tokens"),
        "total_completion_tokens": _sum_usage(runs, "output_tokens"),
        "total_tokens": _sum_usage(runs, "total_tokens"),
        "average_token_reduction_percent": _average(
            run["token_reduction_percent"]
            for run in runs
            if run["token_reduction_percent"] is not None
        ),
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Large Real-World OpenAI Selector + Deterministic Executor",
        "",
        "This benchmark uses an OpenAI selector and a deterministic executor. It is "
        "not OpenAI end-to-end answer generation.",
        "",
        "The purpose is to test whether real selected sources are sufficient for "
        "the existing deterministic answer contract. Deterministic validation is "
        "the source of truth, and no oracle fallback is counted as success.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Router model: `{report['metadata']['router_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"API path: `{report['metadata']['api_path']}`",
        f"Fixture count: {report['metadata']['fixture_count']}",
        "Repair status: not_supported",
        "",
        "## Summary",
        "",
        f"Selector exact match rate: {_format_percent(summary['selector_exact_match_rate'])}",
        f"Deterministic executor validation rate: {_format_percent(summary['deterministic_executor_validation_rate'])}",
        f"Honest end-to-contract pass rate: {_format_percent(summary['honest_end_to_contract_pass_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Parse failure count: {summary['parse_failure_count']}",
        f"Average selector latency ms: {_format_optional_float(summary['average_selector_latency_ms'])}",
        f"Average prompt tokens: {_format_optional_float(summary['average_prompt_tokens'])}",
        f"Average completion tokens: {_format_optional_float(summary['average_completion_tokens'])}",
        f"Average total tokens: {_format_optional_float(summary['average_total_tokens'])}",
        f"Average selected-context token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Fixtures",
        "",
        "| Fixture | Selector exact | Executor valid | Honest pass | Selected sources | Missing required | Extra/distractor selected | Token reduction |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | ---: |",
    ]
    for run in report["runs"]:
        extras = run["extra_selected_source_ids"] or run["selected_distractor_source_ids"]
        lines.append(
            f"| `{run['fixture_id']}` | "
            f"{run['selector_exact_match']} | "
            f"{run['deterministic_executor_validation_passed']} | "
            f"{run['honest_selector_deterministic_executor_pass']} | "
            f"{', '.join(run['selected_source_ids']) or 'none'} | "
            f"{', '.join(run['missing_required_source_ids']) or 'none'} | "
            f"{', '.join(extras) or 'none'} | "
            f"{_format_optional_percent(run['token_reduction_percent'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Large real-world OpenAI selector + deterministic executor")
    print(f"router model: {report['metadata']['router_model']}")
    print(f"selector exact match rate: {_format_percent(summary['selector_exact_match_rate'])}")
    print(
        "deterministic executor validation rate: "
        f"{_format_percent(summary['deterministic_executor_validation_rate'])}"
    )
    print(
        "honest end-to-contract pass rate: "
        f"{_format_percent(summary['honest_end_to_contract_pass_rate'])}"
    )
    print(f"fallback count: {summary['fallback_count']}")
    print(f"parse failure count: {summary['parse_failure_count']}")
    print(
        "average selected-context token reduction: "
        f"{_format_optional_percent(summary['average_token_reduction_percent'])}"
    )
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _rate(values: Any) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if bool(item)) / len(items)


def _average(values: Any) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _sum_usage(runs: list[dict[str, Any]], key: str) -> int | None:
    values = [run["usage"].get(key) for run in runs if run["usage"].get(key) is not None]
    if not values:
        return None
    return sum(int(value) for value in values)


def _average_usage(runs: list[dict[str, Any]], key: str) -> float | None:
    return _average(run["usage"].get(key) for run in runs)


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_optional_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


if __name__ == "__main__":
    main()
