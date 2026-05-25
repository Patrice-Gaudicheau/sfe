"""LLM-backed file selection for workspace discovery."""

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


DEFAULT_LEMONADE_DISCOVERY_MODEL = "Qwen3-0.6B-GGUF"
DISCOVERY_ROUTER_MODE = "llm_router"
DISCOVERY_ROUTER_MAX_TOKENS = 800
DISCOVERY_ROUTER_SYSTEM_INSTRUCTION = (
    "You are the SFE discovery router. Select only the workspace-relative files "
    "that should be inspected for the user's task. You receive metadata only, "
    "not file contents. Return exactly one JSON object with keys files_to_inspect "
    "and reason. files_to_inspect must be a JSON array of workspace-relative "
    "path strings copied from the workspace map. reason must be a short string. "
    "Do not return Markdown, comments, absolute paths, glob patterns, directories, "
    "or file contents."
)


@dataclass(frozen=True)
class DiscoveryRouterSelection:
    files_to_inspect: tuple[str, ...]
    reason: str
    provider_name: str | None = None
    model: str | None = None
    provider_calls_made: int = 0


class DiscoveryRouterError(RuntimeError):
    def __init__(self, category: str, reason: str) -> None:
        self.category = category
        self.reason = reason
        super().__init__(reason)


class DiscoveryRouter(Protocol):
    provider_name: str | None
    model: str | None

    def select_files(
        self,
        *,
        task: str,
        workspace_map: list[dict[str, object]],
        max_files: int,
    ) -> DiscoveryRouterSelection:
        ...


class ConfiguredLLMDiscoveryRouter:
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

    def select_files(
        self,
        *,
        task: str,
        workspace_map: list[dict[str, object]],
        max_files: int,
    ) -> DiscoveryRouterSelection:
        health = self.provider.health()
        if not health.get("ok"):
            raise DiscoveryRouterError(
                "discovery_router_not_configured",
                "configured discovery router is not available",
            )
        prompt = build_discovery_prompt(
            task=task,
            workspace_map=workspace_map,
            max_files=max_files,
        )
        try:
            response = _call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=prompt,
                model=self.model,
                max_tokens=DISCOVERY_ROUTER_MAX_TOKENS,
            )
        except self.missing_key_errors as exc:
            raise DiscoveryRouterError(
                "discovery_router_not_configured",
                "configured discovery router is not available",
            ) from exc
        except TimeoutError as exc:
            raise DiscoveryRouterError(
                "discovery_router_timeout",
                "configured discovery router timed out",
            ) from exc
        except self.provider_error_types as exc:
            raise DiscoveryRouterError(
                "discovery_router_provider_error",
                "configured discovery router provider failed",
            ) from exc
        except LemonadeProviderError as exc:
            raise DiscoveryRouterError(
                f"discovery_router_{exc.error_category}",
                "configured discovery router provider failed",
            ) from exc
        except Exception as exc:
            raise DiscoveryRouterError(
                "discovery_router_provider_error",
                "configured discovery router provider failed",
            ) from exc

        parsed = parse_discovery_router_output(_extract_answer(response))
        return DiscoveryRouterSelection(
            files_to_inspect=parsed.files_to_inspect,
            reason=parsed.reason,
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class ProviderConfigurationErrorDiscoveryRouter:
    provider_name = "invalid"
    model = None

    def select_files(
        self,
        *,
        task: str,
        workspace_map: list[dict[str, object]],
        max_files: int,
    ) -> DiscoveryRouterSelection:
        del task, workspace_map, max_files
        raise DiscoveryRouterError(
            "provider_configuration_error",
            "invalid SFE provider configuration",
        )


class UnsupportedProviderDiscoveryRouter:
    model = None

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def select_files(
        self,
        *,
        task: str,
        workspace_map: list[dict[str, object]],
        max_files: int,
    ) -> DiscoveryRouterSelection:
        del task, workspace_map, max_files
        raise DiscoveryRouterError(
            "discovery_router_provider_not_supported",
            "configured provider is not supported for discovery routing",
        )


def create_configured_discovery_router(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, Any] | None = None,
) -> DiscoveryRouter:
    try:
        provider_name = resolve_sfe_provider(environ, default="openai")
    except ValueError:
        return ProviderConfigurationErrorDiscoveryRouter()

    factory = _provider_factory_for(provider_name, provider_factories)
    if provider_name in ("openai", "openai-compatible"):
        return ConfiguredLLMDiscoveryRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",))
            or DEFAULT_OPENAI_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
        )
    if provider_name == "lemonade":
        return ConfiguredLLMDiscoveryRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"))
            or DEFAULT_LEMONADE_DISCOVERY_MODEL,
            call_style="system_message",
        )
    if provider_name == "alibaba":
        return ConfiguredLLMDiscoveryRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",))
            or DEFAULT_ALIBABA_ROUTER_MODEL,
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
        )
    if provider_name == "anthropic":
        return ConfiguredLLMDiscoveryRouter(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",))
            or DEFAULT_ANTHROPIC_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
        )
    return UnsupportedProviderDiscoveryRouter(provider_name)


def build_discovery_prompt(
    *,
    task: str,
    workspace_map: list[dict[str, object]],
    max_files: int,
) -> str:
    payload = {
        "task": task,
        "max_files_to_inspect": max_files,
        "workspace_map": workspace_map,
        "required_output_schema": {
            "files_to_inspect": ["relative/path.ext"],
            "reason": "short explanation",
        },
    }
    return (
        "Select files to inspect for the user task from this metadata-only "
        "workspace map. Return strict JSON only.\n\nDiscovery payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def parse_discovery_router_output(output: str) -> DiscoveryRouterSelection:
    try:
        parsed = json.loads(_strip_json_fence(output))
    except json.JSONDecodeError as exc:
        raise DiscoveryRouterError(
            "invalid_discovery_router_response",
            "discovery router did not return valid JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise DiscoveryRouterError(
            "invalid_discovery_router_response",
            "discovery router JSON was not an object",
        )
    files = parsed.get("files_to_inspect")
    reason = str(parsed.get("reason") or "").strip()
    if not isinstance(files, list):
        raise DiscoveryRouterError(
            "invalid_discovery_router_response",
            "discovery router files_to_inspect was invalid",
        )
    if not all(isinstance(item, str) for item in files):
        raise DiscoveryRouterError(
            "invalid_discovery_router_response",
            "discovery router files_to_inspect must contain only strings",
        )
    if not reason:
        raise DiscoveryRouterError(
            "invalid_discovery_router_response",
            "discovery router reason was empty",
        )
    return DiscoveryRouterSelection(
        files_to_inspect=tuple(files),
        reason=reason,
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
                {"role": "system", "content": DISCOVERY_ROUTER_SYSTEM_INSTRUCTION},
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
        system_instruction=DISCOVERY_ROUTER_SYSTEM_INSTRUCTION,
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
