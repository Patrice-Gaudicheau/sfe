"""Worktree-first run pipeline for SFE patch execution.

The pipeline is intentionally narrow: discover relevant context, route it down
to the executor payload, request a patch, apply only mechanically valid edits in
an isolated worktree, and return compact structured state.
"""

from __future__ import annotations

import os
import json
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from sfe.discovery import (
    DiscoveryResult,
    discover_workspace_context,
    load_discovery_context_file,
    load_discovered_context,
)
from sfe.contracts import SFEContract, build_contract
from sfe.discovery_router import DiscoveryRouter
from sfe.execution_mode_router import (
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_EXTERNAL_ACTION,
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
    ExecutionModeRouter,
    ExecutionModeRouterError,
    create_configured_execution_mode_router,
)
from sfe.execution_backend import ExecutionBackend, ExecutionResult
from sfe.filesystem_executor import FilesystemExecutor, FilesystemExecutionResult
from sfe.aider_filesystem_executor import AIDER_EXECUTOR_NAME, AiderFilesystemExecutor
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.multipass import (
    MultiPassBatch,
    MultiPassBatchResult,
    MultiPassConfig,
    MultiPassIssue,
    MultiPassPlan,
    MultiPassRunSummary,
    provider_diagnostics_from_execution_summary,
    resolve_multipass_config,
    should_use_multipass,
    validate_patch_paths_in_batch,
)
from sfe.multipass_planner import (
    MultiPassPlanner,
    create_configured_multipass_planner,
)
from sfe.patching import (
    HunkAccountingDiagnostics,
    HunkCountNormalizationDiagnostics,
    MECHANICAL_GUARD_REJECTED,
    PATCH_OPERATION_CREATE,
    PATCH_OPERATION_MODIFY,
    ParsedPatch,
    ParsedFilePatch,
    ParsedHunk,
    PatchApplyResult,
    PatchIssue,
    PatchLine,
    PatchSummary,
    SUPPORTED_CREATE_ACTION,
    SUPPORTED_REPLACE_ACTION,
    StructuredFileEdit,
    StructuredFilePatch,
    apply_patch_to_workspace,
    apply_structured_file_patch,
    generate_structured_file_patch_diff_preview,
    parse_structured_file_patch_json,
    parse_unified_diff,
    normalize_unified_diff_hunk_counts,
    extract_first_parseable_git_diff_segment,
    extract_single_fenced_git_diff,
    summarize_patch,
    summarize_structured_file_patch,
    validate_patch_paths,
    validate_patch_targets,
)
from sfe.patch_proposal_diagnostics import (
    PatchProposalDiagnostics,
    build_patch_proposal_diagnostics,
)
from sfe.workspace_isolation import (
    WorkspaceIsolationPolicy,
    WorkspaceIssue,
    WorkspaceManager,
    WorkspaceSession,
    WorkspaceStatusResult,
)
from sfe.workspace_write_transport import (
    SFE_FILE_START_RE,
    is_invalid_sfe_file_path,
    sfe_file_closing_marker_kind,
)
from sfe.workspace_write_executor import (
    WORKSPACE_WRITE_EXECUTOR_AIDER,
    WORKSPACE_WRITE_EXECUTOR_TEXT,
    WorkspaceWriteExecutorConfigError,
    resolve_workspace_write_executor,
)


RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class RunProgressEvent:
    name: str
    message: str
    metadata: dict[str, object]


RunProgressCallback = Callable[[RunProgressEvent], None]


@dataclass(frozen=True)
class RunIssue:
    category: str
    reason: str
    path: str | None = None
    hunk_accounting: HunkAccountingDiagnostics | None = None
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class GitPreparationResult:
    ok: bool
    auto_initialized: bool = False
    initial_commit_hash: str | None = None
    issue: RunIssue | None = None
    warning: str | None = None


@dataclass(frozen=True)
class PromotionTarget:
    relative_path: str
    source_path: Path
    worktree_path: Path
    source_before: bytes | None
    change_kind: str = "modified"


@dataclass(frozen=True)
class PromotionBaseline:
    targets: tuple[PromotionTarget, ...] = ()
    issue: RunIssue | None = None


@dataclass(frozen=True)
class PromotionResult:
    status: str
    promoted_files: tuple[str, ...] = ()
    issue: RunIssue | None = None


@dataclass(frozen=True)
class RunRequest:
    workspace_root: Path | None
    task: str
    workspace_session: WorkspaceSession | None = None
    workspace_policy: WorkspaceIsolationPolicy = WorkspaceIsolationPolicy()


@dataclass(frozen=True)
class RunPatchProposal:
    proposal: StructuredFilePatch | ParsedPatch
    summary: PatchSummary
    preview: str
    parse_status: str
    hunk_count_normalization: HunkCountNormalizationDiagnostics | None = None

    @property
    def paths(self) -> tuple[str, ...]:
        if isinstance(self.proposal, ParsedPatch):
            return tuple(file_patch.new_path for file_patch in self.proposal.files)
        return self.proposal.paths

    @property
    def transport_warnings(self) -> tuple[str, ...]:
        warnings: list[str] = []
        if "noncanonical" in self.parse_status:
            warnings.append("noncanonical_sfe_file_closing_marker_recovered")
        if "eof" in self.parse_status:
            warnings.append("eof_sfe_file_closing_marker_recovered")
        return tuple(warnings)


@dataclass(frozen=True)
class RunResult:
    status: str
    issue: RunIssue | None = None
    execution_mode_decision: ExecutionModeDecision | None = None
    console_output: str | None = None
    workspace_session: WorkspaceSession | None = None
    active_workspace: Path | None = None
    worktree_created: bool = False
    discovery_result: DiscoveryResult | None = None
    dry_run_result: ExecutionResult | None = None
    patch_result: ExecutionResult | None = None
    patch_generated: bool = False
    patch_applied: bool = False
    patch_summary: PatchSummary | None = None
    changed_files: tuple[str, ...] = ()
    selected_source_refs: tuple[str, ...] = ()
    executor_provider: str | None = None
    warnings: tuple[str, ...] = ()
    git_auto_init: bool = False
    git_initial_commit_hash: str | None = None
    git_init_warning: str | None = None
    promotion_status: str = "skipped"
    promotion_applied: bool = False
    promoted_files: tuple[str, ...] = ()
    promotion_issue: RunIssue | None = None
    patch_proposal_diagnostics: PatchProposalDiagnostics | None = None
    patch_hunk_count_normalization: HunkCountNormalizationDiagnostics | None = None
    multi_pass_summary: MultiPassRunSummary | None = None
    filesystem_result: FilesystemExecutionResult | None = None


class GitWorkspacePreparer:
    def prepare(self, workspace_root: Path) -> GitPreparationResult:
        workspace = workspace_root.expanduser().resolve()
        if not workspace.exists() or not workspace.is_dir():
            return GitPreparationResult(
                ok=False,
                issue=RunIssue("invalid_workspace", "workspace_not_directory"),
            )
        existing = _git(workspace, "rev-parse", "--show-toplevel")
        if existing.returncode == 0:
            return GitPreparationResult(ok=True)

        init = _git(workspace, "init", "-b", "main")
        if init.returncode != 0:
            return GitPreparationResult(
                ok=False,
                issue=RunIssue("git_auto_init", "git_init_failed"),
            )
        if not _ensure_git_info_exclude(workspace, ".sfe-worktrees/"):
            return GitPreparationResult(
                ok=False,
                auto_initialized=True,
                issue=RunIssue("git_auto_init", "git_exclude_update_failed"),
            )
        add = _git(
            workspace,
            "add",
            "--all",
            "--",
            ".",
        )
        if add.returncode != 0:
            return GitPreparationResult(
                ok=False,
                auto_initialized=True,
                issue=RunIssue("git_auto_init", "git_add_failed"),
            )
        commit = _git(
            workspace,
            "-c",
            "user.name=SFE",
            "-c",
            "user.email=sfe@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "Initial SFE workspace snapshot",
        )
        if commit.returncode != 0:
            return GitPreparationResult(
                ok=False,
                auto_initialized=True,
                issue=RunIssue("git_auto_init", "git_initial_commit_failed"),
            )
        head = _git(workspace, "rev-parse", "--short", "HEAD")
        if head.returncode != 0:
            return GitPreparationResult(
                ok=False,
                auto_initialized=True,
                issue=RunIssue("git_auto_init", "git_initial_commit_hash_failed"),
            )
        return GitPreparationResult(
            ok=True,
            auto_initialized=True,
            initial_commit_hash=head.stdout.strip() or None,
        )


