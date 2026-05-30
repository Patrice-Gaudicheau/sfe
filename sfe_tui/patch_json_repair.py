"""Optional JSON repair for TUI patch proposal responses."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from providers.alibaba import DEFAULT_ROUTER_MODEL as DEFAULT_ALIBABA_ROUTER_MODEL
from providers.anthropic import DEFAULT_ROUTER_MODEL as DEFAULT_ANTHROPIC_ROUTER_MODEL
from providers.openai_api import DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL
from sfe.patch_json_repair import (
    PatchJsonRepairer as _PatchJsonRepairer,
    PatchJsonRepairResult as _PatchJsonRepairResult,
)
from sfe.provider_progress import ProviderCallIdleTimeoutError
from sfe.router_review import (
    DEFAULT_LEMONADE_ROUTER_MODEL,
    call_provider_chat,
    extract_answer,
    first_env_value,
    provider_factory_for,
)
from sfe.provider_config import resolve_sfe_provider


PATCH_JSON_REPAIR_MAX_OUTPUT_TOKENS = 12_000
PATCH_JSON_REPAIR_SYSTEM_INSTRUCTION = (
    "You are a JSON repairer, not a code generator. Repair only serialization "
    "errors in a provider response that is intended to be one JSON object with "
    "an edits array. Do not change paths. Do not change actions. Do not rewrite "
    "file contents. Do not complete missing pieces. Correct only JSON "
    "serialization problems such as unescaped quotes, unescaped newlines inside "
    "strings, Markdown fences around JSON, prose before or after JSON, and "
    "trailing commas when necessary. Return only one strict JSON object. No "
    "Markdown. No comments. No text before or after the JSON."
)


class DisabledPatchJsonRepairer:
    provider_name = None
    model = None

    def repair(
        self,
        *,
        raw_response: str,
        parse_error: str,
    ) -> _PatchJsonRepairResult:
        del raw_response, parse_error
        return _PatchJsonRepairResult(None, error_category="disabled")


class ConfiguredPatchJsonRepairer:
    def __init__(
        self,
        *,
        provider: Any,
        provider_name: str,
        model: str,
        call_style: str,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.call_style = call_style

    def repair(
        self,
        *,
        raw_response: str,
        parse_error: str,
    ) -> _PatchJsonRepairResult:
        health = self.provider.health()
        if not health.get("ok"):
            return _PatchJsonRepairResult(
                None,
                error_category="repairer_not_configured",
                provider_name=self.provider_name,
                model=self.model,
            )
        try:
            response = call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=build_patch_json_repair_prompt(
                    raw_response=raw_response,
                    parse_error=parse_error,
                ),
                model=self.model,
                max_tokens=PATCH_JSON_REPAIR_MAX_OUTPUT_TOKENS,
                system_instruction=PATCH_JSON_REPAIR_SYSTEM_INSTRUCTION,
            )
        except ProviderCallIdleTimeoutError:
            return _PatchJsonRepairResult(
                None,
                error_category="repairer_provider_idle_timeout",
                provider_name=self.provider_name,
                model=self.model,
            )
        except TimeoutError:
            return _PatchJsonRepairResult(
                None,
                error_category="repairer_timeout",
                provider_name=self.provider_name,
                model=self.model,
            )
        except Exception:
            return _PatchJsonRepairResult(
                None,
                error_category="repairer_provider_error",
                provider_name=self.provider_name,
                model=self.model,
            )
        repaired = extract_answer(response)
        if not repaired:
            return _PatchJsonRepairResult(
                None,
                error_category="empty_repair_response",
                provider_name=self.provider_name,
                model=self.model,
            )
        return _PatchJsonRepairResult(
            repaired,
            provider_name=self.provider_name,
            model=self.model,
        )


def create_tui_patch_json_repairer(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, Any] | None = None,
) -> _PatchJsonRepairer:
    if not patch_json_repair_enabled(environ):
        return DisabledPatchJsonRepairer()
    try:
        provider_name = resolve_sfe_provider(environ, default="openai")
    except ValueError:
        return DisabledPatchJsonRepairer()
    factory = provider_factory_for(provider_name, provider_factories=provider_factories)
    if provider_name in ("openai", "openai-compatible"):
        return ConfiguredPatchJsonRepairer(
            provider=factory(),
            provider_name=provider_name,
            model=first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",))
            or DEFAULT_OPENAI_ROUTER_MODEL,
            call_style="system_instruction",
        )
    if provider_name == "lemonade":
        return ConfiguredPatchJsonRepairer(
            provider=factory(),
            provider_name=provider_name,
            model=first_env_value(environ, ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"))
            or DEFAULT_LEMONADE_ROUTER_MODEL,
            call_style="system_message",
        )
    if provider_name == "alibaba":
        return ConfiguredPatchJsonRepairer(
            provider=factory(),
            provider_name=provider_name,
            model=first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",))
            or DEFAULT_ALIBABA_ROUTER_MODEL,
            call_style="system_message",
        )
    if provider_name == "anthropic":
        return ConfiguredPatchJsonRepairer(
            provider=factory(),
            provider_name=provider_name,
            model=first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",))
            or DEFAULT_ANTHROPIC_ROUTER_MODEL,
            call_style="system_instruction",
        )
    return DisabledPatchJsonRepairer()


def patch_json_repair_enabled(environ: Mapping[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    value = env.get("SFE_PATCH_JSON_REPAIR_ENABLED")
    if value is None:
        return True
    return value.strip().lower() not in {"0", "false", "no", "off"}


def build_patch_json_repair_prompt(
    *,
    raw_response: str,
    parse_error: str,
) -> str:
    payload = {
        "parse_error": parse_error,
        "expected_schema": {
            "edits": [
                {
                    "path": "relative/path",
                    "action": "replace_existing_file|create_file",
                    "content": "full file content",
                }
            ],
            "diff_preview": "optional untrusted diagnostic diff",
        },
        "raw_provider_response": raw_response,
    }
    return (
        "Repair the raw provider response below into strict JSON only. Preserve "
        "the exact patch intent, paths, actions, and file contents.\n\nRepair "
        "payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )
