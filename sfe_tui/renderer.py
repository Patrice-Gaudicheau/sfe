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
    workspace_label: str | None = None,
    loaded_context_files: int,
    skipped_context_files: int,
    loaded_context_segments: int,
    task_present: bool,
    backend_name: str,
    executor_provider_name: str | None = None,
    latest_result: BackendResult | None = None,
) -> str:
    latest_result_present = latest_result is not None
    latest_result_kind = latest_result.status if latest_result is not None else "none"
    latest_provider_calls = (
        latest_result.provider_calls_made if latest_result is not None else 0
    )
    lines = [
        "SFE TUI status",
        f"  workspace selected: {workspace_selected}",
        f"  workspace: {workspace_label or 'not selected'}",
        f"  loaded context files: {loaded_context_files}",
        f"  skipped context files: {skipped_context_files}",
        f"  loaded context segments: {loaded_context_segments}",
        f"  task present: {task_present}",
        f"  backend: {backend_name}",
    ]
    if executor_provider_name:
        lines.append(f"  executor provider: {executor_provider_name}")
    lines.extend(
        [
            f"  latest result present: {_yes_no(latest_result_present)}",
            f"  latest result kind: {latest_result_kind}",
            f"  latest provider calls made: {latest_provider_calls}",
            "  writes enabled: no",
            "  shell enabled: no",
            "  patch application enabled: no",
        ]
    )
    return "\n".join(lines)


