"""LLM-backed execution-mode routing for SFE runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

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


EXECUTION_MODE_CONSOLE_OUTPUT = "console_output"
EXECUTION_MODE_EXTERNAL_ACTION = "external_action"
EXECUTION_MODE_WORKSPACE_WRITE = "workspace_write"
EXECUTION_MODES = frozenset(
    {
        EXECUTION_MODE_CONSOLE_OUTPUT,
        EXECUTION_MODE_EXTERNAL_ACTION,
        EXECUTION_MODE_WORKSPACE_WRITE,
    }
)
EXECUTION_MODE_ROUTER_MAX_TOKENS = 300
DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL = "Qwen3-0.6B-GGUF"
EXECUTION_MODE_ROUTER_SYSTEM_INSTRUCTION = (
    "You are the SFE execution-mode router. Decide semantically whether the "
    "user task should be resolved by printing a natural language response in "
    "the console, or by writing files in the workspace. Do not use keyword "
    "matching. Do not execute the task. Return exactly one JSON object with "
    "keys execution_mode, reason, and optional confidence. execution_mode "
    "must be console_output, workspace_write, or external_action. "
    "console_output means no "
    "worktree, no patch, and no workspace write is needed. workspace_write "
    "means the task requires creating, modifying, or deleting workspace files. "
    "external_action means the task requires acting outside the workspace, "
    "such as sending email, creating calendar events, publishing something, "
    "opening pull requests or issues, or calling external services, tools, or APIs. "
    "Do not return Markdown, comments, or extra text."
)


@dataclass(frozen=True)
class ExecutionModeDecision:
    execution_mode: str
    reason: str
    confidence: float | None = None
    provider_name: str | None = None
    model: str | None = None
    provider_calls_made: int = 0


class ExecutionModeRouterError(RuntimeError):
    def __init__(self, category: str, reason: str) -> None:
        self.category = category
        self.reason = reason
        super().__init__(reason)


class ExecutionModeRouter(Protocol):
    provider_name: str | None
    model: str | None

    def decide(self, *, task: str) -> ExecutionModeDecision:
        ...


class ConfiguredLLMExecutionModeRouter:
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

    def decide(self, *, task: str) -> ExecutionModeDecision:
        health = self.provider.health()
        if not health.get("ok"):
            raise ExecutionModeRouterError(
                "execution_mode_router_not_configured",
                "configured execution-mode router is not available",
            )
        try:
            response = _call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=build_execution_mode_prompt(task=task),
                model=self.model,
                max_tokens=EXECUTION_MODE_ROUTER_MAX_TOKENS,
            )
        except self.missing_key_errors as exc:
            raise ExecutionModeRouterError(
                "execution_mode_router_not_configured",
                "configured execution-mode router is not available",
            ) from exc
        except TimeoutError as exc:
            raise ExecutionModeRouterError(
                "execution_mode_router_timeout",
                "configured execution-mode router timed out",
            ) from exc
        except self.provider_error_types as exc:
            raise ExecutionModeRouterError(
                "execution_mode_router_provider_error",
                "configured execution-mode router provider failed",
            ) from exc
        except LemonadeProviderError as exc:
            raise ExecutionModeRouterError(
                f"execution_mode_router_{exc.error_category}",
                "configured execution-mode router provider failed",
            ) from exc
        except Exception as exc:
            raise ExecutionModeRouterError(
                "execution_mode_router_provider_error",
                "configured execution-mode router provider failed",
            ) from exc

        parsed = parse_execution_mode_router_output(_extract_answer(response))
        return ExecutionModeDecision(
            execution_mode=parsed.execution_mode,
            reason=parsed.reason,
            confidence=parsed.confidence,
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class ProviderConfigurationErrorExecutionModeRouter:
    provider_name = "invalid"
    model = None

    def decide(self, *, task: str) -> ExecutionModeDecision:
        del task
        raise ExecutionModeRouterError(
            "provider_configuration_error",
            "invalid SFE provider configuration",
        )


class UnsupportedProviderExecutionModeRouter:
    model = None

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def decide(self, *, task: str) -> ExecutionModeDecision:
        del task
        raise ExecutionModeRouterError(
            "execution_mode_router_provider_not_supported",
            "configured provider is not supported for execution-mode routing",
        )


def create_configured_execution_mode_router(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, Any] | None = None,
) -> ExecutionModeRouter:
    try:
        provider_name = resolve_sfe_provider(environ, default="openai")
    except ValueError:
        return ProviderConfigurationErrorExecutionModeRouter()

    factory = _provider_factory_for(provider_name, provider_factories)
    if provider_name in ("openai", "openai-compatible"):
        return ConfiguredLLMExecutionModeRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",))
            or DEFAULT_OPENAI_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
        )
    if provider_name == "lemonade":
        return ConfiguredLLMExecutionModeRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"))
            or DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL,
            call_style="system_message",
        )
    if provider_name == "alibaba":
        return ConfiguredLLMExecutionModeRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",))
            or DEFAULT_ALIBABA_ROUTER_MODEL,
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
        )
    if provider_name == "anthropic":
        return ConfiguredLLMExecutionModeRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",))
            or DEFAULT_ANTHROPIC_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
        )
    return UnsupportedProviderExecutionModeRouter(provider_name)


def build_execution_mode_prompt(*, task: str) -> str:
    payload = {
        "task": task,
        "routing_question": (
            "Given this user task, should SFE resolve it by printing a "
            "response in the console, by writing files to the workspace, or "
            "by taking an external action outside the workspace?"
        ),
        "allowed_execution_modes": sorted(EXECUTION_MODES),
        "required_output_schema": {
            "execution_mode": "console_output|workspace_write|external_action",
            "reason": "short explanation",
            "confidence": 0.0,
        },
    }
    return (
        "Choose exactly one execution mode for this SFE /run task. Return "
        "strict JSON only.\n\nExecution-mode routing payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def parse_execution_mode_router_output(output: str) -> ExecutionModeDecision:
    try:
        parsed = json.loads(_strip_json_fence(output))
    except json.JSONDecodeError as exc:
        raise ExecutionModeRouterError(
            "invalid_execution_mode_router_response",
            "execution-mode router did not return valid JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise ExecutionModeRouterError(
            "invalid_execution_mode_router_response",
            "execution-mode router JSON was not an object",
        )
    execution_mode = str(parsed.get("execution_mode") or "")
    reason = str(parsed.get("reason") or "").strip()
    confidence = parsed.get("confidence")
    if execution_mode not in EXECUTION_MODES:
        raise ExecutionModeRouterError(
            "invalid_execution_mode_router_response",
            "execution-mode router execution_mode was invalid",
        )
    if not reason:
        raise ExecutionModeRouterError(
            "invalid_execution_mode_router_response",
            "execution-mode router reason was empty",
        )
    if confidence is not None:
        if not isinstance(confidence, int | float) or isinstance(confidence, bool):
            raise ExecutionModeRouterError(
                "invalid_execution_mode_router_response",
                "execution-mode router confidence was invalid",
            )
        confidence = float(confidence)
        if confidence < 0 or confidence > 1:
            raise ExecutionModeRouterError(
                "invalid_execution_mode_router_response",
                "execution-mode router confidence was out of range",
            )
    return ExecutionModeDecision(
        execution_mode=execution_mode,
        reason=reason,
        confidence=confidence,
    )


def _call_provider_chat(
    *,
    provider: Any,
    call_style: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    if call_style == "system_message":
        return provider.chat(
            [
                {"role": "system", "content": EXECUTION_MODE_ROUTER_SYSTEM_INSTRUCTION},
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
        system_instruction=EXECUTION_MODE_ROUTER_SYSTEM_INSTRUCTION,
    )


def _extract_answer(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"]).strip()
    return ""


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


def _provider_factory_for(
    provider_name: str,
    provider_factories: Mapping[str, Any] | None,
) -> Any:
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
