"""Tests for the intention-aware SFE run pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.codexcli import CodexCLITimeoutError
from sfe.discovery import discover_workspace_context
from sfe.discovery_router import (
    DiscoveryRouterError,
    DiscoveryRouterSelection,
    create_configured_discovery_router,
)
from sfe.execution_mode_router import (
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_EXTERNAL_ACTION,
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
    ExecutionModeRouterError,
    create_configured_execution_mode_router,
)
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.run_pipeline import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    GitPreparationResult,
    RunIssue,
    RunPipeline,
    RunProgressEvent,
    RunRequest,
)
from sfe.workspace_isolation import WorkspaceIsolationPolicy, WorkspaceManager
from sfe_tui.app import SfeTuiApp
from sfe_tui.backends import DirectBackend
from sfe_tui.executors import (
    DEFAULT_PATCH_OUTPUT_TOKENS,
    PATCH_SYSTEM_INSTRUCTION,
    ExecutorResponse,
    create_tui_executor,
)
from sfe_tui.renderer import render_help, render_run_result, render_run_result_normal


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


class FakeChatProvider:
    def __init__(
        self,
        *,
        answer: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.answer = "provider answer" if answer is None else answer
        self.error = error
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": True}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        return {"choices": [{"message": {"content": self.answer}}]}


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


class FailingDiscoveryRouter:
    provider_name = "unsupported-test-provider"
    model = None

    def select_files(
        self,
        *,
        task: str,
        workspace_map: list[dict[str, object]],
        max_files: int,
    ) -> DiscoveryRouterSelection:
        del task, workspace_map, max_files
        raise DiscoveryRouterError(
            "discovery_router_provider_not_supported",
            "configured provider is not supported for discovery routing",
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


def test_run_pipeline_console_output_emits_minimal_progress_events(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[RunProgressEvent] = []

    result = _pipeline(
        executor=FakeExecutor(console_answer="Symfony is a PHP framework."),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
        git_preparer=FailingGitPreparer(),
        progress_callback=events.append,
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Connais le Framework PHP intitulé Symfony ?",
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert [event.name for event in events] == [
        "run_started",
        "execution_mode_routing",
        "execution_mode_selected",
        "executor_prompt_prepared",
        "console_answer_generated",
    ]
    assert events[2].message == "SFE: execution mode selected: console_output"


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


def test_run_pipeline_workspace_write_emits_minimal_progress_events(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    events: list[RunProgressEvent] = []

    result = _pipeline(
        workspace_manager=manager,
        progress_callback=events.append,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert [event.name for event in events] == [
        "run_started",
        "execution_mode_routing",
        "execution_mode_selected",
        "workspace_preparation_started",
        "context_discovery_started",
        "context_candidates_inspected",
        "relevant_context_selected",
        "estimated_token_reduction",
        "executor_prompt_prepared",
        "patch_worktree_execution_started",
        "patch_validation_completed",
        "promotion_completed",
    ]
    assert events[2].message == "SFE: execution mode selected: workspace_write"
    assert events[5].metadata["candidate_count"] == 1
    assert events[6].metadata["selected_context_count"] == 1
    assert events[7].message.startswith("SFE: estimated token reduction: ")

    assert result.workspace_session is not None
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


def test_run_pipeline_creates_first_file_in_empty_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "empty-workspace"
    workspace.mkdir()
    manager = _manager()
    executor = FakeExecutor(_create_file_proposal("README.md"))
    discovery_router = FakeDiscoveryRouter(("README.md",))

    result = _pipeline(
        workspace_manager=manager,
        executor=executor,
        discovery_router=discovery_router,
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Create a minimal README for this empty workspace",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.discovery_result is not None
    assert result.discovery_result.stop_reason == "empty_workspace"
    assert result.discovery_result.candidate_count == 0
    assert discovery_router.calls == []
    assert result.selected_source_refs == ()
    assert len(executor.patch_calls) == 1
    assert executor.patch_calls[0]["selected_context_segments"] == []
    assert result.patch_applied is True
    assert result.promotion_status == "applied"
    assert result.promoted_files == ("README.md",)
    assert (workspace / "README.md").read_text(encoding="utf-8") == "escaped\n"
    assert not (tmp_path / "README.md").exists()

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_unknown_token_reduction_progress_uses_unknown_label(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "empty-workspace"
    workspace.mkdir()
    manager = _manager()
    events: list[RunProgressEvent] = []

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(_create_file_proposal("README.md")),
        discovery_router=FakeDiscoveryRouter(("README.md",)),
        progress_callback=events.append,
    ).run(
        RunRequest(
            workspace_root=workspace,
            task="Create a minimal README for this empty workspace",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    reduction_event = next(
        event for event in events if event.name == "estimated_token_reduction"
    )
    assert reduction_event.message == "SFE: estimated token reduction: unknown"
    assert reduction_event.metadata["estimated_token_reduction"] == "unknown"
    assert "0%" not in reduction_event.message

    assert result.workspace_session is not None
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


def test_run_pipeline_rejects_hunk_accounting_without_second_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("SFE_PATCH_NORMALIZE_HUNK_COUNTS", raising=False)
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor(_invalid_new_file_hunk_count_diff())

    result = _pipeline(
        workspace_manager=manager,
        executor=executor,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "impossible_hunk_accounting"
    assert result.issue.path == "index.html"
    diagnostics = result.issue.hunk_accounting
    assert diagnostics is not None
    assert diagnostics.hunk_header == "@@ -0,0 +1,5 @@"
    assert diagnostics.declared_old_count == 0
    assert diagnostics.declared_new_count == 5
    assert diagnostics.actual_old_side_count == 0
    assert diagnostics.actual_new_side_count == 3
    assert diagnostics.actual_added_line_count == 3
    assert diagnostics.looks_like_new_file is True
    assert diagnostics.old_file_header_is_dev_null is True
    assert diagnostics.hunk_body_only_added_lines is True
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert result.promoted_files == ()
    assert not (repo / "index.html").exists()
    assert len(executor.patch_calls) == 1
    proposal_diagnostics = result.patch_proposal_diagnostics
    assert proposal_diagnostics is not None
    assert proposal_diagnostics.contains_diff_git_header is True
    assert proposal_diagnostics.contains_hunk_header is True
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_normalizes_hunk_counts_when_flag_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_PATCH_NORMALIZE_HUNK_COUNTS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor(_invalid_new_file_hunk_count_diff())

    result = _pipeline(
        workspace_manager=manager,
        executor=executor,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.promoted_files == ("index.html",)
    assert (repo / "index.html").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    diagnostics = result.patch_hunk_count_normalization
    assert diagnostics is not None
    assert diagnostics.applied is True
    assert diagnostics.message == (
        "Hunk count normalization applied: declared old/new count was 0/5, "
        "but hunk body implies 0/3."
    )
    assert len(diagnostics.changes) == 1
    assert diagnostics.changes[0].original_hunk_header == "@@ -0,0 +1,5 @@"
    assert diagnostics.changes[0].normalized_hunk_header == "@@ -0,0 +1,3 @@"
    rendered = render_run_result(result)
    assert "SFE hunk count normalization" in rendered
    assert "applied: yes" in rendered
    assert "normalized hunk header: @@ -0,0 +1,3 @@" in rendered
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_normalized_hunk_still_fails_on_preimage_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_PATCH_NORMALIZE_HUNK_COUNTS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor(_invalid_context_modification_hunk_count_diff())

    result = _pipeline(
        workspace_manager=manager,
        executor=executor,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.reason == "hunk_preimage_mismatch"
    assert result.patch_generated is True
    assert result.patch_applied is False
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    diagnostics = result.patch_hunk_count_normalization
    assert diagnostics is not None
    assert diagnostics.applied is True
    assert diagnostics.changes[0].normalized_hunk_header == "@@ -1,1 +1,1 @@"
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_normalized_unknown_modify_target_still_rejected(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_PATCH_NORMALIZE_HUNK_COUNTS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor(_invalid_context_modification_hunk_count_diff("missing.txt"))

    result = _pipeline(
        workspace_manager=manager,
        executor=executor,
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
    assert result.issue.reason == "missing_target_not_safe_create"
    assert result.patch_applied is False
    assert not (repo / "missing.txt").exists()
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_does_not_repair_json_or_path_validation_failures(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    json_executor = FakeExecutor('{"edits": []}')
    json_result = _pipeline(
        executor=json_executor,
        workspace_manager=_manager(),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "json-worktrees"),
        )
    )

    assert json_result.status == RUN_STATUS_FAILED
    assert json_result.issue is not None
    assert json_result.issue.category == "invalid_patch_proposal"
    assert json_result.issue.reason == "missing_diff_header"
    assert json_result.patch_proposal_diagnostics is not None
    assert json_result.patch_proposal_diagnostics.looks_like_json is True

    path_executor = FakeExecutor(_valid_new_file_diff(path="../outside.txt"))
    path_result = _pipeline(
        executor=path_executor,
        workspace_manager=_manager(),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "path-worktrees"),
        )
    )

    assert path_result.status == RUN_STATUS_FAILED
    assert path_result.issue is not None
    assert path_result.issue.reason == "path_outside_workspace"


def test_run_pipeline_valid_unified_diff_applies_without_repair_metadata(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor(_valid_new_file_diff())

    result = _pipeline(
        workspace_manager=manager,
        executor=executor,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.promoted_files == ("index.html",)
    assert (repo / "index.html").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_codexcli_dev_patch_executor_applies_valid_unified_diff_through_sfe_pipeline(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    provider = FakeChatProvider(answer=_valid_new_file_diff())
    executor = create_tui_executor(
        environ={
            "SFE_PROVIDER": "codexcli",
            "SFE_CODEXCLI_EXECUTOR_MODEL": "gpt-codex-dev-patch-executor",
            "SFE_OPENAI_EXECUTOR_MODEL": "gpt-openai-executor-ignored",
        },
        provider_factories={"codexcli": lambda: provider},
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.executor_provider == "codexcli"
    assert result.patch_result is not None
    assert result.patch_result.summary["executor_provider"] == "codexcli"
    assert result.patch_result.summary["patch_applied"] is False
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.promoted_files == ("index.html",)
    assert (repo / "index.html").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert provider.calls[0]["model"] == "gpt-codex-dev-patch-executor"
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
    assert provider.calls[0]["max_tokens"] == DEFAULT_PATCH_OUTPUT_TOKENS
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_supports_codexcli_router_with_openai_executor_config(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    router_provider = FakeChatProvider(
        answer='{"execution_mode":"workspace_write","reason":"The task asks to edit files."}'
    )
    executor_provider = FakeChatProvider(answer=_valid_new_file_diff())
    environ = {
        "SFE_PROVIDER": "lemonade",
        "SFE_PROVIDER_ROUTER": "codexcli",
        "SFE_PROVIDER_EXECUTOR": "openai",
        "SFE_CODEXCLI_ROUTER_MODEL": "gpt-codex-router-role",
        "SFE_OPENAI_EXECUTOR_MODEL": "gpt-openai-executor-role",
    }
    execution_mode_router = create_configured_execution_mode_router(
        environ=environ,
        provider_factories={"codexcli": lambda: router_provider},
    )
    executor = create_tui_executor(
        environ=environ,
        provider_factories={"openai": lambda: executor_provider},
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=execution_mode_router,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.execution_mode_decision is not None
    assert result.execution_mode_decision.provider_name == "codexcli"
    assert result.executor_provider == "openai"
    assert router_provider.calls[0]["model"] == "gpt-codex-router-role"
    assert executor_provider.calls[0]["model"] == "gpt-openai-executor-role"
    assert result.promoted_files == ("index.html",)
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_fails_before_executor_when_discovery_router_is_unsupported(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor()

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FailingDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "context_discovery"
    assert result.issue.reason == "discovery_router_provider_not_supported"
    assert result.discovery_result is not None
    assert result.discovery_result.scanned_file_count >= 1
    assert result.discovery_result.workspace_map_count >= 1
    assert result.discovery_result.candidate_count == 0
    assert result.discovery_result.router_provider_name == "unsupported-test-provider"
    assert executor.patch_calls == []
    assert result.patch_result is None
    rendered = render_run_result_normal(result)
    assert (
        "hint: configured discovery provider unsupported-test-provider is not supported"
        in rendered
    )
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_supports_codexcli_discovery_with_fake_response(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor(_valid_new_file_diff())
    discovery_provider = FakeChatProvider(
        answer='{"files_to_inspect":["context.txt"],"reason":"Patch target context."}'
    )
    monkeypatch.delenv("SFE_PROVIDER", raising=False)
    monkeypatch.setenv("SFE_PROVIDER_ROUTER", "codexcli")
    monkeypatch.setenv("SFE_PROVIDER_DISCOVERY", "codexcli")
    monkeypatch.setenv("SFE_PROVIDER_EXECUTOR", "codexcli")
    monkeypatch.setenv("SFE_CODEXCLI_DISCOVERY_MODEL", "codexcli-discovery-model")
    discovery_router = create_configured_discovery_router(
        provider_factories={"codexcli": lambda: discovery_provider}
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=discovery_router,
        execution_mode_router=FakeExecutionModeRouter(),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.discovery_result is not None
    assert result.discovery_result.router_provider_name == "codexcli"
    assert result.discovery_result.router_model == "codexcli-discovery-model"
    assert result.discovery_result.router_error_category is None
    assert result.discovery_result.candidate_count == 1
    assert result.promoted_files == ("index.html",)
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_codexcli_prose_only_patch_fails_without_mutation(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    provider = FakeChatProvider(answer="I would update context.txt with new text.")
    executor = create_tui_executor(
        environ={"SFE_PROVIDER": "codexcli"},
        provider_factories={"codexcli": lambda: provider},
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
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
    assert result.executor_provider == "codexcli"
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_codexcli_unsafe_path_is_rejected_without_mutation(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    provider = FakeChatProvider(answer=_valid_new_file_diff(path="../outside.txt"))
    executor = create_tui_executor(
        environ={"SFE_PROVIDER": "codexcli"},
        provider_factories={"codexcli": lambda: provider},
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context with an unsafe file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.reason == "path_outside_workspace"
    assert result.executor_provider == "codexcli"
    assert result.patch_applied is False
    assert not (tmp_path / "outside.txt").exists()
    assert not (repo / "outside.txt").exists()
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_codexcli_timeout_does_not_mutate_worktree(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    provider = FakeChatProvider(error=CodexCLITimeoutError("timed out"))
    executor = create_tui_executor(
        environ={"SFE_PROVIDER": "codexcli"},
        provider_factories={"codexcli": lambda: provider},
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
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
    assert result.issue.reason == "timeout"
    assert result.executor_provider == "codexcli"
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
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
    assert "Resolve the task and show concise output" in rendered


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
    assert "promoted files: context.txt" in rendered
    assert "modified relative paths: context.txt" in rendered
    assert "created relative paths: none" in rendered
    assert "patch applied: yes" not in rendered
    assert "promotion: applied" not in rendered
    assert "router review: not run" not in rendered
    assert "diff: not shown" not in rendered
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
    run_output = output[-1]
    assert run_output == "Symfony is a PHP framework."
    assert "SFE run" not in run_output
    assert "execution mode: console_output" not in run_output
    assert "SFE console output" not in run_output
    assert "answer generation is not implemented" not in run_output
    assert "missing_diff_header" not in run_output
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
    assert "external action: not implemented" in rendered
    assert "issue category: unsupported_execution_mode" in rendered
    assert "issue reason: external_action_not_implemented" in rendered
    assert "worktree created: no" not in rendered
    assert "patch generated: no" not in rendered
    assert "patch applied: no" not in rendered
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
    progress_callback: object | None = None,
) -> RunPipeline:
    return RunPipeline(
        backend=DirectBackend(executor=executor or FakeExecutor()),
        workspace_manager=workspace_manager or _manager(),
        discovery_router=discovery_router or FakeDiscoveryRouter(),
        execution_mode_router=execution_mode_router or FakeExecutionModeRouter(),
        git_preparer=git_preparer,
        progress_callback=progress_callback,
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


def _invalid_new_file_hunk_count_diff(
    path: str = "index.html",
    *,
    content: tuple[str, ...] = ("one", "two", "three"),
) -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{path}",
            "@@ -0,0 +1,5 @@",
            *(f"+{line}" for line in content),
        ]
    )


def _valid_new_file_diff(path: str = "index.html") -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{path}",
            "@@ -0,0 +1,3 @@",
            "+one",
            "+two",
            "+three",
        ]
    )


def _invalid_context_modification_hunk_count_diff(path: str = "context.txt") -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -1,2 +1,2 @@",
            "-different context",
            "+new context",
        ]
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
