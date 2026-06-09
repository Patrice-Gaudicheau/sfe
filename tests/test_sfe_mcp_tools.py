"""Tests for the local SFE MCP tool layer."""

from __future__ import annotations

import sys
import threading
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.execution_mode_router import (  # noqa: E402
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
)
from sfe.patching import PatchSummary  # noqa: E402
from sfe.run_pipeline import (  # noqa: E402
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
    RunIssue,
    RunProgressEvent,
    RunResult,
)
from sfe.runtime_session import (  # noqa: E402
    RunReportResult,
    RuntimeWorkspaceStatus,
    SessionRunResult,
    TargetDirectoryResult,
    TaskSetResult,
)
from sfe.workspace_isolation import (  # noqa: E402
    WorkspaceSession,
    WorkspaceStatus,
    WorkspaceStatusResult,
)
from sfe_mcp.tools import SfeMcpToolHandlers, V1_TOOL_NAMES  # noqa: E402


FORBIDDEN_TOOL_NAMES = {
    "create_worktree",
    "sfe_create_worktree",
    "apply_patch",
    "sfe_apply_patch",
    "promote",
    "sfe_promote",
    "merge",
    "push",
    "pull_request",
    "cleanup-worktree",
    "sfe_cleanup_worktree",
    "shell",
    "run_shell",
    "benchmark",
    "docker",
    "http",
    "openai_compatible_api",
}

FORBIDDEN_MCP_IMPORTS = {
    "SfeTuiApp",
    "sfe_tui.app",
    "RunPipeline",
    "RunRequest",
}


class FakeRuntimeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.target_result = TargetDirectoryResult(
            ok=True,
            workspace_root=Path.home() / "workspace",
        )
        self.task_result = TaskSetResult(ok=True, task="Patch context")
        self.run_result = SessionRunResult(
            ok=True,
            run_result=make_run_result(),
            progress_events=(
                RunProgressEvent(
                    "run_started",
                    "SFE: run started",
                    {
                        "secret": "SECRET_FILE_CONTENT",
                        "candidate_count": 2,
                    },
                ),
            ),
        )
        self.report_result = RunReportResult(ok=True, run_result=make_run_result())
        self.workspace_status_result = RuntimeWorkspaceStatus(
            workspace_root=Path.home() / "workspace",
            workspace_session=None,
            status_result=None,
        )

    def set_target_directory(self, path: str) -> TargetDirectoryResult:
        self.calls.append(("set_target_directory", path))
        return self.target_result

    def set_task(self, task: str) -> TaskSetResult:
        self.calls.append(("set_task", task))
        return self.task_result

    def run(self) -> SessionRunResult:
        self.calls.append(("run", None))
        return self.run_result

    def run_report(self) -> RunReportResult:
        self.calls.append(("run_report", None))
        return self.report_result

    def workspace_status(self) -> RuntimeWorkspaceStatus:
        self.calls.append(("workspace_status", None))
        return self.workspace_status_result


def make_run_result(
    *,
    status: str = RUN_STATUS_COMPLETED,
    issue: RunIssue | None = None,
) -> RunResult:
    return RunResult(
        status=status,
        issue=issue,
        execution_mode_decision=ExecutionModeDecision(
            execution_mode=EXECUTION_MODE_WORKSPACE_WRITE,
            reason="The task edits workspace files.",
            confidence=0.9,
            provider_name="fake-router",
            model="fake-model",
            provider_calls_made=1,
        ),
        patch_generated=True,
        patch_applied=True,
        patch_summary=PatchSummary(
            paths=("context.txt", "created.txt"),
            file_count=2,
            hunk_count=2,
            lines_added=4,
            lines_removed=1,
            modified_paths=("context.txt",),
            created_paths=("created.txt",),
        ),
        changed_files=("context.txt", "created.txt"),
        selected_source_refs=("context.txt",),
        executor_provider="fake-executor",
        promotion_status="applied",
        promotion_applied=True,
        promoted_files=("context.txt", "created.txt"),
    )


def test_tool_registry_exposes_exactly_v1_tools() -> None:
    handlers = SfeMcpToolHandlers(FakeRuntimeSession())  # type: ignore[arg-type]

    names = tuple(handlers.registry())

    assert names == V1_TOOL_NAMES
    assert set(names).isdisjoint(FORBIDDEN_TOOL_NAMES)


