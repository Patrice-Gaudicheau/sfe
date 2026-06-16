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
            _serialize_run_issue(issue)
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
        **_serialize_multi_pass_top_level(result),
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
        "real_loop": _serialize_real_loop_summary(result),
        "warnings": list(result.warnings),
        "action_hint": _run_action_hint(result),
        "progress": [serialize_progress_event(event) for event in progress_events],
    }
    if include_diagnostics:
        data["diagnostics"] = _serialize_run_diagnostics(result)
    return data


def _serialize_run_issue(issue: Any) -> dict[str, Any]:
    serialized = {
        "category": issue.category,
        "reason": issue.reason,
        "path": issue.path,
    }
    diagnostics = getattr(issue, "diagnostics", None)
    if issue.category == "workspace_write_executor" and isinstance(diagnostics, dict):
        serialized["diagnostics"] = _safe_workspace_write_executor_diagnostics(
            diagnostics
        )
    return serialized


def _safe_workspace_write_executor_diagnostics(
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    install_guidance = diagnostics.get("install_guidance")
    if isinstance(install_guidance, tuple | list):
        safe["install_guidance"] = [
            item for item in install_guidance if isinstance(item, str)
        ]
    configured_value = diagnostics.get("configured_value")
    if isinstance(configured_value, str):
        safe["configured_value"] = configured_value
    supported_values = diagnostics.get("supported_values")
    if isinstance(supported_values, tuple | list):
        safe["supported_values"] = [
            item for item in supported_values if isinstance(item, str)
        ]
    executor_name = diagnostics.get("executor_name")
    if isinstance(executor_name, str):
        safe["executor_name"] = executor_name
    for key in (
        "expected_path",
        "validation_reason",
        "no_changes_reason",
    ):
        value = diagnostics.get(key)
        if isinstance(value, str):
            safe[key] = _safe_diagnostic_value(value)
    for key in (
        "expected_paths",
        "expected_placeholder_paths",
        "actual_changed_paths",
        "precreated_expected_paths",
        "untouched_placeholder_paths",
    ):
        value = diagnostics.get(key)
        if isinstance(value, tuple | list):
            safe[key] = [
                _safe_diagnostic_value(item)
                for item in value[:40]
                if isinstance(item, str)
            ]
    filesystem_diagnostics = diagnostics.get("diagnostics")
    if isinstance(filesystem_diagnostics, dict):
        safe["filesystem_executor"] = _safe_filesystem_diagnostics(
            filesystem_diagnostics
        )
    return safe


def _safe_filesystem_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key in (
        "executor_name",
        "return_code",
        "stdout_length",
        "stderr_length",
        "stdout_preview",
        "stderr_preview",
        "elapsed_ms",
    ):
        if key in diagnostics:
            safe[key] = _safe_diagnostic_value(diagnostics[key])
    metadata = diagnostics.get("metadata")
    if isinstance(metadata, dict):
        safe["metadata"] = {
            key: _safe_diagnostic_value(value)
            for key, value in metadata.items()
            if key
            in {
                "expected_paths",
                "expected_placeholder_paths",
                "actual_changed_paths",
                "precreated_expected_paths",
                "untouched_placeholder_paths",
                "no_changes_reason",
                "context_paths",
            }
        }
    return safe


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
        "multi_pass": False,
        "multi_pass_status": None,
        "passes_total": 0,
        "passes_completed": 0,
        "failed_pass_id": None,
        "failed_pass_issue": None,
        "created_files_by_pass": {},
        "promoted_files_by_pass": {},
        "all_promoted_files": [],
        "safe_resume_possible": False,
        "multi_pass_passes": [],
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
        "real_loop": None,
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
                "clean": not bool(status.changed_files),
                "changed_files_count": len(status.changed_files),
                "changed_files": list(status.changed_files),
                "repository_root_label": safe_path_label(status.source_path),
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
    serialized = {
        "category": issue.category,
        "reason": issue.reason,
        "path": issue.path,
    }
    diagnostics = getattr(issue, "diagnostics", None)
    if diagnostics is not None:
        serialized["diagnostics"] = _safe_diagnostic_mapping(diagnostics)
    return serialized


def _serialize_multi_pass_top_level(result: RunResult) -> dict[str, Any]:
    summary = result.multi_pass_summary
    if summary is None:
        return {
            "multi_pass": False,
            "multi_pass_status": None,
            "passes_total": 0,
            "passes_completed": 0,
            "failed_pass_id": None,
            "failed_pass_issue": None,
            "created_files_by_pass": {},
            "promoted_files_by_pass": {},
            "all_promoted_files": [],
            "safe_resume_possible": False,
            "multi_pass_passes": [],
        }
    return {
        "multi_pass": summary.enabled,
        "multi_pass_status": summary.status,
        "passes_total": summary.passes_total,
        "passes_completed": summary.passes_completed,
        "failed_pass_id": summary.failed_pass_id,
        "failed_pass_issue": _serialize_multi_pass_issue(summary.failed_pass_issue),
        "created_files_by_pass": {
            key: list(value)
            for key, value in (summary.created_files_by_pass or {}).items()
        },
        "promoted_files_by_pass": {
            key: list(value)
            for key, value in (summary.promoted_files_by_pass or {}).items()
        },
        "all_promoted_files": list(summary.all_promoted_files),
        "safe_resume_possible": summary.safe_resume_possible,
        "multi_pass_project_summary": summary.project_summary,
        "multi_pass_passes": [
            {
                "id": result.pass_id,
                "title": result.title,
                "status": result.status,
                "allowed_files": list(result.allowed_files),
                "created_files": list(result.created_files),
                "promoted_files": list(result.promoted_files),
                "patch_paths": list(result.patch_paths),
                "full_content_provided_files": list(
                    result.full_content_provided_files
                ),
                "full_file_replacement_eligible_files": list(
                    result.full_file_replacement_eligible_files
                ),
                "full_file_replacement_used_files": list(
                    result.full_file_replacement_used_files
                ),
                "issue": _serialize_multi_pass_issue(result.issue),
                "provider_diagnostics": (
                    _serialize_executor_response_diagnostics_mapping(
                        result.provider_diagnostics
                    )
                    if result.provider_diagnostics is not None
                    else None
                ),
                "fallback_diagnostics": (
                    _safe_diagnostic_mapping(result.fallback_diagnostics)
                    if result.fallback_diagnostics is not None
                    else None
                ),
            }
            for result in summary.pass_results
        ],
    }


def _serialize_real_loop_summary(result: RunResult) -> dict[str, Any] | None:
    summary = getattr(result, "real_loop_summary", None)
    if summary is None:
        return None
    return {
        "enabled": bool(getattr(summary, "enabled", False)),
        "real_loop_status": getattr(summary, "real_loop_status", None),
        "attempts_total": getattr(summary, "attempts_total", 0),
        "max_iterations": getattr(summary, "max_iterations", 0),
        "llm_verifier_verdict": getattr(summary, "llm_verifier_verdict", None),
        "retry_worthwhile": getattr(summary, "retry_worthwhile", None),
        "stop_reason": getattr(summary, "stop_reason", None),
        "progress_since_previous_iteration": getattr(
            summary,
            "progress_since_previous_iteration",
            None,
        ),
        "detected_issues": [
            _safe_diagnostic_value(item)
            for item in tuple(getattr(summary, "detected_issues", ()) or ())
            if isinstance(item, str)
        ],
        "executor_retry_task": _safe_diagnostic_value(
            getattr(summary, "executor_retry_task", None)
        ),
        "verifier_provider": getattr(summary, "verifier_provider", None),
        "verifier_model": getattr(summary, "verifier_model", None),
        "reason": _safe_diagnostic_value(getattr(summary, "reason", None)),
        "iterations": [
            _serialize_real_loop_iteration(iteration)
            for iteration in tuple(getattr(summary, "iterations", ()) or ())
        ],
    }


def _serialize_real_loop_iteration(iteration: object) -> dict[str, Any]:
    return {
        "iteration_index": getattr(iteration, "iteration_index", 0),
        "run_status": getattr(iteration, "run_status", None),
        "execution_mode": getattr(iteration, "execution_mode", None),
        "changed_files": list(getattr(iteration, "changed_files", ()) or ()),
        "promoted_files": list(getattr(iteration, "promoted_files", ()) or ()),
        "llm_verifier_verdict": getattr(iteration, "llm_verifier_verdict", None),
        "retry_worthwhile": getattr(iteration, "retry_worthwhile", None),
        "progress_since_previous_iteration": getattr(
            iteration,
            "progress_since_previous_iteration",
            None,
        ),
        "repeated_failure": getattr(iteration, "repeated_failure", None),
        "failure_category": getattr(iteration, "failure_category", None),
        "detected_issues": [
            _safe_diagnostic_value(item)
            for item in tuple(getattr(iteration, "detected_issues", ()) or ())
            if isinstance(item, str)
        ],
        "correction_objective": _safe_diagnostic_value(
            getattr(iteration, "correction_objective", None)
        ),
        "executor_retry_task": _safe_diagnostic_value(
            getattr(iteration, "executor_retry_task", None)
        ),
        "files_or_areas_to_focus": [
            _safe_diagnostic_value(item)
            for item in tuple(getattr(iteration, "files_or_areas_to_focus", ()) or ())
            if isinstance(item, str)
        ],
        "reason": _safe_diagnostic_value(getattr(iteration, "reason", None)),
        "stop_reason": getattr(iteration, "stop_reason", None),
    }


def _serialize_multi_pass_issue(issue: object | None) -> dict[str, Any] | None:
    if issue is None:
        return None
    serialized = {
        "category": getattr(issue, "category", None),
        "reason": getattr(issue, "reason", None),
        "path": getattr(issue, "path", None),
        "pass_id": getattr(issue, "pass_id", None),
    }
    diagnostics = getattr(issue, "diagnostics", None)
    if diagnostics is not None:
        serialized["diagnostics"] = diagnostics
    return serialized


def _safe_diagnostic_mapping(diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _safe_diagnostic_value(value)
        for key, value in diagnostics.items()
        if isinstance(key, str)
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
        "patch_proposal": _serialize_patch_proposal_diagnostics(result),
        "executor_response_diagnostics": _serialize_executor_response_diagnostics(
            result
        ),
        "filesystem_executor": _serialize_filesystem_result(result),
    }


def _serialize_filesystem_result(result: RunResult) -> dict[str, Any] | None:
    filesystem_result = getattr(result, "filesystem_result", None)
    if filesystem_result is None:
        return None
    diagnostics = filesystem_result.diagnostics
    return {
        "executor_name": filesystem_result.executor_name,
        "status": filesystem_result.status,
        "changed_paths": list(filesystem_result.changed_paths),
        "error_category": filesystem_result.error_category,
        "diagnostics": {
            "executor_name": diagnostics.executor_name,
            "cwd": diagnostics.cwd,
            "command": list(diagnostics.command),
            "return_code": diagnostics.return_code,
            "stdout_length": diagnostics.stdout_length,
            "stderr_length": diagnostics.stderr_length,
            "stdout_preview": diagnostics.stdout_preview,
            "stderr_preview": diagnostics.stderr_preview,
            "elapsed_ms": diagnostics.elapsed_ms,
            "metadata": _safe_diagnostic_mapping(dict(diagnostics.metadata)),
        },
    }


def _serialize_executor_response_diagnostics(
    result: RunResult,
) -> dict[str, Any] | None:
    patch_result = result.patch_result
    if patch_result is None:
        return None
    diagnostics = patch_result.summary.get("executor_response_diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    return _serialize_executor_response_diagnostics_mapping(diagnostics)


def _serialize_executor_response_diagnostics_mapping(
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    filesystem_diagnostics = diagnostics.get("filesystem_executor")
    if isinstance(filesystem_diagnostics, dict):
        serialized["filesystem_executor"] = _safe_diagnostic_mapping(
            filesystem_diagnostics
        )
    for key in (
        "provider_name",
        "response_object_type",
        "top_level_keys",
        "choices_exists",
        "choices_count",
        "first_choice_keys",
        "finish_reason",
        "message_keys",
        "message_content_exists",
        "message_content_type",
        "message_content_length",
        "output_text_exists",
        "output_text_type",
        "output_text_length",
        "error_exists",
        "error_type",
        "error_keys",
        "status_exists",
        "status_type",
    ):
        if key in diagnostics:
            serialized[key] = _safe_diagnostic_value(diagnostics[key])
    provider_diagnostics = diagnostics.get("provider_diagnostics")
    if isinstance(provider_diagnostics, dict):
        serialized["provider_diagnostics"] = _serialize_provider_diagnostics(
            provider_diagnostics
        )
    timeout_diagnostics = diagnostics.get("provider_timeout_diagnostics")
    if isinstance(timeout_diagnostics, dict):
        serialized["provider_timeout_diagnostics"] = (
            _serialize_provider_timeout_diagnostics(timeout_diagnostics)
        )
    return serialized


def _serialize_provider_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key in (
        "provider",
        "model",
        "returncode",
        "stdout_length",
        "stderr_length",
        "stderr_present",
    ):
        if key in diagnostics:
            serialized[key] = _safe_diagnostic_value(diagnostics[key])
    parser_diagnostics = diagnostics.get("parser_diagnostics")
    if isinstance(parser_diagnostics, dict):
        serialized["parser_diagnostics"] = _serialize_parser_diagnostics(
            parser_diagnostics
        )
    return serialized


def _serialize_parser_diagnostics(diagnostics: dict[str, Any]) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key in (
        "stdout_length",
        "jsonl_line_count",
        "parsed_event_count",
        "invalid_json_line_count",
        "agent_message_count",
        "final_content_present",
        "thread_id_present",
        "usage_present",
    ):
        if key in diagnostics:
            serialized[key] = _safe_diagnostic_value(diagnostics[key])
    event_type_counts = diagnostics.get("event_type_counts")
    if isinstance(event_type_counts, dict):
        serialized["event_type_counts"] = {
            str(key): value
            for key, value in event_type_counts.items()
            if isinstance(key, str) and isinstance(value, int)
        }
    return serialized


def _serialize_provider_timeout_diagnostics(
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    serialized: dict[str, Any] = {}
    for key in (
        "provider",
        "model",
        "role",
        "call_id",
        "timeout_kind",
        "idle_timeout_seconds",
        "elapsed_seconds",
        "provider_output_seen",
        "provider_stdout_chunk_count",
        "last_provider_event_kind",
        "last_provider_event_elapsed_seconds",
    ):
        if key in diagnostics:
            serialized[key] = _safe_diagnostic_value(diagnostics[key])
    return serialized


def _safe_diagnostic_value(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _redact_diagnostic_string(value)
    if isinstance(value, tuple | list):
        return [_safe_diagnostic_value(item) for item in value[:40]]
    return None


def _redact_diagnostic_string(value: str) -> str:
    lowered = value.lower()
    if "sk-" in lowered or "api_key" in lowered or "authorization" in lowered:
        return "[redacted]"
    return value if len(value) <= 120 else value[:117] + "..."


def _serialize_patch_proposal_diagnostics(result: RunResult) -> dict[str, Any] | None:
    diagnostics = result.patch_proposal_diagnostics
    if diagnostics is None:
        return None
    return {
        "raw_output_length": diagnostics.raw_output_length,
        "is_empty": diagnostics.is_empty,
        "starts_with_markdown_fence": diagnostics.starts_with_markdown_fence,
        "contains_fenced_diff": diagnostics.contains_fenced_diff,
        "contains_diff_git_header": diagnostics.contains_diff_git_header,
        "starts_with_diff_git": diagnostics.starts_with_diff_git,
        "diff_git_header_offset": diagnostics.diff_git_header_offset,
        "first_diff_git_header_offset": diagnostics.first_diff_git_header_offset,
        "first_diff_git_header_line_index": (
            diagnostics.first_diff_git_header_line_index
        ),
        "diff_git_header_context_preview": list(
            diagnostics.diff_git_header_context_preview
        ),
        "has_preamble_before_diff": diagnostics.has_preamble_before_diff,
        "preamble_line_count": diagnostics.preamble_line_count,
        "has_trailing_text_after_diff": diagnostics.has_trailing_text_after_diff,
        "contains_old_file_header": diagnostics.contains_old_file_header,
        "contains_new_file_header": diagnostics.contains_new_file_header,
        "contains_hunk_header": diagnostics.contains_hunk_header,
        "looks_like_json": diagnostics.looks_like_json,
        "mentions_selected_paths": list(diagnostics.mentions_selected_paths),
        "looks_like_plain_text_or_markdown": (
            diagnostics.looks_like_plain_text_or_markdown
        ),
        "strict_parse_succeeded": diagnostics.strict_parse_succeeded,
        "strict_parse_issue_reason": diagnostics.strict_parse_issue_reason,
        "fenced_extraction_attempted": diagnostics.fenced_extraction_attempted,
        "fenced_extraction_succeeded": diagnostics.fenced_extraction_succeeded,
        "fenced_extraction_failure_reason": (
            diagnostics.fenced_extraction_failure_reason
        ),
        "raw_segment_extraction_attempted": diagnostics.raw_segment_extraction_attempted,
        "raw_segment_extraction_succeeded": diagnostics.raw_segment_extraction_succeeded,
        "raw_segment_candidate_started": diagnostics.raw_segment_candidate_started,
        "raw_segment_candidate_line_count": diagnostics.raw_segment_candidate_line_count,
        "raw_segment_parse_issue_reason": diagnostics.raw_segment_parse_issue_reason,
        "raw_segment_extraction_failure_reason": (
            diagnostics.raw_segment_extraction_failure_reason
        ),
        "final_extraction_succeeded": diagnostics.final_extraction_succeeded,
        "final_parse_issue_reason": diagnostics.final_parse_issue_reason,
    }


def _run_action_hint(result: RunResult) -> str | None:
    issue = result.issue
    if issue is None:
        return None
    if issue.category == "patch_generation" and issue.reason == "invalid_response":
        return "inspect_run_report_or_retry"
    if issue.category == "workspace_write_executor" and issue.reason == "no_changes":
        return "inspect_run_report_expected_and_actual_paths"
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
        "multi_pass_index",
        "multi_pass_total",
        "multi_pass_id",
    }
    return {key: value for key, value in metadata.items() if key in allowed_keys}
