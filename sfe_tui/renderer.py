"""Pure ANSI/text rendering for the SFE-aware TUI."""

from __future__ import annotations

from pathlib import Path

from .backends import BackendResult
from .contracts import ContextLoadResult, SFEContract


def render_help() -> str:
    return "\n".join(
        [
            "SFE TUI commands:",
            "  /help              Show this help",
            "  /pwd               Show selected workspace",
            "  /status            Show safe TUI state and disabled capabilities",
            "  /files <paths...>  Add context source files or directories",
            "  /task <text>       Set the current task",
            "  /dry-run           Build the SFE contract and show safe counts",
            "  /quit, /exit       Exit",
        ]
    )


def render_workspace_selected(workspace_root: Path) -> str:
    return f"Workspace: {workspace_root}"


def render_file_selection(results: list[ContextLoadResult]) -> str:
    loaded = sum(1 for result in results if result.loaded)
    skipped = len(results) - loaded
    return f"Context sources loaded: {loaded}; skipped: {skipped}"


def render_task_set() -> str:
    return "Task stored."


def render_error(message: str) -> str:
    return f"Error: {message}"


def render_status(
    *,
    workspace_selected: bool,
    loaded_context_files: int,
    skipped_context_files: int,
    task_present: bool,
    backend_name: str,
) -> str:
    return "\n".join(
        [
            "SFE TUI status",
            f"  workspace selected: {workspace_selected}",
            f"  loaded context files: {loaded_context_files}",
            f"  skipped context files: {skipped_context_files}",
            f"  task present: {task_present}",
            f"  backend: {backend_name}",
            "  provider calls made: 0",
            "  writes enabled: no",
            "  shell enabled: no",
        ]
    )


def render_dry_run_summary(contract: SFEContract, result: BackendResult) -> str:
    audit = result.contract.audit
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
            f"  requested files: {contract.metadata['requested_file_count']}",
            f"  loaded files: {contract.metadata['loaded_context_file_count']}",
            f"  skipped files: {contract.metadata['skipped_file_count']}",
            f"  skipped reasons: {contract.metadata['skipped_reason_counts']}",
            f"  total approximate characters: {contract.metadata['total_approx_context_chars']}",
            f"  total approximate tokens: {contract.metadata['total_approx_context_tokens']}",
            f"  size buckets: {contract.metadata['context_size_buckets']}",
            f"  selector mode: {audit.get('selector_mode')}",
            f"  eligible segments: {audit.get('eligible_segment_count')}",
            f"  selected segments: {audit.get('selected_segment_count')}",
            f"  estimated input tokens: {audit.get('estimated_input_tokens')}",
            f"  estimated selected tokens: {audit.get('estimated_selected_tokens')}",
            f"  estimated reduction pct: {audit.get('estimated_reduction_pct')}",
            f"  fallback reason: {audit.get('fallback_reason')}",
            f"  selected segment ids: {audit.get('selected_segment_ids')}",
            f"  provider calls made: {result.provider_calls_made}",
            f"  status: {result.status}",
        ]
    )
