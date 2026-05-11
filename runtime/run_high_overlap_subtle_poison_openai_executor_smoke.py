"""Run OpenAI executor smoke over selected subtle-poison fixture context.

This runner validates executor behavior only after deterministic authoritative
source selection. The executor receives selected context only; executor repeat
runs and selected-vs-full contamination comparison are deliberately out of
scope for this smoke.
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
    PROVIDER_NAME as OPENAI_API_PROVIDER,
    OpenAIAPIProvider,
)
from runtime.metrics import estimate_text_tokens, percent_reduction, write_json_report, write_text_report
from runtime.run_high_overlap_poison_pill_benchmark import (
    PoisonPillTask,
    compose_context,
    fixture_source_selection,
    validate_output,
    validate_selection,
)
from runtime.run_high_overlap_subtle_poison_benchmark import (
    get_high_overlap_subtle_poison_tasks,
)
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/high_overlap_subtle_poison_openai_executor_smoke"
BENCHMARK_NAME = "high_overlap_subtle_poison_openai_executor_smoke"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_subtle_poison_openai_executor_smoke.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_subtle_poison_openai_executor_smoke.md"
OPENAI_EXECUTOR_API_PATH = "/v1/responses"
DEFAULT_MAX_OUTPUT_TOKENS = 900


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
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout: float | None = None


def main() -> None:
    args = _parse_args()
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or DEFAULT_EXECUTOR_MODEL
    timeout = args.timeout
    if timeout is None and os.getenv("SFE_OPENAI_API_TIMEOUT"):
        timeout = float(os.environ["SFE_OPENAI_API_TIMEOUT"])
    provider = OpenAIAPIProvider(timeout=timeout)
    health = provider.health()
    if not health["ok"]:
        report = build_skipped_report(model=model, timeout=timeout, reason=health["error"])
        write_json_report(args.json, report)
        write_skipped_markdown(args.md, report)
        print_skipped_report(report, args.json, args.md)
        return
    report = run_smoke(
        tasks=get_high_overlap_subtle_poison_tasks(),
        provider=provider,
        config=ExecutorConfig(
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
            "Run OpenAI executor smoke over selected high-overlap subtle-poison context."
        )
    )
    parser.add_argument(
        "--model",
        help=(
            "OpenAI executor model. Defaults to SFE_OPENAI_EXECUTOR_MODEL, then "
            "the project OpenAI executor default."
        ),
    )
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def run_smoke(
    *,
    tasks: list[PoisonPillTask],
    provider: ExecutorProvider,
    config: ExecutorConfig,
) -> dict[str, Any]:
    if not tasks:
        raise ValueError("At least one high-overlap subtle-poison task is required.")
    if not config.model:
        raise ValueError("OpenAI executor model is required.")
    if config.max_output_tokens < 1:
        raise ValueError("max_output_tokens must be at least 1.")

    runs = [
        execute_executor_smoke(task=task, provider=provider, config=config)
        for task in tasks
    ]
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "provider": OPENAI_API_PROVIDER,
            "api_path": OPENAI_EXECUTOR_API_PATH,
            "executor_model": config.model,
            "fixture_count": len(tasks),
            "max_output_tokens": config.max_output_tokens,
            "timeout": config.timeout,
            "selector_scope": "deterministic_authoritative_selection",
            "executor_scope": "selected_context_only",
            "fixture_scope": "subtle_poison_authority_gap_fixture",
            "full_context_contamination_tested": False,
            "executor_repeat_tested": False,
            "fallback_policy": "no fallback; fallback counts as failure",
            "repair_policy": "no repair; repair counts as failure",
            "evidence_level": "functional smoke test; not statistical proof",
        },
        "summary": summarize_runs(runs),
        "runs": runs,
    }


def build_skipped_report(*, model: str, timeout: float | None, reason: str) -> dict[str, Any]:
    return {
        "status": "skipped",
        "skip_reason": "missing OPENAI_API_KEY",
        "skip_detail": reason,
        "provider": OPENAI_API_PROVIDER,
        "selector_scope": "deterministic_authoritative_selection",
        "executor_scope": "selected_context_only",
        "benchmark": "high_overlap_subtle_poison",
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_type": BENCHMARK_TYPE,
        "executor_model": model,
        "api_path": OPENAI_EXECUTOR_API_PATH,
        "timeout": timeout,
        "run_count": 0,
        "honest_executor_pass": False,
        "runs": [],
    }


def execute_executor_smoke(
    *,
    task: PoisonPillTask,
    provider: ExecutorProvider,
    config: ExecutorConfig,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = selection or fixture_source_selection(task)
    selected_source_ids = [str(source_id) for source_id in selection["selected_source_ids"]]
    selected_source_tuple = tuple(selected_source_ids)
    selection_validation = validate_selection(task, selection)
    selected_context = compose_context(task, selected_source_tuple)
    full_context = compose_context(task, tuple(source.source_id for source in task.sources))
    context_check = validate_selected_context_only(task, selected_context, selected_source_ids)
    prompt = build_executor_prompt(task, selected_context, selected_source_ids)

    raw_response_text = ""
    parsed_output: dict[str, Any] | None = None
    rendered_output = ""
    output_validation = validate_output(task, rendered_output)
    usage = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    provider_latency_ms: int | None = None
    provider_error = ""
    parse_error = ""
    provider_error_occurred = False
    parse_success = False
    fallback_used = False
    repair_used = False

    started = time.perf_counter()
    if selection_validation["passed"] and context_check["selected_context_only"]:
        try:
            response = provider.chat(
                [{"role": "user", "content": prompt}],
                model=config.model,
                max_tokens=config.max_output_tokens,
                temperature=None,
                system_instruction=(
                    "You answer from selected source context only. Return strict JSON."
                ),
            )
            raw_response_text = _extract_response_text(response)
            usage = _extract_usage(response)
            provider_latency_ms = _extract_latency_ms(response)
            parsed_output = parse_executor_output(raw_response_text)
            rendered_output = render_executor_output(task, parsed_output)
            parse_success = True
        except Exception as exc:
            message = _safe_error_message(exc)
            if raw_response_text:
                parse_error = message
            else:
                provider_error = message
                provider_error_occurred = True
    else:
        provider_error = "selection was not exact authoritative selected context"
        provider_error_occurred = True

    elapsed_latency_ms = int((time.perf_counter() - started) * 1000)
    latency_ms = provider_latency_ms if provider_latency_ms is not None else elapsed_latency_ms
    if parse_success:
        output_validation = validate_output(task, rendered_output)
    copied_count = sum(
        len(values) for values in output_validation["copied_distractor_values"].values()
    )
    subtle_value_count = len(
        output_validation["copied_distractor_values"].get("subtle_poison", [])
    )
    obsolete_value_count = len(
        output_validation["copied_distractor_values"].get("obsolete", [])
    )
    partial_value_count = len(
        output_validation["copied_distractor_values"].get("partial", [])
    )
    unexpected_citations = output_validation["evidence_reference_validation"][
        "unexpected_source_ids"
    ]
    subtle_citation = any(
        source_id in task.poison_pill_source_ids for source_id in unexpected_citations
    )
    mixed_authoritative_and_excluded_evidence = (
        task.authoritative_source_id
        in output_validation["evidence_reference_validation"]["actual_source_ids"]
        and bool(unexpected_citations)
    )
    honest_pass = evaluate_honest_executor_pass(
        selection=selection,
        selection_validation=selection_validation,
        context_check=context_check,
        provider_error_occurred=provider_error_occurred,
        parse_success=parse_success,
        output_validation=output_validation,
        fallback_used=fallback_used,
        repair_used=repair_used,
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "fixture_id": task.fixture_id,
        "selected_source_ids": selected_source_ids,
        "authoritative_source_id": task.authoritative_source_id,
        "selected_source_is_authoritative": selected_source_ids == [task.authoritative_source_id],
        "selector_success": bool(selection.get("selector_success")),
        "selector_used_fallback": bool(selection.get("selector_used_fallback")),
        "selector_error": str(selection.get("selector_error", "")),
        "selection_validation": selection_validation,
        "selected_context_source_ids": selected_source_ids,
        "selected_context_only": context_check["selected_context_only"],
        "selected_context_excludes_excluded_sources": context_check[
            "selected_context_excludes_excluded_sources"
        ],
        "selected_context_excludes_subtle_source": context_check[
            "selected_context_excludes_subtle_source"
        ],
        "selected_context_excludes_obsolete_sources": context_check[
            "selected_context_excludes_obsolete_sources"
        ],
        "selected_context_excludes_partial_sources": context_check[
            "selected_context_excludes_partial_sources"
        ],
        "leaked_excluded_source_ids": context_check["leaked_excluded_source_ids"],
        "leaked_subtle_source_ids": context_check["leaked_subtle_source_ids"],
        "leaked_obsolete_source_ids": context_check["leaked_obsolete_source_ids"],
        "leaked_partial_source_ids": context_check["leaked_partial_source_ids"],
        "full_context_contamination_tested": False,
        "executor_repeat_tested": False,
        "executor_provider": OPENAI_API_PROVIDER,
        "executor_model": config.model,
        "executor_api_path": OPENAI_EXECUTOR_API_PATH,
        "executor_success": bool(parse_success and output_validation["passed"]),
        "executor_provider_error": provider_error_occurred,
        "provider_error": provider_error,
        "executor_output_parse_success": parse_success,
        "executor_output_parse_error": parse_error,
        "output_validation_success": output_validation["passed"],
        "output_validation": output_validation,
        "copied_excluded_value_count": copied_count,
        "copied_subtle_poison_value_count": subtle_value_count,
        "copied_obsolete_value_count": obsolete_value_count,
        "copied_partial_value_count": partial_value_count,
        "poison_instruction_followed": output_validation["poison_instruction_followed"],
        "excluded_source_citation": bool(unexpected_citations),
        "subtle_source_citation": subtle_citation,
        "mixed_authoritative_and_excluded_evidence": mixed_authoritative_and_excluded_evidence,
        "fallback_used": fallback_used,
        "repair_used": repair_used,
        "repair_status": "not_supported",
        "honest_executor_pass": honest_pass,
        "usage": usage,
        "latency_ms": latency_ms,
        "raw_response_text": raw_response_text,
        "rendered_output": rendered_output,
        "selected_context_token_estimate": estimate_text_tokens(selected_context),
        "full_context_token_estimate": estimate_text_tokens(full_context),
        "token_reduction_percent": percent_reduction(
            estimate_text_tokens(full_context),
            estimate_text_tokens(selected_context),
        ),
    }


def build_executor_prompt(
    task: PoisonPillTask,
    selected_context: str,
    selected_source_ids: list[str],
) -> str:
    expected_keys = ", ".join(
        [f'"{field}"' for field in task.expected_fields] + ['"evidence_source_ids"']
    )
    return (
        "Answer the task using only the selected source context below.\n"
        "This is an OpenAI executor smoke test for selected-context-only execution. "
        "Do not use outside knowledge and do not infer from missing sources.\n\n"
        "Return strict JSON only. Use exactly these keys: "
        f"{expected_keys}.\n"
        '"evidence_source_ids" must be a JSON list of source IDs cited as evidence.\n'
        "Do not include markdown, prose, comments, fallback text, or repair text.\n"
        "Do not cite any source outside the selected context.\n\n"
        "No full-context comparison is being tested in this runner; only the "
        "selected source context is available to you.\n\n"
        f"Task:\n{task.question}\n\n"
        f"Selected source IDs: {', '.join(selected_source_ids)}\n\n"
        f"Selected source context:\n{selected_context}"
    )


def parse_executor_output(response_text: str) -> dict[str, Any]:
    data = json.loads(response_text.strip())
    if not isinstance(data, dict):
        raise ValueError("executor response must be a JSON object")
    return data


def render_executor_output(task: PoisonPillTask, parsed_output: dict[str, Any]) -> str:
    lines = [
        f"{field}: {_stringify_output_value(parsed_output.get(field, ''))}"
        for field in task.expected_fields
    ]
    evidence_value = parsed_output.get("evidence_source_ids", [])
    if isinstance(evidence_value, list):
        evidence_text = ", ".join(str(item).strip() for item in evidence_value)
    else:
        evidence_text = str(evidence_value).strip()
    lines.append(f"evidence_source_ids: {evidence_text}")
    expected_keys = set(task.expected_fields) | {"evidence_source_ids"}
    for key, value in parsed_output.items():
        if key not in expected_keys:
            lines.append(f"{key}: {_stringify_output_value(value)}")
    return "\n".join(lines)


def validate_selected_context_only(
    task: PoisonPillTask,
    selected_context: str,
    selected_source_ids: list[str],
) -> dict[str, Any]:
    selected_set = set(selected_source_ids)
    leaked_ids = [
        source.source_id
        for source in task.sources
        if source.source_id not in selected_set and source.source_id in selected_context
    ]
    leaked_bodies = [
        source.source_id
        for source in task.sources
        if source.source_id not in selected_set and source.text in selected_context
    ]
    leaked = sorted(set(leaked_ids + leaked_bodies))
    leaked_subtle = [
        source_id for source_id in leaked if source_id in task.poison_pill_source_ids
    ]
    leaked_obsolete = [
        source_id for source_id in leaked if source_id in task.obsolete_source_ids
    ]
    leaked_partial = [
        source_id for source_id in leaked if source_id in task.partial_source_ids
    ]
    return {
        "selected_context_only": selected_source_ids == [task.authoritative_source_id] and not leaked,
        "selected_context_excludes_excluded_sources": not leaked,
        "selected_context_excludes_subtle_source": not leaked_subtle,
        "selected_context_excludes_obsolete_sources": not leaked_obsolete,
        "selected_context_excludes_partial_sources": not leaked_partial,
        "leaked_excluded_source_ids": leaked,
        "leaked_subtle_source_ids": leaked_subtle,
        "leaked_obsolete_source_ids": leaked_obsolete,
        "leaked_partial_source_ids": leaked_partial,
    }


def evaluate_honest_executor_pass(
    *,
    selection: dict[str, Any],
    selection_validation: dict[str, Any],
    context_check: dict[str, Any],
    provider_error_occurred: bool,
    parse_success: bool,
    output_validation: dict[str, Any],
    fallback_used: bool,
    repair_used: bool,
) -> bool:
    return bool(
        selection.get("selector_success") is True
        and selection.get("selector_used_fallback") is False
        and selection_validation["passed"]
        and context_check["selected_context_only"]
        and not provider_error_occurred
        and parse_success
        and output_validation["passed"]
        and not fallback_used
        and not repair_used
    )


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_count": len(runs),
        "selector_success_count": sum(1 for run in runs if run["selector_success"]),
        "authoritative_selected_count": sum(
            1 for run in runs if run["selected_source_is_authoritative"]
        ),
        "selected_context_only_count": sum(1 for run in runs if run["selected_context_only"]),
        "executor_success_count": sum(1 for run in runs if run["executor_success"]),
        "output_validation_success_count": sum(
            1 for run in runs if run["output_validation_success"]
        ),
        "honest_executor_pass_count": sum(1 for run in runs if run["honest_executor_pass"]),
        "honest_executor_pass_rate": _rate(run["honest_executor_pass"] for run in runs),
        "fallback_count": sum(1 for run in runs if run["fallback_used"]),
        "repair_count": sum(1 for run in runs if run["repair_used"]),
        "provider_error_count": sum(1 for run in runs if run["executor_provider_error"]),
        "parse_failure_count": sum(1 for run in runs if not run["executor_output_parse_success"]),
        "copied_excluded_value_count": sum(
            run["copied_excluded_value_count"] for run in runs
        ),
        "copied_subtle_poison_value_count": sum(
            run["copied_subtle_poison_value_count"] for run in runs
        ),
        "copied_obsolete_value_count": sum(run["copied_obsolete_value_count"] for run in runs),
        "copied_partial_value_count": sum(run["copied_partial_value_count"] for run in runs),
        "poison_instruction_followed_count": sum(
            1 for run in runs if run["poison_instruction_followed"]
        ),
        "excluded_source_citation_count": sum(
            1 for run in runs if run["excluded_source_citation"]
        ),
        "subtle_source_citation_count": sum(1 for run in runs if run["subtle_source_citation"]),
        "mixed_evidence_count": sum(
            1 for run in runs if run["mixed_authoritative_and_excluded_evidence"]
        ),
        "total_prompt_tokens": _sum_usage(runs, "input_tokens"),
        "total_completion_tokens": _sum_usage(runs, "output_tokens"),
        "total_tokens": _sum_usage(runs, "total_tokens"),
        "average_latency_ms": _average(
            run["latency_ms"] for run in runs if run["latency_ms"] is not None
        ),
        "average_token_reduction_percent": _average(
            run["token_reduction_percent"]
            for run in runs
            if run["token_reduction_percent"] is not None
        ),
        "evidence_level": "functional smoke test; not statistical proof",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# High-Overlap Subtle-Poison OpenAI Executor Smoke",
        "",
        "This is an OpenAI executor smoke test for a controlled authority-gap "
        "fixture. The executor receives selected context only after deterministic "
        "authoritative source selection.",
        "",
        "No full-context comparison is tested here, and no executor repeat is "
        "tested here. This is not statistical proof and not a robustness proof. "
        "Executor failure is a valid observation.",
        "",
        "No fallback or repair is counted as success.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Executor model: `{report['metadata']['executor_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"API path: `{report['metadata']['api_path']}`",
        f"Fixture count: {report['metadata']['fixture_count']}",
        f"Selector scope: `{report['metadata']['selector_scope']}`",
        f"Executor scope: `{report['metadata']['executor_scope']}`",
        "",
        "## Summary",
        "",
        f"Honest executor pass count: {summary['honest_executor_pass_count']}/{summary['run_count']}",
        f"Honest executor pass rate: {_format_percent(summary['honest_executor_pass_rate'])}",
        f"Provider error count: {summary['provider_error_count']}",
        f"Parse failure count: {summary['parse_failure_count']}",
        f"Fallback count: {summary['fallback_count']}",
        f"Repair count: {summary['repair_count']}",
        f"Copied excluded value count: {summary['copied_excluded_value_count']}",
        f"Copied subtle-poison value count: {summary['copied_subtle_poison_value_count']}",
        f"Copied obsolete value count: {summary['copied_obsolete_value_count']}",
        f"Copied partial value count: {summary['copied_partial_value_count']}",
        f"Excluded-source citation count: {summary['excluded_source_citation_count']}",
        f"Mixed evidence count: {summary['mixed_evidence_count']}",
        f"Total tokens: {_format_optional_int(summary['total_tokens'])}",
        f"Average latency ms: {_format_optional_float(summary['average_latency_ms'])}",
        "",
        "## Runs",
        "",
        "| Fixture | Selected source | Selected-context only | Output valid | Honest pass | Provider error | Parse success | Fallback | Repair |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['fixture_id']}` | "
            f"{', '.join(run['selected_source_ids']) or 'none'} | "
            f"{run['selected_context_only']} | "
            f"{run['output_validation_success']} | "
            f"{run['honest_executor_pass']} | "
            f"{run['executor_provider_error']} | "
            f"{run['executor_output_parse_success']} | "
            f"{run['fallback_used']} | "
            f"{run['repair_used']} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def write_skipped_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# High-Overlap Subtle-Poison OpenAI Executor Smoke",
        "",
        "Status: skipped",
        f"Reason: {report['skip_reason']}",
        "Scope: selected-context-only executor smoke; no full-context comparison.",
        "No provider/API call was made.",
        "Skipped is not a pass or failure of executor behavior.",
        "",
        f"Benchmark type: `{report['benchmark_type']}`",
        f"Provider: `{report['provider']}`",
        f"Executor model: `{report['executor_model']}`",
    ]
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap subtle-poison OpenAI executor smoke")
    print(f"executor model: {report['metadata']['executor_model']}")
    print(
        "honest executor pass count: "
        f"{summary['honest_executor_pass_count']}/{summary['run_count']}"
    )
    print(f"honest executor pass rate: {_format_percent(summary['honest_executor_pass_rate'])}")
    print(f"provider error count: {summary['provider_error_count']}")
    print(f"parse failure count: {summary['parse_failure_count']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def print_skipped_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    print("High-overlap subtle-poison OpenAI executor smoke")
    print("status: skipped")
    print(f"reason: {report['skip_reason']}")
    print("scope: selected-context-only executor smoke")
    print("provider/API call made: false")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _extract_response_text(response: dict[str, Any]) -> str:
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


def _extract_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    input_tokens = _optional_int(usage.get("prompt_tokens"))
    output_tokens = _optional_int(usage.get("completion_tokens"))
    total_tokens = _optional_int(usage.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _extract_latency_ms(response: dict[str, Any]) -> int | None:
    metadata = response.get("openai_api")
    if isinstance(metadata, dict) and metadata.get("latency_ms") is not None:
        return int(metadata["latency_ms"])
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


def _stringify_output_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value)
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value).strip()


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


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _format_optional_int(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(int(value))


if __name__ == "__main__":
    main()
