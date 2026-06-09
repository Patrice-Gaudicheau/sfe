"""Renderer-independent SFE runtime session controller.

This module owns the local session state shared by user-facing control
surfaces. It deliberately delegates execution to ``RunPipeline`` instead of
creating another runtime path.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sfe.contracts import resolve_workspace
from sfe.discovery import DiscoveryResult
from sfe.discovery_router import DiscoveryRouter
from sfe.execution_backend import ExecutionBackend, ExecutionResult
from sfe.execution_mode_router import ExecutionModeRouter
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.run_pipeline import (
    RunPipeline,
    RunProgressCallback,
    RunProgressEvent,
    RunRequest,
    RunResult,
)
from sfe.workspace_isolation import (
    WorkspaceIssue,
    WorkspaceManager,
    WorkspaceSession,
    WorkspaceStatus,
    WorkspaceStatusResult,
)


@dataclass(frozen=True)
class TargetDirectoryResult:
    ok: bool
    workspace_root: Path | None = None
    error_category: str | None = None


@dataclass(frozen=True)
class TaskSetResult:
    ok: bool
    task: str = ""
    error_category: str | None = None


@dataclass(frozen=True)
class SessionRunResult:
    ok: bool
    run_result: RunResult | None = None
    progress_events: tuple[RunProgressEvent, ...] = ()
    error_category: str | None = None


@dataclass(frozen=True)
class RunReportResult:
    ok: bool
    run_result: RunResult | None = None
    error_category: str | None = None


@dataclass(frozen=True)
class RuntimeWorkspaceStatus:
    workspace_root: Path | None
    workspace_session: WorkspaceSession | None
    status_result: WorkspaceStatusResult | None


class RuntimeSession:
    """Shared state and execution controller for SFE local surfaces."""

    def __init__(
        self,
        *,
        backend: ExecutionBackend,
        cwd: Path | None = None,
        workspace_manager: WorkspaceManager | None = None,
        discovery_router: DiscoveryRouter | None = None,
        execution_mode_router: ExecutionModeRouter | None = None,
    ) -> None:
        self.cwd = (cwd or Path.cwd()).resolve()
        self.backend = backend
        self.workspace_manager = workspace_manager or WorkspaceManager(
            GitWorktreeBackend()
        )
        self.discovery_router = discovery_router
        self.execution_mode_router = execution_mode_router
        self.workspace_root: Path | None = None
        self.workspace_session: WorkspaceSession | None = None
        self.discovery_result: DiscoveryResult | None = None
        self.task = ""
        self.latest_result: ExecutionResult | None = None
        self.last_run_result: RunResult | None = None
        self.last_progress_events: tuple[RunProgressEvent, ...] = ()

    def set_target_directory(self, path: str) -> TargetDirectoryResult:
        try:
            self.workspace_root = resolve_workspace(path, self.cwd)
        except ValueError as exc:
            return TargetDirectoryResult(ok=False, error_category=str(exc))
        return TargetDirectoryResult(ok=True, workspace_root=self.workspace_root)

    def set_task(self, task: str) -> TaskSetResult:
        normalized = task.strip()
        if not normalized:
            return TaskSetResult(ok=False, error_category="missing_task")
        self.task = normalized
        self.discovery_result = None
        self.latest_result = None
        return TaskSetResult(ok=True, task=self.task)

    def reset(self) -> None:
        self.discovery_result = None
        self.task = ""
        self.latest_result = None

    def run(
        self,
        *,
        progress_callback: RunProgressCallback | None = None,
        before_execute: Callable[[], None] | None = None,
        after_execute: Callable[[], None] | None = None,
    ) -> SessionRunResult:
        self.last_progress_events = ()
        error_category = self.run_error_category()
        if error_category is not None:
            return SessionRunResult(ok=False, error_category=error_category)

        progress_events: list[RunProgressEvent] = []

        def capture_progress(event: RunProgressEvent) -> None:
            progress_events.append(event)
            if progress_callback is not None:
                progress_callback(event)

        pipeline = RunPipeline(
            backend=self.backend,
            workspace_manager=self.workspace_manager,
            discovery_router=self.discovery_router,
            execution_mode_router=self.execution_mode_router,
            progress_callback=capture_progress,
        )
        if before_execute is not None:
            before_execute()
        try:
            result = pipeline.run(
                RunRequest(
                    workspace_root=self.workspace_root,
                    task=self.task,
                    workspace_session=self.workspace_session,
                )
            )
        finally:
            if after_execute is not None:
                after_execute()
        self.last_run_result = result
        if result.workspace_session is not None:
            self.workspace_session = result.workspace_session
        if result.active_workspace is not None:
            self.workspace_root = result.active_workspace
        self.discovery_result = result.discovery_result
        self.latest_result = result.patch_result or result.dry_run_result
        self.last_progress_events = tuple(progress_events)
        return SessionRunResult(
            ok=result.status == "completed",
            run_result=result,
            progress_events=self.last_progress_events,
        )

    def run_error_category(self) -> str | None:
        if self.workspace_root is None:
            return "workspace_not_selected"
        if not self.task.strip():
            return "missing_task"
        return None

    def run_report(self) -> RunReportResult:
        if self.last_run_result is None:
            return RunReportResult(ok=False, error_category="no_previous_run")
        return RunReportResult(ok=True, run_result=self.last_run_result)

    def workspace_status(self) -> RuntimeWorkspaceStatus:
        status_result = (
            self.workspace_manager.status(self.workspace_session)
            if self.workspace_session is not None
            else original_workspace_status(self.workspace_root)
        )
        return RuntimeWorkspaceStatus(
            workspace_root=self.workspace_root,
            workspace_session=self.workspace_session,
            status_result=status_result,
        )


def original_workspace_status(workspace_root: Path | None) -> WorkspaceStatusResult | None:
    if workspace_root is None:
        return None
    workspace = workspace_root.expanduser().resolve()
    try:
        git_root = _git(workspace, "rev-parse", "--show-toplevel")
    except FileNotFoundError:
        return WorkspaceStatusResult(
            ok=False,
            issue=WorkspaceIssue("git_status", "git_unavailable"),
        )
    if git_root.returncode != 0:
        return WorkspaceStatusResult(
            ok=False,
            issue=WorkspaceIssue("git_status", "not_a_git_repository"),
        )
    source_path = Path(git_root.stdout.strip()).resolve()
    status_result = _git(source_path, "status", "--porcelain")
    if status_result.returncode != 0:
        return WorkspaceStatusResult(
            ok=False,
            issue=WorkspaceIssue("git_status", "git_status_failed"),
        )
    diff_result = _git(source_path, "diff", "--no-ext-diff")
    if diff_result.returncode != 0:
        return WorkspaceStatusResult(
            ok=False,
            issue=WorkspaceIssue("git_status", "git_diff_failed"),
        )
    branch = _current_branch(source_path)
    return WorkspaceStatusResult(
        ok=True,
        status=WorkspaceStatus(
            git_status_porcelain=status_result.stdout,
            git_diff=diff_result.stdout,
            changed_files=_changed_files_from_status(status_result.stdout),
            source_path=source_path,
            worktree_path=source_path,
            source_branch=branch,
            worktree_branch=branch,
        ),
    )


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _current_branch(git_root: Path) -> str:
    branch = _git(git_root, "branch", "--show-current")
    if branch.returncode == 0 and branch.stdout.strip():
        return branch.stdout.strip()
    sha = _git(git_root, "rev-parse", "--short", "HEAD")
    if sha.returncode == 0 and sha.stdout.strip():
        return f"HEAD-{sha.stdout.strip()}"
    return "HEAD"


def _changed_files_from_status(status_output: str) -> tuple[str, ...]:
    files: list[str] = []
    seen: set[str] = set()
    for line in status_output.splitlines():
        if len(line) < 4:
            continue
        path_text = line[3:]
        if " -> " in path_text:
            path_text = path_text.rsplit(" -> ", 1)[1]
        path_text = path_text.strip()
        if path_text and path_text not in seen:
            seen.add(path_text)
            files.append(path_text)
    return tuple(files)
