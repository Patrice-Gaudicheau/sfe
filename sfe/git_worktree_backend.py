"""Git Worktree backend for SFE isolated workspaces."""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from sfe.workspace_isolation import (
    WorkspaceCleanupResult,
    WorkspaceCreateResult,
    WorkspaceGCEntry,
    WorkspaceGCResult,
    WorkspaceIsolationPolicy,
    WorkspaceIssue,
    WorkspaceSession,
    WorkspaceStatus,
    WorkspaceStatusResult,
)


SFE_WORKTREE_BRANCH_PREFIX = "sfe/worktree/"
SFE_CREATED_BY = "sfe"


class GitWorktreeBackend:
    name = "git-worktree"

    def create(
        self,
        workspace_path: Path,
        policy: WorkspaceIsolationPolicy | None = None,
    ) -> WorkspaceCreateResult:
        policy = policy or WorkspaceIsolationPolicy()
        source_path = workspace_path.expanduser().resolve()
        git_root_result = _git(source_path, "rev-parse", "--show-toplevel")
        if not git_root_result.ok:
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("unsupported_workspace", "not_inside_git_repository"),
            )
        source_git_root = Path(git_root_result.stdout.strip()).resolve()
        if not source_path.exists() or not source_path.is_dir():
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("invalid_workspace", "workspace_not_directory"),
            )

        dirty_status = _git(source_git_root, "status", "--porcelain")
        if not dirty_status.ok:
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("git_error", "source_status_failed"),
            )
        if dirty_status.stdout.strip() and not policy.allow_dirty_source:
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("dirty_source_repo", "dirty_source_refused_by_policy"),
            )

        head_result = _git(source_git_root, "rev-parse", "--verify", "HEAD")
        if not head_result.ok:
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("git_error", "source_head_unavailable"),
            )
        source_branch = _current_branch(source_git_root)
        session_id = _new_session_id()
        worktree_branch = f"{SFE_WORKTREE_BRANCH_PREFIX}{session_id}"
        worktree_parent = _resolve_worktree_parent(source_git_root, policy)
        worktree_path = (worktree_parent / f"{source_git_root.name}-{session_id}").resolve()
        if _is_relative_to(worktree_path, source_path):
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("unsafe_worktree_path", "worktree_path_inside_source_workspace"),
            )
        if worktree_path.exists():
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("unsafe_worktree_path", "worktree_path_already_exists"),
            )

        try:
            worktree_parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("filesystem_error", "worktree_parent_create_failed"),
            )

        add_result = _git(
            source_git_root,
            "worktree",
            "add",
            "-b",
            worktree_branch,
            str(worktree_path),
            "HEAD",
        )
        if not add_result.ok:
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("git_error", "worktree_create_failed"),
            )

        metadata_path = worktree_parent / f"{source_git_root.name}-{session_id}.sfe-session.json"
        session = WorkspaceSession(
            session_id=session_id,
            source_path=source_path,
            source_git_root=source_git_root,
            worktree_path=worktree_path,
            source_branch=source_branch,
            worktree_branch=worktree_branch,
            backend_name=self.name,
            created_by=SFE_CREATED_BY,
            metadata_path=metadata_path,
            metadata={
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_head": head_result.stdout.strip(),
            },
        )
        try:
            _write_session_metadata(session)
        except OSError:
            cleanup_result = self.cleanup(session)
            reason = (
                "session_metadata_create_failed"
                if cleanup_result.cleaned
                else "session_metadata_create_failed_cleanup_failed"
            )
            return WorkspaceCreateResult(
                False,
                issue=WorkspaceIssue("filesystem_error", reason),
            )
        return WorkspaceCreateResult(True, session=session)

    def status(self, session: WorkspaceSession) -> WorkspaceStatusResult:
        if not _is_sfe_session(session):
            return WorkspaceStatusResult(
                False,
                issue=WorkspaceIssue("unsafe_session", "session_not_sfe_created"),
            )
        status_result = _git(session.worktree_path, "status", "--porcelain")
        if not status_result.ok:
            return WorkspaceStatusResult(
                False,
                issue=WorkspaceIssue("git_error", "worktree_status_failed"),
            )
        diff_result = _git(session.worktree_path, "diff", "--no-ext-diff")
        if not diff_result.ok:
            return WorkspaceStatusResult(
                False,
                issue=WorkspaceIssue("git_error", "worktree_diff_failed"),
            )
        return WorkspaceStatusResult(
            True,
            status=WorkspaceStatus(
                git_status_porcelain=status_result.stdout,
                git_diff=diff_result.stdout,
                changed_files=_changed_files_from_status(status_result.stdout),
                source_path=session.source_path,
                worktree_path=session.worktree_path,
                source_branch=session.source_branch,
                worktree_branch=session.worktree_branch,
            ),
        )

    def cleanup(self, session: WorkspaceSession) -> WorkspaceCleanupResult:
        if not _is_sfe_session(session):
            return WorkspaceCleanupResult(
                False,
                WorkspaceIssue("unsafe_cleanup_refused", "session_not_sfe_created"),
            )
        if session.metadata_path is None or not session.metadata_path.exists():
            return WorkspaceCleanupResult(
                False,
                WorkspaceIssue("unsafe_cleanup_refused", "missing_sfe_session_metadata"),
            )
        if not _metadata_matches_session(session):
            return WorkspaceCleanupResult(
                False,
                WorkspaceIssue("unsafe_cleanup_refused", "session_metadata_mismatch"),
            )

        remove_result = _git(
            session.source_git_root,
            "worktree",
            "remove",
            "--force",
            str(session.worktree_path),
        )
        if not remove_result.ok:
            return WorkspaceCleanupResult(
                False,
                WorkspaceIssue("git_error", "worktree_remove_failed"),
            )
        branch_result = _git(
            session.source_git_root,
            "branch",
            "-D",
            session.worktree_branch,
        )
        if not branch_result.ok:
            return WorkspaceCleanupResult(
                False,
                WorkspaceIssue("git_error", "worktree_branch_delete_failed"),
            )
        try:
            session.metadata_path.unlink()
        except OSError:
            return WorkspaceCleanupResult(
                False,
                WorkspaceIssue("filesystem_error", "session_metadata_remove_failed"),
            )
        return WorkspaceCleanupResult(True)

    def gc(
        self,
        workspace_path: Path,
        *,
        clean: bool = False,
        policy: WorkspaceIsolationPolicy | None = None,
        protected_session_ids: tuple[str, ...] = (),
    ) -> WorkspaceGCResult:
        policy = policy or WorkspaceIsolationPolicy()
        source_path = workspace_path.expanduser().resolve()
        git_root_result = _git(source_path, "rev-parse", "--show-toplevel")
        if not git_root_result.ok:
            return WorkspaceGCResult(
                clean=clean,
                source_path=source_path,
                sfe_worktree_count=0,
                eligible_count=0,
                dirty_skipped_count=0,
                non_sfe_ignored_count=0,
                removed_count=0,
                entries=(),
                issue=WorkspaceIssue("unsupported_workspace", "not_inside_git_repository"),
            )
        source_git_root = Path(git_root_result.stdout.strip()).resolve()
        worktree_parent = _resolve_worktree_parent(source_git_root, policy)
        sessions = _load_sfe_sessions(worktree_parent)
        worktree_entries = _git_worktree_entries(source_git_root)
        sfe_paths = {session.worktree_path.resolve() for session in sessions}

        entries: list[WorkspaceGCEntry] = []
        eligible_count = 0
        dirty_skipped_count = 0
        removed_count = 0

        for session in sessions:
            if session.session_id in protected_session_ids:
                entries.append(
                    WorkspaceGCEntry(
                        session=session,
                        worktree_path=session.worktree_path,
                        worktree_branch=session.worktree_branch,
                        metadata_path=session.metadata_path,
                        status="protected_skipped",
                        reason="active_session_protected",
                    )
                )
                continue
            status_result = self.status(session)
            if not status_result.ok or status_result.status is None:
                entries.append(
                    WorkspaceGCEntry(
                        session=session,
                        worktree_path=session.worktree_path,
                        worktree_branch=session.worktree_branch,
                        metadata_path=session.metadata_path,
                        status="skipped",
                        reason=(
                            status_result.issue.reason
                            if status_result.issue is not None
                            else "status_unavailable"
                        ),
                    )
                )
                continue
            if status_result.status.git_status_porcelain.strip():
                dirty_skipped_count += 1
                entries.append(
                    WorkspaceGCEntry(
                        session=session,
                        worktree_path=session.worktree_path,
                        worktree_branch=session.worktree_branch,
                        metadata_path=session.metadata_path,
                        status="dirty_skipped",
                        reason="dirty_worktree_refused_by_policy",
                        changed_files=status_result.status.changed_files,
                    )
                )
                continue

            eligible_count += 1
            if clean:
                cleanup_result = self.cleanup(session)
                if cleanup_result.cleaned:
                    removed_count += 1
                    entries.append(
                        WorkspaceGCEntry(
                            session=session,
                            worktree_path=session.worktree_path,
                            worktree_branch=session.worktree_branch,
                            metadata_path=session.metadata_path,
                            status="removed",
                            reason="clean_sfe_worktree_removed",
                        )
                    )
                else:
                    entries.append(
                        WorkspaceGCEntry(
                            session=session,
                            worktree_path=session.worktree_path,
                            worktree_branch=session.worktree_branch,
                            metadata_path=session.metadata_path,
                            status="cleanup_failed",
                            reason=(
                                cleanup_result.issue.reason
                                if cleanup_result.issue is not None
                                else "cleanup_failed"
                            ),
                        )
                    )
            else:
                entries.append(
                    WorkspaceGCEntry(
                        session=session,
                        worktree_path=session.worktree_path,
                        worktree_branch=session.worktree_branch,
                        metadata_path=session.metadata_path,
                        status="eligible",
                        reason="clean_sfe_worktree_eligible_for_cleanup",
                    )
                )

        non_sfe_ignored_count = 0
        for item in worktree_entries:
            path = item.path.resolve()
            if path == source_git_root or path in sfe_paths:
                continue
            non_sfe_ignored_count += 1
            entries.append(
                WorkspaceGCEntry(
                    session=None,
                    worktree_path=path,
                    worktree_branch=item.branch,
                    metadata_path=None,
                    status="ignored",
                    reason="non_sfe_worktree",
                )
            )

        return WorkspaceGCResult(
            clean=clean,
            source_path=source_path,
            sfe_worktree_count=len(sessions),
            eligible_count=eligible_count,
            dirty_skipped_count=dirty_skipped_count,
            non_sfe_ignored_count=non_sfe_ignored_count,
            removed_count=removed_count,
            entries=tuple(entries),
        )


