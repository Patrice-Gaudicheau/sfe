"""Pure ANSI/text rendering for the SFE-aware TUI."""

from __future__ import annotations

from pathlib import Path

from .backends import BackendResult
from .contracts import SFEContract


def render_help() -> str:
    return "\n".join(
        [
            "SFE TUI commands:",
            "  /help              Show this help",
            "  /pwd               Show selected workspace",
            "  /files <paths...>  Add context source files or directories",
            "  /task <text>       Set the current task",
            "  /dry-run           Build the SFE contract and show safe counts",
            "  /quit, /exit       Exit",
        ]
    )


def render_workspace_selected(workspace_root: Path) -> str:
    return f"Workspace: {workspace_root}"


def render_file_selection(count: int) -> str:
    return f"Context sources selected: {count}"


def render_task_set() -> str:
    return "Task stored."


def render_error(message: str) -> str:
    return f"Error: {message}"


def render_dry_run_summary(contract: SFEContract, result: BackendResult) -> str:
    return "\n".join(
        [
            "SFE dry-run summary",
            f"  workspace selected: {contract.metadata['workspace_root_present']}",
            f"  task present: {contract.task is not None}",
            f"  context segments: {len(contract.context_segments)}",
            f"  protected segments: {len(contract.protected_segments)}",
            f"  backend selected: {result.backend}",
            f"  reducible segments: {contract.metadata['reducible_segment_count']}",
            f"  protected instructions: {contract.metadata['protected_instruction_count']}",
            f"  provider calls made: {result.provider_calls_made}",
            f"  status: {result.status}",
        ]
    )
