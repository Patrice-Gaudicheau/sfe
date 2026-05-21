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
            "  /context           Show safe loaded/selected context metadata",
            "  /files <paths...>  Replace loaded context with text files",
            "  /task <text>       Set the current task",
            "  /dry-run           Build the SFE contract and show safe counts",
            "  /ask               Ask a read-only question using selected context",
            "  /patch             Propose a patch without applying it",
            "  /reset             Clear task, context, and routing; preserve workspace",
            "  /quit, /exit       Exit",
        ]
    )


def safe_workspace_label(workspace_root: Path, launch_cwd: Path | None = None) -> str:
    root = workspace_root.resolve()
    if launch_cwd is not None:
        cwd = launch_cwd.resolve()
        if root == cwd:
            return "."
        try:
            return root.relative_to(cwd).as_posix()
        except ValueError:
            pass
    return root.name or "<workspace>"


def render_workspace_selected(
    workspace_root: Path,
    launch_cwd: Path | None = None,
) -> str:
    return f"Workspace: {safe_workspace_label(workspace_root, launch_cwd)}"


def render_file_selection(results: list[ContextLoadResult]) -> str:
    loaded = sum(1 for result in results if result.loaded)
    skipped = len(results) - loaded
    lines = [
        f"Context files replaced: loaded {loaded}; skipped {skipped}",
    ]
    skipped_reasons = _skipped_reason_counts(results)
    if skipped_reasons:
        lines.append(
            "  skipped reasons: "
            + ", ".join(
                f"{reason} ({_skip_reason_guidance(reason)}): {count}"
                for reason, count in skipped_reasons.items()
            )
        )
    return "\n".join(lines)


def render_task_set() -> str:
    return "Task stored."


def render_reset() -> str:
    return "Session reset. Workspace is preserved."


def render_error(message: str) -> str:
    guidance = {
        "unknown_command": "unknown command; use /help to list commands",
        "missing_task": "missing task; set one with /task <text>",
        "no_context_loaded": "no context loaded; replace context with /files <path>",
        "no_files_provided": "no files provided; use /files <path>",
        "invalid_file_command": "invalid file command; quote paths that contain spaces",
        "workspace_not_selected": "workspace not selected",
        "workspace_not_found": "workspace not found",
        "workspace_not_directory": "workspace path is not a directory",
    }.get(message)
    if guidance is None:
        return f"Error: {message}"
    return f"Error: {message} - {guidance}"


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


def render_context_summary(
    *,
    contract: SFEContract,
    context_files: list[ContextLoadResult],
    latest_result: BackendResult | None,
) -> str:
    if not contract.context_segments:
        return "\n".join(
            [
                "SFE context",
                "  loaded context segments: 0",
                "  empty: no context loaded",
            ]
        )
    warning_by_ref = {
        result.source_ref: result.warning_reason
        for result in context_files
        if result.loaded and result.source_ref and result.warning_reason
    }
    selected_ids = set()
    score_by_id: dict[str, str] = {}
    if latest_result is not None:
        selected_ids = set(latest_result.contract.audit.get("selected_segment_ids") or [])
        score_by_id = dict(
            latest_result.contract.audit.get("router_score_categories_by_segment_id")
            or {}
        )
    lines = [
        "SFE context",
        f"  loaded context segments: {len(contract.context_segments)}",
    ]
    for segment in contract.context_segments:
        warning = warning_by_ref.get(segment.source_ref) or "none"
        score = score_by_id.get(segment.id) or "unrouted"
        selected = "yes" if segment.id in selected_ids else "no"
        lines.append(
            "  "
            + " | ".join(
                [
                    f"id={segment.id}",
                    f"ref={segment.source_ref}",
                    f"chars={segment.approx_size}",
                    f"tokens={segment.approx_tokens}",
                    f"bucket={_context_size_bucket(segment.approx_size)}",
                    f"reducible={_yes_no(segment.reducible)}",
                    f"selected={selected}",
                    f"score={score}",
                    f"warning={warning}",
                ]
            )
        )
    return "\n".join(lines)


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
        f"  warning reasons: {contract.metadata['warning_reason_counts']}",
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
                "  note: local preview only, not an LLM router result",
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
                f"  score categories: {router.score_category_counts}",
                "  note: provider-free lexical preview only, not an LLM router result",
            ]
        )
    return "\n".join(lines)


def render_ask_result(result: BackendResult) -> str:
    lines: list[str] = []
    if result.answer:
        lines.extend(["SFE answer", result.answer])
    else:
        lines.extend(["SFE ask failed", f"  reason: {result.error_category}"])
    audit = result.contract.audit
    lines.extend(
        [
            "SFE ask summary",
            f"  router mode: {audit.get('router_mode')}",
            f"  selected segment count: {audit.get('selected_segment_count')}",
            f"  selected segment ids: {audit.get('selected_segment_ids')}",
            f"  estimated input tokens: {audit.get('estimated_input_tokens')}",
            f"  estimated selected tokens: {audit.get('estimated_selected_tokens')}",
            f"  estimated reduction pct: {audit.get('estimated_reduction_pct')}",
            f"  fallback reason: {audit.get('fallback_reason')}",
            f"  provider calls made: {result.provider_calls_made}",
            "  writes enabled: no",
            "  shell enabled: no",
        ]
    )
    return "\n".join(lines)


def render_patch_result(result: BackendResult) -> str:
    lines: list[str] = []
    if result.answer:
        lines.extend(["Patch proposal only, not applied", result.answer])
    else:
        lines.extend(["SFE patch failed", f"  reason: {result.error_category}"])
    audit = result.contract.audit
    lines.extend(
        [
            "SFE patch summary",
            f"  router mode: {audit.get('router_mode')}",
            f"  selected segment count: {audit.get('selected_segment_count')}",
            f"  selected segment ids: {audit.get('selected_segment_ids')}",
            f"  estimated input tokens: {audit.get('estimated_input_tokens')}",
            f"  estimated selected tokens: {audit.get('estimated_selected_tokens')}",
            f"  estimated reduction pct: {audit.get('estimated_reduction_pct')}",
            f"  fallback reason: {audit.get('fallback_reason')}",
            f"  provider calls made: {result.provider_calls_made}",
            "  writes enabled: no",
            "  shell enabled: no",
            "  patch applied: no",
        ]
    )
    return "\n".join(lines)


def _context_size_bucket(text_chars: int) -> str:
    if text_chars <= 0:
        return "0"
    if text_chars <= 128:
        return "1-128"
    if text_chars <= 512:
        return "129-512"
    if text_chars <= 2_048:
        return "513-2048"
    if text_chars <= 8_192:
        return "2049-8192"
    return "8193+"


def _skipped_reason_counts(results: list[ContextLoadResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if result.loaded:
            continue
        reason = result.reason or "read_error"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _skip_reason_guidance(reason: str) -> str:
    return {
        "not_a_file": "unsupported file input; provide a file path, not a directory",
        "outside_workspace": "path is outside the selected workspace",
        "file_too_large": "file is above the local size limit",
        "binary_or_non_text": "file is not UTF-8 text",
        "secret_like_file": "file looks secret-like and was not loaded",
        "read_error": "file could not be read",
    }.get(reason, "input was not loaded")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