class _GitResult:
    def __init__(self, completed: subprocess.CompletedProcess[str]) -> None:
        self.completed = completed

    @property
    def ok(self) -> bool:
        return self.completed.returncode == 0

    @property
    def stdout(self) -> str:
        return self.completed.stdout


class _GitWorktreeEntry:
    def __init__(self, path: Path, branch: str | None) -> None:
        self.path = path
        self.branch = branch


def _git(cwd: Path, *args: str) -> _GitResult:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return _GitResult(completed)


def _git_worktree_entries(git_root: Path) -> tuple[_GitWorktreeEntry, ...]:
    result = _git(git_root, "worktree", "list", "--porcelain")
    if not result.ok:
        return ()
    entries: list[_GitWorktreeEntry] = []
    current_path: Path | None = None
    current_branch: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current_path is not None:
                entries.append(_GitWorktreeEntry(current_path, current_branch))
            current_path = Path(line.removeprefix("worktree ")).resolve()
            current_branch = None
        elif line.startswith("branch "):
            current_branch = line.removeprefix("branch ")
            if current_branch.startswith("refs/heads/"):
                current_branch = current_branch.removeprefix("refs/heads/")
    if current_path is not None:
        entries.append(_GitWorktreeEntry(current_path, current_branch))
    return tuple(entries)