def test_mcp_package_does_not_import_tui_app_or_run_pipeline_primitives() -> None:
    package_root = PROJECT_ROOT / "sfe_mcp"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(package_root.glob("*.py"))
    )

    for forbidden in FORBIDDEN_MCP_IMPORTS:
        assert forbidden not in source


def test_mcp_package_has_no_direct_stdout_prints_and_uses_stdio_transport() -> None:
    package_root = PROJECT_ROOT / "sfe_mcp"
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(package_root.glob("*.py"))
    }

    assert all("print(" not in source for source in sources.values())
    assert 'transport="stdio"' in sources["server.py"]
    assert "http" not in sources["server.py"].lower()


def test_each_tool_delegates_to_runtime_session() -> None:
    session = FakeRuntimeSession()
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    handlers.sfe_set_target_directory("/tmp/workspace")
    handlers.sfe_set_task("Patch context")
    handlers.sfe_run()
    handlers.sfe_run_report()
    handlers.sfe_workspace_status()

    assert session.calls == [
        ("set_target_directory", "/tmp/workspace"),
        ("set_task", "Patch context"),
        ("run", None),
        ("run_report", None),
        ("workspace_status", None),
    ]


def test_empty_task_rejection_is_surfaced_from_runtime_session() -> None:
    session = FakeRuntimeSession()
    session.task_result = TaskSetResult(ok=False, error_category="missing_task")
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_set_task("   ")

    assert result == {
        "ok": False,
        "status": "failed",
        "error_category": "missing_task",
        "task_present": False,
    }
    assert session.calls == [("set_task", "   ")]