class RunPipeline:
    def __init__(
        self,
        *,
        backend: ExecutionBackend,
        workspace_manager: WorkspaceManager | None = None,
        discovery_router: DiscoveryRouter | None = None,
        execution_mode_router: ExecutionModeRouter | None = None,
        multipass_planner: MultiPassPlanner | None = None,
        filesystem_executor: FilesystemExecutor | None = None,
        full_file_replacement_reviewer: object | None = None,
        git_preparer: GitWorkspacePreparer | None = None,
        progress_callback: RunProgressCallback | None = None,
    ) -> None:
        del full_file_replacement_reviewer
        self.backend = backend
        self.workspace_manager = workspace_manager or WorkspaceManager(
            GitWorktreeBackend()
        )
        self.discovery_router = discovery_router
        self.execution_mode_router = (
            execution_mode_router or create_configured_execution_mode_router()
        )
        self.multipass_planner = multipass_planner or create_configured_multipass_planner()
        self.filesystem_executor = filesystem_executor or AiderFilesystemExecutor()
        self.git_preparer = git_preparer or GitWorkspacePreparer()
        self.progress_callback = progress_callback

    def run(self, request: RunRequest) -> RunResult:
        self._emit_progress("run_started", "SFE: run started")
        if request.workspace_root is None:
            return _failed("workspace", "workspace_not_selected")
        if not request.task.strip():
            return _failed("task", "missing_task")

        try:
            self._emit_progress("execution_mode_routing", "SFE: execution mode routing")
            execution_mode_decision = self.execution_mode_router.decide(
                task=request.task,
            )
        except ExecutionModeRouterError as exc:
            provider_name = exc.provider_name or getattr(
                self.execution_mode_router,
                "provider_name",
                None,
            )
            model = exc.model or getattr(self.execution_mode_router, "model", None)
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue("execution_mode_routing", exc.category),
                execution_mode_decision=ExecutionModeDecision(
                    execution_mode="unknown",
                    reason=exc.reason,
                    provider_name=provider_name,
                    model=model,
                    provider_calls_made=exc.provider_calls_made,
                    invalid_response_preview=exc.invalid_response_preview,
                ),
                warnings=_base_warnings(),
            )
        self._emit_progress(
            "execution_mode_selected",
            f"SFE: execution mode selected: {execution_mode_decision.execution_mode}",
            execution_mode=execution_mode_decision.execution_mode,
            provider_name=execution_mode_decision.provider_name,
            model=execution_mode_decision.model,
        )

        if execution_mode_decision.execution_mode == EXECUTION_MODE_CONSOLE_OUTPUT:
            return self._run_console_output(request, execution_mode_decision)
        if execution_mode_decision.execution_mode == EXECUTION_MODE_EXTERNAL_ACTION:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue(
                    "unsupported_execution_mode",
                    "external_action_not_implemented",
                ),
                execution_mode_decision=execution_mode_decision,
                warnings=("external_action_not_implemented",),
            )
        if execution_mode_decision.execution_mode != EXECUTION_MODE_WORKSPACE_WRITE:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue(
                    "execution_mode_routing",
                    "invalid_execution_mode",
                ),
                execution_mode_decision=execution_mode_decision,
                warnings=_base_warnings(),
            )

        self._emit_progress(
            "workspace_preparation_started",
            "SFE: workspace preparation started",
        )
        git_preparation = self._prepare_git_workspace(request)
        if not git_preparation.ok:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=git_preparation.issue
                or RunIssue("git_auto_init", "git_preparation_failed"),
                execution_mode_decision=execution_mode_decision,
                warnings=_base_warnings(),
                git_auto_init=git_preparation.auto_initialized,
                git_initial_commit_hash=git_preparation.initial_commit_hash,
                git_init_warning=git_preparation.warning,
            )

        session_result = self._ensure_worktree(request)
        if isinstance(session_result, RunResult):
            return _with_git_preparation(
                replace(
                    session_result,
                    execution_mode_decision=execution_mode_decision,
                ),
                git_preparation,
            )
        session, active_workspace, created = session_result

        self._emit_progress(
            "context_discovery_started",
            "SFE: context discovery started",
        )
        discovery_result = discover_workspace_context(
            workspace_root=active_workspace,
            task=request.task,
            router=self.discovery_router,
        )
        self._emit_progress(
            "context_candidates_inspected",
            f"SFE: context candidates inspected: {discovery_result.candidate_count}",
            candidate_count=discovery_result.candidate_count,
            workspace_map_count=discovery_result.workspace_map_count,
            scanned_file_count=discovery_result.scanned_file_count,
            router_provider_name=discovery_result.router_provider_name,
            stop_reason=discovery_result.stop_reason,
        )
        if discovery_result.router_error_category is not None:
            return _with_git_preparation(
                RunResult(
                    status=RUN_STATUS_FAILED,
                    issue=RunIssue(
                        "context_discovery",
                        discovery_result.router_error_category,
                    ),
                    execution_mode_decision=execution_mode_decision,
                    workspace_session=session,
                    active_workspace=active_workspace,
                    worktree_created=created,
                    discovery_result=discovery_result,
                    warnings=_base_warnings(),
                ),
                git_preparation,
            )
        context_files = list(
            load_discovered_context(
                workspace_root=active_workspace,
                discovery_result=discovery_result,
            )
        )
        contract = build_contract(
            workspace_root=active_workspace,
            task=request.task,
            file_paths=[],
            context_files=context_files,
        )
        dry_run_result = self.backend.dry_run(contract)
        selected_ids = list(dry_run_result.contract.audit.get("selected_segment_ids") or [])
        selected_source_refs = _selected_source_refs(dry_run_result, selected_ids)
        self._emit_progress(
            "relevant_context_selected",
            f"SFE: relevant context selected: {len(selected_source_refs)} files",
            selected_context_count=len(selected_source_refs),
            selected_segment_count=len(selected_ids),
        )
        estimated_reduction = _estimated_reduction_label(dry_run_result)
        self._emit_progress(
            "estimated_token_reduction",
            f"SFE: estimated token reduction: {estimated_reduction}",
            estimated_token_reduction=estimated_reduction,
        )
        multipass_config = resolve_multipass_config()
        multipass_requested = should_use_multipass(request.task, multipass_config)
        try:
            workspace_write_executor = resolve_workspace_write_executor()
        except WorkspaceWriteExecutorConfigError as exc:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue(
                    "workspace_write_executor",
                    "unsupported_workspace_write_executor",
                    diagnostics={
                        "configured_value": exc.value,
                        "supported_values": (
                            WORKSPACE_WRITE_EXECUTOR_AIDER,
                            WORKSPACE_WRITE_EXECUTOR_TEXT,
                        ),
                    },
                ),
                execution_mode_decision=execution_mode_decision,
                workspace_session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
                warnings=_base_warnings(),
                git_auto_init=git_preparation.auto_initialized,
                git_initial_commit_hash=git_preparation.initial_commit_hash,
                git_init_warning=git_preparation.warning,
            )
        if (
            dry_run_result.contract.context_segments
            and not selected_ids
            and not multipass_requested
            and workspace_write_executor == WORKSPACE_WRITE_EXECUTOR_TEXT
        ):
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue("routing", "no_selected_context"),
                execution_mode_decision=execution_mode_decision,
                workspace_session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
                warnings=_base_warnings(),
                git_auto_init=git_preparation.auto_initialized,
                git_initial_commit_hash=git_preparation.initial_commit_hash,
                git_init_warning=git_preparation.warning,
            )

        if multipass_requested:
            if workspace_write_executor == WORKSPACE_WRITE_EXECUTOR_AIDER:
                return self._run_workspace_write_multipass_filesystem(
                    request=request,
                    execution_mode_decision=execution_mode_decision,
                    git_preparation=git_preparation,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    selected_source_refs=selected_source_refs,
                    contract=contract,
                    config=multipass_config,
                )
            return self._run_workspace_write_multipass(
                request=request,
                execution_mode_decision=execution_mode_decision,
                git_preparation=git_preparation,
                session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
                contract=contract,
                config=multipass_config,
            )

        if workspace_write_executor == WORKSPACE_WRITE_EXECUTOR_AIDER:
            return self._run_workspace_write_filesystem(
                request=request,
                execution_mode_decision=execution_mode_decision,
                git_preparation=git_preparation,
                session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
            )

        self._emit_progress("executor_prompt_prepared", "SFE: executor prompt prepared")
        self._emit_progress(
            "patch_worktree_execution_started",
            "SFE: patch/worktree execution started",
        )
        patch_result = self.backend.patch(contract)
        if not patch_result.answer:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue(
                    "patch_generation",
                    patch_result.error_category or "invalid_response",
                ),
                execution_mode_decision=execution_mode_decision,
                workspace_session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=patch_result,
                selected_source_refs=selected_source_refs,
                executor_provider=_executor_provider(patch_result),
                warnings=_base_warnings(),
                git_auto_init=git_preparation.auto_initialized,
                git_initial_commit_hash=git_preparation.initial_commit_hash,
                git_init_warning=git_preparation.warning,
                patch_proposal_diagnostics=build_patch_proposal_diagnostics(
                    patch_result.answer or "",
                    selected_source_refs=selected_source_refs,
                ),
            )

        proposal = self._parse_patch_response(active_workspace, patch_result)
        parse_issue: RunIssue | None = None
        patch_proposal_diagnostics = None
        if isinstance(proposal, RunIssue):
            parse_issue = proposal
            if proposal.category == "invalid_patch_proposal":
                patch_proposal_diagnostics = build_patch_proposal_diagnostics(
                    patch_result.answer or "",
                    selected_source_refs=selected_source_refs,
                )
            proposal = None

        apply_result: PatchApplyResult | None = None
        if proposal is not None:
            apply_result = _apply_run_patch_proposal(
                active_workspace,
                session.worktree_path,
                proposal,
            )
            if (
                apply_result.issue is not None
                and apply_result.issue.category == "workspace_boundary"
            ):
                return _patch_failed_result(
                    apply_result.issue,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=patch_result,
                    proposal=proposal,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    execution_mode_decision=execution_mode_decision,
                )

        promotion_baseline = _capture_actual_workspace_changes(session, active_workspace)
        patch_summary = (
            apply_result.summary
            if apply_result is not None and apply_result.summary is not None
            else proposal.summary
            if proposal is not None
            else _summary_from_promotion_baseline(promotion_baseline)
        )
        changed_files = _promotion_baseline_paths(promotion_baseline)
        self._emit_progress(
            "workspace_boundary_check_completed",
            "SFE: workspace boundary check completed",
            changed_file_count=len(changed_files),
            destination_root=str(session.source_path.resolve()),
        )
        if promotion_baseline.issue is not None:
            return _workspace_write_failed_result(
                promotion_baseline.issue,
                session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=patch_result,
                proposal=proposal,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
                execution_mode_decision=execution_mode_decision,
                patch_applied=bool(apply_result and apply_result.applied),
                patch_summary=patch_summary,
                changed_files=changed_files,
                patch_proposal_diagnostics=patch_proposal_diagnostics,
            )
        if parse_issue is not None and not changed_files:
            return _workspace_write_failed_result(
                parse_issue,
                session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=patch_result,
                proposal=proposal,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
                execution_mode_decision=execution_mode_decision,
                patch_applied=bool(apply_result and apply_result.applied),
                patch_summary=patch_summary,
                changed_files=changed_files,
                patch_proposal_diagnostics=patch_proposal_diagnostics,
            )

        promotion_result = _promote_actual_workspace_changes(promotion_baseline)
        if promotion_result.status not in {"applied", "skipped"}:
            issue = promotion_result.issue or RunIssue("promotion", "promotion_not_applied")
            return _workspace_write_failed_result(
                issue,
                session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=patch_result,
                proposal=proposal,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
                execution_mode_decision=execution_mode_decision,
                patch_applied=bool(apply_result and apply_result.applied),
                patch_summary=patch_summary,
                changed_files=changed_files,
                promotion_result=promotion_result,
                patch_proposal_diagnostics=patch_proposal_diagnostics,
            )
        self._emit_progress(
            "promotion_completed",
            "SFE: promotion completed",
            promoted_file_count=len(promotion_result.promoted_files),
        )
        return RunResult(
            status=RUN_STATUS_COMPLETED,
            execution_mode_decision=execution_mode_decision,
            workspace_session=session,
            active_workspace=active_workspace,
            worktree_created=created,
            discovery_result=discovery_result,
            dry_run_result=dry_run_result,
            patch_result=patch_result,
            patch_generated=proposal is not None,
            patch_applied=bool(apply_result and apply_result.applied),
            patch_summary=patch_summary,
            changed_files=changed_files,
            selected_source_refs=selected_source_refs,
            executor_provider=_executor_provider(patch_result),
            warnings=_warnings_for_summary_and_proposal(patch_summary, proposal),
            git_auto_init=git_preparation.auto_initialized,
            git_initial_commit_hash=git_preparation.initial_commit_hash,
            git_init_warning=git_preparation.warning,
            promotion_status=promotion_result.status,
            promotion_applied=promotion_result.status == "applied",
            promoted_files=promotion_result.promoted_files,
            patch_proposal_diagnostics=patch_proposal_diagnostics,
            patch_hunk_count_normalization=(
                proposal.hunk_count_normalization if proposal is not None else None
            ),
        )

    def _run_workspace_write_filesystem(
        self,
        *,
        request: RunRequest,
        execution_mode_decision: ExecutionModeDecision,
        git_preparation: GitPreparationResult,
        session: WorkspaceSession,
        active_workspace: Path,
        worktree_created: bool,
        discovery_result: DiscoveryResult,
        dry_run_result: ExecutionResult,
        selected_source_refs: tuple[str, ...],
    ) -> RunResult:
        from sfe.filesystem_executor import FilesystemExecutionRequest

        self._emit_progress("executor_prompt_prepared", "SFE: executor prompt prepared")
        self._emit_progress(
            "filesystem_worktree_execution_started",
            "SFE: Aider filesystem execution started",
        )
        fs_result = self.filesystem_executor.execute(
            FilesystemExecutionRequest(
                cwd=active_workspace,
                task=request.task,
                expected_paths=(),
                context_paths=selected_source_refs,
                metadata={
                    "workspace_session_id": session.session_id,
                    "source_path": str(session.source_path.resolve()),
                    "worktree_path": str(session.worktree_path.resolve()),
                },
            )
        )
        if fs_result.status != "completed":
            return _filesystem_workspace_write_failed_result(
                fs_result,
                execution_mode_decision=execution_mode_decision,
                session=session,
                active_workspace=active_workspace,
                worktree_created=worktree_created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
            )

        promotion_baseline = _capture_actual_workspace_changes(session, active_workspace)
        patch_summary = _summary_from_promotion_baseline(promotion_baseline)
        changed_files = _promotion_baseline_paths(promotion_baseline)
        self._emit_progress(
            "workspace_boundary_check_completed",
            "SFE: workspace boundary check completed",
            changed_file_count=len(changed_files),
            destination_root=str(session.source_path.resolve()),
        )
        if promotion_baseline.issue is not None:
            return _filesystem_workspace_write_failed_result(
                fs_result,
                issue=promotion_baseline.issue,
                execution_mode_decision=execution_mode_decision,
                session=session,
                active_workspace=active_workspace,
                worktree_created=worktree_created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
                patch_summary=patch_summary,
                changed_files=changed_files,
            )

        promotion_result = _promote_actual_workspace_changes(promotion_baseline)
        if promotion_result.status not in {"applied", "skipped"}:
            issue = promotion_result.issue or RunIssue("promotion", "promotion_not_applied")
            return _filesystem_workspace_write_failed_result(
                fs_result,
                issue=issue,
                execution_mode_decision=execution_mode_decision,
                session=session,
                active_workspace=active_workspace,
                worktree_created=worktree_created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
                patch_summary=patch_summary,
                changed_files=changed_files,
                promotion_result=promotion_result,
            )

        self._emit_progress(
            "promotion_completed",
            "SFE: promotion completed",
            promoted_file_count=len(promotion_result.promoted_files),
        )
        return RunResult(
            status=RUN_STATUS_COMPLETED,
            execution_mode_decision=execution_mode_decision,
            workspace_session=session,
            active_workspace=active_workspace,
            worktree_created=worktree_created,
            discovery_result=discovery_result,
            dry_run_result=dry_run_result,
            patch_result=None,
            patch_generated=False,
            patch_applied=False,
            patch_summary=patch_summary,
            changed_files=changed_files,
            selected_source_refs=selected_source_refs,
            executor_provider=fs_result.executor_name,
            warnings=_warnings_for_summary(patch_summary),
            git_auto_init=git_preparation.auto_initialized,
            git_initial_commit_hash=git_preparation.initial_commit_hash,
            git_init_warning=git_preparation.warning,
            promotion_status=promotion_result.status,
            promotion_applied=promotion_result.status == "applied",
            promoted_files=promotion_result.promoted_files,
            filesystem_result=fs_result,
        )

    def _run_workspace_write_multipass(
        self,
        *,
        request: RunRequest,
        execution_mode_decision: ExecutionModeDecision,
        git_preparation: GitPreparationResult,
        session: WorkspaceSession,
        active_workspace: Path,
        worktree_created: bool,
        discovery_result: DiscoveryResult,
        dry_run_result: ExecutionResult,
        selected_source_refs: tuple[str, ...],
        contract: SFEContract,
        config: MultiPassConfig,
    ) -> RunResult:
        self._emit_progress(
            "multi_pass_planning_started",
            "SFE: multi-pass planning started",
        )
        planner_response = self.multipass_planner.plan(
            contract,
            config=config,
        )
        if planner_response.issue is not None or planner_response.plan is None:
            planning_issue = planner_response.issue or MultiPassIssue(
                "multi_pass_planning",
                "invalid_response",
            )
            issue = _run_issue_from_multipass(planning_issue)
            summary = _build_multi_pass_summary(
                status="failed",
                failed_issue=planning_issue,
            )
            return _multipass_run_result(
                status=RUN_STATUS_FAILED,
                issue=issue,
                execution_mode_decision=execution_mode_decision,
                session=session,
                active_workspace=active_workspace,
                worktree_created=worktree_created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=None,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
                multi_pass_summary=summary,
            )

        parsed_plan = planner_response.plan

        self._emit_progress(
            "multi_pass_plan_completed",
            f"SFE: multi-pass plan completed: {len(parsed_plan.batches)} passes",
            multi_pass_total=len(parsed_plan.batches),
            provider_name=planner_response.provider_name,
            model=planner_response.model,
        )
        pass_results: list[MultiPassBatchResult] = []
        completed_summaries: list[PatchSummary] = []
        all_promoted_files: list[str] = []
        completed_files: list[str] = []
        multi_pass_warnings: list[str] = []
        out_of_scope_promoted_files: set[str] = set()
        latest_patch_result: ExecutionResult | None = None
        latest_hunk_normalization: HunkCountNormalizationDiagnostics | None = None
        current_contract = contract
        refresh_base_refs = tuple(segment.source_ref for segment in contract.context_segments)
        initial_existing_files = _existing_plan_files(active_workspace, parsed_plan)

        for index, batch in enumerate(parsed_plan.batches, start=1):
            self._emit_progress(
                "multi_pass_pass_started",
                f"SFE: multi-pass pass {index}/{len(parsed_plan.batches)} started",
                multi_pass_index=index,
                multi_pass_total=len(parsed_plan.batches),
                multi_pass_id=batch.id,
            )
            changed_files_before_pass = set(
                _promotion_baseline_paths(
                    _capture_actual_workspace_changes(session, active_workspace)
                )
            )
            batch_warnings: list[str] = []
            if batch.allowed_files and all(
                path in out_of_scope_promoted_files for path in batch.allowed_files
            ):
                warning = (
                    "multi_pass_skipped_already_promoted_outside_batch:"
                    + ",".join(batch.allowed_files)
                )
                batch_warnings.append(warning)
                multi_pass_warnings.append(warning)
                pass_results.append(
                    MultiPassBatchResult(
                        pass_id=batch.id,
                        title=batch.title,
                        status="skipped",
                        allowed_files=batch.allowed_files,
                        warnings=tuple(batch_warnings),
                    )
                )
                self._emit_progress(
                    "multi_pass_pass_completed",
                    f"SFE: multi-pass pass {index}/{len(parsed_plan.batches)} skipped",
                    multi_pass_index=index,
                    multi_pass_total=len(parsed_plan.batches),
                    multi_pass_id=batch.id,
                    promoted_file_count=0,
                )
                continue
            current_contract = _refresh_multipass_contract(
                workspace_root=active_workspace,
                task=request.task,
                base_source_refs=refresh_base_refs,
                refreshed_paths=(
                    *batch.allowed_files,
                    *all_promoted_files,
                ),
            )
            patch_result = self.backend.patch_multipass_batch(
                current_contract,
                plan=parsed_plan,
                batch=batch,
                completed_files=tuple(completed_files),
            )
            latest_patch_result = patch_result
            provider_diagnostics = provider_diagnostics_from_execution_summary(
                patch_result.summary
            )
            executor_contract_diagnostics = _executor_contract_diagnostics(
                active_workspace,
                patch_result,
            )
            if not patch_result.answer:
                issue = RunIssue(
                    "patch_generation",
                    patch_result.error_category or "invalid_response",
                )
                pass_issue = _multi_pass_issue_from_run_issue(issue, pass_id=batch.id)
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                        executor_contract_diagnostics=executor_contract_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=pass_issue,
                    all_promoted_files=tuple(all_promoted_files),
                    safe_resume_possible=bool(all_promoted_files),
                )
                return _multipass_run_result(
                    status=RUN_STATUS_FAILED,
                    issue=issue,
                    execution_mode_decision=execution_mode_decision,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=worktree_created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=patch_result,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    multi_pass_summary=summary,
                    patch_summary=_combine_patch_summaries(tuple(completed_summaries)),
                    promoted_files=tuple(all_promoted_files),
                )

            existing_update_files = tuple(
                path for path in batch.allowed_files if path in initial_existing_files
            )
            proposal = self._parse_patch_response(
                active_workspace,
                patch_result,
                completed_files=tuple(completed_files),
                existing_update_files=existing_update_files,
            )
            parse_issue: RunIssue | None = None
            patch_proposal_diagnostics = None
            if isinstance(proposal, RunIssue):
                parse_issue = proposal
                if proposal.category == "invalid_patch_proposal":
                    patch_proposal_diagnostics = build_patch_proposal_diagnostics(
                        patch_result.answer or "",
                        selected_source_refs=selected_source_refs,
                    )
                proposal = None

            executor_contract_diagnostics = _executor_contract_diagnostics(
                active_workspace,
                patch_result,
                proposal,
            )
            if proposal is not None:
                for warning in proposal.transport_warnings:
                    batch_warnings.append(warning)
                    multi_pass_warnings.append(warning)
                scope_issue = validate_patch_paths_in_batch(proposal.paths, batch)
                if scope_issue is not None:
                    for path in _paths_outside_batch(proposal.paths, batch):
                        warning = f"multi_pass_path_outside_allowed_files:{path}"
                        batch_warnings.append(warning)
                        multi_pass_warnings.append(warning)

            apply_result: PatchApplyResult | None = None
            if proposal is not None:
                apply_result = _apply_run_patch_proposal(
                    active_workspace,
                    session.worktree_path,
                    proposal,
                )
                if (
                    apply_result.issue is not None
                    and apply_result.issue.category == "workspace_boundary"
                ):
                    issue = _run_issue_from_patch(
                        apply_result.issue,
                        default_reason="changed_path_outside_destination",
                    )
                    pass_issue = _multi_pass_issue_from_run_issue(
                        issue,
                        pass_id=batch.id,
                    )
                    pass_results.append(
                        _failed_batch_result(
                            batch,
                            issue=pass_issue,
                            provider_diagnostics=provider_diagnostics,
                            executor_contract_diagnostics=executor_contract_diagnostics,
                        )
                    )
                    summary = _build_multi_pass_summary(
                        status="failed",
                        project_summary=parsed_plan.project_summary,
                        passes_total=len(parsed_plan.batches),
                        pass_results=tuple(pass_results),
                        failed_issue=pass_issue,
                        all_promoted_files=tuple(all_promoted_files),
                        safe_resume_possible=bool(all_promoted_files),
                    )
                    return _multipass_run_result(
                        status=RUN_STATUS_FAILED,
                        issue=issue,
                        execution_mode_decision=execution_mode_decision,
                        session=session,
                        active_workspace=active_workspace,
                        worktree_created=worktree_created,
                        discovery_result=discovery_result,
                        dry_run_result=dry_run_result,
                        patch_result=patch_result,
                        selected_source_refs=selected_source_refs,
                        git_preparation=git_preparation,
                        multi_pass_summary=summary,
                        patch_summary=_combine_patch_summaries(tuple(completed_summaries)),
                        promoted_files=tuple(all_promoted_files),
                        patch_proposal_diagnostics=patch_proposal_diagnostics,
                    )
            fallback_diagnostics: dict[str, object] | None = None

            promotion_baseline = _capture_actual_workspace_changes(
                session,
                active_workspace,
            )
            patch_summary = (
                apply_result.summary
                if apply_result is not None and apply_result.summary is not None
                else proposal.summary
                if proposal is not None
                else _summary_from_promotion_baseline(promotion_baseline)
            )
            if promotion_baseline.issue is not None:
                issue = promotion_baseline.issue
                pass_issue = _multi_pass_issue_from_run_issue(issue, pass_id=batch.id)
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                        executor_contract_diagnostics=executor_contract_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=pass_issue,
                    all_promoted_files=tuple(all_promoted_files),
                    safe_resume_possible=bool(all_promoted_files),
                )
                return _multipass_run_result(
                    status=RUN_STATUS_FAILED,
                    issue=issue,
                    execution_mode_decision=execution_mode_decision,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=worktree_created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=patch_result,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    multi_pass_summary=summary,
                    patch_summary=_combine_patch_summaries(
                        (
                            *completed_summaries,
                            *((patch_summary,) if patch_summary is not None else ()),
                        )
                    ),
                    promoted_files=tuple(all_promoted_files),
                    patch_proposal_diagnostics=patch_proposal_diagnostics,
                )
            if parse_issue is not None and not promotion_baseline.targets:
                pass_issue = _multi_pass_issue_from_run_issue(
                    parse_issue,
                    pass_id=batch.id,
                )
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                        executor_contract_diagnostics=executor_contract_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=pass_issue,
                    all_promoted_files=tuple(all_promoted_files),
                    safe_resume_possible=bool(all_promoted_files),
                )
                return _multipass_run_result(
                    status=RUN_STATUS_FAILED,
                    issue=parse_issue,
                    execution_mode_decision=execution_mode_decision,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=worktree_created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=patch_result,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    multi_pass_summary=summary,
                    patch_summary=_combine_patch_summaries(tuple(completed_summaries)),
                    promoted_files=tuple(all_promoted_files),
                    patch_proposal_diagnostics=patch_proposal_diagnostics,
                )

            promotion_result = _promote_actual_workspace_changes(promotion_baseline)
            if promotion_result.status not in {"applied", "skipped"}:
                issue = promotion_result.issue or RunIssue(
                    "promotion",
                    "promotion_not_applied",
                )
                pass_issue = _multi_pass_issue_from_run_issue(issue, pass_id=batch.id)
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                        executor_contract_diagnostics=executor_contract_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=pass_issue,
                    all_promoted_files=tuple(all_promoted_files),
                    safe_resume_possible=bool(all_promoted_files),
                )
                return _multipass_run_result(
                    status=RUN_STATUS_FAILED,
                    issue=issue,
                    execution_mode_decision=execution_mode_decision,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=worktree_created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=patch_result,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    multi_pass_summary=summary,
                    patch_summary=_combine_patch_summaries(
                        (
                            *completed_summaries,
                            *((patch_summary,) if patch_summary is not None else ()),
                        )
                    ),
                    promoted_files=tuple(all_promoted_files),
                    promotion_status=promotion_result.status,
                    promotion_issue=promotion_result.issue,
                    patch_proposal_diagnostics=patch_proposal_diagnostics,
                )

            pass_promoted_files = tuple(
                path
                for path in promotion_result.promoted_files
                if path not in changed_files_before_pass
            )
            for path in pass_promoted_files:
                if path not in set(batch.allowed_files):
                    warning = f"multi_pass_path_outside_allowed_files:{path}"
                    batch_warnings.append(warning)
                    multi_pass_warnings.append(warning)

            latest_hunk_normalization = (
                proposal.hunk_count_normalization if proposal is not None else None
            )
            completed_summaries.append(patch_summary)
            completed_files.extend(pass_promoted_files)
            for promoted_file in promotion_result.promoted_files:
                if promoted_file not in all_promoted_files:
                    all_promoted_files.append(promoted_file)
            out_of_scope_promoted_files.update(
                path
                for path in pass_promoted_files
                if path not in set(batch.allowed_files)
            )
            current_contract = _refresh_multipass_contract(
                workspace_root=active_workspace,
                task=request.task,
                base_source_refs=refresh_base_refs,
                refreshed_paths=tuple(all_promoted_files),
            )
            self._emit_progress(
                "multi_pass_workspace_state_refreshed",
                "SFE: multi-pass workspace state refreshed",
                refreshed_file_count=len(all_promoted_files),
            )
            pass_results.append(
                MultiPassBatchResult(
                    pass_id=batch.id,
                    title=batch.title,
                    status="completed",
                    allowed_files=batch.allowed_files,
                    created_files=patch_summary.created_paths,
                    promoted_files=pass_promoted_files,
                    patch_paths=patch_summary.paths,
                    provider_diagnostics=provider_diagnostics,
                    fallback_diagnostics=fallback_diagnostics,
                    full_content_provided_files=executor_contract_diagnostics[
                        "full_content_provided_files"
                    ],
                    full_file_replacement_eligible_files=executor_contract_diagnostics[
                        "full_file_replacement_eligible_files"
                    ],
                    full_file_replacement_used_files=executor_contract_diagnostics[
                        "full_file_replacement_used_files"
                    ],
                    warnings=tuple(dict.fromkeys(batch_warnings)),
                )
            )
            self._emit_progress(
                "multi_pass_pass_completed",
                f"SFE: multi-pass pass {index}/{len(parsed_plan.batches)} completed",
                multi_pass_index=index,
                multi_pass_total=len(parsed_plan.batches),
                multi_pass_id=batch.id,
                promoted_file_count=len(pass_promoted_files),
            )

        aggregate_summary = _combine_patch_summaries(tuple(completed_summaries))
        multi_pass_summary = _build_multi_pass_summary(
            status="completed",
            project_summary=parsed_plan.project_summary,
            passes_total=len(parsed_plan.batches),
            pass_results=tuple(pass_results),
            all_promoted_files=tuple(all_promoted_files),
        )
        self._emit_progress(
            "promotion_completed",
            "SFE: promotion completed",
            promoted_file_count=len(all_promoted_files),
        )
        return RunResult(
            status=RUN_STATUS_COMPLETED,
            execution_mode_decision=execution_mode_decision,
            workspace_session=session,
            active_workspace=active_workspace,
            worktree_created=worktree_created,
            discovery_result=discovery_result,
            dry_run_result=dry_run_result,
            patch_result=latest_patch_result,
            patch_generated=True,
            patch_applied=True,
            patch_summary=aggregate_summary,
            changed_files=aggregate_summary.paths if aggregate_summary else (),
            selected_source_refs=selected_source_refs,
            executor_provider=_executor_provider(latest_patch_result),
            warnings=tuple(
                dict.fromkeys(
                    (*_warnings_for_summary(aggregate_summary), *multi_pass_warnings)
                )
            ),
            git_auto_init=git_preparation.auto_initialized,
            git_initial_commit_hash=git_preparation.initial_commit_hash,
            git_init_warning=git_preparation.warning,
            promotion_status="applied" if all_promoted_files else "skipped",
            promotion_applied=bool(all_promoted_files),
            promoted_files=tuple(all_promoted_files),
            patch_hunk_count_normalization=latest_hunk_normalization,
            multi_pass_summary=multi_pass_summary,
        )

    def _run_workspace_write_multipass_filesystem(
        self,
        *,
        request: RunRequest,
        execution_mode_decision: ExecutionModeDecision,
        git_preparation: GitPreparationResult,
        session: WorkspaceSession,
        active_workspace: Path,
        worktree_created: bool,
        discovery_result: DiscoveryResult,
        dry_run_result: ExecutionResult,
        selected_source_refs: tuple[str, ...],
        contract: SFEContract,
        config: MultiPassConfig,
    ) -> RunResult:
        from sfe.filesystem_executor import FilesystemExecutionRequest

        self._emit_progress(
            "multi_pass_planning_started",
            "SFE: multi-pass planning started",
        )
        planner_response = self.multipass_planner.plan(
            contract,
            config=config,
        )
        if planner_response.issue is not None or planner_response.plan is None:
            planning_issue = planner_response.issue or MultiPassIssue(
                "multi_pass_planning",
                "invalid_response",
            )
            issue = _run_issue_from_multipass(planning_issue)
            summary = _build_multi_pass_summary(
                status="failed",
                failed_issue=planning_issue,
            )
            return _multipass_run_result(
                status=RUN_STATUS_FAILED,
                issue=issue,
                execution_mode_decision=execution_mode_decision,
                session=session,
                active_workspace=active_workspace,
                worktree_created=worktree_created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=None,
                selected_source_refs=selected_source_refs,
                git_preparation=git_preparation,
                multi_pass_summary=summary,
            )

        parsed_plan = planner_response.plan
        self._emit_progress(
            "multi_pass_plan_completed",
            f"SFE: multi-pass plan completed: {len(parsed_plan.batches)} passes",
            multi_pass_total=len(parsed_plan.batches),
            provider_name=planner_response.provider_name,
            model=planner_response.model,
        )

        pass_results: list[MultiPassBatchResult] = []
        completed_summaries: list[PatchSummary] = []
        all_promoted_files: list[str] = []
        completed_files: list[str] = []
        multi_pass_warnings: list[str] = []
        latest_filesystem_result: FilesystemExecutionResult | None = None
        refresh_base_refs = tuple(segment.source_ref for segment in contract.context_segments)

        for index, batch in enumerate(parsed_plan.batches, start=1):
            self._emit_progress(
                "multi_pass_pass_started",
                f"SFE: multi-pass pass {index}/{len(parsed_plan.batches)} started",
                multi_pass_index=index,
                multi_pass_total=len(parsed_plan.batches),
                multi_pass_id=batch.id,
            )
            changed_files_before_pass = set(
                _promotion_baseline_paths(
                    _capture_actual_workspace_changes(session, active_workspace)
                )
            )
            pass_task = _build_multipass_filesystem_task(
                user_task=request.task,
                plan=parsed_plan,
                batch=batch,
                pass_index=index,
                total_passes=len(parsed_plan.batches),
                completed_files=tuple(completed_files),
            )
            context_paths = _multipass_filesystem_context_paths(
                selected_source_refs=selected_source_refs,
                all_promoted_files=tuple(all_promoted_files),
                allowed_files=batch.allowed_files,
            )
            fs_result = self.filesystem_executor.execute(
                FilesystemExecutionRequest(
                    cwd=active_workspace,
                    task=pass_task,
                    expected_paths=batch.allowed_files,
                    context_paths=context_paths,
                    metadata={
                        "workspace_session_id": session.session_id,
                        "source_path": str(session.source_path.resolve()),
                        "worktree_path": str(session.worktree_path.resolve()),
                        "multi_pass_id": batch.id,
                        "multi_pass_index": index,
                        "multi_pass_total": len(parsed_plan.batches),
                    },
                )
            )
            latest_filesystem_result = fs_result
            provider_diagnostics = _filesystem_pass_provider_diagnostics(
                fs_result,
                pass_index=index,
                total_passes=len(parsed_plan.batches),
            )
            if fs_result.status != "completed":
                issue = RunIssue(
                    "workspace_write_executor",
                    fs_result.error_category or "filesystem_execution_failed",
                    diagnostics={
                        "executor_name": fs_result.executor_name,
                        "install_guidance": fs_result.metadata.get("install_guidance"),
                        "missing_variables": fs_result.metadata.get("missing_variables"),
                        "diagnostics": _filesystem_diagnostics_dict(
                            fs_result.diagnostics
                        ),
                    },
                )
                pass_issue = _multi_pass_issue_from_run_issue(
                    issue,
                    pass_id=batch.id,
                )
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=pass_issue,
                    all_promoted_files=tuple(all_promoted_files),
                    safe_resume_possible=bool(all_promoted_files),
                )
                return _multipass_run_result(
                    status=RUN_STATUS_FAILED,
                    issue=issue,
                    execution_mode_decision=execution_mode_decision,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=worktree_created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=None,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    multi_pass_summary=summary,
                    patch_summary=_combine_patch_summaries(tuple(completed_summaries)),
                    promoted_files=tuple(all_promoted_files),
                )

            promotion_baseline = _capture_actual_workspace_changes(
                session,
                active_workspace,
            )
            patch_summary = _summary_from_promotion_baseline(promotion_baseline)
            changed_files = _promotion_baseline_paths(promotion_baseline)
            if promotion_baseline.issue is not None:
                issue = promotion_baseline.issue
                pass_issue = _multi_pass_issue_from_run_issue(issue, pass_id=batch.id)
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=pass_issue,
                    all_promoted_files=tuple(all_promoted_files),
                    safe_resume_possible=bool(all_promoted_files),
                )
                return _multipass_run_result(
                    status=RUN_STATUS_FAILED,
                    issue=issue,
                    execution_mode_decision=execution_mode_decision,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=worktree_created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=None,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    multi_pass_summary=summary,
                    patch_summary=_combine_patch_summaries(
                        tuple(
                            summary
                            for summary in (*completed_summaries, patch_summary)
                            if summary is not None
                        )
                    ),
                    promoted_files=tuple(all_promoted_files),
                    filesystem_result=latest_filesystem_result,
                )

            promotion_result = _promote_actual_workspace_changes(promotion_baseline)
            if promotion_result.status not in {"applied", "skipped"}:
                issue = promotion_result.issue or RunIssue(
                    "promotion",
                    "promotion_not_applied",
                )
                pass_issue = _multi_pass_issue_from_run_issue(issue, pass_id=batch.id)
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=pass_issue,
                    all_promoted_files=tuple(all_promoted_files),
                    safe_resume_possible=bool(all_promoted_files),
                )
                return _multipass_run_result(
                    status=RUN_STATUS_FAILED,
                    issue=issue,
                    execution_mode_decision=execution_mode_decision,
                    session=session,
                    active_workspace=active_workspace,
                    worktree_created=worktree_created,
                    discovery_result=discovery_result,
                    dry_run_result=dry_run_result,
                    patch_result=None,
                    selected_source_refs=selected_source_refs,
                    git_preparation=git_preparation,
                    multi_pass_summary=summary,
                    patch_summary=_combine_patch_summaries(
                        tuple(
                            summary
                            for summary in (*completed_summaries, patch_summary)
                            if summary is not None
                        )
                    ),
                    promoted_files=tuple(all_promoted_files),
                    promotion_status=promotion_result.status,
                    promotion_issue=promotion_result.issue,
                    filesystem_result=latest_filesystem_result,
                )

            pass_promoted_files = tuple(
                path
                for path in promotion_result.promoted_files
                if path not in changed_files_before_pass
            )
            batch_warnings: list[str] = []
            for path in pass_promoted_files:
                if batch.allowed_files and path not in set(batch.allowed_files):
                    warning = f"multi_pass_path_outside_allowed_files:{path}"
                    batch_warnings.append(warning)
                    multi_pass_warnings.append(warning)
            if patch_summary is not None:
                completed_summaries.append(patch_summary)
            completed_files.extend(pass_promoted_files)
            for promoted_file in promotion_result.promoted_files:
                if promoted_file not in all_promoted_files:
                    all_promoted_files.append(promoted_file)
            self._emit_progress(
                "multi_pass_workspace_state_refreshed",
                "SFE: multi-pass workspace state refreshed",
                refreshed_file_count=len(all_promoted_files),
            )
            pass_results.append(
                MultiPassBatchResult(
                    pass_id=batch.id,
                    title=batch.title,
                    status="completed",
                    allowed_files=batch.allowed_files,
                    created_files=patch_summary.created_paths if patch_summary else (),
                    promoted_files=pass_promoted_files,
                    patch_paths=changed_files,
                    provider_diagnostics=provider_diagnostics,
                    warnings=tuple(dict.fromkeys(batch_warnings)),
                )
            )
            self._emit_progress(
                "multi_pass_pass_completed",
                f"SFE: multi-pass pass {index}/{len(parsed_plan.batches)} completed",
                multi_pass_index=index,
                multi_pass_total=len(parsed_plan.batches),
                multi_pass_id=batch.id,
                promoted_file_count=len(pass_promoted_files),
            )
            _refresh_multipass_contract(
                workspace_root=active_workspace,
                task=request.task,
                base_source_refs=refresh_base_refs,
                refreshed_paths=tuple(all_promoted_files),
            )

        aggregate_summary = _combine_patch_summaries(tuple(completed_summaries))
        multi_pass_summary = _build_multi_pass_summary(
            status="completed",
            project_summary=parsed_plan.project_summary,
            passes_total=len(parsed_plan.batches),
            pass_results=tuple(pass_results),
            all_promoted_files=tuple(all_promoted_files),
        )
        self._emit_progress(
            "promotion_completed",
            "SFE: promotion completed",
            promoted_file_count=len(all_promoted_files),
        )
        return RunResult(
            status=RUN_STATUS_COMPLETED,
            execution_mode_decision=execution_mode_decision,
            workspace_session=session,
            active_workspace=active_workspace,
            worktree_created=worktree_created,
            discovery_result=discovery_result,
            dry_run_result=dry_run_result,
            patch_result=None,
            patch_generated=False,
            patch_applied=False,
            patch_summary=aggregate_summary,
            changed_files=aggregate_summary.paths if aggregate_summary else (),
            selected_source_refs=selected_source_refs,
            executor_provider=(
                latest_filesystem_result.executor_name
                if latest_filesystem_result is not None
                else AIDER_EXECUTOR_NAME
            ),
            warnings=tuple(
                dict.fromkeys(
                    (*_warnings_for_summary(aggregate_summary), *multi_pass_warnings)
                )
            ),
            git_auto_init=git_preparation.auto_initialized,
            git_initial_commit_hash=git_preparation.initial_commit_hash,
            git_init_warning=git_preparation.warning,
            promotion_status="applied" if all_promoted_files else "skipped",
            promotion_applied=bool(all_promoted_files),
            promoted_files=tuple(all_promoted_files),
            multi_pass_summary=multi_pass_summary,
            filesystem_result=latest_filesystem_result,
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
                RunProgressEvent(
                    name=name,
                    message=message,
                    metadata=dict(metadata),
                )
            )
        except Exception:
            return

    def _prepare_git_workspace(self, request: RunRequest) -> GitPreparationResult:
        if request.workspace_session is not None:
            return GitPreparationResult(ok=True)
        return self.git_preparer.prepare(request.workspace_root)

    def _run_console_output(
        self,
        request: RunRequest,
        execution_mode_decision: ExecutionModeDecision,
    ) -> RunResult:
        contract = build_contract(
            workspace_root=request.workspace_root,
            task=request.task,
            file_paths=[],
            context_files=[],
        )
        self._emit_progress("executor_prompt_prepared", "SFE: executor prompt prepared")
        try:
            console_result = self.backend.console(contract)
        except NotImplementedError:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue("console_output", "console_not_supported"),
                execution_mode_decision=execution_mode_decision,
                warnings=("console_output_failed",),
            )
        if not console_result.answer:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue(
                    "console_output",
                    console_result.error_category or "invalid_response",
                ),
                execution_mode_decision=execution_mode_decision,
                executor_provider=_executor_provider(console_result),
                warnings=("console_output_failed",),
            )
        self._emit_progress(
            "console_answer_generated",
            "SFE: console answer generated",
            provider_name=_executor_provider(console_result),
        )
        return RunResult(
            status=RUN_STATUS_COMPLETED,
            execution_mode_decision=execution_mode_decision,
            console_output=console_result.answer,
            executor_provider=_executor_provider(console_result),
            warnings=("no_workspace_write_attempted",),
        )

    def _ensure_worktree(
        self,
        request: RunRequest,
    ) -> tuple[WorkspaceSession, Path, bool] | RunResult:
        if request.workspace_session is not None:
            status_result = self.workspace_manager.status(request.workspace_session)
            if not status_result.ok:
                issue = _run_issue_from_workspace(status_result.issue)
                return RunResult(
                    status=RUN_STATUS_FAILED,
                    issue=issue,
                    workspace_session=request.workspace_session,
                    active_workspace=_active_path_for_session(request.workspace_session),
                    warnings=_base_warnings(),
                )
            return (
                request.workspace_session,
                _active_path_for_session(request.workspace_session),
                False,
            )

        created = self.workspace_manager.create(
            request.workspace_root,
            request.workspace_policy,
        )
        if not created.created or created.session is None:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=_run_issue_from_workspace(created.issue),
                warnings=_base_warnings(),
            )
        session = created.session
        return session, _active_path_for_session(session), True

    def _parse_patch_response(
        self,
        workspace_root: Path,
        result: ExecutionResult,
        *,
        completed_files: tuple[str, ...] = (),
        existing_update_files: tuple[str, ...] = (),
    ) -> RunPatchProposal | RunIssue:
        raw_answer = result.answer or ""
        file_blocks = _parse_sfe_file_block_response(workspace_root, raw_answer)
        if file_blocks is not None:
            return file_blocks

        structured = parse_structured_file_patch_json(raw_answer)
        if structured.proposal is not None and structured.summary is not None:
            preview = generate_structured_file_patch_diff_preview(
                workspace_root,
                structured.proposal,
            )
            proposal = StructuredFilePatch(structured.proposal.edits, preview or None)
            run_proposal = RunPatchProposal(
                proposal=proposal,
                summary=summarize_structured_file_patch(proposal),
                preview=preview,
                parse_status="structured_replacements",
            )
            return _normalize_same_run_create_patches(
                workspace_root,
                run_proposal,
                completed_files=completed_files,
                existing_update_files=existing_update_files,
            )

        return self._parse_unified_diff_response(
            workspace_root,
            result,
            completed_files=completed_files,
            existing_update_files=existing_update_files,
        )

    def _parse_unified_diff_response(
        self,
        workspace_root: Path,
        result: ExecutionResult,
        *,
        completed_files: tuple[str, ...] = (),
        existing_update_files: tuple[str, ...] = (),
    ) -> RunPatchProposal | RunIssue:
        raw_answer = result.answer or ""
        diff_text = raw_answer
        parse_status = "unified_diff"
        diff_parsed = parse_unified_diff(diff_text)
        if (
            diff_parsed.patch is None
            and diff_parsed.issue is not None
            and diff_parsed.issue.reason == "missing_diff_header"
        ):
            tolerated_diff = _extract_tolerated_workspace_diff(raw_answer)
            if tolerated_diff is not None:
                diff_text, parse_status = tolerated_diff
                diff_parsed = parse_unified_diff(diff_text)
            else:
                diff_suffix = _extract_workspace_diff_suffix(raw_answer)
                if diff_suffix is not None:
                    diff_text = diff_suffix
                    parse_status = "malformed_extracted_unified_diff"
                    diff_parsed = parse_unified_diff(diff_text)
        if diff_parsed.patch is None or diff_parsed.summary is None:
            if (
                _is_hunk_accounting_issue(diff_parsed.issue)
                or parse_status == "malformed_extracted_unified_diff"
            ):
                recovered = _recover_new_file_patch_from_malformed_diff(diff_text)
                if recovered is not None:
                    summary = summarize_structured_file_patch(recovered)
                    return RunPatchProposal(
                        proposal=recovered,
                        summary=summary,
                        preview=generate_structured_file_patch_diff_preview(
                            workspace_root,
                            recovered,
                        )
                        or diff_text,
                        parse_status="recovered_new_file_diff",
                    )
            if _is_missing_file_transport_issue(diff_parsed.issue, raw_answer):
                return RunIssue(
                    "invalid_patch_proposal",
                    "executor_produced_no_files",
                )
            if _patch_hunk_count_normalization_enabled() and _is_hunk_accounting_issue(
                diff_parsed.issue
            ):
                normalized = normalize_unified_diff_hunk_counts(diff_text)
                if normalized.issue is not None:
                    return _run_issue_from_patch(
                        normalized.issue,
                        default_reason="patch_not_parseable",
                    )
                if normalized.normalized_text is not None and normalized.diagnostics.applied:
                    normalized_parsed = parse_unified_diff(normalized.normalized_text)
                    if (
                        normalized_parsed.patch is not None
                        and normalized_parsed.summary is not None
                    ):
                        parsed_proposal = RunPatchProposal(
                            proposal=normalized_parsed.patch,
                            summary=normalized_parsed.summary,
                            preview=normalized.normalized_text,
                            parse_status="unified_diff_hunk_counts_normalized",
                            hunk_count_normalization=normalized.diagnostics,
                        )
                        normalized_proposal = _normalize_same_run_create_patches(
                            workspace_root,
                            parsed_proposal,
                            completed_files=completed_files,
                            existing_update_files=existing_update_files,
                        )
                        if isinstance(normalized_proposal, RunIssue):
                            return normalized_proposal
                        validation = validate_patch_targets(
                            workspace_root,
                            normalized_proposal.proposal,
                        )
                        if not validation.ok:
                            return _run_issue_from_patch(
                                validation.issue,
                                default_reason="patch_not_applicable",
                            )
                        return RunPatchProposal(
                            proposal=validation.patch or normalized_proposal.proposal,
                            summary=validation.summary or normalized_proposal.summary,
                            preview=normalized_proposal.preview,
                            parse_status=normalized_proposal.parse_status,
                            hunk_count_normalization=normalized_proposal.hunk_count_normalization,
                        )
                    return _run_issue_from_patch(
                        normalized_parsed.issue,
                        default_reason="patch_not_parseable",
                    )
            return _run_issue_from_patch(
                diff_parsed.issue,
                default_reason="patch_not_parseable",
            )
        parsed_proposal = RunPatchProposal(
            proposal=diff_parsed.patch,
            summary=diff_parsed.summary,
            preview=diff_text,
            parse_status=parse_status,
        )
        normalized_proposal = _normalize_same_run_create_patches(
            workspace_root,
            parsed_proposal,
            completed_files=completed_files,
            existing_update_files=existing_update_files,
        )
        if isinstance(normalized_proposal, RunIssue):
            return normalized_proposal
        validation = validate_patch_targets(workspace_root, normalized_proposal.proposal)
        if not validation.ok:
            return _run_issue_from_patch(validation.issue, default_reason="patch_not_applicable")
        return RunPatchProposal(
            proposal=validation.patch or normalized_proposal.proposal,
            summary=validation.summary or normalized_proposal.summary,
            preview=normalized_proposal.preview,
            parse_status=normalized_proposal.parse_status,
        )


