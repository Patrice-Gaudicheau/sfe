"""Worktree-first run pipeline for SFE patch execution.

The pipeline is intentionally narrow: discover relevant context, route it down
to the executor payload, request a patch, apply only mechanically valid edits in
an isolated worktree, and return compact structured state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from sfe.discovery import (
    DiscoveryResult,
    discover_workspace_context,
    load_discovered_context,
)
from sfe.discovery_router import DiscoveryRouter
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.patching import (
    MECHANICAL_GUARD_REJECTED,
    ParsedPatch,
    PatchApplyResult,
    PatchIssue,
    PatchSummary,
    StructuredFilePatch,
    apply_patch_to_workspace,
    apply_structured_file_patch,
    generate_structured_file_patch_diff_preview,
    parse_structured_file_patch_json,
    parse_unified_diff,
    summarize_structured_file_patch,
    validate_patch_paths,
    validate_patch_targets,
)
from sfe.workspace_isolation import (
    WorkspaceIsolationPolicy,
    WorkspaceIssue,
    WorkspaceManager,
    WorkspaceSession,
    WorkspaceStatusResult,
)
from sfe_tui.backends import BackendAdapter, BackendResult
from sfe_tui.contracts import build_contract
from sfe_tui.patch_json_repair import PATCH_JSON_REPAIR_MAX_INPUT_CHARS


RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"


@dataclass(frozen=True)
class RunIssue:
    category: str
    reason: str
    path: str | None = None


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

    @property
    def paths(self) -> tuple[str, ...]:
        if isinstance(self.proposal, ParsedPatch):
            return tuple(file_patch.new_path for file_patch in self.proposal.files)
        return self.proposal.paths


@dataclass(frozen=True)
class RunResult:
    status: str
    issue: RunIssue | None = None
    workspace_session: WorkspaceSession | None = None
    active_workspace: Path | None = None
    worktree_created: bool = False
    discovery_result: DiscoveryResult | None = None
    dry_run_result: BackendResult | None = None
    patch_result: BackendResult | None = None
    patch_generated: bool = False
    patch_applied: bool = False
    patch_summary: PatchSummary | None = None
    changed_files: tuple[str, ...] = ()
    selected_source_refs: tuple[str, ...] = ()
    executor_provider: str | None = None
    warnings: tuple[str, ...] = ()


class PatchJsonRepairer(Protocol):
    provider_name: str | None
    model: str | None

    def repair(self, *, raw_response: str, parse_error: str) -> object:
        ...


class RunPipeline:
    def __init__(
        self,
        *,
        backend: BackendAdapter,
        workspace_manager: WorkspaceManager | None = None,
        discovery_router: DiscoveryRouter | None = None,
        patch_json_repairer: PatchJsonRepairer | None = None,
    ) -> None:
        self.backend = backend
        self.workspace_manager = workspace_manager or WorkspaceManager(
            GitWorktreeBackend()
        )
        self.discovery_router = discovery_router
        self.patch_json_repairer = patch_json_repairer

    def run(self, request: RunRequest) -> RunResult:
        if request.workspace_root is None:
            return _failed("workspace", "workspace_not_selected")
        if not request.task.strip():
            return _failed("task", "missing_task")

        session_result = self._ensure_worktree(request)
        if isinstance(session_result, RunResult):
            return session_result
        session, active_workspace, created = session_result

        discovery_result = discover_workspace_context(
            workspace_root=active_workspace,
            task=request.task,
            router=self.discovery_router,
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
        if not selected_ids:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue("routing", "no_selected_context"),
                workspace_session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                selected_source_refs=selected_source_refs,
                warnings=_base_warnings(),
            )

        patch_result = self.backend.patch(contract)
        if not patch_result.answer:
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=RunIssue(
                    "patch_generation",
                    patch_result.error_category or "invalid_response",
                ),
                workspace_session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=patch_result,
                selected_source_refs=selected_source_refs,
                executor_provider=_executor_provider(patch_result),
                warnings=_base_warnings(),
            )

        proposal = self._parse_patch_response(active_workspace, patch_result)
        if isinstance(proposal, RunIssue):
            return RunResult(
                status=RUN_STATUS_FAILED,
                issue=proposal,
                workspace_session=session,
                active_workspace=active_workspace,
                worktree_created=created,
                discovery_result=discovery_result,
                dry_run_result=dry_run_result,
                patch_result=patch_result,
                selected_source_refs=selected_source_refs,
                executor_provider=_executor_provider(patch_result),
                warnings=_base_warnings(),
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
            )

        status_result = self.workspace_manager.status(session)
        changed_files = _changed_files(status_result, proposal.summary)
        return RunResult(
            status=RUN_STATUS_COMPLETED,
            workspace_session=session,
            active_workspace=active_workspace,
            worktree_created=created,
            discovery_result=discovery_result,
            dry_run_result=dry_run_result,
            patch_result=patch_result,
            patch_generated=True,
            patch_applied=True,
            patch_summary=apply_result.summary or proposal.summary,
            changed_files=changed_files,
            selected_source_refs=selected_source_refs,
            executor_provider=_executor_provider(patch_result),
            warnings=_warnings_for_summary(apply_result.summary or proposal.summary),
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
        result: BackendResult,
    ) -> RunPatchProposal | RunIssue:
        raw_answer = result.answer or ""
        structured = parse_structured_file_patch_json(raw_answer)
        if structured.proposal is not None and structured.summary is not None:
            preview = generate_structured_file_patch_diff_preview(
                workspace_root,
                structured.proposal,
            )
            proposal = StructuredFilePatch(structured.proposal.edits, preview or None)
            return RunPatchProposal(
                proposal=proposal,
                summary=summarize_structured_file_patch(proposal),
                preview=preview,
                parse_status="structured_replacements",
            )

        if (
            _should_attempt_repair(raw_answer, structured.issue)
            and self.patch_json_repairer is not None
        ):
            repaired_text = self._repair_patch_json(raw_answer, structured.issue)
            if repaired_text is not None:
                repaired_result = replace(result, answer=repaired_text)
                repaired = self._parse_patch_response(workspace_root, repaired_result)
                if isinstance(repaired, RunPatchProposal):
                    return RunPatchProposal(
                        proposal=repaired.proposal,
                        summary=repaired.summary,
                        preview=repaired.preview,
                        parse_status="structured_replacements_repaired",
                    )

        diff_parsed = parse_unified_diff(raw_answer)
        if diff_parsed.patch is None or diff_parsed.summary is None:
            issue = diff_parsed.issue or structured.issue
            return _run_issue_from_patch(issue, default_reason="patch_not_parseable")
        validation = validate_patch_targets(workspace_root, diff_parsed.patch)
        if not validation.ok:
            return _run_issue_from_patch(validation.issue, default_reason="patch_not_applicable")
        return RunPatchProposal(
            proposal=validation.patch or diff_parsed.patch,
            summary=validation.summary or diff_parsed.summary,
            preview=raw_answer,
            parse_status="unified_diff",
        )

    def _repair_patch_json(
        self,
        raw_response: str,
        issue: PatchIssue | None,
    ) -> str | None:
        repairer = self.patch_json_repairer
        if repairer is None:
            return None
        parse_error = issue.reason if issue is not None else "invalid_json"
        result = repairer.repair(raw_response=raw_response, parse_error=parse_error)
        repaired = getattr(result, "repaired_text", None)
        return repaired if isinstance(repaired, str) and repaired.strip() else None


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
    dry_run_result: BackendResult,
    patch_result: BackendResult,
    proposal: RunPatchProposal,
    selected_source_refs: tuple[str, ...],
) -> RunResult:
    return RunResult(
        status=RUN_STATUS_FAILED,
        issue=_run_issue_from_patch(issue, default_reason="patch_not_applicable"),
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
    )


def _failed(category: str, reason: str) -> RunResult:
    return RunResult(
        status=RUN_STATUS_FAILED,
        issue=RunIssue(category, reason),
        warnings=_base_warnings(),
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
    return RunIssue(category, issue.reason, issue.path)


def _active_path_for_session(session: WorkspaceSession) -> Path:
    try:
        relative_source = session.source_path.relative_to(session.source_git_root)
    except ValueError:
        relative_source = Path()
    return (session.worktree_path / relative_source).resolve()


def _selected_source_refs(
    result: BackendResult,
    selected_ids: list[str],
) -> tuple[str, ...]:
    selected = set(selected_ids)
    return tuple(
        segment.source_ref
        for segment in result.contract.context_segments
        if segment.id in selected
    )


def _executor_provider(result: BackendResult | None) -> str | None:
    if result is None:
        return None
    provider = result.summary.get("executor_provider")
    return str(provider) if provider is not None else None


def _changed_files(
    status_result: WorkspaceStatusResult,
    summary: PatchSummary,
) -> tuple[str, ...]:
    if status_result.ok and status_result.status is not None:
        return status_result.status.changed_files
    return summary.paths


def _should_attempt_repair(raw_response: str, issue: PatchIssue | None) -> bool:
    return (
        issue is not None
        and issue.reason == "invalid_json"
        and len(raw_response) <= PATCH_JSON_REPAIR_MAX_INPUT_CHARS
        and _looks_like_structured_patch_response(raw_response)
    )


def _looks_like_structured_patch_response(raw_response: str) -> bool:
    lowered = raw_response.lower()
    return (
        "{" in raw_response
        and "edits" in lowered
        and "path" in lowered
        and "content" in lowered
    )


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
