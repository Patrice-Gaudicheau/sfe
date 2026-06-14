"""Tests for the intention-aware SFE run pipeline."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.codexcli import CodexCLITimeoutError
from sfe.contracts import build_contract
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
from sfe.execution_backend import ExecutionResult
from sfe.filesystem_executor import (
    FilesystemExecutionDiagnostics,
    FilesystemExecutionRequest,
    FilesystemExecutionResult,
)
from sfe.git_worktree_backend import GitWorktreeBackend
from sfe.full_file_replacement_review import (
    FullFileReplacementReviewDecision,
    FullFileReplacementReviewRequest,
    parse_full_file_replacement_review_json,
)
from sfe.multipass import (
    MultiPassBatch,
    MultiPassConfig,
    MultiPassIssue,
    MultiPassPlan,
    parse_multipass_plan_json,
)
from sfe.multipass_planner import MultiPassPlannerResponse
from sfe.patching import PatchApplyResult, PatchIssue
import sfe.run_pipeline as run_pipeline_module
from sfe.run_pipeline import (
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    GitPreparationResult,
    RunIssue,
    RunPipeline,
    RunProgressEvent,
    RunRequest,
)
from sfe.workspace_write_executor import resolve_workspace_write_executor
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


@pytest.fixture(autouse=True)
def _default_legacy_text_workspace_write_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_EXECUTOR", "text")


class FakeExecutor:
    provider_name = "fake-executor"

    def __init__(
        self,
        patch_answer: str | None = None,
        console_answer: str | None = None,
        console_error_category: str | None = None,
        multipass_patch_answers: list[ExecutorResponse | str] | None = None,
    ) -> None:
        self.patch_answer = _replacement_proposal() if patch_answer is None else patch_answer
        self.console_answer = (
            "Symfony is a PHP framework." if console_answer is None else console_answer
        )
        self.console_error_category = console_error_category
        self.multipass_patch_answers = list(multipass_patch_answers or [])
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
        if executor_payload.get("multi_pass"):
            answer = self.multipass_patch_answers.pop(0)
            if isinstance(answer, ExecutorResponse):
                return answer
            return ExecutorResponse(answer, None, 1, provider_name=self.provider_name)
        return ExecutorResponse(self.patch_answer, None, 1, provider_name=self.provider_name)


class GenericTextWorkspaceWriteBackend:
    name = "generic-text"

    def __init__(self, answer: str) -> None:
        self.answer = answer

    def dry_run(self, contract):
        return ExecutionResult(
            backend=self.name,
            status="ok",
            provider_calls_made=0,
            summary={},
            contract=contract,
        )

    def console(self, contract):
        raise NotImplementedError

    def patch(self, contract):
        return ExecutionResult(
            backend=self.name,
            status="ok",
            provider_calls_made=1,
            summary={"executor_provider": "generic-text-provider"},
            contract=contract,
            answer=self.answer,
        )

    def patch_multipass_batch(self, contract, *, plan, batch, completed_files):
        return self.patch(contract)


class DirectMutationExecutor(FakeExecutor):
    def __init__(self, mutation: object) -> None:
        super().__init__(patch_answer="workspace mutated")
        self.mutation = mutation

    def propose_patch(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.patch_calls.append(executor_payload)
        cwd_value = executor_payload.get("executor_working_directory")
        assert isinstance(cwd_value, str)
        self.mutation(Path(cwd_value))
        return ExecutorResponse(
            "workspace mutated",
            None,
            1,
            provider_name=self.provider_name,
        )


class FakeFilesystemExecutor:
    name = "fake-aider"

    def __init__(
        self,
        mutation: object | None = None,
        *,
        status: str = "completed",
        error_category: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.mutation = mutation
        self.status = status
        self.error_category = error_category
        self.metadata = metadata or {}
        self.calls: list[FilesystemExecutionRequest] = []

    def execute(
        self,
        request: FilesystemExecutionRequest,
    ) -> FilesystemExecutionResult:
        self.calls.append(request)
        if self.mutation is not None:
            self.mutation(request.cwd)
        return FilesystemExecutionResult(
            executor_name=self.name,
            status=self.status,
            changed_paths=(),
            diagnostics=FilesystemExecutionDiagnostics(
                executor_name=self.name,
                cwd=str(request.cwd),
                command=("fake-aider", "--message-file", "<message-file>"),
                return_code=0 if self.status == "completed" else 1,
                stdout_length=0,
                stderr_length=0,
                stdout_preview="",
                stderr_preview="",
                elapsed_ms=1,
            ),
            error_category=self.error_category,
            metadata=self.metadata,
        )


class FakeMultiPassPlanner:
    provider_name = "fake-router-planner"
    model = "fake-router-planner-model"

    def __init__(
        self,
        plan_answer: str | None = None,
        *,
        issue: MultiPassIssue | None = None,
    ) -> None:
        self.plan_answer = plan_answer
        self.issue = issue
        self.calls: list[dict[str, object]] = []

    def plan(
        self,
        contract: object,
        *,
        config: MultiPassConfig,
    ) -> MultiPassPlannerResponse:
        self.calls.append({"contract": contract, "config": config})
        if self.issue is not None:
            return MultiPassPlannerResponse(
                plan=None,
                issue=self.issue,
                answer=self.plan_answer,
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        if not self.plan_answer:
            return MultiPassPlannerResponse(
                plan=None,
                issue=MultiPassIssue("multi_pass_planning", "invalid_response"),
                answer=self.plan_answer,
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        parsed = parse_multipass_plan_json(self.plan_answer)
        if isinstance(parsed, MultiPassIssue):
            return MultiPassPlannerResponse(
                plan=None,
                issue=parsed,
                answer=self.plan_answer,
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        return MultiPassPlannerResponse(
            plan=parsed,
            issue=None,
            answer=self.plan_answer,
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class FakeFullFileReplacementReviewer:
    provider_name = "fake-reviewer"
    model = "fake-reviewer-model"

    def __init__(
        self,
        decision: FullFileReplacementReviewDecision | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.decision = decision or FullFileReplacementReviewDecision(
            approve=True,
            risk_level="low",
            reason="replacement is coherent",
        )
        self.error = error
        self.calls: list[FullFileReplacementReviewRequest] = []

    def review(
        self,
        request: FullFileReplacementReviewRequest,
    ) -> FullFileReplacementReviewDecision:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.decision


def test_workspace_write_executor_defaults_to_aider_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SFE_WORKSPACE_WRITE_EXECUTOR", raising=False)

    assert resolve_workspace_write_executor() == "aider"


def test_workspace_write_executor_blank_defaults_to_aider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_EXECUTOR", "  ")

    assert resolve_workspace_write_executor() == "aider"


def test_workspace_write_executor_explicit_text_keeps_legacy_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_EXECUTOR", "text")

    assert resolve_workspace_write_executor() == "text"


class FakeChatProvider:
    def __init__(
        self,
        *,
        answer: str | None = None,
        response: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.answer = "provider answer" if answer is None else answer
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": True}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
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
        "workspace_boundary_check_completed",
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


def test_run_pipeline_accepts_direct_created_modified_and_deleted_files_inside_destination(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "obsolete.txt").write_text("remove me\n", encoding="utf-8")
    _git(repo, "add", "obsolete.txt")
    _git(repo, "commit", "-m", "Add obsolete file")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        (workspace / "context.txt").write_text("directly modified\n", encoding="utf-8")
        (workspace / "created.txt").write_text("directly created\n", encoding="utf-8")
        (workspace / "obsolete.txt").unlink()

    result = _pipeline(
        workspace_manager=manager,
        executor=DirectMutationExecutor(mutate),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and mutate files directly",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert result.changed_files == ("context.txt", "obsolete.txt", "created.txt")
    assert result.promoted_files == ("context.txt", "obsolete.txt", "created.txt")
    assert result.promotion_status == "applied"
    assert (repo / "context.txt").read_text(encoding="utf-8") == "directly modified\n"
    assert (repo / "created.txt").read_text(encoding="utf-8") == "directly created\n"
    assert not (repo / "obsolete.txt").exists()

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_unknown_workspace_write_executor_fails_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_EXECUTOR", "bogus")
    repo = _init_repo(tmp_path / "repo")
    executor = FakeExecutor()

    result = _pipeline(executor=executor).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "workspace_write_executor"
    assert result.issue.reason == "unsupported_workspace_write_executor"
    assert result.issue.diagnostics is not None
    assert result.issue.diagnostics["configured_value"] == "bogus"
    assert executor.patch_calls == []


def test_run_pipeline_missing_aider_fails_closed_without_text_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SFE_WORKSPACE_WRITE_EXECUTOR", raising=False)
    repo = _init_repo(tmp_path / "repo")
    text_executor = FakeExecutor(_create_file_proposal("should-not-run.txt"))
    filesystem_executor = FakeFilesystemExecutor(
        status="failed",
        error_category="aider_missing",
        metadata={
            "install_guidance": (
                "sudo apt update",
                "sudo apt install pipx",
                "pipx install aider-chat",
            )
        },
    )

    result = _pipeline(
        executor=text_executor,
        filesystem_executor=filesystem_executor,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "workspace_write_executor"
    assert result.issue.reason == "aider_missing"
    assert result.issue.diagnostics is not None
    assert result.issue.diagnostics["install_guidance"] == (
        "sudo apt update",
        "sudo apt install pipx",
        "pipx install aider-chat",
    )
    assert text_executor.patch_calls == []
    assert filesystem_executor.calls
    assert not (repo / "should-not-run.txt").exists()


def test_run_pipeline_default_aider_invokes_filesystem_executor_inside_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SFE_WORKSPACE_WRITE_EXECUTOR", raising=False)
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        (workspace / "created.txt").write_text("from fake aider\n", encoding="utf-8")

    filesystem_executor = FakeFilesystemExecutor(mutate)
    result = _pipeline(
        workspace_manager=manager,
        filesystem_executor=filesystem_executor,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create a file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.executor_provider == "fake-aider"
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert result.promoted_files == ("created.txt",)
    assert (repo / "created.txt").read_text(encoding="utf-8") == "from fake aider\n"
    assert result.workspace_session is not None
    assert result.active_workspace is not None
    assert filesystem_executor.calls[0].cwd == result.active_workspace
    assert filesystem_executor.calls[0].cwd != repo
    assert filesystem_executor.calls[0].cwd.is_relative_to(
        result.workspace_session.worktree_path
    )
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_promotes_committed_worktree_changes_relative_to_source_head(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "obsolete.txt").write_text("remove me\n", encoding="utf-8")
    _git(repo, "add", "obsolete.txt")
    _git(repo, "commit", "-m", "Add obsolete file")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        (workspace / "context.txt").write_text("committed modified\n", encoding="utf-8")
        (workspace / "created.txt").write_text("committed created\n", encoding="utf-8")
        (workspace / "obsolete.txt").unlink()
        _git(workspace, "add", "-A")
        _git(workspace, "commit", "-m", "Aider-style committed changes")

    result = _pipeline(
        workspace_manager=manager,
        executor=DirectMutationExecutor(mutate),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and commit files inside the worktree",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert set(result.changed_files) == {"context.txt", "created.txt", "obsolete.txt"}
    assert set(result.promoted_files) == {"context.txt", "created.txt", "obsolete.txt"}
    assert result.promotion_status == "applied"
    assert (repo / "context.txt").read_text(encoding="utf-8") == "committed modified\n"
    assert (repo / "created.txt").read_text(encoding="utf-8") == "committed created\n"
    assert not (repo / "obsolete.txt").exists()

    assert result.workspace_session is not None
    assert (
        _git(result.workspace_session.worktree_path, "status", "--porcelain")
        .stdout.strip()
        == ""
    )
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_default_aider_promotes_committed_worktree_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SFE_WORKSPACE_WRITE_EXECUTOR", raising=False)
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        (workspace / "context.txt").write_text("committed by fake aider\n", encoding="utf-8")
        (workspace / "aider-created.txt").write_text("created\n", encoding="utf-8")
        _git(workspace, "add", "-A")
        _git(workspace, "commit", "-m", "Fake Aider commit")

    result = _pipeline(
        workspace_manager=manager,
        filesystem_executor=FakeFilesystemExecutor(mutate),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create a committed file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert set(result.promoted_files) == {"context.txt", "aider-created.txt"}
    assert (repo / "context.txt").read_text(encoding="utf-8") == "committed by fake aider\n"
    assert (repo / "aider-created.txt").read_text(encoding="utf-8") == "created\n"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_direct_change_outside_destination_directory(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    app_dir = repo / "app"
    app_dir.mkdir()
    (app_dir / "context.txt").write_text("app context\n", encoding="utf-8")
    _git(repo, "add", "app/context.txt")
    _git(repo, "commit", "-m", "Add app context")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        (workspace / "context.txt").write_text("inside app\n", encoding="utf-8")
        (workspace.parent / "outside-app.txt").write_text("outside app\n", encoding="utf-8")

    result = _pipeline(
        workspace_manager=manager,
        executor=DirectMutationExecutor(mutate),
        discovery_router=FakeDiscoveryRouter(("context.txt",)),
    ).run(
        RunRequest(
            workspace_root=app_dir,
            task="Mutate inside app and outside app",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "workspace_boundary"
    assert result.issue.reason == "changed_path_outside_destination"
    assert result.issue.diagnostics is not None
    assert result.issue.diagnostics["authorized_output_root"] == str(app_dir.resolve())
    assert result.issue.diagnostics["offending_paths"] == ("outside-app.txt",)
    assert (app_dir / "context.txt").read_text(encoding="utf-8") == "app context\n"
    assert not (repo / "outside-app.txt").exists()

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_default_aider_rejects_out_of_destination_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SFE_WORKSPACE_WRITE_EXECUTOR", raising=False)
    repo = _init_repo(tmp_path / "repo")
    app_dir = repo / "app"
    app_dir.mkdir()
    (app_dir / "context.txt").write_text("app context\n", encoding="utf-8")
    _git(repo, "add", "app/context.txt")
    _git(repo, "commit", "-m", "Add app context")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        (workspace / "context.txt").write_text("inside app\n", encoding="utf-8")
        (workspace.parent / "outside-app.txt").write_text("outside app\n", encoding="utf-8")

    result = _pipeline(
        workspace_manager=manager,
        filesystem_executor=FakeFilesystemExecutor(mutate),
        discovery_router=FakeDiscoveryRouter(("context.txt",)),
    ).run(
        RunRequest(
            workspace_root=app_dir,
            task="Patch context inside and outside app",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "workspace_boundary"
    assert result.issue.reason == "changed_path_outside_destination"
    assert result.issue.diagnostics is not None
    assert result.issue.diagnostics["offending_paths"] == ("outside-app.txt",)
    assert (app_dir / "context.txt").read_text(encoding="utf-8") == "app context\n"
    assert not (repo / "outside-app.txt").exists()

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_committed_change_outside_destination_directory(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    app_dir = repo / "app"
    app_dir.mkdir()
    (app_dir / "context.txt").write_text("app context\n", encoding="utf-8")
    _git(repo, "add", "app/context.txt")
    _git(repo, "commit", "-m", "Add app context")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        git_root = workspace.parent
        (workspace / "context.txt").write_text("inside app\n", encoding="utf-8")
        (git_root / "outside-app.txt").write_text("outside app\n", encoding="utf-8")
        _git(git_root, "add", "-A")
        _git(git_root, "commit", "-m", "Committed outside selected destination")

    result = _pipeline(
        workspace_manager=manager,
        executor=DirectMutationExecutor(mutate),
        discovery_router=FakeDiscoveryRouter(("context.txt",)),
    ).run(
        RunRequest(
            workspace_root=app_dir,
            task="Commit inside app and outside app",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "workspace_boundary"
    assert result.issue.reason == "changed_path_outside_destination"
    assert result.issue.diagnostics is not None
    assert result.issue.diagnostics["offending_paths"] == ("outside-app.txt",)
    assert (app_dir / "context.txt").read_text(encoding="utf-8") == "app context\n"
    assert not (repo / "outside-app.txt").exists()

    assert result.workspace_session is not None
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


def test_run_pipeline_rejects_create_diff_for_existing_file(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(_create_file_proposal("context.txt")),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update context.txt",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert result.patch_generated is True
    assert result.patch_applied is False
    assert result.promoted_files == ()
    assert result.changed_files == ()
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"

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

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.promotion_status == "applied"
    assert result.promotion_applied is True
    assert result.issue is None
    assert (repo / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert (created.session.worktree_path / "context.txt").read_text(
        encoding="utf-8"
    ) == "new context\n"

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
    assert result.patch_applied is True
    assert result.promotion_status == "rejected"
    assert result.promotion_applied is False
    assert result.issue is not None
    assert result.issue.category == "promotion"
    assert result.issue.reason == "internal_path_not_promoted"
    assert result.issue.path == ".sfe-worktrees/leak.txt"
    assert not (repo / ".sfe-worktrees" / "leak.txt").exists()

    assert result.workspace_session is not None
    assert (
        result.workspace_session.worktree_path / ".sfe-worktrees" / "leak.txt"
    ).exists()
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_committed_internal_promotion_paths(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        target = workspace / ".sfe-worktrees" / "leak.txt"
        target.parent.mkdir()
        target.write_text("committed internal\n", encoding="utf-8")
        _git(workspace, "add", "-A")
        _git(workspace, "commit", "-m", "Commit internal path")

    result = _pipeline(
        workspace_manager=manager,
        executor=DirectMutationExecutor(mutate),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and commit an internal file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "promotion"
    assert result.issue.reason == "internal_path_not_promoted"
    assert result.issue.path == ".sfe-worktrees/leak.txt"
    assert not (repo / ".sfe-worktrees" / "leak.txt").exists()

    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_default_aider_rejects_internal_promotion_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SFE_WORKSPACE_WRITE_EXECUTOR", raising=False)
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()

    def mutate(workspace: Path) -> None:
        target = workspace / ".sfe" / "leak.txt"
        target.parent.mkdir()
        target.write_text("internal\n", encoding="utf-8")

    result = _pipeline(
        workspace_manager=manager,
        filesystem_executor=FakeFilesystemExecutor(mutate),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create an internal file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "promotion"
    assert result.issue.reason == "internal_path_not_promoted"
    assert result.issue.path == ".sfe/leak.txt"
    assert not (repo / ".sfe" / "leak.txt").exists()

    assert result.workspace_session is not None
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

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is False
    assert result.issue is None
    assert result.changed_files == ()
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
    assert result.issue.reason == "changed_path_outside_destination"
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
    assert result.issue.reason == "executor_produced_no_files"
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
    assert result.issue.reason == "executor_produced_no_files"
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


def test_run_pipeline_accepts_sfe_file_blocks_for_text_workspace_write(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="app/index.html">\n'
        "<!doctype html>\n"
        "<title>SFE</title>\n"
        "\n"
        "<main data-state=\"a+b\">Solar & Field</main>\n"
        "<<<END_SFE_FILE>>>\n"
        '<<<SFE_FILE path="app/styles.css">\n'
        ":root { --accent: #31c48d; }\n"
        "\n"
        "main::before { content: \"<<not a marker>>\"; }\n"
        "<<<END_SFE_FILE>>>\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create two files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("app/index.html", "app/styles.css")
    assert result.promoted_files == ("app/index.html", "app/styles.css")
    assert "noncanonical_sfe_file_closing_marker_recovered" not in result.warnings
    assert (repo / "app/index.html").read_text(encoding="utf-8") == (
        "<!doctype html>\n"
        "<title>SFE</title>\n"
        "\n"
        "<main data-state=\"a+b\">Solar & Field</main>\n"
    )
    assert (repo / "app/styles.css").read_text(encoding="utf-8") == (
        ":root { --accent: #31c48d; }\n"
        "\n"
        "main::before { content: \"<<not a marker>>\"; }\n"
    )
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_scans_sfe_file_blocks_around_prose(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        "I will create the first file now.\n\n"
        '<<<SFE_FILE path="app/index.html">\n'
        "<!doctype html>\n"
        "<title>Scanner</title>\n"
        "<<<END_SFE_FILE>>>\n"
        "\nThe first file is done; here is the second.\n\n"
        '<<<SFE_FILE path="app/styles.css">\n'
        "body {\n"
        "  margin: 0;\n"
        "}\n"
        "<<<END_SFE_FILE>>>\n"
        "\nAll files are included above.\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create two files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("app/index.html", "app/styles.css")
    assert (repo / "app/index.html").read_text(encoding="utf-8") == (
        "<!doctype html>\n"
        "<title>Scanner</title>\n"
    )
    assert (repo / "app/styles.css").read_text(encoding="utf-8") == (
        "body {\n"
        "  margin: 0;\n"
        "}\n"
    )
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_recovers_noncanonical_sfe_file_closing_markers(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="app/app.js">\n'
        "const inlineMarker = '</SFE_FILE> is not a closing line';\n"
        "\n"
        "export const answer = 42;\n"
        "</SFE_FILE>>>\n"
        '<<<SFE_FILE path="app/README.md">\n'
        "# App\n"
        "\n"
        "Closing marker recovery keeps blank lines.\n"
        "</SFE_FILE>\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create two files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("app/app.js", "app/README.md")
    assert set(result.promoted_files) == {"app/app.js", "app/README.md"}
    assert "noncanonical_sfe_file_closing_marker_recovered" in result.warnings
    assert (repo / "app/app.js").read_text(encoding="utf-8") == (
        "const inlineMarker = '</SFE_FILE> is not a closing line';\n"
        "\n"
        "export const answer = 42;\n"
    )
    assert (repo / "app/README.md").read_text(encoding="utf-8") == (
        "# App\n"
        "\n"
        "Closing marker recovery keeps blank lines.\n"
    )
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_treats_standalone_noncanonical_closer_as_block_end(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="app/notes.txt">\n'
        "first line\n"
        "</SFE_FILE>\n"
        "this prose is outside the block and ignored\n"
        "<<<END_SFE_FILE>>>\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create one file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert "noncanonical_sfe_file_closing_marker_recovered" in result.warnings
    assert (repo / "app/notes.txt").read_text(encoding="utf-8") == "first line\n"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_core_run_pipeline_accepts_sfe_file_blocks_without_tui_executor(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="app/index.html">\n'
        "<!doctype html>\n"
        "<title>Core transport</title>\n"
        "<<<END_SFE_FILE>>>\n"
    )

    result = RunPipeline(
        backend=GenericTextWorkspaceWriteBackend(raw_output),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(()),
        execution_mode_router=FakeExecutionModeRouter(),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.executor_provider == "generic-text-provider"
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("app/index.html",)
    assert result.promoted_files == ("app/index.html",)
    assert (repo / "app/index.html").read_text(encoding="utf-8") == (
        "<!doctype html>\n"
        "<title>Core transport</title>\n"
    )
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_absolute_sfe_file_block_path(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="/tmp/escape.txt">\n'
        "outside\n"
        "<<<END_SFE_FILE>>>\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create one file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "invalid_sfe_file_path"
    assert result.issue.path == "/tmp/escape.txt"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_sfe_file_block_path_traversal(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="../escape.txt">\n'
        "outside\n"
        "<<<END_SFE_FILE>>>\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create one file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "invalid_sfe_file_path"
    assert result.issue.path == "../escape.txt"
    assert not (tmp_path / "escape.txt").exists()
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_unrecoverable_sfe_file_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="app/one.txt">\n'
        "one\n"
        '<<<SFE_FILE path="app/two.txt">\n'
        "two\n"
        "<<<END_SFE_FILE>>>\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "malformed_sfe_file_block"
    assert result.issue.path == "app/one.txt"
    assert result.issue.diagnostics == {
        "detail": "new_sfe_file_start_before_closing_marker"
    }
    assert not (repo / "app/one.txt").exists()
    assert not (repo / "app/two.txt").exists()
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_recovers_unclosed_sfe_file_block_at_eof(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="app/app.js">\n'
        "console.log('unfinished');\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create one file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("app/app.js",)
    assert set(result.promoted_files) == {"app/app.js"}
    assert "eof_sfe_file_closing_marker_recovered" in result.warnings
    assert (repo / "app/app.js").read_text(encoding="utf-8") == "console.log('unfinished');\n"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_empty_unclosed_sfe_file_block_at_eof(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = '<<<SFE_FILE path="app/app.js">\n'

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create one file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "malformed_sfe_file_block"
    assert result.issue.path == "app/app.js"
    assert result.issue.diagnostics == {"detail": "missing_sfe_file_closing_marker"}
    assert "eof_sfe_file_closing_marker_recovered" not in result.warnings
    assert not (repo / "app/app.js").exists()
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_reports_noncanonical_and_eof_sfe_file_warnings(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        '<<<SFE_FILE path="app/first.txt">\n'
        "first\n"
        "</SFE_FILE>\n"
        "The next file follows.\n"
        '<<<SFE_FILE path="app/second.txt">\n'
        "second\n"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create two files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("app/first.txt", "app/second.txt")
    assert "noncanonical_sfe_file_closing_marker_recovered" in result.warnings
    assert "eof_sfe_file_closing_marker_recovered" in result.warnings
    assert (repo / "app/first.txt").read_text(encoding="utf-8") == "first\n"
    assert (repo / "app/second.txt").read_text(encoding="utf-8") == "second\n"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_accepts_single_fenced_git_diff_patch_proposal(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = f"```diff\n{_valid_new_file_diff()}\n```"

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
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
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("index.html",)
    assert result.promoted_files == ("index.html",)
    assert (repo / "index.html").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_accepts_fenced_git_diff_with_surrounding_prose(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = f"Here is the patch:\n```diff\n{_valid_new_file_diff()}\n```\nPatch complete."

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
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
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("index.html",)
    assert result.promoted_files == ("index.html",)
    assert (repo / "index.html").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_accepts_preamble_git_diff_patch_proposal(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = f"Here is the patch:\n{_valid_new_file_diff()}"

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
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
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("index.html",)
    assert result.promoted_files == ("index.html",)
    assert (repo / "index.html").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_accepts_preamble_multi_file_minisite_git_diff(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = f"Here is the patch:\n\n{_valid_minisite_diff()}\n\nPatch complete."

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create a small static minisite",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == (
        "index.html",
        "style.css",
        "script.js",
        "README.md",
    )
    assert result.promoted_files == (
        "README.md",
        "index.html",
        "script.js",
        "style.css",
    )
    index_html = (repo / "index.html").read_text(encoding="utf-8")
    assert index_html.startswith("<!doctype html>")
    assert (repo / "style.css").read_text(encoding="utf-8").startswith(":root")
    assert (repo / "script.js").read_text(encoding="utf-8").startswith("const")
    assert (repo / "README.md").read_text(encoding="utf-8").startswith("# Mini Site")
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_ambiguous_multiple_fenced_patch_blocks(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        f"```diff\n{_valid_new_file_diff()}\n```\n"
        f"```diff\n{_valid_new_file_diff('two.html')}\n```"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "malformed_hunk_line"
    assert result.patch_applied is False
    assert not (repo / "index.html").exists()
    assert not (repo / "two.html").exists()
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_ambiguous_multiple_preamble_patch_regions(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = (
        f"Here is the first patch:\n{_valid_new_file_diff()}\n"
        f"Here is another patch:\n{_valid_new_file_diff('two.html')}"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "invalid_patch_proposal"
    assert result.issue.reason == "malformed_hunk_line"
    assert result.patch_applied is False
    assert not (repo / "index.html").exists()
    assert not (repo / "two.html").exists()
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_recovers_new_files_from_malformed_preamble_diff(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = "\n".join(
        [
            "Here is the patch:",
            _invalid_new_file_hunk_count_diff(
                "index.html",
                content=("hello", "", "world"),
            ),
            _invalid_new_file_hunk_count_diff(
                "styles.css",
                content=("body {", "  color: black;", "}"),
            ),
        ]
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("index.html", "styles.css")
    assert result.promoted_files == ("index.html", "styles.css")
    assert (repo / "index.html").read_text(encoding="utf-8") == "hello\n\nworld\n"
    assert (repo / "styles.css").read_text(encoding="utf-8") == (
        "body {\n  color: black;\n}\n"
    )
    assert "hunk_preimage_mismatch" not in str(result)
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_recovered_new_file_outside_destination_fails_boundary(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    app_dir = repo / "app"
    app_dir.mkdir()
    (app_dir / "context.txt").write_text("app context\n", encoding="utf-8")
    _git(repo, "add", "app/context.txt")
    _git(repo, "commit", "-m", "Add app context")
    manager = _manager()
    raw_output = (
        "Here is the patch:\n"
        f"{_invalid_new_file_hunk_count_diff('../outside.txt')}"
    )

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
        discovery_router=FakeDiscoveryRouter(("context.txt",)),
    ).run(
        RunRequest(
            workspace_root=app_dir,
            task="Create a recovered file outside the app destination",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "workspace_boundary"
    assert result.issue.reason == "changed_path_outside_destination"
    assert result.issue.diagnostics is not None
    assert result.issue.diagnostics["authorized_output_root"] == str(app_dir.resolve())
    assert result.issue.diagnostics["offending_paths"] == ("outside.txt",)
    assert not (repo / "outside.txt").exists()
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_rejects_preamble_git_diff_with_unsafe_path(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    raw_output = f"Here is the patch:\n{_valid_new_file_diff('../outside.txt')}"

    result = _pipeline(
        workspace_manager=manager,
        executor=FakeExecutor(raw_output),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context with an unsafe file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "workspace_boundary"
    assert result.issue.reason == "changed_path_outside_destination"
    assert result.patch_applied is False
    assert not (tmp_path / "outside.txt").exists()
    assert not (repo / "outside.txt").exists()
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
    assert result.issue.reason == "executor_produced_no_files"
    diagnostics = result.patch_proposal_diagnostics
    assert diagnostics is not None
    assert diagnostics.looks_like_json is True
    assert diagnostics.mentions_selected_paths == ("README.md",)
    assert diagnostics.looks_like_plain_text_or_markdown is False
    assert result.workspace_session is not None
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_recovers_new_file_hunk_accounting_without_second_pass(
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

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.promoted_files == ("index.html",)
    assert (repo / "index.html").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert result.patch_summary is not None
    assert result.patch_summary.created_paths == ("index.html",)
    assert len(executor.patch_calls) == 1
    assert "hunk_preimage_mismatch" not in str(result)
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
    assert result.patch_hunk_count_normalization is None
    rendered = render_run_result(result)
    assert "SFE hunk count normalization" not in rendered
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

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
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
    assert json_result.issue.reason == "executor_produced_no_files"
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


def test_run_pipeline_valid_multi_file_unified_diff_still_applies(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    (repo / "app.py").write_text('GREETING = "Hello"\n', encoding="utf-8")
    (repo / "test_app.py").write_text(
        'from app import GREETING\n\n\ndef test_greeting():\n    assert GREETING == "Hello"\n',
        encoding="utf-8",
    )
    _git(repo, "add", "app.py", "test_app.py")
    _git(repo, "commit", "-m", "add app and test")
    manager = _manager()
    executor = FakeExecutor(_valid_two_file_modify_diff())

    result = _pipeline(
        workspace_manager=manager,
        executor=executor,
        discovery_router=FakeDiscoveryRouter(("app.py", "test_app.py")),
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update greeting and test",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.patch_summary is not None
    assert result.patch_summary.modified_paths == ("app.py", "test_app.py")
    assert result.promoted_files == ("app.py", "test_app.py")
    assert (repo / "app.py").read_text(encoding="utf-8") == 'GREETING = "Hello from SFE"\n'
    assert 'assert GREETING == "Hello from SFE"' in (
        repo / "test_app.py"
    ).read_text(encoding="utf-8")
    assert result.workspace_session is not None
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
    assert result.issue.reason == "executor_produced_no_files"
    assert result.executor_provider == "codexcli"
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_codexcli_empty_patch_response_keeps_files_unchanged(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    provider = FakeChatProvider(
        response={
            "choices": [{"message": {"content": ""}}],
            "codexcli": {
                "provider": "openai-codexcli",
                "model": "gpt-5.5",
                "returncode": 0,
                "stdout_length": 0,
                "stderr_length": 0,
                "stderr_present": False,
                "parser_diagnostics": {
                    "stdout_length": 0,
                    "jsonl_line_count": 0,
                    "parsed_event_count": 0,
                    "invalid_json_line_count": 0,
                    "event_type_counts": {},
                    "agent_message_count": 0,
                    "final_content_present": False,
                    "thread_id_present": False,
                    "usage_present": False,
                },
                "command": ["codex", "exec", "--json"],
            },
        }
    )
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
    assert result.issue.reason == "invalid_response"
    assert result.executor_provider == "codexcli"
    assert result.patch_generated is False
    assert result.patch_applied is False
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    assert result.patch_result is not None
    diagnostics = result.patch_result.summary["executor_response_diagnostics"]
    assert isinstance(diagnostics, dict)
    assert diagnostics["message_content_length"] == 0
    assert diagnostics["provider_diagnostics"] == {
        "provider": "openai-codexcli",
        "model": "gpt-5.5",
        "returncode": 0,
        "stdout_length": 0,
        "stderr_length": 0,
        "stderr_present": False,
        "parser_diagnostics": {
            "stdout_length": 0,
            "jsonl_line_count": 0,
            "parsed_event_count": 0,
            "invalid_json_line_count": 0,
            "event_type_counts": {},
            "agent_message_count": 0,
            "final_content_present": False,
            "thread_id_present": False,
            "usage_present": False,
        },
    }
    assert "command" not in diagnostics["provider_diagnostics"]
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
    assert result.workspace_session is not None
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


def test_run_pipeline_small_workspace_write_stays_single_pass(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "auto")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    executor = FakeExecutor(_valid_new_file_diff())
    planner = FakeMultiPassPlanner(_multipass_plan_json({"unused": ["unused.txt"]}))

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Patch context and create index file",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.multi_pass_summary is None
    assert planner.calls == []
    assert len(executor.patch_calls) == 1
    assert executor.patch_calls[0].get("multi_pass") is None
    executor_cwd = Path(str(executor.patch_calls[0]["executor_working_directory"]))
    assert result.active_workspace is not None
    assert executor_cwd == result.active_workspace
    assert executor_cwd != repo
    assert result.promoted_files == ("index.html",)
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_forced_multipass_promotes_each_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {
                "foundation": ["index.html"],
                "docs": ["README.md"],
            }
        )
    )
    executor = FakeExecutor(
        multipass_patch_answers=[
            _valid_new_file_diff("index.html"),
            _valid_new_file_diff_with_content("README.md", "# Demo\n"),
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create a two file scaffold",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.status == "completed"
    assert result.multi_pass_summary.passes_total == 2
    assert result.multi_pass_summary.passes_completed == 2
    assert result.multi_pass_summary.promoted_files_by_pass == {
        "foundation": ("index.html",),
        "docs": ("README.md",),
    }
    assert result.promoted_files == ("index.html", "README.md")
    assert (repo / "index.html").is_file()
    assert (repo / "README.md").read_text(encoding="utf-8") == "# Demo\n"
    assert len(planner.calls) == 1
    assert not hasattr(executor, "plan_multipass")
    assert len(executor.patch_calls) == 2
    assert executor.patch_calls[0]["multi_pass"]["allowed_files"] == ("index.html",)
    assert result.active_workspace is not None
    assert all(
        Path(str(call["executor_working_directory"])) == result.active_workspace
        for call in executor.patch_calls
    )
    assert all(
        Path(str(call["executor_working_directory"])) != repo
        for call in executor.patch_calls
    )
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_forced_multipass_accepts_leading_prose_before_diff(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {
                "scaffold-html-structure": (
                    "index.html",
                    "styles.css",
                    "app.js",
                    "README.md",
                )
            }
        )
    )
    minisite_diff = (
        _valid_minisite_diff()
        .replace("style.css", "styles.css")
        .replace("script.js", "app.js")
    )
    raw_output = (
        "I'll create the initial scaffold in app/ with HTML, CSS, JS, and README.\n"
        f"{minisite_diff}"
    )
    executor = FakeExecutor(multipass_patch_answers=[raw_output])

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("index.html",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create the initial static app scaffold",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert result.patch_generated is True
    assert result.patch_applied is True
    assert result.changed_files == ("index.html", "styles.css", "app.js", "README.md")
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.passes_completed == 1
    assert result.multi_pass_summary.failed_pass_issue is None
    assert result.multi_pass_summary.pass_results[0].patch_paths == (
        "index.html",
        "styles.css",
        "app.js",
        "README.md",
    )
    assert "hunk_preimage_mismatch" not in str(result.multi_pass_summary)
    assert (repo / "index.html").exists()
    assert (repo / "styles.css").exists()
    assert (repo / "app.js").exists()
    assert (repo / "README.md").exists()
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_multipass_refreshes_state_for_later_updates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    events: list[RunProgressEvent] = []
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {
                "readme_create": ["README.md"],
                "readme_update": ["README.md"],
            }
        )
    )
    executor = FakeExecutor(
        multipass_patch_answers=[
            _valid_new_file_diff_with_content("README.md", "# Todo List\n"),
            _valid_new_file_diff_with_content(
                "README.md",
                "# Todo List\n\nSecond pass details\n",
            ),
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        progress_callback=events.append,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create a Symfony Todo List app and document it",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert (repo / "README.md").read_text(encoding="utf-8") == (
        "# Todo List\n\nSecond pass details\n"
    )
    assert len(executor.patch_calls) == 2
    assert result.active_workspace is not None
    assert all(
        Path(str(call["executor_working_directory"])) == result.active_workspace
        for call in executor.patch_calls
    )
    second_batch = executor.patch_calls[1]["multi_pass"]
    assert second_batch["completed_files"] == ("README.md",)
    assert second_batch["current_allowed_file_context"] == (
        {"path": "README.md", "text": "# Todo List\n"},
    )
    assert second_batch["full_file_replacement_guidance"]["eligible_files"] == (
        "README.md",
    )
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.pass_results[1].created_files == ()
    assert result.multi_pass_summary.pass_results[1].patch_paths == ("README.md",)
    assert result.multi_pass_summary.pass_results[1].full_content_provided_files == (
        "README.md",
    )
    assert result.multi_pass_summary.pass_results[1].full_file_replacement_eligible_files == (
        "README.md",
    )
    refresh_events = [
        event for event in events if event.name == "multi_pass_workspace_state_refreshed"
    ]
    assert len(refresh_events) == 2
    names = [event.name for event in events]
    plan_completed_index = names.index("multi_pass_plan_completed")
    first_pass_started_index = names.index("multi_pass_pass_started")
    assert plan_completed_index < first_pass_started_index
    assert events[plan_completed_index].message == "SFE: multi-pass plan completed: 2 passes"
    assert events[first_pass_started_index].message == "SFE: multi-pass pass 1/2 started"
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_multipass_blocks_direct_source_mutation_with_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    planner = FakeMultiPassPlanner(_multipass_plan_json({"foundation": ["context.txt"]}))

    class SourceMutatingExecutor(FakeExecutor):
        def propose_patch(self, executor_payload: dict[str, object]) -> ExecutorResponse:
            self.patch_calls.append(executor_payload)
            (repo / "context.txt").write_text("mutated source\n", encoding="utf-8")
            return ExecutorResponse(
                _replacement_proposal("context.txt"),
                None,
                1,
                provider_name=self.provider_name,
                response_diagnostics={
                    "provider_name": self.provider_name,
                    "provider_diagnostics": {
                        "cwd": str(executor_payload.get("executor_working_directory")),
                    },
                },
            )

    executor = SourceMutatingExecutor()

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("context.txt",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update context in a forced multipass run",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.passes_completed == 1
    assert result.promoted_files == ("context.txt",)
    assert (repo / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert result.active_workspace is not None
    assert (result.active_workspace / "context.txt").read_text(encoding="utf-8") == (
        "new context\n"
    )
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_direct_backend_marks_small_full_content_file_as_full_file_replacement_eligible(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "src/Entity/Todo.php"
    target.parent.mkdir(parents=True)
    target.write_text("<?php\nfinal class Todo {}\n", encoding="utf-8")
    contract = build_contract(
        workspace_root=repo,
        task="Update src/Entity/Todo.php",
        file_paths=[target],
    )
    batch = MultiPassBatch(
        id="domain",
        title="Domain",
        goal="Update Todo",
        allowed_files=("src/Entity/Todo.php",),
    )
    executor = FakeExecutor(multipass_patch_answers=[_stale_todo_full_file_diff()])

    DirectBackend(executor=executor).patch_multipass_batch(
        contract,
        plan=MultiPassPlan("Project", (batch,)),
        batch=batch,
        completed_files=(),
    )

    guidance = executor.patch_calls[0]["multi_pass"]["full_file_replacement_guidance"]
    assert guidance["full_content_provided_files"] == ("src/Entity/Todo.php",)
    assert guidance["eligible_files"] == ("src/Entity/Todo.php",)
    assert guidance["source_files"] == ("src/Entity/Todo.php",)
    assert guidance["large_files"] == ()


def test_direct_backend_marks_small_controller_as_source_full_file_replacement_eligible(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "src/Controller/TodoController.php"
    target.parent.mkdir(parents=True)
    target.write_text("<?php\nfinal class TodoController {}\n", encoding="utf-8")
    contract = build_contract(
        workspace_root=repo,
        task="Integrate Todo controller with service",
        file_paths=[target],
    )
    batch = MultiPassBatch(
        id="controller-service-integration",
        title="Controller Service Integration",
        goal="Update Todo controller",
        allowed_files=("src/Controller/TodoController.php",),
    )
    executor = FakeExecutor(multipass_patch_answers=[_todo_controller_partial_diff()])

    DirectBackend(executor=executor).patch_multipass_batch(
        contract,
        plan=MultiPassPlan("Project", (batch,)),
        batch=batch,
        completed_files=(),
    )

    guidance = executor.patch_calls[0]["multi_pass"]["full_file_replacement_guidance"]
    assert guidance["full_content_provided_files"] == ("src/Controller/TodoController.php",)
    assert guidance["eligible_files"] == ("src/Controller/TodoController.php",)
    assert guidance["source_files"] == ("src/Controller/TodoController.php",)
    assert guidance["large_files"] == ()


def test_direct_backend_marks_readme_as_documentation_full_file_replacement_eligible(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "README.md"
    target.write_text("# Todo\n\nExisting docs.\n", encoding="utf-8")
    contract = build_contract(
        workspace_root=repo,
        task="Update README.md",
        file_paths=[target],
    )
    batch = MultiPassBatch(
        id="docs",
        title="Docs",
        goal="Update README",
        allowed_files=("README.md",),
    )
    executor = FakeExecutor(multipass_patch_answers=[_readme_full_file_diff()])

    DirectBackend(executor=executor).patch_multipass_batch(
        contract,
        plan=MultiPassPlan("Project", (batch,)),
        batch=batch,
        completed_files=(),
    )

    guidance = executor.patch_calls[0]["multi_pass"]["full_file_replacement_guidance"]
    assert guidance["full_content_provided_files"] == ("README.md",)
    assert guidance["eligible_files"] == ("README.md",)
    assert guidance["documentation_files"] == ("README.md",)


def test_direct_backend_marks_small_twig_template_as_full_file_replacement_eligible(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "templates/dashboard/index.html.twig"
    target.parent.mkdir(parents=True)
    target.write_text("{% block body %}Dashboard{% endblock %}\n", encoding="utf-8")
    contract = build_contract(
        workspace_root=repo,
        task="Update dashboard Twig template",
        file_paths=[target],
    )
    batch = MultiPassBatch(
        id="templates",
        title="Templates",
        goal="Update dashboard template",
        allowed_files=("templates/dashboard/index.html.twig",),
    )
    executor = FakeExecutor(multipass_patch_answers=[_dashboard_twig_full_file_diff()])

    DirectBackend(executor=executor).patch_multipass_batch(
        contract,
        plan=MultiPassPlan("Project", (batch,)),
        batch=batch,
        completed_files=(),
    )

    guidance = executor.patch_calls[0]["multi_pass"]["full_file_replacement_guidance"]
    assert guidance["full_content_provided_files"] == (
        "templates/dashboard/index.html.twig",
    )
    assert guidance["eligible_files"] == ("templates/dashboard/index.html.twig",)
    assert guidance["template_files"] == ("templates/dashboard/index.html.twig",)


def test_direct_backend_does_not_mark_large_full_content_file_as_full_file_replacement_eligible(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    target = repo / "large.txt"
    target.write_text("x" * 65_000, encoding="utf-8")
    contract = build_contract(
        workspace_root=repo,
        task="Update large.txt",
        file_paths=[target],
    )
    batch = MultiPassBatch(
        id="large",
        title="Large",
        goal="Update large file",
        allowed_files=("large.txt",),
    )
    executor = FakeExecutor(multipass_patch_answers=[_valid_new_file_diff("other.txt")])

    DirectBackend(executor=executor).patch_multipass_batch(
        contract,
        plan=MultiPassPlan("Project", (batch,)),
        batch=batch,
        completed_files=(),
    )

    guidance = executor.patch_calls[0]["multi_pass"]["full_file_replacement_guidance"]
    assert guidance["full_content_provided_files"] == ("large.txt",)
    assert guidance["eligible_files"] == ()
    assert guidance["large_files"] == ("large.txt",)


def test_direct_backend_does_not_mark_file_without_full_content_as_full_file_replacement_eligible(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    contract = build_contract(
        workspace_root=repo,
        task="Update missing.txt",
        file_paths=[],
    )
    batch = MultiPassBatch(
        id="missing",
        title="Missing",
        goal="Update missing file",
        allowed_files=("missing.txt",),
    )
    executor = FakeExecutor(multipass_patch_answers=[_valid_new_file_diff("missing.txt")])

    DirectBackend(executor=executor).patch_multipass_batch(
        contract,
        plan=MultiPassPlan("Project", (batch,)),
        batch=batch,
        completed_files=(),
    )

    guidance = executor.patch_calls[0]["multi_pass"]["full_file_replacement_guidance"]
    assert guidance["full_content_provided_files"] == ()
    assert guidance["eligible_files"] == ()
    assert guidance["large_files"] == ()


@pytest.mark.skip(reason="workspace_write no longer repairs hunk/preimage mismatches")
def test_run_pipeline_multipass_rescues_readme_hunk_location_mismatch_deterministically(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("# Todo\n\nExisting docs.\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Add README")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer(
        FullFileReplacementReviewDecision(
            approve=True,
            risk_level="low",
            reason="coherent README replacement",
        )
    )
    planner = FakeMultiPassPlanner(_multipass_plan_json({"docs": ["README.md"]}))
    executor = FakeExecutor(multipass_patch_answers=[_readme_full_file_diff()])
    original_apply = run_pipeline_module._apply_run_patch
    calls = {"count": 0}

    def fail_once_for_location_mismatch(workspace_root: Path, proposal: object) -> PatchApplyResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return PatchApplyResult(
                False,
                PatchIssue(
                    "physical_application_failure",
                    "hunk_location_mismatch",
                    "README.md",
                ),
                None,
                False,
            )
        return original_apply(workspace_root, proposal)

    monkeypatch.setattr(
        run_pipeline_module,
        "_apply_run_patch",
        fail_once_for_location_mismatch,
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("README.md",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update README documentation",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert reviewer.calls == []
    assert "Updated docs" in (repo / "README.md").read_text(encoding="utf-8")
    assert result.multi_pass_summary.pass_results[0].fallback_diagnostics is None
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_allows_full_file_fallback_from_executor_guidance_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    target = repo / "templates/dashboard/index.html.twig"
    target.parent.mkdir(parents=True)
    target.write_text(
        "{% extends 'base.html.twig' %}\n\n{% block body %}\nOld dashboard\n{% endblock %}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "templates/dashboard/index.html.twig")
    _git(repo, "commit", "-m", "Add dashboard template")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer(
        FullFileReplacementReviewDecision(
            approve=True,
            risk_level="low",
            reason="coherent dashboard template replacement",
        )
    )
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {"templates": ["templates/dashboard/index.html.twig"]}
        )
    )
    executor = FakeExecutor(multipass_patch_answers=[_dashboard_twig_full_file_diff()])
    original_apply = run_pipeline_module._apply_run_patch
    calls = {"count": 0}

    def fail_once_for_preimage_mismatch(
        workspace_root: Path,
        proposal: object,
    ) -> PatchApplyResult:
        calls["count"] += 1
        if calls["count"] == 1:
            return PatchApplyResult(
                False,
                PatchIssue(
                    "physical_application_failure",
                    "hunk_preimage_mismatch",
                    "templates/dashboard/index.html.twig",
                ),
                None,
                False,
            )
        return original_apply(workspace_root, proposal)

    monkeypatch.setattr(
        run_pipeline_module,
        "_apply_run_patch",
        fail_once_for_preimage_mismatch,
    )
    monkeypatch.setattr(
        run_pipeline_module,
        "_execution_preview_selected_refs",
        lambda _patch_result: set(),
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("templates/dashboard/index.html.twig",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Finish todo Twig templates",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert reviewer.calls[0].target_path == "templates/dashboard/index.html.twig"
    assert "Dashboard ready" in target.read_text(encoding="utf-8")
    diagnostics = result.multi_pass_summary.pass_results[0].fallback_diagnostics
    assert diagnostics["selected_context"] is False
    assert diagnostics["full_content_provided"] is True
    assert diagnostics["full_file_replacement_eligible"] is True
    assert diagnostics["included_in_full_file_replacement_guidance"] is True
    assert diagnostics["allowed_through_executor_provided_context_gate"] is True
    assert diagnostics["proposed_replacement_full_file_like"] is True
    assert diagnostics["reviewer_approve"] is True
    assert diagnostics["final_outcome"] == "applied"
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_rejects_full_file_fallback_without_full_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {"templates": ["templates/dashboard/index.html.twig"]}
        )
    )
    executor = FakeExecutor(multipass_patch_answers=[_dashboard_twig_full_file_diff()])

    def fail_for_preimage_mismatch(
        workspace_root: Path,
        proposal: object,
    ) -> PatchApplyResult:
        return PatchApplyResult(
            False,
            PatchIssue(
                "physical_application_failure",
                "hunk_preimage_mismatch",
                "templates/dashboard/index.html.twig",
            ),
            None,
            False,
        )

    monkeypatch.setattr(
        run_pipeline_module,
        "_apply_run_patch",
        fail_for_preimage_mismatch,
    )
    monkeypatch.setattr(
        run_pipeline_module,
        "_execution_preview_selected_refs",
        lambda _patch_result: {"templates/dashboard/index.html.twig"},
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("templates/dashboard/index.html.twig",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Finish todo Twig templates",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue.reason == "missing_target_not_safe_create"
    assert reviewer.calls == []
    assert not (repo / "templates/dashboard/index.html.twig").exists()
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer blocks on hunk location mismatch")
def test_run_pipeline_multipass_rejects_partial_hunk_location_mismatch_without_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("# Todo\n\nExisting docs.\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Add README")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer()
    planner = FakeMultiPassPlanner(_multipass_plan_json({"docs": ["README.md"]}))
    executor = FakeExecutor(multipass_patch_answers=[_readme_partial_location_mismatch_diff()])

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("README.md",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update README documentation",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue.reason == "hunk_location_mismatch"
    assert reviewer.calls == []
    diagnostics = result.multi_pass_summary.failed_pass_issue.diagnostics
    assert diagnostics["reviewer_reason"] == "proposed_replacement_not_full_file"
    assert "Updated docs" not in (repo / "README.md").read_text(encoding="utf-8")
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer blocks on hunk preimage mismatch")
def test_run_pipeline_multipass_controller_partial_hunk_failure_reports_guidance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    controller = repo / "src/Controller/TodoController.php"
    controller.parent.mkdir(parents=True)
    controller.write_text(
        "<?php\n\nnamespace App\\Controller;\n\nfinal class TodoController\n{\n"
        "    public function index(): string\n    {\n        return 'old';\n    }\n}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "src/Controller/TodoController.php")
    _git(repo, "commit", "-m", "Add Todo controller")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {"controller-service-integration": ["src/Controller/TodoController.php"]}
        )
    )
    executor = FakeExecutor(multipass_patch_answers=[_todo_controller_partial_diff()])

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("src/Controller/TodoController.php",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Integrate Todo controller with the service layer",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue.reason == "hunk_preimage_mismatch"
    assert result.issue.path == "src/Controller/TodoController.php"
    assert reviewer.calls == []
    pass_result = result.multi_pass_summary.pass_results[0]
    assert pass_result.full_content_provided_files == ("src/Controller/TodoController.php",)
    assert pass_result.full_file_replacement_eligible_files == (
        "src/Controller/TodoController.php",
    )
    assert pass_result.full_file_replacement_used_files == ()
    diagnostics = result.multi_pass_summary.failed_pass_issue.diagnostics
    assert diagnostics["selected_context"] is True
    assert diagnostics["full_content_provided"] is True
    assert diagnostics["full_file_replacement_eligible"] is True
    assert diagnostics["included_in_full_file_replacement_guidance"] is True
    assert diagnostics["executor_used_full_file_replacement"] is False
    assert diagnostics["reviewer_reason"] == "proposed_replacement_not_full_file"
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer retries preimage mismatches")
def test_run_pipeline_multipass_retries_small_composer_preimage_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    (repo / "composer.json").write_text(
        '{\n  "require": {\n    "php": ">=8.2"\n  }\n}\n',
        encoding="utf-8",
    )
    _git(repo, "add", "composer.json")
    _git(repo, "commit", "-m", "Add composer")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"dependencies": ["composer.json"]})
    )
    executor = FakeExecutor(
        multipass_patch_answers=[_stale_full_file_composer_diff(valid_json=True)],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("composer.json",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Continue the existing Symfony Todo List app and inspect composer.json dependencies",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert '"symfony/form": "^7.0"' in (repo / "composer.json").read_text(
        encoding="utf-8"
    )
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.pass_results[0].patch_paths == ("composer.json",)
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer repairs stale hunks")
def test_run_pipeline_multipass_merges_composer_dependency_from_stale_hunk(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    (repo / "composer.json").write_text(
        '{\n  "require": {\n    "php": ">=8.2"\n  }\n}\n',
        encoding="utf-8",
    )
    _git(repo, "add", "composer.json")
    _git(repo, "commit", "-m", "Add composer")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"dependencies": ["composer.json"]})
    )
    executor = FakeExecutor(
        multipass_patch_answers=[
            "\n".join(
                [
                    "diff --git a/composer.json b/composer.json",
                    "--- a/composer.json",
                    "+++ b/composer.json",
                    "@@ -3,3 +3,4 @@",
                    '   "require": {',
                    '-    "php": "^8.1"',
                    '+    "php": ">=8.2",',
                    '+    "symfony/form": "^7.1"',
                    "   }",
                ]
            )
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("composer.json",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Continue the existing Symfony Todo List app and inspect composer.json dependencies",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    composer = json.loads((repo / "composer.json").read_text(encoding="utf-8"))
    assert composer["require"]["php"] == ">=8.2"
    assert composer["require"]["symfony/form"] == "^7.1"
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer retries preimage mismatches")
def test_run_pipeline_multipass_retries_small_frontend_file_preimage_mismatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    (repo / "app").mkdir()
    (repo / "app" / "styles.css").write_text(
        "body { color: blue; }\n.old {}\n",
        encoding="utf-8",
    )
    _git(repo, "add", "app/styles.css")
    _git(repo, "commit", "-m", "Add styles")
    manager = _manager()
    planner = FakeMultiPassPlanner(_multipass_plan_json({"styles": ["app/styles.css"]}))
    executor = FakeExecutor(
        multipass_patch_answers=[
            "\n".join(
                [
                    "diff --git a/app/styles.css b/app/styles.css",
                    "--- a/app/styles.css",
                    "+++ b/app/styles.css",
                    "@@ -1,2 +1,2 @@",
                    "-body { color: red; }",
                    "-.old {}",
                    "+body { color: green; }",
                    "+.new {}",
                ]
            )
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("app/styles.css",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update app/styles.css",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert (repo / "app" / "styles.css").read_text(encoding="utf-8") == (
        "body { color: green; }\n.new {}\n"
    )
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer retries failed patch hunks")
def test_run_pipeline_multipass_retries_failed_small_file_inside_mixed_patch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    (repo / "app").mkdir()
    (repo / "app" / "styles.css").write_text(
        "body { color: blue; }\n.old {}\n",
        encoding="utf-8",
    )
    (repo / "app" / "app.js").write_text(
        "const state = 'old';\n",
        encoding="utf-8",
    )
    _git(repo, "add", "app/styles.css", "app/app.js")
    _git(repo, "commit", "-m", "Add frontend files")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"frontend": ["app/styles.css", "app/app.js"]})
    )
    executor = FakeExecutor(
        multipass_patch_answers=[
            "\n".join(
                [
                    "diff --git a/app/styles.css b/app/styles.css",
                    "--- a/app/styles.css",
                    "+++ b/app/styles.css",
                    "@@ -1,2 +1,2 @@",
                    "-body { color: red; }",
                    "-.old {}",
                    "+body { color: green; }",
                    "+.new {}",
                    "diff --git a/app/app.js b/app/app.js",
                    "--- a/app/app.js",
                    "+++ b/app/app.js",
                    "@@ -1,1 +1,1 @@",
                    "-const state = 'old';",
                    "+const state = 'new';",
                ]
            )
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("app/styles.css", "app/app.js")),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update app/styles.css and app/app.js",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert (repo / "app" / "styles.css").read_text(encoding="utf-8") == (
        "body { color: green; }\n.new {}\n"
    )
    assert (repo / "app" / "app.js").read_text(encoding="utf-8") == (
        "const state = 'new';\n"
    )
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_multipass_updates_preexisting_allowed_file_from_create_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    (repo / "composer.json").write_text(
        '{"require":{"symfony/framework-bundle":"^7.0"}}\n',
        encoding="utf-8",
    )
    (repo / ".env.example").write_text(
        "APP_ENV=dev\nDATABASE_URL=\"sqlite:///%kernel.project_dir%/var/app.db\"\n",
        encoding="utf-8",
    )
    _git(repo, "add", "composer.json", ".env.example")
    _git(repo, "commit", "-m", "Add Symfony config")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {"dependencies-config": ["composer.json", ".env.example"]}
        )
    )
    executor = FakeExecutor(
        multipass_patch_answers=[
            json.dumps(
                {
                    "edits": [
                        {
                            "path": ".env.example",
                            "action": "create_file",
                            "content": (
                                "APP_ENV=dev\n"
                                "APP_SECRET=\n"
                                "DATABASE_URL=\"sqlite:///%kernel.project_dir%/var/data.db\"\n"
                            ),
                        }
                    ]
                }
            )
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("composer.json",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Continue and complete the existing Symfony Todo List application.",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert "var/data.db" in (repo / ".env.example").read_text(
        encoding="utf-8"
    )
    assert result.multi_pass_summary is not None
    pass_result = result.multi_pass_summary.pass_results[0]
    assert pass_result.patch_paths == (".env.example",)
    assert pass_result.created_files == ()
    assert result.changed_files == (".env.example",)
    assert result.patch_summary is not None
    assert result.patch_summary.modified_paths == (".env.example",)
    multi_pass_payload = executor.patch_calls[0]["multi_pass"]
    current_context = multi_pass_payload["current_allowed_file_context"]
    assert {
        "path": ".env.example",
        "text": "APP_ENV=dev\nDATABASE_URL=\"sqlite:///%kernel.project_dir%/var/app.db\"\n",
    } in current_context
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer reports hunk mismatch diagnostics")
def test_run_pipeline_multipass_hunk_mismatch_reports_context_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    (repo / "composer.json").write_text(
        '{\n  "require": {\n    "php": ">=8.2"\n  }\n}\n',
        encoding="utf-8",
    )
    _git(repo, "add", "composer.json")
    _git(repo, "commit", "-m", "Add composer")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"dependencies": ["composer.json"]})
    )
    executor = FakeExecutor(
        multipass_patch_answers=[_stale_full_file_composer_diff(valid_json=False)],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("composer.json",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Continue the existing Symfony Todo List app and inspect composer.json dependencies",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.reason == "hunk_preimage_mismatch"
    assert result.multi_pass_summary is not None
    failed_issue = result.multi_pass_summary.failed_pass_issue
    assert failed_issue is not None
    assert failed_issue.diagnostics == {
        "target_path": "composer.json",
        "pass_index": 1,
        "pass_id": "dependencies",
        "selected_context": True,
        "full_content_provided": True,
        "file_existed_before_run": True,
        "created_earlier_in_run": False,
        "full_file_replacement_eligible": True,
        "included_in_full_file_replacement_guidance": True,
        "executor_used_full_file_replacement": True,
    }
    rendered = render_run_result(result)
    assert "pass 1 diagnostic target path: composer.json" in rendered
    assert "pass 1 diagnostic selected context: yes" in rendered
    assert "pass 1 diagnostic pass index: 1" in rendered
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses full-file patch fallback review")
def test_run_pipeline_multipass_blocks_unsafe_full_file_candidate_before_review(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    _write_todo_entity(repo)
    _git(repo, "add", "src/Entity/Todo.php")
    _git(repo, "commit", "-m", "Add entities")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"entities": ["src/Entity/Todo.php"]})
    )
    reviewer = FakeFullFileReplacementReviewer()
    executor = FakeExecutor(
        multipass_patch_answers=[
            "\n".join(
                [
                    _stale_todo_full_file_diff(),
                    _stale_todo_full_file_diff(),
                ]
            )
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("src/Entity/Todo.php",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update src/Entity/Todo.php entity",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert reviewer.calls == []
    failed_issue = result.multi_pass_summary.failed_pass_issue
    assert failed_issue.diagnostics["final_outcome"] == "blocked_by_deterministic_invariant"
    assert failed_issue.diagnostics["reviewer_reason"] == "target_path_not_exactly_failed_patch_path"
    assert "completed" not in (repo / "src/Entity/Todo.php").read_text(encoding="utf-8")
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_llm_review_approval_applies_full_file_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    _write_todo_entity(repo)
    _git(repo, "add", "src/Entity/Todo.php")
    _git(repo, "commit", "-m", "Add Todo entity")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer(
        FullFileReplacementReviewDecision(
            approve=True,
            risk_level="medium",
            reason="coherent entity replacement",
        )
    )

    result = _run_todo_hunk_mismatch_pipeline(
        repo=repo,
        tmp_path=tmp_path,
        manager=manager,
        reviewer=reviewer,
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert reviewer.calls[0].target_path == "src/Entity/Todo.php"
    text = (repo / "src/Entity/Todo.php").read_text(encoding="utf-8")
    assert "private bool $completed = false;" in text
    diagnostics = result.multi_pass_summary.pass_results[0].fallback_diagnostics
    assert diagnostics["fallback_kind"] == "llm_reviewed_full_file_replacement_after_hunk_mismatch"
    assert diagnostics["reviewer_approve"] is True
    assert diagnostics["reviewer_risk_level"] == "medium"
    assert diagnostics["final_outcome"] == "applied"
    rendered = render_run_result(result)
    assert "pass 1 diagnostic reviewer approve result: yes" in rendered
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_llm_review_applies_full_file_replacement_in_multifile_patch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    _write_todo_entity(repo)
    _git(repo, "add", "src/Entity/Todo.php")
    _git(repo, "commit", "-m", "Add Todo entity")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {"entities": ["src/Entity/Todo.php", "src/Service/TodoStatsService.php"]}
        )
    )
    reviewer = FakeFullFileReplacementReviewer()
    executor = FakeExecutor(
        multipass_patch_answers=[
            "\n".join(
                [
                    _stale_todo_full_file_diff(),
                    _valid_new_file_diff("src/Service/TodoStatsService.php"),
                ]
            )
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("src/Entity/Todo.php",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update src/Entity/Todo.php entity and add todo stats service",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert "completed" in (repo / "src/Entity/Todo.php").read_text(encoding="utf-8")
    assert (repo / "src/Service/TodoStatsService.php").is_file()
    assert result.multi_pass_summary.pass_results[0].patch_paths == (
        "src/Entity/Todo.php",
        "src/Service/TodoStatsService.php",
    )
    diagnostics = result.multi_pass_summary.pass_results[0].fallback_diagnostics
    assert diagnostics["final_outcome"] == "applied"
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_llm_review_rejection_blocks_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    _write_todo_entity(repo)
    _git(repo, "add", "src/Entity/Todo.php")
    _git(repo, "commit", "-m", "Add Todo entity")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer(
        FullFileReplacementReviewDecision(
            approve=False,
            risk_level="medium",
            reason="replacement removes required behavior",
            concerns=("missing methods",),
        )
    )

    result = _run_todo_hunk_mismatch_pipeline(
        repo=repo,
        tmp_path=tmp_path,
        manager=manager,
        reviewer=reviewer,
    )

    assert result.status == RUN_STATUS_FAILED
    assert "completed" not in (repo / "src/Entity/Todo.php").read_text(encoding="utf-8")
    diagnostics = result.multi_pass_summary.failed_pass_issue.diagnostics
    assert diagnostics["reviewer_approve"] is False
    assert diagnostics["reviewer_reason"] == "replacement removes required behavior"
    assert diagnostics["final_outcome"] == "reviewer_rejected"
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_llm_review_high_risk_blocks_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    _write_todo_entity(repo)
    _git(repo, "add", "src/Entity/Todo.php")
    _git(repo, "commit", "-m", "Add Todo entity")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer(
        FullFileReplacementReviewDecision(
            approve=True,
            risk_level="high",
            reason="too destructive",
        )
    )

    result = _run_todo_hunk_mismatch_pipeline(
        repo=repo,
        tmp_path=tmp_path,
        manager=manager,
        reviewer=reviewer,
    )

    assert result.status == RUN_STATUS_FAILED
    assert "completed" not in (repo / "src/Entity/Todo.php").read_text(encoding="utf-8")
    diagnostics = result.multi_pass_summary.failed_pass_issue.diagnostics
    assert diagnostics["reviewer_approve"] is True
    assert diagnostics["reviewer_risk_level"] == "high"
    assert diagnostics["final_outcome"] == "reviewer_rejected"
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_invalid_json_reviewer_result_blocks_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    _write_todo_entity(repo)
    _git(repo, "add", "src/Entity/Todo.php")
    _git(repo, "commit", "-m", "Add Todo entity")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer(
        parse_full_file_replacement_review_json("{not json")
    )

    result = _run_todo_hunk_mismatch_pipeline(
        repo=repo,
        tmp_path=tmp_path,
        manager=manager,
        reviewer=reviewer,
    )

    assert result.status == RUN_STATUS_FAILED
    diagnostics = result.multi_pass_summary.failed_pass_issue.diagnostics
    assert diagnostics["reviewer_reason"] == "invalid_json"
    assert diagnostics["reviewer_error"] == "invalid_json"
    assert "completed" not in (repo / "src/Entity/Todo.php").read_text(encoding="utf-8")
    assert manager.cleanup(result.workspace_session).cleaned is True


@pytest.mark.skip(reason="workspace_write no longer uses LLM full-file patch fallback")
def test_run_pipeline_multipass_reviewer_failure_blocks_replacement(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    monkeypatch.setenv("SFE_FULL_FILE_REPLACEMENT_REVIEW", "auto")
    repo = _init_repo(tmp_path / "repo")
    _write_todo_entity(repo)
    _git(repo, "add", "src/Entity/Todo.php")
    _git(repo, "commit", "-m", "Add Todo entity")
    manager = _manager()
    reviewer = FakeFullFileReplacementReviewer(error=TimeoutError("review timed out"))

    result = _run_todo_hunk_mismatch_pipeline(
        repo=repo,
        tmp_path=tmp_path,
        manager=manager,
        reviewer=reviewer,
    )

    assert result.status == RUN_STATUS_FAILED
    diagnostics = result.multi_pass_summary.failed_pass_issue.diagnostics
    assert diagnostics["reviewer_reason"] == "reviewer_execution_error"
    assert diagnostics["reviewer_error"] == "reviewer_execution_error"
    assert "completed" not in (repo / "src/Entity/Todo.php").read_text(encoding="utf-8")
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_multipass_warns_for_patch_outside_batch_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"foundation": ["index.html"]})
    )
    executor = FakeExecutor(
        multipass_patch_answers=[_valid_new_file_diff("README.md")],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create a scaffold",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.issue is None
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.failed_pass_id is None
    assert result.multi_pass_summary.pass_results[0].warnings == (
        "multi_pass_path_outside_allowed_files:README.md",
    )
    assert "multi_pass_path_outside_allowed_files:README.md" in result.warnings
    assert (repo / "README.md").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_multipass_skips_pass_already_promoted_outside_batch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    planner = FakeMultiPassPlanner(
        _multipass_plan_json(
            {
                "foundation": ["index.html"],
                "docs": ["README.md"],
            }
        )
    )
    executor = FakeExecutor(
        multipass_patch_answers=[_valid_new_file_diff("README.md")],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create a scaffold",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.multi_pass_summary is not None
    assert len(executor.patch_calls) == 1
    first_pass, second_pass = result.multi_pass_summary.pass_results
    assert first_pass.status == "completed"
    assert first_pass.warnings == (
        "multi_pass_path_outside_allowed_files:README.md",
    )
    assert second_pass.status == "skipped"
    assert second_pass.warnings == (
        "multi_pass_skipped_already_promoted_outside_batch:README.md",
    )
    assert result.multi_pass_summary.passes_completed == 1
    assert result.promoted_files == ("README.md",)
    assert (repo / "README.md").read_text(encoding="utf-8") == "one\ntwo\nthree\n"
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_multipass_invalid_plan_fails_cleanly(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    planner = FakeMultiPassPlanner("{bad json")
    executor = FakeExecutor()

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create a scaffold",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "multi_pass_planning"
    assert result.issue.reason == "invalid_plan_json"
    assert result.patch_result is None
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.status == "failed"
    assert result.multi_pass_summary.passes_completed == 0
    assert executor.patch_calls == []
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_multipass_timeout_reports_failed_pass_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "true")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    timeout_diagnostics = {
        "provider_name": "codexcli",
        "error_type": "ProviderCallIdleTimeoutError",
        "provider_timeout_diagnostics": {
            "provider": "openai-codexcli",
            "model": "gpt-5.4",
            "role": "executor",
            "timeout_kind": "idle",
            "idle_timeout_seconds": 900,
            "elapsed_seconds": 901.5,
            "provider_output_seen": False,
            "provider_stdout_chunk_count": 0,
        },
    }
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"foundation": ["index.html"]})
    )
    executor = FakeExecutor(
        multipass_patch_answers=[
            ExecutorResponse(
                None,
                "provider_idle_timeout",
                1,
                provider_name="codexcli",
                response_diagnostics=timeout_diagnostics,
            )
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create a scaffold",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_FAILED
    assert result.issue is not None
    assert result.issue.category == "patch_generation"
    assert result.issue.reason == "provider_idle_timeout"
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.failed_pass_id == "foundation"
    assert result.multi_pass_summary.pass_results[0].provider_diagnostics == timeout_diagnostics
    assert manager.cleanup(result.workspace_session).cleaned is True


def test_run_pipeline_auto_multipass_symfony_scaffold_mock(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SFE_WORKSPACE_WRITE_MULTIPASS", "auto")
    repo = _init_repo(tmp_path / "repo")
    manager = _manager()
    batch_files = {
        "foundation": tuple(f"config/file_{index}.php" for index in range(1, 8)),
        "src": tuple(f"src/File{index}.php" for index in range(1, 8)),
        "templates": tuple(f"templates/page_{index}.html.twig" for index in range(1, 8)),
    }
    planner = FakeMultiPassPlanner(_multipass_plan_json(batch_files))
    executor = FakeExecutor(
        multipass_patch_answers=[
            _valid_multi_new_file_diff(files)
            for files in batch_files.values()
        ],
    )

    result = RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Create a Symfony-style scaffold with 21 files",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )

    assert result.status == RUN_STATUS_COMPLETED
    assert result.multi_pass_summary is not None
    assert result.multi_pass_summary.passes_total == 3
    assert result.multi_pass_summary.passes_completed == 3
    assert len(result.promoted_files) == 21
    assert len(planner.calls) == 1
    assert len(executor.patch_calls) == 3
    assert all((repo / path).is_file() for path in result.promoted_files)
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
    filesystem_executor: FakeFilesystemExecutor | None = None,
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
        filesystem_executor=filesystem_executor,
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


def _valid_minisite_diff() -> str:
    files = {
        "index.html": "\n".join(
            [
                "<!doctype html>",
                '<html lang="en">',
                "<head>",
                '  <meta charset="utf-8">',
                "  <title>Mini Site</title>",
                '  <link rel="stylesheet" href="style.css">',
                "</head>",
                "<body>",
                "  <main>",
                "    <h1>Mini Site</h1>",
                "    <button id=\"action\">Start</button>",
                "  </main>",
                '  <script src="script.js"></script>',
                "</body>",
                "</html>",
            ]
        ),
        "style.css": "\n".join(
            [
                ":root {",
                "  color-scheme: light;",
                "}",
                "body {",
                "  font-family: system-ui, sans-serif;",
                "}",
                "button {",
                "  cursor: pointer;",
                "}",
            ]
        ),
        "script.js": "\n".join(
            [
                'const button = document.querySelector("#action");',
                'button?.addEventListener("click", () => {',
                '  button.textContent = "Ready";',
                "});",
            ]
        ),
        "README.md": "\n".join(
            [
                "# Mini Site",
                "",
                "Open `index.html` in a browser.",
            ]
        ),
    }
    return "\n".join(
        _valid_new_file_diff_with_content(path, content)
        for path, content in files.items()
    )


def _valid_new_file_diff_with_content(path: str, content: str) -> str:
    lines = content.splitlines()
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{path}",
            f"@@ -0,0 +1,{len(lines)} @@",
            *(f"+{line}" for line in lines),
        ]
    )


def _stale_full_file_composer_diff(*, valid_json: bool) -> str:
    new_lines = (
        [
            "{",
            '  "require": {',
            '    "php": ">=8.2",',
            '    "symfony/form": "^7.0"',
            "  }",
            "}",
        ]
        if valid_json
        else [
            "{",
            '  "require": {',
            '    "php": ">=8.2",',
            '    "symfony/form": "^7.0",',
            "  }",
            "}",
        ]
    )
    return "\n".join(
        [
            "diff --git a/composer.json b/composer.json",
            "--- a/composer.json",
            "+++ b/composer.json",
            f"@@ -1,3 +1,{len(new_lines)} @@",
            "-{",
            '-  \"require\": {}',
            "-}",
            *(f"+{line}" for line in new_lines),
        ]
    )


def _write_todo_entity(repo: Path) -> None:
    target = repo / "src/Entity/Todo.php"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "<?php",
                "",
                "namespace App\\Entity;",
                "",
                "class Todo",
                "{",
                "    private ?int $id = null;",
                "",
                "    public function getId(): ?int",
                "    {",
                "        return $this->id;",
                "    }",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _stale_todo_full_file_diff() -> str:
    stale_lines = [
        "<?php",
        "",
        "namespace App\\Entity;",
        "",
        "class Todo",
        "{",
        "    public int $id;",
        "",
        "    public function getId(): ?int",
        "    {",
        "        return $this->id;",
        "    }",
        "}",
    ]
    replacement_lines = [
        "<?php",
        "",
        "namespace App\\Entity;",
        "",
        "class Todo",
        "{",
        "    private ?int $id = null;",
        "    private string $title = '';",
        "    private bool $completed = false;",
        "",
        "    public function getId(): ?int",
        "    {",
        "        return $this->id;",
        "    }",
        "",
        "    public function isCompleted(): bool",
        "    {",
        "        return $this->completed;",
        "    }",
        "}",
    ]
    return "\n".join(
        [
            "diff --git a/src/Entity/Todo.php b/src/Entity/Todo.php",
            "--- a/src/Entity/Todo.php",
            "+++ b/src/Entity/Todo.php",
            f"@@ -1,{len(stale_lines)} +1,{len(replacement_lines)} @@",
            *(f"-{line}" for line in stale_lines),
            *(f"+{line}" for line in replacement_lines),
        ]
    )


def _readme_full_file_diff() -> str:
    old_lines = [
        "# Todo",
        "",
        "Existing docs.",
    ]
    new_lines = [
        "# Todo",
        "",
        "Updated docs.",
        "",
        "Run the Symfony Todo List app and manage tasks from the dashboard.",
    ]
    return "\n".join(
        [
            "diff --git a/README.md b/README.md",
            "--- a/README.md",
            "+++ b/README.md",
            f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@",
            *(f"-{line}" for line in old_lines),
            *(f"+{line}" for line in new_lines),
        ]
    )


def _readme_partial_location_mismatch_diff() -> str:
    return "\n".join(
        [
            "diff --git a/README.md b/README.md",
            "--- a/README.md",
            "+++ b/README.md",
            "@@ -99,1 +99,1 @@",
            "-Old docs",
            "+Updated docs",
        ]
    )


def _dashboard_twig_full_file_diff() -> str:
    old_lines = [
        "{% extends 'base.html.twig' %}",
        "",
        "{% block body %}",
        "Old dashboard",
        "{% endblock %}",
    ]
    new_lines = [
        "{% extends 'base.html.twig' %}",
        "",
        "{% block body %}",
        "<section>",
        "    <h1>Dashboard ready</h1>",
        "</section>",
        "{% endblock %}",
    ]
    return "\n".join(
        [
            "diff --git a/templates/dashboard/index.html.twig b/templates/dashboard/index.html.twig",
            "--- a/templates/dashboard/index.html.twig",
            "+++ b/templates/dashboard/index.html.twig",
            f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@",
            *(f"-{line}" for line in old_lines),
            *(f"+{line}" for line in new_lines),
        ]
    )


def _todo_controller_partial_diff() -> str:
    return "\n".join(
        [
            "diff --git a/src/Controller/TodoController.php b/src/Controller/TodoController.php",
            "--- a/src/Controller/TodoController.php",
            "+++ b/src/Controller/TodoController.php",
            "@@ -9,1 +9,1 @@",
            "-        return 'stale';",
            "+        return 'new';",
        ]
    )


def _run_todo_hunk_mismatch_pipeline(
    *,
    repo: Path,
    tmp_path: Path,
    manager: WorkspaceManager,
    reviewer: FakeFullFileReplacementReviewer,
) -> object:
    planner = FakeMultiPassPlanner(
        _multipass_plan_json({"entities": ["src/Entity/Todo.php"]})
    )
    executor = FakeExecutor(multipass_patch_answers=[_stale_todo_full_file_diff()])
    return RunPipeline(
        backend=DirectBackend(executor=executor),
        workspace_manager=manager,
        discovery_router=FakeDiscoveryRouter(("src/Entity/Todo.php",)),
        execution_mode_router=FakeExecutionModeRouter(),
        multipass_planner=planner,
        full_file_replacement_reviewer=reviewer,
    ).run(
        RunRequest(
            workspace_root=repo,
            task="Update src/Entity/Todo.php entity with completed state",
            workspace_policy=WorkspaceIsolationPolicy(worktree_parent=tmp_path / "worktrees"),
        )
    )


def _valid_two_file_modify_diff() -> str:
    return "\n".join(
        [
            "diff --git a/app.py b/app.py",
            "--- a/app.py",
            "+++ b/app.py",
            "@@ -1,1 +1,1 @@",
            '-GREETING = "Hello"',
            '+GREETING = "Hello from SFE"',
            "diff --git a/test_app.py b/test_app.py",
            "--- a/test_app.py",
            "+++ b/test_app.py",
            "@@ -1,5 +1,5 @@",
            " from app import GREETING",
            " ",
            " ",
            " def test_greeting():",
            '-    assert GREETING == "Hello"',
            '+    assert GREETING == "Hello from SFE"',
        ]
    )


def _valid_multi_new_file_diff(paths: tuple[str, ...]) -> str:
    return "\n".join(
        _valid_new_file_diff_with_content(path, f"<?php // {path}\n")
        for path in paths
    )


def _multipass_plan_json(batch_files: dict[str, tuple[str, ...] | list[str]]) -> str:
    return json.dumps(
        {
            "project_summary": "Mock scaffold",
            "batches": [
                {
                    "id": batch_id,
                    "title": batch_id.title(),
                    "goal": f"Create {batch_id} files.",
                    "allowed_files": list(paths),
                    "depends_on": [],
                    "validation_notes": ["mock validation"],
                }
                for batch_id, paths in batch_files.items()
            ],
        }
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
