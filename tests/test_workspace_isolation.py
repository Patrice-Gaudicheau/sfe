"""Tests for core isolated workspace support."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.workspace_isolation import WorkspaceIsolationPolicy, WorkspaceManager


def test_non_git_workspace_returns_clear_unsupported_result(tmp_path) -> None:
    result = GitWorktreeBackend().create(tmp_path)

    assert result.created is False
    assert result.session is None
    assert result.issue is not None
    assert result.issue.category == "unsupported_workspace"
    assert result.issue.reason == "not_inside_git_repository"


def test_clean_git_repo_creates_isolated_worktree(tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = WorkspaceManager(GitWorktreeBackend())

    result = manager.create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )

    assert result.created is True
    assert result.session is not None
    session = result.session
    assert session.worktree_path.exists()
    assert session.worktree_branch.startswith("sfe/worktree/")
    assert session.source_branch == "main"
    assert session.metadata_path is not None
    assert session.metadata_path.exists()

    cleanup = manager.cleanup(session)
    assert cleanup.cleaned is True


def test_worktree_path_is_outside_original_workspace(tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    result = GitWorktreeBackend().create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )
    assert result.session is not None

    assert not _is_relative_to(result.session.worktree_path, repo)

    GitWorktreeBackend().cleanup(result.session)


def test_edits_in_worktree_do_not_affect_original_workspace(tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    backend = GitWorktreeBackend()
    result = backend.create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )
    assert result.session is not None
    session = result.session

    (session.worktree_path / "example.txt").write_text("changed in worktree\n", encoding="utf-8")
    status = backend.status(session)

    assert status.ok is True
    assert status.status is not None
    assert status.status.changed_files == ("example.txt",)
    assert "changed in worktree" in status.status.git_diff
    assert (repo / "example.txt").read_text(encoding="utf-8") == "initial\n"

    cleanup = backend.cleanup(session)
    assert cleanup.cleaned is True


def test_dirty_source_repo_refused_by_default(tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "example.txt").write_text("dirty\n", encoding="utf-8")

    result = GitWorktreeBackend().create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )

    assert result.created is False
    assert result.issue is not None
    assert result.issue.category == "dirty_source_repo"
    assert result.issue.reason == "dirty_source_refused_by_policy"


def test_dirty_source_repo_allowed_only_with_explicit_policy(tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "example.txt").write_text("dirty\n", encoding="utf-8")
    backend = GitWorktreeBackend()

    result = backend.create(
        repo,
        WorkspaceIsolationPolicy(
            allow_dirty_source=True,
            worktree_parent=tmp_path / "worktrees",
        ),
    )

    assert result.created is True
    assert result.session is not None
    assert (result.session.worktree_path / "example.txt").read_text(encoding="utf-8") == "initial\n"

    cleanup = backend.cleanup(result.session)
    assert cleanup.cleaned is True


def test_cleanup_removes_only_sfe_created_worktree(tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    backend = GitWorktreeBackend()
    result = backend.create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )
    assert result.session is not None
    session = result.session

    unsafe_session = replace(session, created_by="user")
    refused = backend.cleanup(unsafe_session)

    assert refused.cleaned is False
    assert refused.issue is not None
    assert refused.issue.category == "unsafe_cleanup_refused"
    assert session.worktree_path.exists()

    cleanup = backend.cleanup(session)
    assert cleanup.cleaned is True
    assert not session.worktree_path.exists()
    assert session.metadata_path is not None
    assert not session.metadata_path.exists()


def test_no_automatic_merge_to_main_happens(tmp_path) -> None:
    repo = _init_repo(tmp_path / "repo")
    backend = GitWorktreeBackend()
    result = backend.create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )
    assert result.session is not None
    session = result.session

    (session.worktree_path / "example.txt").write_text("changed in worktree\n", encoding="utf-8")

    assert _git(repo, "branch", "--show-current").stdout.strip() == "main"
    assert (repo / "example.txt").read_text(encoding="utf-8") == "initial\n"
    assert _git(repo, "status", "--porcelain").stdout.strip() == ""

    cleanup = backend.cleanup(session)
    assert cleanup.cleaned is True


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init")
    _git(path, "config", "user.email", "sfe@example.invalid")
    _git(path, "config", "user.name", "SFE Test")
    (path / "example.txt").write_text("initial\n", encoding="utf-8")
    _git(path, "add", "example.txt")
    _git(path, "commit", "-m", "initial")
    _git(path, "branch", "-M", "main")
    return path


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return completed


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True
