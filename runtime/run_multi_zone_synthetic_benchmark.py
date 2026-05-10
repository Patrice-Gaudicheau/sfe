"""Run the first small multi-zone synthetic benchmark.

This benchmark is intentionally deterministic. It tests whether SFE-style
selection can compose several role-specific zones instead of selecting one
authoritative block. No provider calls are made.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.metrics import estimate_text_tokens, percent_reduction, write_json_report, write_text_report
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_API_PROVIDER,
    OpenAIAPIProvider,
)
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/synthetic"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "multi_zone_synthetic_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "multi_zone_synthetic_benchmark.md"
FIXTURE_SELECTOR_NAME = "fixture_multi_zone_selector"
FALLBACK_SELECTOR_NAME = "fixture_fallback_after_selector_error"
OPENAI_SELECTOR_NAME = "openai_selector_smoke"
OPENAI_SELECTOR_API_PATH = "/v1/responses"
DEFAULT_OPENAI_SELECTOR_MAX_TOKENS = 800


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
    selector = _build_selector_from_args(args)
    tasks = get_multi_zone_synthetic_tasks()
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1 when provided.")
        tasks = tasks[: args.limit]
    report = run_benchmark(tasks=tasks, repeat=args.repeat, selector=selector)
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic multi-zone synthetic benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--selector",
        choices=("fixture", "openai"),
        default="fixture",
        help="Selector path to use. Default fixture mode makes no provider calls.",
    )
    parser.add_argument(
        "--model",
        help=(
            "OpenAI selector model for --selector openai. Defaults to "
            "SFE_OPENAI_ROUTER_MODEL, then the provider router default."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        help="OpenAI API timeout in seconds for --selector openai.",
    )
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_OPENAI_SELECTOR_MAX_TOKENS,
        help="Maximum selector response tokens for --selector openai.",
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def _build_selector_from_args(args: argparse.Namespace) -> MultiZoneSelector:
    if args.selector == "fixture":
        return FixtureMultiZoneSelector()
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_OPENAI_ROUTER_MODEL
    return OpenAISelectorSmoke(
        model=model,
        timeout=args.timeout,
        max_output_tokens=args.max_output_tokens,
    )


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
            "selector_mode": getattr(selector, "selector_mode", selector.__class__.__name__),
            "provider": getattr(selector, "provider", "deterministic_mock"),
            "model": getattr(selector, "model", None),
            "api_path": getattr(selector, "api_path", None),
            "executor": "deterministic_fixture",
        },
        "summary": summarize_runs(runs),
        "tasks": [task_to_dict(task) for task in tasks],
        "runs": runs,
    }


class FixtureMultiZoneSelector:
    """Deterministic selector for the known complete zone set."""

    provider = "deterministic_mock"
    selector_mode = "fixture"
    model: str | None = None
    api_path: str | None = None

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


class OpenAISelectorSmoke:
    """OpenAI-backed selector smoke path; executor output remains deterministic."""

    provider = OPENAI_API_PROVIDER
    selector_mode = "openai_selector_smoke"
    api_path = OPENAI_SELECTOR_API_PATH

    def __init__(
        self,
        model: str,
        timeout: float | None = None,
        max_output_tokens: int = DEFAULT_OPENAI_SELECTOR_MAX_TOKENS,
        provider: OpenAIAPIProvider | None = None,
    ) -> None:
        if not model:
            raise ValueError("OpenAI selector model is required.")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least 1.")
        self.model = model
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self._provider = provider

    def select(self, task: MultiZoneTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        provider = self._provider or OpenAIAPIProvider(timeout=self.timeout)
        prompt = build_openai_selector_prompt(task)
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=self.model,
            max_tokens=self.max_output_tokens,
            temperature=None,
            system_instruction=(
                "You select relevant context zones for a synthetic benchmark. "
                "Return only valid JSON matching the requested schema."
            ),
        )
        response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        try:
            parsed = parse_openai_selector_output(response_text)
            _validate_openai_selected_zone_ids(task, parsed["selected_zone_ids"])
        except Exception as exc:
            raise OpenAISelectorError(
                str(exc),
                metadata={
                    "provider": OPENAI_API_PROVIDER,
                    "model": self.model,
                    "api_path": OPENAI_SELECTOR_API_PATH,
                    "max_output_tokens": self.max_output_tokens,
                    "raw_response_text": response_text,
                    "raw_selected_zone_ids": _extract_raw_selected_zone_ids(response_text),
                    "usage": usage,
                    "error": _safe_error_message(exc),
                },
            ) from exc
        selected_zone_ids = tuple(str(zone_id) for zone_id in parsed["selected_zone_ids"])
        selected_zones = [zone_by_id(task, zone_id) for zone_id in selected_zone_ids]
        selection = build_selection(
            task=task,
            selected_zones=selected_zones,
            selector_name=OPENAI_SELECTOR_NAME,
            selector_success=True,
            selector_used_fallback=bool(parsed["fallback_used"]),
            confidence=float(parsed["confidence"]),
            rationale=str(parsed["evidence_rationale"]),
        )
        selection["zone_roles"] = {
            zone_id: str(parsed["zone_roles"].get(zone_id) or selection["zone_roles"].get(zone_id))
            for zone_id in selection["selected_zone_ids"]
        }
        selection["openai_selector"] = {
            "provider": OPENAI_API_PROVIDER,
            "model": self.model,
            "api_path": OPENAI_SELECTOR_API_PATH,
            "max_output_tokens": self.max_output_tokens,
            "raw_response_text": response_text,
            "raw_selected_zone_ids": list(parsed["selected_zone_ids"]),
            "usage": usage,
        }
        return selection


class OpenAISelectorError(RuntimeError):
    """Selector failure with non-secret OpenAI response metadata."""

    def __init__(self, message: str, metadata: dict[str, Any]) -> None:
        super().__init__(message)
        self.metadata = dict(metadata)


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
                "openai_selector": _selector_error_metadata(selector, exc),
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
        "selector_validation_result": (
            "complete"
            if selection_validation["selected_zone_complete"]
            and selection_validation["distractors_omitted"]
            else "incomplete"
        ),
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
        "openai_selector": selection.get("openai_selector"),
    }


def compose_context(task: MultiZoneTask, selected_zone_ids: tuple[str, ...]) -> str:
    zones = [zone_by_id(task, zone_id) for zone_id in selected_zone_ids]
    parts = [
        f"ZONE ROLE: {zone.role}\nZONE ID: {zone.zone_id}\nTITLE: {zone.title}\n{zone.text}"
        for zone in zones
    ]
    return "\n\n".join(parts)


def build_openai_selector_prompt(task: MultiZoneTask) -> str:
    zone_catalog = "\n\n".join(format_zone(zone) for zone in task.zones)
    valid_zone_ids = ", ".join(f'"{zone.zone_id}"' for zone in task.zones)
    example_zone = task.zones[0]
    return (
        "Select the minimal complete set of context zones needed to answer the task.\n"
        "Return only JSON with this schema:\n"
        "{\n"
        '  "selected_zone_ids": ["zone-id", "..."],\n'
        '  "zone_roles": {"zone-id": "role"},\n'
        '  "confidence": 0.0,\n'
        '  "evidence_rationale": "short rationale",\n'
        '  "fallback_used": false\n'
        "}\n\n"
        "Rules:\n"
        "- Select every zone required to answer all requested fields.\n"
        "- Do not select obsolete, partial, conflicting, or merely plausible distractor zones.\n"
        "- selected_zone_ids must contain exact canonical zone IDs only.\n"
        '- Do not prefix IDs with "ZONE".\n'
        "- Do not append roles in parentheses.\n"
        "- Do not include labels, explanations, markdown, or decorated strings inside selected_zone_ids.\n"
        "- Valid IDs are exactly the provided IDs and must be copied verbatim.\n"
        "- No single zone contains the full answer.\n"
        "- Set fallback_used to false unless you could not perform selection.\n"
        "- Do not generate the final answer; only select zones.\n\n"
        f"Valid canonical zone IDs: {valid_zone_ids}\n\n"
        "Valid JSON format example using canonical IDs only:\n"
        "{\n"
        f'  "selected_zone_ids": ["{example_zone.zone_id}"],\n'
        f'  "zone_roles": {{"{example_zone.zone_id}": "{example_zone.role}"}},\n'
        '  "confidence": 0.42,\n'
        '  "evidence_rationale": "Short reason for selected zones.",\n'
        '  "fallback_used": false\n'
        "}\n\n"
        f"Task:\n{task.question}\n\n"
        f"Available zones:\n{zone_catalog}"
    )


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
    role_checks = {
        zone_id: selection.get("zone_roles", {}).get(zone_id) == zone_by_id(task, zone_id).role
        for zone_id in selected
    }
    selected_zone_complete = (
        not missing_required
        and all(evidence_checks.values())
        and all(target_checks.values())
        and all(role_checks.values())
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
        "role_checks": role_checks,
        "zone_roles_valid": all(role_checks.values()),
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


def parse_openai_selector_output(response_text: str) -> dict[str, Any]:
    data = _loads_json_object(response_text)
    selected_zone_ids = data.get("selected_zone_ids")
    zone_roles = data.get("zone_roles")
    if not isinstance(selected_zone_ids, list) or not selected_zone_ids:
        raise ValueError("OpenAI selector response must include selected_zone_ids.")
    if not isinstance(zone_roles, dict):
        raise ValueError("OpenAI selector response must include zone_roles.")
    confidence = data.get("confidence", 0.0)
    return {
        "selected_zone_ids": [str(zone_id).strip() for zone_id in selected_zone_ids],
        "zone_roles": {str(key): str(value) for key, value in zone_roles.items()},
        "confidence": float(confidence),
        "evidence_rationale": str(data.get("evidence_rationale") or ""),
        "fallback_used": bool(data.get("fallback_used")),
    }


def _validate_openai_selected_zone_ids(task: MultiZoneTask, selected_zone_ids: list[str]) -> None:
    valid_zone_ids = {zone.zone_id for zone in task.zones}
    invalid_zone_ids = [zone_id for zone_id in selected_zone_ids if zone_id not in valid_zone_ids]
    if invalid_zone_ids:
        raise ValueError(
            "OpenAI selector returned non-canonical zone IDs: "
            + ", ".join(repr(zone_id) for zone_id in invalid_zone_ids)
        )


def _extract_raw_selected_zone_ids(response_text: str) -> list[str]:
    try:
        data = _loads_json_object(response_text)
    except Exception:
        return []
    selected_zone_ids = data.get("selected_zone_ids")
    if not isinstance(selected_zone_ids, list):
        return []
    return [str(zone_id) for zone_id in selected_zone_ids]


def _loads_json_object(response_text: str) -> dict[str, Any]:
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("OpenAI selector response must be a JSON object.")
    return data


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


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _selector_error_metadata(selector: MultiZoneSelector, exc: Exception) -> dict[str, Any] | None:
    if isinstance(exc, OpenAISelectorError):
        return dict(exc.metadata)
    if not isinstance(selector, OpenAISelectorSmoke):
        return None
    return {
        "provider": OPENAI_API_PROVIDER,
        "model": selector.model,
        "api_path": OPENAI_SELECTOR_API_PATH,
        "max_output_tokens": selector.max_output_tokens,
        "error": _safe_error_message(exc),
    }


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


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
        "openai_selector_actual_usage": _sum_openai_selector_usage(spatial_runs),
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
        f"Selector mode: `{report['metadata']['selector_mode']}`",
        f"Model: `{report['metadata']['model'] or 'n/a'}`",
        f"API path: `{report['metadata']['api_path'] or 'n/a'}`",
        f"Executor: `{report['metadata']['executor']}`",
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
        "## OpenAI Selector Usage",
        "",
        "| Metric | Actual tokens |",
        "| --- | ---: |",
        f"| Input | {_format_optional_int(summary['openai_selector_actual_usage']['input_tokens'])} |",
        f"| Output | {_format_optional_int(summary['openai_selector_actual_usage']['output_tokens'])} |",
        f"| Total | {_format_optional_int(summary['openai_selector_actual_usage']['total_tokens'])} |",
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
    print(f"selector mode: {report['metadata']['selector_mode']}")
    print(f"provider: {report['metadata']['provider']}")
    if report["metadata"].get("model"):
        print(f"model: {report['metadata']['model']}")
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


def _sum_openai_selector_usage(runs: list[dict[str, Any]]) -> dict[str, int | None]:
    totals: dict[str, int] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }
    seen: dict[str, bool] = {key: False for key in totals}
    for run in runs:
        selector_metadata = run.get("openai_selector")
        if not isinstance(selector_metadata, dict):
            continue
        usage = selector_metadata.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key)
            if value is not None:
                totals[key] += int(value)
                seen[key] = True
    return {key: totals[key] if seen[key] else None for key in totals}


def _format_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_optional_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_optional_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


if __name__ == "__main__":
    main()
