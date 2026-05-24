"""Core abstractions for isolated execution workspaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class WorkspaceIsolationPolicy:
    allow_dirty_source: bool = False
    worktree_parent: Path | None = None


@dataclass(frozen=True)
class WorkspaceIssue:
    category: str
    reason: str


@dataclass(frozen=True)
class WorkspaceSession:
    session_id: str
    source_path: Path
    source_git_root: Path
    worktree_path: Path
    source_branch: str
    worktree_branch: str
    backend_name: str
    created_by: str = "sfe"
    metadata_path: Path | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceCreateResult:
    created: bool
    session: WorkspaceSession | None = None
    issue: WorkspaceIssue | None = None


@dataclass(frozen=True)
class WorkspaceStatus:
    git_status_porcelain: str
    git_diff: str
    changed_files: tuple[str, ...]
    source_path: Path
    worktree_path: Path
    source_branch: str
    worktree_branch: str


@dataclass(frozen=True)
class WorkspaceStatusResult:
    ok: bool
    status: WorkspaceStatus | None = None
    issue: WorkspaceIssue | None = None


@dataclass(frozen=True)
class WorkspaceCleanupResult:
    cleaned: bool
    issue: WorkspaceIssue | None = None


class WorkspaceBackend(Protocol):
    name: str

    def create(
        self,
        workspace_path: Path,
        policy: WorkspaceIsolationPolicy | None = None,
    ) -> WorkspaceCreateResult:
        ...

    def status(self, session: WorkspaceSession) -> WorkspaceStatusResult:
        ...

    def cleanup(self, session: WorkspaceSession) -> WorkspaceCleanupResult:
        ...


class WorkspaceManager:
    def __init__(self, backend: WorkspaceBackend) -> None:
        self.backend = backend

    def create(
        self,
        workspace_path: Path,
        policy: WorkspaceIsolationPolicy | None = None,
    ) -> WorkspaceCreateResult:
        return self.backend.create(workspace_path, policy)

    def status(self, session: WorkspaceSession) -> WorkspaceStatusResult:
        return self.backend.status(session)

    def cleanup(self, session: WorkspaceSession) -> WorkspaceCleanupResult:
        return self.backend.cleanup(session)


@dataclass(frozen=True)
class IsolatedWorkspace:
    session: WorkspaceSession
    manager: WorkspaceManager

    def status(self) -> WorkspaceStatusResult:
        return self.manager.status(self.session)

    def cleanup(self) -> WorkspaceCleanupResult:
        return self.manager.cleanup(self.session)