def _parse_sfe_file_block_response(
    workspace_root: Path,
    raw_answer: str,
) -> RunPatchProposal | RunIssue | None:
    lines = raw_answer.splitlines(keepends=True)
    if not any(SFE_FILE_START_RE.match(line.rstrip("\r\n")) for line in lines):
        return None

    edits: list[StructuredFileEdit] = []
    seen_paths: set[str] = set()
    noncanonical_closing_recovered = False
    eof_closing_recovered = False
    index = 0
    while index < len(lines):
        marker_line = lines[index].rstrip("\r\n")
        start_match = SFE_FILE_START_RE.match(marker_line)
        if start_match is None:
            # SFE_FILE is an extraction protocol, not a whole-response grammar.
            # Ignore prose outside blocks and enforce structure only after a
            # valid block start marker has been found.
            index += 1
            continue

        path = start_match.group("path")
        invalid_reason = _invalid_sfe_file_block_path_reason(path)
        if invalid_reason is not None:
            return RunIssue("invalid_patch_proposal", invalid_reason, path)
        if path in seen_paths:
            return RunIssue("invalid_patch_proposal", "duplicate_sfe_file_block", path)
        seen_paths.add(path)

        index += 1
        content_parts: list[str] = []
        found_end = False
        while index < len(lines):
            content_line = lines[index].rstrip("\r\n")
            closing_kind = sfe_file_closing_marker_kind(content_line)
            if closing_kind is not None:
                found_end = True
                if closing_kind == "noncanonical":
                    noncanonical_closing_recovered = True
                index += 1
                break
            if SFE_FILE_START_RE.match(content_line):
                return RunIssue(
                    "invalid_patch_proposal",
                    "malformed_sfe_file_block",
                    path,
                    diagnostics={"detail": "new_sfe_file_start_before_closing_marker"},
                )
            content_parts.append(lines[index])
            index += 1
        if not found_end:
            if index == len(lines) and "".join(content_parts):
                eof_closing_recovered = True
            else:
                return RunIssue(
                    "invalid_patch_proposal",
                    "malformed_sfe_file_block",
                    path,
                    diagnostics={"detail": "missing_sfe_file_closing_marker"},
                )

        action = (
            SUPPORTED_REPLACE_ACTION
            if (workspace_root / path).exists()
            else SUPPORTED_CREATE_ACTION
        )
        edits.append(
            StructuredFileEdit(
                path=path,
                action=action,
                content="".join(content_parts),
            )
        )

    if not edits:
        return RunIssue("invalid_patch_proposal", "executor_produced_no_files")

    proposal = StructuredFilePatch(tuple(edits), diff_preview=raw_answer)
    preview = generate_structured_file_patch_diff_preview(workspace_root, proposal)
    parse_status = "canonical_sfe_file_blocks_used"
    if noncanonical_closing_recovered and eof_closing_recovered:
        parse_status = "noncanonical_and_eof_sfe_file_closing_marker_recovered"
    elif noncanonical_closing_recovered:
        parse_status = "noncanonical_sfe_file_closing_marker_recovered"
    elif eof_closing_recovered:
        parse_status = "eof_sfe_file_closing_marker_recovered"

    return RunPatchProposal(
        proposal=proposal,
        summary=summarize_structured_file_patch(proposal),
        preview=preview or raw_answer,
        parse_status=parse_status,
    )


