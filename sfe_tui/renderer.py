"""Pure ANSI/text rendering for the SFE-aware TUI."""

from __future__ import annotations

from pathlib import Path

from sfe.contracts import ContextLoadResult, SFEContract
from sfe.discovery import DiscoveryResult
from sfe.execution_backend import ExecutionResult
from sfe.patching import PatchApplyResult, PatchIssue, PatchSummary
from sfe.run_pipeline import RunIssue, RunProgressEvent, RunResult
from sfe.router_review import JsonReviewDecision
from sfe.workspace_isolation import (
    WorkspaceCleanupResult,
    WorkspaceGCResult,
    WorkspaceIssue,
    WorkspaceSession,
    WorkspaceStatusResult,
)

from .patch_review import PatchReviewDecision


SFE_OUTPUT_COLOR = "\033[96m"
ANSI_RESET = "\033[0m"


def color_sfe_output(text: str, *, enabled: bool) -> str:
    if not enabled or not text:
        return text
    return f"{SFE_OUTPUT_COLOR}{text}{ANSI_RESET}"


def render_run_progress_event(event: RunProgressEvent) -> str:
    message = " ".join(str(event.message or "").split())
    if not message.startswith("SFE:"):
        return f"SFE: {event.name.replace('_', ' ')}"
    return message


def render_help() -> str:
    return "\n".join(
        [
            "SFE TUI commands:",
            "  /help, /?          Show this help",
            "  /status            Show current TUI state",
            "  /task <text>       Set the current task",
            "  /run               Resolve the task and show concise output",
            "  /reset             Clear task, context, discovery, and routing; preserve workspace",
            "  /advanced          Show advanced diagnostic commands",
            "  /quit, /exit       Exit",
        ]
    )


def render_advanced_help() -> str:
    return "\n".join(
        [
            "SFE TUI advanced commands:",
            "  /directory         Show selected workspace directory",
            "  /run-report        Show diagnostics for the previous run without re-running",
            "  /context           Show selected context metadata",
            "  /ask               Ask a read-only question using selected context",
            "  /workspace-status  Show original/isolated workspace state",
        ]
    )


def safe_workspace_label(workspace_root: Path, launch_cwd: Path | None = None) -> str:
    root = workspace_root.resolve()
    del launch_cwd
    home = Path.home().resolve()
    try:
        if root == home:
            return "~"
        return f"~/{root.relative_to(home).as_posix()}"
    except ValueError:
        return root.as_posix() or "<workspace>"


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
        "discovery_not_run": "run /discover after /task before this command",
        "no_context_loaded": "no context loaded; run /discover or use /files <path>",
        "no_files_provided": "no files provided; use /files <path>",
        "invalid_file_command": "invalid file command; quote paths that contain spaces",
        "workspace_not_selected": "workspace not selected",
        "workspace_not_found": "workspace not found",
        "workspace_not_directory": "workspace path is not a directory",
        "no_pending_patch": "run /patch first",
        "workspace_already_isolated": "cleanup the active worktree before creating another",
        "no_isolated_workspace": "run /isolate first",
        "invalid_gc_command": "use /gc-worktrees or /gc-worktrees --clean",
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
    router_provider_name: str | None = None,
    discovery_provider_name: str | None = None,
    executor_provider_name: str | None = None,
    latest_result: ExecutionResult | None = None,
    discovery_result: DiscoveryResult | None = None,
    pending_patch_summary: PatchSummary | None = None,
) -> str:
    latest_result_present = latest_result is not None
    latest_result_kind = latest_result.status if latest_result is not None else "none"
    latest_provider_calls = (
        latest_result.provider_calls_made if latest_result is not None else 0
    )
    discovery_present = discovery_result is not None
    lines = [
        "SFE TUI status",
        f"  workspace selected: {workspace_selected}",
        f"  workspace: {workspace_label or 'not selected'}",
        f"  loaded context files: {loaded_context_files}",
        f"  skipped context files: {skipped_context_files}",
        f"  loaded context segments: {loaded_context_segments}",
        f"  task present: {task_present}",
        f"  discovery result present: {_yes_no(discovery_present)}",
        f"  discovered candidates: {_discovery_count(discovery_result, 'candidate_count')}",
        f"  discovered loaded candidates: {_discovery_count(discovery_result, 'loaded_candidate_count')}",
        f"  backend: {backend_name}",
        f"  router provider: {_display_value(router_provider_name)}",
        f"  discovery provider: {_display_value(discovery_provider_name)}",
        f"  executor provider: {_display_value(executor_provider_name)}",
    ]
    lines.extend(
        [
            f"  latest result present: {_yes_no(latest_result_present)}",
            f"  latest result kind: {latest_result_kind}",
            f"  latest provider calls made: {latest_provider_calls}",
            f"  pending patch: {_yes_no(pending_patch_summary is not None)}",
            f"  pending patch files: {_patch_summary_count(pending_patch_summary, 'file_count')}",
            f"  pending patch hunks: {_patch_summary_count(pending_patch_summary, 'hunk_count')}",
            "  writes: routed /run workspace_write or explicit /apply-patch only",
            "  shell enabled: no",
            "  patch application: routed /run workspace_write or explicit /apply-patch",
        ]
    )
    return "\n".join(lines)


def render_isolate_success(
    session: WorkspaceSession,
    *,
    active_workspace: Path,
    launch_cwd: Path | None = None,
) -> str:
    return "\n".join(
        [
            "SFE isolate",
            "  status: created",
            f"  session id: {session.session_id}",
            f"  source workspace: {safe_workspace_label(session.source_path, launch_cwd)}",
            f"  active workspace: {safe_workspace_label(active_workspace, launch_cwd)}",
            f"  worktree path: {safe_workspace_label(session.worktree_path, launch_cwd)}",
            f"  source branch: {session.source_branch}",
            f"  worktree branch: {session.worktree_branch}",
            "  promotion: disabled; use /review-worktree for router validation",
        ]
    )