def test_run_without_target_or_task_failure_is_surfaced() -> None:
    session = FakeRuntimeSession()
    session.run_result = SessionRunResult(
        ok=False,
        error_category="workspace_not_selected",
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run()

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["error_category"] == "workspace_not_selected"
    assert result["issue"] == {
        "category": "runtime_session",
        "reason": "workspace_not_selected",
        "path": None,
    }
    assert result["action_hint"] == "call_sfe_set_target_directory"
    assert result["execution_mode"] is None
    assert result["selected_source_refs"] == []
    assert result["changed_files"] == []
    assert result["promotion"]["status"] == "skipped"
    assert result["progress"] == []
    assert session.calls == [("run", None)]


def test_run_without_task_failure_is_surfaced_actionably() -> None:
    session = FakeRuntimeSession()
    session.run_result = SessionRunResult(
        ok=False,
        error_category="missing_task",
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run()

    assert result["ok"] is False
    assert result["error_category"] == "missing_task"
    assert result["issue"]["reason"] == "missing_task"
    assert result["action_hint"] == "call_sfe_set_task"
    assert session.calls == [("run", None)]


def test_run_report_without_previous_run_is_surfaced() -> None:
    session = FakeRuntimeSession()
    session.report_result = RunReportResult(
        ok=False,
        error_category="no_previous_run",
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run_report()

    assert result["ok"] is False
    assert result["status"] == "failed"
    assert result["error_category"] == "no_previous_run"
    assert result["issue"] == {
        "category": "runtime_session",
        "reason": "no_previous_run",
        "path": None,
    }
    assert result["action_hint"] == "call_sfe_run_first"
    assert result["progress"] == []
    assert session.calls == [("run_report", None)]


def test_concurrent_run_is_rejected_with_structured_status() -> None:
    entered = threading.Event()
    release = threading.Event()

    class BlockingRuntimeSession(FakeRuntimeSession):
        def run(self) -> SessionRunResult:
            self.calls.append(("run", None))
            entered.set()
            release.wait(timeout=5)
            return self.run_result

    session = BlockingRuntimeSession()
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]
    first_result: list[dict[str, object]] = []

    thread = threading.Thread(
        target=lambda: first_result.append(handlers.sfe_run()),
        daemon=True,
    )
    thread.start()
    assert entered.wait(timeout=5)

    second_result = handlers.sfe_run()

    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert first_result and first_result[0]["ok"] is True
    assert second_result["ok"] is False
    assert second_result["error_category"] == "run_in_progress"
    assert second_result["issue"] == {
        "category": "runtime_session",
        "reason": "run_in_progress",
        "path": None,
    }
    assert second_result["action_hint"] == "retry_sfe_run_after_current_run_finishes"
    assert session.calls == [("run", None)]


def test_run_output_is_structured_and_omits_sensitive_payload_material() -> None:
    session = FakeRuntimeSession()
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run()

    assert result["ok"] is True
    assert result["execution_mode"] == EXECUTION_MODE_WORKSPACE_WRITE
    assert result["selected_source_refs"] == ["context.txt"]
    assert result["modified_files"] == ["context.txt"]
    assert result["created_files"] == ["created.txt"]
    assert result["promoted_files"] == ["context.txt", "created.txt"]
    assert result["promotion"] == {
        "status": "applied",
        "applied": True,
        "issue": None,
    }
    rendered = repr(result)
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "raw_provider_payload" not in rendered
    assert "full prompt" not in rendered
    assert ".env" not in rendered
    assert "api_key" not in rendered.lower()
    assert "provider_payload" not in rendered
    assert result["progress"] == [
        {
            "name": "run_started",
            "message": "SFE: run started",
            "metadata": {"candidate_count": 2},
        }
    ]


def test_failed_run_result_serializes_issue_category_and_reason() -> None:
    session = FakeRuntimeSession()
    session.run_result = SessionRunResult(
        ok=False,
        run_result=make_run_result(
            status=RUN_STATUS_FAILED,
            issue=RunIssue("patch_generation", "invalid_response"),
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run()

    assert result["ok"] is False
    assert result["status"] == RUN_STATUS_FAILED
    assert result["issue"] == {
        "category": "patch_generation",
        "reason": "invalid_response",
        "path": None,
    }
    assert result["action_hint"] == "inspect_run_report_or_retry"


def test_workspace_status_serializes_session_metadata_safely(tmp_path: Path) -> None:
    source = tmp_path / "source"
    worktree = tmp_path / "worktree"
    source.mkdir()
    worktree.mkdir()
    workspace_session = WorkspaceSession(
        session_id="session-1",
        source_path=source,
        source_git_root=source,
        worktree_path=worktree,
        source_branch="main",
        worktree_branch="sfe/session-1",
        backend_name="git-worktree",
    )
    session = FakeRuntimeSession()
    session.workspace_status_result = RuntimeWorkspaceStatus(
        workspace_root=worktree,
        workspace_session=workspace_session,
        status_result=WorkspaceStatusResult(
            ok=True,
            status=WorkspaceStatus(
                git_status_porcelain=" M context.txt",
                git_diff="diff --git a/context.txt b/context.txt",
                changed_files=("context.txt",),
                source_path=source,
                worktree_path=worktree,
                source_branch="main",
                worktree_branch="sfe/session-1",
            ),
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_workspace_status()

    assert result["ok"] is True
    assert result["mode"] == "isolated"
    assert result["isolated_session"]["session_id"] == "session-1"
    assert result["git_status"] == {
        "available": True,
        "changed_files": ["context.txt"],
        "source_branch": "main",
        "worktree_branch": "sfe/session-1",
    }


def test_run_report_includes_diagnostics_without_rerun() -> None:
    session = FakeRuntimeSession()
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run_report()

    assert result["ok"] is True
    assert result["diagnostics"]["execution_mode_router"]["provider"] == "fake-router"
    assert result["progress"] == []
    assert session.calls == [("run_report", None)]


def test_console_output_run_is_serialized_without_workspace_write_fields() -> None:
    session = FakeRuntimeSession()
    session.run_result = SessionRunResult(
        ok=True,
        run_result=RunResult(
            status=RUN_STATUS_COMPLETED,
            execution_mode_decision=ExecutionModeDecision(
                execution_mode=EXECUTION_MODE_CONSOLE_OUTPUT,
                reason="Answer in console.",
                provider_name="fake-router",
                provider_calls_made=1,
            ),
            console_output="safe answer",
            executor_provider="fake-executor",
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run()

    assert result["ok"] is True
    assert result["execution_mode"] == EXECUTION_MODE_CONSOLE_OUTPUT
    assert result["console_output"] == "safe answer"
    assert result["modified_files"] == []
    assert result["created_files"] == []
    assert result["promoted_files"] == []
