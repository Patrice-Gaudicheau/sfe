"""Run OpenAI executor smoke over selected policy-exception fixture context."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.high_overlap_openai_executor_smoke_helpers import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    ExecutorConfig,
    ExecutorProvider,
    ExecutorSmokeSpec,
    ExcludedSourceGroup,
    build_executor_prompt,
    build_skipped_report as _build_skipped_report,
    evaluate_honest_executor_pass,
    execute_executor_smoke as _execute_executor_smoke,
    main_for_spec,
    parse_args_for_spec,
    parse_executor_output,
    render_executor_output,
    run_smoke as _run_smoke,
    summarize_runs,
    validate_selected_context_only as _validate_selected_context_only,
    write_markdown as _write_markdown,
    write_skipped_markdown as _write_skipped_markdown,
)
from runtime.run_high_overlap_poison_pill_benchmark import PoisonPillTask
from runtime.run_high_overlap_policy_exception_benchmark import (
    get_high_overlap_policy_exception_tasks,
)


BENCHMARK_TYPE = "multi_zone/high_overlap_policy_exception_openai_executor_smoke"
BENCHMARK_NAME = "high_overlap_policy_exception_openai_executor_smoke"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_policy_exception_openai_executor_smoke.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_policy_exception_openai_executor_smoke.md"

SPEC = ExecutorSmokeSpec(
    benchmark_name=BENCHMARK_NAME,
    benchmark_type=BENCHMARK_TYPE,
    benchmark_key="high_overlap_policy_exception",
    fixture_scope="policy_exception_fixture",
    authority_gap_type="policy_exception_vs_active_policy",
    title="High-Overlap Policy-Exception OpenAI Executor Smoke",
    description=(
        "This is an OpenAI executor smoke test for a controlled policy-exception "
        "fixture. The selected source is the narrower exception-aware authority."
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


def run_smoke(
    *,
    tasks: list[PoisonPillTask],
    provider: ExecutorProvider,
    config: ExecutorConfig,
) -> dict[str, Any]:
    return _run_smoke(spec=SPEC, tasks=tasks, provider=provider, config=config)


def build_skipped_report(*, model: str, timeout: float | None, reason: str) -> dict[str, Any]:
    return _build_skipped_report(spec=SPEC, model=model, timeout=timeout, reason=reason)


def execute_executor_smoke(
    *,
    task: PoisonPillTask,
    provider: ExecutorProvider,
    config: ExecutorConfig,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _execute_executor_smoke(
        spec=SPEC,
        task=task,
        provider=provider,
        config=config,
        selection=selection,
    )


def validate_selected_context_only(
    task: PoisonPillTask,
    selected_context: str,
    selected_source_ids: list[str],
) -> dict[str, Any]:
    return _validate_selected_context_only(
        spec=SPEC,
        task=task,
        selected_context=selected_context,
        selected_source_ids=selected_source_ids,
    )


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    _write_markdown(path, report, spec=SPEC)


def write_skipped_markdown(path: Path, report: dict[str, Any]) -> None:
    _write_skipped_markdown(path, report, spec=SPEC)


if __name__ == "__main__":
    main()
