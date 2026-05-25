"""Configured router review for pending TUI patches."""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from sfe.router_review import (
    DEFAULT_LEMONADE_ROUTER_MODEL,
    DirectProviderJsonReviewer,
    JsonReviewDecision,
    JsonReviewer,
    ProviderConfigurationErrorJsonReviewer,
    RouterReviewError,
    UnsupportedProviderJsonReviewer,
    call_provider_chat,
    classify_lemonade_error,
    classify_provider_error,
    create_configured_router_json_reviewer,
    extract_answer,
    first_env_value,
    parse_json_review_decision,
    provider_factory_for,
    strip_json_fence,
)


PATCH_REVIEW_MAX_TOKENS = 800
PATCH_REVIEW_SYSTEM_INSTRUCTION = (
    "You are the configured SFE router reviewing an existing pending patch. "
    "Do not rewrite, repair, or produce a patch. Decide only whether the "
    "pending patch is globally acceptable for the user task. Proposed edits are "
    "represented internally as full-file replacements; this is expected and is "
    "only a transport/application format. Do not reject a proposal merely "
    "because it uses full-file replacement format. Judge the effective semantic "
    "and textual delta between current file content and proposed replacement "
    "content. The effective diff preview is computed by SFE from the current "
    "file contents and the proposed full replacements; provider-supplied diff "
    "text is not trusted. Reject if the computed effective diff includes "
    "unrelated or surprising edits. Return exactly one JSON object with keys "
    "decision, reason, files_reviewed, and risk_level. decision must be "
    "OK_APPLY or KO_BLOCK. risk_level must be low, medium, or high. "
    "files_reviewed must be a JSON array of strings containing the reviewed "
    "file paths. Do not return a string, object, count, or comma-separated "
    "text for files_reviewed."
)
DECISIONS = {"OK_APPLY", "KO_BLOCK"}
RISK_LEVELS = {"low", "medium", "high"}

PatchReviewDecision = JsonReviewDecision
PatchReviewError = RouterReviewError
PatchReviewer = JsonReviewer
ProviderConfigurationErrorPatchReviewer = ProviderConfigurationErrorJsonReviewer
ProviderFactory = Callable[[], Any]


class UnsupportedProviderPatchReviewer(UnsupportedProviderJsonReviewer):
    def __init__(self, provider_name: str) -> None:
        super().__init__(
            provider_name,
            reason="configured provider is not supported for patch review",
        )


class DirectProviderPatchReviewer(DirectProviderJsonReviewer):
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
            system_instruction=PATCH_REVIEW_SYSTEM_INSTRUCTION,
            prompt_builder=_build_review_prompt,
            valid_decisions=DECISIONS,
            max_tokens=PATCH_REVIEW_MAX_TOKENS,
            missing_key_errors=missing_key_errors,
            provider_error_types=provider_error_types,
            provider_error_classifier=provider_error_classifier,
        )


def create_tui_patch_reviewer(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, ProviderFactory] | None = None,
) -> PatchReviewer:
    return create_configured_router_json_reviewer(
        system_instruction=PATCH_REVIEW_SYSTEM_INSTRUCTION,
        prompt_builder=_build_review_prompt,
        valid_decisions=DECISIONS,
        max_tokens=PATCH_REVIEW_MAX_TOKENS,
        environ=environ,
        provider_factories=provider_factories,
        unsupported_provider_reason="configured provider is not supported for patch review",
    )


def _build_review_prompt(payload: dict[str, Any]) -> str:
    guidance = (
        "Review the pending patch payload below. The proposal_format "
        "file_replacements means every touched file is represented by complete "
        "replacement text. This is the expected internal application format, "
        "not evidence that the user-visible edit is large or non-minimal. "
        "Compare current_files with proposed_full_replacements and judge only "
        "the effective delta. The diff_preview field was computed locally by "
        "SFE from current_files and proposed_full_replacements; use it as the "
        "trusted readable view of the actual replacement contents. Allow OK_APPLY "
        "when the effective diff is small, task-aligned, preserves unrelated content, and touches appropriate "
        "files. Return KO_BLOCK for unrelated changes, missing required "
        "changes, dangerous or surprising changes, large unrelated rewrites, "
        "README/code inconsistency, or when the computed effective diff includes "
        "edits outside the task."
    )
    return (
        guidance
        + "\n\nPatch review payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _parse_review_decision(output: str) -> PatchReviewDecision:
    return parse_json_review_decision(output, valid_decisions=DECISIONS)


_strip_json_fence = strip_json_fence
_extract_answer = extract_answer
_classify_provider_error = classify_provider_error
_classify_lemonade_error = classify_lemonade_error
_first_env_value = first_env_value
_call_provider_chat = call_provider_chat
_provider_factory = provider_factory_for