def _invalid_sfe_file_block_path_reason(path: str) -> str | None:
    if is_invalid_sfe_file_path(path):
        return "invalid_sfe_file_path"
    return None


def _is_missing_file_transport_issue(
    issue: PatchIssue | None,
    raw_answer: str,
) -> bool:
    if issue is None or issue.reason != "missing_diff_header":
        return False
    return "diff --git " not in raw_answer and "<<<SFE_FILE " not in raw_answer


def _extract_tolerated_workspace_diff(raw_answer: str) -> tuple[str, str] | None:
    fenced_diff = extract_single_fenced_git_diff(raw_answer)
    if fenced_diff is not None:
        return fenced_diff, "fenced_unified_diff"
    extracted_diff = extract_first_parseable_git_diff_segment(raw_answer)
    if extracted_diff is not None:
        return extracted_diff, "extracted_unified_diff"
    return None


def _extract_workspace_diff_suffix(raw_answer: str) -> str | None:
    lines = raw_answer.splitlines()
    for index, line in enumerate(lines):
        if line.startswith("diff --git "):
            return "\n".join(lines[index:])
    return None


_DIFF_HEADER_LINE_RE = re.compile(r"^diff --git a/(?P<old>[^ ]+) b/(?P<new>[^ ]+)$")


def _recover_new_file_patch_from_malformed_diff(
    diff_text: str,
) -> StructuredFilePatch | None:
    lines = diff_text.splitlines()
    if not lines:
        return None
    header_indexes = [
        index for index, line in enumerate(lines) if line.startswith("diff --git ")
    ]
    if not header_indexes:
        return None
    edits: list[StructuredFileEdit] = []
    seen_paths: set[str] = set()
    for position, start in enumerate(header_indexes):
        end = (
            header_indexes[position + 1]
            if position + 1 < len(header_indexes)
            else len(lines)
        )
        edit = _recover_new_file_edit_from_diff_block(lines[start:end])
        if edit is None or edit.path in seen_paths:
            return None
        edits.append(edit)
        seen_paths.add(edit.path)
    if not edits:
        return None
    return StructuredFilePatch(tuple(edits), diff_preview=diff_text)


