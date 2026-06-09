"""Tests for the shared renderer-independent SFE runtime session."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sfe.runtime_session as runtime_session_module  # noqa: E402
from sfe.execution_mode_router import (  # noqa: E402
    EXECUTION_MODE_CONSOLE_OUTPUT,
    ExecutionModeDecision,
)
from sfe.run_pipeline import RunResult  # noqa: E402
from sfe.runtime_session import RuntimeSession  # noqa: E402
from sfe.workspace_isolation import (  # noqa: E402
    WorkspaceSession,
    WorkspaceStatus,
    WorkspaceStatusResult,
)
from sfe_tui.backends import DirectBackend  # noqa: E402
from sfe_tui.executors import ExecutorResponse  # noqa: E402


class FakeExecutor:
    provider_name = "fake-executor"

    def __init__(self) -> None:
        self.console_calls: list[dict[str, object]] = []
        self.patch_calls: list[dict[str, object]] = []

    def answer_console(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.console_calls.append(executor_payload)
        return ExecutorResponse(
            "console answer",
            None,
            1,
            provider_name=self.provider_name,
        )

    def execute(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        return self.answer_console(executor_payload)

    def propose_patch(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.patch_calls.append(executor_payload)
        return ExecutorResponse("unused", None, 1, provider_name=self.provider_name)


class FakeExecutionModeRouter:
    provider_name = "fake-execution-mode-router"
    model = "fake-execution-mode-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def decide(self, *, task: str) -> ExecutionModeDecision:
        self.calls.append({"task": task})
        return ExecutionModeDecision(
            execution_mode=EXECUTION_MODE_CONSOLE_OUTPUT,
            reason="fake console answer",
            confidence=0.9,
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class RecordingWorkspaceManager:
    def __init__(self, status_result: WorkspaceStatusResult) -> None:
        self.status_result = status_result
        self.status_calls: list[WorkspaceSession] = []

    def status(self, session: WorkspaceSession) -> WorkspaceStatusResult:
        self.status_calls.append(session)
        return self.status_result


def make_session(tmp_path: Path) -> tuple[RuntimeSession, FakeExecutionModeRouter, FakeExecutor]:
    executor = FakeExecutor()
    router = FakeExecutionModeRouter()
    session = RuntimeSession(
        backend=DirectBackend(executor=executor),
        cwd=tmp_path,
        execution_mode_router=router,
    )
    return session, router, executor


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def init_git_repo(path: Path) -> Path:
    path.mkdir()
    assert run_git(path, "init", "-b", "main").returncode == 0
    assert run_git(path, "config", "user.name", "SFE Test").returncode == 0
    assert run_git(path, "config", "user.email", "sfe@example.invalid").returncode == 0
    (path / "context.txt").write_text("old context\n", encoding="utf-8")
    assert run_git(path, "add", "context.txt").returncode == 0
    assert run_git(path, "commit", "-m", "initial").returncode == 0
    return path


def test_set_task_invalidates_same_transient_state_without_clearing_run_report(
    tmp_path: Path,
) -> None:
    session, _, _ = make_session(tmp_path)
    previous_run = object()
    session.discovery_result = object()  # type: ignore[assignment]
    session.latest_result = object()  # type: ignore[assignment]
    session.last_run_result = previous_run  # type: ignore[assignment]

    result = session.set_task("  Patch old context  ")

    assert result.ok is True
    assert session.task == "Patch old context"
    assert session.discovery_result is None
    assert session.latest_result is None
    assert session.last_run_result is previous_run


def test_run_without_task_is_blocked_before_runtime_execution(tmp_path: Path) -> None:
    session, router, executor = make_session(tmp_path)
    assert session.set_target_directory("").ok is True

    result = session.run()

    assert result.ok is False
    assert result.error_category == "missing_task"
    assert result.run_result is None
    assert session.last_run_result is None
    assert router.calls == []
    assert executor.console_calls == []
    assert executor.patch_calls == []


def test_run_report_without_previous_run_returns_structured_no_previous_run(
    tmp_path: Path,
) -> None:
    session, router, executor = make_session(tmp_path)

    result = session.run_report()

    assert result.ok is False
    assert result.error_category == "no_previous_run"
    assert result.run_result is None
    assert router.calls == []
    assert executor.console_calls == []


def test_workspace_status_uses_current_workspace_session_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    worktree = tmp_path / "worktree"
    workspace.mkdir()
    worktree.mkdir()
    status_result = WorkspaceStatusResult(
        ok=True,
        status=WorkspaceStatus(
            git_status_porcelain=" M context.txt",
            git_diff="diff --git a/context.txt b/context.txt",
            changed_files=("context.txt",),
            source_path=workspace,
            worktree_path=worktree,
            source_branch="main",
            worktree_branch="sfe/test",
        ),
    )
    manager = RecordingWorkspaceManager(status_result)
    session = RuntimeSession(
        backend=DirectBackend(executor=FakeExecutor()),
        cwd=workspace,
        workspace_manager=manager,  # type: ignore[arg-type]
    )
    workspace_session = WorkspaceSession(
        session_id="sfe-session",
        source_path=workspace,
        source_git_root=workspace,
        worktree_path=worktree,
        source_branch="main",
        worktree_branch="sfe/test",
        backend_name="fake",
    )
    session.workspace_root = worktree
    session.workspace_session = workspace_session

    result = session.workspace_status()

    assert result.workspace_root == worktree
    assert result.workspace_session == workspace_session
    assert result.status_result == status_result
    assert manager.status_calls == [workspace_session]


def test_workspace_status_reports_original_git_repository_state(tmp_path: Path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    session, _, _ = make_session(repo)
    assert session.set_target_directory("").ok is True

    result = session.workspace_status()

    assert result.workspace_root == repo
    assert result.workspace_session is None
    assert result.status_result is not None
    assert result.status_result.ok is True
    assert result.status_result.status is not None
    assert result.status_result.status.source_path == repo
    assert result.status_result.status.worktree_path == repo
    assert result.status_result.status.source_branch == "main"
    assert result.status_result.status.worktree_branch == "main"
    assert result.status_result.status.changed_files == ()
    assert result.status_result.status.git_status_porcelain == ""


def test_workspace_status_reports_original_git_repository_changes(tmp_path: Path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    (repo / "context.txt").write_text("new context\n", encoding="utf-8")
    session, _, _ = make_session(repo)
    assert session.set_target_directory("").ok is True

    result = session.workspace_status()

    assert result.status_result is not None
    assert result.status_result.ok is True
    assert result.status_result.status is not None
    assert result.status_result.status.changed_files == ("context.txt",)
    assert result.status_result.status.git_status_porcelain.strip() == "M context.txt"


def test_workspace_status_reports_original_git_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def missing_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        del cwd, args
        raise FileNotFoundError

    monkeypatch.setattr(runtime_session_module, "_git", missing_git)
    session, _, _ = make_session(workspace)
    assert session.set_target_directory("").ok is True

    result = session.workspace_status()

    assert result.status_result is not None
    assert result.status_result.ok is False
    assert result.status_result.issue is not None
    assert result.status_result.issue.category == "git_status"
    assert result.status_result.issue.reason == "git_unavailable"


def test_target_directory_change_clears_stale_workspace_session_and_run_state(
    tmp_path: Path,
) -> None:
    repo_a = init_git_repo(tmp_path / "repo-a")
    repo_b = init_git_repo(tmp_path / "repo-b")
    stale_worktree = tmp_path / "repo-a-worktree"
    stale_worktree.mkdir()
    status_result = WorkspaceStatusResult(
        ok=True,
        status=WorkspaceStatus(
            git_status_porcelain=" M hello.py",
            git_diff="diff --git a/hello.py b/hello.py",
            changed_files=("hello.py",),
            source_path=repo_a,
            worktree_path=stale_worktree,
            source_branch="main",
            worktree_branch="sfe/stale",
        ),
    )
    manager = RecordingWorkspaceManager(status_result)
    session = RuntimeSession(
        backend=DirectBackend(executor=FakeExecutor()),
        cwd=tmp_path,
        workspace_manager=manager,  # type: ignore[arg-type]
    )
    assert session.set_target_directory(str(repo_a)).ok is True
    stale_session = WorkspaceSession(
        session_id="stale-session",
        source_path=repo_a,
        source_git_root=repo_a,
        worktree_path=stale_worktree,
        source_branch="main",
        worktree_branch="sfe/stale",
        backend_name="fake",
    )
    session.workspace_root = stale_worktree
    session.workspace_session = stale_session
    session.discovery_result = object()  # type: ignore[assignment]
    session.latest_result = object()  # type: ignore[assignment]
    session.last_run_result = object()  # type: ignore[assignment]
    session.last_progress_events = (object(),)  # type: ignore[assignment]

    result = session.set_target_directory(str(repo_b))

    assert result.ok is True
    assert result.workspace_root == repo_b
    assert session.workspace_root == repo_b
    assert session.workspace_session is None
    assert session.discovery_result is None
    assert session.latest_result is None
    assert session.last_run_result is None
    assert session.last_progress_events == ()

    status = session.workspace_status()

    assert status.workspace_root == repo_b
    assert status.workspace_session is None
    assert status.status_result is not None
    assert status.status_result.ok is True
    assert status.status_result.status is not None
    assert status.status_result.status.source_path == repo_b
    assert status.status_result.status.worktree_path == repo_b
    assert manager.status_calls == []


def test_run_after_target_change_does_not_use_previous_worktree_session(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo_a = init_git_repo(tmp_path / "repo-a")
    repo_b = init_git_repo(tmp_path / "repo-b")
    stale_worktree = tmp_path / "repo-a-worktree"
    stale_worktree.mkdir()
    session, _, _ = make_session(tmp_path)
    assert session.set_target_directory(str(repo_a)).ok is True
    session.workspace_root = stale_worktree
    session.workspace_session = WorkspaceSession(
        session_id="stale-session",
        source_path=repo_a,
        source_git_root=repo_a,
        worktree_path=stale_worktree,
        source_branch="main",
        worktree_branch="sfe/stale",
        backend_name="fake",
    )
    assert session.set_target_directory(str(repo_b)).ok is True
    assert session.set_task("Answer from target B").ok is True
    captured_requests = []

    class FakeRunPipeline:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        def run(self, request) -> RunResult:
            captured_requests.append(request)
            return RunResult(
                status="completed",
                active_workspace=request.workspace_root,
                console_output="ok",
            )

    monkeypatch.setattr(runtime_session_module, "RunPipeline", FakeRunPipeline)

    result = session.run()

    assert result.ok is True
    assert len(captured_requests) == 1
    assert captured_requests[0].workspace_root == repo_b
    assert captured_requests[0].workspace_session is None
    assert session.workspace_root == repo_b
    assert session.workspace_session is None


def test_run_captures_structured_progress_events_without_tui_rendering(
    tmp_path: Path,
) -> None:
    session, router, executor = make_session(tmp_path)
    callback_events = []
    assert session.set_target_directory("").ok is True
    assert session.set_task("Answer a question").ok is True

    result = session.run(progress_callback=callback_events.append)

    assert result.ok is True
    assert result.run_result is not None
    assert result.run_result.console_output == "console answer"
    assert [event.name for event in result.progress_events] == [
        "run_started",
        "execution_mode_routing",
        "execution_mode_selected",
        "executor_prompt_prepared",
        "console_answer_generated",
    ]
    assert result.progress_events == session.last_progress_events
    assert callback_events == list(result.progress_events)
    assert router.calls == [{"task": "Answer a question"}]
    assert len(executor.console_calls) == 1
