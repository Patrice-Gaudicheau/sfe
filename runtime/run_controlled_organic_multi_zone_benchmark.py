"""Run the deterministic controlled organic multi-zone benchmark.

This Phase 3a benchmark uses short organic-style project documents instead of
synthetic role blocks. The default path is deterministic and provider-free.
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

from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_OPENAI_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_API_PROVIDER,
    OpenAIAPIProvider,
)
from runtime.metrics import estimate_text_tokens, percent_reduction, write_json_report, write_text_report
from sfe.env import load_repo_env


BENCHMARK_TYPE = "multi_zone/controlled_organic"
BENCHMARK_NAME = "controlled_organic_multi_zone"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "controlled_organic_multi_zone_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "controlled_organic_multi_zone_benchmark.md"
FIXTURE_SELECTOR_NAME = "fixture_controlled_organic_selector"
FALLBACK_SELECTOR_NAME = "fixture_fallback_after_selector_error"
FIXTURE_EXECUTOR_NAME = "fixture_controlled_organic_executor"
OPENAI_SELECTOR_NAME = "openai_controlled_organic_selector_smoke"
OPENAI_SELECTOR_API_PATH = "/v1/responses"
DEFAULT_OPENAI_SELECTOR_MAX_TOKENS = 800
OPENAI_EXECUTOR_NAME = "openai_controlled_organic_executor_smoke"
OPENAI_EXECUTOR_API_PATH = "/v1/responses"
DEFAULT_OPENAI_EXECUTOR_MAX_TOKENS = 1000


@dataclass(frozen=True)
class OrganicSource:
    source_id: str
    role: str
    title: str
    text: str
    required: bool = False
    distractor: bool = False


@dataclass(frozen=True)
class ControlledOrganicTask:
    fixture_id: str
    question: str
    sources: tuple[OrganicSource, ...]
    required_source_ids: tuple[str, ...]
    distractor_source_ids: tuple[str, ...]
    expected_fields: dict[str, str]
    expected_answer: str


class OrganicSelector(Protocol):
    provider: str
    selector_mode: str
    model: str | None
    api_path: str | None

    def select(self, task: ControlledOrganicTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        ...


class OrganicExecutor(Protocol):
    provider: str
    executor_mode: str
    model: str | None
    api_path: str | None

    def execute(
        self,
        task: ControlledOrganicTask,
        selected_source_ids: tuple[str, ...],
        composed_context: str,
    ) -> dict[str, Any]:
        ...


def main() -> None:
    args = _parse_args()
    selector = _build_selector_from_args(args)
    executor = _build_executor_from_args(args)
    tasks = get_controlled_organic_tasks()
    report = run_benchmark(tasks=tasks, repeat=args.repeat, selector=selector, executor=executor)
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic controlled organic multi-zone benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
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
    parser.add_argument(
        "--executor",
        choices=("fixture", "openai"),
        default="fixture",
        help="Executor path to use. Default fixture mode makes no provider calls.",
    )
    parser.add_argument(
        "--executor-model",
        help=(
            "OpenAI executor model for --executor openai. Defaults to "
            "SFE_OPENAI_EXECUTOR_MODEL, then the provider executor default."
        ),
    )
    parser.add_argument(
        "--executor-max-output-tokens",
        type=int,
        default=DEFAULT_OPENAI_EXECUTOR_MAX_TOKENS,
        help="Maximum executor response tokens for --executor openai.",
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def _build_selector_from_args(args: argparse.Namespace) -> OrganicSelector:
    if args.selector == "fixture":
        return FixtureOrganicSelector()
    load_repo_env()
    model = args.model or os.getenv("SFE_OPENAI_ROUTER_MODEL") or DEFAULT_OPENAI_ROUTER_MODEL
    return OpenAIOrganicSelectorSmoke(
        model=model,
        timeout=args.timeout,
        max_output_tokens=args.max_output_tokens,
    )

def _build_executor_from_args(args: argparse.Namespace) -> OrganicExecutor:
    if args.executor == "fixture":
        return FixtureOrganicExecutor()
    load_repo_env()
    model = (
        args.executor_model
        or os.getenv("SFE_OPENAI_EXECUTOR_MODEL")
        or DEFAULT_OPENAI_EXECUTOR_MODEL
    )
    return OpenAIOrganicExecutorSmoke(
        model=model,
        timeout=args.timeout,
        max_output_tokens=args.executor_max_output_tokens,
    )


def get_controlled_organic_tasks() -> list[ControlledOrganicTask]:
    expected_fields = {
        "active_protocol": "Helix Gate 2026.11",
        "cycle_date": "2026-11-14",
        "responsible_component": "relay-admission-controller",
        "owner_id": "COMPONENT_OWNER_RELAY_GATE",
        "threshold": "error budget burn <= 2.8% over 24h",
        "required_action": "enable staged admission with rollback monitor",
        "blocking_condition": "queue replay drift above 0.36",
    }
    required_source_ids = (
        "doc-release-notes-helix-2026-11",
        "doc-policy-thresholds-current",
        "doc-service-ownership-map",
        "doc-incident-followup-778",
    )
    expected_answer = "\n".join(
        [
            "active_protocol: Helix Gate 2026.11",
            "cycle_date: 2026-11-14",
            "responsible_component: relay-admission-controller",
            "owner_id: COMPONENT_OWNER_RELAY_GATE",
            "threshold: error budget burn <= 2.8% over 24h",
            "required_action: enable staged admission with rollback monitor",
            "blocking_condition: queue replay drift above 0.36",
            "evidence_source_ids: doc-release-notes-helix-2026-11, "
            "doc-policy-thresholds-current, doc-service-ownership-map, "
            "doc-incident-followup-778",
        ]
    )
    return [
        ControlledOrganicTask(
            fixture_id="controlled_organic_release_readiness_gate",
            question=(
                "Using the controlled organic project notes, determine the active "
                "Helix Gate release readiness decision. Return the active protocol, "
                "cycle date, responsible component, owner ID, threshold, required "
                "action, blocking condition, and evidence source IDs."
            ),
            sources=(
                _source(
                    "doc-release-notes-helix-2026-11",
                    "release_notes",
                    "Helix Gate 2026.11 Release Notes",
                    (
                        "Release readiness notes for Helix Gate 2026.11. The active "
                        "cycle date is 2026-11-14. The notes state that readiness is "
                        "governed by the current threshold policy and ownership map. "
                        "They do not name the threshold, owner, or final mitigation action."
                    ),
                    required=True,
                ),
                _source(
                    "doc-policy-thresholds-current",
                    "policy_thresholds",
                    "Current Readiness Threshold Policy",
                    (
                        "Current policy for Helix Gate 2026.11: release may proceed "
                        "only when error budget burn <= 2.8% over 24h. The blocking "
                        "condition is queue replay drift above 0.36. This policy is "
                        "authoritative for thresholds but does not identify the owner "
                        "or the required operational action."
                    ),
                    required=True,
                ),
                _source(
                    "doc-service-ownership-map",
                    "ownership_map",
                    "Service Ownership Map",
                    (
                        "The release readiness component for Helix Gate is "
                        "relay-admission-controller. Its owner ID is "
                        "COMPONENT_OWNER_RELAY_GATE. The map intentionally does not "
                        "carry release dates, thresholds, or incident actions."
                    ),
                    required=True,
                ),
                _source(
                    "doc-incident-followup-778",
                    "evidence_record",
                    "Incident Follow-up 778",
                    (
                        "INC-FOLLOWUP-778 records the evidence accepted for Helix Gate "
                        "2026.11 readiness. The required action is enable staged "
                        "admission with rollback monitor. This evidence record confirms "
                        "the action but relies on the release notes, current policy, and "
                        "ownership map for the full decision."
                    ),
                    required=True,
                ),
                _source(
                    "doc-policy-thresholds-previous",
                    "previous_policy",
                    "Previous Threshold Policy",
                    (
                        "Previous policy for Helix Gate 2026.10 allowed release when "
                        "error budget burn <= 3.4% over 48h. The previous blocking "
                        "condition was queue replay drift above 0.44. This document is "
                        "retained for audit comparison and is not valid for 2026.11."
                    ),
                    distractor=True,
                ),
                _source(
                    "doc-ops-note-local-override",
                    "ops_note",
                    "Local Operations Override Note",
                    (
                        "A local operations note mentions relay-admission-local and says "
                        "operators sometimes enable staged admission for regional tests. "
                        "It is useful background but is not authoritative evidence for "
                        "release readiness and does not define the active Helix Gate rule."
                    ),
                    distractor=True,
                ),
                _source(
                    "doc-release-notes-draft",
                    "draft_release_notes",
                    "Draft Helix Gate RC Notes",
                    (
                        "Draft notes for Helix Gate 2026.11-rc1 list the same November "
                        "release family but mark threshold review as pending. They omit "
                        "the blocking condition and are superseded by the final "
                        "Helix Gate 2026.11 release notes."
                    ),
                    distractor=True,
                ),
            ),
            required_source_ids=required_source_ids,
            distractor_source_ids=(
                "doc-policy-thresholds-previous",
                "doc-ops-note-local-override",
                "doc-release-notes-draft",
            ),
            expected_fields=expected_fields,
            expected_answer=expected_answer,
        )
    ]


class FixtureOrganicSelector:
    provider = "deterministic_mock"
    selector_mode = "fixture"
    model: str | None = None
    api_path: str | None = None

    def select(self, task: ControlledOrganicTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        selected_sources = [source_by_id(task, source_id) for source_id in task.required_source_ids]
        return build_selection(
            task=task,
            selected_sources=selected_sources,
            selector_name=FIXTURE_SELECTOR_NAME,
            selector_success=True,
            selector_used_fallback=False,
            confidence=1.0,
            rationale=(
                "Selected final release notes, current threshold policy, ownership map, "
                "and incident evidence because no single source contains the full decision."
            ),
        )


class OpenAIOrganicSelectorSmoke:
    """OpenAI-backed source selector smoke path; executor stays deterministic."""

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

    def select(self, task: ControlledOrganicTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        provider = self._provider or OpenAIAPIProvider(timeout=self.timeout)
        prompt = build_openai_selector_prompt(task)
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=self.model,
            max_tokens=self.max_output_tokens,
            temperature=None,
            system_instruction=(
                "You select relevant source documents for a controlled organic benchmark. "
                "Return only strict JSON matching the requested schema."
            ),
        )
        response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        try:
            parsed = parse_openai_selector_output(response_text)
            _validate_openai_selected_source_ids(task, parsed["selected_source_ids"])
        except Exception as exc:
            raise OpenAISelectorError(
                str(exc),
                metadata={
                    "provider": OPENAI_API_PROVIDER,
                    "model": self.model,
                    "api_path": OPENAI_SELECTOR_API_PATH,
                    "max_output_tokens": self.max_output_tokens,
                    "raw_response_text": response_text,
                    "raw_selected_source_ids": _extract_raw_selected_source_ids(
                        response_text
                    ),
                    "usage": usage,
                    "error": _safe_error_message(exc),
                },
            ) from exc

        selected_source_ids = tuple(str(source_id) for source_id in parsed["selected_source_ids"])
        selected_sources = [source_by_id(task, source_id) for source_id in selected_source_ids]
        selection = build_selection(
            task=task,
            selected_sources=selected_sources,
            selector_name=OPENAI_SELECTOR_NAME,
            selector_success=True,
            selector_used_fallback=bool(parsed["fallback_used"]),
            confidence=float(parsed["confidence"]),
            rationale=str(parsed["evidence_rationale"]),
        )
        selection["source_roles"] = {
            source_id: str(
                parsed["source_roles"].get(source_id)
                or selection["source_roles"].get(source_id)
            )
            for source_id in selection["selected_source_ids"]
        }
        selection["openai_selector"] = {
            "provider": OPENAI_API_PROVIDER,
            "model": self.model,
            "api_path": OPENAI_SELECTOR_API_PATH,
            "max_output_tokens": self.max_output_tokens,
            "raw_response_text": response_text,
            "raw_selected_source_ids": list(parsed["selected_source_ids"]),
            "usage": usage,
        }
        return selection


class OpenAISelectorError(RuntimeError):
    """Selector failure with non-secret OpenAI response metadata."""

    def __init__(self, message: str, metadata: dict[str, Any]) -> None:
        super().__init__(message)
        self.metadata = dict(metadata)


class FixtureOrganicExecutor:
    provider = "deterministic_mock"
    executor_mode = "deterministic_fixture"
    model: str | None = None
    api_path: str | None = None

    def execute(
        self,
        task: ControlledOrganicTask,
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


class OpenAIOrganicExecutorSmoke:
    """OpenAI-backed executor smoke path over selected source context only."""

    provider = OPENAI_API_PROVIDER
    executor_mode = "openai_executor_smoke"
    api_path = OPENAI_EXECUTOR_API_PATH

    def __init__(
        self,
        model: str,
        timeout: float | None = None,
        max_output_tokens: int = DEFAULT_OPENAI_EXECUTOR_MAX_TOKENS,
        provider: OpenAIAPIProvider | None = None,
    ) -> None:
        if not model:
            raise ValueError("OpenAI executor model is required.")
        if max_output_tokens < 1:
            raise ValueError("executor max_output_tokens must be at least 1.")
        self.model = model
        self.timeout = timeout
        self.max_output_tokens = max_output_tokens
        self._provider = provider

    def execute(
        self,
        task: ControlledOrganicTask,
        selected_source_ids: tuple[str, ...],
        composed_context: str,
    ) -> dict[str, Any]:
        provider = self._provider or OpenAIAPIProvider(timeout=self.timeout)
        prompt = build_openai_executor_prompt(task, selected_source_ids, composed_context)
        response = provider.chat(
            [{"role": "user", "content": prompt}],
            model=self.model,
            max_tokens=self.max_output_tokens,
            temperature=None,
            system_instruction=(
                "You synthesize benchmark answers from selected source documents only. "
                "Return only strict JSON matching the requested schema."
            ),
        )
        response_text = _extract_response_text(response)
        usage = _extract_usage(response)
        try:
            output = parse_openai_executor_output(task, response_text)
            output_parse_success = True
            output_parse_error = ""
        except Exception as exc:
            output = ""
            output_parse_success = False
            output_parse_error = _safe_error_message(exc)
        return {
            "executor": OPENAI_EXECUTOR_NAME,
            "executor_mode": self.executor_mode,
            "provider": OPENAI_API_PROVIDER,
            "model": self.model,
            "api_path": OPENAI_EXECUTOR_API_PATH,
            "output": output,
            "output_parse_success": output_parse_success,
            "output_parse_error": output_parse_error,
            "actual_usage": None,
            "openai_executor": {
                "provider": OPENAI_API_PROVIDER,
                "model": self.model,
                "api_path": OPENAI_EXECUTOR_API_PATH,
                "max_output_tokens": self.max_output_tokens,
                "raw_response_text": response_text,
                "usage": usage,
                "output_parse_success": output_parse_success,
                "output_parse_error": output_parse_error,
            },
        }


def run_benchmark(
    tasks: list[ControlledOrganicTask],
    repeat: int = 1,
    selector: OrganicSelector | None = None,
    executor: OrganicExecutor | None = None,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if not tasks:
        raise ValueError("At least one controlled organic task is required.")

    selector = selector or FixtureOrganicSelector()
    executor = executor or FixtureOrganicExecutor()
    baseline_executor = FixtureOrganicExecutor()
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
                    mode="controlled_organic_multi_zone",
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
            "provider": getattr(selector, "provider", "deterministic_mock"),
            "model": getattr(selector, "model", None),
            "api_path": getattr(selector, "api_path", None),
            "selector_mode": getattr(selector, "selector_mode", selector.__class__.__name__),
            "selector_provider": getattr(selector, "provider", "deterministic_mock"),
            "selector_model": getattr(selector, "model", None),
            "selector_api_path": getattr(selector, "api_path", None),
            "executor_mode": getattr(executor, "executor_mode", executor.__class__.__name__),
            "executor_provider": getattr(executor, "provider", "deterministic_mock"),
            "executor_model": getattr(executor, "model", None),
            "executor_api_path": getattr(executor, "api_path", None),
            "executor": getattr(executor, "executor_mode", executor.__class__.__name__),
        },
        "summary": summarize_runs(runs),
        "tasks": [task_to_dict(task) for task in tasks],
        "runs": runs,
    }


def _select_with_fallback(
    task: ControlledOrganicTask,
    selector: OrganicSelector,
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
                "openai_selector": _selector_error_metadata(selector, exc),
            }
        )
        return fallback


def fixture_source_selection(task: ControlledOrganicTask) -> dict[str, Any]:
    return FixtureOrganicSelector().select(task, {})


def all_source_selection(task: ControlledOrganicTask) -> dict[str, Any]:
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
    task: ControlledOrganicTask,
    selected_sources: list[OrganicSource],
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
        "openai_selector": None,
        "selected_source_token_estimates": selected_source_tokens,
        "suppressed_source_token_estimates": suppressed_source_tokens,
        "selected_source_token_estimate": sum(selected_source_tokens.values()),
        "suppressed_source_token_estimate": sum(suppressed_source_tokens.values()),
    }


def execute_task(
    *,
    task: ControlledOrganicTask,
    mode: str,
    selection: dict[str, Any],
    fixture_selection: dict[str, Any],
    repeat_index: int,
    executor: OrganicExecutor | None = None,
    output_override: str | None = None,
) -> dict[str, Any]:
    selected_source_ids = tuple(str(source_id) for source_id in selection["selected_source_ids"])
    composed_context = compose_context(task, selected_source_ids)
    baseline_context = compose_context(task, tuple(source.source_id for source in task.sources))
    executor = executor or FixtureOrganicExecutor()
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
        mode == "controlled_organic_multi_zone"
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
        "honest_controlled_organic_pass_after_repair": None,
        "executor": executor_result["executor"],
        "executor_mode": executor_result["executor_mode"],
        "executor_provider": executor_result["provider"],
        "executor_model": executor_result["model"],
        "executor_api_path": executor_result["api_path"],
        "executor_output_parse_success": executor_result["output_parse_success"],
        "executor_output_parse_error": executor_result["output_parse_error"],
        "actual_usage": executor_result.get("actual_usage"),
        "openai_selector": selection.get("openai_selector"),
        "openai_executor": executor_result.get("openai_executor"),
        "honest_controlled_organic_pass": honest_pass,
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


def validate_selection(task: ControlledOrganicTask, selection: dict[str, Any]) -> dict[str, Any]:
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


def validate_output(task: ControlledOrganicTask, output: str) -> dict[str, Any]:
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
    organic_runs = [run for run in runs if run["mode"] == "controlled_organic_multi_zone"]
    return {
        "run_count": len(runs),
        "baseline_run_count": len(baseline_runs),
        "controlled_organic_run_count": len(organic_runs),
        "source_selection_success_rate": _rate(
            run["selector_success"] is True for run in organic_runs
        ),
        "required_source_completeness_rate": _rate(
            run["required_source_complete"] is True for run in organic_runs
        ),
        "distractor_rejection_rate": _rate(
            run["distractors_omitted"] is True for run in organic_runs
        ),
        "fallback_count": sum(1 for run in organic_runs if run["selector_used_fallback"]),
        "output_validation_complete_rate": _rate(
            run["output_validation_before_repair"] is True for run in organic_runs
        ),
        "output_validation_after_repair_rate": None,
        "executor_output_parse_success_rate": _rate(
            run["executor_output_parse_success"] is True for run in organic_runs
        ),
        "honest_controlled_organic_pass_count": sum(
            1 for run in organic_runs if run["honest_controlled_organic_pass"]
        ),
        "honest_controlled_organic_pass_rate": _rate(
            run["honest_controlled_organic_pass"] is True for run in organic_runs
        ),
        "average_full_context_baseline_tokens": _average(
            run["full_context_baseline_token_estimate"] for run in organic_runs
        ),
        "average_selected_source_tokens": _average(
            run["selected_source_token_estimate"] for run in organic_runs
        ),
        "average_suppressed_source_tokens": _average(
            run["suppressed_source_token_estimate"] for run in organic_runs
        ),
        "average_composed_context_tokens": _average(
            run["total_composed_context_token_estimate"] for run in organic_runs
        ),
        "average_token_reduction_percent": _average(
            run["token_reduction_percent"] for run in organic_runs
            if run["token_reduction_percent"] is not None
        ),
        "openai_selector_actual_usage": _sum_openai_selector_usage(organic_runs),
        "openai_executor_actual_usage": _sum_openai_executor_usage(organic_runs),
        "actual_usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
        "fixtures": _summarize_fixtures(organic_runs),
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
                "run_count": len(fixture_runs),
                "selected_source_ids": first["selected_source_ids"],
                "required_source_complete": all(
                    run["required_source_complete"] for run in fixture_runs
                ),
                "distractors_omitted": all(
                    run["distractors_omitted"] for run in fixture_runs
                ),
                "fallback_used": any(run["selector_used_fallback"] for run in fixture_runs),
                "honest_controlled_organic_pass_count": sum(
                    1 for run in fixture_runs if run["honest_controlled_organic_pass"]
                ),
                "honest_controlled_organic_pass_rate": _rate(
                    run["honest_controlled_organic_pass"] is True for run in fixture_runs
                ),
                "average_token_reduction_percent": _average(
                    run["token_reduction_percent"] for run in fixture_runs
                    if run["token_reduction_percent"] is not None
                ),
            }
        )
    return summaries


def task_to_dict(task: ControlledOrganicTask) -> dict[str, Any]:
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
        "# Controlled Organic Multi-Zone Benchmark",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Provider: `{report['metadata']['provider']}`",
        f"Selector mode: `{report['metadata']['selector_mode']}`",
        f"Selector provider: `{report['metadata']['selector_provider']}`",
        f"Selector model: `{report['metadata']['selector_model'] or 'n/a'}`",
        f"Selector API path: `{report['metadata']['selector_api_path'] or 'n/a'}`",
        f"Executor mode: `{report['metadata']['executor_mode']}`",
        f"Executor provider: `{report['metadata']['executor_provider']}`",
        f"Executor model: `{report['metadata']['executor_model'] or 'n/a'}`",
        f"Executor API path: `{report['metadata']['executor_api_path'] or 'n/a'}`",
        f"Runs: {summary['run_count']}",
        "",
        "## Summary",
        "",
        f"Honest controlled-organic pass rate: {_format_percent(summary['honest_controlled_organic_pass_rate'])}",
        f"Source selection success rate: {_format_percent(summary['source_selection_success_rate'])}",
        f"Required source completeness rate: {_format_percent(summary['required_source_completeness_rate'])}",
        f"Distractor rejection rate: {_format_percent(summary['distractor_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Output validation complete rate: {_format_percent(summary['output_validation_complete_rate'])}",
        f"Executor output parse success rate: {_format_percent(summary['executor_output_parse_success_rate'])}",
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
        "## OpenAI Selector Usage",
        "",
        "| Metric | Actual tokens |",
        "| --- | ---: |",
        f"| Input | {_format_optional_int(summary['openai_selector_actual_usage']['input_tokens'])} |",
        f"| Output | {_format_optional_int(summary['openai_selector_actual_usage']['output_tokens'])} |",
        f"| Total | {_format_optional_int(summary['openai_selector_actual_usage']['total_tokens'])} |",
        "",
        "## OpenAI Executor Usage",
        "",
        "| Metric | Actual tokens |",
        "| --- | ---: |",
        f"| Input | {_format_optional_int(summary['openai_executor_actual_usage']['input_tokens'])} |",
        f"| Output | {_format_optional_int(summary['openai_executor_actual_usage']['output_tokens'])} |",
        f"| Total | {_format_optional_int(summary['openai_executor_actual_usage']['total_tokens'])} |",
        "",
        "## Fixtures",
        "",
        "| Fixture ID | Selected sources | Complete | Distractors omitted | Fallback used | Honest pass rate | Token reduction |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fixture in summary["fixtures"]:
        lines.append(
            f"| `{fixture['fixture_id']}` | "
            f"{', '.join(fixture['selected_source_ids'])} | "
            f"{fixture['required_source_complete']} | "
            f"{fixture['distractors_omitted']} | "
            f"{fixture['fallback_used']} | "
            f"{_format_percent(fixture['honest_controlled_organic_pass_rate'])} | "
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
            f"{run['honest_controlled_organic_pass']} | "
            f"{', '.join(run['selected_source_ids'])} | "
            f"{', '.join(run['missing_required_source_ids']) or 'none'} | "
            f"{', '.join(run['unexpected_distractor_source_ids']) or 'none'} | "
            f"{_format_optional_percent(run['token_reduction_percent'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Controlled organic multi-zone benchmark")
    print(f"selector mode: {report['metadata']['selector_mode']}")
    print(f"selector provider: {report['metadata']['selector_provider']}")
    if report["metadata"].get("selector_model"):
        print(f"selector model: {report['metadata']['selector_model']}")
    print(f"executor mode: {report['metadata']['executor_mode']}")
    print(f"executor provider: {report['metadata']['executor_provider']}")
    if report["metadata"].get("executor_model"):
        print(f"executor model: {report['metadata']['executor_model']}")
    print(f"runs: {summary['run_count']}")
    print(
        "honest controlled-organic pass rate: "
        f"{_format_percent(summary['honest_controlled_organic_pass_rate'])}"
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


def build_openai_selector_prompt(task: ControlledOrganicTask) -> str:
    source_catalog = "\n\n".join(format_source(source) for source in task.sources)
    valid_source_ids = ", ".join(f'"{source.source_id}"' for source in task.sources)
    example_source = task.sources[0]
    return (
        "Select the minimal complete set of source documents needed to answer the task.\n"
        "Return only strict JSON with this schema:\n"
        "{\n"
        '  "selected_source_ids": ["source-id", "..."],\n'
        '  "source_roles": {"source-id": "role"},\n'
        '  "confidence": 0.0,\n'
        '  "evidence_rationale": "short rationale",\n'
        '  "fallback_used": false\n'
        "}\n\n"
        "Rules:\n"
        "- Select every source document required to answer all requested fields.\n"
        "- Do not select previous-version, draft, local-override, partial, or merely plausible distractor documents.\n"
        "- selected_source_ids must contain exact canonical source IDs only.\n"
        '- Do not prefix IDs with "DOC" or "SOURCE".\n'
        "- Do not append roles in parentheses.\n"
        "- Do not include labels, explanations, markdown, or decorated strings inside selected_source_ids.\n"
        "- Valid IDs are exactly the provided IDs and must be copied verbatim.\n"
        "- No single source document contains the full answer.\n"
        "- Set fallback_used to false unless you could not perform selection.\n"
        "- Do not generate the final answer; only select source documents.\n\n"
        f"Valid canonical source IDs: {valid_source_ids}\n\n"
        "Valid JSON format example using canonical IDs only:\n"
        "{\n"
        f'  "selected_source_ids": ["{example_source.source_id}"],\n'
        f'  "source_roles": {{"{example_source.source_id}": "{example_source.role}"}},\n'
        '  "confidence": 0.42,\n'
        '  "evidence_rationale": "Short reason for selected sources.",\n'
        '  "fallback_used": false\n'
        "}\n\n"
        f"Task:\n{task.question}\n\n"
        f"Available source documents:\n{source_catalog}"
    )


def parse_openai_selector_output(response_text: str) -> dict[str, Any]:
    data = _loads_strict_json_object(response_text)
    selected_source_ids = data.get("selected_source_ids")
    source_roles = data.get("source_roles")
    if not isinstance(selected_source_ids, list) or not selected_source_ids:
        raise ValueError("OpenAI selector response must include selected_source_ids.")
    if not isinstance(source_roles, dict):
        raise ValueError("OpenAI selector response must include source_roles.")
    confidence = data.get("confidence", 0.0)
    return {
        "selected_source_ids": [
            str(source_id).strip() for source_id in selected_source_ids
        ],
        "source_roles": {str(key): str(value) for key, value in source_roles.items()},
        "confidence": float(confidence),
        "evidence_rationale": str(data.get("evidence_rationale") or ""),
        "fallback_used": bool(data.get("fallback_used")),
    }


def build_openai_executor_prompt(
    task: ControlledOrganicTask,
    selected_source_ids: tuple[str, ...],
    composed_context: str,
) -> str:
    expected_fields = ", ".join(_expected_answer_fields(task))
    evidence_source_ids = ", ".join(f'"{source_id}"' for source_id in selected_source_ids)
    return (
        "Synthesize the controlled organic benchmark answer using only the selected "
        "source documents below.\n"
        "Return only strict JSON. Do not include markdown fences, extra prose, comments, "
        "or explanatory text outside the JSON object.\n\n"
        "Required JSON schema:\n"
        "{\n"
        '  "active_protocol": "string",\n'
        '  "cycle_date": "string",\n'
        '  "responsible_component": "string",\n'
        '  "owner_id": "string",\n'
        '  "threshold": "string",\n'
        '  "required_action": "string",\n'
        '  "blocking_condition": "string",\n'
        '  "evidence_source_ids": ["source-id", "..."]\n'
        "}\n\n"
        "Rules:\n"
        "- Use exact values from the selected source documents.\n"
        "- Include every required field exactly once.\n"
        "- evidence_source_ids must be a JSON array of exact canonical source IDs only.\n"
        "- Do not decorate source IDs, prefix them with SOURCE or DOC, or append roles in parentheses.\n"
        "- If a value is not supported by the selected source documents, still return JSON; validation will fail.\n\n"
        f"Required fields: {expected_fields}\n"
        f"Allowed evidence source IDs for this selected context: {evidence_source_ids}\n\n"
        f"Task:\n{task.question}\n\n"
        f"Selected source documents:\n{composed_context}"
    )


def parse_openai_executor_output(task: ControlledOrganicTask, response_text: str) -> str:
    data = _loads_strict_json_object(response_text)
    expected_fields = _expected_answer_fields(task)
    missing_fields = [field for field in expected_fields if field not in data]
    if missing_fields:
        raise ValueError(
            "OpenAI executor response is missing required fields: "
            + ", ".join(missing_fields)
        )
    unexpected_fields = [
        field for field in data if field not in set(expected_fields)
    ]
    if unexpected_fields:
        raise ValueError(
            "OpenAI executor response included unexpected fields: "
            + ", ".join(unexpected_fields)
        )
    evidence_refs = data.get("evidence_source_ids")
    if not isinstance(evidence_refs, list):
        raise ValueError("OpenAI executor evidence_source_ids must be a JSON array.")
    lines: list[str] = []
    for field in expected_fields:
        value = data[field]
        if field == "evidence_source_ids":
            value_text = ", ".join(str(item).strip() for item in value if str(item).strip())
        else:
            value_text = str(value).strip()
        lines.append(f"{field}: {value_text}")
    return "\n".join(lines)


def _expected_answer_fields(task: ControlledOrganicTask) -> list[str]:
    fields: list[str] = []
    for line in task.expected_answer.splitlines():
        label, separator, _value = line.partition(":")
        if separator:
            fields.append(label.strip())
    return fields


def _validate_openai_selected_source_ids(
    task: ControlledOrganicTask,
    selected_source_ids: list[str],
) -> None:
    valid_source_ids = {source.source_id for source in task.sources}
    invalid_source_ids = [
        source_id for source_id in selected_source_ids if source_id not in valid_source_ids
    ]
    if invalid_source_ids:
        raise ValueError(
            "OpenAI selector returned non-canonical source IDs: "
            + ", ".join(repr(source_id) for source_id in invalid_source_ids)
        )


def _loads_strict_json_object(response_text: str) -> dict[str, Any]:
    data = json.loads(response_text.strip())
    if not isinstance(data, dict):
        raise ValueError("OpenAI selector response must be a strict JSON object.")
    return data


def _extract_raw_selected_source_ids(response_text: str) -> list[str]:
    try:
        data = _loads_strict_json_object(response_text)
    except Exception:
        return []
    selected_source_ids = data.get("selected_source_ids")
    if not isinstance(selected_source_ids, list):
        return []
    return [str(source_id) for source_id in selected_source_ids]


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


def _selector_error_metadata(selector: OrganicSelector, exc: Exception) -> dict[str, Any] | None:
    if isinstance(exc, OpenAISelectorError):
        return dict(exc.metadata)
    if not isinstance(selector, OpenAIOrganicSelectorSmoke):
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


def _sum_openai_selector_usage(runs: list[dict[str, Any]]) -> dict[str, int | None]:
    return _sum_usage_metadata(run.get("openai_selector") for run in runs)


def _sum_openai_executor_usage(runs: list[dict[str, Any]]) -> dict[str, int | None]:
    return _sum_usage_metadata(run.get("openai_executor") for run in runs)


def _sum_usage_metadata(items: Any) -> dict[str, int | None]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    seen = {key: False for key in totals}
    for metadata in items:
        if not isinstance(metadata, dict):
            continue
        usage = metadata.get("usage")
        if not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key)
            if value is not None:
                totals[key] += int(value)
                seen[key] = True
    return {key: totals[key] if seen[key] else None for key in totals}


def compose_context(task: ControlledOrganicTask, source_ids: tuple[str, ...]) -> str:
    lines: list[str] = []
    for source_id in source_ids:
        source = source_by_id(task, source_id)
        lines.append(format_source(source))
    return "\n\n".join(lines)


def format_source(source: OrganicSource) -> str:
    return "\n".join(
        [
            f"SOURCE ID: {source.source_id}",
            f"SOURCE ROLE: {source.role}",
            f"TITLE: {source.title}",
            source.text,
        ]
    )


def source_by_id(task: ControlledOrganicTask, source_id: str) -> OrganicSource:
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
) -> OrganicSource:
    return OrganicSource(
        source_id=source_id,
        role=role,
        title=title,
        text=text,
        required=required,
        distractor=distractor,
    )


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


def _format_optional_int(value: int | None) -> str:
    if value is None:
        return "n/a"
    return str(value)


if __name__ == "__main__":
    main()