def _recover_new_file_edit_from_diff_block(
    block_lines: list[str],
) -> StructuredFileEdit | None:
    if not block_lines:
        return None
    header_match = _DIFF_HEADER_LINE_RE.match(block_lines[0])
    if header_match is None:
        return None
    old_path = header_match.group("old")
    new_path = header_match.group("new")
    if old_path != new_path:
        return None
    old_header = f"--- /dev/null"
    new_header = f"+++ b/{new_path}"
    if old_header not in block_lines or new_header not in block_lines:
        return None

    added_lines: list[str] = []
    in_hunk = False
    saw_hunk = False
    saw_added_line = False
    for line in block_lines[1:]:
        if line.startswith("@@ "):
            in_hunk = True
            saw_hunk = True
            continue
        if line.startswith("\\"):
            continue
        if not in_hunk:
            if (
                line.startswith("index ")
                or line.startswith("new file mode ")
                or line == old_header
                or line == new_header
            ):
                continue
            return None
        if line.startswith("+") and not line.startswith("+++ "):
            added_lines.append(line[1:])
            saw_added_line = True
            continue
        if line.startswith("-") or line.startswith(" "):
            return None
        return None
    if not saw_hunk:
        return None
    content = "\n".join(added_lines)
    if saw_added_line:
        content += "\n"
    return StructuredFileEdit(
        path=new_path,
        action=SUPPORTED_CREATE_ACTION,
        content=content,
    )


def _apply_run_patch_proposal(
    workspace_root: Path,
    worktree_root: Path,
    proposal: RunPatchProposal,
) -> PatchApplyResult:
    if (
        proposal.parse_status == "recovered_new_file_diff"
        and isinstance(proposal.proposal, StructuredFilePatch)
    ):
        return _apply_recovered_new_file_patch(
            workspace_root,
            worktree_root,
            proposal.proposal,
        )
    return _apply_run_patch(workspace_root, proposal.proposal)


def _apply_recovered_new_file_patch(
    workspace_root: Path,
    worktree_root: Path,
    proposal: StructuredFilePatch,
) -> PatchApplyResult:
    root = workspace_root.resolve()
    worktree = worktree_root.resolve()
    written: list[tuple[Path, bytes | None]] = []
    created_dirs: list[Path] = []
    try:
        for edit in proposal.edits:
            if edit.action != SUPPORTED_CREATE_ACTION:
                return PatchApplyResult(
                    False,
                    PatchIssue("invalid_patch_proposal", "unrecoverable_patch_response", edit.path),
                    None,
                    True,
                )
            target = root / edit.path
            try:
                resolved_target = target.resolve(strict=False)
                resolved_target.relative_to(worktree)
            except ValueError:
                return PatchApplyResult(
                    False,
                    PatchIssue("workspace_boundary", "changed_path_outside_destination", edit.path),
                    None,
                    True,
                )
            created_dirs.extend(_ensure_parent_dirs(resolved_target.parent))
            with resolved_target.open("xb") as handle:
                handle.write(edit.content.encode("utf-8"))
            written.append((resolved_target, None))
    except OSError:
        _rollback_recovered_new_files(written)
        _cleanup_created_dirs(created_dirs)
        return PatchApplyResult(
            False,
            PatchIssue("physical_write_failure", "write_error", None),
            None,
            False,
        )
    return PatchApplyResult(True, None, summarize_structured_file_patch(proposal), True)


def _rollback_recovered_new_files(written: list[tuple[Path, bytes | None]]) -> None:
    for target, original_bytes in reversed(written):
        if original_bytes is not None:
            continue
        try:
            target.unlink(missing_ok=True)
        except OSError:
            continue


def _apply_run_patch(
    workspace_root: Path,
    proposal: StructuredFilePatch | ParsedPatch,
) -> PatchApplyResult:
    if isinstance(proposal, ParsedPatch):
        return apply_patch_to_workspace(workspace_root, proposal)
    return apply_structured_file_patch(workspace_root, proposal)


def _patch_failed_result(
    issue: PatchIssue | None,
    *,
    session: WorkspaceSession,
    active_workspace: Path,
    worktree_created: bool,
    discovery_result: DiscoveryResult,
    dry_run_result: ExecutionResult,
    patch_result: ExecutionResult,
    proposal: RunPatchProposal,
    selected_source_refs: tuple[str, ...],
    git_preparation: GitPreparationResult,
    execution_mode_decision: ExecutionModeDecision,
) -> RunResult:
    return RunResult(
        status=RUN_STATUS_FAILED,
        issue=_run_issue_from_patch(issue, default_reason="patch_not_applicable"),
        execution_mode_decision=execution_mode_decision,
        workspace_session=session,
        active_workspace=active_workspace,
        worktree_created=worktree_created,
        discovery_result=discovery_result,
        dry_run_result=dry_run_result,
        patch_result=patch_result,
        patch_generated=True,
        patch_applied=False,
        patch_summary=proposal.summary,
        selected_source_refs=selected_source_refs,
        executor_provider=_executor_provider(patch_result),
        warnings=_warnings_for_summary_and_proposal(proposal.summary, proposal),
        git_auto_init=git_preparation.auto_initialized,
        git_initial_commit_hash=git_preparation.initial_commit_hash,
        git_init_warning=git_preparation.warning,
        patch_hunk_count_normalization=proposal.hunk_count_normalization,
    )