def render_isolate_failure(issue: WorkspaceIssue | None) -> str:
    return "\n".join(
        [
            "SFE isolate",
            "  status: failed",
            f"  error category: {_workspace_issue_category(issue)}",
            f"  reason: {_workspace_issue_reason(issue)}",
            "  active workspace unchanged",
        ]
    )


def render_workspace_mode_status(
    *,
    workspace_root: Path | None,
    workspace_session: WorkspaceSession | None,
    status_result: WorkspaceStatusResult | None,
    launch_cwd: Path | None = None,
) -> str:
    lines = [
        "SFE workspace-status",
        f"  mode: {'isolated' if workspace_session is not None else 'original'}",
        f"  active workspace: {safe_workspace_label(workspace_root, launch_cwd) if workspace_root is not None else 'not selected'}",
    ]
    if workspace_session is None:
        lines.append("  isolated session: none")
        if status_result is None:
            return "\n".join(lines)
        if not status_result.ok or status_result.status is None:
            lines.extend(
                [
                    f"  status available: no",
                    f"  error category: {_workspace_issue_category(status_result.issue)}",
                    f"  reason: {_workspace_issue_reason(status_result.issue)}",
                ]
            )
            return "\n".join(lines)
        lines.extend(
            [
                "  status available: yes",
                f"  changed files: {_format_string_list(list(status_result.status.changed_files))}",
                f"  git status lines: {len(status_result.status.git_status_porcelain.splitlines())}",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            f"  session id: {workspace_session.session_id}",
            f"  source workspace: {safe_workspace_label(workspace_session.source_path, launch_cwd)}",
            f"  worktree path: {safe_workspace_label(workspace_session.worktree_path, launch_cwd)}",
            f"  source branch: {workspace_session.source_branch}",
            f"  worktree branch: {workspace_session.worktree_branch}",
        ]
    )
    if status_result is None:
        return "\n".join(lines)
    if not status_result.ok or status_result.status is None:
        lines.extend(
            [
                f"  status available: no",
                f"  error category: {_workspace_issue_category(status_result.issue)}",
                f"  reason: {_workspace_issue_reason(status_result.issue)}",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "  status available: yes",
            f"  changed files: {_format_string_list(list(status_result.status.changed_files))}",
            f"  git status lines: {len(status_result.status.git_status_porcelain.splitlines())}",
        ]
    )
    return "\n".join(lines)


def render_worktree_diff(status_result: WorkspaceStatusResult) -> str:
    lines = [
        "SFE worktree-diff",
    ]
    if not status_result.ok or status_result.status is None:
        lines.extend(
            [
                "  status: failed",
                f"  error category: {_workspace_issue_category(status_result.issue)}",
                f"  reason: {_workspace_issue_reason(status_result.issue)}",
            ]
        )
        return "\n".join(lines)
    status = status_result.status
    diff = _truncate_text(status.git_diff, max_chars=4000)
    lines.extend(
        [
            "  status: ok",
            f"  changed files: {_format_string_list(list(status.changed_files))}",
            f"  git status lines: {len(status.git_status_porcelain.splitlines())}",
            "Git status",
            status.git_status_porcelain.rstrip() or "  clean",
            "Git diff",
            diff.rstrip() or "  no diff",
        ]
    )
    return "\n".join(lines)


def render_run_result_normal(result: RunResult) -> str:
    if result.console_output:
        return result.console_output

    execution_mode = _run_execution_mode(result)
    if execution_mode == "external_action":
        lines = [
            "SFE run",
            f"  status: {result.status}",
            "  execution mode: external_action",
            "  external action: not implemented",
        ]
        if result.issue is not None:
            lines.extend(_run_issue_lines(result.issue))
        return "\n".join(lines)

    summary = result.patch_summary
    lines = [
        "SFE run",
        f"  status: {result.status}",
        f"  execution mode: {_display_value(execution_mode)}",
        f"  multi-pass: {_yes_no(result.multi_pass_summary is not None and result.multi_pass_summary.enabled)}",
        f"  promoted files: {_format_string_list(list(result.promoted_files))}",
        f"  modified relative paths: {_format_string_list(list(summary.modified_paths) if summary else [])}",
        f"  created relative paths: {_format_string_list(list(summary.created_paths) if summary else [])}",
    ]
    if result.issue is not None:
        lines.extend(_run_issue_lines(result.issue))
        hint = _run_issue_hint(result)
        if hint is not None:
            lines.append(f"  hint: {hint}")
    return "\n".join(lines)


def _run_issue_hint(result: RunResult) -> str | None:
    issue = result.issue
    if issue is None:
        return None
    if issue.category == "patch_generation" and issue.reason == "invalid_response":
        return (
            "executor returned an invalid or empty response; use /run-report "
            "for diagnostics or retry /run"
        )
    if (
        issue.category == "context_discovery"
        and issue.reason == "discovery_router_provider_not_supported"
    ):
        provider_name = None
        if result.discovery_result is not None:
            provider_name = result.discovery_result.router_provider_name
        provider_label = provider_name or "the configured provider"
        return (
            f"configured discovery provider {provider_label} is not supported; "
            "set SFE_PROVIDER_DISCOVERY to openai, lemonade, alibaba, or another "
            "discovery-supported provider"
        )
    diagnostics = result.patch_proposal_diagnostics
    if (
        issue.category == "invalid_patch_proposal"
        and issue.reason == "missing_diff_header"
        and diagnostics is not None
        and diagnostics.looks_like_json
    ):
        return (
            "executor returned JSON edit instructions instead of a unified diff; "
            "use /run-report for details or retry /run"
        )
    return None


