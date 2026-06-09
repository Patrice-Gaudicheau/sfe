"""Local stdio MCP server for SFE."""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from sfe.runtime_session import RuntimeSession
from sfe_tui.backends import backend_by_name

from .tools import SfeMcpToolHandlers, create_tool_handlers


def create_default_runtime_session(*, cwd: Path | None = None) -> RuntimeSession:
    return RuntimeSession(
        backend=backend_by_name("direct"),
        cwd=cwd,
    )


def create_server(session: RuntimeSession | None = None) -> FastMCP:
    handlers = create_tool_handlers(session or create_default_runtime_session())
    server = FastMCP("SFE MCP", json_response=True)
    register_tools(server, handlers)
    return server


def register_tools(server: FastMCP, handlers: SfeMcpToolHandlers) -> None:
    registry = handlers.registry()

    @server.tool(name="sfe_set_target_directory")
    def sfe_set_target_directory(path: str) -> dict[str, object]:
        """Select the local SFE target directory for this session."""
        return registry["sfe_set_target_directory"](path)

    @server.tool(name="sfe_set_task")
    def sfe_set_task(task: str) -> dict[str, object]:
        """Set the current SFE task for this session."""
        return registry["sfe_set_task"](task)

    @server.tool(name="sfe_run")
    def sfe_run() -> dict[str, object]:
        """Run the current SFE task through RuntimeSession."""
        return registry["sfe_run"]()

    @server.tool(name="sfe_run_report")
    def sfe_run_report() -> dict[str, object]:
        """Return diagnostics for the previous SFE run."""
        return registry["sfe_run_report"]()

    @server.tool(name="sfe_workspace_status")
    def sfe_workspace_status() -> dict[str, object]:
        """Return current SFE workspace and worktree status."""
        return registry["sfe_workspace_status"]()


def run_stdio() -> None:
    create_server().run(transport="stdio")
