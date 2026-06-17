"""Bounded Real Loop controller for verified workspace_write retries."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sfe.execution_mode_router import (
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
    ExecutionModeRouter,
    ExecutionModeRouterError,
)
from sfe.run_pipeline import (
    RUN_STATUS_COMPLETED,
    RunProgressCallback,
    RunProgressEvent,
    RunResult,
)
from sfe.workspace_isolation import WorkspaceSession
from sfe.real_loop_verifier import (
    RealLoopVerifier,
    RealLoopVerifierDecision,
    RealLoopVerifierRequest,
    create_configured_real_loop_verifier,
)


DEFAULT_REAL_LOOP_MODE = "auto"
DEFAULT_REAL_LOOP_MAX_ITERATIONS = 3
DEFAULT_REAL_LOOP_ABORT_ON_NO_PROGRESS = True
DEFAULT_REAL_LOOP_ABORT_ON_DUPLICATE_RETRY_TASK = True
DEFAULT_REAL_LOOP_DIFF_MAX_CHARS = 40_000
DEFAULT_REAL_LOOP_FILE_PREVIEW_MAX_CHARS = 12_000
REAL_LOOP_EXECUTOR_FAILURE_MESSAGE = (
    "Loop Stopped: Executor failed. Try a stronger model for Executor "
    "(SFE_PROVIDER_EXECUTOR in the file .env)"
)

REAL_LOOP_STATUS_VERIFIED_PASS = "verified_pass"
REAL_LOOP_STATUS_BLOCKED = "blocked"
REAL_LOOP_STATUS_ABORTED = "aborted"
REAL_LOOP_STATUS_MAX_ITERATIONS = "max_iterations"
REAL_LOOP_STATUS_RETRY_FAILED = "retry_failed"
REAL_LOOP_STATUS_VERIFIER_FAILED = "verifier_failed"
REAL_LOOP_STATUS_VERIFIER_UNAVAILABLE = "verifier_unavailable"


@dataclass(frozen=True)
class RealLoopConfig:
    mode: str = DEFAULT_REAL_LOOP_MODE
    max_iterations: int = DEFAULT_REAL_LOOP_MAX_ITERATIONS
    abort_on_no_progress: bool = DEFAULT_REAL_LOOP_ABORT_ON_NO_PROGRESS
    abort_on_duplicate_retry_task: bool = (
        DEFAULT_REAL_LOOP_ABORT_ON_DUPLICATE_RETRY_TASK
    )
    diff_max_chars: int = DEFAULT_REAL_LOOP_DIFF_MAX_CHARS
    file_preview_max_chars: int = DEFAULT_REAL_LOOP_FILE_PREVIEW_MAX_CHARS

    @property
    def disabled(self) -> bool:
        return self.mode == "false"

    @property
    def forced(self) -> bool:
        return self.mode == "true"


@dataclass(frozen=True)
class RealLoopRouteDecision:
    execution_mode: str | None
    reason: str | None = None
    provider_name: str | None = None
    model: str | None = None
    provider_calls_made: int = 0
    error_category: str | None = None


@dataclass(frozen=True)
class RealLoopIterationSummary:
    iteration_index: int
    task: str
    run_status: str
    execution_mode: str | None
    changed_files: tuple[str, ...]
    promoted_files: tuple[str, ...]
    llm_verifier_verdict: str | None = None
    retry_worthwhile: bool | None = None
    progress_since_previous_iteration: str | None = None
    repeated_failure: bool | None = None
    failure_category: str | None = None
    detected_issues: tuple[str, ...] = ()
    correction_objective: str | None = None
    executor_retry_task: str | None = None
    files_or_areas_to_focus: tuple[str, ...] = ()
    reason: str | None = None
    stop_reason: str | None = None
    verifier_provider: str | None = None
    verifier_model: str | None = None
    verifier_issue_category: str | None = None
    verifier_issue_reason: str | None = None
    verifier_schema_validation_reason: str | None = None
    verifier_raw_answer_preview: str | None = None


@dataclass(frozen=True)
class RealLoopRunSummary:
    enabled: bool
    real_loop_status: str
    attempts_total: int
    max_iterations: int
    llm_verifier_verdict: str | None = None
    retry_worthwhile: bool | None = None
    stop_reason: str | None = None
    progress_since_previous_iteration: str | None = None
    detected_issues: tuple[str, ...] = ()
    executor_retry_task: str | None = None
    verifier_provider: str | None = None
    verifier_model: str | None = None
    reason: str | None = None
    iterations: tuple[RealLoopIterationSummary, ...] = ()


RunAttempt = Callable[[str, WorkspaceSession | None], RunResult]
RouteCorrectionTask = Callable[[str], RealLoopRouteDecision]


class RealLoopController:
    def __init__(
        self,
        *,
        config: RealLoopConfig | None = None,
        verifier: RealLoopVerifier | None = None,
        progress_callback: RunProgressCallback | None = None,
    ) -> None:
        self.config = config or resolve_real_loop_config()
        self.verifier = verifier or create_configured_real_loop_verifier()
        self.progress_callback = progress_callback

    def run(
        self,
        *,
        initial_result: RunResult,
        original_task: str,
        run_attempt: RunAttempt,
        route_correction_task: RouteCorrectionTask,
    ) -> RunResult:
        if self.config.disabled:
            return initial_result
        if not _is_completed_workspace_write(initial_result):
            return initial_result
        if not self.verifier.is_available():
            if self.config.forced:
                return _with_real_loop_summary(
                    initial_result,
                    self._summary(
                        status=REAL_LOOP_STATUS_VERIFIER_UNAVAILABLE,
                        attempts_total=1,
                        stop_reason="verifier_not_configured",
                        reason="Real Loop verifier is not available.",
                        iterations=(
                            _iteration_from_result(
                                initial_result,
                                iteration_index=1,
                                task=original_task,
                            ),
                        ),
                    ),
                )
            return initial_result

        attempts: list[RunResult] = [initial_result]
        iterations: list[RealLoopIterationSummary] = []
        previous_retry_tasks: list[str] = []
        previous_failure_categories: list[str] = []
        current_result = initial_result
        current_task = original_task
        current_session = initial_result.workspace_session

        for attempt_index in range(1, self.config.max_iterations + 1):
            if attempt_index > 1 and not current_result.promoted_files:
                iterations.append(
                    _iteration_from_result(
                        current_result,
                        iteration_index=attempt_index,
                        task=current_task,
                        stop_reason="executor_produced_no_relevant_workspace_changes",
                    )
                )
                return _with_real_loop_summary(
                    current_result,
                    self._summary(
                        status=REAL_LOOP_STATUS_ABORTED,
                        attempts_total=len(attempts),
                        stop_reason="executor_produced_no_relevant_workspace_changes",
                        reason=REAL_LOOP_EXECUTOR_FAILURE_MESSAGE,
                        iterations=tuple(iterations),
                    ),
                )

            self._emit_progress(
                "real_loop_verification_started",
                f"SFE: Real Loop verification started: attempt {attempt_index}",
                real_loop_attempt=attempt_index,
            )
            verifier_response = self.verifier.verify(
                RealLoopVerifierRequest(
                    original_task=original_task,
                    current_task=current_task,
                    attempt_index=attempt_index,
                    max_iterations=self.config.max_iterations,
                    previous_retry_tasks=tuple(previous_retry_tasks),
                    previous_failure_categories=tuple(previous_failure_categories),
                    run_result=_run_result_payload(current_result),
                    workspace_snapshot=build_real_loop_workspace_snapshot(
                        current_result,
                        self.config,
                    ),
                )
            )
            if verifier_response.issue is not None or verifier_response.decision is None:
                issue = verifier_response.issue
                iterations.append(
                    _iteration_from_result(
                        current_result,
                        iteration_index=attempt_index,
                        task=current_task,
                        stop_reason=issue.reason if issue is not None else "verifier_failed",
                        verifier_issue=issue,
                        verifier_raw_answer=verifier_response.raw_answer,
                    )
                )
                return _with_real_loop_summary(
                    current_result,
                    self._summary(
                        status=REAL_LOOP_STATUS_VERIFIER_FAILED,
                        attempts_total=len(attempts),
                        stop_reason=issue.reason if issue is not None else "verifier_failed",
                        reason="Real Loop verifier failed to produce a usable decision.",
                        iterations=tuple(iterations),
                    ),
                )

            decision = verifier_response.decision
            iterations.append(
                _iteration_from_result(
                    current_result,
                    iteration_index=attempt_index,
                    task=current_task,
                    decision=decision,
                )
            )
            self._emit_progress(
                "real_loop_verification_completed",
                f"SFE: Real Loop verifier verdict: {decision.verdict}",
                real_loop_attempt=attempt_index,
                llm_verifier_verdict=decision.verdict,
                retry_worthwhile=decision.retry_worthwhile,
                stop_reason=decision.stop_reason,
            )

            stop_status = _terminal_status_for_decision(decision)
            if stop_status is not None:
                terminal_reason = (
                    REAL_LOOP_EXECUTOR_FAILURE_MESSAGE
                    if decision.verdict == "abort"
                    else None
                )
                return _with_real_loop_summary(
                    current_result,
                    self._summary_from_decision(
                        decision,
                        status=stop_status,
                        attempts_total=len(attempts),
                        reason=terminal_reason,
                        iterations=tuple(iterations),
                    ),
                )
            if not decision.retry_worthwhile:
                return _with_real_loop_summary(
                    current_result,
                    self._summary_from_decision(
                        decision,
                        status=REAL_LOOP_STATUS_ABORTED,
                        attempts_total=len(attempts),
                        stop_reason="retry_not_worthwhile",
                        reason=REAL_LOOP_EXECUTOR_FAILURE_MESSAGE,
                        iterations=tuple(iterations),
                    ),
                )
            if attempt_index >= self.config.max_iterations:
                return _with_real_loop_summary(
                    current_result,
                    self._summary_from_decision(
                        decision,
                        status=REAL_LOOP_STATUS_MAX_ITERATIONS,
                        attempts_total=len(attempts),
                        stop_reason="max_total_attempts_reached",
                        iterations=tuple(iterations),
                    ),
                )

            controller_stop_reason = self._controller_stop_reason(
                decision,
                original_task=original_task,
                previous_retry_tasks=tuple(previous_retry_tasks),
                previous_failure_categories=tuple(previous_failure_categories),
            )
            if controller_stop_reason is not None:
                return _with_real_loop_summary(
                    current_result,
                    self._summary_from_decision(
                        decision,
                        status=REAL_LOOP_STATUS_ABORTED,
                        attempts_total=len(attempts),
                        stop_reason=controller_stop_reason,
                        reason=REAL_LOOP_EXECUTOR_FAILURE_MESSAGE,
                        iterations=tuple(iterations),
                    ),
                )

            retry_task = decision.executor_retry_task or ""
            route = route_correction_task(retry_task)
            if route.execution_mode != EXECUTION_MODE_WORKSPACE_WRITE:
                return _with_real_loop_summary(
                    current_result,
                    self._summary_from_decision(
                        decision,
                        status=REAL_LOOP_STATUS_ABORTED,
                        attempts_total=len(attempts),
                        stop_reason=(
                            route.error_category
                            or "correction_task_not_workspace_write"
                        ),
                        reason=route.reason or "Correction task did not route to workspace_write.",
                        iterations=tuple(iterations),
                    ),
                )

            previous_retry_tasks.append(retry_task)
            if decision.failure_category is not None:
                previous_failure_categories.append(decision.failure_category)
            self._emit_progress(
                "real_loop_retry_task_ready",
                "SFE: Real Loop targeted retry task prepared",
                real_loop_attempt=attempt_index + 1,
                files_or_areas_to_focus=decision.files_or_areas_to_focus,
            )
            self._emit_progress(
                "real_loop_retry_started",
                f"SFE: Real Loop retry attempt {attempt_index + 1} started",
                real_loop_attempt=attempt_index + 1,
            )
            retry_result = run_attempt(retry_task, current_session)
            attempts.append(retry_result)
            current_result = retry_result
            current_task = retry_task
            current_session = retry_result.workspace_session or current_session
            if retry_result.status != RUN_STATUS_COMPLETED:
                iterations.append(
                    _iteration_from_result(
                        retry_result,
                        iteration_index=attempt_index + 1,
                        task=retry_task,
                        stop_reason="retry_attempt_failed",
                    )
                )
                return _with_real_loop_summary(
                    retry_result,
                    self._summary(
                        status=REAL_LOOP_STATUS_RETRY_FAILED,
                        attempts_total=len(attempts),
                        stop_reason="retry_attempt_failed",
                        reason=REAL_LOOP_EXECUTOR_FAILURE_MESSAGE,
                        iterations=tuple(iterations),
                    ),
                )
            if not _is_completed_workspace_write(retry_result):
                iterations.append(
                    _iteration_from_result(
                        retry_result,
                        iteration_index=attempt_index + 1,
                        task=retry_task,
                        stop_reason="retry_attempt_not_workspace_write",
                    )
                )
                return _with_real_loop_summary(
                    retry_result,
                    self._summary(
                        status=REAL_LOOP_STATUS_ABORTED,
                        attempts_total=len(attempts),
                        stop_reason="retry_attempt_not_workspace_write",
                        reason="Real Loop stopped because the correction attempt left workspace_write.",
                        iterations=tuple(iterations),
                    ),
                )

        return _with_real_loop_summary(
            current_result,
            self._summary(
                status=REAL_LOOP_STATUS_MAX_ITERATIONS,
                attempts_total=len(attempts),
                stop_reason="max_total_attempts_reached",
                iterations=tuple(iterations),
            ),
        )

    def _controller_stop_reason(
        self,
        decision: RealLoopVerifierDecision,
        *,
        original_task: str,
        previous_retry_tasks: tuple[str, ...],
        previous_failure_categories: tuple[str, ...],
    ) -> str | None:
        if (
            self.config.abort_on_no_progress
            and decision.progress_since_previous_iteration == "none"
            and decision.repeated_failure
        ):
            return "no_meaningful_progress_repeated_failure"
        if (
            self.config.abort_on_no_progress
            and decision.progress_since_previous_iteration == "none"
        ):
            return "no_meaningful_progress"
        if decision.repeated_failure:
            return "repeated_failure"
        if (
            decision.failure_category is not None
            and decision.failure_category in set(previous_failure_categories)
        ):
            return "repeated_failure_category"
        retry_task = decision.executor_retry_task or ""
        if self.config.abort_on_duplicate_retry_task and _duplicates_any_task(
            retry_task,
            (original_task, *previous_retry_tasks),
        ):
            return "duplicate_retry_task"
        return None

    def _summary_from_decision(
        self,
        decision: RealLoopVerifierDecision,
        *,
        status: str,
        attempts_total: int,
        iterations: tuple[RealLoopIterationSummary, ...],
        stop_reason: str | None = None,
        reason: str | None = None,
    ) -> RealLoopRunSummary:
        return self._summary(
            status=status,
            attempts_total=attempts_total,
            llm_verifier_verdict=decision.verdict,
            retry_worthwhile=decision.retry_worthwhile,
            stop_reason=stop_reason or decision.stop_reason,
            progress_since_previous_iteration=decision.progress_since_previous_iteration,
            detected_issues=decision.detected_issues,
            executor_retry_task=decision.executor_retry_task,
            verifier_provider=decision.provider_name,
            verifier_model=decision.model,
            reason=reason or decision.reason,
            iterations=iterations,
        )

    def _summary(
        self,
        *,
        status: str,
        attempts_total: int,
        stop_reason: str | None = None,
        llm_verifier_verdict: str | None = None,
        retry_worthwhile: bool | None = None,
        progress_since_previous_iteration: str | None = None,
        detected_issues: tuple[str, ...] = (),
        executor_retry_task: str | None = None,
        verifier_provider: str | None = None,
        verifier_model: str | None = None,
        reason: str | None = None,
        iterations: tuple[RealLoopIterationSummary, ...] = (),
    ) -> RealLoopRunSummary:
        return RealLoopRunSummary(
            enabled=True,
            real_loop_status=status,
            attempts_total=attempts_total,
            max_iterations=self.config.max_iterations,
            llm_verifier_verdict=llm_verifier_verdict,
            retry_worthwhile=retry_worthwhile,
            stop_reason=stop_reason,
            progress_since_previous_iteration=progress_since_previous_iteration,
            detected_issues=detected_issues,
            executor_retry_task=executor_retry_task,
            verifier_provider=verifier_provider or getattr(self.verifier, "provider_name", None),
            verifier_model=verifier_model or getattr(self.verifier, "model", None),
            reason=reason,
            iterations=iterations,
        )

    def _emit_progress(
        self,
        name: str,
        message: str,
        **metadata: object,
    ) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(
                RunProgressEvent(name=name, message=message, metadata=dict(metadata))
            )
        except Exception:
            return


def resolve_real_loop_config(environ: Mapping[str, str] | None = None) -> RealLoopConfig:
    env = os.environ if environ is None else environ
    return RealLoopConfig(
        mode=_resolve_mode(env.get("SFE_REAL_LOOP")),
        max_iterations=_resolve_positive_int(
            env.get("SFE_REAL_LOOP_MAX_ITERATIONS"),
            DEFAULT_REAL_LOOP_MAX_ITERATIONS,
        ),
        abort_on_no_progress=_resolve_bool(
            env.get("SFE_REAL_LOOP_ABORT_ON_NO_PROGRESS"),
            DEFAULT_REAL_LOOP_ABORT_ON_NO_PROGRESS,
        ),
        abort_on_duplicate_retry_task=_resolve_bool(
            env.get("SFE_REAL_LOOP_ABORT_ON_DUPLICATE_RETRY_TASK"),
            DEFAULT_REAL_LOOP_ABORT_ON_DUPLICATE_RETRY_TASK,
        ),
        diff_max_chars=_resolve_positive_int(
            env.get("SFE_REAL_LOOP_DIFF_MAX_CHARS"),
            DEFAULT_REAL_LOOP_DIFF_MAX_CHARS,
        ),
        file_preview_max_chars=_resolve_positive_int(
            env.get("SFE_REAL_LOOP_FILE_PREVIEW_MAX_CHARS"),
            DEFAULT_REAL_LOOP_FILE_PREVIEW_MAX_CHARS,
        ),
    )


def route_real_loop_correction_task(
    router: ExecutionModeRouter,
    task: str,
) -> RealLoopRouteDecision:
    try:
        decision = router.decide(task=task)
    except ExecutionModeRouterError as exc:
        return RealLoopRouteDecision(
            execution_mode=None,
            reason=exc.reason,
            provider_name=exc.provider_name or getattr(router, "provider_name", None),
            model=exc.model or getattr(router, "model", None),
            provider_calls_made=exc.provider_calls_made,
            error_category=exc.category,
        )
    return _route_decision_from_execution_mode_decision(decision)


def build_real_loop_workspace_snapshot(
    result: RunResult,
    config: RealLoopConfig,
) -> dict[str, object]:
    root = result.active_workspace
    paths = tuple(dict.fromkeys((*result.promoted_files, *result.changed_files)))
    previews: list[dict[str, object]] = []
    total_chars = 0
    if root is not None:
        for path in paths[:40]:
            if total_chars >= config.file_preview_max_chars:
                break
            relative_path = Path(path)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                continue
            preview = _read_bounded_file_preview(
                root / relative_path,
                display_path=str(relative_path),
                remaining_chars=config.file_preview_max_chars - total_chars,
            )
            if preview is not None:
                total_chars += len(str(preview.get("text", "")))
                previews.append(preview)
    return {
        "changed_files": list(result.changed_files),
        "promoted_files": list(result.promoted_files),
        "modified_files": list(result.patch_summary.modified_paths)
        if result.patch_summary is not None
        else [],
        "created_files": list(result.patch_summary.created_paths)
        if result.patch_summary is not None
        else [],
        "warnings": list(result.warnings),
        "multi_pass": result.multi_pass_summary is not None
        and result.multi_pass_summary.enabled,
        "file_previews": previews,
    }


def _route_decision_from_execution_mode_decision(
    decision: ExecutionModeDecision,
) -> RealLoopRouteDecision:
    return RealLoopRouteDecision(
        execution_mode=decision.execution_mode,
        reason=decision.reason,
        provider_name=decision.provider_name,
        model=decision.model,
        provider_calls_made=decision.provider_calls_made,
    )


def _is_completed_workspace_write(result: RunResult) -> bool:
    decision = result.execution_mode_decision
    return (
        result.status == RUN_STATUS_COMPLETED
        and decision is not None
        and decision.execution_mode == EXECUTION_MODE_WORKSPACE_WRITE
        and result.workspace_session is not None
    )


def _iteration_from_result(
    result: RunResult,
    *,
    iteration_index: int,
    task: str,
    decision: RealLoopVerifierDecision | None = None,
    stop_reason: str | None = None,
    verifier_issue: object | None = None,
    verifier_raw_answer: str | None = None,
) -> RealLoopIterationSummary:
    execution_mode = (
        result.execution_mode_decision.execution_mode
        if result.execution_mode_decision is not None
        else None
    )
    return RealLoopIterationSummary(
        iteration_index=iteration_index,
        task=task,
        run_status=result.status,
        execution_mode=execution_mode,
        changed_files=result.changed_files,
        promoted_files=result.promoted_files,
        llm_verifier_verdict=decision.verdict if decision is not None else None,
        retry_worthwhile=decision.retry_worthwhile if decision is not None else None,
        progress_since_previous_iteration=(
            decision.progress_since_previous_iteration if decision is not None else None
        ),
        repeated_failure=decision.repeated_failure if decision is not None else None,
        failure_category=decision.failure_category if decision is not None else None,
        detected_issues=decision.detected_issues if decision is not None else (),
        correction_objective=decision.correction_objective if decision is not None else None,
        executor_retry_task=decision.executor_retry_task if decision is not None else None,
        files_or_areas_to_focus=(
            decision.files_or_areas_to_focus if decision is not None else ()
        ),
        reason=decision.reason if decision is not None else None,
        stop_reason=stop_reason or (decision.stop_reason if decision is not None else None),
        verifier_provider=(
            decision.provider_name
            if decision is not None
            else getattr(verifier_issue, "provider_name", None)
        ),
        verifier_model=(
            decision.model
            if decision is not None
            else getattr(verifier_issue, "model", None)
        ),
        verifier_issue_category=(
            getattr(verifier_issue, "category", None) if verifier_issue is not None else None
        ),
        verifier_issue_reason=(
            getattr(verifier_issue, "reason", None) if verifier_issue is not None else None
        ),
        verifier_schema_validation_reason=_verifier_schema_validation_reason(
            verifier_issue
        ),
        verifier_raw_answer_preview=_verifier_raw_answer_preview(
            verifier_issue,
            verifier_raw_answer,
        ),
    )


def _verifier_schema_validation_reason(verifier_issue: object | None) -> str | None:
    if verifier_issue is None:
        return None
    diagnostics = getattr(verifier_issue, "diagnostics", None)
    if not isinstance(diagnostics, dict):
        return None
    value = diagnostics.get("schema_validation_reason")
    return value if isinstance(value, str) else None


def _verifier_raw_answer_preview(
    verifier_issue: object | None,
    raw_answer: str | None,
) -> str | None:
    if verifier_issue is not None:
        diagnostics = getattr(verifier_issue, "diagnostics", None)
        if isinstance(diagnostics, dict):
            value = diagnostics.get("raw_answer_preview")
            if isinstance(value, str):
                return value
    if raw_answer is None:
        return None
    preview = " ".join(raw_answer.replace("\x00", "").split())
    return preview[:500]


def _terminal_status_for_decision(decision: RealLoopVerifierDecision) -> str | None:
    return {
        "pass": REAL_LOOP_STATUS_VERIFIED_PASS,
        "blocked": REAL_LOOP_STATUS_BLOCKED,
        "abort": REAL_LOOP_STATUS_ABORTED,
    }.get(decision.verdict)


def _run_result_payload(result: RunResult) -> dict[str, object]:
    summary = result.patch_summary
    issue = result.issue
    return {
        "status": result.status,
        "execution_mode": (
            result.execution_mode_decision.execution_mode
            if result.execution_mode_decision is not None
            else None
        ),
        "changed_files": list(result.changed_files),
        "promoted_files": list(result.promoted_files),
        "modified_files": list(summary.modified_paths) if summary is not None else [],
        "created_files": list(summary.created_paths) if summary is not None else [],
        "promotion_status": result.promotion_status,
        "promotion_applied": result.promotion_applied,
        "executor_provider": result.executor_provider,
        "issue": (
            {"category": issue.category, "reason": issue.reason, "path": issue.path}
            if issue is not None
            else None
        ),
        "warnings": list(result.warnings),
    }


def _read_bounded_file_preview(
    path: Path,
    *,
    display_path: str,
    remaining_chars: int,
) -> dict[str, object] | None:
    if remaining_chars <= 0:
        return None
    try:
        if not path.is_file():
            return {
                "path": display_path,
                "status": "missing_or_not_file",
                "text": "",
                "truncated": False,
            }
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    truncated = len(text) > remaining_chars
    return {
        "path": display_path,
        "status": "read",
        "text": text[:remaining_chars],
        "truncated": truncated,
    }


def _with_real_loop_summary(
    result: RunResult,
    summary: RealLoopRunSummary,
) -> RunResult:
    return replace(result, real_loop_summary=summary)


def _duplicates_any_task(candidate: str, previous_tasks: tuple[str, ...]) -> bool:
    return any(_substantially_duplicates_task(candidate, previous) for previous in previous_tasks)


def _substantially_duplicates_task(left: str, right: str) -> bool:
    left_norm = _normalize_task(left)
    right_norm = _normalize_task(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    left_words = set(left_norm.split())
    right_words = set(right_norm.split())
    if not left_words or not right_words:
        return False
    intersection = len(left_words & right_words)
    union = len(left_words | right_words)
    jaccard = intersection / union if union else 0
    containment = intersection / min(len(left_words), len(right_words))
    return jaccard >= 0.9 or (containment >= 0.95 and abs(len(left_norm) - len(right_norm)) < 80)


def _normalize_task(task: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", task.casefold()))


def _resolve_mode(value: str | None) -> str:
    normalized = (value or DEFAULT_REAL_LOOP_MODE).strip().lower()
    if normalized in {"1", "true", "yes", "on", "force", "forced"}:
        return "true"
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return "false"
    return "auto"


def _resolve_bool(value: str | None, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _resolve_positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default
