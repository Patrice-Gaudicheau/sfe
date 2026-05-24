"""Router-reviewed validation for isolated workspace results."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from sfe.router_review import (
    DirectProviderJsonReviewer,
    JsonReviewDecision,
    JsonReviewer,
    ProviderFactory,
    RouterReviewError,
    create_configured_router_json_reviewer,
    parse_json_review_decision,
)
from sfe.workspace_isolation import WorkspaceStatus


WORKSPACE_REVIEW_MAX_TOKENS = 900
WORKSPACE_REVIEW_SYSTEM_INSTRUCTION = (
    "You are the configured SFE router reviewing changes produced in an "
    "isolated execution workspace. Do not rewrite, repair, or produce a patch. "
    "Decide only whether the resulting worktree changes are globally "
    "acceptable for the original user task. The worktree is isolated from the "
    "source workspace. Return exactly one JSON object with keys decision, "
    "reason, files_reviewed, and risk_level. decision must be OK_PROMOTE or "
    "KO_BLOCK. risk_level must be low, medium, or high. OK_PROMOTE means the "
    "changes may be considered by an explicit later promotion step; it does "
    "not merge, push, or mutate the source branch."
)
WORKSPACE_REVIEW_DECISIONS = {"OK_PROMOTE", "KO_BLOCK"}

WorkspaceReviewDecision = JsonReviewDecision
WorkspaceReviewError = RouterReviewError
WorkspaceReviewer = JsonReviewer


class DirectProviderWorkspaceReviewer(DirectProviderJsonReviewer):
    def __init__(
        self,
        *,
        provider: Any,
        provider_name: str,
        model: str,
        call_style: str,
        missing_key_errors: tuple[type[Exception], ...] = (),
        provider_error_types: tuple[type[Exception], ...] = (),
        provider_error_classifier: Callable[[Exception], str | None] | None = None,
    ) -> None:
        super().__init__(
            provider=provider,
            provider_name=provider_name,
            model=model,
            call_style=call_style,
            system_instruction=WORKSPACE_REVIEW_SYSTEM_INSTRUCTION,
            prompt_builder=build_workspace_review_prompt,
            valid_decisions=WORKSPACE_REVIEW_DECISIONS,
            max_tokens=WORKSPACE_REVIEW_MAX_TOKENS,
            missing_key_errors=missing_key_errors,
            provider_error_types=provider_error_types,
            provider_error_classifier=provider_error_classifier,
        )


def create_workspace_reviewer(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, ProviderFactory] | None = None,
) -> WorkspaceReviewer:
    return create_configured_router_json_reviewer(
        system_instruction=WORKSPACE_REVIEW_SYSTEM_INSTRUCTION,
        prompt_builder=build_workspace_review_prompt,
        valid_decisions=WORKSPACE_REVIEW_DECISIONS,
        max_tokens=WORKSPACE_REVIEW_MAX_TOKENS,
        environ=environ,
        provider_factories=provider_factories,
        unsupported_provider_reason="configured provider is not supported for workspace review",
    )


def build_workspace_review_payload(
    *,
    original_user_task: str,
    workspace_status: WorkspaceStatus,
    test_results: Mapping[str, Any] | None = None,
    discovered_constraints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "original_user_task": original_user_task,
        "review_target": "isolated_workspace_changes",
        "review_guidance": {
            "router_decides_accept_or_block_only": True,
            "router_must_not_rewrite_or_repair": True,
            "ok_promote_does_not_merge_push_or_mutate_source_branch": True,
        },
        "git_status_porcelain": workspace_status.git_status_porcelain,
        "git_diff_preview": workspace_status.git_diff,
        "changed_files": list(workspace_status.changed_files),
        "test_results": dict(test_results or {}),
        "discovered_constraints": dict(discovered_constraints or {}),
        "workspace_metadata": {
            "source_path": str(workspace_status.source_path),
            "worktree_path": str(workspace_status.worktree_path),
            "source_branch": workspace_status.source_branch,
            "worktree_branch": workspace_status.worktree_branch,
        },
    }


def build_workspace_review_prompt(payload: dict[str, Any]) -> str:
    guidance = (
        "Review the isolated workspace payload below. Decide whether the "
        "changed files, status, diff preview, test results, and metadata "
        "satisfy the original task without unrelated, dangerous, or surprising "
        "changes. Return KO_BLOCK when the diff is missing required changes, "
        "contains unrelated edits, has unresolved test failures, or is too "
        "risky to promote. Return OK_PROMOTE only when the worktree changes are "
        "task-aligned and acceptable for a separate explicit promotion step."
    )
    return (
        guidance
        + "\n\nWorkspace review payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def parse_workspace_review_decision(output: str) -> WorkspaceReviewDecision:
    return parse_json_review_decision(
        output,
        valid_decisions=WORKSPACE_REVIEW_DECISIONS,
    )