def _promotion_failed_result(
    issue: RunIssue,
    *,
    session: WorkspaceSession,
    active_workspace: Path,
    worktree_created: bool,
    discovery_result: DiscoveryResult,
    dry_run_result: ExecutionResult,
    patch_result: ExecutionResult,
    proposal: RunPatchProposal,
    selected_source_refs: tuple[str, ...],
    git_preparation: GitPreparationResult,
    execution_mode_decision: ExecutionModeDecision,
    patch_applied: bool,
    patch_summary: PatchSummary | None = None,
    changed_files: tuple[str, ...] = (),
    promotion_result: PromotionResult | None = None,
) -> RunResult:
    return RunResult(
        status=RUN_STATUS_FAILED,
        issue=issue,
        execution_mode_decision=execution_mode_decision,
        workspace_session=session,
        active_workspace=active_workspace,
        worktree_created=worktree_created,
        discovery_result=discovery_result,
        dry_run_result=dry_run_result,
        patch_result=patch_result,
        patch_generated=True,
        patch_applied=patch_applied,
        patch_summary=patch_summary or proposal.summary,
        changed_files=changed_files,
        selected_source_refs=selected_source_refs,
        executor_provider=_executor_provider(patch_result),
        warnings=_warnings_for_summary_and_proposal(
            patch_summary or proposal.summary,
            proposal,
        ),
        git_auto_init=git_preparation.auto_initialized,
        git_initial_commit_hash=git_preparation.initial_commit_hash,
        git_init_warning=git_preparation.warning,
        promotion_status=promotion_result.status if promotion_result else "rejected",
        promotion_applied=False,
        promoted_files=promotion_result.promoted_files if promotion_result else (),
        promotion_issue=issue,
        patch_hunk_count_normalization=proposal.hunk_count_normalization,
    )


def _workspace_write_failed_result(
    issue: RunIssue,
    *,
    session: WorkspaceSession,
    active_workspace: Path,
    worktree_created: bool,
    discovery_result: DiscoveryResult,
    dry_run_result: ExecutionResult,
    patch_result: ExecutionResult,
    proposal: RunPatchProposal | None,
    selected_source_refs: tuple[str, ...],
    git_preparation: GitPreparationResult,
    execution_mode_decision: ExecutionModeDecision,
    patch_applied: bool,
    patch_summary: PatchSummary | None,
    changed_files: tuple[str, ...],
    promotion_result: PromotionResult | None = None,
    patch_proposal_diagnostics: PatchProposalDiagnostics | None = None,
) -> RunResult:
    return RunResult(
        status=RUN_STATUS_FAILED,
        issue=issue,
        execution_mode_decision=execution_mode_decision,
        workspace_session=session,
        active_workspace=active_workspace,
        worktree_created=worktree_created,
        discovery_result=discovery_result,
        dry_run_result=dry_run_result,
        patch_result=patch_result,
        patch_generated=proposal is not None,
        patch_applied=patch_applied,
        patch_summary=patch_summary,
        changed_files=changed_files,
        selected_source_refs=selected_source_refs,
        executor_provider=_executor_provider(patch_result),
        warnings=_warnings_for_summary_and_proposal(patch_summary, proposal),
        git_auto_init=git_preparation.auto_initialized,
        git_initial_commit_hash=git_preparation.initial_commit_hash,
        git_init_warning=git_preparation.warning,
        promotion_status=promotion_result.status if promotion_result else "rejected",
        promotion_applied=False,
        promoted_files=promotion_result.promoted_files if promotion_result else (),
        promotion_issue=issue,
        patch_proposal_diagnostics=patch_proposal_diagnostics,
        patch_hunk_count_normalization=(
            proposal.hunk_count_normalization if proposal is not None else None
        ),
    )


def _filesystem_workspace_write_failed_result(
    filesystem_result: FilesystemExecutionResult,
    *,
    execution_mode_decision: ExecutionModeDecision,
    session: WorkspaceSession,
    active_workspace: Path,
    worktree_created: bool,
    discovery_result: DiscoveryResult,
    dry_run_result: ExecutionResult,
    selected_source_refs: tuple[str, ...],
    git_preparation: GitPreparationResult,
    issue: RunIssue | None = None,
    patch_summary: PatchSummary | None = None,
    changed_files: tuple[str, ...] = (),
    promotion_result: PromotionResult | None = None,
) -> RunResult:
    effective_issue = issue or RunIssue(
        "workspace_write_executor",
        filesystem_result.error_category or "filesystem_execution_failed",
        diagnostics={
            "executor_name": filesystem_result.executor_name,
            "install_guidance": filesystem_result.metadata.get("install_guidance"),
            "diagnostics": _filesystem_diagnostics_dict(
                filesystem_result.diagnostics
            ),
        },
    )
    return RunResult(
        status=RUN_STATUS_FAILED,
        issue=effective_issue,
        execution_mode_decision=execution_mode_decision,
        workspace_session=session,
        active_workspace=active_workspace,
        worktree_created=worktree_created,
        discovery_result=discovery_result,
        dry_run_result=dry_run_result,
        patch_result=None,
        patch_generated=False,
        patch_applied=False,
        patch_summary=patch_summary,
        changed_files=changed_files,
        selected_source_refs=selected_source_refs,
        executor_provider=filesystem_result.executor_name,
        warnings=_warnings_for_summary(patch_summary),
        git_auto_init=git_preparation.auto_initialized,
        git_initial_commit_hash=git_preparation.initial_commit_hash,
        git_init_warning=git_preparation.warning,
        promotion_status=promotion_result.status if promotion_result else "skipped",
        promotion_applied=False,
        promoted_files=promotion_result.promoted_files if promotion_result else (),
        promotion_issue=effective_issue if issue is not None else None,
        filesystem_result=filesystem_result,
    )


def _multipass_run_result(
    *,
    status: str,
    issue: RunIssue | None,
    execution_mode_decision: ExecutionModeDecision,
    session: WorkspaceSession,
    active_workspace: Path,
    worktree_created: bool,
    discovery_result: DiscoveryResult,
    dry_run_result: ExecutionResult,
    patch_result: ExecutionResult | None,
    selected_source_refs: tuple[str, ...],
    git_preparation: GitPreparationResult,
    multi_pass_summary: MultiPassRunSummary,
    patch_summary: PatchSummary | None = None,
    promoted_files: tuple[str, ...] = (),
    patch_proposal_diagnostics: PatchProposalDiagnostics | None = None,
    promotion_status: str = "skipped",
    promotion_issue: RunIssue | None = None,
    filesystem_result: FilesystemExecutionResult | None = None,
) -> RunResult:
    return RunResult(
        status=status,
        issue=issue,
        execution_mode_decision=execution_mode_decision,
        workspace_session=session,
        active_workspace=active_workspace,
        worktree_created=worktree_created,
        discovery_result=discovery_result,
        dry_run_result=dry_run_result,
        patch_result=patch_result,
        patch_generated=patch_summary is not None,
        patch_applied=False,
        patch_summary=patch_summary,
        changed_files=patch_summary.paths if patch_summary is not None else (),
        selected_source_refs=selected_source_refs,
        executor_provider=_executor_provider(patch_result),
        warnings=_warnings_for_summary(patch_summary),
        git_auto_init=git_preparation.auto_initialized,
        git_initial_commit_hash=git_preparation.initial_commit_hash,
        git_init_warning=git_preparation.warning,
        promotion_status=promotion_status,
        promotion_applied=False,
        promoted_files=promoted_files,
        promotion_issue=promotion_issue,
        patch_proposal_diagnostics=patch_proposal_diagnostics,
        multi_pass_summary=multi_pass_summary,
        filesystem_result=filesystem_result,
    )


def _failed(category: str, reason: str) -> RunResult:
    return RunResult(
        status=RUN_STATUS_FAILED,
        issue=RunIssue(category, reason),
        warnings=_base_warnings(),
    )


def _with_git_preparation(
    result: RunResult,
    git_preparation: GitPreparationResult,
) -> RunResult:
    return replace(
        result,
        git_auto_init=git_preparation.auto_initialized,
        git_initial_commit_hash=git_preparation.initial_commit_hash,
        git_init_warning=git_preparation.warning,
    )


def _run_issue_from_workspace(issue: WorkspaceIssue | None) -> RunIssue:
    if issue is None:
        return RunIssue("workspace", "workspace_unavailable")
    return RunIssue(issue.category, issue.reason)


def _run_issue_from_patch(
    issue: PatchIssue | None,
    *,
    default_reason: str,
) -> RunIssue:
    if issue is None:
        return RunIssue("patch", default_reason)
    category = issue.category or MECHANICAL_GUARD_REJECTED
    return RunIssue(category, issue.reason, issue.path, issue.hunk_accounting)


def _run_issue_from_multipass(issue: MultiPassIssue) -> RunIssue:
    return RunIssue(issue.category, issue.reason, issue.path, diagnostics=issue.diagnostics)


def _multi_pass_issue_from_run_issue(
    issue: RunIssue,
    *,
    pass_id: str | None = None,
    diagnostics: dict[str, object] | None = None,
) -> MultiPassIssue:
    return MultiPassIssue(
        category=issue.category,
        reason=issue.reason,
        path=issue.path,
        pass_id=pass_id,
        diagnostics=diagnostics if diagnostics is not None else issue.diagnostics,
    )


def _failed_batch_result(
    batch: MultiPassBatch,
    *,
    issue: MultiPassIssue,
    provider_diagnostics: dict[str, object] | None,
    executor_contract_diagnostics: dict[str, tuple[str, ...]] | None = None,
) -> MultiPassBatchResult:
    diagnostics = executor_contract_diagnostics or _empty_executor_contract_diagnostics()
    return MultiPassBatchResult(
        pass_id=batch.id,
        title=batch.title,
        status="failed",
        allowed_files=batch.allowed_files,
        provider_diagnostics=provider_diagnostics,
        full_content_provided_files=diagnostics["full_content_provided_files"],
        full_file_replacement_eligible_files=diagnostics[
            "full_file_replacement_eligible_files"
        ],
        full_file_replacement_used_files=diagnostics[
            "full_file_replacement_used_files"
        ],
        issue=issue,
    )


def _build_multi_pass_summary(
    *,
    status: str,
    project_summary: str | None = None,
    passes_total: int = 0,
    pass_results: tuple[MultiPassBatchResult, ...] = (),
    failed_issue: MultiPassIssue | None = None,
    all_promoted_files: tuple[str, ...] = (),
    safe_resume_possible: bool = False,
) -> MultiPassRunSummary:
    created_by_pass = {
        result.pass_id: result.created_files
        for result in pass_results
        if result.created_files
    }
    promoted_by_pass = {
        result.pass_id: result.promoted_files
        for result in pass_results
        if result.promoted_files
    }
    return MultiPassRunSummary(
        enabled=True,
        status=status,
        project_summary=project_summary,
        passes_total=passes_total,
        passes_completed=sum(1 for result in pass_results if result.status == "completed"),
        failed_pass_id=failed_issue.pass_id if failed_issue is not None else None,
        failed_pass_issue=failed_issue,
        created_files_by_pass=created_by_pass,
        promoted_files_by_pass=promoted_by_pass,
        all_promoted_files=all_promoted_files,
        safe_resume_possible=safe_resume_possible,
        pass_results=pass_results,
    )


def _combine_patch_summaries(
    summaries: tuple[PatchSummary, ...],
) -> PatchSummary | None:
    if not summaries:
        return None
    return PatchSummary(
        paths=_dedupe_paths(path for summary in summaries for path in summary.paths),
        file_count=len(_dedupe_paths(path for summary in summaries for path in summary.paths)),
        hunk_count=sum(summary.hunk_count for summary in summaries),
        lines_added=sum(summary.lines_added for summary in summaries),
        lines_removed=sum(summary.lines_removed for summary in summaries),
        modified_paths=_dedupe_paths(
            path for summary in summaries for path in summary.modified_paths
        ),
        created_paths=_dedupe_paths(
            path for summary in summaries for path in summary.created_paths
        ),
        refused_paths=_dedupe_paths(
            path for summary in summaries for path in summary.refused_paths
        ),
        refused_reasons=tuple(
            reason for summary in summaries for reason in summary.refused_reasons
        ),
    )


def _refresh_multipass_contract(
    *,
    workspace_root: Path,
    task: str,
    base_source_refs: tuple[str, ...],
    refreshed_paths: tuple[str, ...],
) -> SFEContract:
    refs = _dedupe_paths((*base_source_refs, *refreshed_paths))
    context_files = [load_discovery_context_file(workspace_root, path) for path in refs]
    return build_contract(
        workspace_root=workspace_root,
        task=task,
        file_paths=[],
        context_files=context_files,
    )


def _normalize_same_run_create_patches(
    workspace_root: Path,
    proposal: RunPatchProposal,
    *,
    completed_files: tuple[str, ...],
    existing_update_files: tuple[str, ...] = (),
) -> RunPatchProposal | RunIssue:
    if not completed_files and not existing_update_files:
        return proposal
    completed = set((*completed_files, *existing_update_files))
    if isinstance(proposal.proposal, StructuredFilePatch):
        return _normalize_same_run_structured_creates(
            workspace_root,
            proposal,
            completed,
        )
    return _normalize_same_run_unified_creates(workspace_root, proposal, completed)


