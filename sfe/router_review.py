"""Shared configured-router JSON review plumbing for SFE surfaces."""

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
from providers.google import (
    DEFAULT_MODEL as DEFAULT_GOOGLE_MODEL,
    GoogleAPIError,
    GoogleAPIProvider,
    MissingGoogleAPIKeyError,
)
from providers.lemonade import LemonadeProvider, LemonadeProviderError
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from sfe.provider_progress import ProviderCallIdleTimeoutError
from sfe.provider_config import resolve_sfe_provider


DEFAULT_LEMONADE_ROUTER_MODEL = "Qwen3-0.6B-GGUF"
DEFAULT_RISK_LEVELS = frozenset({"low", "medium", "high"})


@dataclass(frozen=True)
class JsonReviewDecision:
    decision: str
    reason: str
    files_reviewed: tuple[str, ...]
    risk_level: str
    provider_name: str | None = None
    model: str | None = None


class RouterReviewError(RuntimeError):
    def __init__(self, category: str, reason: str) -> None:
        self.category = category
        self.reason = reason
        super().__init__(reason)


class JsonReviewer(Protocol):
    provider_name: str | None
    model: str | None

    def review(self, payload: dict[str, Any]) -> JsonReviewDecision:
        ...


PromptBuilder = Callable[[dict[str, Any]], str]
ProviderFactory = Callable[[], Any]


class DirectProviderJsonReviewer:
    def __init__(
        self,
        *,
        provider: Any,
        provider_name: str,
        model: str,
        call_style: str,
        system_instruction: str,
        prompt_builder: PromptBuilder,
        valid_decisions: set[str] | frozenset[str],
        max_tokens: int,
        missing_key_errors: tuple[type[Exception], ...] = (),
        provider_error_types: tuple[type[Exception], ...] = (),
        provider_error_classifier: Callable[[Exception], str | None] | None = None,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.call_style = call_style
        self.system_instruction = system_instruction
        self.prompt_builder = prompt_builder
        self.valid_decisions = frozenset(valid_decisions)
        self.max_tokens = max_tokens
        self.missing_key_errors = missing_key_errors
        self.provider_error_types = provider_error_types
        self.provider_error_classifier = provider_error_classifier

    def review(self, payload: dict[str, Any]) -> JsonReviewDecision:
        health = self.provider.health()
        if not health.get("ok"):
            raise RouterReviewError("router_not_configured", "configured router is not available")
        try:
            response = call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=self.prompt_builder(payload),
                model=self.model,
                max_tokens=self.max_tokens,
                system_instruction=self.system_instruction,
            )
        except self.missing_key_errors as exc:
            raise RouterReviewError("router_not_configured", "configured router is not available") from exc
        except ProviderCallIdleTimeoutError as exc:
            raise RouterReviewError(
                "router_provider_idle_timeout",
                "configured router provider stopped producing progress",
            ) from exc
        except TimeoutError as exc:
            raise RouterReviewError("router_timeout", "configured router timed out") from exc
        except self.provider_error_types as exc:
            raise RouterReviewError("router_provider_error", "configured router provider failed") from exc
        except Exception as exc:
            category = classify_provider_error(exc, self.provider_error_classifier)
            raise RouterReviewError(category, "configured router provider failed") from exc

        output = extract_answer(response)
        decision = parse_json_review_decision(output, valid_decisions=self.valid_decisions)
        return JsonReviewDecision(
            decision=decision.decision,
            reason=decision.reason,
            files_reviewed=decision.files_reviewed,
            risk_level=decision.risk_level,
            provider_name=self.provider_name,
            model=self.model,
        )


class ProviderConfigurationErrorJsonReviewer:
    provider_name = "invalid"
    model = None

    def review(self, payload: dict[str, Any]) -> JsonReviewDecision:
        del payload
        raise RouterReviewError("provider_configuration_error", "invalid SFE provider configuration")


class UnsupportedProviderJsonReviewer:
    model = None

    def __init__(
        self,
        provider_name: str,
        *,
        reason: str = "configured provider is not supported for router review",
    ) -> None:
        self.provider_name = provider_name
        self.reason = reason

    def review(self, payload: dict[str, Any]) -> JsonReviewDecision:
        del payload
        raise RouterReviewError("provider_not_supported", self.reason)


