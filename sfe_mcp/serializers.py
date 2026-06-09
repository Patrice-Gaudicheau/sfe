"""Safe structured serializers for SFE MCP tool results."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sfe.run_pipeline import RunProgressEvent, RunResult
from sfe.workspace_isolation import (
    WorkspaceSession,
    WorkspaceStatusResult,
)


SESSION_ERROR_ISSUE_CATEGORY = "runtime_session"


def safe_path_label(path: Path | None) -> str | None:
    if path is None:
        return None
    root = path.resolve()
    home = Path.home().resolve()
    try:
        if root == home:
            return "~"
        return f"~/{root.relative_to(home).as_posix()}"
    except ValueError:
        return root.as_posix() or "<workspace>"


def serialize_run_result(
    result: RunResult,
    *,
    progress_events: tuple[RunProgressEvent, ...] = (),
    include_diagnostics: bool = False,
) -> dict[str, Any]:
    execution_mode_decision = result.execution_mode_decision
    issue = result.issue
    summary = result.patch_summary
    data: dict[str, Any] = {
        "ok": result.status == "completed",
        "status": result.status,
        "execution_mode": (
            execution_mode_decision.execution_mode
            if execution_mode_decision is not None
            else None
        ),
        "issue": (
            {
                "category": issue.category,
                "reason": issue.reason,
                "path": issue.path,
            }
            if issue is not None
            else None
        ),
        "console_output": result.console_output,
        "selected_source_refs": list(result.selected_source_refs),
        "changed_files": list(result.changed_files),
        "modified_files": list(summary.modified_paths) if summary else [],
        "created_files": list(summary.created_paths) if summary else [],
        "promoted_files": list(result.promoted_files),
        "patch_generated": result.patch_generated,
        "patch_applied": result.patch_applied,
        "promotion": {
            "status": result.promotion_status,
            "applied": result.promotion_applied,
            "issue": _serialize_promotion_issue(result),
        },
        "validation": {
            "patch_summary": _serialize_patch_summary(result),
            "hunk_count_normalization_applied": (
                result.patch_hunk_count_normalization.applied
                if result.patch_hunk_count_normalization is not None
                else None
            ),
        },
        "workspace": {
            "active_workspace_label": safe_path_label(result.active_workspace),
            "worktree_created": result.worktree_created,
            "worktree_session_id": (
                result.workspace_session.session_id
                if result.workspace_session is not None
                else None
            ),
        },
        "git": {
            "auto_initialized": result.git_auto_init,
            "initial_commit_hash": result.git_initial_commit_hash,
            "init_warning": result.git_init_warning,
        },
        "executor_provider": result.executor_provider,
        "warnings": list(result.warnings),
        "action_hint": _run_action_hint(result),
        "progress": [serialize_progress_event(event) for event in progress_events],
    }
    if include_diagnostics:
        data["diagnostics"] = _serialize_run_diagnostics(result)
    return data


def serialize_session_error(error_category: str | None) -> dict[str, Any]:
    reason = error_category or "unknown_error"
    return {
        "ok": False,
        "status": "failed",
        "execution_mode": None,
        "error_category": reason,
        "issue": {
            "category": SESSION_ERROR_ISSUE_CATEGORY,
            "reason": reason,
            "path": None,
        },
        "selected_source_refs": [],
        "changed_files": [],
        "modified_files": [],
        "created_files": [],
        "promoted_files": [],
        "promotion": {
            "status": "skipped",
            "applied": False,
            "issue": None,
        },
        "validation": {
            "patch_summary": None,
            "hunk_count_normalization_applied": None,
        },
        "workspace": {
            "active_workspace_label": None,
            "worktree_created": False,
            "worktree_session_id": None,
        },
        "git": {
            "auto_initialized": False,
            "initial_commit_hash": None,
            "init_warning": None,
        },
        "warnings": [],
        "action_hint": _session_error_action_hint(reason),
        "progress": [],
    }


def serialize_progress_event(event: RunProgressEvent) -> dict[str, Any]:
    return {
        "name": event.name,
        "message": _safe_progress_message(event.message),
        "metadata": _safe_progress_metadata(event.metadata),
    }


def serialize_workspace_status(
    *,
    workspace_root: Path | None,
    workspace_session: WorkspaceSession | None,
    status_result: WorkspaceStatusResult | None,
) -> dict[str, Any]:
    status = status_result.status if status_result is not None else None
    issue = status_result.issue if status_result is not None else None
    return {
        "ok": status_result.ok if status_result is not None else True,
        "mode": "isolated" if workspace_session is not None else "original",
        "active_workspace_label": safe_path_label(workspace_root),
        "isolated_session": (
            _serialize_workspace_session(workspace_session)
            if workspace_session is not None
            else None
        ),
        "git_status": (
            {
                "available": True,
                "changed_files": list(status.changed_files),
                "source_branch": status.source_branch,
                "worktree_branch": status.worktree_branch,
            }
            if status is not None
            else {"available": False}
        ),
        "issue": (
            {"category": issue.category, "reason": issue.reason}
            if issue is not None
            else None
        ),
    }


def _serialize_workspace_session(session: WorkspaceSession) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "source_workspace_label": safe_path_label(session.source_path),
        "worktree_label": safe_path_label(session.worktree_path),
        "source_branch": session.source_branch,
        "worktree_branch": session.worktree_branch,
        "backend": session.backend_name,
        "created_by": session.created_by,
    }


def _serialize_patch_summary(result: RunResult) -> dict[str, Any] | None:
    summary = result.patch_summary
    if summary is None:
        return None
    return {
        "paths": list(summary.paths),
        "file_count": summary.file_count,
        "hunk_count": summary.hunk_count,
        "lines_added": summary.lines_added,
        "lines_removed": summary.lines_removed,
        "modified_paths": list(summary.modified_paths),
        "created_paths": list(summary.created_paths),
        "refused_paths": list(summary.refused_paths),
        "refused_reasons": list(summary.refused_reasons),
    }


def _serialize_promotion_issue(result: RunResult) -> dict[str, Any] | None:
    issue = result.promotion_issue
    if issue is None:
        return None
    return {
        "category": issue.category,
        "reason": issue.reason,
        "path": issue.path,
    }


def _serialize_run_diagnostics(result: RunResult) -> dict[str, Any]:
    discovery = result.discovery_result
    dry_run = result.dry_run_result
    execution_mode_decision = result.execution_mode_decision
    return {
        "execution_mode_router": {
            "provider": (
                execution_mode_decision.provider_name
                if execution_mode_decision is not None
                else None
            ),
            "model": (
                execution_mode_decision.model
                if execution_mode_decision is not None
                else None
            ),
            "calls_made": (
                execution_mode_decision.provider_calls_made
                if execution_mode_decision is not None
                else 0
            ),
            "confidence": (
                execution_mode_decision.confidence
                if execution_mode_decision is not None
                else None
            ),
            "reason": (
                execution_mode_decision.reason
                if execution_mode_decision is not None
                else None
            ),
        },
        "discovery": {
            "mode": discovery.discovery_mode if discovery is not None else None,
            "candidate_count": discovery.candidate_count
            if discovery is not None
            else 0,
            "loaded_candidate_count": discovery.loaded_candidate_count
            if discovery is not None
            else 0,
            "router_provider": discovery.router_provider_name
            if discovery is not None
            else None,
            "stop_reason": discovery.stop_reason if discovery is not None else None,
        },
        "routing": {
            "selected_token_estimate": _selected_token_estimate(dry_run),
            "estimated_reduction_pct": _estimated_reduction_pct(dry_run),
        },
    }


def _run_action_hint(result: RunResult) -> str | None:
    issue = result.issue
    if issue is None:
        return None
    if issue.category == "patch_generation" and issue.reason == "invalid_response":
        return "inspect_run_report_or_retry"
    if issue.category == "context_discovery":
        return "inspect_discovery_configuration_or_retry"
    if issue.category == "routing":
        return "refine_task_or_target_directory"
    if issue.category == "promotion":
        return "inspect_workspace_status_and_source_changes"
    if issue.category == "unsupported_execution_mode":
        return "use_another_local_surface_for_external_actions"
    return "inspect_run_report"


def _session_error_action_hint(reason: str) -> str:
    hints = {
        "workspace_not_selected": "call_sfe_set_target_directory",
        "missing_task": "call_sfe_set_task",
        "no_previous_run": "call_sfe_run_first",
        "run_in_progress": "retry_sfe_run_after_current_run_finishes",
    }
    return hints.get(reason, "inspect_error_category")


def _selected_token_estimate(result: object | None) -> int | None:
    preview = getattr(result, "execution_preview", None)
    if preview is None:
        return None
    return getattr(preview, "selected_context_token_estimate", None)


def _estimated_reduction_pct(result: object | None) -> float | None:
    preview = getattr(result, "execution_preview", None)
    if preview is None:
        return None
    return getattr(preview, "estimated_reduction_pct", None)


def _safe_progress_message(message: str) -> str:
    collapsed = " ".join(str(message or "").split())
    return collapsed if collapsed.startswith("SFE:") else "SFE: progress"


def _safe_progress_metadata(metadata: dict[str, object]) -> dict[str, object]:
    allowed_keys = {
        "execution_mode",
        "provider_name",
        "model",
        "candidate_count",
        "workspace_map_count",
        "scanned_file_count",
        "router_provider_name",
        "stop_reason",
        "selected_context_count",
        "selected_segment_count",
        "estimated_token_reduction",
        "patch_file_count",
        "patch_hunk_count",
        "promoted_file_count",
    }
    return {key: value for key, value in metadata.items() if key in allowed_keys}
