"""Read-only executor adapters for the SFE-aware TUI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from providers.alibaba import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_ALIBABA_EXECUTOR_MODEL,
    AlibabaAPIError,
    AlibabaAPIProvider,
    MissingAlibabaAPIKeyError,
)
from providers.anthropic import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_ANTHROPIC_EXECUTOR_MODEL,
    AnthropicAPIError,
    AnthropicProvider,
    MissingAnthropicAPIKeyError,
)
from providers.lemonade import LemonadeProvider, LemonadeProviderError
from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from sfe.provider_config import resolve_sfe_provider


DEFAULT_MAX_OUTPUT_TOKENS = 1500
DEFAULT_PATCH_OUTPUT_TOKENS = 4000
DEFAULT_LEMONADE_EXECUTOR_MODEL = "Qwen3.5-35B-A3B-GGUF"
READ_ONLY_SYSTEM_INSTRUCTION = (
    "You are the read-only SFE TUI executor. Answer only from the selected "
    "context and the user's task. Do not claim to edit files, run commands, "
    "or use tools."
)
PATCH_SYSTEM_INSTRUCTION = (
    "You are the SFE TUI patch proposal executor. Propose a unified diff when "
    "a safe concrete edit can be made from the selected context. Do not use "
    "markdown fences when a clean diff is possible. If no safe diff can be "
    "proposed, explain why briefly. Do not claim files were modified. Do not "
    "invent file contents outside the selected context."
)


@dataclass(frozen=True)
class ExecutorResponse:
    answer: str | None
    error_category: str | None
    provider_calls_made: int
    provider_name: str | None = None


class ReadOnlyExecutor(Protocol):
    provider_name: str

    def execute(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        ...

    def propose_patch(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        ...


class DirectProviderReadOnlyExecutor:
    """Small direct read-only executor for selected TUI context."""

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
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        max_patch_output_tokens: int = DEFAULT_PATCH_OUTPUT_TOKENS,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.call_style = call_style
        self.missing_key_errors = missing_key_errors
        self.provider_error_types = provider_error_types
        self.provider_error_classifier = provider_error_classifier
        self.max_output_tokens = max_output_tokens
        self.max_patch_output_tokens = max_patch_output_tokens

    def execute(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return self._execute_with_instruction(
            executor_payload,
            system_instruction=READ_ONLY_SYSTEM_INSTRUCTION,
            max_tokens=self.max_output_tokens,
        )

    def propose_patch(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return self._execute_with_instruction(
            executor_payload,
            system_instruction=PATCH_SYSTEM_INSTRUCTION,
            max_tokens=self.max_patch_output_tokens,
        )

    def _execute_with_instruction(
        self,
        executor_payload: dict[str, Any],
        *,
        system_instruction: str,
        max_tokens: int,
    ) -> ExecutorResponse:
        health = self.provider.health()
        if not health.get("ok"):
            return ExecutorResponse(
                answer=None,
                error_category="provider_not_configured",
                provider_calls_made=0,
                provider_name=self.provider_name,
            )
        try:
            response = _call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=_build_user_prompt(executor_payload),
                model=self.model,
                max_tokens=max_tokens,
                system_instruction=system_instruction,
            )
        except self.missing_key_errors:
            return ExecutorResponse(
                answer=None,
                error_category="provider_not_configured",
                provider_calls_made=0,
                provider_name=self.provider_name,
            )
        except TimeoutError:
            return ExecutorResponse(
                answer=None,
                error_category="timeout",
                provider_calls_made=1,
                provider_name=self.provider_name,
            )
        except self.provider_error_types:
            return ExecutorResponse(
                answer=None,
                error_category="provider_error",
                provider_calls_made=1,
                provider_name=self.provider_name,
            )
        except Exception as exc:
            error_category = _classify_provider_error(
                exc,
                self.provider_error_classifier,
            )
            return ExecutorResponse(
                answer=None,
                error_category=error_category,
                provider_calls_made=1,
                provider_name=self.provider_name,
            )

        answer = _extract_answer(response)
        if not answer:
            return ExecutorResponse(
                answer=None,
                error_category="invalid_response",
                provider_calls_made=1,
                provider_name=self.provider_name,
            )
        return ExecutorResponse(
            answer=answer,
            error_category=None,
            provider_calls_made=1,
            provider_name=self.provider_name,
        )


class OpenAIReadOnlyExecutor(DirectProviderReadOnlyExecutor):
    """Small OpenAI-backed read-only executor for selected TUI context."""

    def __init__(
        self,
        *,
        provider: OpenAIAPIProvider | None = None,
        model: str | None = None,
        provider_name: str = "openai",
        environ: Mapping[str, str] | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
        max_patch_output_tokens: int = DEFAULT_PATCH_OUTPUT_TOKENS,
    ) -> None:
        super().__init__(
            provider=provider or OpenAIAPIProvider(),
            provider_name=provider_name,
            model=(
                model
                or _first_env_value(environ, ("SFE_OPENAI_EXECUTOR_MODEL",))
                or DEFAULT_EXECUTOR_MODEL
            ),
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
            max_output_tokens=max_output_tokens,
            max_patch_output_tokens=max_patch_output_tokens,
        )


class ProviderConfigurationErrorExecutor:
    """Executor that reports invalid TUI provider configuration safely."""

    provider_name = "invalid"

    def execute(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _configuration_error_response(self.provider_name)

    def propose_patch(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _configuration_error_response(self.provider_name)


class UnsupportedProviderExecutor:
    """Executor that reports a valid provider not yet supported by the TUI."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def execute(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _unsupported_provider_response(self.provider_name)

    def propose_patch(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _unsupported_provider_response(self.provider_name)


ProviderFactory = Callable[[], Any]


def create_tui_executor(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, ProviderFactory] | None = None,
) -> ReadOnlyExecutor:
    """Create the DirectBackend TUI executor selected by SFE_PROVIDER."""
    try:
        provider_name = resolve_sfe_provider(environ, default="openai")
    except ValueError:
        return ProviderConfigurationErrorExecutor()

    provider_factory = _provider_factory(
        provider_name,
        provider_factories=provider_factories,
    )
    if provider_name in ("openai", "openai-compatible"):
        return OpenAIReadOnlyExecutor(
            provider=provider_factory(),
            provider_name=provider_name,
            environ=environ,
        )
    if provider_name == "lemonade":
        return DirectProviderReadOnlyExecutor(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(
                    environ,
                    (
                        "SFE_LEMONADE_EXECUTOR_MODEL",
                        "SFE_LEMONADE_MODEL",
                        "SFE_EXECUTOR_MODEL",
                    ),
                )
                or DEFAULT_LEMONADE_EXECUTOR_MODEL
            ),
            call_style="system_message",
            provider_error_classifier=_classify_lemonade_error,
        )
    if provider_name == "alibaba":
        return DirectProviderReadOnlyExecutor(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(environ, ("SFE_ALIBABA_EXECUTOR_MODEL",))
                or DEFAULT_ALIBABA_EXECUTOR_MODEL
            ),
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
        )
    if provider_name == "anthropic":
        return DirectProviderReadOnlyExecutor(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(environ, ("SFE_ANTHROPIC_EXECUTOR_MODEL",))
                or DEFAULT_ANTHROPIC_EXECUTOR_MODEL
            ),
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
        )
    return UnsupportedProviderExecutor(provider_name)


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


