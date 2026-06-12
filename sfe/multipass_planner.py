"""Router-owned multi-pass planning for large workspace_write runs."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

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
from providers.codexcli import (
    DEFAULT_ROUTER_MODEL as DEFAULT_CODEXCLI_ROUTER_MODEL,
    CodexCLIProvider,
)
from providers.lemonade import LemonadeProvider, LemonadeProviderError
from providers.ollama import (
    DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL,
    OllamaProvider,
    OllamaProviderError,
)
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from sfe.contracts import SFEContract
from sfe.execution_mode_router import DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL
from sfe.multipass import (
    MultiPassConfig,
    MultiPassIssue,
    MultiPassPlan,
    parse_multipass_plan_json,
    validate_multipass_plan,
)
from sfe.provider_config import (
    CODEXCLI_SFE_PROVIDER,
    OLLAMA_SFE_PROVIDER,
    resolve_sfe_router_provider,
)
from sfe.provider_progress import ProviderCallIdleTimeoutError


DEFAULT_MULTIPASS_PLAN_OUTPUT_TOKENS = 4000
MULTIPASS_PLANNER_SYSTEM_INSTRUCTION = (
    "You are the SFE Router-owned multi-pass planner for large workspace_write "
    "tasks. Return only one strict JSON object. Do not return Markdown, code "
    "fences, prose, explanations, diffs, patches, file edits, replacement "
    "JSON, shell commands, or file contents. You must design only the global "
    "multi-pass plan and coherence boundaries. The Executor will generate "
    "each batch patch later. The object must contain project_summary and "
    "batches. Each batch must contain id, title, goal, allowed_files, "
    "depends_on, and validation_notes. Keep batches small and coherent. Use "
    "relative file paths only. Do not include files under .git, .sfe-worktrees, "
    "vendor, var, cache, node_modules, or generated/sensitive directories."
)


@dataclass(frozen=True)
class MultiPassPlannerResponse:
    plan: MultiPassPlan | None
    issue: MultiPassIssue | None
    answer: str | None
    provider_name: str | None = None
    model: str | None = None
    provider_calls_made: int = 0


class MultiPassPlanner(Protocol):
    provider_name: str | None
    model: str | None

    def plan(
        self,
        contract: SFEContract,
        *,
        config: MultiPassConfig,
    ) -> MultiPassPlannerResponse:
        ...


class ConfiguredLLMMultiPassPlanner:
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

    def plan(
        self,
        contract: SFEContract,
        *,
        config: MultiPassConfig,
    ) -> MultiPassPlannerResponse:
        health = self.provider.health()
        if not health.get("ok"):
            return _issue_response(
                "router_not_configured",
                provider_name=self.provider_name,
                model=self.model,
            )
        try:
            response = _call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=build_multipass_planner_prompt(
                    contract=contract,
                    config=config,
                ),
                model=self.model,
                max_tokens=DEFAULT_MULTIPASS_PLAN_OUTPUT_TOKENS,
            )
        except self.missing_key_errors:
            return _issue_response(
                "router_not_configured",
                provider_name=self.provider_name,
                model=self.model,
            )
        except ProviderCallIdleTimeoutError:
            return _issue_response(
                "router_provider_idle_timeout",
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        except TimeoutError:
            return _issue_response(
                "router_timeout",
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        except self.provider_error_types:
            return _issue_response(
                "router_provider_error",
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        except LemonadeProviderError as exc:
            return _issue_response(
                f"router_{exc.error_category}",
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        except OllamaProviderError as exc:
            return _issue_response(
                f"router_{exc.error_category}",
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        except Exception:
            return _issue_response(
                "router_provider_error",
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )

        answer = _extract_answer(response)
        if not answer:
            return _issue_response(
                "invalid_response",
                answer=answer,
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        parsed_plan = parse_multipass_plan_json(answer)
        if isinstance(parsed_plan, MultiPassIssue):
            return MultiPassPlannerResponse(
                plan=None,
                issue=parsed_plan,
                answer=answer,
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=1,
            )
        issue = validate_multipass_plan(parsed_plan, config)
        return MultiPassPlannerResponse(
            plan=None if issue is not None else parsed_plan,
            issue=issue,
            answer=answer,
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class ProviderConfigurationErrorMultiPassPlanner:
    provider_name = "invalid"
    model = None

    def plan(
        self,
        contract: SFEContract,
        *,
        config: MultiPassConfig,
    ) -> MultiPassPlannerResponse:
        del contract, config
        return _issue_response(
            "provider_configuration_error",
            provider_name=self.provider_name,
        )


class UnsupportedProviderMultiPassPlanner:
    model = None

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def plan(
        self,
        contract: SFEContract,
        *,
        config: MultiPassConfig,
    ) -> MultiPassPlannerResponse:
        del contract, config
        return _issue_response(
            "router_provider_not_supported",
            provider_name=self.provider_name,
        )


def create_configured_multipass_planner(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, Any] | None = None,
) -> MultiPassPlanner:
    try:
        provider_name = resolve_sfe_router_provider(environ, default="openai")
    except ValueError:
        return ProviderConfigurationErrorMultiPassPlanner()

    factory = _provider_factory_for(provider_name, provider_factories)
    if provider_name in ("openai", "openai-compatible"):
        return ConfiguredLLMMultiPassPlanner(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",))
            or DEFAULT_OPENAI_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
        )
    if provider_name == CODEXCLI_SFE_PROVIDER:
        return ConfiguredLLMMultiPassPlanner(
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
        return ConfiguredLLMMultiPassPlanner(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"))
            or DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL,
            call_style="system_message",
        )
    if provider_name == "alibaba":
        return ConfiguredLLMMultiPassPlanner(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",))
            or DEFAULT_ALIBABA_ROUTER_MODEL,
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
        )
    if provider_name == "anthropic":
        return ConfiguredLLMMultiPassPlanner(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",))
            or DEFAULT_ANTHROPIC_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
        )
    if provider_name == OLLAMA_SFE_PROVIDER:
        return ConfiguredLLMMultiPassPlanner(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                ("SFE_OLLAMA_ROUTER_MODEL", "SFE_OLLAMA_MODEL"),
            )
            or DEFAULT_OLLAMA_MODEL,
            call_style="system_message",
        )
    return UnsupportedProviderMultiPassPlanner(provider_name)


def build_multipass_planner_prompt(
    *,
    contract: SFEContract,
    config: MultiPassConfig,
) -> str:
    task_text = contract.task.text if contract.task is not None else ""
    selected_context = [
        {
            "id": segment.id,
            "source_ref": segment.source_ref,
            "text": segment.text,
        }
        for segment in contract.context_segments
    ]
    payload = {
        "task": task_text,
        "max_passes": config.max_passes,
        "max_files_per_pass": config.max_files_per_pass,
        "selected_context_segments": selected_context,
        "required_output_schema": {
            "project_summary": "short project summary",
            "batches": [
                {
                    "id": "stable-lowercase-id",
                    "title": "Human-readable title",
                    "goal": "Batch implementation goal",
                    "allowed_files": ["relative/path.ext"],
                    "depends_on": [],
                    "validation_notes": ["batch-specific validation note"],
                }
            ],
        },
        "hard_rules": [
            "Return strict JSON only.",
            "Do not return Markdown, code fences, prose, diffs, patches, file edits, or file contents.",
            "Design only the global multi-pass plan; the Executor generates patches later.",
            "Every batch must include non-empty allowed_files.",
            "allowed_files must be relative workspace paths.",
        ],
    }
    return (
        "Design the Router-owned multi-pass plan for this SFE workspace_write "
        "task. Return strict JSON only.\n\nMulti-pass planning payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def _issue_response(
    reason: str,
    *,
    answer: str | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    provider_calls_made: int = 0,
) -> MultiPassPlannerResponse:
    return MultiPassPlannerResponse(
        plan=None,
        issue=MultiPassIssue("multi_pass_planning", reason),
        answer=answer,
        provider_name=provider_name,
        model=model,
        provider_calls_made=provider_calls_made,
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
                {"role": "system", "content": MULTIPASS_PLANNER_SYSTEM_INSTRUCTION},
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
        system_instruction=MULTIPASS_PLANNER_SYSTEM_INSTRUCTION,
    )


def _extract_answer(response: object) -> str:
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"]).strip()
    return ""


def _provider_factory_for(
    provider_name: str,
    provider_factories: Mapping[str, Any] | None,
) -> Any:
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
    if provider_name == OLLAMA_SFE_PROVIDER:
        return OllamaProvider
    return lambda: None


def _instantiate_codexcli_provider(
    provider_name: str,
    factory: Any,
    provider_factories: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None,
) -> Any:
    if provider_factories and provider_name in provider_factories:
        return factory()
    return factory(
        reasoning_effort=_first_env_value(
            environ,
            ("SFE_CODEXCLI_ROUTER_EFFORT", "SFE_CODEXCLI_REASONING_EFFORT"),
        )
    )


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
