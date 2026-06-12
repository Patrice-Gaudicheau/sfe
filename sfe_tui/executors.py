"""Read-only executor adapters for the SFE-aware TUI."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
    CodexCLIProvider,
)
from providers.google import (
    DEFAULT_MODEL as DEFAULT_GOOGLE_MODEL,
    GoogleAPIError,
    GoogleAPIProvider,
    MissingGoogleAPIKeyError,
)
from providers.lemonade import LemonadeProvider, LemonadeProviderError
from providers.ollama import (
    DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL,
    OllamaProvider,
    OllamaProviderError,
)
from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from sfe.provider_progress import (
    ProviderCallIdleTimeoutError,
    resolve_provider_idle_timeout_seconds,
)
from sfe.provider_config import (
    CODEXCLI_SFE_PROVIDER,
    OLLAMA_SFE_PROVIDER,
    resolve_sfe_executor_provider,
)


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
    "not explain the patch. Do not modify files, run commands, or use tools; "
    "generate a patch proposal only. Do not include a file manifest or any prose "
    "before or after the diff. All paths must be relative to the workspace and use "
    "a/<relative-path> and b/<relative-path> diff paths. For a new file, use "
    "a complete Git-style new-file unified diff that still starts with "
    "diff --git a/<relative-path> b/<relative-path>; do not start the response "
    "with --- /dev/null. Use --- /dev/null and +++ b/<relative-path> file "
    "headers inside the file section, plus normal unified diff hunks. Hunk header counts must "
    "exactly match the hunk body. For each hunk, old_count must equal the "
    "number of context lines plus removed lines. For each hunk, new_count must "
    "equal the number of context lines plus added lines. Do not guess hunk "
    "counts. Recount the hunk body before writing the hunk header. Prefer small "
    "localized hunks when possible, except when later full-file replacement "
    "guidance marks a small fully provided file as eligible or strongly "
    "preferred. For new files, use @@ -0,0 +1,N @@ where N "
    "exactly equals the number of added + lines in that hunk. Every added "
    "content line must start with +. Do not claim to inspect, read, or rely on "
    "workspace files unless they appear in Selected context. If Selected context "
    "is none and the task asks for a path, treat that path as absent and create "
    "it as a new file; do not emit a modification hunk for an absent file. If "
    "unsure, keep files smaller and hunks "
    "simpler. Include normal unified diff hunks for every changed file. Do not "
    "create files under .git, vendor, var, cache, "
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
        provider_idle_timeout_seconds: float | None = None,
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
        self.provider_idle_timeout_seconds = provider_idle_timeout_seconds

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
        model: str | None = None,
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
                model=model or self.model,
                max_tokens=max_tokens,
                system_instruction=system_instruction,
                idle_timeout_seconds=self.provider_idle_timeout_seconds,
                provider_role="executor",
                executor_cwd=_executor_working_directory(executor_payload),
            )
        except self.missing_key_errors:
            return ExecutorResponse(
                answer=None,
                error_category="provider_not_configured",
                provider_calls_made=0,
                provider_name=self.provider_name,
            )
        except ProviderCallIdleTimeoutError as exc:
            return ExecutorResponse(
                answer=None,
                error_category="provider_idle_timeout",
                provider_calls_made=1,
                provider_name=self.provider_name,
                response_diagnostics=_provider_timeout_response_diagnostics(
                    exc,
                    provider_name=self.provider_name,
                    model=model or self.model,
                    role="executor",
                    idle_timeout_seconds=self.provider_idle_timeout_seconds,
                ),
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
            response_diagnostics=_successful_response_diagnostics(
                response,
                provider_name=self.provider_name,
            ),
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
            provider_idle_timeout_seconds=resolve_provider_idle_timeout_seconds(
                role="executor",
                provider_name=provider_name,
                environ=environ,
            ),
        )


class CodexCLIReadOnlyExecutor(DirectProviderReadOnlyExecutor):
    """CodexCLI-backed executor for TUI answers and patch proposals."""

    def __init__(
        self,
        *,
        provider: CodexCLIProvider | None = None,
        model: str | None = None,
        provider_name: str = CODEXCLI_SFE_PROVIDER,
        environ: Mapping[str, str] | None = None,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        super().__init__(
            provider=provider
            or CodexCLIProvider(
                reasoning_effort=_first_env_value(
                    environ,
                    ("SFE_CODEXCLI_EXECUTOR_EFFORT", "SFE_CODEXCLI_REASONING_EFFORT"),
                )
            ),
            provider_name=provider_name,
            model=(
                model
                or _first_env_value(environ, ("SFE_CODEXCLI_EXECUTOR_MODEL",))
                or DEFAULT_CODEXCLI_EXECUTOR_MODEL
            ),
            call_style="system_instruction",
            max_output_tokens=max_output_tokens,
            max_patch_output_tokens=DEFAULT_PATCH_OUTPUT_TOKENS,
            provider_idle_timeout_seconds=resolve_provider_idle_timeout_seconds(
                role="executor",
                provider_name=provider_name,
                environ=environ,
            ),
        )


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
    """Create the DirectBackend TUI executor selected by the executor provider config."""
    try:
        provider_name = resolve_sfe_executor_provider(environ, default="openai")
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
    if provider_name == CODEXCLI_SFE_PROVIDER:
        return CodexCLIReadOnlyExecutor(
            provider=_instantiate_codexcli_provider(
                provider_name,
                provider_factory,
                provider_factories,
                environ,
            ),
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
            provider_idle_timeout_seconds=resolve_provider_idle_timeout_seconds(
                role="executor",
                provider_name=provider_name,
                environ=environ,
            ),
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
            provider_idle_timeout_seconds=resolve_provider_idle_timeout_seconds(
                role="executor",
                provider_name=provider_name,
                environ=environ,
            ),
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
            provider_idle_timeout_seconds=resolve_provider_idle_timeout_seconds(
                role="executor",
                provider_name=provider_name,
                environ=environ,
            ),
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
            provider_idle_timeout_seconds=resolve_provider_idle_timeout_seconds(
                role="executor",
                provider_name=provider_name,
                environ=environ,
            ),
        )
    if provider_name == OLLAMA_SFE_PROVIDER:
        return DirectProviderReadOnlyExecutor(
            provider=provider_factory(),
            provider_name=provider_name,
            model=(
                _first_env_value(
                    environ,
                    ("SFE_OLLAMA_EXECUTOR_MODEL", "SFE_OLLAMA_MODEL"),
                )
                or DEFAULT_OLLAMA_MODEL
            ),
            call_style="system_message",
            provider_error_classifier=_classify_ollama_error,
            provider_idle_timeout_seconds=resolve_provider_idle_timeout_seconds(
                role="executor",
                provider_name=provider_name,
                environ=environ,
            ),
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
    if provider_name == CODEXCLI_SFE_PROVIDER:
        return CodexCLIProvider
    if provider_name == "lemonade":
        return LemonadeProvider
    if provider_name == "alibaba":
        return AlibabaAPIProvider
    if provider_name == "anthropic":
        return AnthropicProvider
    if provider_name == "google":
        return GoogleAPIProvider
    if provider_name == OLLAMA_SFE_PROVIDER:
        return OllamaProvider
    return lambda: None


def _instantiate_codexcli_provider(
    provider_name: str,
    provider_factory: ProviderFactory,
    provider_factories: Mapping[str, ProviderFactory] | None,
    environ: Mapping[str, str] | None,
) -> Any:
    if provider_factories and provider_name in provider_factories:
        return provider_factory()
    return provider_factory(
        reasoning_effort=_first_env_value(
            environ,
            ("SFE_CODEXCLI_EXECUTOR_EFFORT", "SFE_CODEXCLI_REASONING_EFFORT"),
        )
    )


def _call_provider_chat(
    *,
    provider: Any,
    call_style: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
    system_instruction: str,
    idle_timeout_seconds: float | None,
    provider_role: str,
    executor_cwd: Path | None = None,
) -> dict[str, Any]:
    codex_kwargs: dict[str, object] = {}
    if executor_cwd is not None and isinstance(provider, CodexCLIProvider):
        codex_kwargs["cwd"] = executor_cwd
    if call_style == "system_message":
        return provider.chat(
            [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            max_tokens=max_tokens,
            temperature=None,
            idle_timeout_seconds=idle_timeout_seconds,
            provider_role=provider_role,
            **codex_kwargs,
        )
    return provider.chat(
        [{"role": "user", "content": user_prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=None,
        system_instruction=system_instruction,
        idle_timeout_seconds=idle_timeout_seconds,
        provider_role=provider_role,
        **codex_kwargs,
    )


def _executor_working_directory(executor_payload: dict[str, Any]) -> Path | None:
    value = executor_payload.get("executor_working_directory")
    if not isinstance(value, str) or not value.strip():
        return None
    return Path(value).expanduser().resolve()


def _successful_response_diagnostics(
    response: object,
    *,
    provider_name: str | None,
) -> dict[str, object] | None:
    if not isinstance(response, Mapping):
        return None
    codexcli = response.get("codexcli")
    if not isinstance(codexcli, Mapping):
        return None
    provider_diagnostics: dict[str, object] = {
        key: codexcli[key]
        for key in (
            "provider",
            "model",
            "latency_ms",
            "thread_id",
            "command",
            "cwd",
            "max_tokens_requested",
            "temperature_requested",
            "returncode",
            "stdout_length",
            "stderr_length",
            "stderr_present",
        )
        if key in codexcli
    }
    parser_diagnostics = codexcli.get("parser_diagnostics")
    if isinstance(parser_diagnostics, Mapping):
        provider_diagnostics["parser_diagnostics"] = dict(parser_diagnostics)
    return {
        "provider_name": provider_name,
        "provider_diagnostics": provider_diagnostics,
    }


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


def _provider_timeout_response_diagnostics(
    exc: ProviderCallIdleTimeoutError,
    *,
    provider_name: str | None,
    model: str | None,
    role: str,
    idle_timeout_seconds: float | None,
) -> dict[str, object]:
    diagnostics = dict(getattr(exc, "diagnostics", {}) or {})
    diagnostics.setdefault("provider", getattr(exc, "provider", provider_name))
    diagnostics.setdefault("model", getattr(exc, "model", model))
    diagnostics.setdefault("role", role)
    diagnostics.setdefault("call_id", getattr(exc, "call_id", None))
    diagnostics.setdefault(
        "idle_timeout_seconds",
        getattr(exc, "idle_timeout_seconds", idle_timeout_seconds),
    )
    diagnostics.setdefault("timeout_kind", "idle")
    return {
        "provider_name": provider_name,
        "error_type": type(exc).__name__,
        "provider_timeout_diagnostics": diagnostics,
    }


def _classify_lemonade_error(exc: Exception) -> str | None:
    if isinstance(exc, LemonadeProviderError):
        return exc.error_category
    return None


def _classify_ollama_error(exc: Exception) -> str | None:
    if isinstance(exc, OllamaProviderError):
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
    context_text = "\n\n".join(context_parts) if context_parts else "none"
    multi_pass_text = _build_multi_pass_prompt_section(
        executor_payload.get("multi_pass")
    )
    full_file_replacement_text = _format_full_file_replacement_guidance(
        executor_payload.get("full_file_replacement_guidance")
    )
    return "\n\n".join(
        part
        for part in (
            "Protected instructions:\n" + instruction_text,
            "User task:\n" + task_text,
            multi_pass_text,
            full_file_replacement_text,
            "Selected context:\n" + context_text,
        )
        if part.strip()
    )


def _build_multi_pass_prompt_section(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    mode = value.get("mode")
    if mode == "batch":
        allowed_files = _format_prompt_list(value.get("allowed_files"))
        completed_files = _format_prompt_list(value.get("completed_files"))
        validation_notes = _format_prompt_list(value.get("validation_notes"))
        current_file_context = _format_current_file_context(
            value.get("current_allowed_file_context")
        )
        full_file_guidance = _format_full_file_replacement_guidance(
            value.get("full_file_replacement_guidance")
        )
        return "\n".join(
            [
                "Multi-pass batch constraints:",
                f"Project summary: {value.get('project_summary') or ''}",
                f"Batch id: {value.get('batch_id') or ''}",
                f"Batch title: {value.get('batch_title') or ''}",
                f"Batch goal: {value.get('batch_goal') or ''}",
                "Allowed files for this batch:",
                allowed_files or "- none",
                "Already completed/promoted files:",
                completed_files or "- none",
                "Current workspace state for allowed files:",
                current_file_context or "- none",
                full_file_guidance,
                "Validation notes:",
                validation_notes or "- none",
                "Return a strict git diff for this batch only. Do not create, "
                "modify, delete, rename, or mention patch entries for files "
                "outside the allowed files list.",
            ]
        )
    return ""


def _format_prompt_list(value: object) -> str:
    if not isinstance(value, tuple | list):
        return ""
    return "\n".join(f"- {item}" for item in value if isinstance(item, str))


def _format_current_file_context(value: object) -> str:
    if not isinstance(value, tuple | list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        path = item.get("path")
        text = item.get("text")
        if not isinstance(path, str) or not isinstance(text, str):
            continue
        bounded_text = text if len(text) <= 4000 else text[:4000] + "\n[truncated]"
        parts.append(f"- {path} exists with current content:\n{bounded_text}")
    return "\n".join(parts)


def _format_full_file_replacement_guidance(value: object) -> str:
    if not isinstance(value, Mapping):
        return ""
    eligible = value.get("eligible_files")
    if not isinstance(eligible, tuple | list) or not eligible:
        return ""
    documentation = value.get("documentation_files")
    documentation_files = {
        path for path in documentation if isinstance(path, str)
    } if isinstance(documentation, tuple | list) else set()
    source = value.get("source_files")
    source_files = {
        path for path in source if isinstance(path, str)
    } if isinstance(source, tuple | list) else set()
    template = value.get("template_files")
    template_files = {
        path for path in template if isinstance(path, str)
    } if isinstance(template, tuple | list) else set()
    sizes = value.get("file_sizes")
    size_map = sizes if isinstance(sizes, Mapping) else {}
    max_bytes = value.get("max_bytes")
    lines = [
        "Full-file replacement preferred files:",
    ]
    for path in eligible:
        if not isinstance(path, str):
            continue
        size = size_map.get(path)
        size_label = f", {size} bytes" if isinstance(size, int) else ""
        lines.append(f"- {path} (full current content provided{size_label})")
    if documentation_files:
        lines.extend(
            [
                "Documentation full-file replacement strong preference:",
                *[f"- {path}" for path in eligible if path in documentation_files],
                "For documentation files listed here, use a full-file replacement "
                "when changing the file. Documentation is often structurally "
                "rewritten, and partial hunks are fragile.",
            ]
        )
    if source_files:
        lines.extend(
            [
                "Source full-file replacement strong preference:",
                *[f"- {path}" for path in eligible if path in source_files],
                "For eligible source and test files listed here, strongly prefer a "
                "full-file replacement for non-trivial edits.",
                "If you modify one of these listed source files in a way that "
                "changes imports, attributes, constructor arguments, method "
                "signatures, routing, dependencies, query behavior, form fields, "
                "validation, or tests, the expected artifact is a full-file "
                "replacement hunk starting at line 1 and covering the current file.",
                "This is especially important for controllers, entities, services, "
                "repositories, forms, and tests because related imports, methods, "
                "attributes, and constructor dependencies often need coherent updates.",
                "When modifying an eligible PHP controller, entity, service, "
                "repository, form, or test file, output the complete new file "
                "content for that path unless the edit is truly tiny and local.",
                "For controller-service-integration work, eligible controller "
                "files should use full-file replacement unless the only change is "
                "a truly tiny local edit.",
            ]
        )
    if template_files:
        lines.extend(
            [
                "Template full-file replacement strong preference:",
                *[f"- {path}" for path in eligible if path in template_files],
                "For eligible Twig templates listed here, strongly prefer a "
                "full-file replacement for non-trivial template edits.",
                "Template changes often restructure blocks, loops, forms, "
                "partials, routes, and CSS classes, so partial hunks are fragile.",
                "When modifying an eligible templates/**/*.twig file, output the "
                "complete new template content for that path unless the edit is "
                "truly tiny and local.",
                "Do not emit approximate partial hunks for non-trivial edits to "
                "eligible Twig templates.",
            ]
        )
    lines.extend(
        [
            "For files listed above, prefer replacing the full file content when "
            "making non-trivial edits.",
            "Do not emit partial hunks for non-trivial edits to these files.",
            "Do not emit approximate partial hunks for these files.",
            "Reserve partial hunks for large files or truly tiny local edits.",
            "If changing one of these files, output the complete new file content "
            "for that path in the unified diff hunk.",
            "Keep the path unchanged and do not include unrelated files.",
            f"Eligibility threshold: {max_bytes} bytes.",
        ]
    )
    return "\n".join(lines)


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
        codexcli = response.get("codexcli")
        if isinstance(codexcli, dict):
            diagnostics["provider_diagnostics"] = _safe_codexcli_diagnostics(codexcli)
    return diagnostics


def _safe_codexcli_diagnostics(codexcli: Mapping[object, object]) -> dict[str, object]:
    parser_diagnostics = codexcli.get("parser_diagnostics")
    return {
        "provider": _safe_optional_scalar(codexcli.get("provider")),
        "model": _safe_optional_scalar(codexcli.get("model")),
        "returncode": _safe_int(codexcli.get("returncode")),
        "stdout_length": _safe_int(codexcli.get("stdout_length")),
        "stderr_length": _safe_int(codexcli.get("stderr_length")),
        "stderr_present": _safe_bool(codexcli.get("stderr_present")),
        "parser_diagnostics": (
            _safe_codexcli_parser_diagnostics(parser_diagnostics)
            if isinstance(parser_diagnostics, Mapping)
            else None
        ),
    }


def _safe_codexcli_parser_diagnostics(
    diagnostics: Mapping[object, object],
) -> dict[str, object]:
    return {
        "stdout_length": _safe_int(diagnostics.get("stdout_length")),
        "jsonl_line_count": _safe_int(diagnostics.get("jsonl_line_count")),
        "parsed_event_count": _safe_int(diagnostics.get("parsed_event_count")),
        "invalid_json_line_count": _safe_int(
            diagnostics.get("invalid_json_line_count")
        ),
        "event_type_counts": _safe_event_type_counts(
            diagnostics.get("event_type_counts")
        ),
        "agent_message_count": _safe_int(diagnostics.get("agent_message_count")),
        "final_content_present": _safe_bool(diagnostics.get("final_content_present")),
        "thread_id_present": _safe_bool(diagnostics.get("thread_id_present")),
        "usage_present": _safe_bool(diagnostics.get("usage_present")),
    }


def _safe_event_type_counts(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    counts: dict[str, int] = {}
    for key, count in list(value.items())[:40]:
        safe_key = _safe_key(key)
        safe_count = _safe_int(count)
        if safe_count is not None:
            counts[safe_key] = safe_count
    return counts


def _safe_optional_scalar(value: object) -> str | None:
    if value is None:
        return None
    return _safe_scalar(value)


def _safe_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _safe_bool(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


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
