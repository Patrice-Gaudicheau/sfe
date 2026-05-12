"""Run selected-vs-full comparison for the policy-exception fixture."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.high_overlap_openai_comparison_helpers import (
    ComparisonSpec,
    ExecutorConfig,
    ExecutorProvider,
    build_comparison_prompt,
    build_skipped_report as _build_skipped_report,
    compare_conditions,
    contamination_diagnostics,
    evaluate_honest_condition_pass,
    execute_condition as _execute_condition,
    execute_task_comparison as _execute_task_comparison,
    main_for_spec,
    parse_args_for_spec,
    run_comparison as _run_comparison,
    summarize_comparisons,
    validate_context_for_condition as _validate_context_for_condition,
    write_markdown as _write_markdown,
    write_skipped_markdown as _write_skipped_markdown,
)
from runtime.high_overlap_openai_executor_smoke_helpers import ExcludedSourceGroup
from runtime.run_high_overlap_poison_pill_benchmark import PoisonPillTask
from runtime.run_high_overlap_policy_exception_benchmark import (
    get_high_overlap_policy_exception_tasks,
)


BENCHMARK_TYPE = "multi_zone/high_overlap_policy_exception_contamination_comparison"
BENCHMARK_NAME = "high_overlap_policy_exception_contamination_comparison"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_policy_exception_contamination_comparison.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_policy_exception_contamination_comparison.md"

SPEC = ComparisonSpec(
    benchmark_name=BENCHMARK_NAME,
    benchmark_type=BENCHMARK_TYPE,
    benchmark_key="high_overlap_policy_exception",
    fixture_scope="policy_exception_fixture",
    authority_gap_type="policy_exception_vs_active_policy",
    title="High-Overlap Policy-Exception Contamination Comparison",
    description=(
        "This is a controlled selected-context vs full-context comparison for "
        "the policy-exception fixture. The selected source is the narrower "
        "exception-aware authority."
    ),
    task_error_label="high-overlap policy-exception",
    default_json_path=DEFAULT_JSON_PATH,
    default_md_path=DEFAULT_MD_PATH,
    get_tasks=get_high_overlap_policy_exception_tasks,
    excluded_groups=(
        ExcludedSourceGroup("general_policy", "poison_pill_source_ids", "general policy"),
        ExcludedSourceGroup("partial", "partial_source_ids", "partial"),
    ),
)


def main() -> None:
    main_for_spec(SPEC, _parse_args())


def _parse_args() -> Any:
    return parse_args_for_spec(SPEC)


def run_comparison(
    *,
    tasks: list[PoisonPillTask],
    provider: ExecutorProvider,
    config: ExecutorConfig,
) -> dict[str, Any]:
    return _run_comparison(spec=SPEC, tasks=tasks, provider=provider, config=config)


def build_skipped_report(*, model: str, timeout: float | None, reason: str) -> dict[str, Any]:
    return _build_skipped_report(spec=SPEC, model=model, timeout=timeout, reason=reason)


def execute_task_comparison(
    *,
    task: PoisonPillTask,
    provider: ExecutorProvider,
    config: ExecutorConfig,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _execute_task_comparison(
        spec=SPEC,
        task=task,
        provider=provider,
        config=config,
        selection=selection,
    )


def execute_condition(
    *,
    task: PoisonPillTask,
    provider: ExecutorProvider,
    config: ExecutorConfig,
    condition: str,
    selection: dict[str, Any],
) -> dict[str, Any]:
    return _execute_condition(
        spec=SPEC,
        task=task,
        provider=provider,
        config=config,
        condition=condition,
        selection=selection,
    )


def validate_context_for_condition(
    *,
    task: PoisonPillTask,
    condition: str,
    context: str,
    context_source_ids: list[str],
    selected_source_ids: list[str],
) -> dict[str, Any]:
    return _validate_context_for_condition(
        spec=SPEC,
        task=task,
        condition=condition,
        context=context,
        context_source_ids=context_source_ids,
        selected_source_ids=selected_source_ids,
    )


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    _write_markdown(path, report, spec=SPEC)


def write_skipped_markdown(path: Path, report: dict[str, Any]) -> None:
    _write_skipped_markdown(path, report, spec=SPEC)


if __name__ == "__main__":
    main()
