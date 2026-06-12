"""LLM review for full-file replacement fallbacks after hunk mismatches."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from providers.alibaba import AlibabaAPIError, MissingAlibabaAPIKeyError
from providers.anthropic import AnthropicAPIError, MissingAnthropicAPIKeyError
from providers.lemonade import LemonadeProviderError
from providers.ollama import OllamaProviderError
from providers.openai_api import MissingOpenAIAPIKeyError, OpenAIAPIError
from sfe.multipass_planner import (
    _call_provider_chat,
    _extract_answer,
    _first_env_value,
    _instantiate_codexcli_provider,
    _provider_factory_for,
)
from sfe.provider_config import (
    CODEXCLI_SFE_PROVIDER,
    OLLAMA_SFE_PROVIDER,
    resolve_sfe_router_provider,
)
from sfe.provider_progress import ProviderCallIdleTimeoutError


FULL_FILE_REPLACEMENT_REVIEW_FALLBACK_KIND = (
    "llm_reviewed_full_file_replacement_after_hunk_mismatch"
)
DEFAULT_FULL_FILE_REPLACEMENT_REVIEW_MODE = "false"
DEFAULT_FULL_FILE_REPLACEMENT_REVIEW_OUTPUT_TOKENS = 800
FULL_FILE_REPLACEMENT_REVIEW_SYSTEM_INSTRUCTION = (
    "You are an SFE safety reviewer for a proposed full-file replacement after "
    "a unified-diff hunk preimage mismatch. Return only one strict JSON object. "
    "Do not return Markdown, code fences, prose, diffs, patches, or rewritten "
    "file content. You must not rewrite the file and must not invent missing "
    "context. Review only whether the proposed replacement is safe and coherent "
    "enough for SFE to apply. Approve normal full-file rewrites when they are "
    "coherent with the current file and the task. Reject unrelated replacements, "
    "empty or truncated replacements, destructive replacements, obvious syntax "
    "corruption, secrets, or changes outside the task intent. Be conservative "
    "but not overly rigid. The JSON shape is exactly approve, risk_level, "
    "reason, concerns. risk_level must be low, medium, or high."
)


@dataclass(frozen=True)
class FullFileReplacementReviewRequest:
    task_summary: str
    target_path: str
    pass_number: int
    pass_label: str | None
    current_content: str
    proposed_replacement_content: str
    related_selected_file_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class FullFileReplacementReviewDecision:
    approve: bool
    risk_level: str
    reason: str
    concerns: tuple[str, ...] = ()
    raw_answer: str | None = None
    error: str | None = None

    @property
    def apply_allowed(self) -> bool:
        return self.approve and self.risk_level in {"low", "medium"}


class FullFileReplacementReviewer(Protocol):
    provider_name: str | None
    model: str | None

    def review(
        self,
        request: FullFileReplacementReviewRequest,
    ) -> FullFileReplacementReviewDecision:
        ...


class DisabledFullFileReplacementReviewer:
    provider_name = None
    model = None

    def review(
        self,
        request: FullFileReplacementReviewRequest,
    ) -> FullFileReplacementReviewDecision:
        del request
        return FullFileReplacementReviewDecision(
            approve=False,
            risk_level="high",
            reason="full_file_replacement_review_disabled",
            error="disabled",
        )


class ConfiguredLLMFullFileReplacementReviewer:
    def __init__(
        self,
        *,
        provider: Any,
        provider_name: str,
        model: str,
        call_style: str,
        missing_key_errors: tuple[type[Exception], ...] = (),
        provider_error_types: tuple[type[Exception], ...] = (),
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.call_style = call_style
        self.missing_key_errors = missing_key_errors
        self.provider_error_types = provider_error_types

    def review(
        self,
        request: FullFileReplacementReviewRequest,
    ) -> FullFileReplacementReviewDecision:
        health = self.provider.health()
        if not health.get("ok"):
            return _error_decision("reviewer_not_configured")
        try:
            response = _call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=build_full_file_replacement_review_prompt(request),
                model=self.model,
                max_tokens=DEFAULT_FULL_FILE_REPLACEMENT_REVIEW_OUTPUT_TOKENS,
                system_instruction=FULL_FILE_REPLACEMENT_REVIEW_SYSTEM_INSTRUCTION,
            )
        except self.missing_key_errors:
            return _error_decision("reviewer_not_configured")
        except ProviderCallIdleTimeoutError:
            return _error_decision("reviewer_provider_idle_timeout")
        except TimeoutError:
            return _error_decision("reviewer_timeout")
        except self.provider_error_types:
            return _error_decision("reviewer_provider_error")
        except LemonadeProviderError as exc:
            return _error_decision(f"reviewer_{exc.error_category}")
        except OllamaProviderError as exc:
            return _error_decision(f"reviewer_{exc.error_category}")
        except Exception:
            return _error_decision("reviewer_provider_error")

        answer = _extract_answer(response)
        return parse_full_file_replacement_review_json(answer)


def resolve_full_file_replacement_review_mode(
    environ: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    value = (env.get("SFE_FULL_FILE_REPLACEMENT_REVIEW") or "").strip().lower()
    if value in {"false", "true", "auto"}:
        return value
    return DEFAULT_FULL_FILE_REPLACEMENT_REVIEW_MODE


def create_configured_full_file_replacement_reviewer(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, Any] | None = None,
) -> FullFileReplacementReviewer:
    try:
        provider_name = resolve_sfe_router_provider(environ, default="openai")
    except ValueError:
        return DisabledFullFileReplacementReviewer()

    factory = _provider_factory_for(provider_name, provider_factories)
    if provider_name in ("openai", "openai-compatible"):
        from providers.openai_api import DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL

        return ConfiguredLLMFullFileReplacementReviewer(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",))
            or DEFAULT_OPENAI_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
        )
    if provider_name == CODEXCLI_SFE_PROVIDER:
        from providers.codexcli import DEFAULT_ROUTER_MODEL as DEFAULT_CODEXCLI_ROUTER_MODEL

        return ConfiguredLLMFullFileReplacementReviewer(
            provider=_instantiate_codexcli_provider(
                provider_name,
                factory,
                provider_factories,
                environ,
            ),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_CODEXCLI_ROUTER_MODEL",))
            or DEFAULT_CODEXCLI_ROUTER_MODEL,
            call_style="system_instruction",
        )
    if provider_name == "lemonade":
        from sfe.execution_mode_router import DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL

        return ConfiguredLLMFullFileReplacementReviewer(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"))
            or DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL,
            call_style="system_message",
        )
    if provider_name == "alibaba":
        from providers.alibaba import DEFAULT_ROUTER_MODEL as DEFAULT_ALIBABA_ROUTER_MODEL

        return ConfiguredLLMFullFileReplacementReviewer(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",))
            or DEFAULT_ALIBABA_ROUTER_MODEL,
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
        )
    if provider_name == "anthropic":
        from providers.anthropic import DEFAULT_ROUTER_MODEL as DEFAULT_ANTHROPIC_ROUTER_MODEL

        return ConfiguredLLMFullFileReplacementReviewer(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",))
            or DEFAULT_ANTHROPIC_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
        )
    if provider_name == OLLAMA_SFE_PROVIDER:
        from providers.ollama import DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL

        return ConfiguredLLMFullFileReplacementReviewer(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_OLLAMA_ROUTER_MODEL", "SFE_OLLAMA_MODEL"))
            or DEFAULT_OLLAMA_MODEL,
            call_style="system_message",
        )
    return DisabledFullFileReplacementReviewer()


def build_full_file_replacement_review_prompt(
    request: FullFileReplacementReviewRequest,
) -> str:
    payload = {
        "task_summary": request.task_summary,
        "target_path": request.target_path,
        "pass_number": request.pass_number,
        "pass_label": request.pass_label,
        "current_file_content": request.current_content,
        "proposed_replacement_content": request.proposed_replacement_content,
        "related_selected_file_paths": list(request.related_selected_file_paths),
        "required_output_schema": {
            "approve": True,
            "risk_level": "low",
            "reason": "Short reason.",
            "concerns": [],
        },
        "approval_rule": (
            "SFE applies only approve=true with risk_level low or medium. "
            "High risk or approve=false blocks the replacement."
        ),
        "review_rules": [
            "Return strict JSON only.",
            "Do not rewrite the file.",
            "Do not invent missing context.",
            "Approve coherent full-file rewrites that fit the task and current file.",
            "Reject unrelated, empty, truncated, destructive, syntactically corrupt, secret-bearing, or out-of-intent replacements.",
            "Be conservative but not overly rigid.",
        ],
    }
    return (
        "Review this proposed full-file replacement after a hunk preimage "
        "mismatch. Return strict JSON only.\n\nReview payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def parse_full_file_replacement_review_json(
    text: str,
) -> FullFileReplacementReviewDecision:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _error_decision("invalid_json", raw_answer=text)
    if not isinstance(payload, dict):
        return _error_decision("review_json_not_object", raw_answer=text)
    approve = payload.get("approve")
    risk_level = payload.get("risk_level")
    reason = payload.get("reason")
    concerns = payload.get("concerns", [])
    if not isinstance(approve, bool):
        return _error_decision("invalid_approve", raw_answer=text)
    if risk_level not in {"low", "medium", "high"}:
        return _error_decision("invalid_risk_level", raw_answer=text)
    if not isinstance(reason, str) or not reason.strip():
        return _error_decision("invalid_reason", raw_answer=text)
    if not isinstance(concerns, list) or not all(
        isinstance(item, str) for item in concerns
    ):
        return _error_decision("invalid_concerns", raw_answer=text)
    return FullFileReplacementReviewDecision(
        approve=approve,
        risk_level=risk_level,
        reason=reason.strip(),
        concerns=tuple(item for item in concerns if item.strip()),
        raw_answer=text,
    )


def _error_decision(
    reason: str,
    *,
    raw_answer: str | None = None,
) -> FullFileReplacementReviewDecision:
    return FullFileReplacementReviewDecision(
        approve=False,
        risk_level="high",
        reason=reason,
        raw_answer=raw_answer,
        error=reason,
    )