def _current_branch(git_root: Path) -> str:
    branch = _git(git_root, "branch", "--show-current")
    if branch.ok and branch.stdout.strip():
        return branch.stdout.strip()
    sha = _git(git_root, "rev-parse", "--short", "HEAD")
    if sha.ok and sha.stdout.strip():
        return f"HEAD-{sha.stdout.strip()}"
    return "HEAD"


def _new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def _resolve_worktree_parent(
    source_git_root: Path,
    policy: WorkspaceIsolationPolicy,
) -> Path:
    if policy.worktree_parent is not None:
        return policy.worktree_parent.expanduser().resolve()
    return (source_git_root.parent / ".sfe-worktrees").resolve()


def _changed_files_from_status(status_text: str) -> tuple[str, ...]:
    files: list[str] = []
    seen: set[str] = set()
    for line in status_text.splitlines():
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


def _write_session_metadata(session: WorkspaceSession) -> None:
    if session.metadata_path is None:
        return
    payload = {
        "session": {
            **asdict(session),
            "source_path": str(session.source_path),
            "source_git_root": str(session.source_git_root),
            "worktree_path": str(session.worktree_path),
            "metadata_path": str(session.metadata_path),
        }
    }
    session.metadata_path.write_text(
        json.dumps(payload, sort_keys=True, indent=2),
        encoding="utf-8",
    )


