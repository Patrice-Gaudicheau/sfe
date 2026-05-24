"""Configured router review for pending TUI patches."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from providers.alibaba import (
    DEFAULT_ROUTER_MODEL as DEFAULT_ALIBABA_ROUTER_MODEL,
    AlibabaAPIError,
    AlibabaAPIProvider,
    MissingAlibabaAPIKeyError,
)
from providers.anthropic import (
    DEFAULT_ROUTER_MODEL as DEFAULT_ANTHROPIC_ROUTER_MODEL,
    AnthropicAPIError,
    AnthropicProvider,
    MissingAnthropicAPIKeyError,
)
from providers.lemonade import LemonadeProvider, LemonadeProviderError
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from sfe.provider_config import resolve_sfe_provider


DEFAULT_LEMONADE_ROUTER_MODEL = "Qwen3-0.6B-GGUF"
PATCH_REVIEW_MAX_TOKENS = 800
PATCH_REVIEW_SYSTEM_INSTRUCTION = (
    "You are the configured SFE router reviewing an existing pending patch. "
    "Do not rewrite, repair, or produce a patch. Decide only whether the "
    "pending patch is globally acceptable for the user task. Proposed edits are "
    "represented internally as full-file replacements; this is expected and is "
    "only a transport/application format. Do not reject a proposal merely "
    "because it uses full-file replacement format. Judge the effective semantic "
    "and textual delta between current file content and proposed replacement "
    "content. Use any diff preview to understand the intended minimal delta, "
    "and reject if the proposed full content does not correspond to that "
    "preview. Return exactly one JSON object with keys decision, reason, "
    "files_reviewed, and risk_level. decision must be OK_APPLY or KO_BLOCK. "
    "risk_level must be low, medium, or high."
)
DECISIONS = {"OK_APPLY", "KO_BLOCK"}
RISK_LEVELS = {"low", "medium", "high"}


@dataclass(frozen=True)
class PatchReviewDecision:
    decision: str
    reason: str
    files_reviewed: tuple[str, ...]
    risk_level: str
    provider_name: str | None = None
    model: str | None = None


class PatchReviewError(RuntimeError):
    def __init__(self, category: str, reason: str) -> None:
        self.category = category
        self.reason = reason
        super().__init__(reason)


class PatchReviewer(Protocol):
    provider_name: str | None
    model: str | None

    def review(self, payload: dict[str, Any]) -> PatchReviewDecision:
        ...


class DirectProviderPatchReviewer:
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
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.call_style = call_style
        self.missing_key_errors = missing_key_errors
        self.provider_error_types = provider_error_types
        self.provider_error_classifier = provider_error_classifier

    def review(self, payload: dict[str, Any]) -> PatchReviewDecision:
        health = self.provider.health()
        if not health.get("ok"):
            raise PatchReviewError("router_not_configured", "configured router is not available")
        try:
            response = _call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=_build_review_prompt(payload),
                model=self.model,
                max_tokens=PATCH_REVIEW_MAX_TOKENS,
                system_instruction=PATCH_REVIEW_SYSTEM_INSTRUCTION,
            )
        except self.missing_key_errors as exc:
            raise PatchReviewError("router_not_configured", "configured router is not available") from exc
        except TimeoutError as exc:
            raise PatchReviewError("router_timeout", "configured router timed out") from exc
        except self.provider_error_types as exc:
            raise PatchReviewError("router_provider_error", "configured router provider failed") from exc
        except Exception as exc:
            category = _classify_provider_error(exc, self.provider_error_classifier)
            raise PatchReviewError(category, "configured router provider failed") from exc

        output = _extract_answer(response)
        decision = _parse_review_decision(output)
        return PatchReviewDecision(
            decision=decision.decision,
            reason=decision.reason,
            files_reviewed=decision.files_reviewed,
            risk_level=decision.risk_level,
            provider_name=self.provider_name,
            model=self.model,
        )


class ProviderConfigurationErrorPatchReviewer:
    provider_name = "invalid"
    model = None

    def review(self, payload: dict[str, Any]) -> PatchReviewDecision:
        del payload
        raise PatchReviewError("provider_configuration_error", "invalid SFE provider configuration")


class UnsupportedProviderPatchReviewer:
    model = None

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def review(self, payload: dict[str, Any]) -> PatchReviewDecision:
        del payload
        raise PatchReviewError("provider_not_supported", "configured provider is not supported for patch review")


ProviderFactory = Callable[[], Any]


def create_tui_patch_reviewer(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, ProviderFactory] | None = None,
) -> PatchReviewer:
    try:
        provider_name = resolve_sfe_provider(environ, default="openai")
    except ValueError:
        return ProviderConfigurationErrorPatchReviewer()

    provider_factory = _provider_factory(provider_name, provider_factories=provider_factories)
    if provider_name in ("openai", "openai-compatible"):
        return DirectProviderPatchReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",))
                or DEFAULT_OPENAI_ROUTER_MODEL
            ),
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
        )
    if provider_name == "lemonade":
        return DirectProviderPatchReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(environ, ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"))
                or DEFAULT_LEMONADE_ROUTER_MODEL
            ),
            call_style="system_message",
            provider_error_classifier=_classify_lemonade_error,
        )
    if provider_name == "alibaba":
        return DirectProviderPatchReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",))
                or DEFAULT_ALIBABA_ROUTER_MODEL
            ),
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
        )
    if provider_name == "anthropic":
        return DirectProviderPatchReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",))
                or DEFAULT_ANTHROPIC_ROUTER_MODEL
            ),
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
        )
    return UnsupportedProviderPatchReviewer(provider_name)


def _provider_factory(
    provider_name: str,
    *,
    provider_factories: Mapping[str, ProviderFactory] | None,
) -> ProviderFactory:
    if provider_factories and provider_name in provider_factories:
        return provider_factories[provider_name]
    if provider_name in ("openai", "openai-compatible"):
        return OpenAIAPIProvider
    if provider_name == "lemonade":
        return LemonadeProvider
    if provider_name == "alibaba":
        return AlibabaAPIProvider
    if provider_name == "anthropic":
        return AnthropicProvider
    return lambda: None


def _call_provider_chat(
    *,
    provider: Any,
    call_style: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    system_instruction: str,
) -> dict[str, Any]:
    if call_style == "system_message":
        return provider.chat(
            [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            max_tokens=max_tokens,
            temperature=None,
        )
    return provider.chat(
        [{"role": "user", "content": user_prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=None,
        system_instruction=system_instruction,
    )


def _build_review_prompt(payload: dict[str, Any]) -> str:
    guidance = (
        "Review the pending patch payload below. The proposal_format "
        "file_replacements means every touched file is represented by complete "
        "replacement text. This is the expected internal application format, "
        "not evidence that the user-visible edit is large or non-minimal. "
        "Compare current_files with proposed_full_replacements and judge only "
        "the effective delta. Allow OK_APPLY when the effective diff is small, "
        "task-aligned, preserves unrelated content, and touches appropriate "
        "files. Return KO_BLOCK for unrelated changes, missing required "
        "changes, dangerous or surprising changes, large unrelated rewrites, "
        "README/code inconsistency, or when proposed replacement content does "
        "not match the readable diff preview."
    )
    return (
        guidance
        + "\n\nPatch review payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _parse_review_decision(output: str) -> PatchReviewDecision:
    try:
        parsed = json.loads(_strip_json_fence(output))
    except json.JSONDecodeError as exc:
        raise PatchReviewError("invalid_router_response", "router did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise PatchReviewError("invalid_router_response", "router JSON was not an object")
    decision = str(parsed.get("decision") or "")
    reason = str(parsed.get("reason") or "").strip()
    risk_level = str(parsed.get("risk_level") or "")
    files = parsed.get("files_reviewed") or []
    if decision not in DECISIONS:
        raise PatchReviewError("invalid_router_response", "router decision was invalid")
    if risk_level not in RISK_LEVELS:
        raise PatchReviewError("invalid_router_response", "router risk_level was invalid")
    if not reason:
        raise PatchReviewError("invalid_router_response", "router reason was empty")
    if not isinstance(files, list):
        raise PatchReviewError("invalid_router_response", "router files_reviewed was invalid")
    return PatchReviewDecision(
        decision=decision,
        reason=reason,
        files_reviewed=tuple(str(item) for item in files),
        risk_level=risk_level,
    )


def _strip_json_fence(output: str) -> str:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _extract_answer(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"]).strip()
    return ""


def _classify_provider_error(
    exc: Exception,
    classifier: Callable[[Exception], str | None] | None,
) -> str:
    if classifier is None:
        return "router_provider_error"
    return classifier(exc) or "router_provider_error"


def _classify_lemonade_error(exc: Exception) -> str | None:
    if isinstance(exc, LemonadeProviderError):
        return f"router_{exc.error_category}"
    return None


def _first_env_value(
    environ: Mapping[str, str] | None,
    names: tuple[str, ...],
) -> str | None:
    env = os.environ if environ is None else environ
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None
