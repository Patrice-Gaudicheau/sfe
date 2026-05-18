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
    lines = [
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
    if result.execution_preview is not None:
        preview = result.execution_preview
        lines.extend(
            [
                "DirectBackend execution preview",
                f"  backend name: {preview.backend_name}",
                f"  selector mode: {preview.selector_mode}",
                f"  protected instructions: {preview.protected_instruction_count}",
                f"  task present: {preview.task_present}",
                f"  selected segment count: {preview.selected_segment_count}",
                f"  selected segment ids: {preview.selected_segment_ids}",
                f"  selected context characters: {preview.selected_context_char_count}",
                f"  selected context token estimate: {preview.selected_context_token_estimate}",
                f"  total context characters: {preview.total_context_char_count}",
                f"  total context token estimate: {preview.total_context_token_estimate}",
                f"  estimated reduction pct: {preview.estimated_reduction_pct}",
                f"  fallback reason: {preview.fallback_reason}",
                f"  provider calls made: {preview.provider_calls_made}",
                f"  writes enabled: {str(preview.writes_enabled).lower()}",
                f"  shell enabled: {str(preview.shell_enabled).lower()}",
                "  note: deterministic preview only, not an LLM router result",
            ]
        )
    if result.router_preview is not None:
        router = result.router_preview
        lines.extend(
            [
                "DirectBackend router preview",
                f"  router mode: {router.router_mode}",
                f"  router available: {router.router_available}",
                f"  router unavailable reason: {router.router_unavailable_reason}",
                f"  router provider calls made: {router.router_provider_calls_made}",
                f"  input segments: {router.input_segment_count}",
                f"  eligible segments: {router.eligible_segment_count}",
                f"  selected segments: {router.selected_segment_count}",
                f"  selected segment ids: {router.selected_segment_ids}",
                f"  estimated input tokens: {router.estimated_input_tokens}",
                f"  estimated selected tokens: {router.estimated_selected_tokens}",
                f"  estimated reduction pct: {router.estimated_reduction_pct}",
                f"  fallback reason: {router.fallback_reason}",
                "  note: real SFE router not invoked; provider-backed router integration is a later phase",
            ]
        )
    return "\n".join(lines)
