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
from providers.codexcli import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_CODEXCLI_EXECUTOR_MODEL,
    PROVIDER_NAME as CODEXCLI_PROVIDER_NAME,
    CodexCLIProvider,
)
from providers.google import (
    DEFAULT_MODEL as DEFAULT_GOOGLE_MODEL,
    GoogleAPIError,
    GoogleAPIProvider,
    MissingGoogleAPIKeyError,
)
from providers.lemonade import LemonadeProvider, LemonadeProviderError
from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from sfe.provider_progress import ProviderCallIdleTimeoutError
from sfe.provider_config import resolve_sfe_provider


DEFAULT_MAX_OUTPUT_TOKENS = 1500
DEFAULT_PATCH_OUTPUT_TOKENS = 12000
DEFAULT_LEMONADE_EXECUTOR_MODEL = "Qwen3.5-35B-A3B-GGUF"
READ_ONLY_SYSTEM_INSTRUCTION = (
    "You are the read-only SFE TUI executor. Answer only from the selected "
    "context and the user's task. Do not claim to edit files, run commands, "
    "or use tools."
)
CONSOLE_SYSTEM_INSTRUCTION = (
    "You are the SFE console_output executor. Answer the user's task directly "
    "and naturally for display in the TUI console. Use selected context when "
    "it is provided, but you may answer general questions without selected "
    "workspace context. Do not modify files, call tools, run commands, or "
    "claim to have changed the workspace. Do not produce a patch, diff, or "
    "file replacement JSON."
)
PATCH_SYSTEM_INSTRUCTION = (
    "You are the SFE TUI patch proposal executor. Return only a strict unified "
    "diff/git diff that SFE can apply. The response must start with a diff "
    "header like diff --git a/<relative-path> b/<relative-path>; do not start "
    "with {, [, text, or Markdown. Do not return JSON. Do not return an edits "
    "array. Do not return Markdown. Do not wrap the patch in a code fence. Do "
    "not explain the patch. Do not include a file manifest or any prose before "
    "or after the diff. All paths must be relative to the workspace and use "
    "a/<relative-path> and b/<relative-path> diff paths. For a new file, use "
    "a complete Git-style new-file unified diff that still starts with "
    "diff --git a/<relative-path> b/<relative-path>; do not start the response "
    "with --- /dev/null. Use --- /dev/null and +++ b/<relative-path> file "
    "headers inside the file section, plus normal unified diff hunks. Hunk header counts must "
    "exactly match the hunk body. For new files, use @@ -0,0 +1,N @@ where N "
    "exactly equals the number of added + lines in that hunk. Every added "
    "content line must start with +. Do not guess hunk counts; if unsure, keep "
    "files smaller and hunks simpler. Include normal unified diff hunks for "
    "every changed file. Do not create files under .git, vendor, var, cache, "
    "node_modules, or generated/sensitive directories. Do not propose deletes, "
    "renames, mode-only changes, binary patches, or symlink changes. If no safe "
    "unified diff can be proposed, return no text."
)


@dataclass(frozen=True)
class ExecutorResponse:
    answer: str | None
    error_category: str | None
    provider_calls_made: int
    provider_name: str | None = None
    response_diagnostics: dict[str, object] | None = None


