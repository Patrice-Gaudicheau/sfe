"""Backend adapter stubs for the SFE-aware TUI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any, Protocol

from sfe.execution_backend import (
    DirectExecutionPreview,
    ExecutionBackend,
    ExecutionResult,
    RouterPreviewDiagnostics,
)
from sfe.contracts import ContextSegment, SFEContract
from sfe.multipass import MultiPassBatch, MultiPassPlan
from .executors import ExecutorResponse, ReadOnlyExecutor, create_tui_executor
from .routers import (
    LOCAL_LEXICAL_PREVIEW_MODE,
    LocalSegmentRouter,
)


MISSING_TASK = "missing_task"
FULL_FILE_REPLACEMENT_PREFERRED_MAX_BYTES = 64_000


class BackendAdapter(ExecutionBackend, Protocol):
    def run(self, contract: SFEContract) -> ExecutionResult:
        ...


class DirectBackend:
    name = "direct"

    def __init__(self, executor: ReadOnlyExecutor | None = None) -> None:
        self.executor = executor or create_tui_executor()

    @property
    def executor_provider_name(self) -> str | None:
        return getattr(self.executor, "provider_name", None)

    def dry_run(self, contract: SFEContract) -> ExecutionResult:
        return _local_router_preview_result(self.name, contract)

    def console(self, contract: SFEContract) -> ExecutionResult:
        routed = self.dry_run(contract)
        if contract.task is None:
            return console_error_result(routed, "missing_task")
        if routed.execution_preview is None:
            return console_error_result(routed, "invalid_execution_preview")
        executor_response = self.executor.answer_console(
            routed.execution_preview.executor_payload
        )
        return _console_result_from_executor_response(routed, executor_response)

    def run(self, contract: SFEContract) -> ExecutionResult:
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

    def patch(self, contract: SFEContract) -> ExecutionResult:
        routed = self.dry_run(contract)
        if contract.task is None:
            return patch_error_result(routed, "missing_task")
        if (
            contract.context_segments
            and (
                routed.execution_preview is None
                or not routed.execution_preview.selected_segment_ids
            )
        ):
            return patch_error_result(routed, "no_selected_context")
        if routed.execution_preview is None:
            return patch_error_result(routed, "invalid_execution_preview")
        executor_response = self.executor.propose_patch(
            routed.execution_preview.executor_payload
        )
        result = _patch_result_from_executor_response(routed, executor_response)
        return _with_full_file_replacement_guidance_summary(
            result,
            routed.execution_preview.executor_payload,
        )

    def patch_multipass_batch(
        self,
        contract: SFEContract,
        *,
        plan: MultiPassPlan,
        batch: MultiPassBatch,
        completed_files: tuple[str, ...],
    ) -> ExecutionResult:
        routed = self.dry_run(contract)
        if contract.task is None:
            return patch_error_result(routed, "missing_task")
        if routed.execution_preview is None:
            return patch_error_result(routed, "invalid_execution_preview")
        current_allowed_file_context = _current_file_context(
            contract,
            batch.allowed_files,
        )
        full_file_replacement_guidance = _full_file_replacement_guidance(
            contract,
            candidate_files=batch.allowed_files,
        )
        executor_payload = {
            **routed.execution_preview.executor_payload,
            "multi_pass": {
                "mode": "batch",
                "project_summary": plan.project_summary,
                "batch_id": batch.id,
                "batch_title": batch.title,
                "batch_goal": batch.goal,
                "allowed_files": batch.allowed_files,
                "depends_on": batch.depends_on,
                "validation_notes": batch.validation_notes,
                "completed_files": completed_files,
                "current_allowed_file_context": current_allowed_file_context,
                "full_file_replacement_guidance": full_file_replacement_guidance,
            },
            "full_file_replacement_guidance": full_file_replacement_guidance,
        }
        executor_response = self.executor.propose_patch(executor_payload)
        result = _patch_result_from_executor_response(routed, executor_response)
        return _with_full_file_replacement_guidance_summary(result, executor_payload)


def backend_by_name(name: str) -> BackendAdapter:
    normalized = name.strip().lower()
    if normalized == "direct":
        return DirectBackend()
    raise ValueError("unsupported_backend")


def ask_error_result(result: ExecutionResult, error_category: str) -> ExecutionResult:
    return ExecutionResult(
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


def console_error_result(result: ExecutionResult, error_category: str) -> ExecutionResult:
    return ExecutionResult(
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


def patch_error_result(result: ExecutionResult, error_category: str) -> ExecutionResult:
    return ExecutionResult(
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
    routed: ExecutionResult,
    executor_response: ExecutorResponse,
) -> ExecutionResult:
    status = "console_completed" if executor_response.answer else "console_failed"
    return ExecutionResult(
        backend=routed.backend,
        status=status,
        provider_calls_made=executor_response.provider_calls_made,
        summary={
            **routed.summary,
            "provider_calls_made": executor_response.provider_calls_made,
            "console_error_category": executor_response.error_category,
            "executor_provider": executor_response.provider_name,
            **_executor_response_diagnostics_summary(executor_response),
        },
        contract=routed.contract,
        execution_preview=routed.execution_preview,
        router_preview=routed.router_preview,
        answer=executor_response.answer,
        error_category=executor_response.error_category,
    )


def _ask_result_from_executor_response(
    routed: ExecutionResult,
    executor_response: ExecutorResponse,
) -> ExecutionResult:
    status = "ask_completed" if executor_response.answer else "ask_failed"
    return ExecutionResult(
        backend=routed.backend,
        status=status,
        provider_calls_made=executor_response.provider_calls_made,
        summary={
            **routed.summary,
            "provider_calls_made": executor_response.provider_calls_made,
            "ask_error_category": executor_response.error_category,
            "executor_provider": executor_response.provider_name,
            **_executor_response_diagnostics_summary(executor_response),
        },
        contract=routed.contract,
        execution_preview=routed.execution_preview,
        router_preview=routed.router_preview,
        answer=executor_response.answer,
        error_category=executor_response.error_category,
    )


def _patch_result_from_executor_response(
    routed: ExecutionResult,
    executor_response: ExecutorResponse,
) -> ExecutionResult:
    status = "patch_proposed" if executor_response.answer else "patch_failed"
    return ExecutionResult(
        backend=routed.backend,
        status=status,
        provider_calls_made=executor_response.provider_calls_made,
        summary={
            **routed.summary,
            "provider_calls_made": executor_response.provider_calls_made,
            "patch_error_category": executor_response.error_category,
            "patch_applied": False,
            "executor_provider": executor_response.provider_name,
            **_executor_response_diagnostics_summary(executor_response),
        },
        contract=routed.contract,
        execution_preview=routed.execution_preview,
        router_preview=routed.router_preview,
        answer=executor_response.answer,
        error_category=executor_response.error_category,
    )


def _executor_response_diagnostics_summary(
    executor_response: ExecutorResponse,
) -> dict[str, object]:
    if executor_response.response_diagnostics is None:
        return {}
    return {"executor_response_diagnostics": executor_response.response_diagnostics}


def _with_full_file_replacement_guidance_summary(
    result: ExecutionResult,
    executor_payload: dict[str, Any],
) -> ExecutionResult:
    guidance = executor_payload.get("full_file_replacement_guidance")
    if not isinstance(guidance, Mapping):
        return result
    return replace(
        result,
        summary={
            **result.summary,
            "full_file_replacement_guidance": dict(guidance),
        },
    )


def _full_file_replacement_guidance(
    contract: SFEContract,
    *,
    candidate_files: tuple[str, ...] | None = None,
) -> dict[str, object]:
    allowed = set(candidate_files) if candidate_files is not None else None
    full_content_files: list[str] = []
    eligible_files: list[str] = []
    documentation_files: list[str] = []
    source_files: list[str] = []
    template_files: list[str] = []
    large_files: list[str] = []
    file_sizes: dict[str, int] = {}
    for segment in contract.context_segments:
        path = segment.source_ref
        if allowed is not None and path not in allowed:
            continue
        if not segment.text:
            continue
        size = len(segment.text.encode("utf-8"))
        full_content_files.append(path)
        file_sizes[path] = size
        if size <= FULL_FILE_REPLACEMENT_PREFERRED_MAX_BYTES:
            eligible_files.append(path)
            if _is_documentation_full_file_preferred_path(path):
                documentation_files.append(path)
            if _is_source_full_file_preferred_path(path):
                source_files.append(path)
            if _is_template_full_file_preferred_path(path):
                template_files.append(path)
        else:
            large_files.append(path)
    return {
        "max_bytes": FULL_FILE_REPLACEMENT_PREFERRED_MAX_BYTES,
        "full_content_provided_files": tuple(full_content_files),
        "eligible_files": tuple(eligible_files),
        "documentation_files": tuple(documentation_files),
        "source_files": tuple(source_files),
        "template_files": tuple(template_files),
        "large_files": tuple(large_files),
        "file_sizes": file_sizes,
    }


def _is_documentation_full_file_preferred_path(path: str) -> bool:
    pure = Path(path)
    name = pure.name.lower()
    if name in {"readme.md", "changelog.md", "contributing.md", "license"}:
        return True
    if pure.suffix.lower() == ".md":
        return True
    parts = tuple(part.lower() for part in pure.parts)
    return len(parts) >= 2 and parts[0] == "docs" and pure.suffix.lower() == ".md"


def _is_source_full_file_preferred_path(path: str) -> bool:
    pure = Path(path)
    parts = tuple(part.lower() for part in pure.parts)
    suffix = pure.suffix.lower()
    if suffix not in {".php", ".py", ".js", ".jsx", ".ts", ".tsx"}:
        return False
    if not parts:
        return False
    if parts[0] == "tests":
        return True
    if len(parts) >= 2 and parts[0] == "src":
        return parts[1] in {
            "controller",
            "entity",
            "form",
            "repository",
            "service",
            "security",
            "validator",
        }
    return False


def _is_template_full_file_preferred_path(path: str) -> bool:
    pure = Path(path)
    parts = tuple(part.lower() for part in pure.parts)
    return len(parts) >= 2 and parts[0] == "templates" and pure.suffix.lower() == ".twig"


def _current_file_context(
    contract: SFEContract,
    allowed_files: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    allowed = set(allowed_files)
    return tuple(
        {"path": segment.source_ref, "text": segment.text}
        for segment in contract.context_segments
        if segment.source_ref in allowed and segment.text
    )


def _local_router_preview_result(name: str, contract: SFEContract) -> ExecutionResult:
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
) -> ExecutionResult:
    return ExecutionResult(
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
            "executor_working_directory": contract.metadata.get("workspace_root"),
            "full_file_replacement_guidance": _full_file_replacement_guidance(
                replace(contract, context_segments=selected_segments)
            ),
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
