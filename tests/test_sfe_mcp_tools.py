"""Tests for the local SFE MCP tool layer."""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.contracts import SFEContract  # noqa: E402
from sfe.execution_backend import ExecutionResult  # noqa: E402
from sfe.execution_mode_router import (  # noqa: E402
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
)
from sfe.multipass import (  # noqa: E402
    MultiPassBatchResult,
    MultiPassIssue,
    MultiPassRunSummary,
)
from sfe.patching import PatchSummary  # noqa: E402
from sfe.patch_proposal_diagnostics import PatchProposalDiagnostics  # noqa: E402
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
from sfe_mcp.progress import create_mcp_progress_callback  # noqa: E402
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

    def run(self, progress_callback=None) -> SessionRunResult:
        self.calls.append(("run", None))
        if progress_callback is not None:
            for event in self.run_result.progress_events:
                progress_callback(event)
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
    patch_proposal_diagnostics: PatchProposalDiagnostics | None = None,
    patch_result: ExecutionResult | None = None,
    multi_pass_summary: MultiPassRunSummary | None = None,
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
        patch_proposal_diagnostics=patch_proposal_diagnostics,
        patch_result=patch_result,
        multi_pass_summary=multi_pass_summary,
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


def test_mcp_main_loads_launch_env_before_starting_stdio(tmp_path, monkeypatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("SFE_PROVIDER=ollama\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SFE_PROVIDER", raising=False)

    import sfe_mcp.__main__ as mcp_main
    import sfe_mcp.server as mcp_server

    observed_provider: list[str | None] = []

    def fake_run_stdio() -> None:
        observed_provider.append(os.environ.get("SFE_PROVIDER"))

    monkeypatch.setattr(mcp_server, "run_stdio", fake_run_stdio)

    result = mcp_main.main()

    assert result == 0
    assert observed_provider == ["ollama"]


def test_packaging_includes_top_level_providers_package() -> None:
    pyproject = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())

    packages = set(pyproject["tool"]["setuptools"]["packages"])

    assert "providers" in packages
    assert (PROJECT_ROOT / "providers" / "__init__.py").is_file()


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
        def run(self, progress_callback=None) -> SessionRunResult:
            del progress_callback
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


def test_sfe_run_passes_progress_callback_to_runtime_session() -> None:
    session = FakeRuntimeSession()
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]
    progress_events = []

    result = handlers.sfe_run(progress_events.append)

    assert result["ok"] is True
    assert [event.name for event in progress_events] == ["run_started"]
    assert result["progress"] == [
        {
            "name": "run_started",
            "message": "SFE: run started",
            "metadata": {"candidate_count": 2},
        }
    ]


def test_mcp_progress_callback_reports_safe_progress_messages() -> None:
    class FakeContext:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def report_progress(
            self,
            progress: float,
            total: float | None = None,
            message: str | None = None,
        ) -> None:
            self.calls.append(
                {
                    "progress": progress,
                    "total": total,
                    "message": message,
                }
            )

    async def exercise() -> list[dict[str, object]]:
        context = FakeContext()
        loop = asyncio.get_running_loop()
        callback = create_mcp_progress_callback(context, loop)  # type: ignore[arg-type]
        await asyncio.to_thread(
            callback,
            RunProgressEvent(
                "run_started",
                "SFE: run started",
                {"secret": "SECRET_FILE_CONTENT", "candidate_count": 2},
            ),
        )
        await asyncio.sleep(0)
        return context.calls

    calls = asyncio.run(exercise())

    assert calls == [
        {
            "progress": 1.0,
            "total": None,
            "message": "SFE: run started",
        }
    ]


