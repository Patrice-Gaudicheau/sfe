"""Backend adapter stubs for the SFE-aware TUI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol

from .contracts import ContextSegment, SFEContract
from .executors import ExecutorResponse, ReadOnlyExecutor, create_tui_executor
from .routers import (
    LOCAL_LEXICAL_PREVIEW_MODE,
    LocalSegmentRouter,
)


MISSING_TASK = "missing_task"


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
class BackendResult:
    backend: str
    status: str
    provider_calls_made: int
    summary: dict[str, object]
    contract: SFEContract
    execution_preview: DirectExecutionPreview | None = None
    router_preview: RouterPreviewDiagnostics | None = None
    answer: str | None = None
    error_category: str | None = None


class BackendAdapter(Protocol):
    name: str

    def console(self, contract: SFEContract) -> BackendResult:
        ...

    def dry_run(self, contract: SFEContract) -> BackendResult:
        ...

    def run(self, contract: SFEContract) -> BackendResult:
        ...

    def patch(self, contract: SFEContract) -> BackendResult:
        ...


class DirectBackend:
    name = "direct"

    def __init__(self, executor: ReadOnlyExecutor | None = None) -> None:
        self.executor = executor or create_tui_executor()

    @property
    def executor_provider_name(self) -> str | None:
        return getattr(self.executor, "provider_name", None)

    def dry_run(self, contract: SFEContract) -> BackendResult:
        return _local_router_preview_result(self.name, contract)

    def console(self, contract: SFEContract) -> BackendResult:
        routed = self.dry_run(contract)
        if contract.task is None:
            return console_error_result(routed, "missing_task")
        if routed.execution_preview is None:
            return console_error_result(routed, "invalid_execution_preview")
        executor_response = self.executor.answer_console(
            routed.execution_preview.executor_payload
        )
        return _console_result_from_executor_response(routed, executor_response)

    def run(self, contract: SFEContract) -> BackendResult:
        routed = self.dry_run(contract)
        if contract.task is None:
            return ask_error_result(routed, "missing_task")
        if not contract.context_segments:
            return ask_error_result(routed, "no_context_loaded")
        if (
            routed.execution_preview is None
            or not routed.execution_preview.selected_segment_ids
        ):
            return ask_error_result(routed, "no_selected_context")
        executor_response = self.executor.execute(
            routed.execution_preview.executor_payload
        )
        return _ask_result_from_executor_response(routed, executor_response)

    def patch(self, contract: SFEContract) -> BackendResult:
        routed = self.dry_run(contract)
        if contract.task is None:
            return patch_error_result(routed, "missing_task")
        if not contract.context_segments:
            return patch_error_result(routed, "no_context_loaded")
        if (
            routed.execution_preview is None
            or not routed.execution_preview.selected_segment_ids
        ):
            return patch_error_result(routed, "no_selected_context")
        executor_response = self.executor.propose_patch(
            routed.execution_preview.executor_payload
        )
        return _patch_result_from_executor_response(routed, executor_response)


class ProxyBackend:
    name = "proxy"

    def dry_run(self, contract: SFEContract) -> BackendResult:
        return _dry_run_result(self.name, contract, selector_mode="proxy_not_connected")

    def console(self, contract: SFEContract) -> BackendResult:
        raise NotImplementedError("Proxy backend console execution is not implemented yet.")

    def run(self, contract: SFEContract) -> BackendResult:
        raise NotImplementedError("Proxy backend execution is not implemented yet.")

    def patch(self, contract: SFEContract) -> BackendResult:
        raise NotImplementedError("Proxy backend patching is not implemented yet.")


def backend_by_name(name: str) -> BackendAdapter:
    normalized = name.strip().lower()
    if normalized == "direct":
        return DirectBackend()
    if normalized == "proxy":
        return ProxyBackend()
    raise ValueError("unsupported_backend")


def ask_error_result(result: BackendResult, error_category: str) -> BackendResult:
    return BackendResult(
        backend=result.backend,
        status="ask_failed",
        provider_calls_made=0,
        summary={**result.summary, "ask_error_category": error_category},
        contract=result.contract,
        execution_preview=result.execution_preview,
        router_preview=result.router_preview,
        answer=None,
        error_category=error_category,
    )


def console_error_result(result: BackendResult, error_category: str) -> BackendResult:
    return BackendResult(
        backend=result.backend,
        status="console_failed",
        provider_calls_made=0,
        summary={**result.summary, "console_error_category": error_category},
        contract=result.contract,
        execution_preview=result.execution_preview,
        router_preview=result.router_preview,
        answer=None,
        error_category=error_category,
    )


def patch_error_result(result: BackendResult, error_category: str) -> BackendResult:
    return BackendResult(
        backend=result.backend,
        status="patch_failed",
        provider_calls_made=0,
        summary={**result.summary, "patch_error_category": error_category},
        contract=result.contract,
        execution_preview=result.execution_preview,
        router_preview=result.router_preview,
        answer=None,
        error_category=error_category,
    )


def _console_result_from_executor_response(
    routed: BackendResult,
    executor_response: ExecutorResponse,
) -> BackendResult:
    status = "console_completed" if executor_response.answer else "console_failed"
    return BackendResult(
        backend=routed.backend,
        status=status,
        provider_calls_made=executor_response.provider_calls_made,
        summary={
            **routed.summary,
            "provider_calls_made": executor_response.provider_calls_made,
            "console_error_category": executor_response.error_category,
            "executor_provider": executor_response.provider_name,
        },
        contract=routed.contract,
        execution_preview=routed.execution_preview,
        router_preview=routed.router_preview,
        answer=executor_response.answer,
        error_category=executor_response.error_category,
    )


def _ask_result_from_executor_response(
    routed: BackendResult,
    executor_response: ExecutorResponse,
) -> BackendResult:
    status = "ask_completed" if executor_response.answer else "ask_failed"
    return BackendResult(
        backend=routed.backend,
        status=status,
        provider_calls_made=executor_response.provider_calls_made,
        summary={
            **routed.summary,
            "provider_calls_made": executor_response.provider_calls_made,
            "ask_error_category": executor_response.error_category,
            "executor_provider": executor_response.provider_name,
        },
        contract=routed.contract,
        execution_preview=routed.execution_preview,
        router_preview=routed.router_preview,
        answer=executor_response.answer,
        error_category=executor_response.error_category,
    )


def _patch_result_from_executor_response(
    routed: BackendResult,
    executor_response: ExecutorResponse,
) -> BackendResult:
    status = "patch_proposed" if executor_response.answer else "patch_failed"
    return BackendResult(
        backend=routed.backend,
        status=status,
        provider_calls_made=executor_response.provider_calls_made,
        summary={
            **routed.summary,
            "provider_calls_made": executor_response.provider_calls_made,
            "patch_error_category": executor_response.error_category,
            "patch_applied": False,
            "executor_provider": executor_response.provider_name,
        },
        contract=routed.contract,
        execution_preview=routed.execution_preview,
        router_preview=routed.router_preview,
        answer=executor_response.answer,
        error_category=executor_response.error_category,
    )


def _local_router_preview_result(name: str, contract: SFEContract) -> BackendResult:
    task_text = contract.task.text if contract.task is not None else ""
    router_result = LocalSegmentRouter().route(task_text, contract.context_segments)
    selected_segment_ids = router_result.selected_segment_ids
    selected_segment_count = router_result.selected_segment_count
    estimated_selected_tokens = router_result.estimated_selected_tokens
    estimated_reduction_pct = router_result.estimated_reduction_pct
    fallback_reason = router_result.fallback_reason
    if contract.task is None:
        selected_segment_ids = []
        selected_segment_count = 0
        estimated_selected_tokens = 0
        estimated_reduction_pct = None
        fallback_reason = MISSING_TASK
    segments_by_id = {segment.id: segment for segment in contract.context_segments}
    selected_segments = [
        segments_by_id[segment_id]
        for segment_id in selected_segment_ids
        if segment_id in segments_by_id
    ]
    audit = {
        **contract.audit,
        "selected_segment_ids": selected_segment_ids,
        "selector_mode": LOCAL_LEXICAL_PREVIEW_MODE,
        "router_mode": router_result.router_mode,
        "router_available": router_result.router_available,
        "router_unavailable_reason": None,
        "router_provider_calls_made": router_result.provider_calls_made,
        "router_input_segment_ids": router_result.router_input_segment_ids,
        "router_score_category_counts": router_result.score_category_counts,
        "router_score_categories_by_segment_id": (
            router_result.score_categories_by_segment_id
        ),
        "fallback_reason": fallback_reason,
        "input_segment_count": router_result.input_segment_count,
        "eligible_segment_count": router_result.eligible_segment_count,
        "selected_segment_count": selected_segment_count,
        "estimated_input_tokens": router_result.estimated_input_tokens,
        "estimated_selected_tokens": estimated_selected_tokens,
        "estimated_reduction_pct": estimated_reduction_pct,
        "provider_calls_made": 0,
    }
    updated = replace(contract, audit=audit)
    execution_preview = _build_execution_preview(
        name=name,
        contract=updated,
        selected_segments=selected_segments,
    )
    router_preview = _build_router_preview(updated)
    return _dry_run_result(
        name,
        updated,
        selector_mode=LOCAL_LEXICAL_PREVIEW_MODE,
        execution_preview=execution_preview,
        router_preview=router_preview,
    )


def _dry_run_result(
    name: str,
    contract: SFEContract,
    *,
    selector_mode: str,
    execution_preview: DirectExecutionPreview | None = None,
    router_preview: RouterPreviewDiagnostics | None = None,
) -> BackendResult:
    return BackendResult(
        backend=name,
        status="dry_run_only",
        provider_calls_made=0,
        summary={
            "context_segment_count": len(contract.context_segments),
            "protected_segment_count": len(contract.protected_segments),
            "reducible_segment_count": contract.metadata["reducible_segment_count"],
            "protected_instruction_count": contract.metadata[
                "protected_instruction_count"
            ],
            "task_present": contract.task is not None,
            "selector_mode": selector_mode,
            "selected_segment_ids": contract.audit.get("selected_segment_ids", []),
            "fallback_reason": contract.audit.get("fallback_reason"),
            "input_segment_count": contract.audit.get("input_segment_count"),
            "eligible_segment_count": contract.audit.get("eligible_segment_count"),
            "selected_segment_count": contract.audit.get("selected_segment_count"),
            "estimated_input_tokens": contract.audit.get("estimated_input_tokens"),
            "estimated_selected_tokens": contract.audit.get("estimated_selected_tokens"),
            "estimated_reduction_pct": contract.audit.get("estimated_reduction_pct"),
            "router_available": contract.audit.get("router_available"),
            "router_unavailable_reason": contract.audit.get(
                "router_unavailable_reason"
            ),
            "router_provider_calls_made": contract.audit.get(
                "router_provider_calls_made"
            ),
            "router_score_category_counts": contract.audit.get(
                "router_score_category_counts"
            ),
        },
        contract=contract,
        execution_preview=execution_preview,
        router_preview=router_preview,
    )


def _build_execution_preview(
    *,
    name: str,
    contract: SFEContract,
    selected_segments: list[ContextSegment],
) -> DirectExecutionPreview:
    selected_ids = [segment.id for segment in selected_segments]
    selected_chars = sum(segment.approx_size for segment in selected_segments)
    selected_tokens = sum(segment.approx_tokens for segment in selected_segments)
    total_chars = int(contract.metadata.get("total_approx_context_chars") or 0)
    total_tokens = int(contract.metadata.get("total_approx_context_tokens") or 0)
    return DirectExecutionPreview(
        backend_name=name,
        selector_mode=str(contract.audit.get("selector_mode") or ""),
        protected_instruction_count=len(contract.instructions),
        task_present=contract.task is not None,
        selected_segment_ids=selected_ids,
        selected_segment_count=len(selected_segments),
        selected_context_char_count=selected_chars,
        selected_context_token_estimate=selected_tokens,
        total_context_char_count=total_chars,
        total_context_token_estimate=total_tokens,
        estimated_reduction_pct=contract.audit.get("estimated_reduction_pct"),
        fallback_reason=contract.audit.get("fallback_reason"),
        provider_calls_made=0,
        writes_enabled=False,
        shell_enabled=False,
        executor_payload={
            "instructions": contract.instructions,
            "task": contract.task,
            "selected_context_segments": selected_segments,
        },
    )


def _build_router_preview(contract: SFEContract) -> RouterPreviewDiagnostics:
    return RouterPreviewDiagnostics(
        router_mode=str(contract.audit.get("router_mode") or LOCAL_LEXICAL_PREVIEW_MODE),
        router_available=bool(contract.audit.get("router_available")),
        router_unavailable_reason=contract.audit.get("router_unavailable_reason"),
        router_provider_calls_made=int(
            contract.audit.get("router_provider_calls_made") or 0
        ),
        input_segment_count=int(contract.audit.get("input_segment_count") or 0),
        eligible_segment_count=int(contract.audit.get("eligible_segment_count") or 0),
        selected_segment_count=int(contract.audit.get("selected_segment_count") or 0),
        selected_segment_ids=list(contract.audit.get("selected_segment_ids") or []),
        router_input_segment_ids=list(
            contract.audit.get("router_input_segment_ids") or []
        ),
        estimated_input_tokens=int(contract.audit.get("estimated_input_tokens") or 0),
        estimated_selected_tokens=int(
            contract.audit.get("estimated_selected_tokens") or 0
        ),
        estimated_reduction_pct=contract.audit.get("estimated_reduction_pct"),
        fallback_reason=contract.audit.get("fallback_reason"),
        score_category_counts=dict(
            contract.audit.get("router_score_category_counts") or {}
        ),
        score_categories_by_segment_id=dict(
            contract.audit.get("router_score_categories_by_segment_id") or {}
        ),
    )