def create_configured_router_json_reviewer(
    *,
    system_instruction: str,
    prompt_builder: PromptBuilder,
    valid_decisions: set[str] | frozenset[str],
    max_tokens: int,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, ProviderFactory] | None = None,
    unsupported_provider_reason: str = "configured provider is not supported for router review",
) -> JsonReviewer:
    try:
        provider_name = resolve_sfe_provider(environ, default="openai")
    except ValueError:
        return ProviderConfigurationErrorJsonReviewer()

    provider_factory = provider_factory_for(
        provider_name,
        provider_factories=provider_factories,
    )
    common = {
        "system_instruction": system_instruction,
        "prompt_builder": prompt_builder,
        "valid_decisions": valid_decisions,
        "max_tokens": max_tokens,
    }
    if provider_name in ("openai", "openai-compatible"):
        return DirectProviderJsonReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",))
                or DEFAULT_OPENAI_ROUTER_MODEL
            ),
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
            **common,
        )
    if provider_name == "lemonade":
        return DirectProviderJsonReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                first_env_value(environ, ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"))
                or DEFAULT_LEMONADE_ROUTER_MODEL
            ),
            call_style="system_message",
            provider_error_classifier=classify_lemonade_error,
            **common,
        )
    if provider_name == "alibaba":
        return DirectProviderJsonReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",))
                or DEFAULT_ALIBABA_ROUTER_MODEL
            ),
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
            **common,
        )
    if provider_name == "anthropic":
        return DirectProviderJsonReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",))
                or DEFAULT_ANTHROPIC_ROUTER_MODEL
            ),
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
            **common,
        )
    if provider_name == "google":
        return DirectProviderJsonReviewer(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                first_env_value(environ, ("SFE_GOOGLE_MODEL",))
                or DEFAULT_GOOGLE_MODEL
            ),
            call_style="system_message",
            missing_key_errors=(MissingGoogleAPIKeyError,),
            provider_error_types=(GoogleAPIError,),
            **common,
        )
    return UnsupportedProviderJsonReviewer(
        provider_name,
        reason=unsupported_provider_reason,
    )


def provider_factory_for(
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
    if provider_name == "google":
        return GoogleAPIProvider
    return lambda: None


def call_provider_chat(
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


def parse_json_review_decision(
    output: str,
    *,
    valid_decisions: set[str] | frozenset[str],
    valid_risk_levels: set[str] | frozenset[str] = DEFAULT_RISK_LEVELS,
) -> JsonReviewDecision:
    try:
        parsed = json.loads(strip_json_fence(output))
    except json.JSONDecodeError as exc:
        raise RouterReviewError("invalid_router_response", "router did not return valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RouterReviewError("invalid_router_response", "router JSON was not an object")
    decision = str(parsed.get("decision") or "")
    reason = str(parsed.get("reason") or "").strip()
    risk_level = str(parsed.get("risk_level") or "")
    files = parsed.get("files_reviewed") or []
    if decision not in valid_decisions:
        raise RouterReviewError("invalid_router_response", "router decision was invalid")
    if risk_level not in valid_risk_levels:
        raise RouterReviewError("invalid_router_response", "router risk_level was invalid")
    if not reason:
        raise RouterReviewError("invalid_router_response", "router reason was empty")
    if not isinstance(files, list):
        raise RouterReviewError(
            "invalid_router_response",
            f"router files_reviewed was invalid (expected list, got {type(files).__name__})",
        )
    return JsonReviewDecision(
        decision=decision,
        reason=reason,
        files_reviewed=tuple(str(item) for item in files),
        risk_level=risk_level,
    )


def strip_json_fence(output: str) -> str:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def extract_answer(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"]).strip()
    return ""


def classify_provider_error(
    exc: Exception,
    classifier: Callable[[Exception], str | None] | None,
) -> str:
    if classifier is None:
        return "router_provider_error"
    return classifier(exc) or "router_provider_error"


def classify_lemonade_error(exc: Exception) -> str | None:
    if isinstance(exc, LemonadeProviderError):
        return f"router_{exc.error_category}"
    return None


def first_env_value(
    environ: Mapping[str, str] | None,
    names: tuple[str, ...],
) -> str | None:
    env = os.environ if environ is None else environ
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None
