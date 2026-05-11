"""Run the large real-world inspired multi-zone benchmark.

This benchmark is deterministic and controlled. It uses larger project-like
source sets than the minimal benchmark to test whether source selection and
composition can produce more meaningful token reduction without weakening
validation. The default path is provider-free.
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


BENCHMARK_TYPE = "multi_zone/large_real_world_inspired"
BENCHMARK_NAME = "large_real_world_multi_zone"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "large_real_world_multi_zone_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "large_real_world_multi_zone_benchmark.md"
FIXTURE_SELECTOR_NAME = "fixture_large_real_world_selector"
FALLBACK_SELECTOR_NAME = "fixture_fallback_after_selector_error"
FIXTURE_EXECUTOR_NAME = "fixture_large_real_world_executor"
TOKEN_REDUCTION_TARGET_PERCENT = 60.0


@dataclass(frozen=True)
class LargeRealWorldSource:
    source_id: str
    role: str
    title: str
    text: str
    required: bool = False
    distractor: bool = False


@dataclass(frozen=True)
class LargeRealWorldTask:
    fixture_id: str
    task_theme: str
    question: str
    sources: tuple[LargeRealWorldSource, ...]
    required_source_ids: tuple[str, ...]
    distractor_source_ids: tuple[str, ...]
    expected_fields: dict[str, str]
    expected_answer: str


class LargeRealWorldSelector(Protocol):
    provider: str
    selector_mode: str
    model: str | None
    api_path: str | None

    def select(self, task: LargeRealWorldTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        ...


class LargeRealWorldExecutor(Protocol):
    provider: str
    executor_mode: str
    model: str | None
    api_path: str | None

    def execute(
        self,
        task: LargeRealWorldTask,
        selected_source_ids: tuple[str, ...],
        composed_context: str,
    ) -> dict[str, Any]:
        ...


def main() -> None:
    args = _parse_args()
    tasks = get_large_real_world_tasks()
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
        description="Run the deterministic large real-world inspired multi-zone benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def get_large_real_world_tasks() -> list[LargeRealWorldTask]:
    return [
        _gateway_integration_task(),
        _benchmark_roadmap_decision_task(),
    ]


def _gateway_integration_task() -> LargeRealWorldTask:
    required_source_ids = (
        "doc-gateway-architecture-current",
        "doc-gateway-routing-policy",
        "doc-gateway-exclusions-current",
        "doc-gateway-owner-decision-record",
    )
    expected_fields = {
        "current_runtime_mode": "library-only planner runtime",
        "gateway_status": "gateway proxy is planned but not implemented",
        "executor_context_boundary": "executor receives composed selected-source context only",
        "excluded_capability": "no automatic API-key brokering or transparent production traffic interception",
        "responsible_owner": "COMPONENT_OWNER_GATEWAY_BRIDGE",
        "next_step": "build deterministic gateway contract fixture before provider smoke",
    }
    return LargeRealWorldTask(
        fixture_id="large_real_world_gateway_proxy_integration_gate",
        task_theme="gateway_proxy_integration_decision",
        question=(
            "Using the project integration notes, determine the current gateway "
            "status, execution context boundary, excluded proxy capabilities, "
            "responsible owner, and next engineering step."
        ),
        sources=(
            _source(
                "doc-gateway-architecture-current",
                "architecture_note",
                "Gateway Architecture Current State",
                (
                    "Current architecture status: SFE runs as a library-only planner "
                    "runtime. The gateway proxy is planned but not implemented. The "
                    "note describes how future gateway work should preserve deterministic "
                    "selection records, but it does not identify the owner or define "
                    "excluded traffic interception behavior."
                ),
                required=True,
            ),
            _source(
                "doc-gateway-routing-policy",
                "routing_policy",
                "Gateway Routing Policy",
                (
                    "The routing policy states that the executor receives composed "
                    "selected-source context only. Full corpus access is not part of "
                    "the executor contract. This policy defines context boundaries but "
                    "does not define the current runtime mode or gateway ownership."
                ),
                required=True,
            ),
            _source(
                "doc-gateway-exclusions-current",
                "exclusion_policy",
                "Gateway Proxy Exclusions",
                (
                    "The current integration exclusions state: no automatic API-key "
                    "brokering or transparent production traffic interception. Gateway "
                    "experiments may use explicit test credentials in controlled smoke "
                    "runs, but this exclusion note does not name the owner or next step."
                ),
                required=True,
            ),
            _source(
                "doc-gateway-owner-decision-record",
                "owner_decision_record",
                "Gateway Owner Decision Record",
                (
                    "The gateway bridge work is owned by COMPONENT_OWNER_GATEWAY_BRIDGE. "
                    "The approved next step is build deterministic gateway contract "
                    "fixture before provider smoke. This record depends on the current "
                    "architecture, routing policy, and exclusions for the full decision."
                ),
                required=True,
            ),
            _source(
                "doc-gateway-proxy-beta-archive",
                "obsolete_release_note",
                "Archived Gateway Proxy Beta Note",
                _distractor_text(
                    "An archived beta note says a transparent gateway proxy shipped in "
                    "an early branch and could intercept production traffic. It is "
                    "obsolete and superseded by the current architecture note, which "
                    "keeps the runtime library-only and the proxy unimplemented."
                ),
                distractor=True,
            ),
            _source(
                "doc-gateway-glossary",
                "glossary",
                "Gateway and Proxy Glossary",
                _distractor_text(
                    "The glossary defines gateway, proxy, route, context, executor, "
                    "provider, and API-key terms. It contains correct vocabulary but "
                    "does not decide whether the gateway proxy exists, what context the "
                    "executor receives, or who owns the work."
                ),
                distractor=True,
            ),
            _source(
                "doc-local-ingress-ops-note",
                "operations_note",
                "Local Ingress Operations Note",
                _distractor_text(
                    "The local ingress note explains how maintainers run a temporary "
                    "test ingress for development. It mentions explicit credentials and "
                    "routing headers, but it is operational background and not an "
                    "authority for SFE gateway proxy behavior."
                ),
                distractor=True,
            ),
            _source(
                "doc-gateway-roadmap-draft",
                "draft_roadmap",
                "Gateway Roadmap Draft",
                _distractor_text(
                    "A draft roadmap proposes jumping directly to provider smoke tests "
                    "and hosted proxy trials. It omits the deterministic gateway "
                    "contract fixture and is not the accepted owner decision record."
                ),
                distractor=True,
            ),
            _source(
                "doc-provider-adapter-notes",
                "adapter_note",
                "Provider Adapter Notes",
                _distractor_text(
                    "Provider adapter notes discuss response parsing, token accounting, "
                    "timeouts, and model configuration. They are relevant to future "
                    "provider smoke tests but do not authorize a gateway proxy or define "
                    "the selected-source executor boundary."
                ),
                distractor=True,
            ),
            _source(
                "doc-security-review-prep",
                "security_review_note",
                "Security Review Preparation",
                _distractor_text(
                    "A security review preparation note lists questions about secrets, "
                    "bearer tokens, audit logs, and proxy traffic. It is intentionally "
                    "pre-decisional and does not set the current gateway exclusions."
                ),
                distractor=True,
            ),
            _source(
                "doc-cli-gateway-discussion",
                "discussion_note",
                "CLI Gateway Discussion",
                _distractor_text(
                    "A discussion note considers whether a CLI wrapper should mimic a "
                    "gateway. It uses the same gateway terminology but only covers local "
                    "developer ergonomics, not the project integration contract."
                ),
                distractor=True,
            ),
            _source(
                "doc-metrics-exporter-plan",
                "metrics_plan",
                "Gateway Metrics Exporter Plan",
                _distractor_text(
                    "The metrics exporter plan proposes counters for selected sources, "
                    "suppressed sources, and token estimates. It is useful for reporting "
                    "but does not define current runtime mode or proxy exclusions."
                ),
                distractor=True,
            ),
            _source(
                "doc-legacy-router-contract",
                "legacy_contract",
                "Legacy Router Contract",
                _distractor_text(
                    "A legacy router contract allowed the executor to inspect the full "
                    "context after routing. It is retained for comparison and conflicts "
                    "with the current selected-source-only routing policy."
                ),
                distractor=True,
            ),
            _source(
                "doc-gateway-release-checklist",
                "release_checklist",
                "Gateway Release Checklist",
                _distractor_text(
                    "The release checklist has placeholders for owner signoff, smoke "
                    "commands, logs, and rollback steps. The checklist is incomplete "
                    "and does not contain the canonical owner or next engineering step."
                ),
                distractor=True,
            ),
        ),
        required_source_ids=required_source_ids,
        distractor_source_ids=(
            "doc-gateway-proxy-beta-archive",
            "doc-gateway-glossary",
            "doc-local-ingress-ops-note",
            "doc-gateway-roadmap-draft",
            "doc-provider-adapter-notes",
            "doc-security-review-prep",
            "doc-cli-gateway-discussion",
            "doc-metrics-exporter-plan",
            "doc-legacy-router-contract",
            "doc-gateway-release-checklist",
        ),
        expected_fields=expected_fields,
        expected_answer=_answer_from_fields(expected_fields, required_source_ids),
    )


def _benchmark_roadmap_decision_task() -> LargeRealWorldTask:
    required_source_ids = (
        "doc-structural-50k-gate-result",
        "doc-phase2-composition-summary",
        "doc-phase3-roadmap-decision",
        "doc-honest-validation-policy",
    )
    expected_fields = {
        "structural_gate_result": "honest_structural_pass true on synthetic 50k+ structural task",
        "structural_stability": "5/5 repeated structural runs",
        "phase2_result": "synthetic and controlled organic multi-zone smoke checks passed under strict validation",
        "unproven_scope": "broad real-world generalization remains unproven",
        "next_benchmark": "large real-world inspired multi-zone benchmark",
        "honest_gate_rule": "fallback or repair cannot count as honest success",
    }
    return LargeRealWorldTask(
        fixture_id="large_real_world_benchmark_roadmap_gate",
        task_theme="benchmark_result_roadmap_decision",
        question=(
            "Using the benchmark result and roadmap notes, summarize the established "
            "structural and multi-zone results, what remains unproven, the next "
            "benchmark target, and the honest validation rule."
        ),
        sources=(
            _source(
                "doc-structural-50k-gate-result",
                "result_note",
                "Structural 50k Gate Result",
                (
                    "The structural benchmark gate recorded honest_structural_pass "
                    "true on synthetic 50k+ structural task. The stability run reported "
                    "5/5 repeated structural runs. This result is meaningful but does "
                    "not by itself establish multi-zone or broad real-world behavior."
                ),
                required=True,
            ),
            _source(
                "doc-phase2-composition-summary",
                "phase2_summary",
                "Phase 2 Composition Summary",
                (
                    "Phase 2 records that synthetic and controlled organic multi-zone "
                    "smoke checks passed under strict validation. Selector-only, "
                    "executor-only, combined, and repeat smoke paths were evaluated. "
                    "The summary does not select the next larger benchmark."
                ),
                required=True,
            ),
            _source(
                "doc-phase3-roadmap-decision",
                "roadmap_decision",
                "Phase 3 Roadmap Decision",
                (
                    "The current roadmap says broad real-world generalization remains "
                    "unproven. The next benchmark target is large real-world inspired "
                    "multi-zone benchmark, using controlled project-like sources before "
                    "moving to a broad organic corpus."
                ),
                required=True,
            ),
            _source(
                "doc-honest-validation-policy",
                "validation_policy",
                "Honest Validation Policy",
                (
                    "The honest validation policy states that fallback or repair cannot "
                    "count as honest success. Required source completeness, distractor "
                    "rejection, exact fields, exact evidence_source_ids, and parse "
                    "success must be reported separately."
                ),
                required=True,
            ),
            _source(
                "doc-legacy-roadmap-broad-corpus-first",
                "obsolete_roadmap",
                "Legacy Broad Corpus Roadmap",
                _distractor_text(
                    "A legacy roadmap proposed moving directly from the structural "
                    "benchmark to a broad repository corpus. It predates the large "
                    "real-world inspired benchmark decision and is no longer current."
                ),
                distractor=True,
            ),
            _source(
                "doc-token-savings-analysis-draft",
                "partial_analysis",
                "Token Savings Analysis Draft",
                _distractor_text(
                    "A draft analysis discusses estimated token reduction in structural "
                    "and synthetic tasks. It is topically relevant but does not contain "
                    "the honest validation rule or the accepted next benchmark target."
                ),
                distractor=True,
            ),
            _source(
                "doc-openai-smoke-blog-note",
                "announcement_note",
                "OpenAI Smoke Blog Note",
                _distractor_text(
                    "A short blog-style note says OpenAI smoke runs passed and looked "
                    "promising. It omits deterministic validation details, the 5/5 "
                    "structural stability marker, and the unproven scope caveat."
                ),
                distractor=True,
            ),
            _source(
                "doc-fixture-maintenance-checklist",
                "maintenance_checklist",
                "Fixture Maintenance Checklist",
                _distractor_text(
                    "The fixture checklist reminds maintainers to keep source IDs "
                    "canonical, avoid personal names, and preserve exact validation. "
                    "It does not state the benchmark results or roadmap target."
                ),
                distractor=True,
            ),
            _source(
                "doc-reporting-format-notes",
                "reporting_note",
                "Reporting Format Notes",
                _distractor_text(
                    "Reporting notes define Markdown headings, JSON summary fields, "
                    "and token estimate tables. They contain correct reporting vocabulary "
                    "but no canonical result values for the roadmap decision."
                ),
                distractor=True,
            ),
            _source(
                "doc-stability-loop-idea",
                "proposal_note",
                "Stability Loop Proposal",
                _distractor_text(
                    "A proposal suggests running future repeat-10 and repeat-25 loops. "
                    "It is not a completed benchmark result and should not replace the "
                    "recorded 5/5 repeated structural runs."
                ),
                distractor=True,
            ),
            _source(
                "doc-public-claims-review",
                "claims_review",
                "Public Claims Review",
                _distractor_text(
                    "The claims review warns not to describe benchmark results as proof "
                    "of general intelligence or universal context optimization. It is "
                    "useful context but does not define the next benchmark target."
                ),
                distractor=True,
            ),
            _source(
                "doc-provider-cost-note",
                "cost_note",
                "Provider Cost Note",
                _distractor_text(
                    "A provider cost note discusses API cost estimates, token accounting, "
                    "and smoke run hygiene. It is related to benchmark operations but "
                    "does not establish source selection success or honest pass rules."
                ),
                distractor=True,
            ),
            _source(
                "doc-minimal-real-world-result",
                "prior_benchmark_note",
                "Minimal Real-World Benchmark Result",
                _distractor_text(
                    "The minimal real-world inspired benchmark result records a small "
                    "controlled benchmark with modest token reduction. It motivates "
                    "larger context tests but is not itself the Phase 3 roadmap decision."
                ),
                distractor=True,
            ),
            _source(
                "doc-architecture-whiteboard",
                "whiteboard_note",
                "Architecture Whiteboard Notes",
                _distractor_text(
                    "Whiteboard notes speculate about spatial ledgers, verifier passes, "
                    "and source composition. They are exploratory and do not contain the "
                    "canonical structural gate result or the honest validation rule."
                ),
                distractor=True,
            ),
        ),
        required_source_ids=required_source_ids,
        distractor_source_ids=(
            "doc-legacy-roadmap-broad-corpus-first",
            "doc-token-savings-analysis-draft",
            "doc-openai-smoke-blog-note",
            "doc-fixture-maintenance-checklist",
            "doc-reporting-format-notes",
            "doc-stability-loop-idea",
            "doc-public-claims-review",
            "doc-provider-cost-note",
            "doc-minimal-real-world-result",
            "doc-architecture-whiteboard",
        ),
        expected_fields=expected_fields,
        expected_answer=_answer_from_fields(expected_fields, required_source_ids),
    )


class FixtureLargeRealWorldSelector:
    provider = "deterministic_mock"
    selector_mode = "fixture"
    model: str | None = None
    api_path: str | None = None

    def select(self, task: LargeRealWorldTask, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        selected_sources = [source_by_id(task, source_id) for source_id in task.required_source_ids]
        return build_selection(
            task=task,
            selected_sources=selected_sources,
            selector_name=FIXTURE_SELECTOR_NAME,
            selector_success=True,
            selector_used_fallback=False,
            confidence=1.0,
            rationale=(
                "Selected the required project-like sources because the available "
                "context contains plausible obsolete and partial distractors."
            ),
        )


class FixtureLargeRealWorldExecutor:
    provider = "deterministic_mock"
    executor_mode = "deterministic_fixture"
    model: str | None = None
    api_path: str | None = None

    def execute(
        self,
        task: LargeRealWorldTask,
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
    tasks: list[LargeRealWorldTask],
    repeat: int = 1,
    selector: LargeRealWorldSelector | None = None,
    executor: LargeRealWorldExecutor | None = None,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if not tasks:
        raise ValueError("At least one large real-world task is required.")

    selector = selector or FixtureLargeRealWorldSelector()
    executor = executor or FixtureLargeRealWorldExecutor()
    baseline_executor = FixtureLargeRealWorldExecutor()
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
                    mode="large_real_world_multi_zone",
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
            "token_reduction_target_percent": TOKEN_REDUCTION_TARGET_PERCENT,
        },
        "summary": summarize_runs(runs),
        "tasks": [task_to_dict(task) for task in tasks],
        "runs": runs,
    }


def _select_with_fallback(
    task: LargeRealWorldTask,
    selector: LargeRealWorldSelector,
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


def fixture_source_selection(task: LargeRealWorldTask) -> dict[str, Any]:
    return FixtureLargeRealWorldSelector().select(task, {})


def all_source_selection(task: LargeRealWorldTask) -> dict[str, Any]:
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
    task: LargeRealWorldTask,
    selected_sources: list[LargeRealWorldSource],
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
    task: LargeRealWorldTask,
    mode: str,
    selection: dict[str, Any],
    fixture_selection: dict[str, Any],
    repeat_index: int,
    executor: LargeRealWorldExecutor | None = None,
    output_override: str | None = None,
) -> dict[str, Any]:
    selected_source_ids = tuple(str(source_id) for source_id in selection["selected_source_ids"])
    composed_context = compose_context(task, selected_source_ids)
    executor = executor or FixtureLargeRealWorldExecutor()
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
    selected_source_tokens = int(selection["selected_source_token_estimate"])
    suppressed_source_tokens = int(selection["suppressed_source_token_estimate"])
    full_context_tokens = selected_source_tokens + suppressed_source_tokens
    composed_context_tokens = selected_source_tokens
    token_reduction = percent_reduction(full_context_tokens, composed_context_tokens)
    honest_pass = bool(
        mode == "large_real_world_multi_zone"
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
        "suppressed_source_ids": [
            source.source_id for source in task.sources if source.source_id not in selected_source_ids
        ],
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
        "honest_large_real_world_pass_after_repair": None,
        "executor": executor_result["executor"],
        "executor_mode": executor_result["executor_mode"],
        "executor_provider": executor_result["provider"],
        "executor_model": executor_result["model"],
        "executor_api_path": executor_result["api_path"],
        "executor_output_parse_success": executor_result["output_parse_success"],
        "executor_output_parse_error": executor_result["output_parse_error"],
        "actual_usage": executor_result.get("actual_usage"),
        "honest_large_real_world_pass": honest_pass,
        "success": success,
        "output": output,
        "selected_source_token_estimate": selected_source_tokens,
        "suppressed_source_token_estimate": suppressed_source_tokens,
        "total_composed_context_token_estimate": composed_context_tokens,
        "full_context_baseline_token_estimate": full_context_tokens,
        "token_reduction_percent": token_reduction,
        "selected_source_token_estimates": selection["selected_source_token_estimates"],
        "suppressed_source_token_estimates": selection["suppressed_source_token_estimates"],
    }


def validate_selection(task: LargeRealWorldTask, selection: dict[str, Any]) -> dict[str, Any]:
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


def validate_output(task: LargeRealWorldTask, output: str) -> dict[str, Any]:
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
    large_runs = [run for run in runs if run["mode"] == "large_real_world_multi_zone"]
    average_token_reduction = _average(
        run["token_reduction_percent"] for run in large_runs
        if run["token_reduction_percent"] is not None
    )
    return {
        "run_count": len(runs),
        "baseline_run_count": len(baseline_runs),
        "large_real_world_run_count": len(large_runs),
        "source_selection_success_rate": _rate(
            run["selector_success"] is True for run in large_runs
        ),
        "required_source_completeness_rate": _rate(
            run["required_source_complete"] is True for run in large_runs
        ),
        "distractor_rejection_rate": _rate(
            run["distractors_omitted"] is True for run in large_runs
        ),
        "fallback_count": sum(1 for run in large_runs if run["selector_used_fallback"]),
        "output_validation_complete_rate": _rate(
            run["output_validation_before_repair"] is True for run in large_runs
        ),
        "output_validation_after_repair_rate": None,
        "executor_output_parse_success_rate": _rate(
            run["executor_output_parse_success"] is True for run in large_runs
        ),
        "honest_large_real_world_pass_count": sum(
            1 for run in large_runs if run["honest_large_real_world_pass"]
        ),
        "honest_large_real_world_pass_rate": _rate(
            run["honest_large_real_world_pass"] is True for run in large_runs
        ),
        "average_full_context_baseline_tokens": _average(
            run["full_context_baseline_token_estimate"] for run in large_runs
        ),
        "average_selected_source_tokens": _average(
            run["selected_source_token_estimate"] for run in large_runs
        ),
        "average_suppressed_source_tokens": _average(
            run["suppressed_source_token_estimate"] for run in large_runs
        ),
        "average_composed_context_tokens": _average(
            run["total_composed_context_token_estimate"] for run in large_runs
        ),
        "average_token_reduction_percent": average_token_reduction,
        "token_reduction_target_percent": TOKEN_REDUCTION_TARGET_PERCENT,
        "token_reduction_target_met": average_token_reduction >= TOKEN_REDUCTION_TARGET_PERCENT,
        "actual_usage": {"input_tokens": None, "output_tokens": None, "total_tokens": None},
        "fixtures": _summarize_fixtures(large_runs),
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
                "suppressed_source_ids": first["suppressed_source_ids"],
                "required_source_complete": all(
                    run["required_source_complete"] for run in fixture_runs
                ),
                "distractors_omitted": all(
                    run["distractors_omitted"] for run in fixture_runs
                ),
                "fallback_used": any(run["selector_used_fallback"] for run in fixture_runs),
                "honest_large_real_world_pass_count": sum(
                    1 for run in fixture_runs if run["honest_large_real_world_pass"]
                ),
                "honest_large_real_world_pass_rate": _rate(
                    run["honest_large_real_world_pass"] is True for run in fixture_runs
                ),
                "full_context_token_estimate": _average(
                    run["full_context_baseline_token_estimate"] for run in fixture_runs
                ),
                "selected_context_token_estimate": _average(
                    run["total_composed_context_token_estimate"] for run in fixture_runs
                ),
                "average_token_reduction_percent": _average(
                    run["token_reduction_percent"] for run in fixture_runs
                    if run["token_reduction_percent"] is not None
                ),
            }
        )
    return summaries


def task_to_dict(task: LargeRealWorldTask) -> dict[str, Any]:
    data = asdict(task)
    data["full_context_baseline_token_estimate"] = sum(
        estimate_tokens(format_source(source)) for source in task.sources
    )
    data["required_composed_context_token_estimate"] = sum(
        estimate_tokens(format_source(source_by_id(task, source_id)))
        for source_id in task.required_source_ids
    )
    return data


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# Large Real-World Inspired Multi-Zone Benchmark",
        "",
        "This is a controlled, large real-world inspired benchmark. It tests "
        "multi-zone composition over larger realistic project-like context. It is "
        "not proof of broad real-world generalization.",
        "",
        "Deterministic validation is the source of truth. Success requires all "
        "required sources, no distractors, all required facts, and exact undecorated "
        "evidence source IDs.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Fixture count: {report['metadata']['task_count']}",
        f"Selector mode: `{report['metadata']['selector_mode']}`",
        f"Selector provider: `{report['metadata']['selector_provider']}`",
        f"Executor mode: `{report['metadata']['executor_mode']}`",
        f"Executor provider: `{report['metadata']['executor_provider']}`",
        f"Runs: {summary['run_count']}",
        "",
        "## Summary",
        "",
        f"Honest large real-world pass rate: {_format_percent(summary['honest_large_real_world_pass_rate'])}",
        f"Required source completeness rate: {_format_percent(summary['required_source_completeness_rate'])}",
        f"Distractor rejection rate: {_format_percent(summary['distractor_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        f"Output validation complete rate: {_format_percent(summary['output_validation_complete_rate'])}",
        f"Output validation after repair rate: {_format_optional_percent(summary['output_validation_after_repair_rate'])}",
        "Output repair status: not_supported",
        f"Average token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        f"Token reduction target: {TOKEN_REDUCTION_TARGET_PERCENT:.2f}%",
        f"Token reduction target met: {summary['token_reduction_target_met']}",
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
        "| Fixture ID | Selected sources | Suppressed sources | Complete | Distractors omitted | Fallback used | Honest pass rate | Full tokens | Selected tokens | Token reduction |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for fixture in summary["fixtures"]:
        lines.append(
            f"| `{fixture['fixture_id']}` | "
            f"{', '.join(fixture['selected_source_ids'])} | "
            f"{', '.join(fixture['suppressed_source_ids'])} | "
            f"{fixture['required_source_complete']} | "
            f"{fixture['distractors_omitted']} | "
            f"{fixture['fallback_used']} | "
            f"{_format_percent(fixture['honest_large_real_world_pass_rate'])} | "
            f"{fixture['full_context_token_estimate']:.2f} | "
            f"{fixture['selected_context_token_estimate']:.2f} | "
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
            f"{run['honest_large_real_world_pass']} | "
            f"{', '.join(run['selected_source_ids'])} | "
            f"{', '.join(run['missing_required_source_ids']) or 'none'} | "
            f"{', '.join(run['unexpected_distractor_source_ids']) or 'none'} | "
            f"{_format_optional_percent(run['token_reduction_percent'])} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("Large real-world inspired multi-zone benchmark")
    print(f"selector mode: {report['metadata']['selector_mode']}")
    print(f"selector provider: {report['metadata']['selector_provider']}")
    print(f"executor mode: {report['metadata']['executor_mode']}")
    print(f"executor provider: {report['metadata']['executor_provider']}")
    print(f"runs: {summary['run_count']}")
    print(
        "honest large real-world pass rate: "
        f"{_format_percent(summary['honest_large_real_world_pass_rate'])}"
    )
    print(f"fallback count: {summary['fallback_count']}")
    print(
        "average token reduction: "
        f"{_format_optional_percent(summary['average_token_reduction_percent'])}"
    )
    print(f"token reduction target met: {summary['token_reduction_target_met']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def compose_context(task: LargeRealWorldTask, source_ids: tuple[str, ...]) -> str:
    return "\n\n".join(format_source(source_by_id(task, source_id)) for source_id in source_ids)


def format_source(source: LargeRealWorldSource) -> str:
    return "\n".join(
        [
            f"SOURCE ID: {source.source_id}",
            f"SOURCE ROLE: {source.role}",
            f"TITLE: {source.title}",
            source.text,
        ]
    )


def source_by_id(task: LargeRealWorldTask, source_id: str) -> LargeRealWorldSource:
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
) -> LargeRealWorldSource:
    return LargeRealWorldSource(
        source_id=source_id,
        role=role,
        title=title,
        text=text,
        required=required,
        distractor=distractor,
    )


def _distractor_text(summary: str) -> str:
    return (
        f"{summary} This source is realistic project context and may share labels, "
        "components, or terminology with the task. It is intentionally insufficient "
        "for the validated answer because it is obsolete, partial, non-authoritative, "
        "or scoped to a different operational decision."
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
