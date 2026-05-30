"""Run OpenAI selector plus OpenAI executor smoke for the large benchmark.

This is the first large real-world inspired smoke path that uses OpenAI for
both source selection and answer generation. Deterministic validation remains
the pass gate, and no oracle selector or deterministic executor fallback is
used for success.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL,
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
    DEFAULT_MAX_OUTPUT_TOKENS as DEFAULT_SELECTOR_MAX_OUTPUT_TOKENS,
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


BENCHMARK_TYPE = "multi_zone/large_real_world_openai_selector_executor_smoke"
BENCHMARK_NAME = "large_real_world_openai_selector_executor_smoke"
OPENAI_EXECUTOR_API_PATH = "/v1/responses"
DEFAULT_EXECUTOR_MAX_OUTPUT_TOKENS = 1000
DEFAULT_JSON_PATH = (
    PROJECT_ROOT / "logs" / "large_real_world_openai_selector_executor_smoke.json"
)
DEFAULT_MD_PATH = (
    PROJECT_ROOT / "logs" / "large_real_world_openai_selector_executor_smoke.md"
)


class ExecutorProvider(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ExecutorConfig:
    model: str
    max_output_tokens: int = DEFAULT_EXECUTOR_MAX_OUTPUT_TOKENS
    timeout: float | None = None


def main() -> None:
    args = _parse_args()
    load_repo_env()
    router_model = args.model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL
    executor_model = (
        args.executor_model
        or os.getenv("SFE_OPENAI_EXECUTOR_MODEL")
        or DEFAULT_EXECUTOR_MODEL
    )
    timeout = args.timeout
    provider = OpenAIAPIProvider(timeout=timeout)
    health = provider.health()
    if not health["ok"]:
        raise MissingOpenAIAPIKeyError(health["error"])
    report = run_benchmark(
        tasks=get_large_real_world_tasks(),
        selector_provider=provider,
        executor_provider=provider,
        selector_config=SelectorConfig(
            model=router_model,
            timeout=timeout,
            max_output_tokens=args.max_output_tokens,
        ),
        executor_config=ExecutorConfig(
            model=executor_model,
            timeout=timeout,
            max_output_tokens=args.executor_max_output_tokens,
        ),
    )
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run OpenAI selector plus OpenAI executor smoke over the large benchmark."
    )
    parser.add_argument(
        "--model",
        help=(
            "OpenAI selector model. Defaults to SFE_OPENAI_ROUTER_MODEL, then the "
            "project OpenAI router default."
        ),
    )
    parser.add_argument(
        "--executor-model",
        help=(
            "OpenAI executor model. Defaults to SFE_OPENAI_EXECUTOR_MODEL, then the "
            "project OpenAI executor default."
        ),
    )
    parser.add_argument("--timeout", type=float)
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_SELECTOR_MAX_OUTPUT_TOKENS,
        help="Selector max output tokens.",
    )
    parser.add_argument(
        "--executor-max-output-tokens",
        type=int,
        default=DEFAULT_EXECUTOR_MAX_OUTPUT_TOKENS,
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def run_benchmark(
    *,
    tasks: list[LargeRealWorldTask],
    selector_provider: SelectorProvider,
    executor_provider: ExecutorProvider,
    selector_config: SelectorConfig,
    executor_config: ExecutorConfig,
) -> dict[str, Any]:
    if not tasks:
        raise ValueError("At least one large real-world task is required.")
    if not selector_config.model:
        raise ValueError("OpenAI selector model is required.")
    if not executor_config.model:
        raise ValueError("OpenAI executor model is required.")
    if selector_config.max_output_tokens < 1:
        raise ValueError("selector max_output_tokens must be at least 1.")
    if executor_config.max_output_tokens < 1:
        raise ValueError("executor max_output_tokens must be at least 1.")

    runs = [
        execute_selector_executor_smoke(
            task=task,
            selector_provider=selector_provider,
            executor_provider=executor_provider,
            selector_config=selector_config,
            executor_config=executor_config,
        )
        for task in tasks
    ]
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "provider": OPENAI_API_PROVIDER,
            "selector_api_path": OPENAI_SELECTOR_API_PATH,
            "executor_api_path": OPENAI_EXECUTOR_API_PATH,
            "router_model": selector_config.model,
            "executor_model": executor_config.model,
            "fixture_count": len(tasks),
            "selector_max_output_tokens": selector_config.max_output_tokens,
            "executor_max_output_tokens": executor_config.max_output_tokens,
            "timeout": selector_config.timeout,
            "selector_scope": "openai_source_selection",
            "executor_scope": "openai_selected_context_answer_generation",
            "repair_status": "not_supported",
            "fallback_policy": "no oracle or deterministic executor fallback; fallback counts as failure",
        },
        "summary": summarize_runs(runs),
        "runs": runs,
    }


def execute_selector_executor_smoke(
    *,
    task: LargeRealWorldTask,
    selector_provider: SelectorProvider,
    executor_provider: ExecutorProvider,
    selector_config: SelectorConfig,
    executor_config: ExecutorConfig,
) -> dict[str, Any]:
    selector_result = run_openai_selector(
        task=task,
        provider=selector_provider,
        config=selector_config,
    )
    selected_source_ids = selector_result["selected_source_ids"]
    selector_validation = validate_selector_selection(task, selected_source_ids)
    composed_context = compose_known_selected_context(task, selected_source_ids)
    executor_result = run_openai_executor(
        task=task,
        selected_source_ids=selected_source_ids,
        composed_context=composed_context,
        provider=executor_provider,
        config=executor_config,
    )
    output_validation = validate_output(task, executor_result["output"])
    selected_context_tokens = _selected_context_tokens(task, selected_source_ids)
    full_context_tokens = _full_context_tokens(task)
    token_reduction = percent_reduction(full_context_tokens, selected_context_tokens)
    honest_pass = bool(
        selector_result["parse_success"]
        and not selector_result["fallback_used"]
        and selector_validation["exact_selector_match"]
        and executor_result["output_parse_success"]
        and not executor_result["fallback_used"]
        and output_validation["passed"]
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "fixture_id": task.fixture_id,
        "task_theme": task.task_theme,
        "router_model": selector_config.model,
        "executor_model": executor_config.model,
        "provider": OPENAI_API_PROVIDER,
        "selector_api_path": OPENAI_SELECTOR_API_PATH,
        "executor_api_path": OPENAI_EXECUTOR_API_PATH,
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
        "selection_rationale": selector_result["selection_rationale"],
        "selector_parse_success": selector_result["parse_success"],
        "selector_parse_error": selector_result["parse_error"],
        "selector_error": selector_result["selector_error"],
        "selector_fallback_used": selector_result["fallback_used"],
        "selector_exact_match": selector_validation["exact_selector_match"],
        "required_source_complete": selector_validation["required_source_complete"],
        "distractors_omitted": selector_validation["distractors_omitted"],
        "executor": "openai_large_real_world_executor_smoke",
        "executor_provider": OPENAI_API_PROVIDER,
        "executor_mode": "openai_executor_smoke",
        "executor_output_parse_success": executor_result["output_parse_success"],
        "executor_output_parse_error": executor_result["output_parse_error"],
        "executor_fallback_used": executor_result["fallback_used"],
        "executor_error": executor_result["executor_error"],
        "executor_used_selected_source_ids": executor_result["used_selected_source_ids"],
        "executor_prompt_context_source_ids": executor_result["prompt_context_source_ids"],
        "executor_output_json": executor_result["output_json"],
        "output_validation": output_validation,
        "executor_validation_passed": output_validation["passed"],
        "output_validation_before_repair": output_validation["passed"],
        "output_validation_after_repair": None,
        "output_repair_attempted": False,
        "output_repair_status": "not_supported",
        "honest_end_to_end_pass": honest_pass,
        "full_context_token_estimate": full_context_tokens,
        "selected_context_token_estimate": selected_context_tokens,
        "token_reduction_percent": token_reduction,
        "selector_latency_ms": selector_result["latency_ms"],
        "executor_latency_ms": executor_result["latency_ms"],
        "selector_usage": selector_result["usage"],
        "executor_usage": executor_result["usage"],
        "raw_selector_response_text": selector_result["raw_response_text"],
        "raw_executor_response_text": executor_result["raw_response_text"],
        "output": executor_result["output"],
    }


def run_openai_selector(
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
    return {
        "selected_source_ids": parsed["selected_source_ids"] if parsed else [],
        "selection_rationale": parsed["selection_rationale"] if parsed else {},
        "parse_success": parse_success,
        "parse_error": "" if parse_success else selector_error,
        "selector_error": selector_error,
        "fallback_used": fallback_used,
        "latency_ms": provider_latency_ms if provider_latency_ms is not None else elapsed_latency_ms,
        "usage": usage,
        "raw_response_text": raw_response_text,
    }


def run_openai_executor(
    *,
    task: LargeRealWorldTask,
    selected_source_ids: list[str],
    composed_context: str,
    provider: ExecutorProvider,
    config: ExecutorConfig,
) -> dict[str, Any]:
    prompt_context_source_ids = [
        source_id for source_id in selected_source_ids if _known(task, source_id)
    ]
    prompt = build_executor_prompt(task, tuple(prompt_context_source_ids), composed_context)
    started = time.perf_counter()
    raw_response_text = ""
    usage = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    provider_latency_ms: int | None = None
    executor_error = ""
    fallback_used = False
    output_parse_success = False
    output = ""
    output_json: dict[str, Any] | None = None
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=config.model,
            max_tokens=config.max_output_tokens,
            temperature=None,
            system_instruction=(
                "You synthesize benchmark answers from selected source documents only. "
                "Return only strict JSON matching the requested schema."
            ),
        )
        raw_response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        provider_latency_ms = _extract_latency_ms(response)
        output, output_json = parse_executor_output(
            task=task,
            response_text=raw_response_text,
            selected_source_ids=tuple(prompt_context_source_ids),
        )
        output_parse_success = True
    except Exception as exc:
        executor_error = _safe_error_message(exc)
        fallback_used = True

    elapsed_latency_ms = int((time.perf_counter() - started) * 1000)
    return {
        "output": output,
        "output_json": output_json,
        "output_parse_success": output_parse_success,
        "output_parse_error": "" if output_parse_success else executor_error,
        "executor_error": executor_error,
        "fallback_used": fallback_used,
        "used_selected_source_ids": prompt_context_source_ids,
        "prompt_context_source_ids": prompt_context_source_ids,
        "latency_ms": provider_latency_ms if provider_latency_ms is not None else elapsed_latency_ms,
        "usage": usage,
        "raw_response_text": raw_response_text,
    }


def build_executor_prompt(
    task: LargeRealWorldTask,
    selected_source_ids: tuple[str, ...],
    composed_context: str,
) -> str:
    fields = list(task.expected_fields)
    schema_lines = [f'  "{field}": "string",' for field in fields]
    schema_lines.append('  "evidence_source_ids": ["source-id", "..."]')
    evidence_ids = ", ".join(f'"{source_id}"' for source_id in selected_source_ids)
    return (
        "Synthesize the large real-world inspired benchmark answer using only the "
        "selected source documents below.\n"
        "Return only strict JSON. Do not include markdown fences, extra prose, "
        "comments, or explanatory text outside the JSON object.\n\n"
        "Required JSON schema:\n"
        "{\n"
        + "\n".join(schema_lines)
        + "\n}\n\n"
        "Rules:\n"
        "- Use only the selected source context below.\n"
        "- Do not infer from outside knowledge.\n"
        "- Preserve exact canonical markers and exact values from the sources.\n"
        "- Include every required field exactly once.\n"
        "- evidence_source_ids must be a JSON array of exact undecorated source IDs from the selected context only.\n"
        "- Do not prefix evidence IDs with SOURCE or DOC, and do not append roles in parentheses.\n"
        "- If a required fact is not present in the selected context, return JSON with an empty string for that field rather than inventing it; validation will fail.\n\n"
        f"Allowed evidence source IDs for this selected context: {evidence_ids}\n\n"
        f"Task:\n{task.question}\n\n"
        f"Selected source documents:\n{composed_context}"
    )


def parse_executor_output(
    *,
    task: LargeRealWorldTask,
    response_text: str,
    selected_source_ids: tuple[str, ...],
) -> tuple[str, dict[str, Any]]:
    data = _loads_strict_json_object(response_text)
    expected_fields = list(task.expected_fields) + ["evidence_source_ids"]
    missing_fields = [field for field in expected_fields if field not in data]
    if missing_fields:
        raise ValueError(
            "OpenAI executor response is missing required fields: "
            + ", ".join(missing_fields)
        )
    unexpected_fields = [field for field in data if field not in set(expected_fields)]
    if unexpected_fields:
        raise ValueError(
            "OpenAI executor response included unexpected fields: "
            + ", ".join(unexpected_fields)
        )
    evidence_refs = data["evidence_source_ids"]
    if not isinstance(evidence_refs, list):
        raise ValueError("OpenAI executor evidence_source_ids must be a JSON array.")
    cleaned_evidence = [str(source_id).strip() for source_id in evidence_refs]
    if any(not source_id for source_id in cleaned_evidence):
        raise ValueError("OpenAI executor evidence_source_ids must not contain empty IDs.")
    duplicate_evidence = sorted(
        {
            source_id
            for source_id in cleaned_evidence
            if cleaned_evidence.count(source_id) > 1
        }
    )
    if duplicate_evidence:
        raise ValueError(
            "OpenAI executor evidence_source_ids must not contain duplicates: "
            + ", ".join(duplicate_evidence)
        )
    selected_set = set(selected_source_ids)
    outside_selected = [
        source_id for source_id in cleaned_evidence if source_id not in selected_set
    ]
    if outside_selected:
        raise ValueError(
            "OpenAI executor evidence_source_ids outside selected context: "
            + ", ".join(outside_selected)
        )
    lines: list[str] = []
    normalized_json: dict[str, Any] = {}
    for field in task.expected_fields:
        value = str(data[field]).strip()
        normalized_json[field] = value
        lines.append(f"{field}: {value}")
    normalized_json["evidence_source_ids"] = cleaned_evidence
    lines.append(f"evidence_source_ids: {', '.join(cleaned_evidence)}")
    return "\n".join(lines), normalized_json


def compose_known_selected_context(task: LargeRealWorldTask, selected_source_ids: list[str]) -> str:
    known_selected_source_ids = tuple(
        source_id for source_id in selected_source_ids if _known(task, source_id)
    )
    return compose_context(task, known_selected_source_ids)


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fixture_count": len(runs),
        "selector_exact_match_rate": _rate(run["selector_exact_match"] for run in runs),
        "executor_parse_success_rate": _rate(
            run["executor_output_parse_success"] for run in runs
        ),
        "executor_validation_rate": _rate(run["executor_validation_passed"] for run in runs),
        "honest_end_to_end_pass_rate": _rate(run["honest_end_to_end_pass"] for run in runs),
        "honest_end_to_end_pass_count": sum(
            1 for run in runs if run["honest_end_to_end_pass"]
        ),
        "selector_fallback_count": sum(1 for run in runs if run["selector_fallback_used"]),
        "executor_fallback_count": sum(1 for run in runs if run["executor_fallback_used"]),
        "selector_parse_failure_count": sum(
            1 for run in runs if not run["selector_parse_success"]
        ),
        "executor_parse_failure_count": sum(
            1 for run in runs if not run["executor_output_parse_success"]
        ),
        "repair_status": "not_supported",
        "average_selector_latency_ms": _average(
            run["selector_latency_ms"] for run in runs if run["selector_latency_ms"] is not None
        ),
        "average_executor_latency_ms": _average(
            run["executor_latency_ms"] for run in runs if run["executor_latency_ms"] is not None
        ),
        "total_selector_prompt_tokens": _sum_usage(runs, "selector_usage", "input_tokens"),
        "total_selector_completion_tokens": _sum_usage(
            runs, "selector_usage", "output_tokens"
        ),
        "total_selector_tokens": _sum_usage(runs, "selector_usage", "total_tokens"),
        "total_executor_prompt_tokens": _sum_usage(runs, "executor_usage", "input_tokens"),
        "total_executor_completion_tokens": _sum_usage(
            runs, "executor_usage", "output_tokens"
        ),
        "total_executor_tokens": _sum_usage(runs, "executor_usage", "total_tokens"),
        "total_tokens": _sum_total_tokens(runs),
        "average_token_reduction_percent": _average(
            run["token_reduction_percent"]
            for run in runs
            if run["token_reduction_percent"] is not None
        ),
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Large Real-World OpenAI Selector + Executor Smoke",
        "",
        "This is an OpenAI selector + OpenAI executor smoke test. It is the first "
        "full OpenAI end-to-end smoke path for this benchmark family.",
        "",
        "Deterministic validation is still the source of truth. No oracle fallback "
        "or deterministic executor fallback is counted as success.",
        "",
        "This is not broad real-world proof, and repeat-N stability is not established "
        "unless explicitly run.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Router model: `{report['metadata']['router_model']}`",
        f"Executor model: `{report['metadata']['executor_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"Selector API path: `{report['metadata']['selector_api_path']}`",
        f"Executor API path: `{report['metadata']['executor_api_path']}`",
        f"Fixture count: {report['metadata']['fixture_count']}",
        "Repair status: not_supported",
        "",
        "## Summary",
        "",
        f"Selector exact match rate: {_format_percent(summary['selector_exact_match_rate'])}",
        f"Executor parse success rate: {_format_percent(summary['executor_parse_success_rate'])}",
        f"Executor validation rate: {_format_percent(summary['executor_validation_rate'])}",
        f"Honest end-to-end pass rate: {_format_percent(summary['honest_end_to_end_pass_rate'])}",
        f"Selector fallback count: {summary['selector_fallback_count']}",
        f"Executor fallback count: {summary['executor_fallback_count']}",
        f"Selector parse failure count: {summary['selector_parse_failure_count']}",
        f"Executor parse failure count: {summary['executor_parse_failure_count']}",
        f"Average selector latency ms: {_format_optional_float(summary['average_selector_latency_ms'])}",
        f"Average executor latency ms: {_format_optional_float(summary['average_executor_latency_ms'])}",
        f"Total selector tokens: {_format_optional_float(summary['total_selector_tokens'])}",
        f"Total executor tokens: {_format_optional_float(summary['total_executor_tokens'])}",
        f"Total tokens: {_format_optional_float(summary['total_tokens'])}",
        f"Average selected-context token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Fixtures",
        "",
        "| Fixture | Selector exact | Executor parse | Executor valid | Honest pass | Selected sources | Missing required | Extra/distractor selected | Token reduction |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- | --- | ---: |",
    ]
    for run in report["runs"]:
        extras = run["extra_selected_source_ids"] or run["selected_distractor_source_ids"]
        lines.append(
            f"| `{run['fixture_id']}` | "
            f"{run['selector_exact_match']} | "
            f"{run['executor_output_parse_success']} | "
            f"{run['executor_validation_passed']} | "
            f"{run['honest_end_to_end_pass']} | "
            f"{', '.join(run['selected_source_ids']) or 'none'} | "
            f"{', '.join(run['missing_required_source_ids']) or 'none'} | "
            f"{', '.join(extras) or 'none'} | "
            f"{_format_optional_percent(run['token_reduction_percent'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Large real-world OpenAI selector + executor smoke")
    print(f"router model: {report['metadata']['router_model']}")
    print(f"executor model: {report['metadata']['executor_model']}")
    print(f"selector exact match rate: {_format_percent(summary['selector_exact_match_rate'])}")
    print(f"executor parse success rate: {_format_percent(summary['executor_parse_success_rate'])}")
    print(f"executor validation rate: {_format_percent(summary['executor_validation_rate'])}")
    print(f"honest end-to-end pass rate: {_format_percent(summary['honest_end_to_end_pass_rate'])}")
    print(f"selector fallback count: {summary['selector_fallback_count']}")
    print(f"executor fallback count: {summary['executor_fallback_count']}")
    print(f"selector parse failure count: {summary['selector_parse_failure_count']}")
    print(f"executor parse failure count: {summary['executor_parse_failure_count']}")
    print(
        "average selected-context token reduction: "
        f"{_format_optional_percent(summary['average_token_reduction_percent'])}"
    )
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _loads_strict_json_object(response_text: str) -> dict[str, Any]:
    data = json.loads(response_text.strip())
    if not isinstance(data, dict):
        raise ValueError("OpenAI executor response must be a strict JSON object.")
    return data


def _known(task: LargeRealWorldTask, source_id: str) -> bool:
    return any(source.source_id == source_id for source in task.sources)


def _average(values: Any) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers) / len(numbers)


def _rate(values: Any) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if bool(item)) / len(items)


def _sum_usage(runs: list[dict[str, Any]], usage_key: str, token_key: str) -> int | None:
    values = [
        run[usage_key].get(token_key)
        for run in runs
        if run[usage_key].get(token_key) is not None
    ]
    if not values:
        return None
    return sum(int(value) for value in values)


def _sum_total_tokens(runs: list[dict[str, Any]]) -> int | None:
    selector_total = _sum_usage(runs, "selector_usage", "total_tokens")
    executor_total = _sum_usage(runs, "executor_usage", "total_tokens")
    if selector_total is None and executor_total is None:
        return None
    return (selector_total or 0) + (executor_total or 0)


if __name__ == "__main__":
    main()