def render_run_result(result: RunResult, *, launch_cwd: Path | None = None) -> str:
    return render_run_result_debug(result, launch_cwd=launch_cwd)


def render_run_result_debug(result: RunResult, *, launch_cwd: Path | None = None) -> str:
    discovery = result.discovery_result
    dry_run = result.dry_run_result
    summary = result.patch_summary
    session = result.workspace_session
    issue = result.issue
    execution_mode_decision = result.execution_mode_decision
    worktree_path = (
        safe_workspace_label(session.worktree_path, launch_cwd)
        if session is not None
        else None
    )
    lines = [
        "SFE run",
        f"  status: {result.status}",
        f"  execution mode: {_display_value(execution_mode_decision.execution_mode if execution_mode_decision is not None else None)}",
        f"  execution-mode router provider: {_display_value(execution_mode_decision.provider_name if execution_mode_decision is not None else None)}",
        f"  execution-mode router model: {_display_value(execution_mode_decision.model if execution_mode_decision is not None else None)}",
        f"  execution-mode router calls made: {execution_mode_decision.provider_calls_made if execution_mode_decision is not None else 0}",
        f"  execution-mode router confidence: {_display_value(execution_mode_decision.confidence if execution_mode_decision is not None else None)}",
        f"  execution-mode router reason: {_display_value(execution_mode_decision.reason if execution_mode_decision is not None else None)}",
        f"  worktree session: {_display_value(session.session_id if session is not None else None)}",
        f"  worktree path: {_display_value(worktree_path)}",
        f"  worktree created: {_yes_no(result.worktree_created)}",
        f"  git auto-init: {_yes_no(result.git_auto_init)}",
        f"  git initial commit: {result.git_initial_commit_hash or 'none'}",
        f"  git init warning: {result.git_init_warning or 'none'}",
        f"  discovery mode: {_display_value(discovery.discovery_mode if discovery is not None else None)}",
        f"  discovery candidates: {discovery.candidate_count if discovery is not None else 0}",
        f"  selected source refs: {_format_string_list(list(result.selected_source_refs))}",
        f"  selected context tokens: {_display_value(_run_selected_tokens(dry_run))}",
        f"  estimated reduction pct: {_display_value(_run_reduction_pct(dry_run))}",
        f"  executor provider: {_display_value(result.executor_provider)}",
        f"  patch generated: {_yes_no(result.patch_generated)}",
        f"  patch applied: {_yes_no(result.patch_applied)}",
        f"  multi-pass: {_yes_no(result.multi_pass_summary is not None and result.multi_pass_summary.enabled)}",
        f"  promotion: {result.promotion_status}",
        f"  promoted files: {_format_string_list(list(result.promoted_files))}",
        f"  changed files: {_format_string_list(list(result.changed_files))}",
        f"  modified relative paths: {_format_string_list(list(summary.modified_paths) if summary else [])}",
        f"  created relative paths: {_format_string_list(list(summary.created_paths) if summary else [])}",
        f"  warnings: {_format_string_list(list(result.warnings))}",
    ]
    if (
        execution_mode_decision is not None
        and execution_mode_decision.invalid_response_preview
    ):
        lines.append(
            "  execution-mode router invalid response preview: "
            + execution_mode_decision.invalid_response_preview
        )
    if result.promotion_issue is not None:
        lines.extend(
            [
                f"  promotion issue category: {result.promotion_issue.category}",
                f"  promotion issue reason: {result.promotion_issue.reason}",
            ]
        )
        if result.promotion_issue.path is not None:
            lines.append(f"  promotion issue path: {result.promotion_issue.path}")
    if result.multi_pass_summary is not None:
        lines.extend(_render_multi_pass_summary(result.multi_pass_summary))
    if issue is not None:
        lines.extend(
            [
                f"  issue category: {issue.category}",
                f"  issue reason: {issue.reason}",
            ]
        )
        if issue.path is not None:
            lines.append(f"  issue path: {issue.path}")
    if issue is not None and issue.hunk_accounting is not None:
        lines.extend(_render_hunk_accounting_diagnostics(issue.hunk_accounting))
    if result.patch_hunk_count_normalization is not None:
        lines.extend(
            _render_hunk_count_normalization(
                result.patch_hunk_count_normalization
            )
        )
    if result.patch_proposal_diagnostics is not None:
        diagnostics = result.patch_proposal_diagnostics
        file_headers = (
            diagnostics.contains_old_file_header
            and diagnostics.contains_new_file_header
        )
        lines.extend(
            [
                f"  patch proposal output length: {diagnostics.raw_output_length}",
                f"  patch proposal empty: {_yes_no(diagnostics.is_empty)}",
                "  patch proposal first line: "
                f"{_display_value(diagnostics.first_non_empty_line)}",
                "  patch proposal starts with markdown fence: "
                f"{_yes_no(diagnostics.starts_with_markdown_fence)}",
                "  patch proposal contains fenced diff: "
                f"{_yes_no(diagnostics.contains_fenced_diff)}",
                "  patch proposal contains diff header: "
                f"{_yes_no(diagnostics.contains_diff_git_header)}",
                "  patch proposal first diff header offset: "
                f"{_display_value(diagnostics.first_diff_git_header_offset)}",
                "  patch proposal first diff header line: "
                f"{_display_value(diagnostics.first_diff_git_header_line_index)}",
                f"  patch proposal contains file headers: {_yes_no(file_headers)}",
                "  patch proposal contains hunk header: "
                f"{_yes_no(diagnostics.contains_hunk_header)}",
                "  patch proposal strict parse succeeded: "
                f"{_yes_no(diagnostics.strict_parse_succeeded)}",
                "  patch proposal strict parse issue: "
                f"{_display_value(diagnostics.strict_parse_issue_reason)}",
                "  patch proposal fenced extraction attempted: "
                f"{_yes_no(diagnostics.fenced_extraction_attempted)}",
                "  patch proposal fenced extraction succeeded: "
                f"{_yes_no(diagnostics.fenced_extraction_succeeded)}",
                "  patch proposal fenced extraction failure: "
                f"{_display_value(diagnostics.fenced_extraction_failure_reason)}",
                "  patch proposal raw segment extraction attempted: "
                f"{_yes_no(diagnostics.raw_segment_extraction_attempted)}",
                "  patch proposal raw segment extraction succeeded: "
                f"{_yes_no(diagnostics.raw_segment_extraction_succeeded)}",
                "  patch proposal raw segment candidate started: "
                f"{_yes_no(diagnostics.raw_segment_candidate_started)}",
                "  patch proposal raw segment candidate lines: "
                f"{_display_value(diagnostics.raw_segment_candidate_line_count)}",
                "  patch proposal raw segment parse issue: "
                f"{_display_value(diagnostics.raw_segment_parse_issue_reason)}",
                "  patch proposal raw segment extraction failure: "
                f"{_display_value(diagnostics.raw_segment_extraction_failure_reason)}",
                "  patch proposal final extraction succeeded: "
                f"{_yes_no(diagnostics.final_extraction_succeeded)}",
                "  patch proposal final parse issue: "
                f"{_display_value(diagnostics.final_parse_issue_reason)}",
                "  patch proposal looks like JSON: "
                f"{_yes_no(diagnostics.looks_like_json)}",
                "  patch proposal mentions selected paths: "
                f"{_format_string_list(list(diagnostics.mentions_selected_paths))}",
                "  patch proposal looks like plain text: "
                f"{_yes_no(diagnostics.looks_like_plain_text_or_markdown)}",
            ]
        )
    response_diagnostics = _executor_response_diagnostics(result)
    if response_diagnostics is not None:
        lines.extend(_render_executor_response_diagnostics(response_diagnostics))
    if result.console_output:
        lines.extend(["SFE console output", result.console_output])
    lines.extend(
        [
            "  router review: not run",
            "  worktree review: not run",
            "  tests: not run",
            "  lint: not run",
            "  diff: not shown",
        ]
    )
    return "\n".join(lines)