def _configuration_error_response(provider_name: str) -> ExecutorResponse:
    return ExecutorResponse(
        answer=None,
        error_category="provider_configuration_error",
        provider_calls_made=0,
        provider_name=provider_name,
    )


def _unsupported_provider_response(provider_name: str) -> ExecutorResponse:
    return ExecutorResponse(
        answer=None,
        error_category="provider_not_supported",
        provider_calls_made=0,
        provider_name=provider_name,
    )


def _classify_provider_error(
    exc: Exception,
    classifier: Callable[[Exception], str | None] | None,
) -> str:
    if classifier is None:
        return "provider_error"
    return classifier(exc) or "provider_error"


def _classify_lemonade_error(exc: Exception) -> str | None:
    if isinstance(exc, LemonadeProviderError):
        return exc.error_category
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


def _build_user_prompt(executor_payload: dict[str, Any]) -> str:
    instructions = executor_payload.get("instructions") or []
    task = executor_payload.get("task")
    selected_segments = executor_payload.get("selected_context_segments") or []
    instruction_text = "\n".join(
        str(item.text) for item in instructions if getattr(item, "text", "")
    )
    task_text = str(getattr(task, "text", "") or "")
    context_parts = [
        f"[{segment.id}]\n{segment.text}"
        for segment in selected_segments
        if getattr(segment, "text", "")
    ]
    return "\n\n".join(
        part
        for part in (
            "Protected instructions:\n" + instruction_text,
            "User task:\n" + task_text,
            "Selected context:\n" + "\n\n".join(context_parts),
        )
        if part.strip()
    )


def _extract_answer(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if content is not None:
                    return str(content).strip()
    return ""