def render_context_summary(
    *,
    contract: SFEContract,
    context_files: list[ContextLoadResult],
    latest_result: BackendResult | None,
) -> str:
    skipped_count = sum(1 for result in context_files if not result.loaded)
    skipped_reasons = _skipped_reason_counts(context_files)
    latest_selected_ids: list[str] = []
    if latest_result is not None:
        latest_selected_ids = list(
            latest_result.contract.audit.get("selected_segment_ids") or []
        )
    if not contract.context_segments:
        return "\n".join(
            [
                "SFE context",
                "  loaded context segments: 0",
                f"  skipped context files: {skipped_count}",
                f"  skipped reasons: {_format_reason_counts(skipped_reasons)}",
                f"  latest selected segment ids: {latest_selected_ids}",
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
        selected_ids = set(latest_selected_ids)
        score_by_id = dict(
            latest_result.contract.audit.get("router_score_categories_by_segment_id")
            or {}
        )
    lines = [
        "SFE context",
        f"  loaded context segments: {len(contract.context_segments)}",
        f"  skipped context files: {skipped_count}",
        f"  skipped reasons: {_format_reason_counts(skipped_reasons)}",
        f"  latest selected segment ids: {latest_selected_ids}",
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
    selected_ids = list(audit.get("selected_segment_ids") or [])
    selected_refs = _selected_source_refs(result.contract, selected_ids)
    task_present = contract.task is not None
    context_loaded = bool(contract.context_segments)
    selected_count = int(audit.get("selected_segment_count") or 0)
    fallback_reason = audit.get("fallback_reason")
    lines = [
        "SFE dry-run summary",
        "Preflight state",
        f"  workspace selected: {_yes_no(bool(contract.metadata['workspace_root_present']))}",
        f"  task present: {_yes_no(task_present)}",
        f"  context loaded: {_yes_no(context_loaded)}",
        f"  requested files: {contract.metadata['requested_file_count']}",
        f"  loaded context segments: {len(contract.context_segments)}",
        f"  loaded files: {contract.metadata['loaded_context_file_count']}",
        f"  skipped files: {contract.metadata['skipped_file_count']}",
        f"  total approximate tokens: {contract.metadata['total_approx_context_tokens']}",
        "Local routing preview",
        f"  selector mode: {_display_value(audit.get('selector_mode'))}",
        "  note: local preview only, not an LLM router result",
        f"  eligible segments: {_display_value(audit.get('eligible_segment_count'))}",
        f"  selected segments: {selected_count}",
        f"  selected segment ids: {_format_string_list(selected_ids)}",
        f"  selected source refs: {_format_string_list(selected_refs)}",
        f"  estimated input tokens: {_display_value(audit.get('estimated_input_tokens'))}",
        f"  estimated selected tokens: {_display_value(audit.get('estimated_selected_tokens'))}",
        f"  estimated reduction pct: {_display_value(audit.get('estimated_reduction_pct'))}",
        f"  fallback reason: {_display_value(fallback_reason)}",
    ]
    if not task_present:
        lines.append("  action: missing task; set one with /task <text>")
    elif not context_loaded:
        lines.append("  action: no context loaded; replace context with /files <path>")
    elif selected_count == 0:
        lines.append(
            "  action: routing found no relevant context segments; revise the task or loaded files"
        )

    lines.extend(
        [
            "Selected context",
            f"  selected segment ids: {_format_string_list(selected_ids)}",
            f"  selected source refs: {_format_string_list(selected_refs)}",
            f"  selected context token estimate: {_display_value(audit.get('estimated_selected_tokens'))}",
            "Skipped/rejected context",
            f"  skipped files: {contract.metadata['skipped_file_count']}",
            f"  skipped reasons: {_format_reason_counts(contract.metadata['skipped_reason_counts'])}",
            f"  warning reasons: {_format_reason_counts(contract.metadata['warning_reason_counts'])}",
            "Safety guarantees",
            f"  backend: {result.backend}",
            f"  provider calls made: {result.provider_calls_made}",
            "  executor/provider called: no",
            "  writes disabled",
            "  shell disabled",
            "  patch application disabled",
            f"  status: {result.status}",
        ]
    )
    return "\n".join(lines)


def render_ask_result(result: BackendResult) -> str:
    audit = result.contract.audit
    selected_ids = list(audit.get("selected_segment_ids") or [])
    selected_refs = _selected_source_refs(result.contract, selected_ids)
    task_present = result.contract.task is not None
    context_loaded = bool(result.contract.context_segments)
    selected_count = int(audit.get("selected_segment_count") or 0)
    lines: list[str] = [
        "SFE ask",
        "Preflight state",
        f"  task present: {_yes_no(task_present)}",
        f"  context loaded: {_yes_no(context_loaded)}",
        f"  loaded context segments: {len(result.contract.context_segments)}",
        "Local routing",
        f"  mode: {_display_value(audit.get('router_mode'))}",
        f"  selected segments: {selected_count}",
        f"  selected segment ids: {_format_string_list(selected_ids)}",
        f"  selected source refs: {_format_string_list(selected_refs)}",
        f"  estimated input tokens: {_display_value(audit.get('estimated_input_tokens'))}",
        f"  estimated selected tokens: {_display_value(audit.get('estimated_selected_tokens'))}",
        f"  estimated reduction pct: {_display_value(audit.get('estimated_reduction_pct'))}",
        f"  fallback reason: {_display_value(audit.get('fallback_reason'))}",
        "Provider call",
        f"  provider: {_display_value(result.summary.get('executor_provider'))}",
        f"  status: {_ask_provider_status(result)}",
        f"  provider calls made: {result.provider_calls_made}",
    ]
    if result.answer:
        lines.extend(["SFE answer", result.answer])
    else:
        lines.extend(
            [
                "SFE ask failed",
                f"  reason: {_display_value(result.error_category)}",
                f"  action: {_failure_guidance(result.error_category)}",
            ]
        )
    lines.extend(
        [
            "Safety state",
            "  writes disabled",
            "  shell disabled",
            "  patch application disabled",
        ]
    )
    return "\n".join(lines)


def render_patch_result(result: BackendResult) -> str:
    audit = result.contract.audit
    selected_ids = list(audit.get("selected_segment_ids") or [])
    selected_refs = _selected_source_refs(result.contract, selected_ids)
    task_present = result.contract.task is not None
    context_loaded = bool(result.contract.context_segments)
    selected_count = int(audit.get("selected_segment_count") or 0)
    lines: list[str] = [
        "SFE patch",
        "Preflight state",
        f"  task present: {_yes_no(task_present)}",
        f"  context loaded: {_yes_no(context_loaded)}",
        f"  loaded context segments: {len(result.contract.context_segments)}",
        "Local routing",
        f"  mode: {_display_value(audit.get('router_mode'))}",
        f"  selected segments: {selected_count}",
        f"  selected segment ids: {_format_string_list(selected_ids)}",
        f"  selected source refs: {_format_string_list(selected_refs)}",
        f"  estimated input tokens: {_display_value(audit.get('estimated_input_tokens'))}",
        f"  estimated selected tokens: {_display_value(audit.get('estimated_selected_tokens'))}",
        f"  estimated reduction pct: {_display_value(audit.get('estimated_reduction_pct'))}",
        f"  fallback reason: {_display_value(audit.get('fallback_reason'))}",
        "Provider call",
        f"  provider: {_display_value(result.summary.get('executor_provider'))}",
        f"  status: {_patch_provider_status(result)}",
        f"  provider calls made: {result.provider_calls_made}",
        "Patch application",
        "  patch proposal only",
        "  not applied",
        "  no files were modified",
        "  patch application disabled",
    ]
    if result.answer:
        lines.extend(["Patch proposal only, not applied", result.answer])
    else:
        lines.extend(
            [
                "SFE patch failed",
                f"  reason: {_display_value(result.error_category)}",
                f"  action: {_failure_guidance(result.error_category)}",
            ]
        )
    lines.extend(
        [
            "Safety state",
            "  writes disabled",
            "  shell disabled",
            "  patch application disabled",
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


def _format_reason_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{reason}: {count}" for reason, count in counts.items())


def _format_string_list(values: list[str]) -> str:
    if not values:
        return "none"
    return ", ".join(values)


def _display_value(value: object) -> str:
    if value is None:
        return "unknown"
    return str(value)


def _selected_source_refs(contract: SFEContract, selected_ids: list[str]) -> list[str]:
    selected = set(selected_ids)
    return [
        segment.source_ref
        for segment in contract.context_segments
        if segment.id in selected
    ]


def _ask_provider_status(result: BackendResult) -> str:
    if result.answer:
        return "answer received"
    if result.error_category:
        return f"failed ({result.error_category})"
    return "no answer returned"


def _patch_provider_status(result: BackendResult) -> str:
    if result.answer:
        return "proposal received"
    if result.error_category:
        return f"failed ({result.error_category})"
    return "no proposal returned"


def _failure_guidance(error_category: str | None) -> str:
    return {
        "missing_task": "set a task with /task <text>",
        "no_context_loaded": "replace context with /files <path>",
        "no_selected_context": (
            "routing found no relevant context segments; revise the task or loaded files"
        ),
        "provider_not_configured": (
            "this command needs a configured executor/provider"
        ),
        "timeout": "provider call timed out; retry later or check provider settings",
        "provider_error": "provider call failed; check provider configuration and retry",
        "provider_configuration_error": (
            "set SFE_PROVIDER to openai-compatible, openai, lemonade, alibaba, or anthropic"
        ),
        "provider_not_supported": "selected provider is not supported by the TUI executor yet",
        "invalid_response": "provider returned an invalid response",
    }.get(error_category, "check the command state and retry")


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