def _render_multi_pass_summary(summary: object) -> list[str]:
    pass_results = tuple(getattr(summary, "pass_results", ()) or ())
    lines = [
        "SFE multi-pass",
        f"  status: {_display_value(getattr(summary, 'status', None))}",
        f"  project summary: {_display_value(getattr(summary, 'project_summary', None))}",
        f"  passes completed: {getattr(summary, 'passes_completed', 0)}/{getattr(summary, 'passes_total', 0)}",
        f"  failed pass id: {_display_value(getattr(summary, 'failed_pass_id', None))}",
        "  safe resume possible: "
        f"{_yes_no(bool(getattr(summary, 'safe_resume_possible', False)))}",
        "  all promoted files: "
        f"{_format_string_list(list(getattr(summary, 'all_promoted_files', ()) or ())) }",
    ]
    failed_issue = getattr(summary, "failed_pass_issue", None)
    if failed_issue is not None:
        lines.extend(
            [
                "  failed pass issue category: "
                f"{_display_value(getattr(failed_issue, 'category', None))}",
                "  failed pass issue reason: "
                f"{_display_value(getattr(failed_issue, 'reason', None))}",
            ]
        )
        if getattr(failed_issue, "path", None) is not None:
            lines.append(
                "  failed pass issue path: "
                f"{_display_value(getattr(failed_issue, 'path', None))}"
            )
    for index, pass_result in enumerate(pass_results, start=1):
        lines.extend(
            [
                f"  pass {index}/{getattr(summary, 'passes_total', 0)} id: {_display_value(getattr(pass_result, 'pass_id', None))}",
                f"  pass {index} title: {_display_value(getattr(pass_result, 'title', None))}",
                f"  pass {index} status: {_display_value(getattr(pass_result, 'status', None))}",
                "  pass "
                f"{index} allowed files: {_format_string_list(list(getattr(pass_result, 'allowed_files', ()) or ())) }",
                "  pass "
                f"{index} promoted files: {_format_string_list(list(getattr(pass_result, 'promoted_files', ()) or ())) }",
                "  pass "
                f"{index} created files: {_format_string_list(list(getattr(pass_result, 'created_files', ()) or ())) }",
            ]
        )
        issue = getattr(pass_result, "issue", None)
        if issue is not None:
            lines.extend(
                [
                    "  pass "
                    f"{index} issue category: {_display_value(getattr(issue, 'category', None))}",
                    "  pass "
                    f"{index} issue reason: {_display_value(getattr(issue, 'reason', None))}",
                ]
            )
            if getattr(issue, "path", None) is not None:
                lines.append(
                    "  pass "
                    f"{index} issue path: {_display_value(getattr(issue, 'path', None))}"
                )
        diagnostics = getattr(pass_result, "provider_diagnostics", None)
        if isinstance(diagnostics, dict):
            timeout_diagnostics = diagnostics.get("provider_timeout_diagnostics")
            if isinstance(timeout_diagnostics, dict):
                lines.extend(_render_provider_timeout_diagnostics(timeout_diagnostics))
    return lines


