"""Unit-testable SFE MCP tool handlers."""

from __future__ import annotations

from collections.abc import Callable
import threading
from typing import Any

from sfe.runtime_session import RuntimeSession

from .serializers import (
    safe_path_label,
    serialize_run_result,
    serialize_session_error,
    serialize_workspace_status,
)


V1_TOOL_NAMES = (
    "sfe_set_target_directory",
    "sfe_set_task",
    "sfe_run",
    "sfe_run_report",
    "sfe_workspace_status",
)


class SfeMcpToolHandlers:
    def __init__(self, session: RuntimeSession) -> None:
        self.session = session
        self._run_lock = threading.Lock()

    def registry(self) -> dict[str, Callable[..., dict[str, Any]]]:
        return {
            "sfe_set_target_directory": self.sfe_set_target_directory,
            "sfe_set_task": self.sfe_set_task,
            "sfe_run": self.sfe_run,
            "sfe_run_report": self.sfe_run_report,
            "sfe_workspace_status": self.sfe_workspace_status,
        }

    def sfe_set_target_directory(self, path: str) -> dict[str, Any]:
        result = self.session.set_target_directory(path)
        return {
            "ok": result.ok,
            "status": "selected" if result.ok else "failed",
            "error_category": result.error_category,
            "workspace_label": safe_path_label(result.workspace_root),
        }

    def sfe_set_task(self, task: str) -> dict[str, Any]:
        result = self.session.set_task(task)
        return {
            "ok": result.ok,
            "status": "stored" if result.ok else "failed",
            "error_category": result.error_category,
            "task_present": bool(result.task.strip()) if result.ok else False,
        }

    def sfe_run(self) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return serialize_session_error("run_in_progress")
        try:
            result = self.session.run()
            if result.run_result is None:
                return serialize_session_error(result.error_category)
            return serialize_run_result(
                result.run_result,
                progress_events=result.progress_events,
                include_diagnostics=False,
            )
        finally:
            self._run_lock.release()

    def sfe_run_report(self) -> dict[str, Any]:
        result = self.session.run_report()
        if result.run_result is None:
            return serialize_session_error(result.error_category)
        return serialize_run_result(
            result.run_result,
            progress_events=(),
            include_diagnostics=True,
        )

    def sfe_workspace_status(self) -> dict[str, Any]:
        status = self.session.workspace_status()
        return serialize_workspace_status(
            workspace_root=status.workspace_root,
            workspace_session=status.workspace_session,
            status_result=status.status_result,
        )


def create_tool_handlers(session: RuntimeSession) -> SfeMcpToolHandlers:
    return SfeMcpToolHandlers(session)
