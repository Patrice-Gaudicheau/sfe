"""Run the large/contextual benchmark.

This benchmark isolates the case where SFE can pay for routing by reducing a
large, noisy executor context. Baseline execution receives every context block.
Spatial execution receives only the deterministically selected relevant block.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.lemonade import (
    DEFAULT_BASE_URL as LEMONADE_DEFAULT_BASE_URL,
    DEFAULT_TIMEOUT,
    LemonadeProvider,
)
from providers.alibaba import (
    DEFAULT_BASE_URL as ALIBABA_API_DEFAULT_BASE_URL,
    DEFAULT_EXECUTOR_MODEL as ALIBABA_API_DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as ALIBABA_API_DEFAULT_ROUTER_MODEL,
    AlibabaAPIProvider,
)
from providers.google import (
    API_STYLE as GOOGLE_API_STYLE,
    DEFAULT_BASE_URL as GOOGLE_API_DEFAULT_BASE_URL,
    DEFAULT_MODEL as GOOGLE_API_DEFAULT_MODEL,
    GoogleAPIProvider,
)
from providers.anthropic import (
    API_STYLE as ANTHROPIC_API_STYLE,
    DEFAULT_BASE_URL as ANTHROPIC_DEFAULT_BASE_URL,
    DEFAULT_EXECUTOR_MODEL as ANTHROPIC_DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as ANTHROPIC_DEFAULT_ROUTER_MODEL,
    AnthropicProvider,
)
from providers.openai_api import (
    DEFAULT_BASE_URL as OPENAI_API_DEFAULT_BASE_URL,
    DEFAULT_EXECUTOR_MODEL as OPENAI_API_DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as OPENAI_API_DEFAULT_ROUTER_MODEL,
    OpenAIAPIProvider,
)
from providers.codexcli import (
    DEFAULT_EXECUTOR_MODEL as CODEXCLI_DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as CODEXCLI_DEFAULT_ROUTER_MODEL,
    PROVIDER_NAME as OPENAI_CODEXCLI_EXECUTOR,
    CodexCLIProvider,
)
from router.llm_router import DEFAULT_ROUTER_MODEL
from runtime.run_experiment import (
    DEFAULT_EXECUTION_MODEL,
    _extract_response_text,
    _extract_token_usage,
)
from runtime.metrics import (
    average,
    estimate_text_tokens,
    percent_reduction,
    success_rate,
    write_json_report,
    write_text_report,
)
from runtime.output_repair import (
    OUTPUT_REPAIR_STATUS_ATTEMPTED_COMPLETE,
    OUTPUT_REPAIR_STATUS_ATTEMPTED_INCOMPLETE,
    OUTPUT_REPAIR_STATUS_DISABLED,
    OUTPUT_REPAIR_STATUS_NOT_REQUIRED,
    OUTPUT_REPAIR_STATUS_SKIPPED_SELECTION_INCOMPLETE,
    OutputRepairer,
    OutputRepairResult,
    output_repair_not_attempted,
)
from runtime.output_validation import OutputValidator
from runtime.selection_verification import SelectionVerifier
from sfe.env import load_repo_env


BENCHMARK_TYPE = "large/contextual"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark.md"
OPENAI_API_JSON_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_openai_api.json"
OPENAI_API_MD_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_openai_api.md"
ANTHROPIC_JSON_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_anthropic.json"
ANTHROPIC_MD_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_anthropic.md"
ALIBABA_API_JSON_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_alibaba_api.json"
ALIBABA_API_MD_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_alibaba_api.md"
GOOGLE_API_JSON_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_google.json"
GOOGLE_API_MD_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_google.md"
CODEXCLI_JSON_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_codexcli.json"
CODEXCLI_MD_PATH = PROJECT_ROOT / "logs" / "large_contextual_benchmark_codexcli.md"
CODEXCLI_PROCESS_BASE_URL = "process:codex-cli"
FIXTURE_ROUTER_NAME = "fixture_relevance_router"
LEMONADE_EXECUTOR = "lemonade"
OPENAI_API_EXECUTOR = "openai-api"
ANTHROPIC_EXECUTOR = "anthropic"
ALIBABA_API_EXECUTOR = "alibaba-api"
GOOGLE_API_EXECUTOR = "google"
EXECUTORS = (
    LEMONADE_EXECUTOR,
    OPENAI_CODEXCLI_EXECUTOR,
    OPENAI_API_EXECUTOR,
    ANTHROPIC_EXECUTOR,
    ALIBABA_API_EXECUTOR,
    GOOGLE_API_EXECUTOR,
)
LEMONADE_BLOCK_SELECTOR_NAME = "lemonade_block_selector"
OPENAI_API_BLOCK_SELECTOR_NAME = "openai_api_block_selector"
ANTHROPIC_BLOCK_SELECTOR_NAME = "anthropic_messages_block_selector"
ALIBABA_API_BLOCK_SELECTOR_NAME = "alibaba_api_block_selector"
GOOGLE_API_BLOCK_SELECTOR_NAME = "google_api_block_selector"
CODEXCLI_BLOCK_SELECTOR_NAME = "codexcli_block_selector"
REAL_ROUTER_NAME = LEMONADE_BLOCK_SELECTOR_NAME
DRY_RUN_ROUTER_NAME = "dry_run_fixture_block_selector"
SELECTION_MODES = ("fixture", "router", "both")
TASK_TIER_STANDARD = "standard"
TASK_TIER_PRACTICAL = "practical"
TASK_TIER_HIGH_CONTEXT = "high_context"
TASK_TIER_STRUCTURAL = "structural"
TASK_TIER_LONG = "long"
TASK_TIERS = (
    TASK_TIER_STANDARD,
    TASK_TIER_PRACTICAL,
    TASK_TIER_HIGH_CONTEXT,
    TASK_TIER_STRUCTURAL,
    TASK_TIER_LONG,
)
TASK_TIER_DESCRIPTIONS = {
    TASK_TIER_STANDARD: "standard 2k-5k mechanism validation tier",
    TASK_TIER_PRACTICAL: "practical 10k-20k realistic amortization tier",
    TASK_TIER_HIGH_CONTEXT: "high_context 20k-50k strong SFE relevance zone",
    TASK_TIER_STRUCTURAL: "structural 50k+ structural necessity zone",
}
TASK_TIER_ALIASES = {TASK_TIER_LONG: TASK_TIER_PRACTICAL}
FINAL_PHASE_CONCLUSION = (
    "Routing is reliable, but routing has a fixed cost. SFE must be activated "
    "selectively on tasks where context reduction or cognitive separation can "
    "amortize that cost."
)
SELECTION_VERIFICATION_TRIGGER_STRUCTURAL_TIER = "structural_tier"
OUTPUT_VALIDATION_TRIGGER_STRUCTURAL_TIER = "structural_tier"
OUTPUT_REPAIR_TRIGGER_STRUCTURAL_TIER = "structural_tier"
CODEXCLI_REASONING_EFFORTS = ("low", "medium", "high")


class ChatProvider(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
        chat_template_kwargs: dict | None = None,
    ) -> dict[str, Any]:
        ...


class BlockSelector(Protocol):
    def select(
        self,
        task: "LargeContextualTask",
        fixture_route: dict[str, Any],
    ) -> dict[str, Any]:
        ...


class ProviderCallPacer:
    """Optional delay between live provider calls."""

    def __init__(self, delay_seconds: float = 0.0, sleep_func=time.sleep) -> None:
        if delay_seconds < 0:
            raise ValueError("--provider-call-delay-seconds must be at least 0.")
        self.delay_seconds = delay_seconds
        self.sleep_func = sleep_func
        self.call_count = 0

    def wait_before_call(self) -> None:
        if self.delay_seconds > 0 and self.call_count > 0:
            self.sleep_func(self.delay_seconds)
        self.call_count += 1


@dataclass(frozen=True)
class ContextBlock:
    block_id: str
    title: str
    text: str
    relevant: bool = False


@dataclass(frozen=True)
class LargeContextualTask:
    task_label: str
    question: str
    blocks: tuple[ContextBlock, ...]
    expected_answer_hints: tuple[str, ...]
    validation_targets: tuple[str, ...]
    difficulty_patterns: tuple[str, ...] = ()


def main() -> None:
    load_repo_env()
    args = _parse_args()
    tasks = get_large_contextual_tasks(args.task_tier)
    tasks = filter_tasks_by_label(tasks, args.task_label, args.task_tier)
    if args.limit is not None:
        if args.limit < 1:
            raise ValueError("--limit must be at least 1 when provided.")
        tasks = tasks[: args.limit]

    report = run_benchmark(
        tasks=tasks,
        repeat=args.repeat,
        model=args.model,
        base_url=args.base_url,
        timeout_seconds=args.timeout_seconds,
        codexcli_idle_timeout_seconds=args.codexcli_idle_timeout_seconds,
        codexcli_router_reasoning_effort=args.codexcli_router_reasoning_effort,
        max_tokens=args.max_tokens,
        dry_run=args.dry_run,
        selection_mode=args.selection_mode,
        router_model=args.router_model,
        task_tier=args.task_tier,
        executor=args.executor,
        max_output_repairs=args.max_output_repairs,
        provider_call_delay_seconds=args.provider_call_delay_seconds,
    )

    write_json(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare full-context baseline against reduced-context SFE execution."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--task-label",
        help="Exact task label to run after task-tier selection and before --limit.",
    )
    parser.add_argument(
        "--executor",
        choices=EXECUTORS,
        default=LEMONADE_EXECUTOR,
        help="Provider used for executor and real-router calls.",
    )
    parser.add_argument(
        "--model",
        help=(
            "Executor model id. Defaults to SFE_EXECUTOR_MODEL for Lemonade or "
            "SFE_OPENAI_EXECUTOR_MODEL for OpenAI API/CodexCLI or "
            "SFE_ANTHROPIC_EXECUTOR_MODEL for Anthropic or "
            "SFE_ALIBABA_EXECUTOR_MODEL for Alibaba/Qwen or SFE_GOOGLE_MODEL "
            "for Google/Gemini."
        ),
    )
    parser.add_argument(
        "--base-url",
        help=(
            "Provider base URL. Defaults to SFE_LEMONADE_BASE_URL for Lemonade "
            "or OPENAI_BASE_URL for OpenAI API or ANTHROPIC_BASE_URL for Anthropic "
            "or ALIBABA_BASE_URL for Alibaba/Qwen or SFE_GOOGLE_BASE_URL for "
            "Google/Gemini."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="Lemonade request timeout.",
    )
    parser.add_argument(
        "--codexcli-idle-timeout-seconds",
        type=float,
        help=(
            "Idle supervision window for --executor openai-codexcli. Defaults "
            "to the shared SFE provider idle timeout instead of --timeout-seconds."
        ),
    )
    parser.add_argument(
        "--codexcli-router-reasoning-effort",
        choices=CODEXCLI_REASONING_EFFORTS,
        help=(
            "CodexCLI model_reasoning_effort override for router calls only. "
            "Executor calls are unchanged."
        ),
    )
    parser.add_argument("--max-tokens", type=int, default=160)
    parser.add_argument(
        "--max-output-repairs",
        type=int,
        default=0,
        help=(
            "Maximum structural output repair attempts per eligible spatial_router run. "
            "Defaults to 0; repair is disabled unless explicitly enabled."
        ),
    )
    parser.add_argument(
        "--provider-call-delay-seconds",
        type=float,
        default=0.0,
        help=(
            "Optional delay inserted between live provider calls within a benchmark "
            "run. Defaults to 0 and does not affect dry-run execution."
        ),
    )
    parser.add_argument(
        "--selection-mode",
        choices=SELECTION_MODES,
        default="fixture",
        help=(
            "Block selection mode. fixture preserves the existing oracle behavior; "
            "router uses the configured provider block selector; both runs baseline, "
            "oracle, and router modes."
        ),
    )
    parser.add_argument(
        "--task-tier",
        choices=TASK_TIERS,
        default=TASK_TIER_STANDARD,
        help=(
            "Task tier. standard is the existing 7-task 2k-5k reference benchmark; "
            "practical is the 10k-20k realistic amortization tier; high_context "
            "is the 20k-50k strong SFE relevance tier; structural is the 50k+ "
            "structural necessity tier. long is a backward-compatible alias for practical."
        ),
    )
    parser.add_argument(
        "--router-model",
        help=(
            "Router model id for --selection-mode router or both. Defaults to "
            "SFE_ROUTER_MODEL for Lemonade or SFE_OPENAI_ROUTER_MODEL for OpenAI "
            "API/CodexCLI or SFE_ANTHROPIC_ROUTER_MODEL for Anthropic or "
            "SFE_ALIBABA_ROUTER_MODEL for Alibaba/Qwen or SFE_GOOGLE_MODEL for "
            "Google/Gemini."
        ),
    )
    parser.add_argument("--json", type=Path)
    parser.add_argument("--md", type=Path)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompts and deterministic metrics without calling a provider.",
    )
    args = parser.parse_args()
    if (
        args.codexcli_idle_timeout_seconds is not None
        and args.codexcli_idle_timeout_seconds <= 0
    ):
        parser.error("--codexcli-idle-timeout-seconds must be greater than 0.")
    return _resolve_provider_defaults(args)


def _resolve_provider_defaults(args: argparse.Namespace) -> argparse.Namespace:
    if args.model is None:
        args.model = _default_executor_model(args.executor)
    if args.base_url is None:
        args.base_url = _default_base_url(args.executor)
    if args.router_model is None:
        args.router_model = _default_router_model(args.executor)
    if args.json is None:
        args.json = _default_json_path(args.executor)
    if args.md is None:
        args.md = _default_md_path(args.executor)
    return args


def _default_executor_model(executor: str) -> str:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or CODEXCLI_DEFAULT_EXECUTOR_MODEL
    if executor == OPENAI_API_EXECUTOR:
        return os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or OPENAI_API_DEFAULT_EXECUTOR_MODEL
    if executor == ANTHROPIC_EXECUTOR:
        return os.getenv("SFE_ANTHROPIC_EXECUTOR_MODEL") or ANTHROPIC_DEFAULT_EXECUTOR_MODEL
    if executor == ALIBABA_API_EXECUTOR:
        return os.getenv("SFE_ALIBABA_EXECUTOR_MODEL") or ALIBABA_API_DEFAULT_EXECUTOR_MODEL
    if executor == GOOGLE_API_EXECUTOR:
        return os.getenv("SFE_GOOGLE_MODEL") or GOOGLE_API_DEFAULT_MODEL
    return os.getenv("SFE_EXECUTOR_MODEL") or DEFAULT_EXECUTION_MODEL


def _default_router_model(executor: str) -> str | None:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return os.getenv("SFE_OPENAI_ROUTER_MODEL") or CODEXCLI_DEFAULT_ROUTER_MODEL
    if executor == OPENAI_API_EXECUTOR:
        return os.getenv("SFE_OPENAI_ROUTER_MODEL") or OPENAI_API_DEFAULT_ROUTER_MODEL
    if executor == ANTHROPIC_EXECUTOR:
        return os.getenv("SFE_ANTHROPIC_ROUTER_MODEL") or ANTHROPIC_DEFAULT_ROUTER_MODEL
    if executor == ALIBABA_API_EXECUTOR:
        return os.getenv("SFE_ALIBABA_ROUTER_MODEL") or ALIBABA_API_DEFAULT_ROUTER_MODEL
    if executor == GOOGLE_API_EXECUTOR:
        return os.getenv("SFE_GOOGLE_MODEL") or GOOGLE_API_DEFAULT_MODEL
    return os.getenv("SFE_ROUTER_MODEL") or DEFAULT_ROUTER_MODEL


def _default_base_url(executor: str) -> str:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return CODEXCLI_PROCESS_BASE_URL
    if executor == OPENAI_API_EXECUTOR:
        return os.getenv("OPENAI_BASE_URL") or OPENAI_API_DEFAULT_BASE_URL
    if executor == ANTHROPIC_EXECUTOR:
        return os.getenv("ANTHROPIC_BASE_URL") or ANTHROPIC_DEFAULT_BASE_URL
    if executor == ALIBABA_API_EXECUTOR:
        return os.getenv("ALIBABA_BASE_URL") or ALIBABA_API_DEFAULT_BASE_URL
    if executor == GOOGLE_API_EXECUTOR:
        return os.getenv("SFE_GOOGLE_BASE_URL") or GOOGLE_API_DEFAULT_BASE_URL
    return os.getenv("SFE_LEMONADE_BASE_URL") or LEMONADE_DEFAULT_BASE_URL


def _default_json_path(executor: str) -> Path:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return CODEXCLI_JSON_PATH
    if executor == OPENAI_API_EXECUTOR:
        return OPENAI_API_JSON_PATH
    if executor == ANTHROPIC_EXECUTOR:
        return ANTHROPIC_JSON_PATH
    if executor == ALIBABA_API_EXECUTOR:
        return ALIBABA_API_JSON_PATH
    if executor == GOOGLE_API_EXECUTOR:
        return GOOGLE_API_JSON_PATH
    return DEFAULT_JSON_PATH


def _default_md_path(executor: str) -> Path:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return CODEXCLI_MD_PATH
    if executor == OPENAI_API_EXECUTOR:
        return OPENAI_API_MD_PATH
    if executor == ANTHROPIC_EXECUTOR:
        return ANTHROPIC_MD_PATH
    if executor == ALIBABA_API_EXECUTOR:
        return ALIBABA_API_MD_PATH
    if executor == GOOGLE_API_EXECUTOR:
        return GOOGLE_API_MD_PATH
    return DEFAULT_MD_PATH


def get_large_contextual_tasks(
    task_tier: str = TASK_TIER_STANDARD,
) -> list[LargeContextualTask]:
    """Return deterministic large/contextual fixtures for a task tier."""

    task_tier = normalize_task_tier(task_tier)
    if task_tier == TASK_TIER_STANDARD:
        return _standard_large_contextual_tasks()
    if task_tier == TASK_TIER_PRACTICAL:
        return _practical_large_contextual_tasks()
    if task_tier == TASK_TIER_HIGH_CONTEXT:
        return _high_context_large_contextual_tasks()
    if task_tier == TASK_TIER_STRUCTURAL:
        return _structural_large_contextual_tasks()
    raise ValueError(f"Unknown task tier: {task_tier}")


def filter_tasks_by_label(
    tasks: list[LargeContextualTask],
    task_label: str | None,
    task_tier: str,
) -> list[LargeContextualTask]:
    """Filter an existing tier task list by exact label without changing fixtures."""
    if not task_label:
        return tasks
    matches = [task for task in tasks if task.task_label == task_label]
    if matches:
        return matches
    available = ", ".join(task.task_label for task in tasks)
    normalized_tier = normalize_task_tier(task_tier)
    raise ValueError(
        f"Task label {task_label!r} was not found in task tier {normalized_tier!r}. "
        f"Available task labels: {available}"
    )


def normalize_task_tier(task_tier: str) -> str:
    if task_tier not in TASK_TIERS:
        raise ValueError(f"Unknown task tier: {task_tier}")
    return TASK_TIER_ALIASES.get(task_tier, task_tier)


def _standard_large_contextual_tasks() -> list[LargeContextualTask]:
    """Return the existing standard 7-task large/contextual fixture set."""

    return [
        LargeContextualTask(
            task_label="large_contextual_payments_failover",
            question=(
                "For the Vertex North payments pilot, what was the root cause of "
                "duplicate settlement notices, and who owns the first mitigation?"
            ),
            blocks=(
                _block(
                    "pay-ops",
                    "Payments Operations Summary",
                    (
                        "The Vertex North payments pilot saw duplicate settlement notices after the "
                        "Tuesday failover. The root cause was a cache key salted with the region code "
                        "after failover, so retries in eu-west and eu-central no longer deduplicated "
                        "the same settlement event. The first mitigation owner is Priya Nair, who must "
                        "ship the neutral cache-key patch before the next settlement window."
                    ),
                    True,
                ),
                _block(
                    "pay-risk",
                    "Payments Risk Register",
                    (
                        "The risk register for payment launches tracks fraud rules, manual review "
                        "thresholds, and customer notification copy. It discusses chargeback spikes, "
                        "issuer response drift, and batch reconciliation delays, but it does not assign "
                        "ownership for the Vertex North duplicate-notice incident."
                    ),
                ),
                _block(
                    "support",
                    "Support Queue Notes",
                    (
                        "Support agents reported confusing ticket tags during the pilot. Several "
                        "customers asked about invoice names, payment descriptors, and notification "
                        "language. The notes are operationally plausible but describe triage behavior "
                        "rather than the settlement deduplication defect."
                    ),
                ),
                _block(
                    "infra",
                    "Infrastructure Capacity Memo",
                    (
                        "The infrastructure memo covers autoscaling headroom, queue depth alerts, and "
                        "database maintenance windows for the same launch week. It mentions failover "
                        "drills and regional capacity, but not duplicate settlement notices or patch "
                        "ownership."
                    ),
                ),
                _block(
                    "billing",
                    "Billing Copy Review",
                    (
                        "The billing review compares customer-facing wording for receipts, invoices, "
                        "refund explanations, and subscription renewal notices. It is thematically close "
                        "to payments, yet it only concerns copy quality and legal approval."
                    ),
                ),
                _block(
                    "analytics",
                    "Analytics Instrumentation Plan",
                    (
                        "The analytics plan defines event names, dashboard slices, and retention rules "
                        "for the pilot. It includes settlement funnel metrics and duplicate-event charts, "
                        "but it treats those charts as observability artifacts rather than root-cause data."
                    ),
                ),
            ),
            expected_answer_hints=("cache key salted with the region code", "Priya Nair"),
            validation_targets=("cache", "region", "Priya Nair"),
        ),
        LargeContextualTask(
            task_label="large_contextual_inventory_allocation",
            question=(
                "For Indigo Shelf priority bins, which allocation rule applies, "
                "and what exception must be kept?"
            ),
            blocks=(
                _block(
                    "warehouse",
                    "Warehouse Staffing Memo",
                    (
                        "The warehouse memo discusses picker schedules, overtime caps, training "
                        "rotations, and aisle coverage for the seasonal reset. It repeatedly references "
                        "priority bins and Indigo Shelf labels, but only as staffing pressure points."
                    ),
                ),
                _block(
                    "forecast",
                    "Demand Forecast Appendix",
                    (
                        "The forecast appendix reviews category velocity, supplier confidence, and "
                        "expected stockout windows. Indigo Shelf products appear in the same tables as "
                        "standard replenishment items, but no allocation rule is specified here."
                    ),
                ),
                _block(
                    "allocation",
                    "Priority Allocation Decision",
                    (
                        "For Indigo Shelf priority bins, allocate scarce units by earliest confirmed "
                        "delivery appointment, not by account tier or forecast volume. Keep the exception "
                        "for hospital-grade replacement kits: those kits remain first-reserved when a "
                        "service ticket is marked critical."
                    ),
                    True,
                ),
                _block(
                    "supplier",
                    "Supplier Escalation Log",
                    (
                        "The supplier log lists late trailers, partial pallets, substitute cartons, and "
                        "label mismatches. It sounds relevant because it names Indigo Shelf vendors, but "
                        "it only records inbound problems and escalation owners."
                    ),
                ),
                _block(
                    "finance",
                    "Finance Margin Review",
                    (
                        "The finance review recommends margin bands and rebate handling for priority "
                        "inventory. It discourages allocation by account tier in one scenario, but that "
                        "statement is a pricing note rather than the operating rule for bins."
                    ),
                ),
                _block(
                    "comms",
                    "Customer Communications Draft",
                    (
                        "The communications draft prepares language for delayed Indigo Shelf shipments. "
                        "It covers expectation setting, partial shipment wording, and escalation paths, "
                        "but it intentionally avoids internal allocation logic."
                    ),
                ),
            ),
            expected_answer_hints=(
                "earliest confirmed delivery appointment",
                "hospital-grade replacement kits",
            ),
            validation_targets=("earliest", "appointment", "hospital"),
        ),
        LargeContextualTask(
            task_label="large_contextual_eval_rollback",
            question=(
                "In the Atlas evaluator launch notes, what rollback threshold was "
                "approved, and which dataset must be excluded from the launch gate?"
            ),
            blocks=(
                _block(
                    "eval-plan",
                    "Evaluator Launch Gate",
                    (
                        "The Atlas evaluator launch gate approved rollback when the calibrated helpfulness "
                        "score falls below 0.72 for two consecutive nightly runs. The launch gate must "
                        "exclude the Larch-17 synthetic dataset because its prompts overlap with tuning "
                        "data and inflate the helpfulness estimate."
                    ),
                    True,
                ),
                _block(
                    "red-team",
                    "Red-Team Findings",
                    (
                        "The red-team findings describe jailbreak categories, refusal misses, and "
                        "annotation disagreements. They include several Atlas evaluator examples, but "
                        "the document is about qualitative risk themes rather than the numerical launch "
                        "rollback threshold."
                    ),
                ),
                _block(
                    "latency",
                    "Latency Regression Report",
                    (
                        "The latency report compares nightly inference duration, queue wait time, cache "
                        "reuse, and tokenizer overhead. It recommends a rollout pause for slow paths, "
                        "but it does not define the evaluator helpfulness threshold."
                    ),
                ),
                _block(
                    "dataset",
                    "Dataset Catalog",
                    (
                        "The dataset catalog lists public, synthetic, adversarial, and internal evaluation "
                        "sets used by the Atlas team. It names Larch-17, Maple-08, and Cedar-Holdout, but "
                        "it does not say which one is excluded from the launch gate."
                    ),
                ),
                _block(
                    "annotation",
                    "Annotation Quality Notes",
                    (
                        "The annotation notes track reviewer calibration, rubric ambiguity, and rejected "
                        "labels. They discuss helpfulness scoring and examples that resemble the launch "
                        "gate, yet the document only governs labeling process."
                    ),
                ),
                _block(
                    "release",
                    "Release Manager Checklist",
                    (
                        "The release checklist covers dashboard ownership, sign-off order, incident "
                        "contacts, and rollback rehearsal timing. It references the Atlas launch gate "
                        "as an input, but it deliberately avoids restating score criteria."
                    ),
                ),
            ),
            expected_answer_hints=("below 0.72", "Larch-17 synthetic dataset"),
            validation_targets=("0.72", "Larch-17", "synthetic"),
        ),
        LargeContextualTask(
            task_label="large_contextual_cache_failover_keyscope",
            question=(
                "For the Helio cache failover on 2026-04-18, which cache scope "
                "caused stale entitlement reads, and what exact guard must Mira Chen add?"
            ),
            blocks=(
                _block(
                    "helio-cache-incident",
                    "Helio Cache Failover Incident Review",
                    (
                        "The Helio cache failover on 2026-04-18 produced stale entitlement reads "
                        "only for tenants restored through the blue-region replay path. The cause was "
                        "the cache scope named entitlement:tenant-visible, which survived replay because "
                        "the failover job invalidated account-scoped keys but not tenant-visible keys. "
                        "Mira Chen owns the mitigation: add a replay_epoch guard to every "
                        "entitlement:tenant-visible read and reject entries whose replay_epoch is older "
                        "than the entitlement ledger checkpoint. The same review explicitly says the "
                        "session cache and the pricing cache were noisy but not causal."
                    ),
                    True,
                    target_words=360,
                ),
                _block(
                    "helio-session-cache",
                    "Session Cache Failover Notes",
                    (
                        "The session cache failover notes repeatedly mention cache scope, failover, "
                        "replay, and stale reads. They say the session cache named session:regional "
                        "had a five-minute TTL mismatch and recommend extending the login grace period. "
                        "That detail is plausible but wrong for the entitlement incident because it "
                        "affects authentication banners, not stale entitlement reads."
                    ),
                    target_words=360,
                ),
                _block(
                    "helio-pricing-cache",
                    "Pricing Cache Rollback Memo",
                    (
                        "The pricing cache rollback memo says cache scope pricing:contract-summary "
                        "was rebuilt after the same blue-region failover. It names Mira Chen as a reviewer "
                        "and mentions replay_epoch as an observability label, but it does not assign the "
                        "entitlement read guard or identify the causal entitlement cache scope."
                    ),
                    target_words=360,
                ),
                _block(
                    "helio-ops-timeline",
                    "Helio Operations Timeline",
                    (
                        "The operations timeline lists failover events on 2026-04-12, 2026-04-18, and "
                        "2026-04-23. It says the April 12 failover involved session banners, the April 18 "
                        "failover involved entitlement reads, and the April 23 rollback involved pricing "
                        "summaries. The timeline is useful for dates but does not contain the exact guard."
                    ),
                    target_words=360,
                ),
                _block(
                    "helio-ledger",
                    "Entitlement Ledger Audit",
                    (
                        "The entitlement ledger audit discusses tenant checkpoints, account checkpoints, "
                        "and replay windows. It shares vocabulary with the incident review, including "
                        "entitlement, stale reads, failover, and replay_epoch, but it only verifies ledger "
                        "ordering and deliberately avoids prescribing cache-read mitigation."
                    ),
                    target_words=360,
                ),
                _block(
                    "helio-status-copy",
                    "Customer Status Copy",
                    (
                        "The customer status copy explains that a failover caused stale entitlement "
                        "messages for some tenants. It simplifies the public wording, avoids internal "
                        "cache-scope names, and says engineering added extra validation. It is near the "
                        "topic but insufficient for the exact cache scope and guard."
                    ),
                    target_words=360,
                ),
            ),
            expected_answer_hints=(
                "entitlement:tenant-visible",
                "replay_epoch guard",
                "Mira Chen",
            ),
            validation_targets=("entitlement:tenant-visible", "replay_epoch", "Mira Chen"),
            difficulty_patterns=("same_keyword_distractor", "near_relevant_block"),
        ),
        LargeContextualTask(
            task_label="large_contextual_rollback_false_owner",
            question=(
                "For Meridian model gateway rollback R-42, what latency threshold "
                "triggers rollback, and who is the approved rollback owner?"
            ),
            blocks=(
                _block(
                    "r42-gateway-decision",
                    "Meridian Gateway R-42 Rollback Decision",
                    (
                        "Rollback R-42 for the Meridian model gateway uses the p95 gateway latency "
                        "threshold of 840 ms measured over three consecutive five-minute windows. The "
                        "approved rollback owner is Tomas Ibarra, not the serving team lead, because the "
                        "decision requires coordinating gateway routing and model admission at the same "
                        "time. The decision note warns that an older draft listed 760 ms and owner Lina "
                        "Park, but that draft was superseded before approval."
                    ),
                    True,
                    target_words=370,
                ),
                _block(
                    "r42-draft",
                    "Rollback R-42 Draft Proposal",
                    (
                        "The draft proposal for rollback R-42 is a strong false-answer distractor. It "
                        "states that p95 gateway latency above 760 ms should trigger rollback and names "
                        "Lina Park as owner. The document contains the same rollback, latency, gateway, "
                        "and owner vocabulary, but its header marks it as a pre-approval draft replaced "
                        "by the final R-42 decision."
                    ),
                    target_words=370,
                ),
                _block(
                    "r41-closeout",
                    "Meridian Gateway R-41 Closeout",
                    (
                        "The R-41 closeout describes the previous model gateway rollback. It uses a p95 "
                        "latency threshold of 900 ms and assigns ownership to the serving team lead. It "
                        "is close in numbering and operational domain, but the user asks specifically "
                        "about R-42 rather than R-41."
                    ),
                    target_words=370,
                ),
                _block(
                    "admission-control",
                    "Admission Control Tuning",
                    (
                        "Admission control tuning explains why gateway routing, model admission, latency, "
                        "and rollback ownership are connected. It recommends adding queue-depth signals "
                        "to rollback dashboards, but it does not approve the R-42 latency threshold or "
                        "name the owner."
                    ),
                    target_words=370,
                ),
                _block(
                    "latency-dashboard",
                    "Latency Dashboard Notes",
                    (
                        "The dashboard notes show p50, p90, p95, and p99 gateway latency panels. They "
                        "include examples around 840 ms and 760 ms because both values appear in review "
                        "comments. The notes are measurement guidance only and cannot determine which "
                        "threshold was approved."
                    ),
                    target_words=370,
                ),
                _block(
                    "incident-comms",
                    "Incident Communications Template",
                    (
                        "The incident communications template gives customer-facing phrasing for a "
                        "gateway rollback. It mentions Tomas Ibarra as an escalation contact, Lina Park "
                        "as a serving lead, and latency as the visible symptom, but it does not encode "
                        "the rollback threshold."
                    ),
                    target_words=370,
                ),
            ),
            expected_answer_hints=("840 ms", "Tomas Ibarra"),
            validation_targets=("840", "Tomas Ibarra"),
            difficulty_patterns=("false_answer_distractor", "same_keyword_distractor"),
        ),
        LargeContextualTask(
            task_label="large_contextual_temporal_evaluation_gate",
            question=(
                "For the Boreal evaluation gate in version 2026.04, what dataset is "
                "excluded and what minimum reviewer agreement is required?"
            ),
            blocks=(
                _block(
                    "boreal-2026-04",
                    "Boreal Evaluation Gate Version 2026.04",
                    (
                        "For Boreal evaluation gate version 2026.04, exclude the Quince-Delta replay "
                        "dataset because it includes prompts copied from the March remediation queue. "
                        "The same version requires minimum reviewer agreement of 0.81 before launch "
                        "approval. The note ties the two details together: the exclusion prevents inflated "
                        "scores, while the 0.81 agreement floor protects the remaining evaluation set from "
                        "rubric drift."
                    ),
                    True,
                    target_words=380,
                ),
                _block(
                    "boreal-2026-03",
                    "Boreal Evaluation Gate Version 2026.03",
                    (
                        "Version 2026.03 excluded the Hazel-22 adversarial dataset and required reviewer "
                        "agreement of 0.76. It also used the words evaluation, launch gate, reviewer "
                        "agreement, and excluded dataset throughout the decision record, but it describes "
                        "the previous month rather than version 2026.04."
                    ),
                    target_words=380,
                ),
                _block(
                    "boreal-2026-05-draft",
                    "Boreal Evaluation Gate Version 2026.05 Draft",
                    (
                        "The 2026.05 draft proposes excluding Quince-Delta only for calibration reports "
                        "and raising reviewer agreement to 0.84. It is a temporal distractor because it "
                        "shares the Quince-Delta dataset name and evaluation-gate vocabulary, but the "
                        "question asks about the approved 2026.04 gate."
                    ),
                    target_words=380,
                ),
                _block(
                    "reviewer-training",
                    "Reviewer Training Calibration",
                    (
                        "Reviewer training material explains agreement, rubric drift, disagreement "
                        "adjudication, and launch approval. It mentions a target of 0.81 as an example "
                        "from a training slide, but it does not identify which dataset version must be "
                        "excluded for the Boreal 2026.04 gate."
                    ),
                    target_words=380,
                ),
                _block(
                    "dataset-catalog",
                    "Boreal Dataset Catalog",
                    (
                        "The dataset catalog lists Quince-Delta, Hazel-22, Fir-Holdout, and Moss-Canary. "
                        "It notes provenance, size, and known overlaps. It is near-relevant because it "
                        "can explain why a dataset might be excluded, but it does not state the approved "
                        "gate decision or reviewer agreement floor."
                    ),
                    target_words=380,
                ),
                _block(
                    "launch-checklist",
                    "Boreal Launch Checklist",
                    (
                        "The launch checklist references evaluation gates for versions 2026.03, 2026.04, "
                        "and 2026.05. It requires confirming excluded datasets and reviewer agreement, "
                        "but it delegates exact values to the versioned gate records."
                    ),
                    target_words=380,
                ),
            ),
            expected_answer_hints=("Quince-Delta replay dataset", "0.81"),
            validation_targets=("Quince-Delta", "0.81"),
            difficulty_patterns=("temporal_distractor", "cross_reference_selected_block"),
        ),
        LargeContextualTask(
            task_label="large_contextual_near_relevant_allocation_exception",
            question=(
                "For Cobalt Route allocation after the northbound rail delay, what "
                "rule should dispatch use and which exception remains active?"
            ),
            blocks=(
                _block(
                    "cobalt-dispatch-decision",
                    "Cobalt Route Dispatch Allocation Decision",
                    (
                        "After the northbound rail delay, Cobalt Route dispatch should allocate trailer "
                        "slots by earliest dock-ready timestamp, not by customer tier or booked volume. "
                        "The active exception remains emergency vaccine replenishment: loads tagged "
                        "vaccine-critical stay first-reserved when pharmacy inventory falls below the "
                        "two-day floor. Dispatch must apply both parts together so the normal rule does "
                        "not override the vaccine-critical exception."
                    ),
                    True,
                    target_words=380,
                ),
                _block(
                    "cobalt-rail-status",
                    "Northbound Rail Delay Status",
                    (
                        "The rail status block explains why the northbound delay occurred and which "
                        "yards were affected. It mentions Cobalt Route dispatch, trailer slots, customer "
                        "tier, dock readiness, and vaccine replenishment, but it only describes transport "
                        "status and lacks the allocation rule."
                    ),
                    target_words=380,
                ),
                _block(
                    "cobalt-customer-tier",
                    "Customer Tier Allocation Proposal",
                    (
                        "This proposal recommends allocating delayed trailer capacity by platinum, gold, "
                        "and standard customer tier. It is a plausible but rejected answer. The final "
                        "dispatch decision explicitly says not to use customer tier for Cobalt Route "
                        "slots after the northbound rail delay."
                    ),
                    target_words=380,
                ),
                _block(
                    "cobalt-volume-model",
                    "Booked Volume Model",
                    (
                        "The volume model ranks customers by booked volume, predicted trailer utilization, "
                        "and cancellation risk. It discusses allocation and delay recovery in detail, "
                        "but it is a planning model rather than the approved dispatch rule."
                    ),
                    target_words=380,
                ),
                _block(
                    "cobalt-pharmacy-note",
                    "Pharmacy Inventory Exception Note",
                    (
                        "The pharmacy note explains the vaccine-critical tag and two-day inventory floor. "
                        "It is near-relevant because it contains the exception mechanics, but it does not "
                        "say the normal allocation rule for delayed Cobalt Route trailer slots."
                    ),
                    target_words=380,
                ),
                _block(
                    "cobalt-comms",
                    "Customer Communications Plan",
                    (
                        "The communications plan prepares messages about delayed trailers, emergency "
                        "healthcare loads, and slot allocation. It avoids internal rule details and says "
                        "customers will be contacted after dispatch applies the approved decision."
                    ),
                    target_words=380,
                ),
            ),
            expected_answer_hints=("earliest dock-ready timestamp", "vaccine-critical"),
            validation_targets=("earliest", "dock-ready", "vaccine-critical"),
            difficulty_patterns=(
                "near_relevant_block",
                "false_answer_distractor",
                "cross_reference_selected_block",
            ),
        ),
    ]


def _practical_large_contextual_tasks() -> list[LargeContextualTask]:
    """Return practical 10k-20k large/contextual fixtures."""

    block_words = 860
    return [
        LargeContextualTask(
            task_label="large_contextual_long_aquila_entitlements_replay",
            question=(
                "For Aquila entitlement replay version 2026.05-r3, which dataset must "
                "be excluded, what owner signs off the mitigation, and what exact "
                "replay guard must ship?"
            ),
            blocks=(
                _block(
                    "aquila-r3-final",
                    "Aquila Entitlement Replay 2026.05-r3 Final Decision",
                    (
                        "For Aquila entitlement replay version 2026.05-r3, exclude the "
                        "CedarMirror-44 dataset because its replay samples include copied "
                        "tenant grants from the April remediation queue. The mitigation "
                        "sign-off owner is Anika Rao. The exact guard that must ship is "
                        "grant_epoch_after_snapshot, applied before any entitlement replay "
                        "record can refresh a tenant-visible grant. The final decision rejects "
                        "the earlier CedarMirror-17 exclusion and says account_epoch_guard is "
                        "insufficient because it checks account snapshots rather than tenant "
                        "grant snapshots."
                    ),
                    True,
                    target_words=block_words,
                ),
                _block(
                    "aquila-r2-decision",
                    "Aquila Entitlement Replay 2026.05-r2 Decision",
                    (
                        "The 2026.05-r2 replay decision excluded CedarMirror-17, named Anika "
                        "Rao as reviewer, and proposed account_epoch_guard for account-level "
                        "grant refreshes. It repeats entitlement replay, tenant-visible grant, "
                        "dataset exclusion, and mitigation vocabulary, but it is the superseded "
                        "r2 version rather than 2026.05-r3."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "aquila-dataset-catalog",
                    "Aquila Dataset Catalog",
                    (
                        "The catalog lists CedarMirror-44, CedarMirror-17, JuniperHoldout-9, "
                        "and SpruceGrant-Delta. It explains provenance, replay sample counts, "
                        "tenant grant overlaps, and remediation queue lineage. It is near the "
                        "answer because it describes why CedarMirror datasets can contaminate "
                        "evaluation, but it does not state the final r3 exclusion, owner, or guard."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "aquila-owner-roster",
                    "Aquila Owner Roster",
                    (
                        "The owner roster names Anika Rao, Mateo Klein, and Selene Ortiz across "
                        "entitlement replay workstreams. It assigns Anika Rao to final mitigation "
                        "sign-off reviews, but it does not tie her to the CedarMirror-44 exclusion "
                        "or to grant_epoch_after_snapshot for version 2026.05-r3."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "aquila-account-guard",
                    "Account Epoch Guard Proposal",
                    (
                        "The account guard proposal recommends account_epoch_guard and says it "
                        "should ship before replay refreshes account-scoped entitlements. This is "
                        "a false-answer distractor: the r3 final decision explicitly rejects this "
                        "guard for tenant-visible grants and requires grant_epoch_after_snapshot."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "aquila-replay-observability",
                    "Replay Observability Plan",
                    (
                        "The observability plan tracks entitlement replay latency, grant refresh "
                        "volume, tenant-visible cache churn, and dataset identifiers such as "
                        "CedarMirror-44. It mentions Anika Rao as a dashboard consumer, but it "
                        "does not define the dataset exclusion or required mitigation guard."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "aquila-april-incident",
                    "April Remediation Queue Incident",
                    (
                        "The April incident review explains how copied tenant grants entered a "
                        "remediation queue. It shares the causal vocabulary behind the r3 exclusion, "
                        "but it predates version 2026.05-r3 and does not approve a replay guard."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "aquila-release-checklist",
                    "Aquila Release Checklist",
                    (
                        "The release checklist requires confirming dataset exclusions, mitigation "
                        "sign-off, and replay guards before launch. It delegates exact values to "
                        "the versioned decision record and therefore cannot answer which dataset, "
                        "owner, and guard apply to 2026.05-r3."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "aquila-comms",
                    "Aquila Customer Communications Draft",
                    (
                        "The communications draft says entitlement replay will avoid stale tenant "
                        "grants and that engineering added safeguards. It intentionally avoids "
                        "internal dataset names, exact owner names, and guard identifiers."
                    ),
                    target_words=block_words,
                ),
            ),
            expected_answer_hints=(
                "CedarMirror-44",
                "Anika Rao",
                "grant_epoch_after_snapshot",
            ),
            validation_targets=("CedarMirror-44", "Anika Rao", "grant_epoch_after_snapshot"),
            difficulty_patterns=(
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
            ),
        ),
        LargeContextualTask(
            task_label="large_contextual_long_meridian_gateway_budget",
            question=(
                "For Meridian gateway budget policy MGB-19 final, what p99 spend "
                "threshold triggers rollback, which policy version is active, and who "
                "owns the rollback approval?"
            ),
            blocks=(
                _block(
                    "mgb19-final",
                    "Meridian Gateway Budget Policy MGB-19 Final",
                    (
                        "MGB-19 final sets rollback when p99 gateway spend exceeds 18.6 "
                        "credits per thousand requests for four consecutive ten-minute windows. "
                        "The active policy version is MGB-19c. The rollback approval owner is "
                        "Noor El-Sayed. The final policy supersedes MGB-19b, which used a 16.9 "
                        "credit threshold and listed Henrik Vale as provisional approver. The "
                        "final note also rejects using average spend because p99 spend captures "
                        "the expensive router-plus-executor tail."
                    ),
                    True,
                    target_words=block_words,
                ),
                _block(
                    "mgb19b-draft",
                    "Meridian Gateway Budget Policy MGB-19b Draft",
                    (
                        "The MGB-19b draft says rollback should trigger at 16.9 credits per "
                        "thousand requests and names Henrik Vale as provisional approver. It "
                        "uses the same gateway budget, p99 spend, rollback, and policy version "
                        "terms, but it is explicitly superseded by MGB-19 final."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "mgb18-closeout",
                    "Meridian Gateway Budget MGB-18 Closeout",
                    (
                        "MGB-18 closeout used a p99 spend threshold of 21.2 credits and active "
                        "version MGB-18f. It describes rollback windows, approvals, gateway spend, "
                        "and executor cost, but the numbering and version are for the prior policy."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "gateway-cost-dashboard",
                    "Gateway Cost Dashboard Notes",
                    (
                        "The dashboard notes show p50, p95, and p99 spend panels. Example charts "
                        "include 18.6, 16.9, and 21.2 credits because reviewers compared MGB-19c, "
                        "MGB-19b, and MGB-18f. The dashboard explains measurement but not approval."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "owner-rotation",
                    "Gateway Owner Rotation",
                    (
                        "The owner rotation lists Noor El-Sayed, Henrik Vale, and Julia Marin for "
                        "budget policy reviews. It says Noor owns final approval weeks in May but "
                        "does not identify the MGB-19 final threshold or active policy version."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "router-cost-mitigation",
                    "Router Cost Mitigation Plan",
                    (
                        "The mitigation plan recommends reducing router prompts, caching selected "
                        "block IDs, and watching router-plus-executor tail spend. It repeats p99 "
                        "spend and gateway budget language, but it is not the rollback policy."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "finance-review",
                    "Finance Review for Gateway Budgets",
                    (
                        "Finance review discusses monthly budget envelopes, credits per thousand "
                        "requests, and variance reporting. It mentions MGB-19c as one scenario, but "
                        "it does not approve the operational rollback trigger."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "incident-template",
                    "Budget Rollback Incident Template",
                    (
                        "The incident template gives communication structure for gateway budget "
                        "rollbacks. It includes placeholders for threshold, policy version, and "
                        "approval owner, but no final MGB-19 values."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "admission-tail-study",
                    "Admission Tail Spend Study",
                    (
                        "The tail study explains why p99 spend is more relevant than average spend "
                        "for router-plus-executor chains. It contains several MGB examples, yet it "
                        "only supports the policy rationale and lacks the final trigger fields."
                    ),
                    target_words=block_words,
                ),
            ),
            expected_answer_hints=("18.6 credits", "MGB-19c", "Noor El-Sayed"),
            validation_targets=("18.6", "MGB-19c", "Noor El-Sayed"),
            difficulty_patterns=(
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
            ),
        ),
        LargeContextualTask(
            task_label="large_contextual_long_cobalt_dispatch_reconciliation",
            question=(
                "For Cobalt Dispatch reconciliation rule CR-88 approved on 2026-04-27, "
                "what allocation rule applies, what exception remains active, and which "
                "audit dataset must be excluded?"
            ),
            blocks=(
                _block(
                    "cr88-final",
                    "Cobalt Dispatch Reconciliation CR-88 Final Approval",
                    (
                        "CR-88 approved on 2026-04-27 says delayed dispatch slots must be "
                        "allocated by earliest customs-cleared timestamp, not by customer tier "
                        "or booked volume. The active exception remains neonatal oxygen kits: "
                        "loads tagged oxygen-critical stay first-reserved when hospital reserve "
                        "inventory falls below the six-hour floor. The audit dataset excluded "
                        "from reconciliation scoring is HarborReplay-12 because it contains "
                        "manual overrides from the March customs outage. The final approval says "
                        "all three fields must be applied together."
                    ),
                    True,
                    target_words=block_words,
                ),
                _block(
                    "cr88-draft-tier",
                    "CR-88 Customer Tier Draft",
                    (
                        "An early CR-88 draft proposed allocating delayed slots by platinum, gold, "
                        "and standard customer tier. It also mentioned neonatal oxygen kits and "
                        "HarborReplay-12 in open questions. This is a strong false-answer distractor "
                        "because the final CR-88 approval rejects customer-tier allocation."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "cr87-final",
                    "Cobalt Dispatch Reconciliation CR-87 Final",
                    (
                        "CR-87 used earliest dock-ready timestamp, kept vaccine-critical loads "
                        "first-reserved, and excluded HarborReplay-9. It shares Cobalt dispatch, "
                        "reconciliation, exception, allocation, and audit dataset vocabulary, but "
                        "it is the prior rule rather than CR-88 approved on 2026-04-27."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "oxygen-exception-note",
                    "Neonatal Oxygen Exception Note",
                    (
                        "The exception note defines oxygen-critical tags and the six-hour hospital "
                        "reserve floor. It is near-relevant because it contains the active exception, "
                        "but it does not define the allocation rule or audit dataset exclusion."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "customs-delay-status",
                    "Customs Delay Status Report",
                    (
                        "The status report explains the customs delay and lists delayed dispatch "
                        "slots, booked volume, customer tier, customs-cleared timestamps, and hospital "
                        "reserve inventory. It describes conditions but not the approved CR-88 rule."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "audit-dataset-catalog",
                    "Cobalt Audit Dataset Catalog",
                    (
                        "The catalog lists HarborReplay-12, HarborReplay-9, DockTrace-41, and "
                        "CustomsHoldout-6. It explains manual override contamination, scoring fields, "
                        "and reconciliation lineage. It lacks the CR-88 allocation rule and exception."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "booked-volume-model",
                    "Booked Volume Dispatch Model",
                    (
                        "The booked volume model ranks customers by predicted utilization and booked "
                        "volume. It argues for volume-based allocation after customs delays, but CR-88 "
                        "final chooses earliest customs-cleared timestamp instead."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "hospital-comms",
                    "Hospital Communications Plan",
                    (
                        "The communications plan prepares wording for delayed oxygen-critical loads, "
                        "hospital reserve inventory, and customs-cleared trailer status. It avoids "
                        "internal audit dataset names and does not state the allocation rule."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "reconciliation-dashboard",
                    "Reconciliation Dashboard Notes",
                    (
                        "The dashboard notes describe charts for customs-cleared timestamps, customer "
                        "tier, booked volume, exceptions, and audit dataset exclusions. It shows the "
                        "fields operators inspect but delegates approved values to CR-88 final."
                    ),
                    target_words=block_words,
                ),
            ),
            expected_answer_hints=(
                "earliest customs-cleared timestamp",
                "oxygen-critical",
                "HarborReplay-12",
            ),
            validation_targets=(
                "earliest",
                "customs-cleared",
                "oxygen-critical",
                "HarborReplay-12",
            ),
            difficulty_patterns=(
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
                "cross_reference_selected_block",
            ),
        ),
    ]


def _high_context_large_contextual_tasks() -> list[LargeContextualTask]:
    """Return high_context 20k-50k large/contextual fixtures."""

    block_words = 1250
    return [
        LargeContextualTask(
            task_label="large_contextual_high_context_orion_router_budget_gate",
            question=(
                "For Orion router budget gate ORB-74 approved in policy version "
                "2026.06-hc2, what rollback rule applies, which dataset must be "
                "excluded, who owns final approval, and what mitigation label must ship?"
            ),
            blocks=(
                _block(
                    "orb74-hc2-final",
                    "Orion Router Budget Gate ORB-74 2026.06-hc2 Final Approval",
                    (
                        "For Orion router budget gate ORB-74 approved in policy version "
                        "2026.06-hc2, rollback applies when router-plus-executor p99 spend "
                        "exceeds 31.4 credits per thousand routed requests for three "
                        "consecutive twelve-minute windows. The dataset excluded from the "
                        "gate is NebulaReplay-88 because it contains copied routing decisions "
                        "from the May admission incident. Final approval owner is Imani Vos. "
                        "The mitigation label that must ship is orb74_cost_epoch_lock. The "
                        "final approval says all four fields override older ORB-74 drafts, "
                        "including the 27.8 credit draft threshold and the obsolete "
                        "orb74_router_cache_cap mitigation."
                    ),
                    True,
                    target_words=block_words,
                ),
                _block(
                    "orb74-hc1-draft",
                    "Orion Router Budget Gate ORB-74 2026.06-hc1 Draft",
                    (
                        "The hc1 draft is a plausible but obsolete rule. It proposed rollback "
                        "when p99 spend exceeded 27.8 credits per thousand routed requests, "
                        "excluded NebulaReplay-71, and used mitigation label "
                        "orb74_router_cache_cap. Imani Vos appears as a reviewer, but this "
                        "draft was superseded before the 2026.06-hc2 approval."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "orb73-closeout",
                    "Orion Router Budget Gate ORB-73 Closeout",
                    (
                        "ORB-73 used p99 spend, router-plus-executor totals, and admission "
                        "incident language similar to ORB-74. It rolled back above 34.2 credits "
                        "and excluded NebulaReplay-60. The document repeatedly names Imani Vos "
                        "as a finance reviewer, but it covers the prior gate rather than ORB-74."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "nebula-dataset-catalog",
                    "Nebula Replay Dataset Catalog",
                    (
                        "The catalog lists NebulaReplay-88, NebulaReplay-71, NebulaReplay-60, "
                        "CometHoldout-19, and PulsarRoute-5. It explains copied routing "
                        "decisions, admission incidents, provenance, and gate contamination. "
                        "It is near-relevant because it can justify exclusions but does not "
                        "state the ORB-74 hc2 rollback rule, owner, or mitigation label."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "imani-approval-roster",
                    "Orion Approval Roster",
                    (
                        "The approval roster mentions Imani Vos across several router budget "
                        "gates, including ORB-72, ORB-73, and ORB-74. Multiple blocks mention "
                        "the same owner to make owner matching insufficient. This roster says "
                        "who can approve gates but not which ORB-74 rule, dataset, or mitigation "
                        "was approved."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "router-cache-cap-plan",
                    "Router Cache Cap Mitigation Plan",
                    (
                        "The cache cap plan argues for orb74_router_cache_cap and cites a "
                        "27.8 credit p99 spend threshold. It is a false-answer distractor "
                        "because that mitigation label was used in the obsolete hc1 draft and "
                        "was replaced by orb74_cost_epoch_lock in the final hc2 approval."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "cost-epoch-lock-design",
                    "Cost Epoch Lock Design Notes",
                    (
                        "The design note defines cost epoch locks, routed request windows, and "
                        "router-plus-executor cost accounting. It mentions orb74_cost_epoch_lock "
                        "as a candidate label, but it does not approve the ORB-74 threshold, "
                        "dataset exclusion, or final owner."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "may-admission-incident",
                    "May Admission Incident Review",
                    (
                        "The May admission incident review explains how copied routing decisions "
                        "entered replay data. NebulaReplay-88 appears in lineage tables along "
                        "with NebulaReplay-71. The review supplies background but predates the "
                        "ORB-74 2026.06-hc2 gate."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "gateway-finance-variance",
                    "Gateway Finance Variance Memo",
                    (
                        "Finance variance analysis compares 31.4, 27.8, and 34.2 credit p99 "
                        "spend scenarios for router-plus-executor paths. It names Imani Vos "
                        "as finance approver in example tables, but it does not identify which "
                        "scenario became the ORB-74 hc2 rule."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "router-observability-runbook",
                    "Router Observability Runbook",
                    (
                        "The runbook shows p50, p95, and p99 spend dashboards, twelve-minute "
                        "window aggregation, fallback counters, dataset tags, and mitigation "
                        "labels. It tells operators how to measure the gate but delegates final "
                        "values to the approved policy record."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "incident-comms-orion",
                    "Orion Incident Communications Draft",
                    (
                        "The communications draft says a budget gate may roll back expensive "
                        "router-plus-executor paths and that Imani Vos can approve customer "
                        "messaging. It intentionally removes internal dataset names, exact "
                        "thresholds, and mitigation labels."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "orb74-release-checklist",
                    "ORB-74 Release Checklist",
                    (
                        "The release checklist requires confirming rollback rule, excluded "
                        "dataset, approval owner, and mitigation label before enabling ORB-74. "
                        "It references policy version 2026.06-hc2, but it does not restate the "
                        "approved values."
                    ),
                    target_words=block_words,
                ),
            ),
            expected_answer_hints=(
                "31.4 credits",
                "NebulaReplay-88",
                "Imani Vos",
                "orb74_cost_epoch_lock",
            ),
            validation_targets=(
                "31.4",
                "NebulaReplay-88",
                "Imani Vos",
                "orb74_cost_epoch_lock",
            ),
            difficulty_patterns=(
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
                "same_owner_distractor",
                "obsolete_rule_distractor",
            ),
        ),
        LargeContextualTask(
            task_label="large_contextual_high_context_boreal_eval_release_gate",
            question=(
                "For Boreal evaluation release gate BER-122 in version 2026.07-hc4, "
                "which score threshold triggers rollback, which reviewer agreement "
                "floor is required, which dataset is excluded, and who owns the "
                "approved gate?"
            ),
            blocks=(
                _block(
                    "ber122-hc4-final",
                    "Boreal Evaluation Release Gate BER-122 Version 2026.07-hc4",
                    (
                        "For Boreal evaluation release gate BER-122 in version 2026.07-hc4, "
                        "rollback triggers when calibrated task-success score falls below "
                        "0.783 for two consecutive nightly runs. The required reviewer "
                        "agreement floor is 0.86. The excluded dataset is QuasarBlend-52 "
                        "because it contains prompts copied from the June repair board. The "
                        "approved gate owner is Celia Okafor. The final record says the older "
                        "0.801 threshold, 0.82 agreement floor, and QuasarBlend-31 exclusion "
                        "belong to the obsolete hc3 draft."
                    ),
                    True,
                    target_words=block_words,
                ),
                _block(
                    "ber122-hc3-draft",
                    "Boreal Evaluation Release Gate BER-122 Version 2026.07-hc3 Draft",
                    (
                        "The hc3 draft proposed rollback below 0.801, reviewer agreement of "
                        "0.82, and exclusion of QuasarBlend-31. It named Celia Okafor as a "
                        "review participant. This block is a plausible obsolete rule because "
                        "it has the same BER-122, Boreal, evaluation, release gate, dataset, "
                        "and owner vocabulary but was replaced by hc4."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "ber121-final",
                    "Boreal Evaluation Release Gate BER-121 Final",
                    (
                        "BER-121 used rollback below 0.771, reviewer agreement of 0.84, and "
                        "excluded QuasarBlend-29. It shares evaluation-gate structure and names "
                        "Celia Okafor as a process reviewer, but it is the prior gate and cannot "
                        "answer the BER-122 hc4 question."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "quasar-dataset-catalog",
                    "QuasarBlend Dataset Catalog",
                    (
                        "The dataset catalog lists QuasarBlend-52, QuasarBlend-31, QuasarBlend-29, "
                        "LyraHoldout-8, and VegaRepair-6. It describes copied prompts, June repair "
                        "board overlap, evaluation provenance, and scoring contamination. It lacks "
                        "the approved rollback threshold, reviewer agreement floor, and owner."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "celia-owner-roster",
                    "Boreal Gate Owner Roster",
                    (
                        "The owner roster repeatedly names Celia Okafor across BER-119 through "
                        "BER-122. It is designed to make owner-name matching insufficient: several "
                        "blocks mention Celia, but only the final hc4 gate contains all approved "
                        "decision fields."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "reviewer-calibration-plan",
                    "Reviewer Calibration Plan",
                    (
                        "The calibration plan discusses agreement floors of 0.82, 0.84, and 0.86 "
                        "for Boreal releases. It says Celia Okafor requested stricter calibration, "
                        "but it does not identify which floor belongs to BER-122 hc4 or which "
                        "dataset is excluded."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "score-threshold-study",
                    "Task-Success Score Threshold Study",
                    (
                        "The threshold study compares calibrated score cutoffs of 0.771, 0.783, "
                        "and 0.801 across Boreal releases. It explains the statistical rationale "
                        "for nightly run windows, but it is analysis rather than the approved "
                        "release gate."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "june-repair-board",
                    "June Repair Board Prompt Review",
                    (
                        "The June repair board review explains how copied prompts entered "
                        "QuasarBlend-52 and why replay data can inflate task-success scores. It "
                        "is near-relevant for dataset rationale but does not state the BER-122 "
                        "threshold, agreement floor, or owner."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "ber122-dashboard",
                    "BER-122 Dashboard Specification",
                    (
                        "The dashboard specification displays calibrated task-success score, "
                        "reviewer agreement, dataset exclusions, nightly run count, and owner "
                        "acknowledgement. It includes placeholders for hc4 values and examples "
                        "from hc3, but not the approved decision."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "release-manager-checklist",
                    "Boreal Release Manager Checklist",
                    (
                        "The release manager checklist requires confirming rollback threshold, "
                        "reviewer agreement floor, excluded dataset, and gate owner before launch. "
                        "It points to the versioned BER-122 hc4 record for exact values."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "eval-comms-draft",
                    "Boreal Evaluation Communications Draft",
                    (
                        "The communications draft says an evaluation release may be paused when "
                        "calibrated score or reviewer agreement falls outside approved gates. It "
                        "does not expose internal score thresholds, dataset names, or owner names."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "adjudication-runbook",
                    "Reviewer Adjudication Runbook",
                    (
                        "The adjudication runbook defines reviewer agreement, rubric drift, "
                        "calibration disputes, and nightly evaluation workflow. It mentions "
                        "Celia Okafor as an escalation owner and uses the same evaluation-gate "
                        "terms, but it cannot answer the approved BER-122 hc4 gate."
                    ),
                    target_words=block_words,
                ),
            ),
            expected_answer_hints=(
                "0.783",
                "0.86",
                "QuasarBlend-52",
                "Celia Okafor",
            ),
            validation_targets=("0.783", "0.86", "QuasarBlend-52", "Celia Okafor"),
            difficulty_patterns=(
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
                "same_owner_distractor",
                "obsolete_rule_distractor",
            ),
        ),
    ]


def _structural_large_contextual_tasks() -> list[LargeContextualTask]:
    """Return structural 50k+ large/contextual fixtures."""

    block_words = 2075
    relevant_block_words = 2250
    return [
        LargeContextualTask(
            task_label="large_contextual_structural_atlas_policy_mesh_gate",
            question=(
                "For Atlas policy mesh gate S-9 in active version 2026.08-s9, "
                "what rollback threshold applies, which replay dataset is excluded, "
                "who owns final approval, and what mitigation label must ship?"
            ),
            blocks=(
                _block(
                    "atlas-mesh-s9-final",
                    "Atlas Policy Mesh Gate S-9 Active Version 2026.08-s9 Final Record",
                    (
                        "For Atlas policy mesh gate S-9 in active version 2026.08-s9, "
                        "rollback applies when policy mesh p99 coordination cost exceeds "
                        "42.7 credits per thousand governed requests for four consecutive "
                        "fifteen-minute windows. The excluded replay dataset is "
                        "SableReplay-144 because it contains copied gate decisions from the "
                        "July policy repair board. Final approval owner is ATLAS_OWNER_S9. The "
                        "mitigation label that must ship is mesh_s9_epoch_pin. This final "
                        "record overrides the S-8 closeout, the 2026.08-s8 draft, and the "
                        "dashboard examples that still show the older 39.2 credit threshold."
                    ),
                    True,
                    target_words=relevant_block_words,
                ),
                _block(
                    "atlas-mesh-s8-draft",
                    "Atlas Policy Mesh Gate S-8 Draft Carried Into 2026.08",
                    (
                        "The S-8 draft is a plausible obsolete rule. It proposed rollback "
                        "above 39.2 credits per thousand governed requests, excluded "
                        "SableReplay-121, and used mitigation label mesh_s8_window_cap. "
                        "ATLAS_OWNER_S9 appears as a reviewer because the draft was copied into "
                        "the 2026.08 planning folder, but it is not the active S-9 record."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "atlas-mesh-s9-dashboard",
                    "Atlas Mesh S-9 Dashboard Specification",
                    (
                        "The dashboard specification renders p50, p95, and p99 coordination "
                        "cost, governed request counts, rollback windows, replay dataset tags, "
                        "and owner acknowledgement. It contains placeholders for 2026.08-s9 "
                        "and example values copied from S-8, including 39.2 credits and "
                        "mesh_s8_window_cap, but it does not approve final S-9 values."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "sable-replay-catalog",
                    "Sable Replay Dataset Catalog",
                    (
                        "The catalog lists SableReplay-144, SableReplay-121, SableReplay-88, "
                        "QuartzHoldout-31, and EmberRepair-17. It explains copied gate "
                        "decisions, July policy repair board provenance, and replay lineage. "
                        "It can justify why SableReplay-144 is risky, but it does not state "
                        "the S-9 rollback threshold, final owner, or mitigation label."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "atlas-owner-approval-roster",
                    "Atlas Policy Approval Roster",
                    (
                        "The approval roster names ATLAS_OWNER_S9 across S-6, S-7, S-8, and S-9 "
                        "policy mesh gates. It is intentionally insufficient by itself: owner "
                        "matching alone cannot identify the active threshold, excluded replay "
                        "dataset, or required mitigation label for 2026.08-s9."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "policy-repair-board-july",
                    "July Policy Repair Board Review",
                    (
                        "The July policy repair board describes copied gate decisions entering "
                        "SableReplay-144 and explains why replay-derived policy examples can "
                        "inflate mesh stability measurements. It supplies provenance and risk "
                        "context, but it predates final S-9 approval and does not contain all "
                        "approved gate fields."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "mesh-epoch-pin-design",
                    "Mesh Epoch Pin Design Notes",
                    (
                        "The design notes define mesh epoch pinning, governed request epochs, "
                        "policy repair windows, and coordination-cost accounting. They mention "
                        "mesh_s9_epoch_pin as a candidate mitigation label, but they do not "
                        "approve the 42.7 credit rollback threshold, dataset exclusion, or "
                        "final owner."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "mesh-window-cap-plan",
                    "Mesh Window Cap Mitigation Plan",
                    (
                        "The window cap plan argues for mesh_s8_window_cap and uses a 39.2 "
                        "credit p99 coordination-cost threshold. It is a false-answer "
                        "distractor because those values belong to the obsolete S-8 draft and "
                        "were replaced before the active 2026.08-s9 decision."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "atlas-s7-closeout",
                    "Atlas Policy Mesh Gate S-7 Closeout",
                    (
                        "The S-7 closeout uses similar policy mesh terminology, governed "
                        "requests, p99 cost windows, replay datasets, and mitigation labels. "
                        "It rolled back above 44.1 credits and excluded SableReplay-88. "
                        "ATLAS_OWNER_S9 appears as an escalation reviewer, but S-7 is not S-9."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "atlas-s9-release-checklist",
                    "Atlas S-9 Release Checklist",
                    (
                        "The release checklist requires confirming active version, rollback "
                        "threshold, excluded replay dataset, final approval owner, and mitigation "
                        "label before enabling S-9. It references the 2026.08-s9 final record "
                        "as the source of truth but intentionally does not restate the values."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "policy-mesh-runbook",
                    "Policy Mesh Operations Runbook",
                    (
                        "The operations runbook explains how to measure p99 coordination cost, "
                        "count governed requests, detect four-window rollback conditions, and "
                        "annotate replay dataset exclusions. It describes the measurement "
                        "process but delegates approved S-9 values to the final policy record."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "owner-escalation-thread",
                    "Owner Escalation Thread",
                    (
                        "The escalation thread contains messages from ATLAS_OWNER_S9, OWNER_ALT_7, "
                        "and OWNER_ALT_3 about S-9 rollout risk. It discusses approval order and "
                        "weekend coverage. It is near-relevant for ownership but lacks the "
                        "approved threshold, excluded dataset, and mitigation label."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "coordination-cost-study",
                    "Policy Mesh Coordination Cost Study",
                    (
                        "The cost study compares thresholds of 39.2, 42.7, and 44.1 credits "
                        "across historical mesh gates. It explains why p99 cost over four "
                        "fifteen-minute windows is a stable trigger. It is analysis rather "
                        "than the active approval record."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "governed-request-ledger",
                    "Governed Request Ledger Audit",
                    (
                        "The ledger audit describes governed request IDs, mesh epochs, policy "
                        "repair snapshots, and replay checkpoint ordering. It mentions "
                        "SableReplay-144 in lineage tables and mesh_s9_epoch_pin in audit "
                        "comments, but it does not approve the gate."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "atlas-s9-comms-draft",
                    "Atlas S-9 Communications Draft",
                    (
                        "The communications draft says Atlas may pause policy mesh rollout when "
                        "coordination cost exceeds an approved gate and that a named owner will "
                        "approve customer-facing status language. It removes internal thresholds, "
                        "replay dataset names, and mitigation labels."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "repair-dataset-holdout",
                    "Repair Dataset Holdout Memo",
                    (
                        "The holdout memo recommends using QuartzHoldout-31 and excluding some "
                        "SableReplay data from retrospective scoring. It discusses SableReplay-144 "
                        "and SableReplay-121 together, but it does not identify which dataset the "
                        "active S-9 gate excludes."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "mesh-stability-dashboard",
                    "Mesh Stability Dashboard Notes",
                    (
                        "The dashboard notes describe charts for coordination cost, policy mesh "
                        "stability, replay exclusions, mitigation label rollout, and final owner "
                        "acknowledgement. They show fields operators inspect but point to the "
                        "final record for approved values."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "atlas-s9-changelog",
                    "Atlas S-9 Changelog",
                    (
                        "The changelog records that S-9 replaced S-8 draft values and switched "
                        "from window capping toward epoch pinning. It names 2026.08-s9 and "
                        "ATLAS_OWNER_S9, but it omits the final threshold and replay dataset exclusion."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "mesh-policy-faq",
                    "Policy Mesh FAQ",
                    (
                        "The FAQ explains terms such as policy mesh, governed request, p99 "
                        "coordination cost, replay dataset, final owner, active version, and "
                        "mitigation label. It is broad background and intentionally contains no "
                        "approved S-9 values."
                    ),
                    target_words=block_words,
                ),
                _block(
                    "s9-audit-precheck",
                    "S-9 Audit Precheck",
                    (
                        "The audit precheck confirms that the release package must include a "
                        "rollback threshold, excluded replay dataset, final approval owner, "
                        "active policy version, and mitigation label. It verifies document "
                        "completeness but not the actual approved values."
                    ),
                    target_words=block_words,
                ),
            ),
            expected_answer_hints=(
                "42.7 credits",
                "SableReplay-144",
                "ATLAS_OWNER_S9",
                "mesh_s9_epoch_pin",
                "2026.08-s9",
            ),
            validation_targets=(
                "42.7",
                "SableReplay-144",
                "ATLAS_OWNER_S9",
                "mesh_s9_epoch_pin",
                "2026.08-s9",
            ),
            difficulty_patterns=(
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
                "same_owner_distractor",
                "obsolete_rule_distractor",
                "structural_record_navigation",
                "partial_field_distractor",
            ),
        ),
    ]


def _block(
    block_id: str,
    title: str,
    lead: str,
    relevant: bool = False,
    target_words: int = 270,
) -> ContextBlock:
    filler = (
        "The surrounding notes preserve realistic operational noise: status updates, "
        "owner names, dates, caveats, metrics, risks, and adjacent decisions. These "
        "sentences make the block large enough to test context pressure while keeping "
        "the factual answer anchored in the opening paragraph. Readers should treat "
        "this material as plausible background unless the user question asks for it."
    )
    words = lead.split()
    filler_words = filler.split()
    while len(words) < target_words:
        words.extend(filler_words)
    return ContextBlock(block_id=block_id, title=title, text=" ".join(words), relevant=relevant)


def run_benchmark(
    tasks: list[LargeContextualTask],
    repeat: int,
    model: str,
    base_url: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT,
    max_tokens: int = 160,
    dry_run: bool = False,
    provider: ChatProvider | None = None,
    codexcli_idle_timeout_seconds: float | None = None,
    codexcli_router_reasoning_effort: str | None = None,
    selection_mode: str = "fixture",
    router_model: str | None = None,
    selector: BlockSelector | None = None,
    task_tier: str = TASK_TIER_STANDARD,
    executor: str = LEMONADE_EXECUTOR,
    max_output_repairs: int = 0,
    provider_call_delay_seconds: float = 0.0,
    sleep_func=time.sleep,
) -> dict[str, Any]:
    if repeat < 1:
        raise ValueError("--repeat must be at least 1.")
    if timeout_seconds <= 0:
        raise ValueError("--timeout-seconds must be greater than 0.")
    if codexcli_idle_timeout_seconds is not None and codexcli_idle_timeout_seconds <= 0:
        raise ValueError("--codexcli-idle-timeout-seconds must be greater than 0.")
    if (
        codexcli_router_reasoning_effort is not None
        and codexcli_router_reasoning_effort not in CODEXCLI_REASONING_EFFORTS
    ):
        raise ValueError(
            "--codexcli-router-reasoning-effort must be one of: "
            + ", ".join(CODEXCLI_REASONING_EFFORTS)
        )
    if max_tokens < 1:
        raise ValueError("--max-tokens must be at least 1.")
    if max_output_repairs < 0:
        raise ValueError("--max-output-repairs must be at least 0.")
    if provider_call_delay_seconds < 0:
        raise ValueError("--provider-call-delay-seconds must be at least 0.")
    if not tasks:
        raise ValueError("At least one large/contextual task is required.")
    if selection_mode not in SELECTION_MODES:
        raise ValueError(f"Unknown selection mode: {selection_mode}")
    if executor not in EXECUTORS:
        raise ValueError(f"Unknown executor: {executor}")
    task_tier = normalize_task_tier(task_tier)
    base_url = base_url or _default_base_url(executor)
    provider_pacer = ProviderCallPacer(
        delay_seconds=provider_call_delay_seconds,
        sleep_func=sleep_func,
    )

    provider = provider or (
        None
        if dry_run
        else _make_provider(
            executor,
            base_url,
            timeout_seconds,
            codexcli_idle_timeout_seconds=codexcli_idle_timeout_seconds,
        )
    )
    router_model = router_model or _default_router_model(executor)
    selector = selector or _make_selector(
        selection_mode=selection_mode,
        dry_run=dry_run,
        executor=executor,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
        codexcli_idle_timeout_seconds=codexcli_idle_timeout_seconds,
        codexcli_router_reasoning_effort=codexcli_router_reasoning_effort,
        router_model=router_model,
        provider_pacer=provider_pacer,
    )
    selection_verifier = SelectionVerifier()
    selection_verification_enabled = _selection_verification_enabled(task_tier)
    output_validator = OutputValidator()
    output_validation_enabled = _output_validation_enabled(task_tier)
    output_repairer = OutputRepairer(output_validator)
    output_repair_enabled = _output_repair_enabled(task_tier)
    runs = []
    for task in tasks:
        fixture_route = select_relevant_block(task)
        for repeat_index in range(1, repeat + 1):
            for mode in _execution_modes(selection_mode):
                route = _route_for_mode(task, mode, fixture_route, selector)
                route = _verify_route_selection(
                    task=task,
                    mode=mode,
                    route=route,
                    verifier=selection_verifier,
                    enabled=selection_verification_enabled,
                )
                runs.append(
                    execute_task(
                        task=task,
                        mode=mode,
                        route=route,
                        repeat_index=repeat_index,
                        model=model,
                        base_url=base_url,
                        max_tokens=max_tokens,
                        dry_run=dry_run,
                        provider=provider,
                        fixture_route=fixture_route,
                        executor=executor,
                        output_validator=output_validator,
                        output_validation_required=output_validation_enabled,
                        output_repairer=output_repairer,
                        output_repair_enabled=output_repair_enabled,
                        max_output_repairs=max_output_repairs,
                        task_tier=task_tier,
                        provider_pacer=provider_pacer,
                    )
                )

    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_type": BENCHMARK_TYPE,
            "router": _router_name_for_selection_mode(selection_mode, dry_run, executor),
            "provider": executor,
            "api_style": _api_style(executor),
            "executor": executor,
            "executor_model": model,
            "router_model": router_model if selection_mode in ("router", "both") else None,
            "base_url": base_url,
            "repeat": repeat,
            "selection_mode": selection_mode,
            "task_tier": task_tier,
            "task_tier_description": TASK_TIER_DESCRIPTIONS[task_tier],
            "task_count": len(tasks),
            "run_count": len(runs),
            "dry_run": dry_run,
            "provider_call_delay_seconds": provider_call_delay_seconds,
            "codexcli_idle_timeout_seconds": (
                codexcli_idle_timeout_seconds
                if executor == OPENAI_CODEXCLI_EXECUTOR
                else None
            ),
            "codexcli_router_reasoning_effort": (
                codexcli_router_reasoning_effort
                if executor == OPENAI_CODEXCLI_EXECUTOR
                and selection_mode in ("router", "both")
                else None
            ),
            "selection_verification": {
                "enabled": selection_verification_enabled,
                "trigger": (
                    SELECTION_VERIFICATION_TRIGGER_STRUCTURAL_TIER
                    if selection_verification_enabled
                    else None
                ),
                "applies_to_modes": (
                    ["spatial_router"] if selection_verification_enabled else []
                ),
            },
            "output_validation": {
                "enabled": output_validation_enabled,
                "trigger": (
                    OUTPUT_VALIDATION_TRIGGER_STRUCTURAL_TIER
                    if output_validation_enabled
                    else None
                ),
                "applies_to_modes": (
                    list(_execution_modes(selection_mode)) if output_validation_enabled else []
                ),
            },
            "output_repair": {
                "enabled": output_repair_enabled and max_output_repairs > 0,
                "trigger": (
                    OUTPUT_REPAIR_TRIGGER_STRUCTURAL_TIER
                    if output_repair_enabled
                    else None
                ),
                "max_output_repairs": max_output_repairs,
                "applies_to_modes": (
                    ["spatial_router"] if output_repair_enabled else []
                ),
            },
            "final_phase_conclusion": FINAL_PHASE_CONCLUSION,
        },
        "summary": summarize_runs(runs, task_tier=task_tier),
        "per_task": summarize_per_task(runs),
        "tasks": [task_to_dict(task) for task in tasks],
        "runs": runs,
    }


def _make_provider(
    executor: str,
    base_url: str,
    timeout_seconds: float,
    *,
    codexcli_idle_timeout_seconds: float | None = None,
    codexcli_reasoning_effort: str | None = None,
) -> ChatProvider:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        kwargs: dict[str, Any] = {"idle_timeout": codexcli_idle_timeout_seconds}
        if codexcli_reasoning_effort is not None:
            kwargs["reasoning_effort"] = codexcli_reasoning_effort
        return CodexCLIProvider(**kwargs)
    if executor == OPENAI_API_EXECUTOR:
        return OpenAIAPIProvider(base_url=base_url, timeout=timeout_seconds)
    if executor == ANTHROPIC_EXECUTOR:
        return AnthropicProvider(base_url=base_url, timeout=timeout_seconds)
    if executor == ALIBABA_API_EXECUTOR:
        return AlibabaAPIProvider(base_url=base_url, timeout=timeout_seconds)
    if executor == GOOGLE_API_EXECUTOR:
        return GoogleAPIProvider(base_url=base_url, timeout=timeout_seconds)
    provider = LemonadeProvider(base_url=base_url)
    provider.timeout = timeout_seconds
    return provider


def _make_selector(
    selection_mode: str,
    dry_run: bool,
    executor: str,
    base_url: str,
    timeout_seconds: float,
    codexcli_idle_timeout_seconds: float | None,
    codexcli_router_reasoning_effort: str | None,
    router_model: str,
    provider_pacer: ProviderCallPacer | None = None,
) -> BlockSelector | None:
    if selection_mode == "fixture":
        return None
    if dry_run:
        return DryRunBlockSelector()
    provider = _make_provider(
        executor,
        base_url,
        timeout_seconds,
        codexcli_idle_timeout_seconds=codexcli_idle_timeout_seconds,
        codexcli_reasoning_effort=(
            codexcli_router_reasoning_effort
            if executor == OPENAI_CODEXCLI_EXECUTOR
            else None
        ),
    )
    return LemonadeBlockSelector(
        provider=provider,
        model=router_model,
        router_name=_block_selector_name(executor),
        selection_source=_selection_source(executor),
        provider_pacer=provider_pacer,
    )


def _execution_modes(selection_mode: str) -> tuple[str, ...]:
    if selection_mode == "fixture":
        return ("baseline", "spatial")
    if selection_mode == "router":
        return ("baseline", "spatial_router")
    if selection_mode == "both":
        return ("baseline", "spatial_fixture", "spatial_router")
    raise ValueError(f"Unknown selection mode: {selection_mode}")


def _route_for_mode(
    task: LargeContextualTask,
    mode: str,
    fixture_route: dict[str, Any],
    selector: BlockSelector | None,
) -> dict[str, Any]:
    if mode in ("baseline", "spatial", "spatial_fixture"):
        return fixture_route
    if mode == "spatial_router":
        if selector is None:
            raise ValueError("selector is required for spatial_router mode.")
        return selector.select(task, fixture_route)
    raise ValueError(f"Unknown mode: {mode}")


def _selection_verification_enabled(task_tier: str) -> bool:
    return normalize_task_tier(task_tier) == TASK_TIER_STRUCTURAL


def _output_validation_enabled(task_tier: str) -> bool:
    return normalize_task_tier(task_tier) == TASK_TIER_STRUCTURAL


def _output_repair_enabled(task_tier: str) -> bool:
    return normalize_task_tier(task_tier) == TASK_TIER_STRUCTURAL


def _verify_route_selection(
    *,
    task: LargeContextualTask,
    mode: str,
    route: dict[str, Any],
    verifier: SelectionVerifier,
    enabled: bool,
) -> dict[str, Any]:
    if not enabled or mode != "spatial_router":
        return route

    selected_block = _block_by_id(task, str(route["selected_block_id"]))
    verification = verifier.verify(
        selected_context=selected_block.text,
        required_targets=task.validation_targets,
    )
    verified_route = dict(route)
    verified_route.update(
        {
            "selection_verification_required": True,
            "selection_verification_status": verification.status,
            "selection_contains_all_targets": verification.contains_all_targets,
            "selection_present_targets": list(verification.present_targets),
            "selection_missing_targets": list(verification.missing_targets),
            "selection_target_count": verification.target_count,
            "selection_missing_target_count": verification.missing_target_count,
            "notes": (
                f"{route['notes']}; selection_verification={verification.status}; "
                f"missing_targets={','.join(verification.missing_targets) or 'none'}"
            ),
        }
    )
    return verified_route


def _router_name_for_selection_mode(selection_mode: str, dry_run: bool, executor: str) -> str:
    if selection_mode == "fixture":
        return FIXTURE_ROUTER_NAME
    if dry_run:
        return DRY_RUN_ROUTER_NAME
    return _block_selector_name(executor)


def _block_selector_name(executor: str) -> str:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return CODEXCLI_BLOCK_SELECTOR_NAME
    if executor == OPENAI_API_EXECUTOR:
        return OPENAI_API_BLOCK_SELECTOR_NAME
    if executor == ANTHROPIC_EXECUTOR:
        return ANTHROPIC_BLOCK_SELECTOR_NAME
    if executor == ALIBABA_API_EXECUTOR:
        return ALIBABA_API_BLOCK_SELECTOR_NAME
    if executor == GOOGLE_API_EXECUTOR:
        return GOOGLE_API_BLOCK_SELECTOR_NAME
    return LEMONADE_BLOCK_SELECTOR_NAME


def _selection_source(executor: str) -> str:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return "codexcli"
    if executor == OPENAI_API_EXECUTOR:
        return "openai_api"
    if executor == ANTHROPIC_EXECUTOR:
        return "anthropic_messages"
    if executor == ALIBABA_API_EXECUTOR:
        return "alibaba_api"
    if executor == GOOGLE_API_EXECUTOR:
        return "google_api"
    return "lemonade"


def _api_style(executor: str) -> str:
    if executor == OPENAI_CODEXCLI_EXECUTOR:
        return "codexcli_process_jsonl"
    if executor == OPENAI_API_EXECUTOR:
        return "openai_responses"
    if executor == ANTHROPIC_EXECUTOR:
        return ANTHROPIC_API_STYLE
    if executor == GOOGLE_API_EXECUTOR:
        return GOOGLE_API_STYLE
    return "openai_compatible_chat"


def select_relevant_block(task: LargeContextualTask) -> dict[str, Any]:
    relevant_blocks = [block for block in task.blocks if block.relevant]
    if len(relevant_blocks) != 1:
        raise ValueError(
            f"Task {task.task_label!r} must have exactly one relevant block; "
            f"found {len(relevant_blocks)}."
        )
    selected = relevant_blocks[0]
    return {
        "router": FIXTURE_ROUTER_NAME,
        "selected_block_id": selected.block_id,
        "selected_block_title": selected.title,
        "selected_block_count": 1,
        "selection_source": "fixture",
        "router_success": True,
        "router_valid_selection": True,
        "router_selection_matches_fixture": True,
        "executor_used_fallback": False,
        "router_latency_ms": None,
        "router_input_tokens": None,
        "router_output_tokens": None,
        "router_total_tokens": None,
        "router_error": "",
        "router_confidence": 1.0,
        "router_reason": "Fixture oracle selected the known relevant block.",
        "available_block_ids": [block.block_id for block in task.blocks],
        "notes": (
            f"selected block {selected.block_id}; suppressed "
            f"{len(task.blocks) - 1} distractor blocks"
        ),
    }


class DryRunBlockSelector:
    """Deterministic selector used when dry-run asks for router mode."""

    def select(
        self,
        task: LargeContextualTask,
        fixture_route: dict[str, Any],
    ) -> dict[str, Any]:
        selected_block = _block_by_id(task, str(fixture_route["selected_block_id"]))
        prompt = build_selector_prompt(task)
        return {
            "router": DRY_RUN_ROUTER_NAME,
            "selected_block_id": selected_block.block_id,
            "router_selected_block_id": selected_block.block_id,
            "selected_block_title": selected_block.title,
            "selected_block_count": 1,
            "selection_source": "dry_run_fixture",
            "router_success": True,
            "router_valid_selection": True,
            "router_selection_matches_fixture": True,
            "executor_used_fallback": False,
            "router_latency_ms": deterministic_latency_ms(
                task.task_label, "router", estimate_tokens(prompt)
            ),
            "router_input_tokens": estimate_tokens(prompt),
            "router_output_tokens": estimate_tokens(selected_block.block_id),
            "router_total_tokens": estimate_tokens(prompt) + estimate_tokens(selected_block.block_id),
            "router_error": "",
            "router_confidence": 1.0,
            "router_reason": "Dry-run router simulation selected the fixture-relevant block.",
            "available_block_ids": [block.block_id for block in task.blocks],
            "notes": (
                f"dry-run router selected block {selected_block.block_id}; "
                f"suppressed {len(task.blocks) - 1} distractor blocks"
            ),
        }


class LemonadeBlockSelector:
    """Provider-backed selector for large/contextual block ids."""

    def __init__(
        self,
        provider: ChatProvider,
        model: str,
        router_name: str = LEMONADE_BLOCK_SELECTOR_NAME,
        selection_source: str = "lemonade",
        provider_pacer: ProviderCallPacer | None = None,
    ):
        self.provider = provider
        self.model = model
        self.router_name = router_name
        self.selection_source = selection_source
        self.provider_pacer = provider_pacer or ProviderCallPacer()

    def select(
        self,
        task: LargeContextualTask,
        fixture_route: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = build_selector_prompt(task)
        started = time.perf_counter()
        response: dict[str, Any] = {}
        output = ""
        attempted_block_id: str | None = None
        try:
            self.provider_pacer.wait_before_call()
            response = self.provider.chat(
                [{"role": "user", "content": prompt}],
                model=self.model,
                max_tokens=192,
                temperature=0.0,
            )
            output = _extract_response_text(response)
            parsed = parse_selector_output(output)
            attempted_block_id = str(parsed["selected_block_id"])
            block = _block_by_id(task, attempted_block_id)
            latency_ms = int((time.perf_counter() - started) * 1000)
            token_usage = _extract_token_usage(response, prompt, output)
            return _selector_route(
                task=task,
                fixture_route=fixture_route,
                block=block,
                router_selected_block_id=attempted_block_id,
                latency_ms=latency_ms,
                token_usage=token_usage,
                success=True,
                error="",
                confidence=_coerce_confidence(parsed.get("confidence")),
                reason=str(parsed.get("reason") or ""),
                router_name=self.router_name,
                selection_source=self.selection_source,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            token_usage = _extract_token_usage(response, prompt, output)
            fallback_block = _block_by_id(task, str(fixture_route["selected_block_id"]))
            return _selector_route(
                task=task,
                fixture_route=fixture_route,
                block=fallback_block,
                router_selected_block_id=attempted_block_id,
                latency_ms=latency_ms,
                token_usage=token_usage,
                success=False,
                error=str(exc),
                confidence=0.0,
                reason="Router failed; fell back to fixture-selected block for safe execution.",
                router_name=self.router_name,
                selection_source="fixture_fallback_after_router_error",
            )


def _selector_route(
    task: LargeContextualTask,
    fixture_route: dict[str, Any],
    block: ContextBlock,
    router_selected_block_id: str | None,
    latency_ms: int,
    token_usage: dict[str, Any],
    success: bool,
    error: str,
    confidence: float,
    reason: str,
    router_name: str,
    selection_source: str,
) -> dict[str, Any]:
    executor_used_fallback = not bool(success)
    matches_fixture = bool(success) and block.block_id == fixture_route["selected_block_id"]
    return {
        "router": router_name if success else str(selection_source),
        "selected_block_id": block.block_id,
        "router_selected_block_id": router_selected_block_id if success else router_selected_block_id,
        "selected_block_title": block.title,
        "selected_block_count": 1,
        "selection_source": selection_source,
        "router_success": bool(success),
        "router_valid_selection": bool(success),
        "router_selection_matches_fixture": matches_fixture,
        "executor_used_fallback": executor_used_fallback,
        "router_latency_ms": int(latency_ms),
        "router_input_tokens": int(token_usage["input_tokens"]),
        "router_output_tokens": int(token_usage["output_tokens"]),
        "router_total_tokens": int(token_usage["total_tokens"]),
        "router_error": error,
        "router_confidence": confidence,
        "router_reason": reason,
        "available_block_ids": [candidate.block_id for candidate in task.blocks],
        "notes": (
            f"router_selected={router_selected_block_id}; executor_block={block.block_id}; "
            f"fixture={fixture_route['selected_block_id']}; match={matches_fixture}; "
            f"fallback={executor_used_fallback}; source={selection_source}; "
            f"suppressed {len(task.blocks) - 1} distractor blocks"
        ),
    }


def build_selector_prompt(task: LargeContextualTask) -> str:
    allowed_block_ids = json.dumps([block.block_id for block in task.blocks])
    block_lines = "\n".join(format_selector_block(block, task.question) for block in task.blocks)
    return (
        "/no_think\n"
        "You are selecting the single context block that contains enough information to answer "
        "every requested field in the user question. Do not answer the question.\n\n"
        "Selection rules:\n"
        "- Distractor blocks may share the same keywords, dates, people, incidents, and domain vocabulary.\n"
        "- Prefer answer sufficiency over topical similarity. Inspect whether the block contains all requested values.\n"
        "- A block that only lists required field names, schemas, checklists, audit requirements, "
        "or document completeness rules is not sufficient unless it contains the actual requested values.\n"
        "- Prefer blocks containing the actual values requested by the question.\n"
        "- Do not choose blocks that only identify the incident, timeline, background, observability, status, "
        "communications, or related context if they lack the exact answer.\n"
        "- Prefer the block with the exact requested fields such as cache scope, guard, owner, threshold, "
        "dataset, version, decision, exception, or mitigation.\n"
        "- Your reason should cite the exact requested values found in the selected block. "
        "Cite at least two exact values when possible. Keep the reason to one short line. "
        "If you cannot cite those values from that block, select another block.\n"
        "- Copy selected_block_id exactly from the allowed block ID JSON array, byte-for-byte.\n"
        "- The selected_block_id value must be the ID string only, without labels or prefixes. "
        "Return the ID value, not labels such as \"block_id: ...\".\n"
        "- Do not normalize, abbreviate, spell-correct, prefix, or invent block IDs. "
        "Invalid block IDs count as router failure.\n"
        "- If uncertain, choose one exact listed block_id with lower confidence instead of modifying an ID.\n\n"
        "Return only compact JSON with keys selected_block_id, confidence, and reason.\n"
        f"Allowed block IDs JSON array: {allowed_block_ids}\n\n"
        f"Question: {task.question}\n\n"
        "Candidate blocks:\n"
        f"{block_lines}\n\n"
        "Return JSON only. The selected_block_id string must be one of the allowed block IDs."
    )


def format_selector_block(block: ContextBlock, question: str) -> str:
    found_terms, missing_terms = _question_term_signals(question, block.text)
    return (
        f"- \"{block.block_id}\"\n"
        f"  title: {block.title}\n"
        f"  preview: {_block_preview(block.text)}\n"
        f"  keywords: {_block_keywords(block)}\n"
        f"  question_terms_found: {found_terms}\n"
        f"  question_terms_missing: {missing_terms}"
    )


def _block_preview(text: str, max_words: int = 90) -> str:
    words = text.split()
    preview = " ".join(words[:max_words])
    if len(words) > max_words:
        preview = f"{preview} ..."
    return preview


def _block_keywords(block: ContextBlock) -> str:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9:-]{3,}", f"{block.title} {block.text}")
    seen: set[str] = set()
    keywords = []
    for candidate in candidates:
        key = candidate.lower()
        if key in seen:
            continue
        seen.add(key)
        keywords.append(candidate)
        if len(keywords) >= 10:
            break
    return ", ".join(keywords)


def _question_term_signals(question: str, block_text: str, max_terms: int = 12) -> tuple[str, str]:
    """Expose compact lexical overlap without leaking fixture relevance labels."""

    stopwords = {
        "about",
        "after",
        "before",
        "block",
        "does",
        "exact",
        "for",
        "from",
        "and",
        "must",
        "only",
        "required",
        "should",
        "that",
        "the",
        "their",
        "there",
        "these",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "was",
    }
    candidates = re.findall(r"[A-Za-z0-9][A-Za-z0-9:-]{2,}", question)
    seen: set[str] = set()
    terms = []
    for candidate in candidates:
        key = candidate.lower()
        if key in stopwords or key in seen:
            continue
        seen.add(key)
        terms.append(candidate)
    block_lower = block_text.lower()
    found = [term for term in terms if term.lower() in block_lower][:max_terms]
    missing = [term for term in terms if term.lower() not in block_lower][:max_terms]
    return ", ".join(found) or "none", ", ".join(missing) or "none"


def parse_selector_output(output: str) -> dict[str, Any]:
    stripped = output.strip()
    if not stripped:
        raise ValueError("router returned empty selector output")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("router selector output must be a JSON object")
    selected_block_id = parsed.get("selected_block_id")
    if not isinstance(selected_block_id, str) or not selected_block_id.strip():
        raise ValueError("router selector output must include selected_block_id")
    parsed["selected_block_id"] = selected_block_id.strip()
    return parsed


def _block_by_id(task: LargeContextualTask, block_id: str) -> ContextBlock:
    for block in task.blocks:
        if block.block_id == block_id:
            return block
    allowed = ", ".join(block.block_id for block in task.blocks)
    raise ValueError(f"Invalid selected_block_id {block_id!r}; expected one of: {allowed}")


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return min(1.0, max(0.0, confidence))


def _maybe_repair_output(
    *,
    task: LargeContextualTask,
    mode: str,
    route: dict[str, Any],
    output: str,
    output_validation: Any,
    output_repairer: OutputRepairer,
    output_repair_enabled: bool,
    max_output_repairs: int,
    dry_run: bool,
    execution_error: str,
    provider: ChatProvider | None,
    model: str,
    max_tokens: int,
    provider_pacer: ProviderCallPacer | None = None,
) -> tuple[OutputRepairResult, bool]:
    output_missing_targets = tuple(
        output_validation.missing_targets if output_validation is not None else ()
    )
    in_repair_scope = output_repair_enabled and mode == "spatial_router"
    selection_status = route.get("selection_verification_status")
    repair_required = bool(
        in_repair_scope
        and not dry_run
        and not execution_error
        and selection_status == "complete"
        and output_validation is not None
        and output_validation.status == "incomplete"
        and output_missing_targets
    )
    if not in_repair_scope or dry_run:
        return (
            output_repair_not_attempted(
                status=OUTPUT_REPAIR_STATUS_DISABLED,
                missing_targets_before=output_missing_targets,
                missing_targets_after=output_missing_targets,
            ),
            repair_required,
        )
    if selection_status == "incomplete":
        return (
            output_repair_not_attempted(
                status=OUTPUT_REPAIR_STATUS_SKIPPED_SELECTION_INCOMPLETE,
                missing_targets_before=output_missing_targets,
                missing_targets_after=output_missing_targets,
            ),
            False,
        )
    if not repair_required:
        return (
            output_repair_not_attempted(
                status=OUTPUT_REPAIR_STATUS_NOT_REQUIRED,
                missing_targets_before=output_missing_targets,
                missing_targets_after=output_missing_targets,
            ),
            False,
        )
    if max_output_repairs <= 0 or provider is None:
        return (
            output_repair_not_attempted(
                status=OUTPUT_REPAIR_STATUS_DISABLED,
                missing_targets_before=output_missing_targets,
                missing_targets_after=output_missing_targets,
            ),
            True,
        )

    selected_block = _block_by_id(task, str(route["selected_block_id"]))
    if provider_pacer is not None:
        provider_pacer.wait_before_call()
    repair = output_repairer.repair(
        provider=provider,
        model=model,
        question=task.question,
        selected_block_id=selected_block.block_id,
        selected_context=selected_block.text,
        original_output=output,
        missing_targets=output_missing_targets,
        required_targets=task.validation_targets,
        max_tokens=max_tokens,
    )
    return repair, True


def execute_task(
    task: LargeContextualTask,
    mode: str,
    route: dict[str, Any],
    repeat_index: int,
    model: str,
    base_url: str,
    max_tokens: int,
    dry_run: bool,
    provider: ChatProvider | None,
    fixture_route: dict[str, Any] | None = None,
    executor: str = LEMONADE_EXECUTOR,
    output_validator: OutputValidator | None = None,
    output_validation_required: bool = False,
    output_repairer: OutputRepairer | None = None,
    output_repair_enabled: bool = False,
    max_output_repairs: int = 0,
    task_tier: str | None = None,
    provider_pacer: ProviderCallPacer | None = None,
) -> dict[str, Any]:
    prompt = build_prompt(task, mode, route, task_tier=task_tier)
    prompt_tokens_estimate = estimate_tokens(prompt)
    started = time.perf_counter()
    error = ""
    response: dict[str, Any] = {}

    if dry_run:
        output = " ".join(task.expected_answer_hints)
        latency_ms = deterministic_latency_ms(task.task_label, mode, prompt_tokens_estimate)
        tokens = {
            "input_tokens": prompt_tokens_estimate,
            "output_tokens": estimate_tokens(output),
            "total_tokens": prompt_tokens_estimate + estimate_tokens(output),
        }
    else:
        if provider is None:
            raise ValueError("provider is required when dry_run is false.")
        try:
            if provider_pacer is not None:
                provider_pacer.wait_before_call()
            response = provider.chat(
                [{"role": "user", "content": prompt}],
                model=model,
                max_tokens=max_tokens,
                temperature=0.0,
            )
            output = _extract_response_text(response)
        except Exception as exc:
            output = ""
            error = str(exc)
        latency_ms = int((time.perf_counter() - started) * 1000)
        tokens = _extract_token_usage(response, prompt, output)

    validation = validate_output(task, output)
    original_success = bool(not error and validation["passed"])
    output_validation = None
    if output_validation_required:
        validator = output_validator or OutputValidator()
        output_validation = validator.validate(
            output=output,
            required_targets=task.validation_targets,
        )
    repair_result, repair_required = _maybe_repair_output(
        task=task,
        mode=mode,
        route=route,
        output=output,
        output_validation=output_validation,
        output_repairer=output_repairer or OutputRepairer(output_validator),
        output_repair_enabled=output_repair_enabled,
        max_output_repairs=max_output_repairs,
        dry_run=dry_run,
        execution_error=error,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        provider_pacer=provider_pacer,
    )
    repair_complete = repair_result.status == OUTPUT_REPAIR_STATUS_ATTEMPTED_COMPLETE
    output_final = repair_result.repaired_text if repair_complete else output
    output_final_source = "repaired" if repair_complete else "original"
    success_after_output_repair = (
        True
        if repair_complete
        else (
            False
            if repair_result.status == OUTPUT_REPAIR_STATUS_ATTEMPTED_INCOMPLETE
            else original_success
        )
    )
    used_blocks = block_ids_for_mode(task, mode, route)
    fixture_selected_block_id = (
        str(fixture_route["selected_block_id"]) if fixture_route else str(route["selected_block_id"])
    )
    router_total_tokens = _optional_int(route.get("router_total_tokens"))
    router_latency_ms = _optional_int(route.get("router_latency_ms"))
    return {
        "task_label": task.task_label,
        "mode": mode,
        "router": str(route["router"]),
        "executor": executor,
        "provider": executor,
        "model": model,
        "prompt_style": f"{BENCHMARK_TYPE}:{mode}",
        "benchmark_type": BENCHMARK_TYPE,
        "repeat_index": repeat_index,
        "input_tokens": int(tokens["input_tokens"]),
        "output_tokens": int(tokens["output_tokens"]),
        "total_tokens": int(tokens["total_tokens"]),
        "input_tokens_estimate": prompt_tokens_estimate,
        "latency_ms": latency_ms,
        "success": original_success,
        "success_after_output_repair": success_after_output_repair,
        "error": error,
        "validation": validation,
        "output_validation_required": output_validation_required,
        "output_validation_status": (
            output_validation.status if output_validation is not None else None
        ),
        "output_contains_all_targets": (
            output_validation.contains_all_targets if output_validation is not None else None
        ),
        "output_present_targets": (
            list(output_validation.present_targets) if output_validation is not None else None
        ),
        "output_missing_targets": (
            list(output_validation.missing_targets) if output_validation is not None else None
        ),
        "output_target_count": (
            output_validation.target_count if output_validation is not None else None
        ),
        "output_missing_target_count": (
            output_validation.missing_target_count if output_validation is not None else None
        ),
        "output_original": output,
        "output_final": output_final,
        "output_final_source": output_final_source,
        "output_repair_required": repair_required,
        "output_repair_attempted": repair_result.attempted,
        "output_repair_count": repair_result.repair_count,
        "output_repair_status": repair_result.status,
        "output_repair_missing_targets_before": list(
            repair_result.missing_targets_before
        ),
        "output_repair_missing_targets_after": list(
            repair_result.missing_targets_after
        ),
        "output_repair_used_same_context": repair_result.used_same_context,
        "output_repair_added_tokens": repair_result.added_tokens,
        "output_repair_added_latency_ms": repair_result.added_latency_ms,
        "output_repair_added_estimated_cost": repair_result.added_estimated_cost,
        "output_repair_error": repair_result.error,
        "output_repair_prompt_tokens": repair_result.prompt_tokens,
        "output_repair_output_tokens": repair_result.output_tokens,
        "output_repair_total_tokens": repair_result.total_tokens,
        "output_repaired_text": repair_result.repaired_text,
        "question": task.question,
        "selected_block_id": route["selected_block_id"],
        "fixture_selected_block_id": fixture_selected_block_id,
        "router_selected_block_id": (
            route.get("router_selected_block_id") if mode == "spatial_router" else None
        ),
        "router_selection_matches_fixture": (
            route.get("router_selection_matches_fixture") if mode == "spatial_router" else None
        ),
        "router_success": route.get("router_success") if mode == "spatial_router" else None,
        "router_valid_selection": (
            route.get("router_valid_selection") if mode == "spatial_router" else None
        ),
        "executor_used_fallback": (
            route.get("executor_used_fallback") if mode == "spatial_router" else False
        ),
        "success_with_fallback": bool(
            mode == "spatial_router"
            and route.get("executor_used_fallback")
            and not error
            and validation["passed"]
        ),
        "router_latency_ms": router_latency_ms if mode == "spatial_router" else None,
        "router_input_tokens": route.get("router_input_tokens") if mode == "spatial_router" else None,
        "router_output_tokens": route.get("router_output_tokens") if mode == "spatial_router" else None,
        "router_total_tokens": router_total_tokens if mode == "spatial_router" else None,
        "router_end_to_end_total_tokens": (
            int(tokens["total_tokens"]) + router_total_tokens
            if mode == "spatial_router" and router_total_tokens is not None
            else None
        ),
        "router_end_to_end_latency_ms": (
            latency_ms + router_latency_ms
            if mode == "spatial_router" and router_latency_ms is not None
            else None
        ),
        "router_error": route.get("router_error") if mode == "spatial_router" else None,
        "router_confidence": route.get("router_confidence") if mode == "spatial_router" else None,
        "router_reason": route.get("router_reason") if mode == "spatial_router" else None,
        "selection_verification_required": (
            route.get("selection_verification_required") if mode == "spatial_router" else None
        ),
        "selection_verification_status": (
            route.get("selection_verification_status") if mode == "spatial_router" else None
        ),
        "selection_contains_all_targets": (
            route.get("selection_contains_all_targets") if mode == "spatial_router" else None
        ),
        "selection_present_targets": (
            route.get("selection_present_targets") if mode == "spatial_router" else None
        ),
        "selection_missing_targets": (
            route.get("selection_missing_targets") if mode == "spatial_router" else None
        ),
        "selection_target_count": (
            route.get("selection_target_count") if mode == "spatial_router" else None
        ),
        "selection_missing_target_count": (
            route.get("selection_missing_target_count") if mode == "spatial_router" else None
        ),
        "selection_source": route.get("selection_source"),
        "used_block_ids": used_blocks,
        "used_block_count": len(used_blocks),
        "available_block_count": len(task.blocks),
        "context_reduced": mode != "baseline" and len(used_blocks) < len(task.blocks),
        "notes": (
            f"{route['notes']}; used_blocks={','.join(used_blocks)}; "
            f"dry_run={dry_run}; base_url={base_url}"
        ),
        "output": output,
    }


def build_prompt(
    task: LargeContextualTask,
    mode: str,
    route: dict[str, Any],
    task_tier: str | None = None,
) -> str:
    block_ids = block_ids_for_mode(task, mode, route)
    blocks = [block for block in task.blocks if block.block_id in block_ids]
    context = "\n\n".join(format_block(block) for block in blocks)
    structural_schema = _structural_executor_schema(task, task_tier)
    return (
        "/no_think\n"
        "Answer using only the provided context blocks. Do not use outside facts. "
        "Return a concise final answer and include the block id that supports it. "
        "Preserve exact identifiers, labels, dataset names, policy names, status "
        "tags, and hyphenated markers from the context; copy requested values "
        "verbatim instead of paraphrasing them.\n\n"
        f"{structural_schema}"
        f"Benchmark: {BENCHMARK_TYPE}\n"
        f"Mode: {mode}\n"
        f"Question: {task.question}\n\n"
        "Context blocks:\n"
        f"{context}\n\n"
        "Final answer:"
    )


def _structural_executor_schema(
    task: LargeContextualTask,
    task_tier: str | None,
) -> str:
    if not _uses_structural_executor_schema(task, task_tier):
        return ""
    return (
        "Structural answer format:\n"
        "- Return the answer as explicit field lines using these field names: "
        "active_version, rollback_threshold, excluded_dataset, "
        "final_approval_owner, mitigation_label, evidence_block_id.\n"
        "- Fill every field from the selected context block. Do not omit the active version "
        "when the question names one.\n"
        "- The evidence_block_id value must be the BLOCK id that contains the values.\n\n"
    )


def _uses_structural_executor_schema(
    task: LargeContextualTask,
    task_tier: str | None,
) -> bool:
    if task_tier is not None:
        return normalize_task_tier(task_tier) == TASK_TIER_STRUCTURAL
    return "structural_record_navigation" in task.difficulty_patterns


def block_ids_for_mode(
    task: LargeContextualTask, mode: str, route: dict[str, Any]
) -> list[str]:
    if mode == "baseline":
        return [block.block_id for block in task.blocks]
    if mode in ("spatial", "spatial_fixture", "spatial_router"):
        return [str(route["selected_block_id"])]
    raise ValueError(f"Unknown mode: {mode}")


def format_block(block: ContextBlock) -> str:
    return f"BLOCK {block.block_id} - {block.title}\n{block.text}"


def validate_output(task: LargeContextualTask, output: str) -> dict[str, Any]:
    normalized = output.lower()
    checks = [
        {
            "target": target,
            "passed": str(target).lower() in normalized,
        }
        for target in task.validation_targets
    ]
    return {
        "passed": bool(output.strip()) and all(check["passed"] for check in checks),
        "checks": checks,
    }


def summarize_runs(
    runs: list[dict[str, Any]], task_tier: str | None = None
) -> dict[str, Any]:
    if not runs:
        raise ValueError("At least one run is required for summary reporting.")

    modes = _modes_in_runs(runs)
    by_mode = {mode: [run for run in runs if run["mode"] == mode] for mode in modes}
    summary: dict[str, Any] = {"modes": {}}
    for mode, mode_runs in by_mode.items():
        summary["modes"][mode] = {
            "run_count": len(mode_runs),
            "average_input_tokens": average(run["input_tokens"] for run in mode_runs),
            "average_output_tokens": average(run["output_tokens"] for run in mode_runs),
            "average_total_tokens": average(run["total_tokens"] for run in mode_runs),
            "average_latency_ms": average(run["latency_ms"] for run in mode_runs),
            "success_rate": success_rate(mode_runs),
        }

    baseline = summary["modes"]["baseline"]
    comparison_mode = _primary_spatial_mode(modes)
    spatial = summary["modes"][comparison_mode]
    summary["token_reduction_percent"] = percent_reduction(
        baseline["average_input_tokens"], spatial["average_input_tokens"]
    )
    summary["input_token_reduction_by_mode"] = {
        mode: percent_reduction(baseline["average_input_tokens"], data["average_input_tokens"])
        for mode, data in summary["modes"].items()
        if mode != "baseline"
    }
    summary["token_accounting"] = summarize_token_accounting(runs)
    summary["latency_delta_ms"] = (
        spatial["average_latency_ms"] - baseline["average_latency_ms"]
    )
    summary["context_reduction_verified"] = all(
        run["used_block_count"] == 1 for run in runs if run["mode"] != "baseline"
    ) and all(
        run["used_block_count"] > 1 for run in runs if run["mode"] == "baseline"
    )
    router_runs = [run for run in runs if run["mode"] == "spatial_router"]
    summary["router_selection"] = summarize_router_selection(router_runs)
    summary["output_validation"] = summarize_output_validation(runs)
    summary["output_repair"] = summarize_output_repair(runs)
    if task_tier is not None and normalize_task_tier(task_tier) == TASK_TIER_STRUCTURAL:
        summary["structural_reliability_cost"] = (
            summarize_structural_reliability_cost(runs)
        )
    summary["final_phase_conclusion"] = FINAL_PHASE_CONCLUSION
    return summary


def summarize_per_task(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = sorted({run["task_label"] for run in runs})
    modes = _modes_in_runs(runs)
    comparison_mode = _primary_spatial_mode(modes)
    rows = []
    for label in labels:
        task_runs = [run for run in runs if run["task_label"] == label]
        baseline = [run for run in task_runs if run["mode"] == "baseline"]
        spatial = [run for run in task_runs if run["mode"] == comparison_mode]
        router = [run for run in task_runs if run["mode"] == "spatial_router"]
        token_accounting = summarize_token_accounting(task_runs)
        rows.append(
            {
                "task_label": label,
                "baseline_average_input_tokens": average(
                    run["input_tokens"] for run in baseline
                ),
                "spatial_average_input_tokens": average(
                    run["input_tokens"] for run in spatial
                ),
                "token_reduction_percent": percent_reduction(
                    average(run["input_tokens"] for run in baseline),
                    average(run["input_tokens"] for run in spatial),
                ),
                "baseline_success_rate": success_rate(baseline),
                "spatial_success_rate": success_rate(spatial),
                "selected_block_id": spatial[0]["selected_block_id"] if spatial else "",
                "spatial_used_blocks": spatial[0]["used_block_ids"] if spatial else [],
                "fixture_selected_block_id": (
                    baseline[0]["fixture_selected_block_id"] if baseline else ""
                ),
                "router_selected_block_id": (
                    router[0]["router_selected_block_id"] if router else None
                ),
                "router_selection_matches_fixture": (
                    router[0]["router_selection_matches_fixture"] if router else None
                ),
                "router_valid_selection": (
                    router[0]["router_valid_selection"] if router else None
                ),
                "executor_used_fallback": (
                    router[0]["executor_used_fallback"] if router else None
                ),
                "selection_verification_status": (
                    router[0].get("selection_verification_status") if router else None
                ),
                "selection_contains_all_targets": (
                    router[0].get("selection_contains_all_targets") if router else None
                ),
                "selection_missing_targets": (
                    router[0].get("selection_missing_targets") if router else None
                ),
                "output_validation_status": (
                    router[0].get("output_validation_status") if router else None
                ),
                "output_contains_all_targets": (
                    router[0].get("output_contains_all_targets") if router else None
                ),
                "output_missing_targets": (
                    router[0].get("output_missing_targets") if router else None
                ),
                "output_repair_status": (
                    router[0].get("output_repair_status") if router else None
                ),
                "success_after_output_repair": (
                    router[0].get("success_after_output_repair") if router else None
                ),
                "token_accounting": token_accounting,
                "baseline_average_output_tokens": token_accounting[
                    "baseline_average_output_tokens"
                ],
                "input_token_delta": token_accounting["input_token_delta"],
                "input_token_reduction_percent": token_accounting[
                    "input_token_reduction_percent"
                ],
                "spatial_average_output_tokens": token_accounting[
                    "selected_executor_average_output_tokens"
                ],
                "router_inclusive_average_output_tokens": token_accounting[
                    "router_inclusive_average_output_tokens"
                ],
                "output_token_delta": token_accounting["output_token_delta"],
                "output_token_ratio": token_accounting["output_token_ratio"],
                "total_token_delta": token_accounting["total_token_delta"],
                "total_token_reduction_percent": token_accounting[
                    "total_token_reduction_percent"
                ],
                "output_tokens_reduced": token_accounting["output_tokens_reduced"],
                "output_tokens_increased": token_accounting["output_tokens_increased"],
                "total_tokens_reduced": token_accounting["total_tokens_reduced"],
                "output_expansion_offsets_input_reduction": token_accounting[
                    "output_expansion_offsets_input_reduction"
                ],
            }
        )
    return rows


def summarize_token_accounting(runs: list[dict[str, Any]]) -> dict[str, Any]:
    modes = _modes_in_runs(runs)
    baseline_runs = [run for run in runs if run["mode"] == "baseline"]
    comparison_mode = "spatial_router" if "spatial_router" in modes else _primary_spatial_mode(modes)
    selected_executor_runs = [
        run for run in runs if run["mode"] == comparison_mode
    ]
    router_runs = [run for run in runs if run["mode"] == "spatial_router"]

    baseline = _average_token_triplet(baseline_runs)
    selected_executor = _average_token_triplet(selected_executor_runs)
    router = _average_token_triplet(
        router_runs,
        input_key="router_input_tokens",
        output_key="router_output_tokens",
        total_key="router_total_tokens",
    )
    router_inclusive = _router_inclusive_average_token_triplet(
        selected_executor_runs,
        router_runs,
    )

    input_delta = _optional_difference(
        router_inclusive["average_input_tokens"],
        baseline["average_input_tokens"],
    )
    output_delta = _optional_difference(
        router_inclusive["average_output_tokens"],
        baseline["average_output_tokens"],
    )
    total_delta = _optional_difference(
        router_inclusive["average_total_tokens"],
        baseline["average_total_tokens"],
    )
    return {
        "comparison_mode": comparison_mode,
        "baseline_average_input_tokens": baseline["average_input_tokens"],
        "baseline_average_output_tokens": baseline["average_output_tokens"],
        "baseline_average_total_tokens": baseline["average_total_tokens"],
        "selected_executor_average_input_tokens": selected_executor[
            "average_input_tokens"
        ],
        "selected_executor_average_output_tokens": selected_executor[
            "average_output_tokens"
        ],
        "selected_executor_average_total_tokens": selected_executor[
            "average_total_tokens"
        ],
        "router_average_input_tokens": router["average_input_tokens"],
        "router_average_output_tokens": router["average_output_tokens"],
        "router_average_total_tokens": router["average_total_tokens"],
        "router_inclusive_average_input_tokens": router_inclusive[
            "average_input_tokens"
        ],
        "router_inclusive_average_output_tokens": router_inclusive[
            "average_output_tokens"
        ],
        "router_inclusive_average_total_tokens": router_inclusive[
            "average_total_tokens"
        ],
        "input_token_delta": input_delta,
        "input_token_reduction_percent": _optional_percent_reduction(
            baseline["average_input_tokens"],
            router_inclusive["average_input_tokens"],
        ),
        "output_token_delta": output_delta,
        "output_token_ratio": _optional_ratio(
            router_inclusive["average_output_tokens"],
            baseline["average_output_tokens"],
        ),
        "total_token_delta": total_delta,
        "total_token_reduction_percent": _optional_percent_reduction(
            baseline["average_total_tokens"],
            router_inclusive["average_total_tokens"],
        ),
        "output_tokens_reduced": (
            output_delta < 0 if output_delta is not None else None
        ),
        "output_tokens_increased": (
            output_delta > 0 if output_delta is not None else None
        ),
        "total_tokens_reduced": (
            total_delta < 0 if total_delta is not None else None
        ),
        "output_expansion_offsets_input_reduction": (
            input_delta is not None
            and output_delta is not None
            and input_delta < 0
            and output_delta > 0
        ),
    }


def summarize_output_repair(runs: list[dict[str, Any]]) -> dict[str, Any]:
    required = [run for run in runs if run.get("output_repair_required") is True]
    attempted = [run for run in runs if run.get("output_repair_attempted") is True]
    attempted_complete = [
        run
        for run in attempted
        if run.get("output_repair_status") == OUTPUT_REPAIR_STATUS_ATTEMPTED_COMPLETE
    ]
    attempted_incomplete = [
        run
        for run in attempted
        if run.get("output_repair_status") == OUTPUT_REPAIR_STATUS_ATTEMPTED_INCOMPLETE
    ]
    skipped_selection_incomplete = [
        run
        for run in runs
        if run.get("output_repair_status")
        == OUTPUT_REPAIR_STATUS_SKIPPED_SELECTION_INCOMPLETE
    ]
    disabled = [
        run
        for run in runs
        if run.get("output_repair_status") == OUTPUT_REPAIR_STATUS_DISABLED
    ]
    added_tokens = [
        int(run["output_repair_added_tokens"])
        for run in attempted
        if run.get("output_repair_added_tokens") is not None
    ]
    added_latency_ms = [
        int(run["output_repair_added_latency_ms"])
        for run in attempted
        if run.get("output_repair_added_latency_ms") is not None
    ]
    return {
        "required_count": len(required),
        "attempted_count": len(attempted),
        "completed_count": len(attempted_complete),
        "incomplete_count": len(attempted_incomplete),
        "skipped_selection_incomplete_count": len(skipped_selection_incomplete),
        "disabled_count": len(disabled),
        "added_total_tokens": sum(added_tokens),
        "added_latency_ms": sum(added_latency_ms),
    }


def summarize_structural_reliability_cost(runs: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_runs = [run for run in runs if run["mode"] == "baseline"]
    router_runs = [run for run in runs if run["mode"] == "spatial_router"]
    router_success = (
        all(run.get("router_success") is True for run in router_runs)
        if router_runs
        else None
    )
    selector_fallback_used = (
        any(run.get("executor_used_fallback") is True for run in router_runs)
        if router_runs
        else None
    )
    verified_selection_complete = (
        all(run.get("selection_verification_status") == "complete" for run in router_runs)
        if router_runs
        else None
    )
    output_validation_complete = (
        all(run.get("output_validation_status") == "complete" for run in router_runs)
        if router_runs
        else None
    )
    route_honesty_conditions_met = bool(
        router_runs
        and router_success is True
        and selector_fallback_used is False
        and verified_selection_complete is True
    )
    honest_structural_pass = bool(
        route_honesty_conditions_met
        and output_validation_complete is True
        and all(bool(run.get("success")) for run in router_runs)
    )
    repair_required = (
        any(run.get("output_repair_required") is True for run in router_runs)
        if router_runs
        else None
    )
    attempted_repairs_complete = bool(
        router_runs
        and repair_required is True
        and all(
            run.get("output_repair_status")
            in (
                OUTPUT_REPAIR_STATUS_ATTEMPTED_COMPLETE,
                OUTPUT_REPAIR_STATUS_NOT_REQUIRED,
            )
            for run in router_runs
        )
    )
    honest_structural_pass_after_repair = bool(
        route_honesty_conditions_met
        and not honest_structural_pass
        and attempted_repairs_complete
        and all(bool(run.get("success_after_output_repair")) for run in router_runs)
    )
    baseline_total_tokens = _optional_average(
        run.get("total_tokens") for run in baseline_runs
    )
    spatial_router_router_tokens = _optional_average(
        run.get("router_total_tokens") for run in router_runs
    )
    spatial_router_executor_tokens = _optional_average(
        run.get("total_tokens") for run in router_runs
    )
    spatial_router_total_tokens = _optional_average(
        run.get("router_end_to_end_total_tokens") for run in router_runs
    )
    output_repair_added_tokens = _optional_average(
        run.get("output_repair_added_tokens") for run in router_runs
    )
    spatial_router_total_tokens_after_repair = _optional_sum(
        spatial_router_total_tokens,
        output_repair_added_tokens,
    )
    tokens_saved_before_repair_vs_baseline = _optional_difference(
        baseline_total_tokens,
        spatial_router_total_tokens,
    )
    tokens_saved_after_repair_vs_baseline = _optional_difference(
        baseline_total_tokens,
        spatial_router_total_tokens_after_repair,
    )
    return {
        "run_count": len(router_runs),
        "baseline_total_tokens": baseline_total_tokens,
        "spatial_router_total_tokens": spatial_router_total_tokens,
        "spatial_router_router_tokens": spatial_router_router_tokens,
        "spatial_router_executor_tokens": spatial_router_executor_tokens,
        "output_repair_added_tokens": output_repair_added_tokens,
        "spatial_router_total_tokens_after_repair": (
            spatial_router_total_tokens_after_repair
        ),
        "tokens_saved_before_repair_vs_baseline": (
            tokens_saved_before_repair_vs_baseline
        ),
        "tokens_saved_after_repair_vs_baseline": (
            tokens_saved_after_repair_vs_baseline
        ),
        "token_reduction_before_repair_vs_baseline_pct": (
            _optional_percent_reduction(
                baseline_total_tokens,
                spatial_router_total_tokens,
            )
        ),
        "token_reduction_after_repair_vs_baseline_pct": (
            _optional_percent_reduction(
                baseline_total_tokens,
                spatial_router_total_tokens_after_repair,
            )
        ),
        "repair_token_tax": output_repair_added_tokens,
        "repair_token_tax_pct_of_router_executor": _optional_ratio_percent(
            output_repair_added_tokens,
            spatial_router_total_tokens,
        ),
        "raw_executor_success": all(bool(run.get("success")) for run in router_runs)
        if router_runs
        else None,
        "repaired_success": all(
            bool(run.get("success_after_output_repair")) for run in router_runs
        )
        if router_runs
        else None,
        "router_success": router_success,
        "selector_fallback_used": selector_fallback_used,
        "verified_selection_complete": verified_selection_complete,
        "output_validation_complete": output_validation_complete,
        "output_repair_required": repair_required,
        "honest_structural_pass": honest_structural_pass if router_runs else None,
        "honest_structural_pass_after_repair": (
            honest_structural_pass_after_repair if router_runs else None
        ),
        "publication_gate": "honest_structural_pass",
        "success": all(bool(run.get("success")) for run in router_runs)
        if router_runs
        else None,
        "success_after_output_repair": all(
            bool(run.get("success_after_output_repair")) for run in router_runs
        )
        if router_runs
        else None,
    }


def summarize_output_validation(runs: list[dict[str, Any]]) -> dict[str, Any]:
    required = [run for run in runs if run.get("output_validation_required") is True]
    if not required:
        return {
            "required_count": 0,
            "complete_count": 0,
            "incomplete_count": 0,
            "complete_rate": None,
            "missing_target_counts": {},
        }
    complete = [
        run for run in required if run.get("output_contains_all_targets") is True
    ]
    incomplete = [
        run for run in required if run.get("output_contains_all_targets") is False
    ]
    missing_target_counts: dict[str, int] = {}
    for run in incomplete:
        for target in run.get("output_missing_targets") or []:
            missing_target_counts[str(target)] = missing_target_counts.get(str(target), 0) + 1
    return {
        "required_count": len(required),
        "complete_count": len(complete),
        "incomplete_count": len(incomplete),
        "complete_rate": len(complete) / len(required),
        "missing_target_counts": dict(sorted(missing_target_counts.items())),
    }


def summarize_router_selection(router_runs: list[dict[str, Any]]) -> dict[str, Any]:
    if not router_runs:
        return {
            "run_count": 0,
            "success_rate": None,
            "valid_selection_rate": None,
            "fallback_count": 0,
            "fallback_rate": None,
            "match_rate": None,
            "match_rate_valid_selections": None,
            "average_latency_ms": None,
            "average_total_tokens": None,
            "average_end_to_end_total_tokens": None,
            "average_end_to_end_latency_ms": None,
            "verification_required_count": 0,
            "verified_complete_count": 0,
            "verified_incomplete_count": 0,
            "verified_complete_rate": None,
        }
    matched = [
        run for run in router_runs if run.get("router_selection_matches_fixture") is True
    ]
    successful = [run for run in router_runs if run.get("router_success") is True]
    valid = [run for run in router_runs if run.get("router_valid_selection") is True]
    valid_matched = [
        run for run in valid if run.get("router_selection_matches_fixture") is True
    ]
    fallback_runs = [run for run in router_runs if run.get("executor_used_fallback") is True]
    total_tokens = [
        int(run["router_total_tokens"])
        for run in router_runs
        if run.get("router_total_tokens") is not None
    ]
    end_to_end_tokens = [
        int(run["router_end_to_end_total_tokens"])
        for run in router_runs
        if run.get("router_end_to_end_total_tokens") is not None
    ]
    end_to_end_latencies = [
        int(run["router_end_to_end_latency_ms"])
        for run in router_runs
        if run.get("router_end_to_end_latency_ms") is not None
    ]
    latencies = [
        int(run["router_latency_ms"])
        for run in router_runs
        if run.get("router_latency_ms") is not None
    ]
    verification_required = [
        run for run in router_runs if run.get("selection_verification_required") is True
    ]
    verified_complete = [
        run for run in verification_required if run.get("selection_contains_all_targets") is True
    ]
    verified_incomplete = [
        run for run in verification_required if run.get("selection_contains_all_targets") is False
    ]
    return {
        "run_count": len(router_runs),
        "success_rate": len(successful) / len(router_runs),
        "valid_selection_rate": len(valid) / len(router_runs),
        "fallback_count": len(fallback_runs),
        "fallback_rate": len(fallback_runs) / len(router_runs),
        "match_rate": len(matched) / len(router_runs),
        "match_rate_valid_selections": (
            len(valid_matched) / len(valid) if valid else None
        ),
        "average_latency_ms": average(latencies),
        "average_total_tokens": average(total_tokens),
        "average_end_to_end_total_tokens": average(end_to_end_tokens),
        "average_end_to_end_latency_ms": average(end_to_end_latencies),
        "verification_required_count": len(verification_required),
        "verified_complete_count": len(verified_complete),
        "verified_incomplete_count": len(verified_incomplete),
        "verified_complete_rate": (
            len(verified_complete) / len(verification_required)
            if verification_required
            else None
        ),
    }


def _modes_in_runs(runs: list[dict[str, Any]]) -> list[str]:
    order = ("baseline", "spatial", "spatial_fixture", "spatial_router")
    present = {run["mode"] for run in runs}
    return [mode for mode in order if mode in present]


def _primary_spatial_mode(modes: list[str]) -> str:
    if "spatial" in modes:
        return "spatial"
    if "spatial_fixture" in modes:
        return "spatial_fixture"
    if "spatial_router" in modes:
        return "spatial_router"
    raise ValueError("No spatial mode found.")


def estimate_tokens(text: str) -> int:
    return estimate_text_tokens(text)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_average(values: Any) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return average(numbers) if numbers else None


def _optional_sum(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left + right


def _optional_difference(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    return left - right


def _optional_percent_reduction(
    baseline: float | None, reduced: float | None
) -> float | None:
    if baseline is None or reduced is None:
        return None
    return percent_reduction(baseline, reduced)


def _optional_ratio_percent(
    numerator: float | None, denominator: float | None
) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return (numerator / denominator) * 100.0


def _optional_ratio(
    numerator: float | None, denominator: float | None
) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _average_token_triplet(
    runs: list[dict[str, Any]],
    *,
    input_key: str = "input_tokens",
    output_key: str = "output_tokens",
    total_key: str = "total_tokens",
) -> dict[str, float | None]:
    return {
        "average_input_tokens": _optional_average(run.get(input_key) for run in runs),
        "average_output_tokens": _optional_average(run.get(output_key) for run in runs),
        "average_total_tokens": _optional_average(run.get(total_key) for run in runs),
    }


def _router_inclusive_average_token_triplet(
    selected_executor_runs: list[dict[str, Any]],
    router_runs: list[dict[str, Any]],
) -> dict[str, float | None]:
    if not router_runs:
        return _average_token_triplet(selected_executor_runs)

    return {
        "average_input_tokens": _optional_average(
            _optional_sum(run.get("input_tokens"), run.get("router_input_tokens"))
            for run in router_runs
        ),
        "average_output_tokens": _optional_average(
            _optional_sum(run.get("output_tokens"), run.get("router_output_tokens"))
            for run in router_runs
        ),
        "average_total_tokens": _optional_average(
            _optional_sum(run.get("total_tokens"), run.get("router_total_tokens"))
            for run in router_runs
        ),
    }


def deterministic_latency_ms(task_label: str, mode: str, input_tokens: int) -> int:
    mode_offset = 45 if mode == "spatial" else 90
    label_offset = sum(ord(char) for char in task_label) % 37
    return mode_offset + label_offset + int(input_tokens / 20)


def task_to_dict(task: LargeContextualTask) -> dict[str, Any]:
    data = asdict(task)
    data["estimated_full_prompt_tokens"] = estimate_tokens(
        build_prompt(task, "baseline", select_relevant_block(task))
    )
    data["estimated_spatial_prompt_tokens"] = estimate_tokens(
        build_prompt(task, "spatial", select_relevant_block(task))
    )
    return data


def write_json(path: Path, report: dict[str, Any]) -> None:
    write_json_report(path, report)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    modes = list(report["summary"]["modes"])
    lines = [
        "# Large Contextual Benchmark",
        "",
        f"Benchmark type: `{BENCHMARK_TYPE}`",
        f"Executor: `{report['metadata']['executor']}`",
        f"API style: `{report['metadata'].get('api_style')}`",
        f"Executor model: `{report['metadata'].get('executor_model')}`",
        f"Router model: `{report['metadata'].get('router_model')}`",
        f"Base URL: `{report['metadata'].get('base_url')}`",
        f"Router: `{report['metadata']['router']}`",
        f"Selection mode: `{report['metadata']['selection_mode']}`",
        f"Task tier: `{report['metadata']['task_tier']}` ({report['metadata']['task_tier_description']})",
        f"Dry run: `{report['metadata']['dry_run']}`",
        f"Provider call delay seconds: `{report['metadata'].get('provider_call_delay_seconds', 0.0)}`",
        "",
        "## Summary",
        "",
        "| Mode | Runs | Avg input tokens | Avg output tokens | Avg total tokens | Avg latency ms | Success rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for mode in modes:
        mode_summary = report["summary"]["modes"][mode]
        lines.append(
            f"| `{mode}` | {mode_summary['run_count']} | "
            f"{mode_summary['average_input_tokens']:.2f} | "
            f"{mode_summary['average_output_tokens']:.2f} | "
            f"{mode_summary['average_total_tokens']:.2f} | "
            f"{mode_summary['average_latency_ms']:.2f} | "
            f"{mode_summary['success_rate']:.2%} |"
        )

    reduction = report["summary"]["token_reduction_percent"]
    reduction_text = "n/a" if reduction is None else f"{reduction:.2f}%"
    lines.extend(
        [
            "",
            f"Input token reduction: {reduction_text}",
            f"Context reduction verified: `{report['summary']['context_reduction_verified']}`",
            f"Output validation required runs: {report['summary']['output_validation']['required_count']}",
            f"Output validation complete runs: {report['summary']['output_validation']['complete_count']}",
            f"Output validation incomplete runs: {report['summary']['output_validation']['incomplete_count']}",
            f"Output validation complete rate: {_format_optional_percent(report['summary']['output_validation']['complete_rate'])}",
            f"Output repair required runs: {report['summary']['output_repair']['required_count']}",
            f"Output repair attempted runs: {report['summary']['output_repair']['attempted_count']}",
            f"Output repair completed runs: {report['summary']['output_repair']['completed_count']}",
            f"Output repair incomplete runs: {report['summary']['output_repair']['incomplete_count']}",
            f"Output repair skipped selection-incomplete runs: {report['summary']['output_repair']['skipped_selection_incomplete_count']}",
            f"Output repair disabled runs: {report['summary']['output_repair']['disabled_count']}",
            f"Output repair added total tokens: {report['summary']['output_repair']['added_total_tokens']}",
            f"Output repair added latency ms: {report['summary']['output_repair']['added_latency_ms']}",
        ]
    )
    token_accounting = report["summary"].get("token_accounting")
    if token_accounting is not None:
        lines.extend(
            [
                "",
                "## Token Accounting",
                "",
                "| Scope | Avg input tokens | Avg output tokens | Avg total tokens |",
                "| --- | ---: | ---: | ---: |",
                (
                    "| Baseline | "
                    f"{_format_optional_number(token_accounting['baseline_average_input_tokens'])} | "
                    f"{_format_optional_number(token_accounting['baseline_average_output_tokens'])} | "
                    f"{_format_optional_number(token_accounting['baseline_average_total_tokens'])} |"
                ),
                (
                    "| Selected executor | "
                    f"{_format_optional_number(token_accounting['selected_executor_average_input_tokens'])} | "
                    f"{_format_optional_number(token_accounting['selected_executor_average_output_tokens'])} | "
                    f"{_format_optional_number(token_accounting['selected_executor_average_total_tokens'])} |"
                ),
                (
                    "| Router | "
                    f"{_format_optional_number(token_accounting['router_average_input_tokens'])} | "
                    f"{_format_optional_number(token_accounting['router_average_output_tokens'])} | "
                    f"{_format_optional_number(token_accounting['router_average_total_tokens'])} |"
                ),
                (
                    "| Router-inclusive | "
                    f"{_format_optional_number(token_accounting['router_inclusive_average_input_tokens'])} | "
                    f"{_format_optional_number(token_accounting['router_inclusive_average_output_tokens'])} | "
                    f"{_format_optional_number(token_accounting['router_inclusive_average_total_tokens'])} |"
                ),
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Input token delta | {_format_optional_number(token_accounting['input_token_delta'])} |",
                f"| Input token reduction | {_format_optional_percent_value(token_accounting['input_token_reduction_percent'])} |",
                f"| Output token delta | {_format_optional_number(token_accounting['output_token_delta'])} |",
                f"| Output token ratio | {_format_optional_number(token_accounting['output_token_ratio'])} |",
                f"| Total token delta | {_format_optional_number(token_accounting['total_token_delta'])} |",
                f"| Total token reduction | {_format_optional_percent_value(token_accounting['total_token_reduction_percent'])} |",
                f"| Output tokens reduced | {_format_optional_bool(token_accounting['output_tokens_reduced'])} |",
                f"| Output tokens increased | {_format_optional_bool(token_accounting['output_tokens_increased'])} |",
                f"| Total tokens reduced | {_format_optional_bool(token_accounting['total_tokens_reduced'])} |",
                f"| Output expansion offsets input reduction | {_format_optional_bool(token_accounting['output_expansion_offsets_input_reduction'])} |",
            ]
        )
    structural_cost = report["summary"].get("structural_reliability_cost")
    if structural_cost is not None:
        lines.extend(
            [
                "",
                "## Structural Reliability Cost",
                "",
                "| Metric | Value |",
                "| --- | ---: |",
                f"| Baseline total tokens | {_format_optional_number(structural_cost['baseline_total_tokens'])} |",
                f"| Spatial router total tokens | {_format_optional_number(structural_cost['spatial_router_total_tokens'])} |",
                f"| Spatial router router tokens | {_format_optional_number(structural_cost['spatial_router_router_tokens'])} |",
                f"| Spatial router executor tokens | {_format_optional_number(structural_cost['spatial_router_executor_tokens'])} |",
                f"| Output repair added tokens | {_format_optional_number(structural_cost['output_repair_added_tokens'])} |",
                f"| Spatial router total tokens after repair | {_format_optional_number(structural_cost['spatial_router_total_tokens_after_repair'])} |",
                f"| Tokens saved before repair vs baseline | {_format_optional_number(structural_cost['tokens_saved_before_repair_vs_baseline'])} |",
                f"| Tokens saved after repair vs baseline | {_format_optional_number(structural_cost['tokens_saved_after_repair_vs_baseline'])} |",
                f"| Token reduction before repair vs baseline | {_format_optional_percent_value(structural_cost['token_reduction_before_repair_vs_baseline_pct'])} |",
                f"| Token reduction after repair vs baseline | {_format_optional_percent_value(structural_cost['token_reduction_after_repair_vs_baseline_pct'])} |",
                f"| Repair token tax | {_format_optional_number(structural_cost['repair_token_tax'])} |",
                f"| Repair token tax pct of router+executor | {_format_optional_percent_value(structural_cost['repair_token_tax_pct_of_router_executor'])} |",
                f"| Raw executor success | {_format_optional_bool(structural_cost['raw_executor_success'])} |",
                f"| Repaired success | {_format_optional_bool(structural_cost['repaired_success'])} |",
                f"| Router success | {_format_optional_bool(structural_cost['router_success'])} |",
                f"| Selector fallback used | {_format_optional_bool(structural_cost['selector_fallback_used'])} |",
                f"| Verified selection complete | {_format_optional_bool(structural_cost['verified_selection_complete'])} |",
                f"| Output validation complete before repair | {_format_optional_bool(structural_cost['output_validation_complete'])} |",
                f"| Output repair required | {_format_optional_bool(structural_cost['output_repair_required'])} |",
                f"| Honest structural pass | {_format_optional_bool(structural_cost['honest_structural_pass'])} |",
                f"| Honest structural pass after repair | {_format_optional_bool(structural_cost['honest_structural_pass_after_repair'])} |",
                f"| Publication gate | `{structural_cost['publication_gate']}` |",
                f"| Success | {_format_optional_bool(structural_cost['success'])} |",
                f"| Success after output repair | {_format_optional_bool(structural_cost['success_after_output_repair'])} |",
            ]
        )
    lines.extend(
        [
            "",
            "## Router Selection",
            "",
            f"Router run count: {report['summary']['router_selection']['run_count']}",
            f"Router success rate: {_format_optional_percent(report['summary']['router_selection']['success_rate'])}",
            f"Valid router selection rate: {_format_optional_percent(report['summary']['router_selection']['valid_selection_rate'])}",
            f"Router selection match rate: {_format_optional_percent(report['summary']['router_selection']['match_rate'])}",
            f"Router match rate among valid selections: {_format_optional_percent(report['summary']['router_selection']['match_rate_valid_selections'])}",
            f"Fallback-assisted executor runs: {report['summary']['router_selection']['fallback_count']}",
            f"Fallback-assisted executor rate: {_format_optional_percent(report['summary']['router_selection']['fallback_rate'])}",
            f"Selection verification required runs: {report['summary']['router_selection']['verification_required_count']}",
            f"Verified complete selections: {report['summary']['router_selection']['verified_complete_count']}",
            f"Verified incomplete selections: {report['summary']['router_selection']['verified_incomplete_count']}",
            f"Verified complete selection rate: {_format_optional_percent(report['summary']['router_selection']['verified_complete_rate'])}",
            f"Average router latency ms: {_format_optional_number(report['summary']['router_selection']['average_latency_ms'])}",
            f"Average router total tokens: {_format_optional_number(report['summary']['router_selection']['average_total_tokens'])}",
            f"Average router+executor total tokens: {_format_optional_number(report['summary']['router_selection']['average_end_to_end_total_tokens'])}",
            f"Average router+executor latency ms: {_format_optional_number(report['summary']['router_selection']['average_end_to_end_latency_ms'])}",
            "",
            "## Per Task",
            "",
            "| Task | Baseline input | Spatial input | Input delta | Input reduction | Baseline output | Router-inclusive output | Output delta | Output ratio | Total delta | Total reduction | Output increased | Total reduced | Offset | Fixture block | Router block | Router valid | Router match | Fallback |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in report["per_task"]:
        router_block = row["router_selected_block_id"] or "n/a"
        router_match = (
            "n/a"
            if row["router_selection_matches_fixture"] is None
            else str(bool(row["router_selection_matches_fixture"]))
        )
        router_valid = (
            "n/a"
            if row["router_valid_selection"] is None
            else str(bool(row["router_valid_selection"]))
        )
        fallback = (
            "n/a"
            if row["executor_used_fallback"] is None
            else str(bool(row["executor_used_fallback"]))
        )
        lines.append(
            f"| `{row['task_label']}` | {row['baseline_average_input_tokens']:.2f} | "
            f"{row['spatial_average_input_tokens']:.2f} | "
            f"{_format_optional_number(row['input_token_delta'])} | "
            f"{_format_optional_percent_value(row['input_token_reduction_percent'])} | "
            f"{_format_optional_number(row['baseline_average_output_tokens'])} | "
            f"{_format_optional_number(row['router_inclusive_average_output_tokens'])} | "
            f"{_format_optional_number(row['output_token_delta'])} | "
            f"{_format_optional_number(row['output_token_ratio'])} | "
            f"{_format_optional_number(row['total_token_delta'])} | "
            f"{_format_optional_percent_value(row['total_token_reduction_percent'])} | "
            f"{_format_optional_bool(row['output_tokens_increased'])} | "
            f"{_format_optional_bool(row['total_tokens_reduced'])} | "
            f"{_format_optional_bool(row['output_expansion_offsets_input_reduction'])} | "
            f"`{row['fixture_selected_block_id']}` | `{router_block}` | "
            f"{router_valid} | {router_match} | {fallback} |"
        )

    router_runs = [run for run in report["runs"] if run["mode"] == "spatial_router"]
    if router_runs:
        lines.extend(
            [
                "",
                "## Router Details",
                "",
                "| Task | Fixture block | Router block | Valid | Match | Fallback | Selection verification | Selection missing targets | Output validation | Output missing targets | Output repair | Success after repair | Confidence | Reason | Error |",
                "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |",
            ]
        )
        for run in router_runs:
            router_block = run.get("router_selected_block_id") or "n/a"
            confidence = run.get("router_confidence")
            confidence_text = (
                "n/a" if confidence is None else f"{float(confidence):.2f}"
            )
            verification_status = run.get("selection_verification_status") or "n/a"
            missing_targets = ", ".join(run.get("selection_missing_targets") or []) or "n/a"
            output_validation_status = run.get("output_validation_status") or "n/a"
            output_missing_targets = ", ".join(run.get("output_missing_targets") or []) or "n/a"
            output_repair_status = run.get("output_repair_status") or "n/a"
            success_after_repair = run.get("success_after_output_repair")
            success_after_repair_text = (
                "n/a" if success_after_repair is None else str(bool(success_after_repair))
            )
            lines.append(
                f"| `{run['task_label']}` | `{run['fixture_selected_block_id']}` | "
                f"`{router_block}` | {bool(run['router_valid_selection'])} | "
                f"{bool(run['router_selection_matches_fixture'])} | "
                f"{bool(run['executor_used_fallback'])} | "
                f"{_markdown_cell(verification_status)} | "
                f"{_markdown_cell(missing_targets)} | "
                f"{_markdown_cell(output_validation_status)} | "
                f"{_markdown_cell(output_missing_targets)} | "
                f"{_markdown_cell(output_repair_status)} | "
                f"{success_after_repair_text} | {confidence_text} | "
                f"{_markdown_cell(run.get('router_reason') or '')} | "
                f"{_markdown_cell(run.get('router_error') or '')} |"
            )

    lines.extend(["", "## Conclusion", "", FINAL_PHASE_CONCLUSION, ""])
    write_text_report(path, "\n".join(lines))


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    reduction = report["summary"]["token_reduction_percent"]
    reduction_text = "n/a" if reduction is None else f"{reduction:.2f}%"
    print("Large/contextual benchmark")
    print(
        f"task tier: {report['metadata']['task_tier']} "
        f"({report['metadata']['task_tier_description']})"
    )
    print(f"runs: {report['metadata']['run_count']}")
    print(f"context reduction verified: {report['summary']['context_reduction_verified']}")
    print(f"input token reduction: {reduction_text}")
    output_validation = report["summary"]["output_validation"]
    if output_validation["required_count"]:
        print(
            "output validation complete rate: "
            f"{_format_optional_percent(output_validation['complete_rate'])}"
        )
    output_repair = report["summary"]["output_repair"]
    if output_repair["required_count"] or output_repair["attempted_count"]:
        print(f"output repair attempted runs: {output_repair['attempted_count']}")
        print(f"output repair completed runs: {output_repair['completed_count']}")
    structural_cost = report["summary"].get("structural_reliability_cost")
    if structural_cost is not None:
        print(
            "honest structural pass: "
            f"{_format_optional_bool(structural_cost['honest_structural_pass'])}"
        )
        print(
            "honest structural pass after repair: "
            f"{_format_optional_bool(structural_cost['honest_structural_pass_after_repair'])}"
        )
    router_selection = report["summary"]["router_selection"]
    if router_selection["run_count"]:
        print(f"router selection match rate: {_format_optional_percent(router_selection['match_rate'])}")
        print(f"router valid selection rate: {_format_optional_percent(router_selection['valid_selection_rate'])}")
        print(f"fallback-assisted executor runs: {router_selection['fallback_count']}")
        if router_selection["verification_required_count"]:
            print(
                "verified complete selection rate: "
                f"{_format_optional_percent(router_selection['verified_complete_rate'])}"
            )
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


def _format_optional_percent(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2%}"


def _format_optional_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def _format_optional_percent_value(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}%"


def _format_optional_bool(value: bool | None) -> str:
    if value is None:
        return "n/a"
    return str(bool(value))


def _markdown_cell(value: object) -> str:
    text = str(value).replace("\n", " ").replace("|", "\\|").strip()
    return text or "n/a"


if __name__ == "__main__":
    main()
