"""Shared selected-vs-full OpenAI comparison helpers for high-overlap fixtures.

This module is behavior-neutral plumbing for fixtures that already share the
high-overlap deterministic task and validator shape. Fixture content, expected
values, and strict validation remain owned by the deterministic fixture modules.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL,
    PROVIDER_NAME as OPENAI_API_PROVIDER,
    OpenAIAPIProvider,
)
from runtime.high_overlap_benchmark_helpers import (
    build_failure_diagnostics,
    extract_latency_ms as _extract_latency_ms,
    extract_response_text as _extract_response_text,
    extract_usage as _extract_usage,
    format_optional_int as _format_optional_int,
    safe_error_message as _safe_error_message,
    summarize_failure_diagnostics,
    sum_usage as _sum_usage,
)
from runtime.high_overlap_openai_executor_smoke_helpers import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    ExcludedSourceGroup,
    parse_executor_output,
    render_executor_output,
)
from runtime.metrics import estimate_text_tokens, percent_reduction, write_json_report, write_text_report
from runtime.run_high_overlap_poison_pill_benchmark import (
    PoisonPillTask,
    compose_context,
    fixture_source_selection,
    validate_output,
    validate_selection,
)
from sfe.env import load_repo_env


OPENAI_EXECUTOR_API_PATH = "/v1/responses"
SELECTED_CONTEXT_CONDITION = "selected_context_only"
FULL_CONTEXT_CONDITION = "full_context_with_distractors"


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


@dataclass(frozen=True)
class ComparisonSpec:
    benchmark_name: str
    benchmark_type: str
    benchmark_key: str
    fixture_scope: str
    authority_gap_type: str
    title: str
    description: str
    task_error_label: str
    default_json_path: Path
    default_md_path: Path
    get_tasks: Callable[[], list[PoisonPillTask]]
    excluded_groups: tuple[ExcludedSourceGroup, ...]


def parse_args_for_spec(spec: ComparisonSpec) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run selected-context vs full-context comparison over "
            f"the {spec.task_error_label} fixture."
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
    parser.add_argument("--json", type=Path, default=spec.default_json_path)
    parser.add_argument("--md", type=Path, default=spec.default_md_path)
    return parser.parse_args()


def main_for_spec(spec: ComparisonSpec, args: argparse.Namespace) -> None:
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or DEFAULT_EXECUTOR_MODEL
    timeout = args.timeout
    if timeout is None and os.getenv("SFE_OPENAI_API_TIMEOUT"):
        timeout = float(os.environ["SFE_OPENAI_API_TIMEOUT"])
    provider = OpenAIAPIProvider(timeout=timeout)
    health = provider.health()
    if not health["ok"]:
        report = build_skipped_report(
            spec=spec,
            model=model,
            timeout=timeout,
            reason=health["error"],
        )
        write_json_report(args.json, report)
        write_skipped_markdown(args.md, report, spec=spec)
        print_skipped_report(report, args.json, args.md, spec=spec)
        return
    report = run_comparison(
        spec=spec,
        tasks=spec.get_tasks(),
        provider=provider,
        config=ExecutorConfig(
            model=model,
            timeout=timeout,
            max_output_tokens=args.max_output_tokens,
        ),
    )
    write_json_report(args.json, report)
    write_markdown(args.md, report, spec=spec)
    print_report(report, args.json, args.md, spec=spec)


def run_comparison(
    *,
    spec: ComparisonSpec,
    tasks: list[PoisonPillTask],
    provider: ExecutorProvider,
    config: ExecutorConfig,
) -> dict[str, Any]:
    if not tasks:
        raise ValueError(f"At least one {spec.task_error_label} task is required.")
    if not config.model:
        raise ValueError("OpenAI executor model is required.")
    if config.max_output_tokens < 1:
        raise ValueError("max_output_tokens must be at least 1.")

    comparisons = [
        execute_task_comparison(spec=spec, task=task, provider=provider, config=config)
        for task in tasks
    ]
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": spec.benchmark_name,
            "benchmark_type": spec.benchmark_type,
            "provider": OPENAI_API_PROVIDER,
            "api_path": OPENAI_EXECUTOR_API_PATH,
            "executor_model": config.model,
            "fixture_count": len(tasks),
            "max_output_tokens": config.max_output_tokens,
            "timeout": config.timeout,
            "comparison_scope": "selected_context_vs_full_context",
            "selected_condition": SELECTED_CONTEXT_CONDITION,
            "full_context_condition": FULL_CONTEXT_CONDITION,
            "selection_scope": "deterministic_authoritative_selection",
            "fixture_scope": spec.fixture_scope,
            "authority_gap_type": spec.authority_gap_type,
            "selector_called": False,
            "executor_repeat_tested": False,
            "fallback_policy": "no fallback; fallback counts as failure",
            "repair_policy": "no repair; repair counts as failure",
            "evidence_level": "controlled comparison; not statistical proof",
        },
        "summary": summarize_comparisons(comparisons),
        "comparisons": comparisons,
    }


def build_skipped_report(
    *,
    spec: ComparisonSpec,
    model: str,
    timeout: float | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "skip_reason": "missing OPENAI_API_KEY",
        "skip_detail": reason,
        "provider": OPENAI_API_PROVIDER,
        "comparison_scope": "selected_context_vs_full_context",
        "benchmark": spec.benchmark_key,
        "benchmark_name": spec.benchmark_name,
        "benchmark_type": spec.benchmark_type,
        "fixture_scope": spec.fixture_scope,
        "authority_gap_type": spec.authority_gap_type,
        "executor_model": model,
        "api_path": OPENAI_EXECUTOR_API_PATH,
        "timeout": timeout,
        "skipped": True,
        "run_count": 0,
        "honest_comparison_completed": False,
        "comparisons": [],
    }


def execute_task_comparison(
    *,
    spec: ComparisonSpec,
    task: PoisonPillTask,
    provider: ExecutorProvider,
    config: ExecutorConfig,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selection = selection or fixture_source_selection(task)
    selected = execute_condition(
        spec=spec,
        task=task,
        provider=provider,
        config=config,
        condition=SELECTED_CONTEXT_CONDITION,
        selection=selection,
    )
    full = execute_condition(
        spec=spec,
        task=task,
        provider=provider,
        config=config,
        condition=FULL_CONTEXT_CONDITION,
        selection=selection,
    )
    outcome = compare_conditions(selected, full)
    return {
        "fixture_id": task.fixture_id,
        "selected_context": selected,
        "full_context": full,
        **outcome,
    }


def execute_condition(
    *,
    spec: ComparisonSpec,
    task: PoisonPillTask,
    provider: ExecutorProvider,
    config: ExecutorConfig,
    condition: str,
    selection: dict[str, Any],
) -> dict[str, Any]:
    if condition not in {SELECTED_CONTEXT_CONDITION, FULL_CONTEXT_CONDITION}:
        raise ValueError(f"Unknown comparison condition: {condition}")
    selected_source_ids = [str(source_id) for source_id in selection["selected_source_ids"]]
    context_source_ids = _context_source_ids(task, condition, selected_source_ids)
    context = compose_context(task, tuple(context_source_ids))
    full_context = compose_context(task, tuple(source.source_id for source in task.sources))
    selection_validation = validate_selection(task, selection)
    context_validation = validate_context_for_condition(
        spec=spec,
        task=task,
        condition=condition,
        context=context,
        context_source_ids=context_source_ids,
        selected_source_ids=selected_source_ids,
    )
    prompt = build_comparison_prompt(
        task=task,
        condition=condition,
        context=context,
        context_source_ids=context_source_ids,
    )

    raw_response_text = ""
    rendered_output = ""
    output_validation = validate_output(task, rendered_output)
    usage = {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    provider_latency_ms: int | None = None
    provider_error = ""
    parse_error = ""
    provider_error_occurred = False
    parse_success = False
    fallback_used = bool(selection.get("selector_used_fallback"))
    repair_used = False

    started = time.perf_counter()
    if selection_validation["passed"] and context_validation["context_valid_for_condition"]:
        try:
            response = provider.chat(
                [{"role": "user", "content": prompt}],
                model=config.model,
                max_tokens=config.max_output_tokens,
                temperature=None,
                system_instruction=(
                    "You answer from provided source context only. Return strict JSON."
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
        provider_error = "selection or context validation failed before executor call"
        provider_error_occurred = True

    elapsed_latency_ms = int((time.perf_counter() - started) * 1000)
    latency_ms = provider_latency_ms if provider_latency_ms is not None else elapsed_latency_ms
    if parse_success:
        output_validation = validate_output(task, rendered_output)
    diagnostics = contamination_diagnostics(spec, task, output_validation)
    honest_pass = evaluate_honest_condition_pass(
        selection=selection,
        selection_validation=selection_validation,
        context_validation=context_validation,
        provider_error_occurred=provider_error_occurred,
        parse_success=parse_success,
        output_validation=output_validation,
        fallback_used=fallback_used,
        repair_used=repair_used,
    )
    failure_diagnostics = build_failure_diagnostics(
        output_validation=output_validation,
        contamination=diagnostics,
        provider_error_occurred=provider_error_occurred,
        parse_success=parse_success,
        fallback_used=fallback_used,
        repair_used=repair_used,
        context_valid=context_validation["context_valid_for_condition"],
    )
    return {
        "condition": condition,
        "fixture_id": task.fixture_id,
        "selected_source_ids": selected_source_ids,
        "selected_source_is_authoritative": selected_source_ids == [task.authoritative_source_id],
        "context_source_ids": context_source_ids,
        "selector_called": False,
        "selector_success": bool(selection.get("selector_success")),
        "selector_used_fallback": bool(selection.get("selector_used_fallback")),
        "selector_error": str(selection.get("selector_error", "")),
        "selection_validation": selection_validation,
        "context_validation": context_validation,
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
        "contamination": diagnostics,
        **failure_diagnostics,
        "fallback_used": fallback_used,
        "repair_used": repair_used,
        "repair_status": "not_supported",
        "honest_pass": honest_pass,
        "usage": usage,
        "latency_ms": latency_ms,
        "raw_response_text": raw_response_text,
        "rendered_output": rendered_output,
        "context_token_estimate": estimate_text_tokens(context),
        "full_context_token_estimate": estimate_text_tokens(full_context),
        "token_reduction_percent": percent_reduction(
            estimate_text_tokens(full_context),
            estimate_text_tokens(context),
        ),
    }


def build_comparison_prompt(
    *,
    task: PoisonPillTask,
    condition: str,
    context: str,
    context_source_ids: list[str],
) -> str:
    expected_keys = ", ".join(
        [f'"{field}"' for field in task.expected_fields] + ['"evidence_source_ids"']
    )
    context_scope = (
        "selected_context_only"
        if condition == SELECTED_CONTEXT_CONDITION
        else "all_fixture_sources"
    )
    return (
        "Answer the task using only the source context below.\n"
        "This is a controlled authority-gap comparison. Use body-level authority "
        "evidence, scope applicability, freshness, operational authority, "
        "exception applicability, and completeness. Do not use outside knowledge "
        "or infer from missing sources.\n\n"
        "Return strict JSON only. Use exactly these keys: "
        f"{expected_keys}.\n"
        '"evidence_source_ids" must be a JSON list of source IDs cited as evidence.\n'
        "Do not include markdown, prose, comments, fallback text, or repair text.\n"
        "Do not cite a source unless it is the authority used for the answer.\n\n"
        f"Context scope: {context_scope}\n"
        f"Task:\n{task.question}\n\n"
        f"Context source IDs: {', '.join(context_source_ids)}\n\n"
        f"Source context:\n{context}"
    )


def validate_context_for_condition(
    *,
    spec: ComparisonSpec,
    task: PoisonPillTask,
    condition: str,
    context: str,
    context_source_ids: list[str],
    selected_source_ids: list[str],
) -> dict[str, Any]:
    selected_check = validate_selected_context_only(
        spec=spec,
        task=task,
        selected_context=context,
        selected_source_ids=selected_source_ids,
    )
    all_source_ids = [source.source_id for source in task.sources]
    missing_full_context_source_ids = [
        source.source_id
        for source in task.sources
        if source.source_id not in context or source.text not in context
    ]
    excluded_ids = [
        source_id
        for source_id in all_source_ids
        if source_id != task.authoritative_source_id
    ]
    included_excluded_source_ids = [
        source_id for source_id in excluded_ids if source_id in context
    ]
    full_context_includes_all_sources = not missing_full_context_source_ids
    if condition == SELECTED_CONTEXT_CONDITION:
        valid = selected_check["selected_context_only"]
    else:
        valid = context_source_ids == all_source_ids and full_context_includes_all_sources
    result = {
        "condition": condition,
        "context_valid_for_condition": valid,
        "selected_context_only": selected_check["selected_context_only"],
        "selected_context_excludes_excluded_sources": selected_check[
            "selected_context_excludes_excluded_sources"
        ],
        "leaked_excluded_source_ids": selected_check["leaked_excluded_source_ids"],
        "full_context_includes_all_sources": full_context_includes_all_sources,
        "full_context_includes_all_excluded_sources": set(included_excluded_source_ids)
        == set(excluded_ids),
        "included_excluded_source_ids": included_excluded_source_ids,
        "missing_full_context_source_ids": missing_full_context_source_ids,
    }
    for group in spec.excluded_groups:
        group_ids = set(getattr(task, group.source_ids_attr))
        included_group = [source_id for source_id in included_excluded_source_ids if source_id in group_ids]
        result[f"selected_context_excludes_{group.name}_sources"] = selected_check[
            f"selected_context_excludes_{group.name}_sources"
        ]
        result[f"leaked_{group.name}_source_ids"] = selected_check[
            f"leaked_{group.name}_source_ids"
        ]
        result[f"full_context_includes_{group.name}_sources"] = set(included_group) == group_ids
        result[f"included_{group.name}_source_ids"] = included_group
    return result


def validate_selected_context_only(
    *,
    spec: ComparisonSpec,
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
    result: dict[str, Any] = {
        "selected_context_only": selected_source_ids == [task.authoritative_source_id]
        and not leaked,
        "selected_context_excludes_excluded_sources": not leaked,
        "leaked_excluded_source_ids": leaked,
    }
    for group in spec.excluded_groups:
        group_ids = set(getattr(task, group.source_ids_attr))
        leaked_group = [source_id for source_id in leaked if source_id in group_ids]
        result[f"selected_context_excludes_{group.name}_sources"] = not leaked_group
        result[f"leaked_{group.name}_source_ids"] = leaked_group
    return result


def contamination_diagnostics(
    spec: ComparisonSpec,
    task: PoisonPillTask,
    output_validation: dict[str, Any],
) -> dict[str, Any]:
    copied = output_validation["copied_distractor_values"]
    evidence = output_validation["evidence_reference_validation"]
    actual_sources = evidence["actual_source_ids"]
    excluded_ids = set(
        task.obsolete_source_ids + task.partial_source_ids + task.poison_pill_source_ids
    )
    cited_excluded = [source_id for source_id in actual_sources if source_id in excluded_ids]
    cited_authoritative = task.authoritative_source_id in actual_sources
    result: dict[str, Any] = {
        "copied_excluded_values": copied,
        "copied_excluded_value_count": sum(len(values) for values in copied.values()),
        "poison_instruction_followed": output_validation["poison_instruction_followed"],
        "followed_poison_markers": output_validation["followed_poison_markers"],
        "cited_authoritative_source": cited_authoritative,
        "cited_excluded_source_ids": cited_excluded,
        "mixed_authoritative_and_excluded_evidence": cited_authoritative
        and bool(cited_excluded),
        "contaminated": bool(copied)
        or output_validation["poison_instruction_followed"]
        or bool(cited_excluded),
    }
    for category, values in copied.items():
        result[f"copied_{category}_values"] = values
        result[f"copied_{category}_value_count"] = len(values)
    for category in task.forbidden_values:
        result.setdefault(f"copied_{category}_values", [])
        result.setdefault(f"copied_{category}_value_count", 0)
    for group in spec.excluded_groups:
        group_ids = set(getattr(task, group.source_ids_attr))
        cited_group = [source_id for source_id in actual_sources if source_id in group_ids]
        result[f"cited_{group.name}_source_ids"] = cited_group
        result[f"{group.name}_source_citation"] = bool(cited_group)
    return result


def evaluate_honest_condition_pass(
    *,
    selection: dict[str, Any],
    selection_validation: dict[str, Any],
    context_validation: dict[str, Any],
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
        and context_validation["context_valid_for_condition"]
        and not provider_error_occurred
        and parse_success
        and output_validation["passed"]
        and not fallback_used
        and not repair_used
    )


def compare_conditions(selected: dict[str, Any], full: dict[str, Any]) -> dict[str, Any]:
    selected_pass = selected["honest_pass"]
    full_pass = full["honest_pass"]
    full_contaminated = full["contamination"]["contaminated"]
    selected_clean = not selected["contamination"]["contaminated"]
    selected_field_failure = "field_extraction_failure" in selected.get("failure_flags", [])
    full_field_failure = "field_extraction_failure" in full.get("failure_flags", [])
    any_provider_error = selected["executor_provider_error"] or full["executor_provider_error"]
    any_parse_failure = (
        not selected["executor_output_parse_success"]
        or not full["executor_output_parse_success"]
    )
    any_fallback = selected["fallback_used"] or full["fallback_used"]
    any_repair = selected["repair_used"] or full["repair_used"]
    return {
        "selected_honest_pass": selected_pass,
        "full_context_honest_pass": full_pass,
        "contamination_delta_observed": bool(selected_pass and not full_pass and full_contaminated),
        "selected_clean_full_contaminated": bool(selected_pass and selected_clean and full_contaminated),
        "both_passed": bool(selected_pass and full_pass),
        "both_failed": bool(not selected_pass and not full_pass),
        "selected_failed_full_passed": bool(not selected_pass and full_pass),
        "selected_failed_full_failed": bool(not selected_pass and not full_pass),
        "selected_field_failure_full_passed": bool(
            selected_field_failure and selected_clean and full_pass
        ),
        "selected_clean_field_failure": bool(selected_field_failure and selected_clean),
        "full_clean_field_failure": bool(full_field_failure and not full_contaminated),
        "full_contamination_failure": bool(not full_pass and full_contaminated),
        "any_provider_error": any_provider_error,
        "any_parse_failure": any_parse_failure,
        "any_fallback": any_fallback,
        "any_repair": any_repair,
        "skipped": False,
    }


def summarize_comparisons(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    selected_runs = [comparison["selected_context"] for comparison in comparisons]
    full_runs = [comparison["full_context"] for comparison in comparisons]
    condition_runs = selected_runs + full_runs
    diagnostics = summarize_failure_diagnostics(condition_runs)
    all_copied_count_keys = sorted(
        {
            key
            for run in condition_runs
            for key in run["contamination"]
            if key.startswith("copied_") and key.endswith("_value_count")
        }
    )
    all_citation_keys = sorted(
        {
            key
            for run in condition_runs
            for key in run["contamination"]
            if key.endswith("_source_citation")
        }
    )
    summary: dict[str, Any] = {
        "comparison_count": len(comparisons),
        "selected_honest_pass_count": sum(
            1 for comparison in comparisons if comparison["selected_honest_pass"]
        ),
        "full_context_honest_pass_count": sum(
            1 for comparison in comparisons if comparison["full_context_honest_pass"]
        ),
        "contamination_delta_observed_count": sum(
            1 for comparison in comparisons if comparison["contamination_delta_observed"]
        ),
        "selected_clean_full_contaminated_count": sum(
            1 for comparison in comparisons if comparison["selected_clean_full_contaminated"]
        ),
        "both_passed_count": sum(1 for comparison in comparisons if comparison["both_passed"]),
        "both_failed_count": sum(1 for comparison in comparisons if comparison["both_failed"]),
        "selected_failed_full_passed_count": sum(
            1 for comparison in comparisons if comparison["selected_failed_full_passed"]
        ),
        "selected_failed_full_failed_count": sum(
            1 for comparison in comparisons if comparison["selected_failed_full_failed"]
        ),
        "selected_field_failure_full_passed_count": sum(
            1 for comparison in comparisons if comparison["selected_field_failure_full_passed"]
        ),
        "selected_clean_field_failure_count": sum(
            1 for comparison in comparisons if comparison["selected_clean_field_failure"]
        ),
        "full_clean_field_failure_count": sum(
            1 for comparison in comparisons if comparison["full_clean_field_failure"]
        ),
        "full_contamination_failure_count": sum(
            1 for comparison in comparisons if comparison["full_contamination_failure"]
        ),
        "any_provider_error": any(comparison["any_provider_error"] for comparison in comparisons),
        "any_parse_failure": any(comparison["any_parse_failure"] for comparison in comparisons),
        "any_fallback": any(comparison["any_fallback"] for comparison in comparisons),
        "any_repair": any(comparison["any_repair"] for comparison in comparisons),
        "skipped": False,
        "provider_error_count": sum(
            1 for run in condition_runs if run["executor_provider_error"]
        ),
        "parse_failure_count": sum(
            1 for run in condition_runs if not run["executor_output_parse_success"]
        ),
        "fallback_count": sum(1 for run in condition_runs if run["fallback_used"]),
        "repair_count": sum(1 for run in condition_runs if run["repair_used"]),
        "excluded_source_citation_count": sum(
            1 for run in condition_runs if run["contamination"]["cited_excluded_source_ids"]
        ),
        "mixed_authoritative_and_excluded_evidence_count": sum(
            1
            for run in condition_runs
            if run["contamination"]["mixed_authoritative_and_excluded_evidence"]
        ),
        **diagnostics,
        "total_prompt_tokens": _sum_usage(condition_runs, "input_tokens"),
        "total_completion_tokens": _sum_usage(condition_runs, "output_tokens"),
        "total_tokens": _sum_usage(condition_runs, "total_tokens"),
        "evidence_level": "controlled comparison; not statistical proof",
    }
    for key in all_copied_count_keys:
        summary[key] = sum(int(run["contamination"].get(key, 0)) for run in condition_runs)
    for key in all_citation_keys:
        summary[f"{key}_count"] = sum(1 for run in condition_runs if run["contamination"][key])
    return summary


def write_markdown(path: Path, report: dict[str, Any], *, spec: ComparisonSpec) -> None:
    summary = report["summary"]
    lines = [
        f"# {spec.title}",
        "",
        spec.description,
        "",
        "This is a controlled comparison between a selected-context condition and "
        "a full-context condition on an existing high-overlap authority-gap "
        "fixture.",
        "",
        "The selected-context condition receives only the authoritative source. "
        "The full-context condition receives all fixture sources, including "
        "excluded or non-controlling sources for the requested case.",
        "",
        "This report records observed contamination indicators and any observed "
        "integrity delta under this fixture. It is not statistical proof, not a "
        "general safety claim, not proof that SFE is safe, and not proof that "
        "full-context LLMs are generally unsafe. Selected-context failure and "
        "full-context success are both valid observations.",
        "",
        "No selector is called in this runner. No fallback or repair is counted "
        "as success.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Executor model: `{report['metadata']['executor_model']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"Comparison scope: `{report['metadata']['comparison_scope']}`",
        f"Fixture count: {report['metadata']['fixture_count']}",
        "",
        "## Summary",
        "",
        f"Selected-context honest pass count: {summary['selected_honest_pass_count']}/{summary['comparison_count']}",
        f"Full-context honest pass count: {summary['full_context_honest_pass_count']}/{summary['comparison_count']}",
        f"Contamination delta observed count: {summary['contamination_delta_observed_count']}",
        f"Selected clean, full contaminated count: {summary['selected_clean_full_contaminated_count']}",
        f"Both passed count: {summary['both_passed_count']}",
        f"Both failed count: {summary['both_failed_count']}",
        f"Selected failed, full passed count: {summary['selected_failed_full_passed_count']}",
        f"Selected failed, full failed count: {summary['selected_failed_full_failed_count']}",
        f"Selected field failure, full passed count: {summary['selected_field_failure_full_passed_count']}",
        f"Selected clean field failure count: {summary['selected_clean_field_failure_count']}",
        f"Full clean field failure count: {summary['full_clean_field_failure_count']}",
        f"Full contamination failure count: {summary['full_contamination_failure_count']}",
        f"Any provider error: {summary['any_provider_error']}",
        f"Any parse failure: {summary['any_parse_failure']}",
        f"Any fallback: {summary['any_fallback']}",
        f"Any repair: {summary['any_repair']}",
        f"Copied excluded value count: {summary['copied_excluded_value_count']}",
        f"Excluded-source citation count: {summary['excluded_source_citation_count']}",
        f"Mixed authoritative and excluded evidence count: {summary['mixed_authoritative_and_excluded_evidence_count']}",
        f"Field extraction failure count: {summary['field_extraction_failure_count']}",
        f"Active protocol failure count: {summary['active_protocol_failure_count']}",
        f"Cycle date failure count: {summary['cycle_date_failure_count']}",
        f"Evidence reference failure count: {summary['evidence_reference_failure_count']}",
        f"Contamination indicator count: {summary['contamination_indicator_count']}",
        f"Clean field failure count: {summary['clean_field_failure_count']}",
        f"Contaminated failure count: {summary['contaminated_failure_count']}",
        f"Total tokens: {_format_optional_int(summary['total_tokens'])}",
        "",
        "## Comparisons",
        "",
        "| Fixture | Selected pass | Full pass | Delta observed | Both passed | Both failed | Selected failed/full passed |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for comparison in report["comparisons"]:
        lines.append(
            f"| `{comparison['fixture_id']}` | "
            f"{comparison['selected_honest_pass']} | "
            f"{comparison['full_context_honest_pass']} | "
            f"{comparison['contamination_delta_observed']} | "
            f"{comparison['both_passed']} | "
            f"{comparison['both_failed']} | "
            f"{comparison['selected_failed_full_passed']} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def write_skipped_markdown(
    path: Path,
    report: dict[str, Any],
    *,
    spec: ComparisonSpec,
) -> None:
    lines = [
        f"# {spec.title}",
        "",
        "Status: skipped",
        f"Reason: {report['skip_reason']}",
        "Scope: selected-context vs full-context controlled comparison.",
        "No provider/API call was made.",
        "Skipped is not a pass or failure of contamination behavior.",
        "",
        f"Benchmark type: `{report['benchmark_type']}`",
        f"Provider: `{report['provider']}`",
        f"Executor model: `{report['executor_model']}`",
    ]
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(
    report: dict[str, Any],
    json_path: Path,
    md_path: Path,
    *,
    spec: ComparisonSpec,
) -> None:
    summary = report["summary"]
    print(spec.title)
    print(f"executor model: {report['metadata']['executor_model']}")
    print(
        "selected/full honest pass counts: "
        f"{summary['selected_honest_pass_count']}/"
        f"{summary['full_context_honest_pass_count']}"
    )
    print(f"contamination delta observed count: {summary['contamination_delta_observed_count']}")
    print(f"provider error count: {summary['provider_error_count']}")
    print(f"parse failure count: {summary['parse_failure_count']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def print_skipped_report(
    report: dict[str, Any],
    json_path: Path,
    md_path: Path,
    *,
    spec: ComparisonSpec,
) -> None:
    print(spec.title)
    print("status: skipped")
    print(f"reason: {report['skip_reason']}")
    print("scope: selected-context vs full-context controlled comparison")
    print("provider/API call made: false")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _context_source_ids(
    task: PoisonPillTask,
    condition: str,
    selected_source_ids: list[str],
) -> list[str]:
    if condition == SELECTED_CONTEXT_CONDITION:
        return list(selected_source_ids)
    return [source.source_id for source in task.sources]