def test_mcp_progress_callback_sanitizes_non_sfe_messages() -> None:
    class FakeContext:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        async def report_progress(
            self,
            progress: float,
            total: float | None = None,
            message: str | None = None,
        ) -> None:
            self.calls.append(
                {
                    "progress": progress,
                    "total": total,
                    "message": message,
                }
            )

    async def exercise() -> list[dict[str, object]]:
        context = FakeContext()
        loop = asyncio.get_running_loop()
        callback = create_mcp_progress_callback(context, loop)  # type: ignore[arg-type]
        callback(
            RunProgressEvent(
                "provider_detail",
                "SECRET_FILE_CONTENT",
                {"secret": "SECRET_FILE_CONTENT"},
            )
        )
        await asyncio.sleep(0)
        return context.calls

    calls = asyncio.run(exercise())

    assert calls == [
        {
            "progress": 1.0,
            "total": None,
            "message": "SFE: progress",
        }
    ]


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
        "clean": False,
        "changed_files_count": 1,
        "changed_files": ["context.txt"],
        "repository_root_label": str(source),
        "source_branch": "main",
        "worktree_branch": "sfe/session-1",
    }


def test_workspace_status_serializes_original_git_repository_metadata_safely(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    session = FakeRuntimeSession()
    session.workspace_status_result = RuntimeWorkspaceStatus(
        workspace_root=source,
        workspace_session=None,
        status_result=WorkspaceStatusResult(
            ok=True,
            status=WorkspaceStatus(
                git_status_porcelain="",
                git_diff="",
                changed_files=(),
                source_path=source,
                worktree_path=source,
                source_branch="main",
                worktree_branch="main",
            ),
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_workspace_status()

    assert result["ok"] is True
    assert result["mode"] == "original"
    assert result["isolated_session"] is None
    assert result["git_status"] == {
        "available": True,
        "clean": True,
        "changed_files_count": 0,
        "changed_files": [],
        "repository_root_label": str(source),
        "source_branch": "main",
        "worktree_branch": "main",
    }


def test_run_report_includes_diagnostics_without_rerun() -> None:
    session = FakeRuntimeSession()
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run_report()

    assert result["ok"] is True
    assert result["diagnostics"]["execution_mode_router"]["provider"] == "fake-router"
    assert result["progress"] == []
    assert session.calls == [("run_report", None)]


def test_run_report_serializes_safe_patch_proposal_diagnostics() -> None:
    session = FakeRuntimeSession()
    session.report_result = RunReportResult(
        ok=True,
        run_result=make_run_result(
            status=RUN_STATUS_FAILED,
            issue=RunIssue("invalid_patch_proposal", "missing_diff_header"),
            patch_proposal_diagnostics=PatchProposalDiagnostics(
                raw_output_length=142,
                is_empty=False,
                first_non_empty_line="SECRET_FILE_CONTENT",
                starts_with_markdown_fence=True,
                contains_fenced_diff=True,
                contains_diff_git_header=False,
                starts_with_diff_git=False,
                diff_git_header_offset=None,
                first_diff_git_header_offset=None,
                first_diff_git_header_line_index=None,
                diff_git_header_context_preview=(),
                has_preamble_before_diff=False,
                preamble_line_count=0,
                has_trailing_text_after_diff=None,
                contains_old_file_header=True,
                contains_new_file_header=True,
                contains_hunk_header=True,
                looks_like_json=False,
                mentions_selected_paths=("app.py",),
                looks_like_plain_text_or_markdown=False,
            ),
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run_report()

    assert result["ok"] is False
    assert result["issue"] == {
        "category": "invalid_patch_proposal",
        "reason": "missing_diff_header",
        "path": None,
    }
    assert result["diagnostics"]["patch_proposal"] == {
        "raw_output_length": 142,
        "is_empty": False,
        "starts_with_markdown_fence": True,
        "contains_fenced_diff": True,
        "contains_diff_git_header": False,
        "starts_with_diff_git": False,
        "diff_git_header_offset": None,
        "first_diff_git_header_offset": None,
        "first_diff_git_header_line_index": None,
        "diff_git_header_context_preview": [],
        "has_preamble_before_diff": False,
        "preamble_line_count": 0,
        "has_trailing_text_after_diff": None,
        "contains_old_file_header": True,
        "contains_new_file_header": True,
        "contains_hunk_header": True,
        "looks_like_json": False,
        "mentions_selected_paths": ["app.py"],
        "looks_like_plain_text_or_markdown": False,
        "strict_parse_succeeded": False,
        "strict_parse_issue_reason": None,
        "fenced_extraction_attempted": False,
        "fenced_extraction_succeeded": False,
        "fenced_extraction_failure_reason": None,
        "raw_segment_extraction_attempted": False,
        "raw_segment_extraction_succeeded": False,
        "raw_segment_candidate_started": False,
        "raw_segment_candidate_line_count": None,
        "raw_segment_parse_issue_reason": None,
        "raw_segment_extraction_failure_reason": None,
        "final_extraction_succeeded": False,
        "final_parse_issue_reason": None,
    }
    rendered = repr(result)
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "first_non_empty_line" not in rendered


def test_run_report_serializes_safe_executor_response_diagnostics() -> None:
    patch_result = ExecutionResult(
        backend="direct",
        status="patch_failed",
        provider_calls_made=1,
        summary={
            "executor_provider": "codexcli",
            "executor_response_diagnostics": {
                "provider_name": "codexcli",
                "response_object_type": "dict",
                "top_level_keys": ("choices", "codexcli"),
                "choices_exists": True,
                "choices_count": 1,
                "first_choice_keys": ("message",),
                "finish_reason": None,
                "message_keys": ("content",),
                "message_content_exists": True,
                "message_content_type": "str",
                "message_content_length": 0,
                "output_text_exists": False,
                "output_text_type": None,
                "output_text_length": None,
                "error_exists": False,
                "error_type": None,
                "error_keys": (),
                "status_exists": False,
                "status_type": None,
                "stdout": "SECRET stdout payload",
                "stderr": "SECRET stderr payload",
                "provider_diagnostics": {
                    "provider": "openai-codexcli",
                    "model": "gpt-5.5",
                    "returncode": 0,
                    "stdout_length": 0,
                    "stderr_length": 21,
                    "stderr_present": True,
                    "stderr": "SECRET stderr payload",
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
                },
            },
        },
        contract=SFEContract(
            instructions=[],
            task=None,
            context_segments=[],
            protected_segments=[],
        ),
        answer=None,
        error_category="invalid_response",
    )
    session = FakeRuntimeSession()
    session.report_result = RunReportResult(
        ok=True,
        run_result=make_run_result(
            status=RUN_STATUS_FAILED,
            issue=RunIssue("patch_generation", "invalid_response"),
            patch_result=patch_result,
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run_report()

    diagnostics = result["diagnostics"]["executor_response_diagnostics"]
    assert diagnostics["provider_name"] == "codexcli"
    assert diagnostics["message_content_length"] == 0
    assert diagnostics["provider_diagnostics"] == {
        "provider": "openai-codexcli",
        "model": "gpt-5.5",
        "returncode": 0,
        "stdout_length": 0,
        "stderr_length": 21,
        "stderr_present": True,
        "parser_diagnostics": {
            "stdout_length": 0,
            "jsonl_line_count": 0,
            "parsed_event_count": 0,
            "invalid_json_line_count": 0,
            "agent_message_count": 0,
            "final_content_present": False,
            "thread_id_present": False,
            "usage_present": False,
            "event_type_counts": {},
        },
    }
    rendered = repr(result)
    assert "SECRET stdout payload" not in rendered
    assert "SECRET stderr payload" not in rendered
    assert "Protected instructions:" not in rendered
    assert "User task:" not in rendered


def test_run_report_serializes_provider_timeout_diagnostics() -> None:
    patch_result = ExecutionResult(
        backend="direct",
        status="patch_failed",
        provider_calls_made=1,
        summary={
            "executor_provider": "codexcli",
            "executor_response_diagnostics": {
                "provider_name": "codexcli",
                "error_type": "ProviderCallIdleTimeoutError",
                "provider_timeout_diagnostics": {
                    "provider": "openai-codexcli",
                    "model": "gpt-5.4",
                    "role": "executor",
                    "call_id": "call-123",
                    "timeout_kind": "idle",
                    "idle_timeout_seconds": 900,
                    "elapsed_seconds": 901.5,
                    "provider_output_seen": False,
                    "provider_stdout_chunk_count": 0,
                    "last_provider_event_kind": None,
                    "last_provider_event_elapsed_seconds": None,
                    "raw_stdout": "SECRET stdout",
                },
            },
        },
        contract=SFEContract(
            instructions=[],
            task=None,
            context_segments=[],
            protected_segments=[],
        ),
        answer=None,
        error_category="provider_idle_timeout",
    )
    session = FakeRuntimeSession()
    session.report_result = RunReportResult(
        ok=True,
        run_result=make_run_result(
            status=RUN_STATUS_FAILED,
            issue=RunIssue("patch_generation", "provider_idle_timeout"),
            patch_result=patch_result,
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run_report()

    diagnostics = result["diagnostics"]["executor_response_diagnostics"]
    timeout_diagnostics = diagnostics["provider_timeout_diagnostics"]
    assert timeout_diagnostics == {
        "provider": "openai-codexcli",
        "model": "gpt-5.4",
        "role": "executor",
        "call_id": "call-123",
        "timeout_kind": "idle",
        "idle_timeout_seconds": 900,
        "elapsed_seconds": 901.5,
        "provider_output_seen": False,
        "provider_stdout_chunk_count": 0,
        "last_provider_event_kind": None,
        "last_provider_event_elapsed_seconds": None,
    }
    assert "SECRET stdout" not in repr(result)


def test_run_report_serializes_multipass_summary_and_pass_diagnostics() -> None:
    timeout_diagnostics = {
        "provider_name": "codexcli",
        "error_type": "ProviderCallIdleTimeoutError",
        "provider_timeout_diagnostics": {
            "provider": "openai-codexcli",
            "model": "gpt-5.4",
            "role": "executor",
            "call_id": "call-123",
            "timeout_kind": "idle",
            "idle_timeout_seconds": 900,
            "elapsed_seconds": 901.5,
            "provider_output_seen": False,
            "provider_stdout_chunk_count": 0,
            "last_provider_event_kind": None,
            "last_provider_event_elapsed_seconds": None,
            "raw_stdout": "SECRET stdout",
        },
    }
    summary = MultiPassRunSummary(
        enabled=True,
        status="failed",
        project_summary="Mock scaffold",
        passes_total=2,
        passes_completed=1,
        failed_pass_id="templates",
        failed_pass_issue=MultiPassIssue(
            "patch_generation",
            "provider_idle_timeout",
            pass_id="templates",
        ),
        created_files_by_pass={"foundation": ("composer.json",)},
        promoted_files_by_pass={"foundation": ("composer.json",)},
        all_promoted_files=("composer.json",),
        safe_resume_possible=True,
        pass_results=(
            MultiPassBatchResult(
                pass_id="foundation",
                title="Foundation",
                status="completed",
                allowed_files=("composer.json",),
                created_files=("composer.json",),
                promoted_files=("composer.json",),
                patch_paths=("composer.json",),
            ),
            MultiPassBatchResult(
                pass_id="templates",
                title="Templates",
                status="failed",
                allowed_files=("templates/base.html.twig",),
                provider_diagnostics=timeout_diagnostics,
                issue=MultiPassIssue(
                    "patch_generation",
                    "provider_idle_timeout",
                    pass_id="templates",
                ),
            ),
        ),
    )
    session = FakeRuntimeSession()
    session.report_result = RunReportResult(
        ok=True,
        run_result=make_run_result(
            status=RUN_STATUS_FAILED,
            issue=RunIssue("patch_generation", "provider_idle_timeout"),
            multi_pass_summary=summary,
        ),
    )
    handlers = SfeMcpToolHandlers(session)  # type: ignore[arg-type]

    result = handlers.sfe_run_report()

    assert result["multi_pass"] is True
    assert result["multi_pass_status"] == "failed"
    assert result["passes_total"] == 2
    assert result["passes_completed"] == 1
    assert result["failed_pass_id"] == "templates"
    assert result["failed_pass_issue"] == {
        "category": "patch_generation",
        "reason": "provider_idle_timeout",
        "path": None,
        "pass_id": "templates",
    }
    assert result["created_files_by_pass"] == {"foundation": ["composer.json"]}
    assert result["promoted_files_by_pass"] == {"foundation": ["composer.json"]}
    assert result["all_promoted_files"] == ["composer.json"]
    assert result["safe_resume_possible"] is True
    assert result["multi_pass_passes"][1]["provider_diagnostics"][
        "provider_timeout_diagnostics"
    ]["provider"] == "openai-codexcli"
    assert "SECRET stdout" not in repr(result)


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
