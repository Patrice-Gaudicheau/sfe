"""Run the minimal real-world inspired multi-zone benchmark.

This benchmark uses small project-like source documents instead of synthetic
role blocks. It remains controlled and deterministic: the default path makes no
provider calls and strict validation is the source of truth.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.metrics import estimate_text_tokens, percent_reduction, write_json_report, write_text_report


BENCHMARK_TYPE = "multi_zone/minimal_real_world_inspired"
BENCHMARK_NAME = "minimal_real_world_multi_zone"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "minimal_real_world_multi_zone_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "minimal_real_world_multi_zone_benchmark.md"
FIXTURE_SELECTOR_NAME = "fixture_minimal_real_world_selector"
FALLBACK_SELECTOR_NAME = "fixture_fallback_after_selector_error"
FIXTURE_EXECUTOR_NAME = "fixture_minimal_real_world_executor"


@dataclass(frozen=True)
class RealWorldSource:
    source_id: str
    role: str
    title: str
    text: str
    required: bool = False
    distractor: bool = False


@dataclass(frozen=True)
class RealWorldTask:
    fixture_id: str
    task_theme: str
    question: str
    sources: tuple[RealWorldSource, ...]
    required_source_ids: tuple[str, ...]
    distractor_source_ids: tuple[str, ...]
    expected_fields: dict[str, str]
    expected_answer: str


class RealWorldSelector(Protocol):
    provider: str
    selector_mode: str
    model: str | None
    api_path: str | None

    def select(self, task: RealWorldTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        ...


class RealWorldExecutor(Protocol):
    provider: str
    executor_mode: str
    model: str | None
    api_path: str | None

    def execute(
        self,
        task: RealWorldTask,
        selected_source_ids: tuple[str, ...],
        composed_context: str,
    ) -> dict[str, Any]:
        ...


def main() -> None:
    args = _parse_args()
    tasks = get_minimal_real_world_tasks()
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1 when provided.")
        tasks = tasks[: args.limit]
    report = run_benchmark(tasks=tasks, repeat=args.repeat)
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic minimal real-world inspired multi-zone benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def get_minimal_real_world_tasks() -> list[RealWorldTask]:
    return [
        _licensing_policy_task(),
        _benchmark_roadmap_task(),
    ]


def _licensing_policy_task() -> RealWorldTask:
    required_source_ids = (
        "doc-readme-licensing-note",
        "doc-apache-license-summary",
        "doc-optional-services-note",
        "doc-contribution-policy-note",
    )
    expected_fields = {
        "license_marker": "Apache License 2.0",
        "permitted_scope": "use, copy, modify, distribute, fork, and build on the project",
        "commercial_permission": "commercial use is permitted under Apache-2.0",
        "services_policy": "paid support, consulting, hosted deployments, or private integrations may be offered separately but are not required",
        "contribution_policy": "issues and pull requests are welcome under clear project rules",
        "claim_boundary": "no unsupported production, safety, security, reliability, or fitness claims",
    }
    expected_answer = _answer_from_fields(
        expected_fields,
        required_source_ids,
    )
    return RealWorldTask(
        fixture_id="minimal_real_world_licensing_policy_gate",
        task_theme="licensing_commercial_use_contribution_policy",
        question=(
            "Using the project-style licensing and contribution notes, determine "
            "what use is permitted under the open-source license, how commercial "
            "use and optional services should be treated, how forks and pull "
            "requests should be handled, and which sources support the decision."
        ),
        sources=(
            _source(
                "doc-readme-licensing-note",
                "readme_license_summary",
                "README Licensing Note",
                (
                    "The README says SFE is open source under the Apache License "
                    "2.0. It says users may use, copy, modify, distribute, fork, "
                    "and build on the project under that license. The README also "
                    "states that the project is experimental research-grade "
                    "infrastructure without production, safety, security, "
                    "reliability, or fitness claims."
                ),
                required=True,
            ),
            _source(
                "doc-apache-license-summary",
                "license_terms_summary",
                "Apache License Summary",
                (
                    "The Apache-2.0 license summary states that users may use, "
                    "copy, modify, distribute, fork, and build on the project under "
                    "the license terms. It does not require a separate license for "
                    "commercial use, and it does not replace project-specific "
                    "contribution rules."
                ),
                required=True,
            ),
            _source(
                "doc-optional-services-note",
                "optional_services_policy",
                "Optional Services Note",
                (
                    "Commercial use is permitted under Apache-2.0. Paid support, "
                    "consulting, hosted deployments, or private integrations may be "
                    "offered separately but are not required for using, "
                    "forking, modifying, or distributing the project under the "
                    "license. This note does not define pull request quality rules."
                ),
                required=True,
            ),
            _source(
                "doc-contribution-policy-note",
                "contribution_policy",
                "Contribution Policy Note",
                (
                    "issues and pull requests are welcome under clear project rules "
                    "for bug fixes, docs, benchmarks, provider integrations, and "
                    "focused design changes. Contributions are provided under "
                    "Apache-2.0 and should include clear rationale plus tests or "
                    "reproduction steps where practical. The contribution rules make "
                    "no unsupported production, safety, security, reliability, or "
                    "fitness claims."
                ),
                required=True,
            ),
            _source(
                "doc-legacy-mit-license-note",
                "obsolete_policy",
                "Legacy MIT License Note",
                (
                    "An old planning note proposed using an MIT-style license for "
                    "early prototypes and broad reuse. The note is marked obsolete "
                    "after the repository adopted Apache License 2.0 and cannot "
                    "support current licensing decisions."
                ),
                distractor=True,
            ),
            _source(
                "doc-hosted-demo-operations-note",
                "operations_note",
                "Hosted Demo Operations Note",
                (
                    "A demo operations note describes a private hosted evaluation "
                    "instance used by maintainers for testing. It is useful operational "
                    "background but is not an authority for licensing, forks, or pull "
                    "request rights."
                ),
                distractor=True,
            ),
            _source(
                "doc-community-fork-faq-draft",
                "draft_faq",
                "Community Fork FAQ Draft",
                (
                    "A draft FAQ says community forks are welcome and asks contributors "
                    "to open pull requests. It omits the Apache-2.0 contribution "
                    "terms, does not mention the experimental claim boundaries, and "
                    "is not the accepted contribution policy."
                ),
                distractor=True,
            ),
        ),
        required_source_ids=required_source_ids,
        distractor_source_ids=(
            "doc-legacy-mit-license-note",
            "doc-hosted-demo-operations-note",
            "doc-community-fork-faq-draft",
        ),
        expected_fields=expected_fields,
        expected_answer=expected_answer,
    )


def _benchmark_roadmap_task() -> RealWorldTask:
    required_source_ids = (
        "doc-structural-50k-result-note",
        "doc-phase2-roadmap-decision",
        "doc-multi-zone-smoke-summary",
        "doc-validation-gate-policy",
    )
    expected_fields = {
        "established_result": "honest structural routing passed on a synthetic 50k+ context",
        "stability_marker": "5/5 repeated structural runs",
        "phase2_observation": "multi-zone synthetic and controlled organic smoke paths passed under strict validation",
        "not_proven": "broad real-world generalization is not proven",
        "next_engineering_step": "minimal real-world inspired multi-zone benchmark",
        "gate_policy": "no fallback or repair may be counted as an honest pass",
    }
    expected_answer = _answer_from_fields(
        expected_fields,
        required_source_ids,
    )
    return RealWorldTask(
        fixture_id="minimal_real_world_benchmark_roadmap_gate",
        task_theme="benchmark_result_roadmap_decision",
        question=(
            "Using the project result and roadmap notes, state what has been "
            "established, what remains unproven, the next engineering benchmark "
            "step, and the validation policy that governs honest pass reporting."
        ),
        sources=(
            _source(
                "doc-structural-50k-result-note",
                "result_note",
                "Structural 50k Result Note",
                (
                    "The structural benchmark result note records that honest "
                    "structural routing passed on a synthetic 50k+ context. The "
                    "repeat check reported 5/5 repeated structural runs. The note "
                    "states that broad real-world generalization is not proven."
                ),
                required=True,
            ),
            _source(
                "doc-phase2-roadmap-decision",
                "roadmap_decision",
                "Post-Structural Roadmap Decision",
                (
                    "The roadmap says the next phase must test composition beyond "
                    "single-block routing. It identifies the next engineering step "
                    "as a minimal real-world inspired multi-zone benchmark before a "
                    "larger real-world corpus benchmark."
                ),
                required=True,
            ),
            _source(
                "doc-multi-zone-smoke-summary",
                "phase2_summary",
                "Multi-Zone Smoke Summary",
                (
                    "The Phase 2 summary says multi-zone synthetic and controlled "
                    "organic smoke paths passed under strict validation. It records "
                    "that selector and executor checks were isolated before combined "
                    "smoke runs. It does not define the next benchmark target."
                ),
                required=True,
            ),
            _source(
                "doc-validation-gate-policy",
                "validation_policy",
                "Honest Pass Validation Policy",
                (
                    "The validation policy says no fallback or repair may be counted "
                    "as an honest pass. Deterministic gates must reject missing sources, "
                    "selected distractors, parse failures, and incomplete evidence. "
                    "The policy is about reporting and does not describe benchmark results."
                ),
                required=True,
            ),
            _source(
                "doc-openai-smoke-announcement",
                "announcement_note",
                "OpenAI Smoke Announcement",
                (
                    "A short announcement says OpenAI smoke checks looked promising. "
                    "It does not identify the 5/5 structural stability marker, the "
                    "next benchmark, or the honest pass policy. It is not a validation "
                    "record."
                ),
                distractor=True,
            ),
            _source(
                "doc-old-roadmap-real-corpus",
                "obsolete_roadmap",
                "Old Real Corpus Roadmap",
                (
                    "An older roadmap proposed moving directly to a broad repository "
                    "benchmark after the structural result. It predates the decision "
                    "to add a minimal real-world inspired multi-zone benchmark first."
                ),
                distractor=True,
            ),
            _source(
                "doc-token-savings-note",
                "partial_metric_note",
                "Token Savings Note",
                (
                    "A metric note discusses token reduction observed in earlier "
                    "benchmarks. It is topically related but does not establish the "
                    "roadmap decision, the 5/5 structural stability marker, or the "
                    "rule that fallback and repair cannot count as honest passes."
                ),
                distractor=True,
            ),
        ),
        required_source_ids=required_source_ids,
        distractor_source_ids=(
            "doc-openai-smoke-announcement",
            "doc-old-roadmap-real-corpus",
            "doc-token-savings-note",
        ),
        expected_fields=expected_fields,
        expected_answer=expected_answer,
    )


class FixtureRealWorldSelector:
    provider = "deterministic_mock"
    selector_mode = "fixture"
    model: str | None = None
    api_path: str | None = None

    def select(self, task: RealWorldTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        selected_sources = [source_by_id(task, source_id) for source_id in task.required_source_ids]
        return build_selection(
            task=task,
            selected_sources=selected_sources,
            selector_name=FIXTURE_SELECTOR_NAME,
            selector_success=True,
            selector_used_fallback=False,
            confidence=1.0,
            rationale=(
                "Selected the required project-like sources because no single source "
                "contains the complete validated answer."
            ),
        )


class FixtureRealWorldExecutor:
    provider = "deterministic_mock"
    executor_mode = "deterministic_fixture"
    model: str | None = None
    api_path: str | None = None

    def execute(
        self,
        task: RealWorldTask,
        selected_source_ids: tuple[str, ...],
        composed_context: str,
    ) -> dict[str, Any]:
        return {
            "executor": FIXTURE_EXECUTOR_NAME,
            "executor_mode": self.executor_mode,
            "provider": self.provider,
            "model": self.model,
            "api_path": self.api_path,
            "output": task.expected_answer,
            "output_parse_success": True,
            "output_parse_error": "",
            "actual_usage": None,
        }


def run_benchmark(
    tasks: list[RealWorldTask],
    repeat: int = 1,
    selector: RealWorldSelector | None = None,
    executor: RealWorldExecutor | None = None,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if not tasks:
        raise ValueError("At least one minimal real-world task is required.")

    selector = selector or FixtureRealWorldSelector()
    executor = executor or FixtureRealWorldExecutor()
    baseline_executor = FixtureRealWorldExecutor()
    runs: list[dict[str, Any]] = []
    for task in tasks:
        fixture_selection = fixture_source_selection(task)
        for repeat_index in range(1, repeat + 1):
            runs.append(
                execute_task(
                    task=task,
                    mode="baseline",
                    selection=all_source_selection(task),
                    fixture_selection=fixture_selection,
                    repeat_index=repeat_index,
                    executor=baseline_executor,
                )
            )
            selection = _select_with_fallback(task, selector, fixture_selection)
            runs.append(
                execute_task(
                    task=task,
                    mode="minimal_real_world_multi_zone",
                    selection=selection,
                    fixture_selection=fixture_selection,
                    repeat_index=repeat_index,
                    executor=executor,
                )
            )

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "task_count": len(tasks),
            "repeat": repeat,
            "run_count": len(runs),
            "selector_mode": getattr(selector, "selector_mode", selector.__class__.__name__),
            "selector_provider": getattr(selector, "provider", "deterministic_mock"),
            "selector_model": getattr(selector, "model", None),
            "selector_api_path": getattr(selector, "api_path", None),
            "executor_mode": getattr(executor, "executor_mode", executor.__class__.__name__),
            "executor_provider": getattr(executor, "provider", "deterministic_mock"),
            "executor_model": getattr(executor, "model", None),
            "executor_api_path": getattr(executor, "api_path", None),
        },
        "summary": summarize_runs(runs),
        "tasks": [task_to_dict(task) for task in tasks],
        "runs": runs,
    }


def _select_with_fallback(
    task: RealWorldTask,
    selector: RealWorldSelector,
    fixture_selection: dict[str, Any],
) -> dict[str, Any]:
    try:
        return selector.select(task, fixture_selection)
    except Exception as exc:
        fallback = dict(fixture_selection)
        fallback.update(
            {
                "selector": FALLBACK_SELECTOR_NAME,
                "selector_success": False,
                "selector_used_fallback": True,
                "selector_error": str(exc),
                "confidence": 0.0,
                "evidence_rationale": "Selector failed; fixture sources used for safe execution.",
            }
        )
        return fallback


def fixture_source_selection(task: RealWorldTask) -> dict[str, Any]:
    return FixtureRealWorldSelector().select(task, {})


def all_source_selection(task: RealWorldTask) -> dict[str, Any]:
    return build_selection(
        task=task,
        selected_sources=list(task.sources),
        selector_name="full_context_baseline",
        selector_success=True,
        selector_used_fallback=False,
        confidence=1.0,
        rationale="Baseline includes every source document.",
    )


def build_selection(
    *,
    task: RealWorldTask,
    selected_sources: list[RealWorldSource],
    selector_name: str,
    selector_success: bool,
    selector_used_fallback: bool,
    confidence: float,
    rationale: str,
    selector_error: str = "",
) -> dict[str, Any]:
    selected_source_ids = [source.source_id for source in selected_sources]
    source_roles = {source.source_id: source.role for source in selected_sources}
    selected_source_tokens = {
        source.source_id: estimate_tokens(format_source(source))
        for source in selected_sources
    }
    suppressed_sources = [
        source for source in task.sources if source.source_id not in selected_source_ids
    ]
    suppressed_source_tokens = {
        source.source_id: estimate_tokens(format_source(source))
        for source in suppressed_sources
    }
    return {
        "selector": selector_name,
        "selected_source_ids": selected_source_ids,
        "source_roles": source_roles,
        "confidence": float(confidence),
        "evidence_rationale": rationale,
        "selector_success": bool(selector_success),
        "selector_used_fallback": bool(selector_used_fallback),
        "selector_error": selector_error,
        "selected_source_token_estimates": selected_source_tokens,
        "suppressed_source_token_estimates": suppressed_source_tokens,
        "selected_source_token_estimate": sum(selected_source_tokens.values()),
        "suppressed_source_token_estimate": sum(suppressed_source_tokens.values()),
    }


def execute_task(
    *,
    task: RealWorldTask,
    mode: str,
    selection: dict[str, Any],
    fixture_selection: dict[str, Any],
    repeat_index: int,
    executor: RealWorldExecutor | None = None,
    output_override: str | None = None,
) -> dict[str, Any]:
    selected_source_ids = tuple(str(source_id) for source_id in selection["selected_source_ids"])
    composed_context = compose_context(task, selected_source_ids)
    baseline_context = compose_context(task, tuple(source.source_id for source in task.sources))
    executor = executor or FixtureRealWorldExecutor()
    if output_override is None:
        executor_result = executor.execute(task, selected_source_ids, composed_context)
    else:
        executor_result = {
            "executor": "test_output_override",
            "executor_mode": "test_override",
            "provider": "deterministic_test",
            "model": None,
            "api_path": None,
            "output": output_override,
            "output_parse_success": True,
            "output_parse_error": "",
            "actual_usage": None,
        }

    selection_validation = validate_selection(task, selection)
    output = str(executor_result["output"])
    output_validation = validate_output(task, output)
    full_context_tokens = estimate_tokens(baseline_context)
    composed_context_tokens = estimate_tokens(composed_context)
    token_reduction = percent_reduction(full_context_tokens, composed_context_tokens)
    honest_pass = bool(
        mode == "minimal_real_world_multi_zone"
        and selection["selector_success"] is True
        and selection["selector_used_fallback"] is False
        and selection_validation["required_source_complete"] is True
        and selection_validation["distractors_omitted"] is True
        and executor_result["output_parse_success"] is True
        and output_validation["passed"] is True
    )
    success = bool(
        output_validation["passed"]
        and executor_result["output_parse_success"]
        and (
            mode == "baseline"
            or (
                selection_validation["required_source_complete"]
                and selection_validation["distractors_omitted"]
            )
        )
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "fixture_id": task.fixture_id,
        "task_theme": task.task_theme,
        "mode": mode,
        "repeat_index": repeat_index,
        "selector": selection["selector"],
        "selector_success": selection["selector_success"],
        "selector_used_fallback": selection["selector_used_fallback"],
        "selector_error": selection["selector_error"],
        "confidence": selection["confidence"],
        "evidence_rationale": selection["evidence_rationale"],
        "selected_source_ids": list(selected_source_ids),
        "fixture_selected_source_ids": list(fixture_selection["selected_source_ids"]),
        "source_roles": selection["source_roles"],
        "required_source_ids": list(task.required_source_ids),
        "distractor_source_ids": list(task.distractor_source_ids),
        "selection_validation": selection_validation,
        "selector_validation_result": (
            "complete"
            if selection_validation["required_source_complete"]
            and selection_validation["distractors_omitted"]
            else "incomplete"
        ),
        "required_source_complete": selection_validation["required_source_complete"],
        "missing_required_source_ids": selection_validation["missing_required_source_ids"],
        "unexpected_distractor_source_ids": selection_validation[
            "unexpected_distractor_source_ids"
        ],
        "distractors_omitted": selection_validation["distractors_omitted"],
        "output_validation": output_validation,
        "output_validation_before_repair": output_validation["passed"],
        "output_validation_after_repair": None,
        "output_repair_attempted": False,
        "output_repair_status": "not_supported",
        "honest_minimal_real_world_pass_after_repair": None,
        "executor": executor_result["executor"],
        "executor_mode": executor_result["executor_mode"],
        "executor_provider": executor_result["provider"],
        "executor_model": executor_result["model"],
        "executor_api_path": executor_result["api_path"],
        "executor_output_parse_success": executor_result["output_parse_success"],
        "executor_output_parse_error": executor_result["output_parse_error"],
        "actual_usage": executor_result.get("actual_usage"),
        "honest_minimal_real_world_pass": honest_pass,
        "success": success,
        "output": output,
        "selected_source_token_estimate": int(selection["selected_source_token_estimate"]),
        "suppressed_source_token_estimate": int(selection["suppressed_source_token_estimate"]),
        "total_composed_context_token_estimate": composed_context_tokens,
        "full_context_baseline_token_estimate": full_context_tokens,
        "token_reduction_percent": token_reduction,
        "selected_source_token_estimates": selection["selected_source_token_estimates"],
        "suppressed_source_token_estimates": selection["suppressed_source_token_estimates"],
    }


def validate_selection(task: RealWorldTask, selection: dict[str, Any]) -> dict[str, Any]:
    selected = tuple(str(source_id) for source_id in selection["selected_source_ids"])
    selected_set = set(selected)
    required_set = set(task.required_source_ids)
    missing_required = [
        source_id for source_id in task.required_source_ids if source_id not in selected_set
    ]
    unexpected_distractors = [
        source_id for source_id in task.distractor_source_ids if source_id in selected_set
    ]
    role_checks = {
        source_id: selection.get("source_roles", {}).get(source_id)
        == source_by_id(task, source_id).role
        for source_id in selected
    }
    composed_context = compose_context(task, selected)
    target_checks = {
        field_name: expected_value.lower() in composed_context.lower()
        for field_name, expected_value in task.expected_fields.items()
    }
    required_source_complete = (
        not missing_required
        and len(required_set & selected_set) == len(task.required_source_ids)
        and all(role_checks.values())
        and all(target_checks.values())
    )
    return {
        "required_source_complete": required_source_complete,
        "distractors_omitted": not unexpected_distractors,
        "selected_required_source_count": len(required_set & selected_set),
        "required_source_count": len(task.required_source_ids),
        "missing_required_source_ids": missing_required,
        "unexpected_distractor_source_ids": unexpected_distractors,
        "role_checks": role_checks,
        "source_roles_valid": all(role_checks.values()),
        "target_checks": target_checks,
        "contains_all_context_targets": all(target_checks.values()),
    }


def validate_output(task: RealWorldTask, output: str) -> dict[str, Any]:
    normalized = output.lower()
    field_checks = [
        {
            "field": field_name,
            "target": expected_value,
            "passed": expected_value.lower() in normalized,
        }
        for field_name, expected_value in task.expected_fields.items()
    ]
    evidence_refs = _extract_csv_field(output, "evidence_source_ids")
    expected_evidence = set(task.required_source_ids)
    actual_evidence = set(evidence_refs)
    evidence_validation = {
        "passed": actual_evidence == expected_evidence,
        "expected_source_ids": list(task.required_source_ids),
        "actual_source_ids": evidence_refs,
        "missing_source_ids": [
            source_id for source_id in task.required_source_ids if source_id not in actual_evidence
        ],
        "unexpected_source_ids": [
            source_id for source_id in evidence_refs if source_id not in expected_evidence
        ],
    }
    return {
        "passed": (
            bool(output.strip())
            and all(check["passed"] for check in field_checks)
            and evidence_validation["passed"]
        ),
        "field_checks": field_checks,
        "evidence_reference_validation": evidence_validation,
        "missing_fields": [
            check["field"] for check in field_checks if not check["passed"]
        ],
    }


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_runs = [run for run in runs if run["mode"] == "baseline"]
    real_world_runs = [run for run in runs if run["mode"] == "minimal_real_world_multi_zone"]
    return {
        "run_count": len(runs),
        "baseline_run_count": len(baseline_runs),
        "minimal_real_world_run_count": len(real_world_runs),
        "source_selection_success_rate": _rate(
            run["selector_success"] is True for run in real_world_runs
        ),
        "required_source_completeness_rate": _rate(
            run["required_source_complete"] is True for run in real_world_runs
        ),
        "distractor_rejection_rate": _rate(
            run["distractors_omitted"] is True for run in real_world_runs
        ),
        "fallback_count": sum(1 for run in real_world_runs if run["selector_used_fallback"]),
        "output_validation_complete_rate": _rate(
            run["output_validation_before_repair"] is True for run in real_world_runs
        ),
        "output_validation_after_repair_rate": None,
        "executor_output_parse_success_rate": _rate(
            run["executor_output_parse_success"] is True for run in real_world_runs
        ),
        "honest_minimal_real_world_pass_count": sum(
            1 for run in real_world_runs if run["honest_minimal_real_world_pass"]
        ),
        "honest_minimal_real_world_pass_rate": _rate(
            run["honest_minimal_real_world_pass"] is True for run in real_world_runs
        ),
        "average_full_context_baseline_tokens": _average(
            run["full_context_baseline_token_estimate"] for run in real_world_runs
        ),
        "average_selected_source_tokens": _average(
            run["selected_source_token_estimate"] for run in real_world_runs
        ),
        "average_suppressed_source_tokens": _average(
            run["suppressed_source_token_estimate"] for run in real_world_runs
        ),
        "average_composed_context_tokens": _average(
            run["total_composed_context_token_estimate"] for run in real_world_runs
        ),
        "average_token_reduction_percent": _average(
            run["token_reduction_percent"] for run in real_world_runs
            if run["token_reduction_percent"] is not None
        ),
        "actual_usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
        "fixtures": _summarize_fixtures(real_world_runs),
    }


def _summarize_fixtures(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixture_ids = sorted({run["fixture_id"] for run in runs})
    summaries: list[dict[str, Any]] = []
    for fixture_id in fixture_ids:
        fixture_runs = [run for run in runs if run["fixture_id"] == fixture_id]
        first = fixture_runs[0]
        summaries.append(
            {
                "fixture_id": fixture_id,
                "task_theme": first["task_theme"],
                "run_count": len(fixture_runs),
                "selected_source_ids": first["selected_source_ids"],
                "required_source_complete": all(
                    run["required_source_complete"] for run in fixture_runs
                ),
                "distractors_omitted": all(
                    run["distractors_omitted"] for run in fixture_runs
                ),
                "fallback_used": any(run["selector_used_fallback"] for run in fixture_runs),
                "honest_minimal_real_world_pass_count": sum(
                    1 for run in fixture_runs if run["honest_minimal_real_world_pass"]
                ),
                "honest_minimal_real_world_pass_rate": _rate(
                    run["honest_minimal_real_world_pass"] is True for run in fixture_runs
                ),
                "average_token_reduction_percent": _average(
                    run["token_reduction_percent"] for run in fixture_runs
                    if run["token_reduction_percent"] is not None
                ),
            }
        )
    return summaries


def task_to_dict(task: RealWorldTask) -> dict[str, Any]:
    data = asdict(task)
    data["full_context_baseline_token_estimate"] = estimate_tokens(
        compose_context(task, tuple(source.source_id for source in task.sources))
    )
    data["required_composed_context_token_estimate"] = estimate_tokens(
        compose_context(task, task.required_source_ids)
    )
    return data


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Minimal Real-World Inspired Multi-Zone Benchmark",
        "",
        "This is a controlled, minimal real-world inspired benchmark. It tests "
        "multi-zone composition over realistic project-like context, not broad "
        "real-world generalization.",
        "",
        "Deterministic validation is the source of truth. Success requires all "
        "required sources, no distractors, all required facts, and exact evidence "
        "source IDs.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Selector mode: `{report['metadata']['selector_mode']}`",
        f"Selector provider: `{report['metadata']['selector_provider']}`",
        f"Executor mode: `{report['metadata']['executor_mode']}`",
        f"Executor provider: `{report['metadata']['executor_provider']}`",
        f"Runs: {summary['run_count']}",
        "",
        "## Summary",
        "",
        f"Honest minimal real-world pass rate: {_format_percent(summary['honest_minimal_real_world_pass_rate'])}",
        f"Required source completeness rate: {_format_percent(summary['required_source_completeness_rate'])}",
        f"Distractor rejection rate: {_format_percent(summary['distractor_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Output validation complete rate: {_format_percent(summary['output_validation_complete_rate'])}",
        f"Output validation after repair rate: {_format_optional_percent(summary['output_validation_after_repair_rate'])}",
        "Output repair status: not_supported",
        f"Average token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Estimated Token Accounting",
        "",
        "| Metric | Estimated tokens |",
        "| --- | ---: |",
        f"| Full-context baseline | {summary['average_full_context_baseline_tokens']:.2f} |",
        f"| Selected sources | {summary['average_selected_source_tokens']:.2f} |",
        f"| Suppressed sources | {summary['average_suppressed_source_tokens']:.2f} |",
        f"| Composed context | {summary['average_composed_context_tokens']:.2f} |",
        "",
        "## Fixtures",
        "",
        "| Fixture ID | Theme | Selected sources | Complete | Distractors omitted | Fallback used | Honest pass rate | Token reduction |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fixture in summary["fixtures"]:
        lines.append(
            f"| `{fixture['fixture_id']}` | "
            f"`{fixture['task_theme']}` | "
            f"{', '.join(fixture['selected_source_ids'])} | "
            f"{fixture['required_source_complete']} | "
            f"{fixture['distractors_omitted']} | "
            f"{fixture['fallback_used']} | "
            f"{_format_percent(fixture['honest_minimal_real_world_pass_rate'])} | "
            f"{_format_optional_percent(fixture['average_token_reduction_percent'])} |"
        )
    lines.extend(
        [
            "",
            "## Runs",
            "",
            "| Fixture | Mode | Selector validation | Honest pass | Selected sources | Missing required | Distractors selected | Token reduction |",
            "| --- | --- | --- | ---: | --- | --- | --- | ---: |",
        ]
    )
    for run in report["runs"]:
        lines.append(
            f"| `{run['fixture_id']}` | `{run['mode']}` | "
            f"{run['selector_validation_result']} | "
            f"{run['honest_minimal_real_world_pass']} | "
            f"{', '.join(run['selected_source_ids'])} | "
            f"{', '.join(run['missing_required_source_ids']) or 'none'} | "
            f"{', '.join(run['unexpected_distractor_source_ids']) or 'none'} | "
            f"{_format_optional_percent(run['token_reduction_percent'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Minimal real-world inspired multi-zone benchmark")
    print(f"selector mode: {report['metadata']['selector_mode']}")
    print(f"selector provider: {report['metadata']['selector_provider']}")
    print(f"executor mode: {report['metadata']['executor_mode']}")
    print(f"executor provider: {report['metadata']['executor_provider']}")
    print(f"runs: {summary['run_count']}")
    print(
        "honest minimal real-world pass rate: "
        f"{_format_percent(summary['honest_minimal_real_world_pass_rate'])}"
    )
    print(
        "required source completeness rate: "
        f"{_format_percent(summary['required_source_completeness_rate'])}"
    )
    print(f"fallback count: {summary['fallback_count']}")
    print(
        "average token reduction: "
        f"{_format_optional_percent(summary['average_token_reduction_percent'])}"
    )
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def compose_context(task: RealWorldTask, source_ids: tuple[str, ...]) -> str:
    lines: list[str] = []
    for source_id in source_ids:
        source = source_by_id(task, source_id)
        lines.append(format_source(source))
    return "\n\n".join(lines)


def format_source(source: RealWorldSource) -> str:
    return "\n".join(
        [
            f"SOURCE ID: {source.source_id}",
            f"SOURCE ROLE: {source.role}",
            f"TITLE: {source.title}",
            source.text,
        ]
    )


def source_by_id(task: RealWorldTask, source_id: str) -> RealWorldSource:
    for source in task.sources:
        if source.source_id == source_id:
            return source
    raise KeyError(f"Unknown source ID: {source_id}")


def _source(
    source_id: str,
    role: str,
    title: str,
    text: str,
    *,
    required: bool = False,
    distractor: bool = False,
) -> RealWorldSource:
    return RealWorldSource(
        source_id=source_id,
        role=role,
        title=title,
        text=text,
        required=required,
        distractor=distractor,
    )


def _answer_from_fields(
    expected_fields: dict[str, str],
    evidence_source_ids: tuple[str, ...],
) -> str:
    lines = [f"{field}: {value}" for field, value in expected_fields.items()]
    lines.append(f"evidence_source_ids: {', '.join(evidence_source_ids)}")
    return "\n".join(lines)


def _extract_csv_field(output: str, field_name: str) -> list[str]:
    prefix = f"{field_name}:"
    for line in output.splitlines():
        if line.lower().startswith(prefix.lower()):
            raw = line.split(":", 1)[1]
            return [item.strip() for item in raw.split(",") if item.strip()]
    return []


def estimate_tokens(text: str) -> int:
    return estimate_text_tokens(text)


def _average(values: Any) -> float:
    numbers = [float(value) for value in values]
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


def _rate(values: Any) -> float:
    items = list(values)
    if not items:
        return 0.0
    return sum(1 for item in items if bool(item)) / len(items)


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_optional_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


if __name__ == "__main__":
    main()