def _metadata_matches_session(session: WorkspaceSession) -> bool:
    if session.metadata_path is None:
        return False
    try:
        payload = json.loads(session.metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    stored = payload.get("session")
    if not isinstance(stored, dict):
        return False
    return (
        stored.get("session_id") == session.session_id
        and stored.get("created_by") == SFE_CREATED_BY
        and stored.get("backend_name") == session.backend_name
        and stored.get("worktree_branch") == session.worktree_branch
        and Path(str(stored.get("worktree_path") or "")).resolve()
        == session.worktree_path.resolve()
    )


def _load_sfe_sessions(worktree_parent: Path) -> tuple[WorkspaceSession, ...]:
    if not worktree_parent.exists() or not worktree_parent.is_dir():
        return ()
    sessions: list[WorkspaceSession] = []
    for metadata_path in sorted(worktree_parent.glob("*.sfe-session.json")):
        session = _session_from_metadata(metadata_path)
        if session is None:
            continue
        if not _is_sfe_session(session):
            continue
        if not _metadata_matches_session(session):
            continue
        sessions.append(session)
    return tuple(sessions)


def _session_from_metadata(metadata_path: Path) -> WorkspaceSession | None:
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    stored = payload.get("session")
    if not isinstance(stored, dict):
        return None
    try:
        return WorkspaceSession(
            session_id=str(stored["session_id"]),
            source_path=Path(str(stored["source_path"])).resolve(),
            source_git_root=Path(str(stored["source_git_root"])).resolve(),
            worktree_path=Path(str(stored["worktree_path"])).resolve(),
            source_branch=str(stored["source_branch"]),
            worktree_branch=str(stored["worktree_branch"]),
            backend_name=str(stored["backend_name"]),
            created_by=str(stored.get("created_by") or ""),
            metadata_path=metadata_path.resolve(),
            metadata={
                str(key): str(value)
                for key, value in dict(stored.get("metadata") or {}).items()
            },
        )
    except (KeyError, TypeError, ValueError):
        return None


def _is_sfe_session(session: WorkspaceSession) -> bool:
    return (
        session.created_by == SFE_CREATED_BY
        and session.backend_name == GitWorktreeBackend.name
        and session.worktree_branch.startswith(SFE_WORKTREE_BRANCH_PREFIX)
    )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True
