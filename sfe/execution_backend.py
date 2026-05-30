"""Core-owned execution backend interface for SFE run pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sfe.contracts import SFEContract


@dataclass(frozen=True)
class DirectExecutionPreview:
    backend_name: str
    selector_mode: str
    protected_instruction_count: int
    task_present: bool
    selected_segment_ids: list[str]
    selected_segment_count: int
    selected_context_char_count: int
    selected_context_token_estimate: int
    total_context_char_count: int
    total_context_token_estimate: int
    estimated_reduction_pct: float | None
    fallback_reason: str | None
    provider_calls_made: int
    writes_enabled: bool
    shell_enabled: bool
    executor_payload: dict[str, Any]


@dataclass(frozen=True)
class RouterPreviewDiagnostics:
    router_mode: str
    router_available: bool
    router_unavailable_reason: str | None
    router_provider_calls_made: int
    input_segment_count: int
    eligible_segment_count: int
    selected_segment_count: int
    selected_segment_ids: list[str]
    router_input_segment_ids: list[str]
    estimated_input_tokens: int
    estimated_selected_tokens: int
    estimated_reduction_pct: float | None
    fallback_reason: str | None
    score_category_counts: dict[str, int]
    score_categories_by_segment_id: dict[str, str]


@dataclass(frozen=True)
class ExecutionResult:
    backend: str
    status: str
    provider_calls_made: int
    summary: dict[str, object]
    contract: SFEContract
    execution_preview: DirectExecutionPreview | None = None
    router_preview: RouterPreviewDiagnostics | None = None
    answer: str | None = None
    error_category: str | None = None


class ExecutionBackend(Protocol):
    name: str

    def console(self, contract: SFEContract) -> ExecutionResult:
        ...

    def dry_run(self, contract: SFEContract) -> ExecutionResult:
        ...

    def patch(self, contract: SFEContract) -> ExecutionResult:
        ...

    def patch_repair(
        self,
        contract: SFEContract,
        *,
        repair_instruction: str,
    ) -> ExecutionResult:
        ...