def _normalize_same_run_structured_creates(
    workspace_root: Path,
    proposal: RunPatchProposal,
    completed_files: set[str],
) -> RunPatchProposal:
    changed = False
    edits: list[StructuredFileEdit] = []
    for edit in proposal.proposal.edits:  # type: ignore[union-attr]
        if edit.action == SUPPORTED_CREATE_ACTION and edit.path in completed_files:
            target = (workspace_root / edit.path).resolve()
            if target.is_file():
                edits.append(
                    StructuredFileEdit(
                        path=edit.path,
                        action=SUPPORTED_REPLACE_ACTION,
                        content=edit.content,
                    )
                )
                changed = True
                continue
        edits.append(edit)
    if not changed:
        return proposal
    normalized = StructuredFilePatch(tuple(edits), proposal.proposal.diff_preview)
    return RunPatchProposal(
        proposal=normalized,
        summary=summarize_structured_file_patch(normalized),
        preview=proposal.preview,
        parse_status=proposal.parse_status + "_same_run_create_normalized",
        hunk_count_normalization=proposal.hunk_count_normalization,
    )


def _normalize_same_run_unified_creates(
    workspace_root: Path,
    proposal: RunPatchProposal,
    completed_files: set[str],
) -> RunPatchProposal | RunIssue:
    changed = False
    files: list[ParsedFilePatch] = []
    for file_patch in proposal.proposal.files:  # type: ignore[union-attr]
        if (
            file_patch.operation == PATCH_OPERATION_CREATE
            and file_patch.new_path in completed_files
        ):
            replacement = _same_run_create_as_modify(workspace_root, file_patch)
            if isinstance(replacement, RunIssue):
                return replacement
            files.append(replacement)
            changed = True
            continue
        files.append(file_patch)
    if not changed:
        return proposal
    normalized = ParsedPatch(tuple(files))
    return RunPatchProposal(
        proposal=normalized,
        summary=summarize_patch(normalized),
        preview=proposal.preview,
        parse_status=proposal.parse_status + "_same_run_create_normalized",
        hunk_count_normalization=proposal.hunk_count_normalization,
    )


def _same_run_create_as_modify(
    workspace_root: Path,
    file_patch: ParsedFilePatch,
) -> ParsedFilePatch | RunIssue:
    target = (workspace_root / file_patch.new_path).resolve()
    if not target.is_file():
        return file_patch
    try:
        current_text = target.read_text(encoding="utf-8")
    except OSError:
        return RunIssue(
            "physical_application_failure",
            "read_error",
            file_patch.new_path,
        )
    current_lines = current_text.splitlines()
    replacement_lines = _create_patch_replacement_lines(file_patch)
    old_start = 1 if current_lines else 0
    new_start = 1 if replacement_lines else 0
    hunk = ParsedHunk(
        old_start=old_start,
        old_count=len(current_lines),
        new_start=new_start,
        new_count=len(replacement_lines),
        lines=tuple(
            [*(PatchLine("-", line) for line in current_lines)]
            + [*(PatchLine("+", line) for line in replacement_lines)]
        ),
    )
    return ParsedFilePatch(
        old_path=file_patch.new_path,
        new_path=file_patch.new_path,
        hunks=(hunk,),
        operation=PATCH_OPERATION_MODIFY,
    )


def _create_patch_replacement_lines(file_patch: ParsedFilePatch) -> list[str]:
    lines: list[str] = []
    for hunk in file_patch.hunks:
        for line in hunk.lines:
            if line.kind in {" ", "+"}:
                lines.append(line.text)
    return lines


def _existing_plan_files(workspace_root: Path, plan: MultiPassPlan) -> frozenset[str]:
    paths = {
        path
        for batch in plan.batches
        for path in batch.allowed_files
        if (workspace_root / path).exists()
    }
    return frozenset(paths)


def _paths_outside_batch(
    paths: tuple[str, ...],
    batch: MultiPassBatch,
) -> tuple[str, ...]:
    allowed = set(batch.allowed_files)
    return tuple(path for path in paths if path not in allowed)


def _full_file_replacement_lines_from_patch(
    file_patch: ParsedFilePatch,
    *,
    current_line_count: int,
) -> list[str] | None:
    if len(file_patch.hunks) != 1:
        return None
    hunk = file_patch.hunks[0]
    if hunk.old_start > 1 or hunk.new_start > 1:
        return None
    replacement_lines = [line.text for line in hunk.lines if line.kind in {" ", "+"}]
    if file_patch.new_path == "composer.json":
        return replacement_lines
    if hunk.old_count < max(1, current_line_count - 1):
        return None
    return replacement_lines


def _executor_contract_diagnostics(
    workspace_root: Path,
    patch_result: ExecutionResult,
    proposal: RunPatchProposal | None = None,
) -> dict[str, tuple[str, ...]]:
    guidance = patch_result.summary.get("full_file_replacement_guidance")
    if not isinstance(guidance, dict):
        return _empty_executor_contract_diagnostics()
    full_content_files = _string_tuple_from_object(
        guidance.get("full_content_provided_files")
    )
    eligible_files = _string_tuple_from_object(guidance.get("eligible_files"))
    used_files: tuple[str, ...] = ()
    if proposal is not None and isinstance(proposal.proposal, ParsedPatch):
        used_files = _full_file_replacement_used_files(
            workspace_root,
            proposal.proposal,
            eligible_files=eligible_files,
        )
    return {
        "full_content_provided_files": full_content_files,
        "full_file_replacement_eligible_files": eligible_files,
        "full_file_replacement_used_files": used_files,
        "full_file_replacement_source_files": _string_tuple_from_object(
            guidance.get("source_files")
        ),
        "full_file_replacement_template_files": _string_tuple_from_object(
            guidance.get("template_files")
        ),
    }


def _empty_executor_contract_diagnostics() -> dict[str, tuple[str, ...]]:
    return {
        "full_content_provided_files": (),
        "full_file_replacement_eligible_files": (),
        "full_file_replacement_used_files": (),
        "full_file_replacement_source_files": (),
        "full_file_replacement_template_files": (),
    }


