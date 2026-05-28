"""Tests for the intention-aware SFE run pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.discovery import discover_workspace_context
from sfe.discovery_router import DiscoveryRouterSelection
from sfe.execution_mode_router import (
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_EXTERNAL_ACTION,
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
    ExecutionModeRouterError,
)
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.run_pipeline import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    GitPreparationResult,
    RunIssue,
    RunPipeline,
    RunRequest,
)
from sfe.workspace_isolation import WorkspaceIsolationPolicy, WorkspaceManager
from sfe_tui.app import SfeTuiApp
from sfe_tui.backends import DirectBackend
from sfe_tui.executors import ExecutorResponse
from sfe_tui.renderer import render_help, render_run_result


class FakeExecutor:
    provider_name = "fake-executor"

    def __init__(
        self,
        patch_answer: str | None = None,
        console_answer: str | None = None,
        console_error_category: str | None = None,
    ) -> None:
        self.patch_answer = _replacement_proposal() if patch_answer is None else patch_answer
        self.console_answer = (
            "Symfony is a PHP framework." if console_answer is None else console_answer
        )
        self.console_error_category = console_error_category
        self.console_calls: list[dict[str, object]] = []
        self.patch_calls: list[dict[str, object]] = []

    def answer_console(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.console_calls.append(executor_payload)
        if self.console_error_category is not None:
            return ExecutorResponse(
                None,
                self.console_error_category,
                1,
                provider_name=self.provider_name,
            )
        return ExecutorResponse(
            self.console_answer,
            None,
            1,
            provider_name=self.provider_name,
        )

    def execute(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        return ExecutorResponse("unused", None, 1, provider_name=self.provider_name)

    def propose_patch(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.patch_calls.append(executor_payload)
        return ExecutorResponse(self.patch_answer, None, 1, provider_name=self.provider_name)


class FakeDiscoveryRouter:
    provider_name = "fake-discovery-router"
    model = "fake-discovery-model"

    def __init__(self, files_to_inspect: tuple[str, ...] = ("context.txt",)) -> None:
        self.files_to_inspect = files_to_inspect
        self.calls: list[dict[str, object]] = []

    def select_files(
        self,
        *,
        task: str,
        workspace_map: list[dict[str, object]],
        max_files: int,
    ) -> DiscoveryRouterSelection:
        self.calls.append(
            {
                "task": task,
                "workspace_map": workspace_map,
                "max_files": max_files,
            }
        )
        return DiscoveryRouterSelection(
            files_to_inspect=self.files_to_inspect,
            reason=f"selected files for {task}",
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class FakeExecutionModeRouter:
    provider_name = "fake-execution-mode-router"
    model = "fake-execution-mode-model"

    def __init__(
        self,
        execution_mode: str = EXECUTION_MODE_WORKSPACE_WRITE,
    ) -> None:
        self.execution_mode = execution_mode
        self.calls: list[dict[str, object]] = []

    def decide(self, *, task: str) -> ExecutionModeDecision:
        self.calls.append({"task": task})
        return ExecutionModeDecision(
            execution_mode=self.execution_mode,
            reason=f"fake selected {self.execution_mode}",
            confidence=0.87,
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class FailingExecutionModeRouter:
    provider_name = "failing-execution-mode-router"
    model = "failing-execution-mode-model"

    def decide(self, *, task: str) -> ExecutionModeDecision:
        del task
        raise ExecutionModeRouterError(
            "invalid_execution_mode_router_response",
            "simulated invalid routing response",
        )


class FakeInput:
    def __init__(self, values: list[str]) -> None:
        self.values = list(values)

    def prompt(self, message: str, default: str = "") -> str:
        del message
        if not self.values:
            return default
        value = self.values.pop(0)
        return value if value else default


class ExplodingReviewer:
    provider_name = "exploding-reviewer"
    model = "exploding-model"

    def review(self, payload: dict[str, object]) -> object:
        del payload
        raise AssertionError("router review must not run for /run")


class FailingGitPreparer:
    def prepare(self, workspace_root: Path) -> GitPreparationResult:
        del workspace_root
        return GitPreparationResult(
            ok=False,
            issue=RunIssue("git_auto_init", "simulated_git_prepare_failure"),
        )


def test_run_pipeline_refuses_without_task(tmp_path: Path) -> None:
    result = _pipeline().run(RunRequest(workspace_root=tmp_path, task=""))

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.reason == "missing_task"


def test_run_pipeline_refuses_without_workspace() -> None:
    result = _pipeline().run(RunRequest(workspace_root=None, task="Patch context"))

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.reason == "workspace_not_selected"


def test_run_pipeline_console_output_generates_answer_before_worktree_or_patch(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(console_answer="Symfony is a PHP framework.")
    router = FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT)
    discovery_router = FakeDiscoveryRouter()

    result = _pipeline(
        executor=executor,
        discovery_router=discovery_router,
        execution_mode_router=router,
        git_preparer=FailingGitPreparer(),
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Connais le Framework PHP intitulé Symfony ?",
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.execution_mode_decision is not None
    assert result.execution_mode_decision.execution_mode == EXECUTION_MODE_CONSOLE_OUTPUT
    assert result.console_output == "Symfony is a PHP framework."
    assert "answer generation is not implemented" not in result.console_output
    assert result.workspace_session is None
    assert result.worktree_created is False
    assert result.discovery_result is None
    assert result.dry_run_result is None
    assert result.patch_result is None
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert result.promotion_applied is False
    assert result.executor_provider == "fake-executor"
    assert len(executor.console_calls) == 1
    assert executor.console_calls[0]["selected_context_segments"] == []
    assert executor.patch_calls == []
    assert discovery_router.calls == []
    assert router.calls == [{"task": "Connais le Framework PHP intitulé Symfony ?"}]
    assert not (workspace / ".git").exists()
    assert not (workspace / ".sfe-worktrees").exists()
    assert (workspace / "context.txt").read_text(encoding="utf-8") == "old context\n"


def test_run_pipeline_console_output_failure_returns_before_worktree_or_patch(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(console_error_category="provider_error")
    discovery_router = FakeDiscoveryRouter()

    result = _pipeline(
        executor=executor,
        discovery_router=discovery_router,
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
        git_preparer=FailingGitPreparer(),
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Connais le Framework PHP intitulé Symfony ?",
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "console_output"
    assert result.issue.reason == "provider_error"
    assert result.console_output is None
    assert result.workspace_session is None
    assert result.worktree_created is False
    assert result.discovery_result is None
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert len(executor.console_calls) == 1
    assert executor.patch_calls == []
    assert discovery_router.calls == []
    assert not (workspace / ".git").exists()
    assert not (workspace / ".sfe-worktrees").exists()
    assert (workspace / "context.txt").read_text(encoding="utf-8") == "old context\n"


def test_run_pipeline_execution_mode_failure_returns_before_worktree(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor()

    result = _pipeline(
        executor=executor,
        execution_mode_router=FailingExecutionModeRouter(),
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Patch context",
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "execution_mode_routing"
    assert result.issue.reason == "invalid_execution_mode_router_response"
    assert result.workspace_session is None
    assert result.worktree_created is False
    assert result.patch_generated is False
    assert executor.patch_calls == []
    assert not (workspace / ".git").exists()
    assert not (workspace / ".sfe-worktrees").exists()


def test_run_pipeline_external_action_fails_before_worktree_or_patch(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor()
    router = FakeExecutionModeRouter(EXECUTION_MODE_EXTERNAL_ACTION)

    result = _pipeline(
        executor=executor,
        execution_mode_router=router,
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Create a calendar event for tomorrow.",
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "unsupported_execution_mode"
    assert result.issue.reason == "external_action_not_implemented"
    assert result.execution_mode_decision is not None
    assert result.execution_mode_decision.execution_mode == EXECUTION_MODE_EXTERNAL_ACTION
    assert result.workspace_session is None
    assert result.worktree_created is False
    assert result.discovery_result is None
    assert result.dry_run_result is None
    assert result.patch_result is None
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert result.promotion_applied is False
    assert executor.patch_calls == []
    assert router.calls == [{"task": "Create a calendar event for tomorrow."}]
    assert not (workspace / ".git").exists()
    assert not (workspace / ".sfe-worktrees").exists()
    assert (workspace / "context.txt").read_text(encoding="utf-8") == "old context\n"


def test_run_pipeline_unknown_execution_mode_fails_closed(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor()

    result = _pipeline(
        executor=executor,
        execution_mode_router=FakeExecutionModeRouter("unknown_mode"),
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Patch context",
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "execution_mode_routing"
    assert result.issue.reason == "invalid_execution_mode"
    assert result.workspace_session is None
    assert result.worktree_created is False
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert executor.patch_calls == []
    assert not (workspace / ".git").exists()
    assert not (workspace / ".sfe-worktrees").exists()
    assert (workspace / "context.txt").read_text(encoding="utf-8") == "old context\n"


def test_run_pipeline_creates_worktree_applies_patch_and_promotes(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    pipeline = _pipeline(workspace_manager=manager)

    result = pipeline.run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.workspace_session is not None
    assert result.workspace_session.worktree_path.parent == repo / ".sfe-worktrees"
    assert result.worktree_created is True
    assert result.git_auto_init is False
    assert result.git_initial_commit_hash is None
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.promotion_status == "applied"
    assert result.promotion_applied is True
    assert result.promoted_files == ("context.txt",)
    assert result.changed_files == ("context.txt",)
    assert result.patch_summary is not None
    assert result.patch_summary.modified_paths == ("context.txt",)
    assert (repo / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert (result.workspace_session.worktree_path / "context.txt").read_text(
        encoding="utf-8"
    ) == "new context\n"

    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_auto_initializes_non_git_workspace_then_uses_worktree(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    (workspace / ".sfe-worktrees").mkdir()
    (workspace / ".sfe-worktrees" / "stale.txt").write_text("ignore me\n", encoding="utf-8")
    manager = _manager()

    result = _pipeline(workspace_manager=manager).run(
        RunRequest(
            workspace_root=workspace,
            task="Patch context",
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.git_auto_init is True
    assert result.git_initial_commit_hash is not None
    assert (workspace / ".git").is_dir()
    assert _git(workspace, "branch", "--show-current").stdout.strip() == "main"
    assert _git(workspace, "remote", "-v").stdout.strip() == ""
    assert ".sfe-worktrees/stale.txt" not in _git(workspace, "ls-files").stdout
    assert (workspace / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert _git(workspace, "status", "--short").stdout.strip() == "M context.txt"
    assert result.workspace_session is not None
    assert result.workspace_session.worktree_path.parent == workspace / ".sfe-worktrees"
    assert (result.workspace_session.worktree_path / "context.txt").read_text(
        encoding="utf-8"
    ) == "new context\n"
    assert result.changed_files == ("context.txt",)
    assert result.promotion_status == "applied"
    assert result.promoted_files == ("context.txt",)

    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_promotes_created_files_to_source_workspace(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(_create_file_proposal("docs/example.txt")),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context by creating a small docs file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_applied is True
    assert result.promotion_status == "applied"
    assert result.promoted_files == ("docs/example.txt",)
    assert (repo / "docs" / "example.txt").read_text(encoding="utf-8") == "escaped\n"
    assert result.workspace_session is not None
    assert (
        result.workspace_session.worktree_path / "docs" / "example.txt"
    ).read_text(encoding="utf-8") == "escaped\n"

    assert manager.cleanup(result.workspace_session).cleaned is True


def test_discover_does_not_auto_initialize_non_git_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")

    result = discover_workspace_context(
        workspace_root=workspace,
        task="Patch context",
        router=FakeDiscoveryRouter(),
    )

    assert result.workspace_root_present is True
    assert result.candidate_count == 1
    assert not (workspace / ".git").exists()


def test_run_pipeline_reports_git_preparation_failure(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")

    result = _pipeline(git_preparer=FailingGitPreparer()).run(
        RunRequest(workspace_root=workspace, task="Patch context")
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "git_auto_init"
    assert result.issue.reason == "simulated_git_prepare_failure"
    assert result.patch_generated is False
    assert result.patch_applied is False


def test_run_pipeline_reuses_active_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    created = manager.create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )
    assert created.session is not None

    result = _pipeline(workspace_manager=manager).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_session=created.session,
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.workspace_session == created.session
    assert result.worktree_created is False
    assert result.promotion_status == "applied"
    assert (repo / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert (created.session.worktree_path / "context.txt").read_text(
        encoding="utf-8"
    ) == "new context\n"

    assert manager.cleanup(created.session).cleaned is True


def test_run_pipeline_rejects_promotion_when_source_diverged(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    created = manager.create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )
    assert created.session is not None
    (repo / "context.txt").write_text("user changed source\n", encoding="utf-8")

    result = _pipeline(workspace_manager=manager).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_session=created.session,
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.patch_generated is True
    assert result.patch_applied is False
    assert result.promotion_status == "rejected"
    assert result.promotion_applied is False
    assert result.issue is not None
    assert result.issue.category == "promotion"
    assert result.issue.reason == "source_workspace_changed"
    assert result.issue.path == "context.txt"
    assert (repo / "context.txt").read_text(encoding="utf-8") == "user changed source\n"
    assert (created.session.worktree_path / "context.txt").read_text(
        encoding="utf-8"
    ) == "old context\n"

    assert manager.cleanup(created.session).cleaned is True


def test_run_pipeline_rejects_internal_promotion_paths(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(_create_file_proposal(".sfe-worktrees/leak.txt")),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context by creating an internal file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.patch_generated is True
    assert result.patch_applied is False
    assert result.promotion_status == "rejected"
    assert result.promotion_applied is False
    assert result.issue is not None
    assert result.issue.category == "promotion"
    assert result.issue.reason == "internal_path_not_promoted"
    assert result.issue.path == ".sfe-worktrees/leak.txt"
    rendered = render_run_result(result)
    assert "promotion: rejected" in rendered
    assert "promotion issue reason: internal_path_not_promoted" in rendered
    assert "promotion issue path: .sfe-worktrees/leak.txt" in rendered
    assert not (repo / ".sfe-worktrees" / "leak.txt").exists()

    assert result.workspace_session is not None
    assert not (
        result.workspace_session.worktree_path / ".sfe-worktrees" / "leak.txt"
    ).exists()
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_does_not_require_router_review_or_diff_inspection(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    result = _pipeline(workspace_manager=manager).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert "no_router_review_run" in result.warnings
    assert "diff_not_inspected" in result.warnings

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_refuses_parent_traversal_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    pipeline = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(_replacement_proposal(path="../outside.txt")),
    )

    result = pipeline.run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.patch_generated is True
    assert result.patch_applied is False
    assert result.issue is not None
    assert result.issue.reason == "path_outside_workspace"
    assert not (tmp_path / "outside.txt").exists()

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_refuses_symlink_escape_from_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    created = manager.create(
        repo,
        WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
    )
    assert created.session is not None
    outside = tmp_path / "outside"
    outside.mkdir()
    (created.session.worktree_path / "linked").symlink_to(outside, target_is_directory=True)
    pipeline = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(_create_file_proposal("linked/escape.txt")),
    )

    result = pipeline.run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_session=created.session,
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.reason == "path_outside_workspace"
    assert not (outside / "escape.txt").exists()

    assert manager.cleanup(created.session).cleaned is True


def test_run_pipeline_reports_plain_text_patch_proposal_diagnostics(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _add_readme(repo)
    manager = _manager()
    raw_output = (
        "# SFE Test 01\n\n"
        "Short README sentence.\n\n"
        "## Checks\n\n"
        "- README.md selected.\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
        discovery_router=FakeDiscoveryRouter(("README.md",)),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Replace README.md with short content",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "missing_diff_header"
    assert result.patch_generated is False
    assert result.patch_applied is False
    diagnostics = result.patch_proposal_diagnostics
    assert diagnostics is not None
    assert diagnostics.raw_output_length == len(raw_output)
    assert diagnostics.is_empty is False
    assert diagnostics.first_non_empty_line == "# SFE Test 01"
    assert diagnostics.contains_diff_git_header is False
    assert diagnostics.contains_hunk_header is False
    assert diagnostics.looks_like_json is False
    assert diagnostics.mentions_selected_paths == ("README.md",)
    assert diagnostics.looks_like_plain_text_or_markdown is True
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_reports_empty_patch_proposal_diagnostics(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(""),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "patch_generation"
    assert result.issue.reason == "invalid_response"
    diagnostics = result.patch_proposal_diagnostics
    assert diagnostics is not None
    assert diagnostics.raw_output_length == 0
    assert diagnostics.is_empty is True
    assert diagnostics.first_non_empty_line is None
    assert diagnostics.looks_like_plain_text_or_markdown is False
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_reports_fenced_diff_patch_proposal_diagnostics(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = "```diff\n--- a/context.txt\n+++ b/context.txt\n@@ -1 +1 @@\n-old\n+new\n```"

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "missing_diff_header"
    diagnostics = result.patch_proposal_diagnostics
    assert diagnostics is not None
    assert diagnostics.starts_with_markdown_fence is True
    assert diagnostics.contains_fenced_diff is True
    assert diagnostics.contains_diff_git_header is False
    assert diagnostics.contains_old_file_header is True
    assert diagnostics.contains_new_file_header is True
    assert diagnostics.contains_hunk_header is True
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_reports_json_looking_patch_proposal_diagnostics(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _add_readme(repo)
    manager = _manager()
    raw_output = '{"message": "README.md should be updated"}'

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
        discovery_router=FakeDiscoveryRouter(("README.md",)),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Replace README.md with short content",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "missing_diff_header"
    diagnostics = result.patch_proposal_diagnostics
    assert diagnostics is not None
    assert diagnostics.looks_like_json is True
    assert diagnostics.mentions_selected_paths == ("README.md",)
    assert diagnostics.looks_like_plain_text_or_markdown is False
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_renders_invalid_patch_diagnostics_without_full_output(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    _add_readme(repo)
    manager = _manager()
    raw_output = "# " + ("SFE Test 01 " * 30) + "\n\nREADME.md content."

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
        discovery_router=FakeDiscoveryRouter(("README.md",)),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Replace README.md with short content",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    rendered = render_run_result(result)

    assert "patch proposal output length:" in rendered
    assert "patch proposal empty: no" in rendered
    assert "patch proposal first line: # SFE Test 01" in rendered
    assert "patch proposal looks like plain text: yes" in rendered
    assert "patch proposal mentions selected paths: README.md" in rendered
    assert raw_output not in rendered
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_returns_compact_summary_with_changed_files(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    result = _pipeline(workspace_manager=manager).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.discovery_result is not None
    assert result.selected_source_refs == ("context.txt",)
    assert result.executor_provider == "fake-executor"
    assert result.changed_files == ("context.txt",)
    assert result.promotion_status == "applied"
    assert result.promoted_files == ("context.txt",)
    assert result.patch_summary is not None
    assert result.patch_summary.file_count == 1

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_tui_run_is_in_help() -> None:
    rendered = render_help()

    assert "/run" in rendered
    assert "Resolve the task via console answer or workspace write" in rendered


def test_tui_run_uses_pipeline_without_patch_reviewer(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch context", "/run", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=FakeExecutor()),
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        patch_reviewer=ExplodingReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE run" in rendered
    assert "status: completed" in rendered
    assert "patch applied: yes" in rendered
    assert "promotion: applied" in rendered
    assert "promoted files: context.txt" in rendered
    assert "router review: not run" in rendered
    assert "diff: not shown" in rendered
    assert "diff --git" not in rendered
    assert (repo / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert app.workspace_session is not None
    assert (app.workspace_session.worktree_path / "context.txt").read_text(
        encoding="utf-8"
    ) == "new context\n"

    assert app.workspace_manager.cleanup(app.workspace_session).cleaned is True


def test_tui_run_renders_console_output_without_worktree(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Connais le Framework PHP intitulé Symfony ?", "/run", "/quit"]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
        patch_reviewer=ExplodingReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE run" in rendered
    assert "status: completed" in rendered
    assert "execution mode: console_output" in rendered
    assert "worktree created: no" in rendered
    assert "patch generated: no" in rendered
    assert "patch applied: no" in rendered
    assert "SFE console output" in rendered
    assert "Symfony is a PHP framework." in rendered
    assert "answer generation is not implemented" not in rendered
    assert "missing_diff_header" not in rendered
    assert len(executor.console_calls) == 1
    assert executor.patch_calls == []
    assert app.workspace_session is None
    assert not (workspace / ".git").exists()
    assert not (workspace / ".sfe-worktrees").exists()
    assert (workspace / "context.txt").read_text(encoding="utf-8") == "old context\n"


def test_tui_run_renders_external_action_without_worktree(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.txt").write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Create a calendar event for tomorrow", "/run", "/quit"]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_EXTERNAL_ACTION),
        patch_reviewer=ExplodingReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE run" in rendered
    assert "status: failed" in rendered
    assert "execution mode: external_action" in rendered
    assert "issue category: unsupported_execution_mode" in rendered
    assert "issue reason: external_action_not_implemented" in rendered
    assert "worktree created: no" in rendered
    assert "patch generated: no" in rendered
    assert "patch applied: no" in rendered
    assert executor.patch_calls == []
    assert app.workspace_session is None
    assert not (workspace / ".git").exists()
    assert not (workspace / ".sfe-worktrees").exists()
    assert (workspace / "context.txt").read_text(encoding="utf-8") == "old context\n"


def _pipeline(
    *,
    workspace_manager: WorkspaceManager | None = None,
    executor: FakeExecutor | None = None,
    discovery_router: FakeDiscoveryRouter | None = None,
    execution_mode_router: object | None = None,
    git_preparer: object | None = None,
) -> RunPipeline:
    return RunPipeline(
        backend=DirectBackend(executor=executor or FakeExecutor()),
        workspace_manager=workspace_manager or _manager(),
        discovery_router=discovery_router or FakeDiscoveryRouter(),
        execution_mode_router=execution_mode_router or FakeExecutionModeRouter(),
        git_preparer=git_preparer,
    )


def _manager() -> WorkspaceManager:
    return WorkspaceManager(GitWorktreeBackend())


def _replacement_proposal(path: str = "context.txt") -> str:
    return json.dumps(
        {
            "edits": [
                {
                    "path": path,
                    "action": "replace_existing_file",
                    "content": "new context\n",
                }
            ]
        }
    )


def _create_file_proposal(path: str) -> str:
    return json.dumps(
        {
            "edits": [
                {
                    "path": path,
                    "action": "create_file",
                    "content": "escaped\n",
                }
            ]
        }
    )


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "sfe@example.test")
    _git(path, "config", "user.name", "SFE Test")
    (path / "context.txt").write_text("old context\n", encoding="utf-8")
    _git(path, "add", "context.txt")
    _git(path, "commit", "-m", "initial")
    return path


def _add_readme(repo: Path) -> None:
    (repo / "README.md").write_text("old readme\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "add readme")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