class ReadOnlyExecutor(Protocol):
    provider_name: str

    def answer_console(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        ...

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

    def answer_console(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return self._execute_with_instruction(
            executor_payload,
            system_instruction=CONSOLE_SYSTEM_INSTRUCTION,
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
        user_prompt: str | None = None,
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
                user_prompt=user_prompt or _build_user_prompt(executor_payload),
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
        except ProviderCallIdleTimeoutError:
            return ExecutorResponse(
                answer=None,
                error_category="provider_idle_timeout",
                provider_calls_made=1,
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
                response_diagnostics=build_response_shape_diagnostics(
                    response,
                    provider_name=self.provider_name,
                ),
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


class CodexCLIReadOnlyExecutor(DirectProviderReadOnlyExecutor):
    """CodexCLI-backed executor for non-mutating TUI answer modes only."""

    def __init__(
        self,
        *,
        provider: CodexCLIProvider | None = None,
        model: str | None = None,
        provider_name: str = CODEXCLI_PROVIDER_NAME,
        environ: Mapping[str, str] | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        super().__init__(
            provider=provider or CodexCLIProvider(),
            provider_name=provider_name,
            model=(
                model
                or _first_env_value(environ, ("SFE_OPENAI_EXECUTOR_MODEL",))
                or DEFAULT_CODEXCLI_EXECUTOR_MODEL
            ),
            call_style="system_instruction",
            max_output_tokens=max_output_tokens,
            max_patch_output_tokens=0,
        )

    def propose_patch(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        del executor_payload
        return _unsupported_provider_response(self.provider_name)


class ProviderConfigurationErrorExecutor:
    """Executor that reports invalid TUI provider configuration safely."""

    provider_name = "invalid"

    def answer_console(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _configuration_error_response(self.provider_name)

    def execute(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _configuration_error_response(self.provider_name)

    def propose_patch(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _configuration_error_response(self.provider_name)


class UnsupportedProviderExecutor:
    """Executor that reports a valid provider not yet supported by the TUI."""

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def answer_console(self, executor_payload: dict[str, Any]) -> ExecutorResponse:
        return _unsupported_provider_response(self.provider_name)

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
    if provider_name == CODEXCLI_PROVIDER_NAME:
        return CodexCLIReadOnlyExecutor(
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
    if provider_name == "google":
        return DirectProviderReadOnlyExecutor(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(environ, ("SFE_GOOGLE_MODEL",))
                or DEFAULT_GOOGLE_MODEL
            ),
            call_style="system_message",
            missing_key_errors=(MissingGoogleAPIKeyError,),
            provider_error_types=(GoogleAPIError,),
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
    if provider_name == CODEXCLI_PROVIDER_NAME:
        return CodexCLIProvider
    if provider_name == "lemonade":
        return LemonadeProvider
    if provider_name == "alibaba":
        return AlibabaAPIProvider
    if provider_name == "anthropic":
        return AnthropicProvider
    if provider_name == "google":
        return GoogleAPIProvider
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


def _extract_answer(response: object) -> str:
    if not isinstance(response, dict):
        return ""
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


def build_response_shape_diagnostics(
    response: object,
    *,
    provider_name: str | None,
) -> dict[str, object]:
    """Return bounded structural metadata for an invalid provider response."""

    diagnostics: dict[str, object] = {
        "provider_name": provider_name,
        "response_object_type": type(response).__name__,
    }
    if isinstance(response, dict):
        diagnostics["top_level_keys"] = _safe_keys(response)
        diagnostics["choices_exists"] = "choices" in response
        choices = response.get("choices")
        diagnostics["choices_count"] = len(choices) if isinstance(choices, list) else None
        first_choice = choices[0] if isinstance(choices, list) and choices else None
        if isinstance(first_choice, dict):
            diagnostics["first_choice_keys"] = _safe_keys(first_choice)
            finish_reason = first_choice.get("finish_reason")
            diagnostics["finish_reason"] = (
                _safe_scalar(finish_reason) if finish_reason is not None else None
            )
            message = first_choice.get("message")
            if isinstance(message, dict):
                diagnostics["message_keys"] = _safe_keys(message)
                content_exists = "content" in message
                diagnostics["message_content_exists"] = content_exists
                content = message.get("content") if content_exists else None
                diagnostics["message_content_type"] = (
                    type(content).__name__ if content_exists else None
                )
                diagnostics["message_content_length"] = (
                    _safe_length(content) if content_exists else None
                )
            else:
                diagnostics["message_keys"] = ()
                diagnostics["message_content_exists"] = False
                diagnostics["message_content_type"] = None
                diagnostics["message_content_length"] = None
        else:
            diagnostics["first_choice_keys"] = ()
            diagnostics["finish_reason"] = None
            diagnostics["message_keys"] = ()
            diagnostics["message_content_exists"] = False
            diagnostics["message_content_type"] = None
            diagnostics["message_content_length"] = None

        output_text_exists = "output_text" in response
        diagnostics["output_text_exists"] = output_text_exists
        output_text = response.get("output_text") if output_text_exists else None
        diagnostics["output_text_type"] = (
            type(output_text).__name__ if output_text_exists else None
        )
        diagnostics["output_text_length"] = (
            _safe_length(output_text) if output_text_exists else None
        )
        error = response.get("error")
        diagnostics["error_exists"] = error is not None
        diagnostics["error_type"] = type(error).__name__ if error is not None else None
        diagnostics["error_keys"] = _safe_keys(error) if isinstance(error, dict) else ()
        status = response.get("status")
        diagnostics["status_exists"] = status is not None
        diagnostics["status_type"] = type(status).__name__ if status is not None else None
    return diagnostics


def _safe_keys(value: Mapping[object, object]) -> tuple[str, ...]:
    return tuple(sorted(_safe_key(key) for key in value.keys()))[:40]


def _safe_key(key: object) -> str:
    text = _redact_secret_like(str(key))
    return text if len(text) <= 80 else text[:77] + "..."


def _safe_scalar(value: object) -> str:
    text = _redact_secret_like(str(value))
    return text if len(text) <= 80 else text[:77] + "..."


def _safe_length(value: object) -> int | None:
    if isinstance(value, str | bytes | list | tuple | dict):
        return len(value)
    return None


def _redact_secret_like(text: str) -> str:
    lowered = text.lower()
    if "sk-" in lowered or "api_key" in lowered or "authorization" in lowered:
        return "[redacted]"
    return text