def _string_tuple_from_object(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple | list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _full_file_replacement_used_files(
    workspace_root: Path,
    patch: ParsedPatch,
    *,
    eligible_files: tuple[str, ...],
) -> tuple[str, ...]:
    eligible = set(eligible_files)
    used: list[str] = []
    for file_patch in patch.files:
        path = file_patch.new_path
        if path not in eligible:
            continue
        target = workspace_root / path
        if not target.is_file():
            continue
        try:
            current_text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        replacement_lines = _full_file_replacement_lines_from_patch(
            file_patch,
            current_line_count=len(current_text.splitlines()),
        )
        if replacement_lines is not None:
            used.append(path)
    return tuple(used)


def _dedupe_paths(paths: object) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for path in paths:  # type: ignore[not-an-iterable]
        if not isinstance(path, str) or path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return tuple(deduped)


def _active_path_for_session(session: WorkspaceSession) -> Path:
    try:
        relative_source = session.source_path.relative_to(session.source_git_root)
    except ValueError:
        relative_source = Path()
    return (session.worktree_path / relative_source).resolve()


def _selected_source_refs(
    result: ExecutionResult,
    selected_ids: list[str],
) -> tuple[str, ...]:
    selected = set(selected_ids)
    return tuple(
        segment.source_ref
        for segment in result.contract.context_segments
        if segment.id in selected
    )


def _executor_provider(result: ExecutionResult | None) -> str | None:
    if result is None:
        return None
    provider = result.summary.get("executor_provider")
    return str(provider) if provider is not None else None


def _filesystem_diagnostics_dict(
    diagnostics: object,
) -> dict[str, object]:
    if not hasattr(diagnostics, "executor_name"):
        return {}
    return {
        "executor_name": getattr(diagnostics, "executor_name", None),
        "cwd": getattr(diagnostics, "cwd", None),
        "command": list(getattr(diagnostics, "command", ()) or ()),
        "return_code": getattr(diagnostics, "return_code", None),
        "stdout_length": getattr(diagnostics, "stdout_length", 0),
        "stderr_length": getattr(diagnostics, "stderr_length", 0),
        "stdout_preview": getattr(diagnostics, "stdout_preview", None),
        "stderr_preview": getattr(diagnostics, "stderr_preview", None),
        "elapsed_ms": getattr(diagnostics, "elapsed_ms", 0),
        "metadata": dict(getattr(diagnostics, "metadata", {}) or {}),
    }


def _filesystem_pass_provider_diagnostics(
    result: FilesystemExecutionResult,
    *,
    pass_index: int,
    total_passes: int,
) -> dict[str, object]:
    return {
        "provider_name": result.executor_name,
        "filesystem_executor": {
            "executor_name": result.executor_name,
            "status": result.status,
            "error_category": result.error_category,
            "changed_paths": tuple(result.changed_paths),
            "pass_index": pass_index,
            "passes_total": total_passes,
            "diagnostics": _filesystem_diagnostics_dict(result.diagnostics),
        },
    }


def _build_multipass_filesystem_task(
    *,
    user_task: str,
    plan: MultiPassPlan,
    batch: MultiPassBatch,
    pass_index: int,
    total_passes: int,
    completed_files: tuple[str, ...],
) -> str:
    allowed_files = "\n".join(f"- {path}" for path in batch.allowed_files) or "- none"
    dependencies = "\n".join(f"- {item}" for item in batch.depends_on) or "- none"
    validation_notes = (
        "\n".join(f"- {item}" for item in batch.validation_notes) or "- none"
    )
    completed = "\n".join(f"- {path}" for path in completed_files) or "- none"
    return "\n".join(
        [
            "Execute one SFE multi-pass workspace_write batch.",
            "Keep this pass small and scoped. Do not plan or implement other passes.",
            "Modify only files needed for this batch, preferably the allowed files.",
            "",
            f"Pass: {pass_index}/{total_passes}",
            f"Batch id: {batch.id}",
            f"Batch title: {batch.title}",
            "",
            "Global user task summary:",
            user_task,
            "",
            "Project plan summary:",
            plan.project_summary,
            "",
            "Batch goal:",
            batch.goal,
            "",
            "Allowed or expected editable files:",
            allowed_files,
            "",
            "Dependencies:",
            dependencies,
            "",
            "Previously promoted files:",
            completed,
            "",
            "Validation notes:",
            validation_notes,
            "",
        ]
    )


def _multipass_filesystem_context_paths(
    *,
    selected_source_refs: tuple[str, ...],
    all_promoted_files: tuple[str, ...],
    allowed_files: tuple[str, ...],
) -> tuple[str, ...]:
    candidates = (*selected_source_refs, *all_promoted_files)
    allowed = set(allowed_files)
    selected: list[str] = []
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen or path in allowed:
            continue
        seen.add(path)
        selected.append(path)
    return tuple(selected[:10])


def _is_hunk_accounting_issue(issue: PatchIssue | None) -> bool:
    return (
        issue is not None
        and issue.category == "invalid_patch_proposal"
        and issue.reason == "impossible_hunk_accounting"
    )


def _patch_hunk_count_normalization_enabled() -> bool:
    value = os.getenv("SFE_PATCH_NORMALIZE_HUNK_COUNTS", "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _estimated_reduction_label(result: ExecutionResult) -> str:
    value = result.contract.audit.get("estimated_reduction_pct")
    if value is None:
        return "unknown"
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "unknown"
    return f"{numeric:.1f}%"


def _changed_files(
    status_result: WorkspaceStatusResult,
    summary: PatchSummary,
) -> tuple[str, ...]:
    if status_result.ok and status_result.status is not None:
        return status_result.status.changed_files
    return summary.paths


def _promotion_baseline_paths(baseline: PromotionBaseline) -> tuple[str, ...]:
    return tuple(target.relative_path for target in baseline.targets)


def _summary_from_promotion_baseline(baseline: PromotionBaseline) -> PatchSummary | None:
    if baseline.issue is not None or not baseline.targets:
        return None
    paths = _promotion_baseline_paths(baseline)
    created_paths = tuple(
        target.relative_path
        for target in baseline.targets
        if target.change_kind == "created"
    )
    modified_paths = tuple(
        target.relative_path
        for target in baseline.targets
        if target.change_kind == "modified"
    )
    return PatchSummary(
        paths=paths,
        file_count=len(paths),
        hunk_count=0,
        lines_added=0,
        lines_removed=0,
        modified_paths=modified_paths,
        created_paths=created_paths,
    )


def _capture_actual_workspace_changes(
    session: WorkspaceSession,
    active_workspace: Path,
) -> PromotionBaseline:
    status_result = _git(
        session.worktree_path,
        "status",
        "--porcelain=v1",
        "-z",
        "-uall",
        "--no-renames",
    )
    if status_result.returncode != 0:
        return PromotionBaseline(
            issue=RunIssue("workspace_status", "worktree_status_failed")
        )
    committed_entries = _capture_committed_worktree_change_entries(session)
    if isinstance(committed_entries, RunIssue):
        return PromotionBaseline(issue=committed_entries)
    change_entries = _dedupe_change_entries(
        (
            *committed_entries,
            *_parse_git_status_z(status_result.stdout),
        )
    )
    active_root = active_workspace.resolve()
    source_root = session.source_path.resolve()
    try:
        active_prefix = active_root.relative_to(session.worktree_path.resolve())
    except ValueError:
        return PromotionBaseline(
            issue=RunIssue("workspace_boundary", "active_workspace_outside_worktree")
        )
    active_prefix_parts = active_prefix.parts
    targets: list[PromotionTarget] = []
    offending_paths: list[str] = []
    for status_code, worktree_relative_path in change_entries:
        worktree_relative = Path(worktree_relative_path)
        if worktree_relative.is_absolute() or ".." in worktree_relative.parts:
            offending_paths.append(worktree_relative_path)
            continue
        if active_prefix_parts:
            if worktree_relative.parts[: len(active_prefix_parts)] != active_prefix_parts:
                offending_paths.append(worktree_relative_path)
                continue
            destination_relative = Path(*worktree_relative.parts[len(active_prefix_parts) :])
        else:
            destination_relative = worktree_relative
        if not destination_relative.parts:
            offending_paths.append(worktree_relative_path)
            continue
        relative_path = destination_relative.as_posix()
        if _is_internal_promotion_path(relative_path):
            return PromotionBaseline(
                issue=RunIssue("promotion", "internal_path_not_promoted", relative_path)
            )
        worktree_target = active_root / destination_relative
        source_target = source_root / destination_relative
        deleted = "D" in status_code and not worktree_target.exists()
        issue = _validate_actual_change_target(
            source_root=source_root,
            source_target=source_target,
            active_root=active_root,
            worktree_target=worktree_target,
            relative_path=relative_path,
            deleted=deleted,
        )
        if issue is not None:
            return PromotionBaseline(issue=issue)
        source_before = _read_optional_file_bytes(source_target, relative_path)
        if isinstance(source_before, RunIssue):
            return PromotionBaseline(issue=source_before)
        change_kind = (
            "deleted"
            if deleted
            else "created"
            if source_before is None
            else "modified"
        )
        targets.append(
            PromotionTarget(
                relative_path=relative_path,
                source_path=source_target,
                worktree_path=worktree_target,
                source_before=source_before,
                change_kind=change_kind,
            )
        )
    if offending_paths:
        return PromotionBaseline(
            issue=_workspace_boundary_issue(
                offending_paths=tuple(offending_paths),
                source_root=source_root,
                active_root=active_root,
            )
        )
    return PromotionBaseline(targets=tuple(targets))


def _capture_committed_worktree_change_entries(
    session: WorkspaceSession,
) -> tuple[tuple[str, str], ...] | RunIssue:
    source_head = _source_head_for_session(session)
    if source_head is None:
        return RunIssue("workspace_status", "source_head_unavailable")
    diff_result = _git(
        session.worktree_path,
        "diff",
        "--name-status",
        "-z",
        "--no-renames",
        source_head,
        "HEAD",
    )
    if diff_result.returncode != 0:
        return RunIssue("workspace_status", "committed_worktree_diff_failed")
    return _parse_git_name_status_z(diff_result.stdout)


def _source_head_for_session(session: WorkspaceSession) -> str | None:
    source_head = session.metadata.get("source_head")
    if isinstance(source_head, str) and source_head.strip():
        return source_head.strip()
    result = _git(session.source_git_root, "rev-parse", "--verify", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _parse_git_name_status_z(status_text: str) -> tuple[tuple[str, str], ...]:
    tokens = [token for token in status_text.split("\0") if token]
    entries: list[tuple[str, str]] = []
    index = 0
    while index + 1 < len(tokens):
        status_code = tokens[index]
        path = tokens[index + 1]
        entries.append((status_code, path))
        index += 2
    return tuple(entries)


def _dedupe_change_entries(
    entries: tuple[tuple[str, str], ...],
) -> tuple[tuple[str, str], ...]:
    order: list[str] = []
    by_path: dict[str, str] = {}
    for status_code, path in entries:
        if path not in by_path:
            order.append(path)
        by_path[path] = status_code
    return tuple((by_path[path], path) for path in order)


def _parse_git_status_z(status_text: str) -> tuple[tuple[str, str], ...]:
    entries: list[tuple[str, str]] = []
    for raw_entry in status_text.split("\0"):
        if not raw_entry or len(raw_entry) < 4:
            continue
        status_code = raw_entry[:2]
        path = raw_entry[3:]
        if path:
            entries.append((status_code, path))
    return tuple(entries)


def _validate_actual_change_target(
    *,
    source_root: Path,
    source_target: Path,
    active_root: Path,
    worktree_target: Path,
    relative_path: str,
    deleted: bool,
) -> RunIssue | None:
    try:
        if deleted:
            worktree_target.parent.resolve().relative_to(active_root)
        else:
            worktree_target.resolve().relative_to(active_root)
    except ValueError:
        return _workspace_boundary_issue(
            offending_paths=(relative_path,),
            source_root=source_root,
            active_root=active_root,
        )
    try:
        if source_target.exists() or source_target.is_symlink():
            source_target.resolve().relative_to(source_root)
        else:
            source_target.parent.resolve().relative_to(source_root)
    except ValueError:
        return _workspace_boundary_issue(
            offending_paths=(relative_path,),
            source_root=source_root,
            active_root=active_root,
        )
    return None


def _workspace_boundary_issue(
    *,
    offending_paths: tuple[str, ...],
    source_root: Path,
    active_root: Path,
) -> RunIssue:
    return RunIssue(
        "workspace_boundary",
        "changed_path_outside_destination",
        offending_paths[0] if offending_paths else None,
        diagnostics={
            "authorized_output_root": str(source_root),
            "isolated_workspace_root": str(active_root),
            "offending_paths": offending_paths,
        },
    )


def _promote_actual_workspace_changes(baseline: PromotionBaseline) -> PromotionResult:
    if baseline.issue is not None:
        return PromotionResult("rejected", issue=baseline.issue)
    if not baseline.targets:
        return PromotionResult("skipped")

    written: list[PromotionTarget] = []
    created_dirs: list[Path] = []
    try:
        for target in baseline.targets:
            if target.change_kind == "deleted":
                if target.source_path.exists() or target.source_path.is_symlink():
                    if not target.source_path.is_file() and not target.source_path.is_symlink():
                        raise IsADirectoryError(str(target.source_path))
                    target.source_path.unlink()
                written.append(target)
                continue
            if not target.worktree_path.is_file():
                return PromotionResult(
                    "rejected",
                    issue=RunIssue(
                        "promotion",
                        "worktree_changed_path_not_file",
                        target.relative_path,
                    ),
                )
            created_dirs.extend(_ensure_parent_dirs(target.source_path.parent))
            target.source_path.write_bytes(target.worktree_path.read_bytes())
            written.append(target)
    except OSError:
        _rollback_promotion(written)
        _cleanup_created_dirs(created_dirs)
        failed_path = written[-1].relative_path if written else None
        return PromotionResult(
            "rejected",
            issue=RunIssue("promotion", "source_write_failed", failed_path),
        )
    return PromotionResult(
        "applied",
        promoted_files=tuple(target.relative_path for target in baseline.targets),
    )


def _source_workspace_changed_issue_with_diagnostics(
    issue: RunIssue,
    *,
    session: WorkspaceSession,
    active_workspace: Path,
    proposed_paths: tuple[str, ...],
    patch_result: ExecutionResult | None,
    pass_index: int | None,
    pass_id: str | None,
    pass_label: str | None,
    mutation_timing: str,
    execution_step: str,
) -> RunIssue:
    if issue.category != "promotion" or issue.reason != "source_workspace_changed":
        return issue
    diagnostics = {
        "original_target_directory": str(session.source_path.resolve()),
        "source_git_root": str(session.source_git_root.resolve()),
        "isolated_workspace_directory": str(active_workspace.resolve()),
        "executor_working_directory": _executor_cwd_from_patch_result(patch_result),
        "changed_path": issue.path,
        "expected_to_be_promoted": issue.path in set(proposed_paths)
        if issue.path is not None
        else False,
        "proposed_paths": proposed_paths,
        "pass_index": pass_index,
        "pass_id": pass_id,
        "pass_label": pass_label,
        "mutation_timing": mutation_timing,
        "execution_step": execution_step,
        "clue": (
            "source content differed from the isolated workspace copy when "
            "SFE checked promotion safety"
        ),
    }
    return replace(
        issue,
        diagnostics={**(issue.diagnostics or {}), **diagnostics},
    )


def _executor_cwd_from_patch_result(patch_result: ExecutionResult | None) -> str | None:
    if patch_result is None:
        return None
    diagnostics = patch_result.summary.get("executor_response_diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    provider_diagnostics = diagnostics.get("provider_diagnostics")
    if not isinstance(provider_diagnostics, dict):
        return None
    cwd = provider_diagnostics.get("cwd")
    return cwd if isinstance(cwd, str) else None


def _capture_promotion_baseline(
    session: WorkspaceSession,
    active_workspace: Path,
    paths: tuple[str, ...],
) -> PromotionBaseline:
    source_root = session.source_path.resolve()
    worktree_root = active_workspace.resolve()
    path_issue = validate_patch_paths(source_root, paths)
    if path_issue is not None:
        return PromotionBaseline(
            issue=_run_issue_from_patch(path_issue, default_reason="promotion_path_rejected")
        )
    targets: list[PromotionTarget] = []
    for relative_path in paths:
        if _is_internal_promotion_path(relative_path):
            return PromotionBaseline(
                issue=RunIssue("promotion", "internal_path_not_promoted", relative_path)
            )
        source_target = (source_root / relative_path).resolve()
        worktree_target = (worktree_root / relative_path).resolve()
        try:
            source_target.relative_to(source_root)
            worktree_target.relative_to(worktree_root)
        except ValueError:
            return PromotionBaseline(
                issue=RunIssue("promotion", "path_outside_workspace", relative_path)
            )
        source_before = _read_optional_file_bytes(source_target, relative_path)
        if isinstance(source_before, RunIssue):
            return PromotionBaseline(issue=source_before)
        worktree_before = _read_optional_file_bytes(worktree_target, relative_path)
        if isinstance(worktree_before, RunIssue):
            return PromotionBaseline(issue=worktree_before)
        if source_before != worktree_before:
            return PromotionBaseline(
                issue=RunIssue("promotion", "source_workspace_changed", relative_path)
            )
        targets.append(
            PromotionTarget(
                relative_path=relative_path,
                source_path=source_target,
                worktree_path=worktree_target,
                source_before=source_before,
            )
        )
    return PromotionBaseline(targets=tuple(targets))


def _promote_run_changes(baseline: PromotionBaseline) -> PromotionResult:
    if baseline.issue is not None:
        return PromotionResult("rejected", issue=baseline.issue)
    if not baseline.targets:
        return PromotionResult("skipped")

    # Deletes are intentionally not promoted in V1. The current patch parser
    # rejects delete operations; if that changes later, missing worktree files
    # are rejected here instead of being interpreted as source deletes.
    planned: list[tuple[PromotionTarget, bytes]] = []
    for target in baseline.targets:
        current_source = _read_optional_file_bytes(target.source_path, target.relative_path)
        if isinstance(current_source, RunIssue):
            return PromotionResult("rejected", issue=current_source)
        if current_source != target.source_before:
            return PromotionResult(
                "rejected",
                issue=RunIssue(
                    "promotion",
                    "source_workspace_changed",
                    target.relative_path,
                ),
            )
        try:
            if not target.worktree_path.is_file():
                return PromotionResult(
                    "rejected",
                    issue=RunIssue(
                        "promotion",
                        "worktree_promoted_file_missing",
                        target.relative_path,
                    ),
                )
            planned.append((target, target.worktree_path.read_bytes()))
        except OSError:
            return PromotionResult(
                "rejected",
                issue=RunIssue("promotion", "worktree_read_failed", target.relative_path),
            )

    written: list[PromotionTarget] = []
    created_dirs: list[Path] = []
    try:
        for target, content in planned:
            created_dirs.extend(_ensure_parent_dirs(target.source_path.parent))
            target.source_path.write_bytes(content)
            written.append(target)
    except OSError:
        _rollback_promotion(written)
        _cleanup_created_dirs(created_dirs)
        failed_path = written[-1].relative_path if written else None
        return PromotionResult(
            "rejected",
            issue=RunIssue("promotion", "source_write_failed", failed_path),
        )
    return PromotionResult(
        "applied",
        promoted_files=tuple(target.relative_path for target, _content in planned),
    )


def _read_optional_file_bytes(path: Path, relative_path: str) -> bytes | None | RunIssue:
    if not path.exists():
        return None
    if not path.is_file():
        return RunIssue("promotion", "promotion_target_not_file", relative_path)
    try:
        return path.read_bytes()
    except OSError:
        return RunIssue("promotion", "source_read_failed", relative_path)


def _rollback_promotion(written: list[PromotionTarget]) -> None:
    for target in reversed(written):
        try:
            if target.source_before is None:
                target.source_path.unlink(missing_ok=True)
            else:
                target.source_path.write_bytes(target.source_before)
        except OSError:
            continue


def _ensure_parent_dirs(path: Path) -> list[Path]:
    created: list[Path] = []
    current = path
    missing: list[Path] = []
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)
    return created


def _cleanup_created_dirs(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.rmdir()
        except OSError:
            continue


def _is_internal_promotion_path(path: str) -> bool:
    parts = {part.lower() for part in Path(path).parts}
    return bool(parts & {".git", ".sfe-worktrees", ".sfe"})


def _warnings_for_summary(summary: PatchSummary | None) -> tuple[str, ...]:
    warnings = list(_base_warnings())
    if summary is None:
        return tuple(warnings)
    if summary.file_count >= 10:
        warnings.append("many_files_changed")
    if summary.lines_added + summary.lines_removed >= 500:
        warnings.append("large_change")
    if len(summary.created_paths) > 1:
        warnings.append("multiple_creations")
    if any(_is_sensitive_path(path) for path in summary.paths):
        warnings.append("sensitive_path_touched")
    return tuple(dict.fromkeys(warnings))


def _warnings_for_summary_and_proposal(
    summary: PatchSummary | None,
    proposal: RunPatchProposal | None,
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *_warnings_for_summary(summary),
                *(proposal.transport_warnings if proposal is not None else ()),
            )
        )
    )


def _base_warnings() -> tuple[str, ...]:
    return (
        "no_router_review_run",
        "no_worktree_review_run",
        "no_tests_run",
        "no_lint_run",
        "diff_not_inspected",
    )


def _is_sensitive_path(path: str) -> bool:
    parts = {part.lower() for part in Path(path).parts}
    return bool(parts & {".env", ".ssh", "secrets", "secret"})


def _ensure_git_info_exclude(workspace: Path, pattern: str) -> bool:
    exclude_path = workspace / ".git" / "info" / "exclude"
    try:
        existing = exclude_path.read_text(encoding="utf-8") if exclude_path.exists() else ""
        if pattern in existing.splitlines():
            return True
        suffix = "" if not existing or existing.endswith("\n") else "\n"
        exclude_path.write_text(f"{existing}{suffix}{pattern}\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _git(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