def _render_hunk_accounting_diagnostics(diagnostics: object) -> list[str]:
    lines = [
        "SFE hunk accounting diagnostics",
        f"  message: {_display_value(getattr(diagnostics, 'message', None))}",
        f"  hunk path: {_display_value(getattr(diagnostics, 'path', None))}",
        f"  hunk header: {_display_value(getattr(diagnostics, 'hunk_header', None))}",
        "  declared old start: "
        f"{_display_value(getattr(diagnostics, 'declared_old_start', None))}",
        "  declared old count: "
        f"{_display_value(getattr(diagnostics, 'declared_old_count', None))}",
        "  declared new start: "
        f"{_display_value(getattr(diagnostics, 'declared_new_start', None))}",
        "  declared new count: "
        f"{_display_value(getattr(diagnostics, 'declared_new_count', None))}",
        "  actual old-side count: "
        f"{_display_value(getattr(diagnostics, 'actual_old_side_count', None))}",
        "  actual new-side count: "
        f"{_display_value(getattr(diagnostics, 'actual_new_side_count', None))}",
        "  actual context line count: "
        f"{_display_value(getattr(diagnostics, 'actual_context_line_count', None))}",
        "  actual removed line count: "
        f"{_display_value(getattr(diagnostics, 'actual_removed_line_count', None))}",
        "  actual added line count: "
        f"{_display_value(getattr(diagnostics, 'actual_added_line_count', None))}",
        "  looks like new-file hunk: "
        f"{_yes_no(bool(getattr(diagnostics, 'looks_like_new_file', False)))}",
        "  old file header is /dev/null: "
        f"{_yes_no(bool(getattr(diagnostics, 'old_file_header_is_dev_null', False)))}",
        "  hunk body only added lines: "
        f"{_yes_no(bool(getattr(diagnostics, 'hunk_body_only_added_lines', False)))}",
        "  LLM-correctable in principle: "
        f"{_yes_no(bool(getattr(diagnostics, 'llm_correctable_in_principle', False)))}",
    ]
    return lines


def _render_hunk_count_normalization(diagnostics: object) -> list[str]:
    changes = tuple(getattr(diagnostics, "changes", ()) or ())
    lines = [
        "SFE hunk count normalization",
        f"  applied: {_yes_no(bool(getattr(diagnostics, 'applied', False)))}",
        f"  message: {_display_value(getattr(diagnostics, 'message', None))}",
        f"  normalized hunks: {len(changes)}",
    ]
    for change in changes:
        lines.extend(
            [
                f"  normalized hunk path: {_display_value(getattr(change, 'path', None))}",
                "  original hunk header: "
                f"{_display_value(getattr(change, 'original_hunk_header', None))}",
                "  normalized hunk header: "
                f"{_display_value(getattr(change, 'normalized_hunk_header', None))}",
                "  declared old/new count: "
                f"{_display_value(getattr(change, 'declared_old_count', None))}/"
                f"{_display_value(getattr(change, 'declared_new_count', None))}",
                "  actual old/new count: "
                f"{_display_value(getattr(change, 'actual_old_side_count', None))}/"
                f"{_display_value(getattr(change, 'actual_new_side_count', None))}",
            ]
        )
    return lines


def _executor_response_diagnostics(result: RunResult) -> dict[str, object] | None:
    patch_result = result.patch_result
    if patch_result is None:
        return None
    diagnostics = patch_result.summary.get("executor_response_diagnostics")
    return diagnostics if isinstance(diagnostics, dict) else None


def _render_executor_response_diagnostics(
    diagnostics: dict[str, object],
) -> list[str]:
    timeout_diagnostics = diagnostics.get("provider_timeout_diagnostics")
    if isinstance(timeout_diagnostics, dict) and "response_object_type" not in diagnostics:
        return [
            "SFE executor response diagnostics",
            f"  executor response provider: {_display_value(diagnostics.get('provider_name'))}",
            f"  executor response error type: {_display_value(diagnostics.get('error_type'))}",
            *_render_provider_timeout_diagnostics(timeout_diagnostics),
        ]
    lines = [
        "SFE executor response diagnostics",
        f"  executor response provider: {_display_value(diagnostics.get('provider_name'))}",
        "  executor response object type: "
        f"{_display_value(diagnostics.get('response_object_type'))}",
        "  executor response top-level keys: "
        f"{_format_diagnostic_list(diagnostics.get('top_level_keys'))}",
        "  executor response choices exists: "
        f"{_display_bool(diagnostics.get('choices_exists'))}",
        "  executor response choices count: "
        f"{_display_value(diagnostics.get('choices_count'))}",
        "  executor response first choice keys: "
        f"{_format_diagnostic_list(diagnostics.get('first_choice_keys'))}",
        f"  executor response finish reason: {_display_value(diagnostics.get('finish_reason'))}",
        "  executor response message keys: "
        f"{_format_diagnostic_list(diagnostics.get('message_keys'))}",
        "  executor response message content exists: "
        f"{_display_bool(diagnostics.get('message_content_exists'))}",
        "  executor response message content type: "
        f"{_display_value(diagnostics.get('message_content_type'))}",
        "  executor response message content length: "
        f"{_display_value(diagnostics.get('message_content_length'))}",
        "  executor response output_text exists: "
        f"{_display_bool(diagnostics.get('output_text_exists'))}",
        "  executor response output_text type: "
        f"{_display_value(diagnostics.get('output_text_type'))}",
        "  executor response output_text length: "
        f"{_display_value(diagnostics.get('output_text_length'))}",
        "  executor response error exists: "
        f"{_display_bool(diagnostics.get('error_exists'))}",
        f"  executor response error type: {_display_value(diagnostics.get('error_type'))}",
        "  executor response error keys: "
        f"{_format_diagnostic_list(diagnostics.get('error_keys'))}",
        "  executor response status exists: "
        f"{_display_bool(diagnostics.get('status_exists'))}",
        f"  executor response status type: {_display_value(diagnostics.get('status_type'))}",
    ]
    if isinstance(timeout_diagnostics, dict):
        lines.extend(_render_provider_timeout_diagnostics(timeout_diagnostics))
    return lines


