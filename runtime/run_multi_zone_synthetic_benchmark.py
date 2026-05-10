"""Run the first small multi-zone synthetic benchmark.

This benchmark is intentionally deterministic. It tests whether SFE-style
selection can compose several role-specific zones instead of selecting one
authoritative block. No provider calls are made.
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


BENCHMARK_TYPE = "multi_zone/synthetic"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "multi_zone_synthetic_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "multi_zone_synthetic_benchmark.md"
FIXTURE_SELECTOR_NAME = "fixture_multi_zone_selector"
FALLBACK_SELECTOR_NAME = "fixture_fallback_after_selector_error"


@dataclass(frozen=True)
class MultiZoneContextZone:
    zone_id: str
    role: str
    title: str
    text: str
    required: bool = False
    distractor: bool = False


@dataclass(frozen=True)
class MultiZoneTask:
    task_label: str
    question: str
    zones: tuple[MultiZoneContextZone, ...]
    required_zone_ids: tuple[str, ...]
    distractor_zone_ids: tuple[str, ...]
    validation_targets: tuple[str, ...]
    expected_answer: str
    required_evidence: dict[str, tuple[str, ...]]


class MultiZoneSelector(Protocol):
    def select(self, task: MultiZoneTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        ...


def main() -> None:
    args = _parse_args()
    tasks = get_multi_zone_synthetic_tasks()
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
        description="Run the deterministic multi-zone synthetic benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def get_multi_zone_synthetic_tasks() -> list[MultiZoneTask]:
    """Return the first deterministic Phase 2 multi-zone fixture."""

    return [
        MultiZoneTask(
            task_label="multi_zone_synthetic_aurora_release_gate",
            question=(
                "For the Aurora release gate, produce the active launch decision: "
                "which version is active, what rollback threshold applies, which "
                "dataset is excluded, who approves the launch, what mitigation "
                "label must ship, and what governed request class is in scope?"
            ),
            zones=(
                _zone(
                    "intent-aurora-gate",
                    "task_intent",
                    "Aurora Release Gate User Intent",
                    (
                        "The user needs the active launch decision for the Aurora release gate. "
                        "The final answer must include active version, rollback threshold, excluded "
                        "dataset, launch approval owner, mitigation label, governed request class, "
                        "and evidence zone references. This zone defines the requested fields but "
                        "does not contain the approved values."
                    ),
                    required=True,
                ),
                _zone(
                    "constraints-aurora-active",
                    "hard_constraints",
                    "Aurora Active Constraint Record",
                    (
                        "Use only the active release record for version AUR-2026.09-mz2. "
                        "Ignore draft version AUR-2026.09-mz1 and any table marked obsolete. "
                        "The answer must preserve internal identifiers exactly and must not "
                        "replace owner IDs with display names."
                    ),
                    required=True,
                ),
                _zone(
                    "domain-aurora-governance",
                    "domain_context",
                    "Aurora Governance Domain Context",
                    (
                        "Aurora release gates are evaluated only for customer-visible writes. "
                        "Read-only probes, internal replay checks, and dashboard simulations are "
                        "outside the governed request class. Rollback thresholds are expressed "
                        "as p99 coordination cost per thousand governed requests."
                    ),
                    required=True,
                ),
                _zone(
                    "evidence-aurora-final",
                    "evidence_records",
                    "Aurora Final Evidence Records",
                    (
                        "For AUR-2026.09-mz2, rollback applies when p99 coordination cost "
                        "exceeds 27.4 credits per thousand governed requests for three consecutive "
                        "ten-minute windows. The excluded replay dataset is RavenReplay-204. "
                        "Final approval owner is AURORA_OWNER_MZ2. The mitigation label that must "
                        "ship is aurora_mz2_epoch_lock. These values supersede earlier mz1 drafts."
                    ),
                    required=True,
                ),
                _zone(
                    "distractor-aurora-mz1-draft",
                    "obsolete_conflict",
                    "Aurora MZ1 Draft Values",
                    (
                        "The obsolete AUR-2026.09-mz1 draft proposed rollback above 24.1 credits, "
                        "excluded RavenReplay-177, named AURORA_OWNER_MZ1, and used mitigation "
                        "label aurora_mz1_window_cap. It is plausible but not active."
                    ),
                    distractor=True,
                ),
                _zone(
                    "distractor-aurora-dashboard",
                    "partial_distractor",
                    "Aurora Dashboard Field Checklist",
                    (
                        "The dashboard checklist lists fields for active version, rollback threshold, "
                        "dataset exclusion, owner, mitigation label, and governed request class. It "
                        "does not provide the approved values and must not be used as the answer."
                    ),
                    distractor=True,
                ),
            ),
            required_zone_ids=(
                "intent-aurora-gate",
                "constraints-aurora-active",
                "domain-aurora-governance",
                "evidence-aurora-final",
            ),
            distractor_zone_ids=(
                "distractor-aurora-mz1-draft",
                "distractor-aurora-dashboard",
            ),
            validation_targets=(
                "AUR-2026.09-mz2",
                "27.4",
                "RavenReplay-204",
                "AURORA_OWNER_MZ2",
                "aurora_mz2_epoch_lock",
                "customer-visible writes",
                "intent-aurora-gate",
                "constraints-aurora-active",
                "domain-aurora-governance",
                "evidence-aurora-final",
            ),
            expected_answer=(
                "active_version: AUR-2026.09-mz2\n"
                "rollback_threshold: 27.4 credits per thousand governed requests for three consecutive ten-minute windows\n"
                "excluded_dataset: RavenReplay-204\n"
                "launch_approval_owner: AURORA_OWNER_MZ2\n"
                "mitigation_label: aurora_mz2_epoch_lock\n"
                "governed_request_class: customer-visible writes\n"
                "evidence_zone_ids: intent-aurora-gate, constraints-aurora-active, "
                "domain-aurora-governance, evidence-aurora-final"
            ),
            required_evidence={
                "active_version": ("constraints-aurora-active", "evidence-aurora-final"),
                "rollback_threshold": ("evidence-aurora-final",),
                "excluded_dataset": ("evidence-aurora-final",),
                "approval_owner": ("evidence-aurora-final",),
                "mitigation_label": ("evidence-aurora-final",),
                "governed_request_class": ("domain-aurora-governance",),
                "requested_fields": ("intent-aurora-gate",),
            },
        )
    ]


def _zone(
    zone_id: str,
    role: str,
    title: str,
    text: str,
    required: bool = False,
    distractor: bool = False,
) -> MultiZoneContextZone:
    return MultiZoneContextZone(
        zone_id=zone_id,
        role=role,
        title=title,
        text=text,
        required=required,
        distractor=distractor,
    )


def run_benchmark(
    tasks: list[MultiZoneTask],
    repeat: int = 1,
    selector: MultiZoneSelector | None = None,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if not tasks:
        raise ValueError("At least one multi-zone task is required.")

    runs: list[dict[str, Any]] = []
    selector = selector or FixtureMultiZoneSelector()
    for task in tasks:
        fixture_selection = fixture_zone_selection(task)
        for repeat_index in range(1, repeat + 1):
            runs.append(
                execute_task(
                    task=task,
                    mode="baseline",
                    selection=all_zone_selection(task),
                    fixture_selection=fixture_selection,
                    repeat_index=repeat_index,
                )
            )
            selection = _select_with_fallback(task, selector, fixture_selection)
            runs.append(
                execute_task(
                    task=task,
                    mode="spatial_multi_zone",
                    selection=selection,
                    fixture_selection=fixture_selection,
                    repeat_index=repeat_index,
                )
            )

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_type": BENCHMARK_TYPE,
            "task_count": len(tasks),
            "repeat": repeat,
            "run_count": len(runs),
            "selector": selector.__class__.__name__,
            "provider": "deterministic_mock",
        },
        "summary": summarize_runs(runs),
        "tasks": [task_to_dict(task) for task in tasks],
        "runs": runs,
    }


class FixtureMultiZoneSelector:
    """Deterministic selector for the known complete zone set."""

    def select(self, task: MultiZoneTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        selected_zones = [zone_by_id(task, zone_id) for zone_id in task.required_zone_ids]
        return build_selection(
            task=task,
            selected_zones=selected_zones,
            selector_name=FIXTURE_SELECTOR_NAME,
            selector_success=True,
            selector_used_fallback=False,
            confidence=1.0,
            rationale=(
                "Selected intent, constraints, domain context, and final evidence because "
                "no single zone contains the complete answer."
            ),
        )


def _select_with_fallback(
    task: MultiZoneTask,
    selector: MultiZoneSelector,
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
                "evidence_rationale": "Selector failed; fixture zones used for safe execution.",
            }
        )
        return fallback


def fixture_zone_selection(task: MultiZoneTask) -> dict[str, Any]:
    return FixtureMultiZoneSelector().select(task, {})


def all_zone_selection(task: MultiZoneTask) -> dict[str, Any]:
    return build_selection(
        task=task,
        selected_zones=list(task.zones),
        selector_name="full_context_baseline",
        selector_success=True,
        selector_used_fallback=False,
        confidence=1.0,
        rationale="Baseline includes every zone.",
    )


def build_selection(
    *,
    task: MultiZoneTask,
    selected_zones: list[MultiZoneContextZone],
    selector_name: str,
    selector_success: bool,
    selector_used_fallback: bool,
    confidence: float,
    rationale: str,
    selector_error: str = "",
) -> dict[str, Any]:
    selected_zone_ids = [zone.zone_id for zone in selected_zones]
    zone_roles = {zone.zone_id: zone.role for zone in selected_zones}
    selected_zone_tokens = {
        zone.zone_id: estimate_tokens(format_zone(zone)) for zone in selected_zones
    }
    suppressed_zones = [zone for zone in task.zones if zone.zone_id not in selected_zone_ids]
    suppressed_zone_tokens = {
        zone.zone_id: estimate_tokens(format_zone(zone)) for zone in suppressed_zones
    }
    return {
        "selector": selector_name,
        "selected_zone_ids": selected_zone_ids,
        "zone_roles": zone_roles,
        "confidence": float(confidence),
        "evidence_rationale": rationale,
        "selector_success": bool(selector_success),
        "selector_used_fallback": bool(selector_used_fallback),
        "selector_error": selector_error,
        "selected_zone_token_estimates": selected_zone_tokens,
        "suppressed_zone_token_estimates": suppressed_zone_tokens,
        "selected_zone_token_estimate": sum(selected_zone_tokens.values()),
        "suppressed_zone_token_estimate": sum(suppressed_zone_tokens.values()),
    }


def execute_task(
    *,
    task: MultiZoneTask,
    mode: str,
    selection: dict[str, Any],
    fixture_selection: dict[str, Any],
    repeat_index: int,
    output_override: str | None = None,
) -> dict[str, Any]:
    selected_zone_ids = tuple(str(zone_id) for zone_id in selection["selected_zone_ids"])
    composed_context = compose_context(task, selected_zone_ids)
    baseline_context = compose_context(task, tuple(zone.zone_id for zone in task.zones))
    output = output_override if output_override is not None else task.expected_answer
    selection_validation = validate_selection(task, selection)
    output_validation = validate_output(task, output)
    full_context_tokens = estimate_tokens(baseline_context)
    composed_context_tokens = estimate_tokens(composed_context)
    token_reduction = percent_reduction(full_context_tokens, composed_context_tokens)
    honest_multi_zone_pass = bool(
        mode == "spatial_multi_zone"
        and selection.get("selector_success") is True
        and selection.get("selector_used_fallback") is False
        and selection_validation["selected_zone_complete"] is True
        and selection_validation["distractors_omitted"] is True
        and output_validation["passed"] is True
    )
    success = bool(
        output_validation["passed"]
        and (
            mode == "baseline"
            or (
                selection_validation["selected_zone_complete"]
                and selection_validation["distractors_omitted"]
            )
        )
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "task_label": task.task_label,
        "mode": mode,
        "repeat_index": repeat_index,
        "selector": selection["selector"],
        "selector_success": selection["selector_success"],
        "selector_used_fallback": selection["selector_used_fallback"],
        "selector_error": selection["selector_error"],
        "confidence": selection["confidence"],
        "evidence_rationale": selection["evidence_rationale"],
        "selected_zone_ids": list(selected_zone_ids),
        "fixture_selected_zone_ids": list(fixture_selection["selected_zone_ids"]),
        "zone_roles": selection["zone_roles"],
        "required_zone_ids": list(task.required_zone_ids),
        "distractor_zone_ids": list(task.distractor_zone_ids),
        "selection_validation": selection_validation,
        "selected_zone_complete": selection_validation["selected_zone_complete"],
        "missing_required_zone_ids": selection_validation["missing_required_zone_ids"],
        "unexpected_distractor_zone_ids": selection_validation["unexpected_distractor_zone_ids"],
        "distractors_omitted": selection_validation["distractors_omitted"],
        "output_validation": output_validation,
        "output_validation_status": "complete" if output_validation["passed"] else "incomplete",
        "output_validation_before_repair": output_validation["passed"],
        "output_validation_after_repair": None,
        "output_repair_attempted": False,
        "output_repair_status": "not_supported",
        "honest_multi_zone_pass_after_repair": None,
        "honest_multi_zone_pass": honest_multi_zone_pass,
        "success": success,
        "output": output,
        "selected_zone_token_estimate": int(selection["selected_zone_token_estimate"]),
        "suppressed_zone_token_estimate": int(selection["suppressed_zone_token_estimate"]),
        "total_composed_context_token_estimate": composed_context_tokens,
        "full_context_baseline_token_estimate": full_context_tokens,
        "token_reduction_percent": token_reduction,
        "selected_zone_token_estimates": selection["selected_zone_token_estimates"],
        "suppressed_zone_token_estimates": selection["suppressed_zone_token_estimates"],
    }


def compose_context(task: MultiZoneTask, selected_zone_ids: tuple[str, ...]) -> str:
    zones = [zone_by_id(task, zone_id) for zone_id in selected_zone_ids]
    parts = [
        f"ZONE ROLE: {zone.role}\nZONE ID: {zone.zone_id}\nTITLE: {zone.title}\n{zone.text}"
        for zone in zones
    ]
    return "\n\n".join(parts)


def format_zone(zone: MultiZoneContextZone) -> str:
    return f"ZONE {zone.zone_id} ({zone.role}) - {zone.title}\n{zone.text}"


def zone_by_id(task: MultiZoneTask, zone_id: str) -> MultiZoneContextZone:
    for zone in task.zones:
        if zone.zone_id == zone_id:
            return zone
    allowed = ", ".join(zone.zone_id for zone in task.zones)
    raise ValueError(f"Unknown zone_id {zone_id!r}; expected one of: {allowed}")


def validate_selection(task: MultiZoneTask, selection: dict[str, Any]) -> dict[str, Any]:
    selected = tuple(str(zone_id) for zone_id in selection["selected_zone_ids"])
    selected_set = set(selected)
    required_set = set(task.required_zone_ids)
    missing_required = tuple(
        zone_id for zone_id in task.required_zone_ids if zone_id not in selected_set
    )
    unexpected_distractors = tuple(
        zone_id for zone_id in task.distractor_zone_ids if zone_id in selected_set
    )
    composed_context = compose_context(task, selected)
    evidence_checks = {
        field_name: all(zone_id in selected_set for zone_id in zone_ids)
        for field_name, zone_ids in task.required_evidence.items()
    }
    target_checks = {
        target: str(target).lower() in composed_context.lower()
        for target in task.validation_targets
        if target not in task.required_zone_ids
    }
    selected_zone_complete = (
        not missing_required
        and all(evidence_checks.values())
        and all(target_checks.values())
    )
    return {
        "selected_zone_complete": selected_zone_complete,
        "distractors_omitted": not unexpected_distractors,
        "selected_required_zone_count": len(required_set & selected_set),
        "required_zone_count": len(task.required_zone_ids),
        "missing_required_zone_ids": list(missing_required),
        "unexpected_distractor_zone_ids": list(unexpected_distractors),
        "evidence_checks": evidence_checks,
        "target_checks": target_checks,
        "contains_all_context_targets": all(target_checks.values()),
    }


def validate_output(task: MultiZoneTask, output: str) -> dict[str, Any]:
    normalized = output.lower()
    checks = [
        {"target": target, "passed": str(target).lower() in normalized}
        for target in task.validation_targets
    ]
    evidence_refs = _extract_csv_field(output, "evidence_zone_ids")
    expected_evidence_refs = set(task.required_zone_ids)
    actual_evidence_refs = set(evidence_refs)
    evidence_reference_validation = {
        "passed": actual_evidence_refs == expected_evidence_refs,
        "expected_zone_ids": list(task.required_zone_ids),
        "actual_zone_ids": evidence_refs,
        "missing_zone_ids": [
            zone_id for zone_id in task.required_zone_ids if zone_id not in actual_evidence_refs
        ],
        "unexpected_zone_ids": [
            zone_id for zone_id in evidence_refs if zone_id not in expected_evidence_refs
        ],
    }
    return {
        "passed": (
            bool(output.strip())
            and all(check["passed"] for check in checks)
            and evidence_reference_validation["passed"]
        ),
        "checks": checks,
        "evidence_reference_validation": evidence_reference_validation,
        "missing_targets": [check["target"] for check in checks if not check["passed"]],
    }


def _extract_csv_field(output: str, field_name: str) -> list[str]:
    expected_label = field_name.strip().lower()
    for line in output.splitlines():
        label, separator, value = line.partition(":")
        if separator and label.strip().lower() == expected_label:
            return [item.strip() for item in value.split(",") if item.strip()]
    return []


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_runs = [run for run in runs if run["mode"] == "baseline"]
    spatial_runs = [run for run in runs if run["mode"] == "spatial_multi_zone"]
    return {
        "run_count": len(runs),
        "baseline_run_count": len(baseline_runs),
        "spatial_multi_zone_run_count": len(spatial_runs),
        "zone_selection_success_rate": _rate(
            run["selector_success"] is True for run in spatial_runs
        ),
        "selected_zone_completeness_rate": _rate(
            run["selected_zone_complete"] is True for run in spatial_runs
        ),
        "distractor_rejection_rate": _rate(
            run["distractors_omitted"] is True for run in spatial_runs
        ),
        "fallback_count": sum(1 for run in spatial_runs if run["selector_used_fallback"]),
        "fallback_rate": _rate(run["selector_used_fallback"] is True for run in spatial_runs),
        "output_validation_complete_rate": _rate(
            run["output_validation_before_repair"] is True for run in spatial_runs
        ),
        "output_validation_after_repair_rate": None,
        "honest_multi_zone_pass_count": sum(
            1 for run in spatial_runs if run["honest_multi_zone_pass"]
        ),
        "honest_multi_zone_pass_rate": _rate(
            run["honest_multi_zone_pass"] is True for run in spatial_runs
        ),
        "average_full_context_baseline_tokens": _average(
            run["full_context_baseline_token_estimate"] for run in spatial_runs
        ),
        "average_selected_zone_tokens": _average(
            run["selected_zone_token_estimate"] for run in spatial_runs
        ),
        "average_suppressed_zone_tokens": _average(
            run["suppressed_zone_token_estimate"] for run in spatial_runs
        ),
        "average_composed_context_tokens": _average(
            run["total_composed_context_token_estimate"] for run in spatial_runs
        ),
        "average_token_reduction_percent": _average(
            run["token_reduction_percent"] for run in spatial_runs
            if run["token_reduction_percent"] is not None
        ),
    }


def task_to_dict(task: MultiZoneTask) -> dict[str, Any]:
    data = asdict(task)
    data["full_context_baseline_token_estimate"] = estimate_tokens(
        compose_context(task, tuple(zone.zone_id for zone in task.zones))
    )
    data["required_composed_context_token_estimate"] = estimate_tokens(
        compose_context(task, task.required_zone_ids)
    )
    return data


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Multi-Zone Synthetic Benchmark",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"Runs: {summary['run_count']}",
        "",
        "## Summary",
        "",
        f"Honest multi-zone pass rate: {_format_percent(summary['honest_multi_zone_pass_rate'])}",
        f"Zone selection success rate: {_format_percent(summary['zone_selection_success_rate'])}",
        f"Selected-zone completeness rate: {_format_percent(summary['selected_zone_completeness_rate'])}",
        f"Distractor rejection rate: {_format_percent(summary['distractor_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Output validation complete rate: {_format_percent(summary['output_validation_complete_rate'])}",
        f"Average token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Estimated Token Accounting",
        "",
        "| Metric | Estimated tokens |",
        "| --- | ---: |",
        f"| Full-context baseline | {summary['average_full_context_baseline_tokens']:.2f} |",
        f"| Selected zones | {summary['average_selected_zone_tokens']:.2f} |",
        f"| Suppressed zones | {summary['average_suppressed_zone_tokens']:.2f} |",
        f"| Composed context | {summary['average_composed_context_tokens']:.2f} |",
        "",
        "## Runs",
        "",
        "| Task | Mode | Honest pass | Selected zones | Missing required | Distractors selected | Token reduction |",
        "| --- | --- | ---: | --- | --- | --- | ---: |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['task_label']}` | `{run['mode']}` | "
            f"{run['honest_multi_zone_pass']} | "
            f"{', '.join(run['selected_zone_ids'])} | "
            f"{', '.join(run['missing_required_zone_ids']) or 'none'} | "
            f"{', '.join(run['unexpected_distractor_zone_ids']) or 'none'} | "
            f"{_format_optional_percent(run['token_reduction_percent'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Multi-zone synthetic benchmark")
    print(f"runs: {summary['run_count']}")
    print(
        "honest multi-zone pass rate: "
        f"{_format_percent(summary['honest_multi_zone_pass_rate'])}"
    )
    print(
        "selected-zone completeness rate: "
        f"{_format_percent(summary['selected_zone_completeness_rate'])}"
    )
    print(f"fallback count: {summary['fallback_count']}")
    print(
        "average token reduction: "
        f"{_format_optional_percent(summary['average_token_reduction_percent'])}"
    )
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def estimate_tokens(text: str) -> int:
    return estimate_text_tokens(text)


def _rate(values: Any) -> float | None:
    items = list(values)
    if not items:
        return None
    return sum(1 for value in items if value) / len(items)


def _average(values: Any) -> float:
    numbers = [float(value) for value in values]
    if not numbers:
        return 0.0
    return sum(numbers) / len(numbers)


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
