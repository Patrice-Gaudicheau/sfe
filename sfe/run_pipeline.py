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
from pathlib import Path, PurePosixPath
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
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.full_file_replacement_review import (
    FULL_FILE_REPLACEMENT_REVIEW_FALLBACK_KIND,
    FullFileReplacementReviewDecision,
    FullFileReplacementReviewRequest,
    FullFileReplacementReviewer,
    create_configured_full_file_replacement_reviewer,
    resolve_full_file_replacement_review_mode,
)
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


@dataclass(frozen=True)
class PatchRetryResult:
    proposal: RunPatchProposal
    apply_result: PatchApplyResult
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class FullFileReplacementFallbackCandidate:
    path: str
    file_patch_index: int
    current_content: str
    replacement_content: str
    diagnostics: dict[str, object]
    issue: str | None = None


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
        full_file_replacement_reviewer: FullFileReplacementReviewer | None = None,
        git_preparer: GitWorkspacePreparer | None = None,
        progress_callback: RunProgressCallback | None = None,
    ) -> None:
        self.backend = backend
        self.workspace_manager = workspace_manager or WorkspaceManager(
            GitWorktreeBackend()
        )
        self.discovery_router = discovery_router
        self.execution_mode_router = (
            execution_mode_router or create_configured_execution_mode_router()
        )
        self.multipass_planner = multipass_planner or create_configured_multipass_planner()
        self.full_file_replacement_reviewer = (
            full_file_replacement_reviewer
            or create_configured_full_file_replacement_reviewer()
        )
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
        if (
            dry_run_result.contract.context_segments
            and not selected_ids
            and not multipass_requested
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
        if isinstance(proposal, RunIssue):
            diagnostics = None
            if proposal.category == "invalid_patch_proposal":
                diagnostics = build_patch_proposal_diagnostics(
                    patch_result.answer or "",
                    selected_source_refs=selected_source_refs,
                )
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=proposal,
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
                patch_proposal_diagnostics=diagnostics,
            )

        guard_issue = validate_patch_paths(active_workspace, proposal.paths)
        if guard_issue is not None:
            return _patch_failed_result(
                guard_issue,
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

        self._emit_progress(
            "patch_validation_completed",
            "SFE: patch validation completed",
            patch_file_count=proposal.summary.file_count,
            patch_hunk_count=proposal.summary.hunk_count,
        )
        promotion_baseline = _capture_promotion_baseline(
            session,
            active_workspace,
            proposal.summary.paths,
        )
        if promotion_baseline.issue is not None:
            issue = _source_workspace_changed_issue_with_diagnostics(
                promotion_baseline.issue,
                session=session,
                active_workspace=active_workspace,
                proposed_paths=proposal.summary.paths,
                patch_result=patch_result,
                pass_index=None,
                pass_id=None,
                pass_label=None,
                mutation_timing="before_patch_application",
                execution_step="promotion_baseline_capture",
            )
            return _promotion_failed_result(
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
                patch_applied=False,
            )

        apply_result = _apply_run_patch(active_workspace, proposal.proposal)
        if not apply_result.applied:
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

        status_result = self.workspace_manager.status(session)
        changed_files = _changed_files(status_result, proposal.summary)
        patch_summary = apply_result.summary or proposal.summary
        promotion_result = _promote_run_changes(promotion_baseline)
        if promotion_result.status != "applied":
            issue = _source_workspace_changed_issue_with_diagnostics(
                promotion_result.issue
                or RunIssue("promotion", "promotion_not_applied"),
                session=session,
                active_workspace=active_workspace,
                proposed_paths=proposal.summary.paths,
                patch_result=patch_result,
                pass_index=None,
                pass_id=None,
                pass_label=None,
                mutation_timing="after_patch_application",
                execution_step="promotion_apply",
            )
            return _promotion_failed_result(
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
                patch_applied=True,
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
            worktree_created=created,
            discovery_result=discovery_result,
            dry_run_result=dry_run_result,
            patch_result=patch_result,
            patch_generated=True,
            patch_applied=True,
            patch_summary=patch_summary,
            changed_files=changed_files,
            selected_source_refs=selected_source_refs,
            executor_provider=_executor_provider(patch_result),
            warnings=_warnings_for_summary(patch_summary),
            git_auto_init=git_preparation.auto_initialized,
            git_initial_commit_hash=git_preparation.initial_commit_hash,
            git_init_warning=git_preparation.warning,
            promotion_status=promotion_result.status,
            promotion_applied=True,
            promoted_files=promotion_result.promoted_files,
            patch_hunk_count_normalization=proposal.hunk_count_normalization,
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
            if isinstance(proposal, RunIssue):
                pass_issue = _multi_pass_issue_from_run_issue(proposal, pass_id=batch.id)
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=pass_issue,
                        provider_diagnostics=provider_diagnostics,
                        executor_contract_diagnostics=executor_contract_diagnostics,
                    )
                )
                diagnostics = None
                if proposal.category == "invalid_patch_proposal":
                    diagnostics = build_patch_proposal_diagnostics(
                        patch_result.answer or "",
                        selected_source_refs=selected_source_refs,
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
                    issue=proposal,
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
                    patch_proposal_diagnostics=diagnostics,
                    )

            executor_contract_diagnostics = _executor_contract_diagnostics(
                active_workspace,
                patch_result,
                proposal,
            )
            guard_issue = validate_patch_paths(active_workspace, proposal.paths)
            if guard_issue is not None:
                issue = _run_issue_from_patch(
                    guard_issue,
                    default_reason="patch_not_applicable",
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

            scope_issue = validate_patch_paths_in_batch(proposal.paths, batch)
            if scope_issue is not None:
                issue = _run_issue_from_multipass(scope_issue)
                pass_results.append(
                    _failed_batch_result(
                        batch,
                        issue=scope_issue,
                        provider_diagnostics=provider_diagnostics,
                        executor_contract_diagnostics=executor_contract_diagnostics,
                    )
                )
                summary = _build_multi_pass_summary(
                    status="failed",
                    project_summary=parsed_plan.project_summary,
                    passes_total=len(parsed_plan.batches),
                    pass_results=tuple(pass_results),
                    failed_issue=scope_issue,
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

            promotion_baseline = _capture_promotion_baseline(
                session,
                active_workspace,
                proposal.summary.paths,
            )
            if promotion_baseline.issue is not None:
                issue = _source_workspace_changed_issue_with_diagnostics(
                    promotion_baseline.issue,
                    session=session,
                    active_workspace=active_workspace,
                    proposed_paths=proposal.summary.paths,
                    patch_result=patch_result,
                    pass_index=index,
                    pass_id=batch.id,
                    pass_label=batch.title,
                    mutation_timing="before_patch_application",
                    execution_step="promotion_baseline_capture",
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

            apply_result = _apply_run_patch(active_workspace, proposal.proposal)
            fallback_diagnostics: dict[str, object] | None = None
            if not apply_result.applied:
                retry_result = _retry_existing_create_as_update(
                    active_workspace,
                    proposal,
                    issue=apply_result.issue,
                    existing_update_files=existing_update_files,
                )
                if retry_result is None:
                    retry_result = _retry_small_file_preimage_mismatch(
                        active_workspace,
                        proposal,
                        issue=apply_result.issue,
                    )
                if retry_result is None:
                    retry_result = self._retry_llm_reviewed_full_file_replacement(
                        workspace_root=active_workspace,
                        request=request,
                        contract=current_contract,
                        patch_result=patch_result,
                        proposal=proposal,
                        issue=apply_result.issue,
                        completed_files=tuple(completed_files),
                        initial_existing_files=initial_existing_files,
                        pass_index=index,
                        batch=batch,
                    )
                if retry_result is not None and retry_result.apply_result.applied:
                    proposal = retry_result.proposal
                    apply_result = retry_result.apply_result
                    fallback_diagnostics = retry_result.diagnostics
                else:
                    failed_apply_issue = (
                        retry_result.apply_result.issue
                        if retry_result is not None
                        else apply_result.issue
                    )
                    issue = _run_issue_from_patch(
                        failed_apply_issue,
                        default_reason="patch_not_applicable",
                    )
                    diagnostics = _multi_pass_patch_issue_diagnostics(
                        active_workspace=active_workspace,
                        source_workspace=session.source_path,
                        contract=current_contract,
                        patch_result=patch_result,
                        proposal=proposal,
                        path=issue.path,
                        completed_files=tuple(completed_files),
                        initial_existing_files=initial_existing_files,
                        pass_index=index,
                        batch=batch,
                    )
                    llm_diagnostics = None
                    if retry_result is not None:
                        llm_diagnostics = retry_result.diagnostics
                    if llm_diagnostics is not None:
                        diagnostics = {
                            **(diagnostics or {}),
                            **llm_diagnostics,
                        }
                    pass_issue = _multi_pass_issue_from_run_issue(
                        issue,
                        pass_id=batch.id,
                        diagnostics=diagnostics,
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
                    )

            patch_summary = apply_result.summary or proposal.summary
            promotion_result = _promote_run_changes(promotion_baseline)
            if promotion_result.status != "applied":
                issue = _source_workspace_changed_issue_with_diagnostics(
                    promotion_result.issue
                    or RunIssue(
                        "promotion",
                        "promotion_not_applied",
                    ),
                    session=session,
                    active_workspace=active_workspace,
                    proposed_paths=proposal.summary.paths,
                    patch_result=patch_result,
                    pass_index=index,
                    pass_id=batch.id,
                    pass_label=batch.title,
                    mutation_timing="after_patch_application",
                    execution_step="promotion_apply",
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
                    promotion_status=promotion_result.status,
                    promotion_issue=promotion_result.issue,
                )

            latest_hunk_normalization = proposal.hunk_count_normalization
            completed_summaries.append(patch_summary)
            completed_files.extend(promotion_result.promoted_files)
            all_promoted_files.extend(promotion_result.promoted_files)
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
                    promoted_files=promotion_result.promoted_files,
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
                )
            )
            self._emit_progress(
                "multi_pass_pass_completed",
                f"SFE: multi-pass pass {index}/{len(parsed_plan.batches)} completed",
                multi_pass_index=index,
                multi_pass_total=len(parsed_plan.batches),
                multi_pass_id=batch.id,
                promoted_file_count=len(promotion_result.promoted_files),
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
            warnings=_warnings_for_summary(aggregate_summary),
            git_auto_init=git_preparation.auto_initialized,
            git_initial_commit_hash=git_preparation.initial_commit_hash,
            git_init_warning=git_preparation.warning,
            promotion_status="applied",
            promotion_applied=True,
            promoted_files=tuple(all_promoted_files),
            patch_hunk_count_normalization=latest_hunk_normalization,
            multi_pass_summary=multi_pass_summary,
        )

    def _retry_llm_reviewed_full_file_replacement(
        self,
        *,
        workspace_root: Path,
        request: RunRequest,
        contract: SFEContract,
        patch_result: ExecutionResult,
        proposal: RunPatchProposal,
        issue: PatchIssue | None,
        completed_files: tuple[str, ...],
        initial_existing_files: frozenset[str],
        pass_index: int,
        batch: MultiPassBatch,
    ) -> PatchRetryResult | None:
        mode = resolve_full_file_replacement_review_mode()
        if mode == "false":
            return None
        candidate = _full_file_replacement_review_candidate(
            workspace_root=workspace_root,
            contract=contract,
            patch_result=patch_result,
            proposal=proposal,
            issue=issue,
            completed_files=completed_files,
            initial_existing_files=initial_existing_files,
            pass_index=pass_index,
            batch=batch,
            reviewer_mode=mode,
        )
        if candidate is None:
            return None
        if candidate.issue is not None:
            return PatchRetryResult(
                proposal=proposal,
                apply_result=PatchApplyResult(False, issue, None, False),
                diagnostics=candidate.diagnostics,
            )
        review_request = FullFileReplacementReviewRequest(
            task_summary=request.task,
            target_path=candidate.path,
            pass_number=pass_index,
            pass_label=batch.title or batch.id,
            current_content=candidate.current_content,
            proposed_replacement_content=candidate.replacement_content,
            related_selected_file_paths=tuple(
                path
                for path in _execution_preview_selected_refs(patch_result)
                if path != candidate.path
            )[:20],
        )
        try:
            decision = self.full_file_replacement_reviewer.review(review_request)
        except Exception:
            decision = FullFileReplacementReviewDecision(
                approve=False,
                risk_level="high",
                reason="reviewer_execution_error",
                error="reviewer_execution_error",
            )
        diagnostics = _full_file_replacement_review_diagnostics(
            candidate,
            decision=decision,
            outcome="applied" if decision.apply_allowed else "reviewer_rejected",
        )
        diagnostics = {
            **diagnostics,
            "reviewer_provider": self.full_file_replacement_reviewer.provider_name,
            "reviewer_model": self.full_file_replacement_reviewer.model,
        }
        if not decision.apply_allowed:
            return PatchRetryResult(
                proposal=proposal,
                apply_result=PatchApplyResult(False, issue, None, False),
                diagnostics=diagnostics,
            )
        retry_patch = _proposal_with_reviewed_full_file_replacement(
            proposal,
            candidate,
        )
        retry_apply = _apply_run_patch(workspace_root, retry_patch)
        if not retry_apply.applied:
            diagnostics = {
                **diagnostics,
                "final_outcome": "reviewer_approved_apply_failed",
            }
            return PatchRetryResult(
                proposal=proposal,
                apply_result=retry_apply,
                diagnostics=diagnostics,
            )
        retry_proposal = RunPatchProposal(
            proposal=retry_patch,
            summary=summarize_patch(retry_patch),
            preview=proposal.preview,
            parse_status=proposal.parse_status
            + "_llm_reviewed_full_file_replacement_retry",
            hunk_count_normalization=proposal.hunk_count_normalization,
        )
        return PatchRetryResult(
            proposal=retry_proposal,
            apply_result=retry_apply,
            diagnostics=diagnostics,
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
            fenced_diff = extract_single_fenced_git_diff(raw_answer)
            if fenced_diff is not None:
                diff_text = fenced_diff
                parse_status = "fenced_unified_diff"
                diff_parsed = parse_unified_diff(diff_text)
            else:
                extracted_diff = extract_first_parseable_git_diff_segment(raw_answer)
                if extracted_diff is not None:
                    diff_text = extracted_diff
                    parse_status = "extracted_unified_diff"
                    diff_parsed = parse_unified_diff(diff_text)
        if diff_parsed.patch is None or diff_parsed.summary is None:
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
        warnings=_warnings_for_summary(proposal.summary),
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
        warnings=_warnings_for_summary(patch_summary or proposal.summary),
        git_auto_init=git_preparation.auto_initialized,
        git_initial_commit_hash=git_preparation.initial_commit_hash,
        git_init_warning=git_preparation.warning,
        promotion_status=promotion_result.status if promotion_result else "rejected",
        promotion_applied=False,
        promoted_files=promotion_result.promoted_files if promotion_result else (),
        promotion_issue=issue,
        patch_hunk_count_normalization=proposal.hunk_count_normalization,
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


def _retry_existing_create_as_update(
    workspace_root: Path,
    proposal: RunPatchProposal,
    *,
    issue: PatchIssue | None,
    existing_update_files: tuple[str, ...],
) -> PatchRetryResult | None:
    if (
        issue is None
        or issue.reason != "target_already_exists"
        or not existing_update_files
    ):
        return None
    normalized = _normalize_same_run_create_patches(
        workspace_root,
        proposal,
        completed_files=(),
        existing_update_files=existing_update_files,
    )
    if isinstance(normalized, RunIssue) or normalized is proposal:
        return None
    retry_apply = _apply_run_patch(workspace_root, normalized.proposal)
    if not retry_apply.applied:
        return None
    return PatchRetryResult(proposal=normalized, apply_result=retry_apply)


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


FULL_FILE_REPLACEMENT_REVIEW_MAX_BYTES = 128_000
FULL_FILE_REPLACEMENT_REVIEW_HUNK_MISMATCH_REASONS = {
    "hunk_preimage_mismatch",
    "hunk_location_mismatch",
}


def _retry_small_file_preimage_mismatch(
    workspace_root: Path,
    proposal: RunPatchProposal,
    *,
    issue: PatchIssue | None,
) -> PatchRetryResult | None:
    if (
        issue is None
        or issue.reason != "hunk_preimage_mismatch"
        or not isinstance(proposal.proposal, ParsedPatch)
    ):
        return None
    edits: list[StructuredFileEdit] = []
    for file_patch in proposal.proposal.files:
        replacement = _small_file_replacement_from_patch(workspace_root, file_patch)
        if replacement is None:
            return None
        edits.append(replacement)
    structured = StructuredFilePatch(tuple(edits), proposal.preview)
    retry_apply = apply_structured_file_patch(workspace_root, structured)
    if not retry_apply.applied:
        return None
    retry_proposal = RunPatchProposal(
        proposal=structured,
        summary=summarize_structured_file_patch(structured),
        preview=proposal.preview,
        parse_status=proposal.parse_status + "_small_file_replacement_retry",
        hunk_count_normalization=proposal.hunk_count_normalization,
    )
    return PatchRetryResult(proposal=retry_proposal, apply_result=retry_apply)


def _full_file_replacement_review_candidate(
    *,
    workspace_root: Path,
    contract: SFEContract,
    patch_result: ExecutionResult,
    proposal: RunPatchProposal,
    issue: PatchIssue | None,
    completed_files: tuple[str, ...],
    initial_existing_files: frozenset[str],
    pass_index: int,
    batch: MultiPassBatch,
    reviewer_mode: str,
) -> FullFileReplacementFallbackCandidate | None:
    if (
        issue is None
        or issue.reason not in FULL_FILE_REPLACEMENT_REVIEW_HUNK_MISMATCH_REASONS
        or issue.path is None
        or not isinstance(proposal.proposal, ParsedPatch)
    ):
        return None
    path = issue.path
    selected_refs = _execution_preview_selected_refs(patch_result)
    contract_refs = {segment.source_ref for segment in contract.context_segments}
    executor_diagnostics = _executor_contract_diagnostics(
        workspace_root,
        patch_result,
        proposal,
    )
    full_content_guidance_files = set(executor_diagnostics["full_content_provided_files"])
    eligible_files = set(executor_diagnostics["full_file_replacement_eligible_files"])
    included_in_guidance = path in full_content_guidance_files or path in eligible_files
    full_file_eligible = path in eligible_files
    target = workspace_root / path
    selected_context = path in selected_refs
    created_earlier = path in completed_files and path not in initial_existing_files
    full_content_provided = (
        target.is_file()
        and (selected_context or (path in batch.allowed_files and path in contract_refs))
    )
    executor_provided_context_allowed = (
        full_content_provided and full_file_eligible and included_in_guidance
    )
    diagnostics = {
        "fallback_kind": FULL_FILE_REPLACEMENT_REVIEW_FALLBACK_KIND,
        "target_path": path,
        "pass_index": pass_index,
        "pass_id": batch.id,
        "pass_label": batch.title,
        "selected_context": selected_context,
        "full_content_provided": full_content_provided,
        "full_file_replacement_eligible": full_file_eligible,
        "included_in_full_file_replacement_guidance": included_in_guidance,
        "allowed_through_executor_provided_context_gate": (
            executor_provided_context_allowed
        ),
        "file_existed_before_run": path in initial_existing_files,
        "created_earlier_in_run": created_earlier,
        "reviewer_enabled_mode": reviewer_mode,
        "proposed_replacement_full_file_like": False,
    }

    def blocked(reason: str) -> FullFileReplacementFallbackCandidate:
        return FullFileReplacementFallbackCandidate(
            path=path,
            file_patch_index=-1,
            current_content="",
            replacement_content="",
            diagnostics={
                **diagnostics,
                "final_outcome": "blocked_by_deterministic_invariant",
                "reviewer_reason": reason,
            },
            issue=reason,
        )

    matching_indexes = [
        index
        for index, candidate_file_patch in enumerate(proposal.proposal.files)
        if candidate_file_patch.new_path == path
    ]
    if len(matching_indexes) != 1:
        return blocked("target_path_not_exactly_failed_patch_path")
    file_patch_index = matching_indexes[0]
    file_patch = proposal.proposal.files[file_patch_index]
    if path not in batch.allowed_files:
        return blocked("target_path_not_in_current_pass_scope")
    if validate_patch_paths(workspace_root, (path,)) is not None:
        return blocked("target_path_outside_workspace_scope")
    if (
        not selected_context
        and not created_earlier
        and not executor_provided_context_allowed
    ):
        return blocked("target_not_selected_or_created_earlier")
    if not full_content_provided:
        return blocked("full_current_content_not_provided")
    try:
        current_content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return blocked("current_content_unreadable")
    replacement_lines = _full_file_replacement_lines_from_patch(
        file_patch,
        current_line_count=len(current_content.splitlines()),
    )
    if replacement_lines is None:
        return blocked("proposed_replacement_not_full_file")
    diagnostics = {
        **diagnostics,
        "proposed_replacement_full_file_like": True,
    }
    replacement_content = "\n".join(replacement_lines)
    if replacement_lines:
        replacement_content += "\n"
    if not replacement_content.strip():
        return blocked("proposed_replacement_empty")
    if (
        len(replacement_content.encode("utf-8"))
        > FULL_FILE_REPLACEMENT_REVIEW_MAX_BYTES
    ):
        return blocked("proposed_replacement_too_large")
    return FullFileReplacementFallbackCandidate(
        path=path,
        file_patch_index=file_patch_index,
        current_content=current_content,
        replacement_content=replacement_content,
        diagnostics=diagnostics,
    )


def _proposal_with_reviewed_full_file_replacement(
    proposal: RunPatchProposal,
    candidate: FullFileReplacementFallbackCandidate,
) -> ParsedPatch:
    if not isinstance(proposal.proposal, ParsedPatch):
        raise TypeError("reviewed fallback requires a parsed patch proposal")
    files = list(proposal.proposal.files)
    current_lines = candidate.current_content.splitlines()
    replacement_lines = candidate.replacement_content.splitlines()
    old_start = 1 if current_lines else 0
    new_start = 1 if replacement_lines else 0
    files[candidate.file_patch_index] = ParsedFilePatch(
        old_path=candidate.path,
        new_path=candidate.path,
        hunks=(
            ParsedHunk(
                old_start=old_start,
                old_count=len(current_lines),
                new_start=new_start,
                new_count=len(replacement_lines),
                lines=tuple(
                    [*(PatchLine("-", line) for line in current_lines)]
                    + [*(PatchLine("+", line) for line in replacement_lines)]
                ),
            ),
        ),
        operation=PATCH_OPERATION_MODIFY,
    )
    return ParsedPatch(files=tuple(files))


def _full_file_replacement_review_diagnostics(
    candidate: FullFileReplacementFallbackCandidate,
    *,
    decision: FullFileReplacementReviewDecision,
    outcome: str,
) -> dict[str, object]:
    return {
        **candidate.diagnostics,
        "reviewer_approve": decision.approve,
        "reviewer_risk_level": decision.risk_level,
        "reviewer_reason": decision.reason,
        "reviewer_concerns": list(decision.concerns),
        "reviewer_error": decision.error,
        "final_outcome": outcome,
    }


def _small_file_replacement_from_patch(
    workspace_root: Path,
    file_patch: ParsedFilePatch,
) -> StructuredFileEdit | None:
    path = file_patch.new_path
    if not _is_small_replacement_candidate_path(path):
        return None
    target = (workspace_root / path).resolve()
    if not target.is_file():
        return None
    try:
        current_text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if len(current_text.encode("utf-8")) > 64_000:
        return None
    replacement_lines = _full_file_replacement_lines_from_patch(
        file_patch,
        current_line_count=len(current_text.splitlines()),
    )
    if replacement_lines is None and path == "composer.json":
        return _composer_json_merge_replacement_from_patch(
            path,
            current_text=current_text,
            file_patch=file_patch,
        )
    if replacement_lines is None:
        return None
    replacement_text = "\n".join(replacement_lines)
    if replacement_lines:
        replacement_text += "\n"
    if path == "composer.json":
        try:
            parsed_json = json.loads(replacement_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed_json, dict):
            return None
    return StructuredFileEdit(
        path=path,
        action=SUPPORTED_REPLACE_ACTION,
        content=replacement_text,
    )


_COMPOSER_PACKAGE_LINE_RE = re.compile(r'^\s*"(?P<name>[^"]+)":\s*"(?P<constraint>[^"]+)"\s*,?\s*$')


def _composer_json_merge_replacement_from_patch(
    path: str,
    *,
    current_text: str,
    file_patch: ParsedFilePatch,
) -> StructuredFileEdit | None:
    try:
        parsed_json = json.loads(current_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed_json, dict):
        return None
    additions = _composer_dependency_additions(file_patch)
    if not additions:
        return None
    changed = False
    for section, packages in additions.items():
        current_section = parsed_json.setdefault(section, {})
        if not isinstance(current_section, dict):
            return None
        for package, constraint in packages.items():
            if current_section.get(package) != constraint:
                current_section[package] = constraint
                changed = True
    if not changed:
        return None
    replacement_text = json.dumps(parsed_json, indent=4, ensure_ascii=False) + "\n"
    return StructuredFileEdit(
        path=path,
        action=SUPPORTED_REPLACE_ACTION,
        content=replacement_text,
    )


def _composer_dependency_additions(
    file_patch: ParsedFilePatch,
) -> dict[str, dict[str, str]]:
    additions: dict[str, dict[str, str]] = {}
    current_section: str | None = None
    for hunk in file_patch.hunks:
        for line in hunk.lines:
            text = line.text.strip()
            if line.kind in {" ", "+"}:
                if text.startswith('"require-dev"') and "{" in text:
                    current_section = "require-dev"
                elif text.startswith('"require"') and "{" in text:
                    current_section = "require"
                elif text == "},":
                    current_section = None
            if line.kind != "+":
                continue
            match = _COMPOSER_PACKAGE_LINE_RE.match(line.text)
            if match is None:
                continue
            package = match.group("name")
            constraint = match.group("constraint")
            section = current_section or _infer_composer_dependency_section(package)
            additions.setdefault(section, {})[package] = constraint
    return additions


def _infer_composer_dependency_section(package: str) -> str:
    if package.startswith("phpunit/") or package in {
        "symfony/browser-kit",
        "symfony/css-selector",
        "symfony/maker-bundle",
        "symfony/phpunit-bridge",
        "symfony/web-profiler-bundle",
    }:
        return "require-dev"
    return "require"


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


def _is_small_replacement_candidate_path(path: str) -> bool:
    pure = PurePosixPath(path)
    if path in {"composer.json", "README.md", ".env.example", "phpunit.xml.dist"}:
        return True
    return (
        len(pure.parts) >= 2
        and pure.parts[0] == "config"
        and pure.suffix in {".yaml", ".yml"}
    )


def _multi_pass_patch_issue_diagnostics(
    *,
    active_workspace: Path,
    source_workspace: Path,
    contract: SFEContract,
    patch_result: ExecutionResult,
    proposal: RunPatchProposal,
    path: str | None,
    completed_files: tuple[str, ...],
    initial_existing_files: frozenset[str],
    pass_index: int,
    batch: MultiPassBatch,
) -> dict[str, object] | None:
    if path is None:
        return None
    selected_refs = _execution_preview_selected_refs(patch_result)
    contract_refs = {segment.source_ref for segment in contract.context_segments}
    target = active_workspace / path
    executor_diagnostics = _executor_contract_diagnostics(
        active_workspace,
        patch_result,
        proposal,
    )
    eligible_files = set(
        executor_diagnostics["full_file_replacement_eligible_files"]
    )
    full_content_guidance_files = set(executor_diagnostics["full_content_provided_files"])
    used_files = set(executor_diagnostics["full_file_replacement_used_files"])
    return {
        "target_path": path,
        "pass_index": pass_index,
        "pass_id": batch.id,
        "selected_context": path in selected_refs,
        "full_content_provided": (
            target.is_file()
            and (path in selected_refs or path in batch.allowed_files and path in contract_refs)
        ),
        "file_existed_before_run": (
            path in initial_existing_files
            or ((source_workspace / path).exists() and path not in completed_files)
        ),
        "created_earlier_in_run": path in completed_files
        and path not in initial_existing_files,
        "full_file_replacement_eligible": path in eligible_files,
        "included_in_full_file_replacement_guidance": path in full_content_guidance_files
        or path in eligible_files,
        "executor_used_full_file_replacement": path in used_files,
    }


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


def _execution_preview_selected_refs(result: ExecutionResult) -> set[str]:
    preview = result.execution_preview
    if preview is None:
        return set()
    segments = preview.executor_payload.get("selected_context_segments")
    if not isinstance(segments, list | tuple):
        return set()
    return {
        segment.source_ref
        for segment in segments
        if isinstance(getattr(segment, "source_ref", None), str)
    }


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