def _render_provider_timeout_diagnostics(
    diagnostics: dict[str, object],
) -> list[str]:
    return [
        "SFE provider timeout diagnostics",
        f"  provider: {_display_value(diagnostics.get('provider'))}",
        f"  model: {_display_value(diagnostics.get('model'))}",
        f"  role: {_display_value(diagnostics.get('role'))}",
        f"  timeout kind: {_display_value(diagnostics.get('timeout_kind'))}",
        "  idle timeout seconds: "
        f"{_display_value(diagnostics.get('idle_timeout_seconds'))}",
        f"  elapsed seconds: {_display_value(diagnostics.get('elapsed_seconds'))}",
        "  provider output seen: "
        f"{_display_bool(diagnostics.get('provider_output_seen'))}",
        "  provider stdout chunks: "
        f"{_display_value(diagnostics.get('provider_stdout_chunk_count'))}",
        "  last provider event: "
        f"{_display_value(diagnostics.get('last_provider_event_kind'))}",
        "  last provider event elapsed seconds: "
        f"{_display_value(diagnostics.get('last_provider_event_elapsed_seconds'))}",
    ]


def _format_diagnostic_list(value: object) -> str:
    if isinstance(value, tuple | list):
        return _format_string_list([str(item) for item in value])
    return _format_string_list([])


def _display_bool(value: object) -> str:
    return _yes_no(value) if isinstance(value, bool) else _display_value(None)


def _run_execution_mode(result: RunResult) -> str | None:
    if result.execution_mode_decision is None:
        return None
    return result.execution_mode_decision.execution_mode


def _run_issue_lines(issue: RunIssue) -> list[str]:
    lines = [
        f"  issue category: {issue.category}",
        f"  issue reason: {issue.reason}",
    ]
    if issue.path is not None:
        lines.append(f"  issue path: {issue.path}")
    return lines


def render_worktree_review_success(decision: JsonReviewDecision) -> str:
    return "\n".join(
        [
            "SFE review-worktree",
            "  status: reviewed",
            *_router_decision_lines(decision),
            "  promotion: not performed",
            "  merge: not performed",
            "  push: not performed",
        ]
    )


def render_worktree_review_failure(
    issue: WorkspaceIssue | None,
    *,
    failure_category: str | None = None,
    router_reason: str | None = None,
    router_provider: str | None = None,
    router_model: str | None = None,
) -> str:
    lines = [
        "SFE review-worktree",
        "  status: failed",
        f"  error category: {failure_category or _workspace_issue_category(issue)}",
    ]
    if router_reason is not None:
        lines.extend(
            [
                f"  router provider: {_display_value(router_provider)}",
                f"  router model: {_display_value(router_model)}",
                f"  router reason: {router_reason}",
            ]
        )
    else:
        lines.append(f"  reason: {_workspace_issue_reason(issue)}")
    lines.extend(
        [
            "  promotion: not performed",
            "  merge: not performed",
            "  push: not performed",
        ]
    )
    return "\n".join(lines)


def render_cleanup_worktree_result(
    result: WorkspaceCleanupResult,
    *,
    restored_workspace: Path | None = None,
    launch_cwd: Path | None = None,
) -> str:
    lines = [
        "SFE cleanup-worktree",
        f"  status: {'cleaned' if result.cleaned else 'failed'}",
    ]
    if result.cleaned:
        lines.append(
            f"  active workspace: {safe_workspace_label(restored_workspace, launch_cwd) if restored_workspace is not None else 'original'}"
        )
        return "\n".join(lines)
    lines.extend(
        [
            f"  error category: {_workspace_issue_category(result.issue)}",
            f"  reason: {_workspace_issue_reason(result.issue)}",
            "  active workspace unchanged",
        ]
    )
    return "\n".join(lines)


def render_gc_worktrees_result(
    result: WorkspaceGCResult,
    *,
    launch_cwd: Path | None = None,
) -> str:
    lines = [
        "SFE gc-worktrees",
        f"  mode: {'clean' if result.clean else 'dry-run'}",
    ]
    if result.issue is not None:
        lines.extend(
            [
                "  status: failed",
                f"  error category: {_workspace_issue_category(result.issue)}",
                f"  reason: {_workspace_issue_reason(result.issue)}",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "  status: ok",
            f"  SFE worktrees found: {result.sfe_worktree_count}",
            f"  clean eligible worktrees: {result.eligible_count}",
            f"  dirty worktrees skipped: {result.dirty_skipped_count}",
            f"  non-SFE worktrees ignored: {result.non_sfe_ignored_count}",
            f"  worktrees removed: {result.removed_count}",
        ]
    )
    for entry in result.entries:
        branch = entry.worktree_branch or "unknown"
        changed = _format_string_list(list(entry.changed_files))
        lines.append(
            "  "
            + " | ".join(
                [
                    f"status={entry.status}",
                    f"branch={branch}",
                    f"path={safe_workspace_label(entry.worktree_path, launch_cwd)}",
                    f"reason={entry.reason}",
                    f"changed={changed}",
                ]
            )
        )
    return "\n".join(lines)


def render_macro_start(name: str) -> str:
    return "\n".join(
        [
            f"SFE {name}",
            "  status: started",
        ]
    )


def render_macro_step(name: str, step: str) -> str:
    return f"SFE {name} step: {step}"


def render_macro_stop(name: str, reason: str) -> str:
    return "\n".join(
        [
            f"SFE {name}",
            "  status: stopped",
            f"  reason: {reason}",
        ]
    )


def render_macro_done(name: str) -> str:
    return "\n".join(
        [
            f"SFE {name}",
            "  status: completed",
            "  merge: not performed",
            "  push: not performed",
            "  cleanup: not performed",
        ]
    )


