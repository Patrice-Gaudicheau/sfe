"""Run the controlled output-variation benchmark.

This benchmark compares full-context baseline execution against fixture-selected
SFE-style context on tasks where output length can vary. Fixture execution is
deterministic and is meant to validate benchmark accounting, not real LLM
behavior.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import (  # noqa: E402
    DEFAULT_EXECUTOR_MODEL as DEFAULT_OPENAI_EXECUTOR_MODEL,
    OpenAIAPIProvider,
)
from runtime.metrics import (  # noqa: E402
    average,
    estimate_text_tokens,
    estimated_token_usage,
    percent_reduction,
    write_json_report,
    write_text_report,
)
from runtime.run_experiment import _extract_response_text, _extract_token_usage  # noqa: E402
from sfe.env import load_repo_env  # noqa: E402
from sfe_proxy.shadow_router import (  # noqa: E402
    LEMONADE_ROUTER_PROVIDER,
    OPENAI_ROUTER_PROVIDER,
    ShadowRouter,
    ShadowRouterInput,
    create_shadow_router,
)


BENCHMARK_TYPE = "output_variation/controlled"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "output_variation_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "output_variation_benchmark.md"
MODE_BASELINE = "baseline"
MODE_SELECTED = "selected"
MODES = (MODE_BASELINE, MODE_SELECTED)
EXECUTOR_FIXTURE = "fixture"
EXECUTOR_OPENAI_API = "openai-api"
EXECUTORS = (EXECUTOR_FIXTURE, EXECUTOR_OPENAI_API)
SELECTION_SOURCE_FIXTURE = "fixture"
SELECTION_SOURCE_ROUTER = "router"
SELECTION_SOURCES = (SELECTION_SOURCE_FIXTURE, SELECTION_SOURCE_ROUTER)
DEFAULT_ROUTER_SELECTION_PROVIDER = OPENAI_ROUTER_PROVIDER
USABLE_ROUTER_SELECTION_STATUSES = {
    "candidate_selected",
    "eligible",
    "selected",
    "success",
}
DRY_RUN_NOTE = (
    "Fixture outputs are deterministic synthetic outputs used to validate the "
    "benchmark pipeline and token-accounting logic. They are not evidence that "
    "SFE reduces or increases output tokens in real LLM behavior."
)
ROUTER_SELECTION_NOTE = (
    "Router selection uses the proxy shadow-router selection path. Executor token "
    "comparisons remain baseline-vs-selected executor costs; router selection "
    "metadata is reported separately and is not mixed into those totals. Actual "
    "router provider token usage is not currently available from the shadow-router "
    "result."
)


@dataclass(frozen=True)
class OutputVariationContextBlock:
    block_id: str
    title: str
    text: str
    selected: bool = False
    distractor: bool = False


@dataclass(frozen=True)
class OutputVariationTask:
    task_label: str
    family: str
    question: str
    output_contract: str
    context_blocks: tuple[OutputVariationContextBlock, ...]
    selected_block_ids: tuple[str, ...]
    required_facts: tuple[str, ...]
    forbidden_mentions: tuple[str, ...]
    format_markers: tuple[str, ...]
    dry_run_outputs: dict[str, str]


class OutputVariationExecutor(Protocol):
    executor_name: str
    provider: str
    model: str | None

    def execute(self, task: OutputVariationTask, mode: str, prompt: str) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class OutputVariationSelection:
    selection_source: str
    selected_block_ids: tuple[str, ...]
    router_used: bool = False
    router_provider: str | None = None
    router_status: str | None = None
    router_reason: str | None = None
    router_error_type: str | None = None
    router_confidence: float | None = None
    router_selection_usable: bool = True
    router_selected_block_ids: tuple[str, ...] = ()
    router_latency_ms: int | None = None
    router_estimated_selected_input_tokens: int | None = None
    router_estimated_token_reduction_pct: float | None = None


class OutputVariationSelector(Protocol):
    selection_source: str
    router_used: bool
    router_provider: str | None
    router_model: str | None

    def select(self, task: OutputVariationTask, repeat_index: int) -> OutputVariationSelection:
        ...


class FixtureOutputVariationSelector:
    selection_source = SELECTION_SOURCE_FIXTURE
    router_used = False
    router_provider: str | None = None
    router_model: str | None = None

    def select(self, task: OutputVariationTask, repeat_index: int) -> OutputVariationSelection:
        del repeat_index
        return OutputVariationSelection(
            selection_source=self.selection_source,
            selected_block_ids=task.selected_block_ids,
            router_used=False,
            router_selection_usable=True,
        )


@dataclass(frozen=True)
class _RouterSelectionConfig:
    shadow_router_timeout_seconds: int


class ProxyShadowRouterOutputVariationSelector:
    selection_source = SELECTION_SOURCE_ROUTER
    router_used = True

    def __init__(
        self,
        *,
        provider: str | None = None,
        timeout_seconds: int = 30,
        router_factory: Callable[[str, _RouterSelectionConfig], ShadowRouter] | None = None,
    ) -> None:
        self.router_provider = _router_provider_from_env(provider)
        self.router_model = _router_model_from_env(self.router_provider)
        self.config = _RouterSelectionConfig(
            shadow_router_timeout_seconds=max(1, int(timeout_seconds))
        )
        self.router_factory = router_factory or (
            lambda router_provider, config: create_shadow_router(
                router_provider,
                config=config,
            )
        )

    def select(self, task: OutputVariationTask, repeat_index: int) -> OutputVariationSelection:
        router_input = build_shadow_router_input(
            task,
            repeat_index=repeat_index,
            router_model=self.router_model,
        )
        try:
            result = self.router_factory(self.router_provider, self.config).analyze(
                router_input
            )
        except Exception as exc:  # noqa: BLE001
            return OutputVariationSelection(
                selection_source=self.selection_source,
                selected_block_ids=(),
                router_used=True,
                router_provider=self.router_provider,
                router_error_type=type(exc).__name__,
                router_reason="router_call_failed",
                router_selection_usable=False,
            )

        known_block_ids = {block.block_id for block in task.context_blocks}
        unknown_selected_block_ids = tuple(
            block_id
            for block_id in result.candidate_selected_segment_ids
            if block_id not in known_block_ids
        )
        selected = tuple(
            block_id
            for block_id in result.candidate_selected_segment_ids
            if block_id in known_block_ids
        )
        usable = (
            result.router_status in USABLE_ROUTER_SELECTION_STATUSES
            and result.error_type is None
            and bool(selected)
            and not unknown_selected_block_ids
        )
        return OutputVariationSelection(
            selection_source=self.selection_source,
            selected_block_ids=selected if usable else (),
            router_used=True,
            router_provider=self.router_provider,
            router_status=result.router_status,
            router_reason=result.router_reason,
            router_error_type=result.error_type,
            router_confidence=result.confidence,
            router_selection_usable=usable,
            router_selected_block_ids=tuple(result.candidate_selected_segment_ids),
            router_latency_ms=result.router_latency_ms,
            router_estimated_selected_input_tokens=(
                result.estimated_router_selected_input_tokens
            ),
            router_estimated_token_reduction_pct=(
                result.estimated_router_token_reduction_pct
            ),
        )


class FixtureOutputVariationExecutor:
    executor_name = EXECUTOR_FIXTURE
    provider = "deterministic_fixture"
    model: str | None = None

    def execute(self, task: OutputVariationTask, mode: str, prompt: str) -> dict[str, Any]:
        output = task.dry_run_outputs[mode]
        return {
            "output": output,
            "usage": estimated_token_usage(prompt, output),
            "raw_response": None,
        }


class OpenAIOutputVariationExecutor:
    executor_name = EXECUTOR_OPENAI_API
    provider = EXECUTOR_OPENAI_API

    def __init__(
        self,
        model: str,
        max_tokens: int,
        provider: OpenAIAPIProvider | None = None,
    ) -> None:
        if not model:
            raise ValueError("OpenAI executor model is required.")
        if max_tokens < 1:
            raise ValueError("--max-tokens must be at least 1.")
        self.model = model
        self.max_tokens = max_tokens
        self.provider_instance = provider or OpenAIAPIProvider()

    def execute(self, task: OutputVariationTask, mode: str, prompt: str) -> dict[str, Any]:
        response = self.provider_instance.chat(
            [{"role": "user", "content": prompt}],
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=0.0,
            system_instruction=(
                "You are executing a controlled benchmark. Answer only from the "
                "provided context and follow the requested output contract."
            ),
        )
        output = _extract_response_text(response)
        return {
            "output": output,
            "usage": _extract_token_usage(response, prompt, output),
            "raw_response": response,
        }


def main() -> None:
    load_repo_env()
    args = _parse_args()
    tasks = get_output_variation_tasks()
    if args.task_family:
        tasks = [task for task in tasks if task.family == args.task_family]
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1.")
        tasks = tasks[: args.limit]
    executor = _build_executor(args)
    selector = _build_selector(args)
    report = run_benchmark(
        tasks=tasks,
        repeat=args.repeat,
        executor=executor,
        selector=selector,
    )
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the controlled SFE output-variation benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--task-family",
        choices=task_families(),
        help="Run only one output-variation task family.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Force fixture execution.")
    parser.add_argument("--executor", choices=EXECUTORS, default=EXECUTOR_FIXTURE)
    parser.add_argument(
        "--selection-source",
        choices=SELECTION_SOURCES,
        default=SELECTION_SOURCE_FIXTURE,
        help="Use deterministic fixture selection or the proxy shadow-router path.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or DEFAULT_OPENAI_EXECUTOR_MODEL,
    )
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    args = parser.parse_args()
    if args.dry_run:
        args.executor = EXECUTOR_FIXTURE
    if args.dry_run and args.selection_source == SELECTION_SOURCE_ROUTER:
        parser.error("--selection-source router requires live router selection; omit --dry-run.")
    if (
        args.selection_source == SELECTION_SOURCE_ROUTER
        and args.executor == EXECUTOR_FIXTURE
    ):
        parser.error("--selection-source router requires --executor openai-api.")
    return args


def _build_executor(args: argparse.Namespace) -> OutputVariationExecutor:
    if args.executor == EXECUTOR_FIXTURE:
        return FixtureOutputVariationExecutor()
    return OpenAIOutputVariationExecutor(model=args.model, max_tokens=args.max_tokens)


def _build_selector(args: argparse.Namespace) -> OutputVariationSelector:
    if args.selection_source == SELECTION_SOURCE_FIXTURE:
        return FixtureOutputVariationSelector()
    return ProxyShadowRouterOutputVariationSelector()


def task_families() -> tuple[str, ...]:
    return (
        "ambiguous_diagnostic",
        "broad_synthesis",
        "patch_planning",
        "bounded_output_control",
        "distractor_inflation",
    )


def get_output_variation_tasks() -> list[OutputVariationTask]:
    return [
        OutputVariationTask(
            task_label="output_variation_ambiguous_diagnostic",
            family="ambiguous_diagnostic",
            question=(
                "Diagnose the checkout incident and name the most likely cause, "
                "owner, and next action."
            ),
            output_contract="Write a concise diagnostic note with cause, owner, and next action.",
            context_blocks=(
                _block(
                    "payments-cache",
                    "Payments Cache Incident",
                    (
                        "The checkout incident was caused by stale PSP routing cache entries. "
                        "Only card payments through PSP-Blue failed. Owner Priya Nair must flush "
                        "the PSP routing cache and pin cache epoch pay-cache-17."
                    ),
                    selected=True,
                ),
                _block(
                    "search-index",
                    "Search Index Alert",
                    (
                        "Search indexing lagged during the same window. It affected catalog "
                        "ranking only and did not affect checkout. Owner Mason Vale closed it."
                    ),
                    distractor=True,
                ),
                _block(
                    "email-provider",
                    "Email Provider Degradation",
                    (
                        "Email receipts were delayed by provider EchoMail. This created support "
                        "tickets but was not the checkout failure cause."
                    ),
                    distractor=True,
                ),
            ),
            selected_block_ids=("payments-cache",),
            required_facts=("stale PSP routing cache", "Priya Nair", "pay-cache-17"),
            forbidden_mentions=("Search indexing", "EchoMail", "Mason Vale"),
            format_markers=("Cause:", "Owner:", "Next action:"),
            dry_run_outputs={
                MODE_BASELINE: (
                    "Cause: The most likely cause is stale PSP routing cache, but search "
                    "index lag and EchoMail receipt delay occurred nearby and should be ruled "
                    "out. Owner: Priya Nair for the payment path, with Mason Vale unrelated "
                    "to checkout. Next action: flush PSP routing cache and pin pay-cache-17."
                ),
                MODE_SELECTED: (
                    "Cause: stale PSP routing cache. Owner: Priya Nair. Next action: flush "
                    "the PSP routing cache and pin pay-cache-17."
                ),
            },
        ),
        OutputVariationTask(
            task_label="output_variation_broad_synthesis",
            family="broad_synthesis",
            question="Synthesize the launch readiness note for the Atlas mobile beta.",
            output_contract="Return a focused synthesis with decision, blocker, owner, and evidence.",
            context_blocks=(
                _block(
                    "beta-readiness",
                    "Atlas Mobile Beta Readiness",
                    (
                        "Atlas mobile beta is ready for a limited launch after fixing the consent "
                        "copy blocker. Owner Lina Park must approve consent-copy-v4. Evidence: "
                        "crash-free sessions reached 99.2 percent and payment smoke tests passed."
                    ),
                    selected=True,
                ),
                _block(
                    "growth-plan",
                    "Growth Launch Ideas",
                    (
                        "The growth team proposed referral banners, creator incentives, and "
                        "regional launch copy. These are not beta-readiness blockers."
                    ),
                    distractor=True,
                ),
                _block(
                    "support-training",
                    "Support Training",
                    (
                        "Support needs updated macros for billing, login recovery, and mobile "
                        "beta onboarding. This is operational background, not the launch decision."
                    ),
                    distractor=True,
                ),
            ),
            selected_block_ids=("beta-readiness",),
            required_facts=("limited launch", "consent-copy-v4", "Lina Park"),
            forbidden_mentions=("referral banners", "creator incentives", "billing macros"),
            format_markers=("Decision:", "Blocker:", "Owner:", "Evidence:"),
            dry_run_outputs={
                MODE_BASELINE: (
                    "Decision: limited launch is appropriate. Blocker: consent-copy-v4 approval. "
                    "Owner: Lina Park. Evidence: 99.2 percent crash-free sessions and passing "
                    "payment smoke tests. The growth referral banners and support billing macros "
                    "can continue separately but should not gate the beta."
                ),
                MODE_SELECTED: (
                    "Decision: limited launch. Blocker: consent-copy-v4 approval. Owner: Lina "
                    "Park. Evidence: 99.2 percent crash-free sessions and passing payment smoke tests."
                ),
            },
        ),
        OutputVariationTask(
            task_label="output_variation_patch_planning",
            family="patch_planning",
            question="Plan the minimal patch for the invoice export failure.",
            output_contract="Return a compact patch plan with files, change, and test.",
            context_blocks=(
                _block(
                    "invoice-exporter",
                    "Relevant File: billing/exporter.py",
                    (
                        "billing/exporter.py drops invoice rows when currency is None. The patch "
                        "should default missing currency to account_currency before serializing CSV. "
                        "Test tests/test_billing_exporter.py should cover a missing currency invoice."
                    ),
                    selected=True,
                ),
                _block(
                    "ui-table",
                    "Unrelated File: ui/invoice_table.tsx",
                    (
                        "ui/invoice_table.tsx renders invoice cells and filters date ranges. It "
                        "does not serialize CSV export rows."
                    ),
                    distractor=True,
                ),
                _block(
                    "legacy-job",
                    "Legacy Batch Job",
                    (
                        "jobs/legacy_invoice_dump.py still uses an older TSV exporter. It is not "
                        "called by the failing CSV export path."
                    ),
                    distractor=True,
                ),
            ),
            selected_block_ids=("invoice-exporter",),
            required_facts=("billing/exporter.py", "account_currency", "tests/test_billing_exporter.py"),
            forbidden_mentions=("ui/invoice_table.tsx", "legacy_invoice_dump.py"),
            format_markers=("Files:", "Change:", "Test:"),
            dry_run_outputs={
                MODE_BASELINE: (
                    "Files: billing/exporter.py is the likely target; verify ui/invoice_table.tsx "
                    "and jobs/legacy_invoice_dump.py are not involved. Change: default missing "
                    "currency to account_currency before CSV serialization. Test: add coverage "
                    "in tests/test_billing_exporter.py for a missing currency invoice."
                ),
                MODE_SELECTED: (
                    "Files: billing/exporter.py. Change: default missing currency to "
                    "account_currency before CSV serialization. Test: add "
                    "tests/test_billing_exporter.py coverage for a missing currency invoice."
                ),
            },
        ),
        OutputVariationTask(
            task_label="output_variation_bounded_output_control",
            family="bounded_output_control",
            question="Return the release gate fields for Vega R7.",
            output_contract=(
                "Return exactly these lines: status, owner, blocker, evidence_block. "
                "No extra commentary."
            ),
            context_blocks=(
                _block(
                    "vega-r7-final",
                    "Vega R7 Gate",
                    (
                        "Vega R7 status is hold. Owner is Omar Chen. Blocker is privacy-review-19. "
                        "The evidence block is vega-r7-final."
                    ),
                    selected=True,
                ),
                _block(
                    "vega-r6-history",
                    "Vega R6 History",
                    "Vega R6 shipped after resolving privacy-review-12. This is prior history.",
                    distractor=True,
                ),
            ),
            selected_block_ids=("vega-r7-final",),
            required_facts=("hold", "Omar Chen", "privacy-review-19", "vega-r7-final"),
            forbidden_mentions=("privacy-review-12", "Vega R6"),
            format_markers=("status:", "owner:", "blocker:", "evidence_block:"),
            dry_run_outputs={
                MODE_BASELINE: (
                    "status: hold\nowner: Omar Chen\nblocker: privacy-review-19\n"
                    "evidence_block: vega-r7-final"
                ),
                MODE_SELECTED: (
                    "status: hold\nowner: Omar Chen\nblocker: privacy-review-19\n"
                    "evidence_block: vega-r7-final"
                ),
            },
        ),
        OutputVariationTask(
            task_label="output_variation_distractor_inflation",
            family="distractor_inflation",
            question="Explain the active mitigation for the Nimbus alert storm.",
            output_contract="Return the active mitigation and avoid rejected alternatives.",
            context_blocks=(
                _block(
                    "nimbus-active",
                    "Nimbus Active Mitigation",
                    (
                        "The active mitigation is alert_epoch_dedupe owned by Sora Kim. It "
                        "deduplicates repeated alerts by incident epoch and ships behind flag "
                        "nimbus-alert-dedupe."
                    ),
                    selected=True,
                ),
                _block(
                    "nimbus-rejected",
                    "Rejected Mitigations",
                    (
                        "Rejected alternatives included raising pager thresholds and muting "
                        "regional alerts. Those options were tempting but explicitly rejected."
                    ),
                    distractor=True,
                ),
            ),
            selected_block_ids=("nimbus-active",),
            required_facts=("alert_epoch_dedupe", "Sora Kim", "nimbus-alert-dedupe"),
            forbidden_mentions=("raising pager thresholds", "muting regional alerts"),
            format_markers=("Active mitigation:", "Owner:", "Flag:"),
            dry_run_outputs={
                MODE_BASELINE: (
                    "Active mitigation: alert_epoch_dedupe. Owner: Sora Kim. Flag: "
                    "nimbus-alert-dedupe. Do not use the rejected alternatives of raising "
                    "pager thresholds or muting regional alerts."
                ),
                MODE_SELECTED: (
                    "Active mitigation: alert_epoch_dedupe. Owner: Sora Kim. Flag: "
                    "nimbus-alert-dedupe."
                ),
            },
        ),
    ]


def _block(
    block_id: str,
    title: str,
    text: str,
    *,
    selected: bool = False,
    distractor: bool = False,
) -> OutputVariationContextBlock:
    return OutputVariationContextBlock(
        block_id=block_id,
        title=title,
        text=text,
        selected=selected,
        distractor=distractor,
    )


def run_benchmark(
    *,
    tasks: list[OutputVariationTask],
    repeat: int,
    executor: OutputVariationExecutor | None = None,
    selector: OutputVariationSelector | None = None,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if not tasks:
        raise ValueError("At least one output-variation task is required.")
    executor = executor or FixtureOutputVariationExecutor()
    selector = selector or FixtureOutputVariationSelector()
    runs: list[dict[str, Any]] = []
    for task in tasks:
        for repeat_index in range(1, repeat + 1):
            runs.append(
                execute_task(
                    task=task,
                    mode=MODE_BASELINE,
                    repeat_index=repeat_index,
                    executor=executor,
                    selection=baseline_selection(selector),
                )
            )
            selection = selector.select(task, repeat_index)
            if selection.router_used and not selection.router_selection_usable:
                runs.append(skipped_selected_run(task, repeat_index, executor, selection))
                continue
            runs.append(
                execute_task(
                    task=task,
                    mode=MODE_SELECTED,
                    repeat_index=repeat_index,
                    executor=executor,
                    selection=selection,
                )
            )
    comparisons = compare_runs(runs)
    is_fixture = executor.executor_name == EXECUTOR_FIXTURE
    notes = []
    if is_fixture:
        notes.append(DRY_RUN_NOTE)
    if selector.router_used:
        notes.append(ROUTER_SELECTION_NOTE)
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_type": BENCHMARK_TYPE,
            "task_count": len(tasks),
            "repeat": repeat,
            "run_count": len(runs),
            "comparison_count": len(comparisons),
            "executor": executor.executor_name,
            "executor_provider": executor.provider,
            "executor_model": executor.model,
            "dry_run": is_fixture,
            "dry_run_fixture_outputs": is_fixture,
            "dry_run_note": DRY_RUN_NOTE if is_fixture else None,
            "selection_source": selector.selection_source,
            "selection_strategy": (
                "fixture_selected_context"
                if selector.selection_source == SELECTION_SOURCE_FIXTURE
                else "proxy_shadow_router_selected_context"
            ),
            "router_used": selector.router_used,
            "router_provider": selector.router_provider,
            "router_model": selector.router_model,
            "router_selection_note": ROUTER_SELECTION_NOTE if selector.router_used else None,
        },
        "summary": summarize(comparisons, notes=notes),
        "tasks": [task_to_dict(task) for task in tasks],
        "runs": runs,
        "comparisons": comparisons,
    }


def execute_task(
    *,
    task: OutputVariationTask,
    mode: str,
    repeat_index: int,
    executor: OutputVariationExecutor,
    selection: OutputVariationSelection,
) -> dict[str, Any]:
    prompt = build_prompt(task, mode, selected_block_ids=selection.selected_block_ids)
    result = executor.execute(task, mode, prompt)
    output = str(result["output"])
    usage = result["usage"]
    quality = validate_output(task, output)
    used_block_ids = block_ids_for_mode(
        task,
        mode,
        selected_block_ids=selection.selected_block_ids,
    )
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "task_label": task.task_label,
        "family": task.family,
        "mode": mode,
        "execution_status": "completed",
        "repeat_index": repeat_index,
        "executor": executor.executor_name,
        "provider": executor.provider,
        "model": executor.model,
        **selection_fields(selection),
        "input_tokens": int(usage["input_tokens"]),
        "output_tokens": int(usage["output_tokens"]),
        "total_tokens": int(usage["total_tokens"]),
        "quality": quality,
        "success": quality["success"],
        "compactness_score": compactness_score(quality["required_fact_count"], int(usage["output_tokens"])),
        "used_block_ids": used_block_ids,
        "used_block_count": len(used_block_ids),
        "output": output,
    }


def skipped_selected_run(
    task: OutputVariationTask,
    repeat_index: int,
    executor: OutputVariationExecutor,
    selection: OutputVariationSelection,
) -> dict[str, Any]:
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "task_label": task.task_label,
        "family": task.family,
        "mode": MODE_SELECTED,
        "execution_status": "skipped_router_selection_unusable",
        "repeat_index": repeat_index,
        "executor": executor.executor_name,
        "provider": executor.provider,
        "model": executor.model,
        **selection_fields(selection),
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
        "quality": {
            "required_facts_present": False,
            "forbidden_mentions_absent": False,
            "format_respected": False,
            "success": False,
            "missing_required_facts": list(task.required_facts),
            "present_forbidden_mentions": [],
            "missing_format_markers": list(task.format_markers),
        },
        "success": False,
        "compactness_score": None,
        "used_block_ids": [],
        "used_block_count": 0,
        "output": "",
        "skip_reason": selection.router_reason or "router_selection_unusable",
    }


def baseline_selection(selector: OutputVariationSelector) -> OutputVariationSelection:
    return OutputVariationSelection(
        selection_source=selector.selection_source,
        selected_block_ids=(),
        router_used=selector.router_used,
        router_provider=selector.router_provider,
        router_selection_usable=True,
    )


def selection_fields(selection: OutputVariationSelection) -> dict[str, Any]:
    return {
        "selection_source": selection.selection_source,
        "router_used": selection.router_used,
        "router_provider": selection.router_provider,
        "router_status": selection.router_status,
        "router_reason": selection.router_reason,
        "router_error_type": selection.router_error_type,
        "router_confidence": selection.router_confidence,
        "router_selection_usable": selection.router_selection_usable,
        "router_selected_block_ids": list(selection.router_selected_block_ids),
        "router_latency_ms": selection.router_latency_ms,
        "router_estimated_selected_input_tokens": (
            selection.router_estimated_selected_input_tokens
        ),
        "router_estimated_token_reduction_pct": (
            selection.router_estimated_token_reduction_pct
        ),
    }


def build_prompt(
    task: OutputVariationTask,
    mode: str,
    *,
    selected_block_ids: tuple[str, ...] | None = None,
) -> str:
    context = "\n\n".join(
        format_block(block)
        for block in blocks_for_mode(task, mode, selected_block_ids=selected_block_ids)
    )
    return (
        "Answer using only the provided context. Do not use outside facts.\n\n"
        f"Benchmark: {BENCHMARK_TYPE}\n"
        f"Task family: {task.family}\n"
        f"Mode: {mode}\n"
        f"Question: {task.question}\n\n"
        f"Output contract:\n{task.output_contract}\n\n"
        f"Context:\n{context}\n\n"
        "Final answer:"
    )


def blocks_for_mode(
    task: OutputVariationTask,
    mode: str,
    *,
    selected_block_ids: tuple[str, ...] | None = None,
) -> list[OutputVariationContextBlock]:
    if mode == MODE_BASELINE:
        return list(task.context_blocks)
    if mode == MODE_SELECTED:
        selected = set(selected_block_ids or task.selected_block_ids)
        return [block for block in task.context_blocks if block.block_id in selected]
    raise ValueError(f"Unknown mode: {mode}")


def block_ids_for_mode(
    task: OutputVariationTask,
    mode: str,
    *,
    selected_block_ids: tuple[str, ...] | None = None,
) -> list[str]:
    return [
        block.block_id
        for block in blocks_for_mode(
            task,
            mode,
            selected_block_ids=selected_block_ids,
        )
    ]


def format_block(block: OutputVariationContextBlock) -> str:
    return f"BLOCK {block.block_id} - {block.title}\n{block.text}"


def build_shadow_router_input(
    task: OutputVariationTask,
    *,
    repeat_index: int,
    router_model: str | None,
) -> ShadowRouterInput:
    candidate_segments = [router_candidate_segment(block) for block in task.context_blocks]
    rough_tokens = estimate_text_tokens(
        "\n\n".join(
            [
                task.question,
                task.output_contract,
                *[format_block(block) for block in task.context_blocks],
            ]
        )
    )
    return ShadowRouterInput(
        request_id=f"{task.task_label}:{repeat_index}",
        endpoint="output_variation_benchmark",
        model=router_model,
        rough_estimated_input_tokens=rough_tokens,
        candidate_segments_metadata=[
            {key: value for key, value in segment.items() if key != "text"}
            for segment in candidate_segments
        ],
        eligibility_metadata={
            "sfe_routing_eligible": True,
            "eligibility_reason": "output_variation_router_selection",
            "eligibility_threshold_tokens": 0,
            "benchmark_type": BENCHMARK_TYPE,
            "task_family": task.family,
            "question": task.question,
            "output_contract": task.output_contract,
        },
        request_body_bytes=sum(len(block.text.encode("utf-8")) for block in task.context_blocks),
        stream=False,
        candidate_text_segments=candidate_segments,
    )


def router_candidate_segment(block: OutputVariationContextBlock) -> dict[str, Any]:
    text = format_block(block)
    return {
        "segment_id": block.block_id,
        "source": block.title,
        "text": text,
        "text_chars": len(text),
        "text_bytes": len(text.encode("utf-8")),
        "estimated_tokens": estimate_text_tokens(text),
        "distractor": block.distractor,
        "fixture_selected": block.selected,
    }


def _router_provider_from_env(provider: str | None) -> str:
    selected = (
        provider
        or os.getenv("SFE_PROXY_SHADOW_ROUTER_PROVIDER", "").strip()
        or DEFAULT_ROUTER_SELECTION_PROVIDER
    )
    if selected not in {OPENAI_ROUTER_PROVIDER, LEMONADE_ROUTER_PROVIDER}:
        raise ValueError(
            "Router selection source requires SFE_PROXY_SHADOW_ROUTER_PROVIDER "
            "to be openai or lemonade."
        )
    return selected


def _router_model_from_env(provider: str) -> str | None:
    if provider == OPENAI_ROUTER_PROVIDER:
        return os.getenv("SFE_OPENAI_ROUTER_MODEL") or None
    if provider == LEMONADE_ROUTER_PROVIDER:
        return os.getenv("SFE_LEMONADE_MODEL") or os.getenv("SFE_ROUTER_MODEL") or None
    return None


def validate_output(task: OutputVariationTask, output: str) -> dict[str, Any]:
    normalized = output.lower()
    required_checks = [
        {"fact": fact, "present": fact.lower() in normalized}
        for fact in task.required_facts
    ]
    forbidden_checks = [
        {"mention": mention, "absent": mention.lower() not in normalized}
        for mention in task.forbidden_mentions
    ]
    format_checks = [
        {"marker": marker, "present": marker.lower() in normalized}
        for marker in task.format_markers
    ]
    required_facts_present = all(check["present"] for check in required_checks)
    forbidden_mentions_absent = all(check["absent"] for check in forbidden_checks)
    format_respected = all(check["present"] for check in format_checks)
    return {
        "required_facts_present": required_facts_present,
        "forbidden_mentions_absent": forbidden_mentions_absent,
        "format_respected": format_respected,
        "success": required_facts_present and forbidden_mentions_absent and format_respected,
        "required_fact_checks": required_checks,
        "forbidden_mention_checks": forbidden_checks,
        "format_checks": format_checks,
        "missing_required_facts": [
            check["fact"] for check in required_checks if not check["present"]
        ],
        "present_forbidden_mentions": [
            check["mention"] for check in forbidden_checks if not check["absent"]
        ],
        "missing_format_markers": [
            check["marker"] for check in format_checks if not check["present"]
        ],
        "required_fact_count": sum(1 for check in required_checks if check["present"]),
    }


def compactness_score(required_fact_count: int, output_tokens: int) -> float:
    return required_fact_count / max(output_tokens, 1)


def compare_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comparisons = []
    keys = sorted({(run["task_label"], run["repeat_index"]) for run in runs})
    for task_label, repeat_index in keys:
        pair = [
            run for run in runs
            if run["task_label"] == task_label and run["repeat_index"] == repeat_index
        ]
        baseline = next(run for run in pair if run["mode"] == MODE_BASELINE)
        selected = next(run for run in pair if run["mode"] == MODE_SELECTED)
        comparison = compare_pair(baseline, selected)
        comparisons.append(comparison)
    return comparisons


def compare_pair(baseline: dict[str, Any], selected: dict[str, Any]) -> dict[str, Any]:
    base = {
        "task_label": baseline["task_label"],
        "family": baseline["family"],
        "repeat_index": baseline["repeat_index"],
        "selection_source": selected.get("selection_source", SELECTION_SOURCE_FIXTURE),
        "router_used": bool(selected.get("router_used")),
        "router_provider": selected.get("router_provider"),
        "router_status": selected.get("router_status"),
        "router_reason": selected.get("router_reason"),
        "router_error_type": selected.get("router_error_type"),
        "router_confidence": selected.get("router_confidence"),
        "router_selection_usable": selected.get("router_selection_usable", True),
        "router_selected_block_ids": selected.get("router_selected_block_ids", []),
        "router_latency_ms": selected.get("router_latency_ms"),
        "router_estimated_selected_input_tokens": selected.get(
            "router_estimated_selected_input_tokens"
        ),
        "router_estimated_token_reduction_pct": selected.get(
            "router_estimated_token_reduction_pct"
        ),
        "comparison_valid": True,
        "comparison_invalid_reason": None,
    }
    if (
        baseline.get("execution_status", "completed") != "completed"
        or selected.get("execution_status", "completed") != "completed"
        or baseline.get("input_tokens") is None
        or selected.get("input_tokens") is None
    ):
        return {
            **base,
            "comparison_valid": False,
            "comparison_invalid_reason": selected.get("skip_reason")
            or "selected_execution_not_completed",
            "baseline_input_tokens": baseline.get("input_tokens"),
            "baseline_output_tokens": baseline.get("output_tokens"),
            "baseline_total_tokens": baseline.get("total_tokens"),
            "selected_input_tokens": selected.get("input_tokens"),
            "selected_output_tokens": selected.get("output_tokens"),
            "selected_total_tokens": selected.get("total_tokens"),
            "input_delta": None,
            "output_delta": None,
            "total_delta": None,
            "output_ratio": None,
            "input_reduction_percent": None,
            "total_reduction_percent": None,
            "output_tokens_reduced": False,
            "output_tokens_increased": False,
            "output_unchanged_or_near_equal": False,
            "output_expansion_offsets_input_reduction": False,
            "total_tokens_reduced": False,
            "baseline_success": baseline.get("success", False),
            "selected_success": False,
            "quality_pass": False,
            "selected_quality_pass": False,
            "baseline_quality_pass": baseline.get("success", False),
            "baseline_compactness_score": baseline.get("compactness_score"),
            "selected_compactness_score": None,
        }
    input_delta = selected["input_tokens"] - baseline["input_tokens"]
    output_delta = selected["output_tokens"] - baseline["output_tokens"]
    total_delta = selected["total_tokens"] - baseline["total_tokens"]
    near_equal = output_unchanged_or_near_equal(
        baseline["output_tokens"], selected["output_tokens"]
    )
    return {
        **base,
        "baseline_input_tokens": baseline["input_tokens"],
        "baseline_output_tokens": baseline["output_tokens"],
        "baseline_total_tokens": baseline["total_tokens"],
        "selected_input_tokens": selected["input_tokens"],
        "selected_output_tokens": selected["output_tokens"],
        "selected_total_tokens": selected["total_tokens"],
        "input_delta": input_delta,
        "output_delta": output_delta,
        "total_delta": total_delta,
        "output_ratio": safe_ratio(selected["output_tokens"], baseline["output_tokens"]),
        "input_reduction_percent": percent_reduction(
            baseline["input_tokens"], selected["input_tokens"]
        ),
        "total_reduction_percent": percent_reduction(
            baseline["total_tokens"], selected["total_tokens"]
        ),
        "output_tokens_reduced": output_delta < 0 and not near_equal,
        "output_tokens_increased": output_delta > 0 and not near_equal,
        "output_unchanged_or_near_equal": near_equal,
        "output_expansion_offsets_input_reduction": input_delta < 0 and output_delta > 0,
        "total_tokens_reduced": total_delta < 0,
        "baseline_success": baseline["success"],
        "selected_success": selected["success"],
        "quality_pass": baseline["success"] and selected["success"],
        "selected_quality_pass": selected["success"],
        "baseline_quality_pass": baseline["success"],
        "baseline_compactness_score": baseline["compactness_score"],
        "selected_compactness_score": selected["compactness_score"],
    }


def output_unchanged_or_near_equal(baseline_output: int, selected_output: int) -> bool:
    delta = abs(selected_output - baseline_output)
    return delta <= max(3, baseline_output * 0.05)


def safe_ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def summarize(
    comparisons: list[dict[str, Any]], *, notes: list[str]
) -> dict[str, Any]:
    return {
        "notes": notes,
        "overall": summarize_comparisons(comparisons),
        "by_family": {
            family: summarize_comparisons(
                [comparison for comparison in comparisons if comparison["family"] == family]
            )
            for family in sorted({comparison["family"] for comparison in comparisons})
        },
    }


def summarize_comparisons(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [comparison for comparison in comparisons if comparison.get("comparison_valid", True)]
    return {
        "comparison_count": len(comparisons),
        "valid_comparison_count": len(valid),
        "invalid_comparison_count": len(comparisons) - len(valid),
        "average_baseline_input_tokens": average_value(valid, "baseline_input_tokens"),
        "average_selected_input_tokens": average_value(valid, "selected_input_tokens"),
        "average_baseline_output_tokens": average_value(valid, "baseline_output_tokens"),
        "average_selected_output_tokens": average_value(valid, "selected_output_tokens"),
        "average_baseline_total_tokens": average_value(valid, "baseline_total_tokens"),
        "average_selected_total_tokens": average_value(valid, "selected_total_tokens"),
        "average_output_delta": average_value(valid, "output_delta"),
        "average_output_ratio": average_present(comparison.get("output_ratio") for comparison in valid),
        "average_total_delta": average_value(valid, "total_delta"),
        "average_input_reduction_percent": average_present(
            comparison.get("input_reduction_percent") for comparison in valid
        ),
        "average_total_reduction_percent": average_present(
            comparison.get("total_reduction_percent") for comparison in valid
        ),
        "output_tokens_reduced_count": count_true(valid, "output_tokens_reduced"),
        "output_tokens_increased_count": count_true(valid, "output_tokens_increased"),
        "output_unchanged_or_near_equal_count": count_true(
            valid, "output_unchanged_or_near_equal"
        ),
        "output_expansion_offsets_input_reduction_count": count_true(
            valid, "output_expansion_offsets_input_reduction"
        ),
        "total_tokens_reduced_count": count_true(valid, "total_tokens_reduced"),
        "quality_pass_count": count_true(valid, "quality_pass"),
        "selected_quality_pass_count": count_true(valid, "selected_quality_pass"),
        "baseline_quality_pass_count": count_true(valid, "baseline_quality_pass"),
        "quality_pass_rate": (
            count_true(valid, "quality_pass") / len(valid)
            if valid else 0.0
        ),
        "selected_quality_pass_rate": (
            count_true(valid, "selected_quality_pass") / len(valid)
            if valid else 0.0
        ),
        "baseline_quality_pass_rate": (
            count_true(valid, "baseline_quality_pass") / len(valid)
            if valid else 0.0
        ),
        "router_selection_usable_count": count_true(comparisons, "router_selection_usable"),
    }


def average_value(rows: list[dict[str, Any]], key: str) -> float:
    values = [row[key] for row in rows if row.get(key) is not None]
    return average(values) if values else 0.0


def average_present(values: Any) -> float | None:
    present = [float(value) for value in values if value is not None]
    return average(present) if present else None


def count_true(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def task_to_dict(task: OutputVariationTask) -> dict[str, Any]:
    data = asdict(task)
    data.pop("dry_run_outputs", None)
    return data


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Output Variation Benchmark",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Executor: `{report['metadata']['executor']}`",
        f"Dry run fixture outputs: `{report['metadata']['dry_run_fixture_outputs']}`",
        f"Selection source: `{report['metadata']['selection_source']}`",
        f"Selection strategy: `{report['metadata']['selection_strategy']}`",
        f"Router used: `{report['metadata']['router_used']}`",
        "",
    ]
    if report["metadata"].get("router_selection_note"):
        lines.extend(["## Router Selection Note", "", report["metadata"]["router_selection_note"], ""])
    if report["metadata"].get("dry_run_note"):
        lines.extend(["## Dry-Run Note", "", report["metadata"]["dry_run_note"], ""])

    lines.extend(
        [
            "## Summary By Task Family",
            "",
            "| Family | Base in | Selected in | Base out | Selected out | Out delta | Out ratio | Total delta | Input reduction | Total reduction | Quality base/selected | Output flag |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for family, summary in report["summary"]["by_family"].items():
        lines.append(
            f"| `{family}` | "
            f"{summary['average_baseline_input_tokens']:.2f} | "
            f"{summary['average_selected_input_tokens']:.2f} | "
            f"{summary['average_baseline_output_tokens']:.2f} | "
            f"{summary['average_selected_output_tokens']:.2f} | "
            f"{summary['average_output_delta']:.2f} | "
            f"{format_optional_float(summary['average_output_ratio'])} | "
            f"{summary['average_total_delta']:.2f} | "
            f"{format_optional_percent(summary['average_input_reduction_percent'])} | "
            f"{format_optional_percent(summary['average_total_reduction_percent'])} | "
            f"{summary['baseline_quality_pass_rate']:.2%}/"
            f"{summary['selected_quality_pass_rate']:.2%} | "
            f"{family_output_flag(summary)} |"
        )

    lines.extend(
        [
            "",
            "## Per-Task Comparisons",
            "",
            "| Task | Family | Base in/out/total | Selected in/out/total | Output delta | Output ratio | Total delta | Quality base/selected | Router | Flags |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for comparison in report["comparisons"]:
        lines.append(
            f"| `{comparison['task_label']}` | `{comparison['family']}` | "
            f"{format_optional_int(comparison['baseline_input_tokens'])}/"
            f"{format_optional_int(comparison['baseline_output_tokens'])}/"
            f"{format_optional_int(comparison['baseline_total_tokens'])} | "
            f"{format_optional_int(comparison['selected_input_tokens'])}/"
            f"{format_optional_int(comparison['selected_output_tokens'])}/"
            f"{format_optional_int(comparison['selected_total_tokens'])} | "
            f"{format_optional_int(comparison['output_delta'])} | "
            f"{format_optional_float(comparison['output_ratio'])} | "
            f"{format_optional_int(comparison['total_delta'])} | "
            f"{bool(comparison['baseline_quality_pass'])}/"
            f"{bool(comparison['selected_quality_pass'])} | "
            f"{router_comparison_summary(comparison)} | "
            f"{comparison_flags(comparison)} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            (
                "This benchmark observes output-token variation under controlled task "
                "families. Output reduction is conditional: selected context can reduce, "
                "increase, or leave output length stable depending on ambiguity, distractors, "
                "and the output contract."
            ),
            (
                "When selection source is router, selected context comes from the proxy "
                "shadow-router selection path. Router overhead is reported as selection "
                "metadata when available and is not included in baseline or selected "
                "executor token totals."
            ),
            (
                "The bounded output control family is expected to show small differences "
                "because a strict schema constrains output length."
            ),
            (
                "Dry-run fixture outputs are deterministic synthetic outputs used to validate "
                "the benchmark pipeline and accounting logic. They are not evidence that SFE "
                "reduces or increases output tokens in real LLM behavior."
            ),
            "",
        ]
    )
    write_text_report(path, "\n".join(lines))


def family_output_flag(summary: dict[str, Any]) -> str:
    if summary["output_tokens_reduced_count"]:
        return "reduced"
    if summary["output_tokens_increased_count"]:
        return "increased"
    if summary["output_unchanged_or_near_equal_count"]:
        return "near_equal"
    return "mixed"


def comparison_flags(comparison: dict[str, Any]) -> str:
    if not comparison.get("comparison_valid", True):
        return "invalid_comparison"
    flags = []
    if comparison["output_tokens_reduced"]:
        flags.append("output_reduced")
    if comparison["output_tokens_increased"]:
        flags.append("output_increased")
    if comparison["output_unchanged_or_near_equal"]:
        flags.append("output_near_equal")
    if comparison["total_tokens_reduced"]:
        flags.append("total_reduced")
    if comparison["output_expansion_offsets_input_reduction"]:
        flags.append("output_offsets_input")
    return ", ".join(flags) or "none"


def format_optional_float(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def format_optional_int(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def format_optional_percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}%"


def router_comparison_summary(comparison: dict[str, Any]) -> str:
    if not comparison.get("router_used"):
        return "n/a"
    status = comparison.get("router_status") or "unknown"
    selected = comparison.get("router_selected_block_ids") or []
    selected_text = ",".join(str(item) for item in selected) or "none"
    usable = bool(comparison.get("router_selection_usable"))
    return f"{status}; usable={usable}; selected={selected_text}"


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    overall = report["summary"]["overall"]
    print("Output variation benchmark")
    print(f"tasks: {report['metadata']['task_count']}")
    print(f"comparisons: {report['metadata']['comparison_count']}")
    print(f"dry_run_fixture_outputs: {report['metadata']['dry_run_fixture_outputs']}")
    print(f"selection_source: {report['metadata']['selection_source']}")
    print(f"router_used: {report['metadata']['router_used']}")
    print(f"quality pass rate: {overall['quality_pass_rate']:.2%}")
    print(f"average output delta: {overall['average_output_delta']:.2f}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


if __name__ == "__main__":
    main()
