"""Run OpenAI selector smoke for the high-overlap deprecated-memo fixture.

This runner tests source selection only. It does not run an executor, repeat-N
selector loop, repair, fallback-as-success, or selected-vs-full comparison.
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
    DEFAULT_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_API_PROVIDER,
    OpenAIAPIProvider,
)
from runtime.high_overlap_benchmark_helpers import (
    average as _average,
    average_usage as _average_usage,
    extract_latency_ms as _extract_latency_ms,
    extract_response_text as _extract_response_text,
    extract_usage as _extract_usage,
    format_optional_float as _format_optional_float,
    format_optional_percent as _format_optional_percent,
    format_percent as _format_percent,
    rate as _rate,
    safe_error_message as _safe_error_message,
    sum_usage as _sum_usage,
)
from runtime.metrics import estimate_text_tokens, percent_reduction, write_json_report, write_text_report
from runtime.run_high_overlap_poison_pill_benchmark import (
    PoisonPillTask,
    PoisonPillSource,
    source_by_id,
)
from runtime.run_high_overlap_deprecated_memo_benchmark import (
    BENCHMARK_TYPE as FIXTURE_BENCHMARK_TYPE,
    get_high_overlap_deprecated_memo_tasks,
)
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/high_overlap_deprecated_memo_openai_selector_smoke"
BENCHMARK_NAME = "high_overlap_deprecated_memo_openai_selector_smoke"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_deprecated_memo_openai_selector_smoke.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_deprecated_memo_openai_selector_smoke.md"
OPENAI_SELECTOR_API_PATH = "/v1/responses"
DEFAULT_MAX_OUTPUT_TOKENS = 700


class SelectorProvider(Protocol):
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
class SelectorConfig:
    model: str
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    timeout: float | None = None


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
        report = build_skipped_report(model=model, timeout=timeout, reason=health["error"])
        write_json_report(args.json, report)
        write_skipped_markdown(args.md, report)
        print_skipped_report(report, args.json, args.md)
        return
    report = run_smoke(
        tasks=get_high_overlap_deprecated_memo_tasks(),
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
        description="Run OpenAI selector smoke over the high-overlap deprecated-memo fixture."
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


def run_smoke(
    *,
    tasks: list[PoisonPillTask],
    provider: SelectorProvider,
    config: SelectorConfig,
) -> dict[str, Any]:
    if not tasks:
        raise ValueError("At least one high-overlap deprecated-memo task is required.")
    if not config.model:
        raise ValueError("OpenAI selector model is required.")
    if config.max_output_tokens < 1:
        raise ValueError("max_output_tokens must be at least 1.")

    runs = [
        execute_selector_smoke(task=task, provider=provider, config=config)
        for task in tasks
    ]
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "fixture_benchmark_type": FIXTURE_BENCHMARK_TYPE,
            "provider": OPENAI_API_PROVIDER,
            "api_path": OPENAI_SELECTOR_API_PATH,
            "router_model": config.model,
            "fixture_count": len(tasks),
            "max_output_tokens": config.max_output_tokens,
            "timeout": config.timeout,
            "selector_scope": "source_selection_only",
            "executor": "not_tested",
            "comparison_scope": "not_tested",
            "fallback_policy": "no fallback; fallback counts as failure",
            "repair_policy": "no repair; repair is not supported",
            "evidence_level": "OpenAI selector smoke on controlled fixture; not statistical proof",
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
        "selector_scope": "source_selection_only",
        "executor": "not_tested",
        "benchmark": "high_overlap_deprecated_memo",
        "benchmark_name": BENCHMARK_NAME,
        "benchmark_type": BENCHMARK_TYPE,
        "router_model": model,
        "api_path": OPENAI_SELECTOR_API_PATH,
        "timeout": timeout,
        "run_count": 0,
        "honest_selector_pass": False,
        "runs": [],
    }


def execute_selector_smoke(
    *,
    task: PoisonPillTask,
    provider: SelectorProvider,
    config: SelectorConfig,
) -> dict[str, Any]:
    alias_map = build_prompt_source_aliases(task)
    prompt = build_selector_prompt(task, alias_map)
    started = time.perf_counter()
    raw_response_text = ""
    usage = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    provider_latency_ms: int | None = None
    error = ""
    provider_error = False
    parse_success = False
    parsed: dict[str, Any] | None = None
    try:
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=config.model,
            max_tokens=config.max_output_tokens,
            temperature=None,
            system_instruction=(
                "You select source documents for a controlled authority-gap "
                "benchmark. Return only strict JSON."
            ),
        )
        raw_response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        provider_latency_ms = _extract_latency_ms(response)
        parsed = parse_selector_output(raw_response_text)
        parse_success = True
    except Exception as exc:
        error = _safe_error_message(exc)
        provider_error = not bool(raw_response_text)

    elapsed_latency_ms = int((time.perf_counter() - started) * 1000)
    latency_ms = provider_latency_ms if provider_latency_ms is not None else elapsed_latency_ms
    selected_prompt_source_ids = parsed["selected_source_ids"] if parsed else []
    selected_source_ids, unknown_prompt_source_ids = resolve_prompt_source_ids(
        selected_prompt_source_ids,
        alias_map,
    )
    rationale = parsed["selection_rationale"] if parsed else {}
    validation = validate_selector_selection(
        task=task,
        selected_source_ids=selected_source_ids,
        unknown_prompt_source_ids=unknown_prompt_source_ids,
        selected_prompt_source_ids=selected_prompt_source_ids,
    )
    full_context_tokens = _full_context_tokens(task)
    selected_context_tokens = _selected_context_tokens(task, selected_source_ids)
    token_reduction = percent_reduction(full_context_tokens, selected_context_tokens)
    fallback_used = False
    repair_used = False
    honest_pass = evaluate_honest_selector_pass(
        parse_success=parse_success,
        provider_error=provider_error,
        validation=validation,
        fallback_used=fallback_used,
        repair_used=repair_used,
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "fixture_id": task.fixture_id,
        "router_model": config.model,
        "provider": OPENAI_API_PROVIDER,
        "api_path": OPENAI_SELECTOR_API_PATH,
        "selected_prompt_source_ids": selected_prompt_source_ids,
        "selected_source_ids": selected_source_ids,
        "authoritative_source_id": task.authoritative_source_id,
        "obsolete_source_ids": list(task.obsolete_source_ids),
        "partial_source_ids": list(task.partial_source_ids),
        "deprecated_memo_source_ids": list(task.obsolete_source_ids),
        "selection_rationale": rationale,
        "parse_success": parse_success,
        "parse_error": "" if parse_success else error,
        "selector_provider_error": provider_error,
        "selector_error": error,
        "fallback_used": fallback_used,
        "repair_used": repair_used,
        "repair_status": "not_supported",
        "honest_selector_pass": honest_pass,
        "full_context_token_estimate": full_context_tokens,
        "selected_context_token_estimate": selected_context_tokens,
        "token_reduction_percent": token_reduction,
        "latency_ms": latency_ms,
        "usage": usage,
        "raw_response_text": raw_response_text,
        **validation,
    }


def build_prompt_source_aliases(task: PoisonPillTask) -> dict[str, str]:
    return {f"candidate-{index}": source.source_id for index, source in enumerate(task.sources, 1)}


def resolve_prompt_source_ids(
    selected_prompt_source_ids: list[str],
    alias_map: dict[str, str],
) -> tuple[list[str], list[str]]:
    selected_source_ids: list[str] = []
    unknown_prompt_source_ids: list[str] = []
    for prompt_source_id in selected_prompt_source_ids:
        if prompt_source_id in alias_map:
            selected_source_ids.append(alias_map[prompt_source_id])
        else:
            unknown_prompt_source_ids.append(prompt_source_id)
    return selected_source_ids, unknown_prompt_source_ids


def build_selector_prompt(task: PoisonPillTask, alias_map: dict[str, str] | None = None) -> str:
    alias_map = alias_map or build_prompt_source_aliases(task)
    source_catalog = "\n\n".join(
        format_prompt_source(alias, source_by_id(task, source_id))
        for alias, source_id in alias_map.items()
    )
    source_ids = ", ".join(f'"{alias}"' for alias in alias_map)
    return (
        "Select the exact source document needed to answer the task.\n"
        "This is an OpenAI selector smoke test. You are selecting candidate "
        "handles only; do not answer the task.\n\n"
        "Return strict JSON only with this exact shape:\n"
        "{\n"
        '  "selected_source_ids": ["candidate-1"],\n'
        '  "selection_rationale": {"candidate-1": "short reason"}\n'
        "}\n\n"
        "Selection rules:\n"
        "- Select by current authority evidence, signature status, supersession authority, freshness, and completeness.\n"
        "- Choose the source that can support the requested implementation gate with current controlling authority.\n"
        "- Reject superseded planning memos and incomplete dashboard or operator notes.\n"
        "- Select only the exact source required by the task; this fixture requires exactly 1 candidate handle.\n"
        "- selected_source_ids must contain exact candidate handles only.\n"
        "- Do not include markdown, prose, comments, or decorated handles.\n"
        "- Do not invent handles.\n"
        f"- Valid candidate handles are exactly: {source_ids}\n\n"
        f"Fixture ID: {task.fixture_id}\n"
        f"Task:\n{task.question}\n\n"
        f"Candidate sources:\n{source_catalog}"
    )


def format_prompt_source(alias: str, source: PoisonPillSource) -> str:
    return "\n".join(
        [
            f"CANDIDATE HANDLE: {alias}",
            f"SOURCE ROLE: {source.role}",
            f"TITLE: {source.title}",
            source.text,
        ]
    )


def parse_selector_output(response_text: str) -> dict[str, Any]:
    data = json.loads(response_text.strip())
    if not isinstance(data, dict):
        raise ValueError("selector response must be a JSON object")
    selected = data.get("selected_source_ids")
    if not isinstance(selected, list):
        raise ValueError("selected_source_ids must be a list")
    selected_source_ids = [str(source_id).strip() for source_id in selected]
    if not selected_source_ids:
        raise ValueError("selected_source_ids must not be empty")
    duplicate_ids = sorted(
        {
            source_id
            for source_id in selected_source_ids
            if selected_source_ids.count(source_id) > 1
        }
    )
    if duplicate_ids:
        raise ValueError(
            "selected_source_ids must not contain duplicates: "
            + ", ".join(duplicate_ids)
        )
    rationale = data.get("selection_rationale", {})
    if not isinstance(rationale, dict):
        raise ValueError("selection_rationale must be an object")
    return {
        "selected_source_ids": selected_source_ids,
        "selection_rationale": {str(key): str(value) for key, value in rationale.items()},
    }


def validate_selector_selection(
    *,
    task: PoisonPillTask,
    selected_source_ids: list[str],
    unknown_prompt_source_ids: list[str],
    selected_prompt_source_ids: list[str],
) -> dict[str, Any]:
    selected_set = set(selected_source_ids)
    duplicate_prompt_ids = sorted(
        {
            source_id
            for source_id in selected_prompt_source_ids
            if selected_prompt_source_ids.count(source_id) > 1
        }
    )
    deprecated_memo_selected = [
        source_id for source_id in task.obsolete_source_ids if source_id in selected_set
    ]
    obsolete_selected = [
        source_id for source_id in task.obsolete_source_ids if source_id in selected_set
    ]
    partial_selected = [
        source_id for source_id in task.partial_source_ids if source_id in selected_set
    ]
    exact_authoritative = (
        not duplicate_prompt_ids
        and not unknown_prompt_source_ids
        and selected_source_ids == [task.authoritative_source_id]
    )
    extra_selected = [
        source_id
        for source_id in selected_source_ids
        if source_id != task.authoritative_source_id
    ]
    return {
        "exact_authoritative_selection": exact_authoritative,
        "authoritative_source_selected": task.authoritative_source_id in selected_set,
        "deprecated_memo_sources_omitted": not deprecated_memo_selected,
        "obsolete_sources_omitted": not obsolete_selected,
        "partial_sources_omitted": not partial_selected,
        "selected_deprecated_memo_source_ids": deprecated_memo_selected,
        "selected_obsolete_source_ids": obsolete_selected,
        "selected_partial_source_ids": partial_selected,
        "extra_selected_source_ids": extra_selected,
        "unknown_selected_source_ids": unknown_prompt_source_ids,
        "duplicate_selected_source_ids": duplicate_prompt_ids,
    }


def evaluate_honest_selector_pass(
    *,
    parse_success: bool,
    provider_error: bool,
    validation: dict[str, Any],
    fallback_used: bool,
    repair_used: bool,
) -> bool:
    return bool(
        parse_success
        and not provider_error
        and validation["exact_authoritative_selection"]
        and validation["deprecated_memo_sources_omitted"]
        and validation["obsolete_sources_omitted"]
        and validation["partial_sources_omitted"]
        and not validation["unknown_selected_source_ids"]
        and not validation["duplicate_selected_source_ids"]
        and not fallback_used
        and not repair_used
    )


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fixture_count": len(runs),
        "exact_authoritative_selection_rate": _rate(
            run["exact_authoritative_selection"] for run in runs
        ),
        "deprecated_memo_rejection_rate": _rate(
            run["deprecated_memo_sources_omitted"] for run in runs
        ),
        "obsolete_rejection_rate": _rate(run["obsolete_sources_omitted"] for run in runs),
        "partial_rejection_rate": _rate(run["partial_sources_omitted"] for run in runs),
        "honest_selector_pass_rate": _rate(run["honest_selector_pass"] for run in runs),
        "honest_selector_pass_count": sum(1 for run in runs if run["honest_selector_pass"]),
        "fallback_count": sum(1 for run in runs if run["fallback_used"]),
        "repair_count": sum(1 for run in runs if run["repair_used"]),
        "provider_error_count": sum(1 for run in runs if run["selector_provider_error"]),
        "parse_failure_count": sum(1 for run in runs if not run["parse_success"]),
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
        "# High-Overlap Deprecated-Memo OpenAI Selector Smoke",
        "",
        "This is an OpenAI selector smoke test for a controlled deprecated-memo "
        "fixture. It tests source selection only; no executor was tested and no "
        "selected-vs-full comparison was tested.",
        "",
        "The fixture checks freshness and operational-authority reasoning: a "
        "formal memo can be superseded by an active implementation notice.",
        "",
        "Selector failure is a valid observation. This smoke test is not "
        "statistical proof and not general robustness proof.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Router model: `{report['metadata']['router_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"API path: `{report['metadata']['api_path']}`",
        f"Fixture count: {report['metadata']['fixture_count']}",
        "",
        "## Summary",
        "",
        f"Exact authoritative selection rate: {_format_percent(summary['exact_authoritative_selection_rate'])}",
        f"Honest selector pass rate: {_format_percent(summary['honest_selector_pass_rate'])}",
        f"Deprecated-memo rejection rate: {_format_percent(summary['deprecated_memo_rejection_rate'])}",
        f"Obsolete-source rejection rate: {_format_percent(summary['obsolete_rejection_rate'])}",
        f"Partial-source rejection rate: {_format_percent(summary['partial_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Repair count: {summary['repair_count']}",
        f"Provider error count: {summary['provider_error_count']}",
        f"Parse failure count: {summary['parse_failure_count']}",
        f"Average selector latency ms: {_format_optional_float(summary['average_selector_latency_ms'])}",
        f"Average prompt tokens: {_format_optional_float(summary['average_prompt_tokens'])}",
        f"Average completion tokens: {_format_optional_float(summary['average_completion_tokens'])}",
        f"Average total tokens: {_format_optional_float(summary['average_total_tokens'])}",
        f"Average selected-context token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Fixtures",
        "",
        "| Fixture | Exact authoritative | Honest pass | Selected sources | Deprecated-memo selected | Obsolete selected | Partial selected | Fallback | Repair |",
        "| --- | ---: | ---: | --- | --- | --- | --- | ---: | ---: |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['fixture_id']}` | "
            f"{run['exact_authoritative_selection']} | "
            f"{run['honest_selector_pass']} | "
            f"{', '.join(run['selected_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_deprecated_memo_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_obsolete_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_partial_source_ids']) or 'none'} | "
            f"{run['fallback_used']} | "
            f"{run['repair_used']} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def write_skipped_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# High-Overlap Deprecated-Memo OpenAI Selector Smoke",
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
    ]
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap deprecated-memo OpenAI selector smoke")
    print(f"router model: {report['metadata']['router_model']}")
    print(
        "exact authoritative selection rate: "
        f"{_format_percent(summary['exact_authoritative_selection_rate'])}"
    )
    print(f"honest selector pass rate: {_format_percent(summary['honest_selector_pass_rate'])}")
    print(f"fallback count: {summary['fallback_count']}")
    print(f"repair count: {summary['repair_count']}")
    print(f"provider error count: {summary['provider_error_count']}")
    print(f"parse failure count: {summary['parse_failure_count']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def print_skipped_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    print("High-overlap deprecated-memo OpenAI selector smoke")
    print("status: skipped")
    print(f"reason: {report['skip_reason']}")
    print("scope: selector-only; no executor was run")
    print("provider/API call made: false")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _full_context_tokens(task: PoisonPillTask) -> int:
    return sum(_source_tokens(task, source.source_id) for source in task.sources)


def _selected_context_tokens(task: PoisonPillTask, selected_source_ids: list[str]) -> int:
    return sum(
        _source_tokens(task, source_id)
        for source_id in selected_source_ids
        if _known(task, source_id)
    )


def _source_tokens(task: PoisonPillTask, source_id: str) -> int:
    source = source_by_id(task, source_id)
    return estimate_text_tokens(
        "\n".join([f"SOURCE ROLE: {source.role}", f"TITLE: {source.title}", source.text])
    )


def _known(task: PoisonPillTask, source_id: str) -> bool:
    return any(source.source_id == source_id for source in task.sources)


if __name__ == "__main__":
    main()