def render_context_summary(
    *,
    contract: SFEContract,
    context_files: list[ContextLoadResult],
    latest_result: ExecutionResult | None,
    discovery_result: DiscoveryResult | None = None,
    pending_patch_summary: PatchSummary | None = None,
) -> str:
    skipped_count = sum(1 for result in context_files if not result.loaded)
    skipped_reasons = _skipped_reason_counts(context_files)
    latest_selected_ids: list[str] = []
    if latest_result is not None:
        latest_selected_ids = list(
            latest_result.contract.audit.get("selected_segment_ids") or []
        )
    if not contract.context_segments:
        lines = [
            "SFE context",
            *_discovery_context_lines(discovery_result),
            "  loaded context segments: 0",
            f"  skipped context files: {skipped_count}",
            f"  skipped reasons: {_format_reason_counts(skipped_reasons)}",
            f"  latest selected segment ids: {latest_selected_ids}",
            *_pending_patch_context_lines(pending_patch_summary),
            "  empty: no context loaded",
        ]
        return "\n".join(lines)
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
        *_discovery_context_lines(discovery_result),
        f"  loaded context segments: {len(contract.context_segments)}",
        f"  skipped context files: {skipped_count}",
        f"  skipped reasons: {_format_reason_counts(skipped_reasons)}",
        f"  latest selected segment ids: {latest_selected_ids}",
        *_pending_patch_context_lines(pending_patch_summary),
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


def render_discovery_summary(discovery_result: DiscoveryResult | None) -> str:
    if discovery_result is None:
        return "\n".join(
            [
                "SFE discovery",
                "  discovery ran: no",
            ]
        )
    top_refs = [candidate.source_ref for candidate in discovery_result.candidates[:5]]
    lines = [
        "SFE discovery",
        "  discovery ran: yes",
        f"  workspace selected: {_yes_no(discovery_result.workspace_root_present)}",
        f"  task present: {_yes_no(discovery_result.task_present)}",
        f"  discovery mode: {_display_value(discovery_result.discovery_mode)}",
        f"  scanned files: {discovery_result.scanned_file_count}",
        f"  workspace map entries: {discovery_result.workspace_map_count}",
        f"  candidates: {discovery_result.candidate_count}",
        f"  loaded candidate count: {discovery_result.loaded_candidate_count}",
        f"  skipped candidate count: {discovery_result.skipped_candidate_count}",
        f"  stop reason: {_display_value(discovery_result.stop_reason)}",
        f"  router provider: {_display_value(discovery_result.router_provider_name)}",
        f"  router model: {_display_value(discovery_result.router_model)}",
        f"  router calls made: {discovery_result.router_provider_calls_made}",
        f"  router reason: {_display_value(discovery_result.router_reason)}",
        f"  top candidate source refs: {_format_string_list(top_refs)}",
        f"  skipped reasons: {_format_reason_counts(discovery_result.skipped_reason_counts)}",
        f"  warning reasons: {_format_reason_counts(discovery_result.warning_reason_counts)}",
    ]
    if discovery_result.stop_reason == "empty_workspace":
        lines.append(
            "  note: empty workspace is valid in DEV patch mode; no existing context to inspect"
        )
    return "\n".join(lines)


def render_dry_run_summary(contract: SFEContract, result: ExecutionResult) -> str:
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
        "Local dry-run context preview",
        f"  selector mode: {_display_value(audit.get('selector_mode'))}",
        "  note: this dry-run context preview is local; /discover reports its own discovery mode",
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
        lines.append("  action: no context loaded; run /discover or use /files <path>")
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
            "  automatic writes disabled; explicit /apply-patch available",
            "  shell disabled",
            "  patch application available through explicit /apply-patch",
            f"  status: {result.status}",
        ]
    )
    return "\n".join(lines)


def render_ask_result(result: ExecutionResult) -> str:
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
            "  automatic writes disabled; explicit /apply-patch available",
            "  shell disabled",
            "  patch application available through explicit /apply-patch",
        ]
    )
    return "\n".join(lines)


def render_patch_result(
    result: ExecutionResult,
    *,
    pending_patch_summary: PatchSummary | None = None,
    pending_patch_issue: object | None = None,
    pending_patch_preview: str | None = None,
    pending_patch_diagnostics: object | None = None,
) -> str:
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
        f"  pending patch stored: {_yes_no(pending_patch_summary is not None)}",
        "  pending patch repair attempted: "
        + _yes_no(bool(getattr(pending_patch_diagnostics, "repair_attempted", False))),
        "  pending patch repair result: "
        + _display_value(
            getattr(pending_patch_diagnostics, "repair_result", None) or "not_needed"
        ),
    ]
    detail = getattr(pending_patch_diagnostics, "detail", None)
    if detail is not None:
        lines.append(f"  pending patch detail: {_display_value(detail)}")
    if pending_patch_summary is not None:
        lines.extend(
            [
                f"  pending patch files: {pending_patch_summary.file_count}",
                f"  pending patch created files: {len(pending_patch_summary.created_paths)}",
                f"  pending patch hunks: {pending_patch_summary.hunk_count}",
                "  apply command: /apply-patch",
            ]
        )
    elif pending_patch_issue is not None:
        lines.append(
            f"  pending patch reason: {_safe_patch_issue_category(pending_patch_issue)}"
        )
    if result.answer:
        if pending_patch_summary is not None:
            proposal_text = pending_patch_preview or "No text diff preview available."
        else:
            proposal_text = result.answer
        lines.extend(["Patch proposal only, not applied", proposal_text])
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
            "  automatic writes disabled for /patch",
            "  shell disabled",
            "  patch application available through explicit /apply-patch",
            "  patch applied: no",
        ]
    )
    return "\n".join(lines)


def render_apply_patch_success(
    result: PatchApplyResult,
    *,
    router_decision: PatchReviewDecision | None = None,
) -> str:
    summary = result.summary
    lines = [
        "SFE apply-patch",
        "  status: applied",
    ]
    if router_decision is not None:
        lines.extend(_router_decision_lines(router_decision))
    lines.extend(
        [
            f"  modified relative paths: {_format_string_list(list(summary.modified_paths) if summary else [])}",
            f"  created relative paths: {_format_string_list(list(summary.created_paths) if summary else [])}",
            f"  file count: {summary.file_count if summary else 0}",
            f"  hunk count: {summary.hunk_count if summary else 0}",
            f"  lines added: {summary.lines_added if summary else 0}",
            f"  lines removed: {summary.lines_removed if summary else 0}",
            f"  pending patch cleared: {_yes_no(result.pending_patch_cleared)}",
        ]
    )
    return "\n".join(lines)


def render_apply_patch_failure(
    error_category: str,
    issue: PatchIssue | None,
    *,
    pending_patch_cleared: bool,
    failure_kind: str | None = None,
    router_decision: PatchReviewDecision | None = None,
    router_reason: str | None = None,
    router_provider: str | None = None,
    router_model: str | None = None,
) -> str:
    lines = [
        "SFE apply-patch",
        f"  status: failed",
        f"  error category: {error_category}",
    ]
    if failure_kind is not None:
        lines.append(f"  failure kind: {failure_kind}")
    if router_decision is not None:
        lines.extend(_router_decision_lines(router_decision))
    elif router_reason is not None:
        lines.extend(
            [
                f"  router provider: {_display_value(router_provider)}",
                f"  router model: {_display_value(router_model)}",
                f"  router reason: {router_reason}",
            ]
        )
    if issue is not None and issue.path is not None:
        lines.append(f"  relative path: {issue.path}")
    if issue is not None:
        lines.append(f"  reason category: {issue.reason}")
    lines.extend(
        [
            f"  pending patch cleared: {_yes_no(pending_patch_cleared)}",
            "  no files were modified",
        ]
    )
    return "\n".join(lines)


def _router_decision_lines(decision: PatchReviewDecision) -> list[str]:
    return [
        f"  router decision: {decision.decision}",
        f"  router provider: {_display_value(decision.provider_name)}",
        f"  router model: {_display_value(decision.model)}",
        f"  router risk level: {decision.risk_level}",
        f"  router files reviewed: {_format_string_list(list(decision.files_reviewed))}",
        f"  router reason: {decision.reason}",
    ]


def _workspace_issue_category(issue: WorkspaceIssue | None) -> str:
    if issue is None:
        return "workspace_error"
    return issue.category


def _workspace_issue_reason(issue: WorkspaceIssue | None) -> str:
    if issue is None:
        return "unknown"
    return issue.reason


def _truncate_text(text: str, *, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... truncated ..."


def _pending_patch_context_lines(summary: PatchSummary | None) -> list[str]:
    if summary is None:
        return [
            "  pending patch: no",
            "  pending patch files: 0",
            "  pending patch hunks: 0",
        ]
    return [
        "  pending patch: yes",
        f"  pending patch files: {summary.file_count}",
        f"  pending patch created files: {len(summary.created_paths)}",
        f"  pending patch hunks: {summary.hunk_count}",
    ]


def _patch_summary_count(summary: PatchSummary | None, attr_name: str) -> int:
    if summary is None:
        return 0
    return int(getattr(summary, attr_name))


def _run_selected_tokens(result: ExecutionResult | None) -> object | None:
    if result is None:
        return None
    return result.contract.audit.get("estimated_selected_tokens")


def _run_reduction_pct(result: ExecutionResult | None) -> object | None:
    if result is None:
        return None
    return result.contract.audit.get("estimated_reduction_pct")


def _safe_patch_issue_category(issue: object) -> str:
    category = getattr(issue, "category", None)
    if category is None:
        return "none"
    return str(category)


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


def _ask_provider_status(result: ExecutionResult) -> str:
    if result.answer:
        return "answer received"
    if result.error_category:
        return f"failed ({result.error_category})"
    return "no answer returned"


def _patch_provider_status(result: ExecutionResult) -> str:
    if result.answer:
        return "proposal received"
    if result.error_category:
        return f"failed ({result.error_category})"
    return "no proposal returned"


def _failure_guidance(error_category: str | None) -> str:
    return {
        "missing_task": "set a task with /task <text>",
        "discovery_not_run": "run /discover after /task before this command",
        "no_context_loaded": "run /discover or use /files <path>",
        "no_selected_context": (
            "routing found no relevant context segments; revise the task or loaded files"
        ),
        "provider_not_configured": (
            "this command needs a configured executor/provider"
        ),
        "timeout": "provider call timed out; retry later or check provider settings",
        "provider_idle_timeout": "provider call stalled after progress stopped; retry later or check provider health",
        "http_error": "provider returned an HTTP error; check provider settings",
        "network_error": "provider could not be reached; check local provider status",
        "invalid_json": "provider returned non-JSON data",
        "provider_error": "provider call failed; check provider configuration and retry",
        "provider_configuration_error": (
            "set SFE_PROVIDER to openai-compatible, openai, lemonade, alibaba, "
            "anthropic, google, or codexcli"
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


def _discovery_count(
    discovery_result: DiscoveryResult | None,
    attr_name: str,
) -> int:
    if discovery_result is None:
        return 0
    return int(getattr(discovery_result, attr_name))


def _discovery_context_lines(
    discovery_result: DiscoveryResult | None,
) -> list[str]:
    if discovery_result is None:
        return ["  discovery result present: no"]
    top_refs = [candidate.source_ref for candidate in discovery_result.candidates[:5]]
    return [
        "  discovery result present: yes",
        f"  discovered candidates: {discovery_result.candidate_count}",
        f"  discovered loaded candidates: {discovery_result.loaded_candidate_count}",
        f"  discovered source refs: {_format_string_list(top_refs)}",
    ]
