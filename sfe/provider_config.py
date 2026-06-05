"""Shared provider selection helpers for SFE surfaces.

The helpers in this module are intentionally pure: they do not load .env files,
print environment values, or instantiate provider clients.
"""

from __future__ import annotations

import os
from typing import Mapping


SFE_PROVIDER_ENV = "SFE_PROVIDER"
DEFAULT_SFE_PROVIDER = "openai"
DEFAULT_PROXY_STANDBY_PROVIDER = "openai-compatible"
CODEXCLI_SFE_PROVIDER = "codexcli"

CANONICAL_PROVIDER_VALUES = (
    "openai-compatible",
    "openai",
    "lemonade",
    "alibaba",
    "anthropic",
    "google",
    CODEXCLI_SFE_PROVIDER,
)
PROVIDER_ALIASES = {
    "openai-api": "openai",
    "alibaba-api": "alibaba",
    "gemini": "google",
}


def normalize_provider_name(value: str) -> str:
    """Normalize and validate a configured SFE provider name."""
    normalized = value.strip().lower()
    normalized = PROVIDER_ALIASES.get(normalized, normalized)
    if normalized not in CANONICAL_PROVIDER_VALUES:
        supported = ", ".join(CANONICAL_PROVIDER_VALUES)
        aliases = ", ".join(sorted(PROVIDER_ALIASES))
        raise ValueError(
            f"Unsupported SFE provider {value!r}; supported providers: {supported}; "
            f"supported aliases: {aliases}."
        )
    return normalized


def resolve_sfe_provider(
    environ: Mapping[str, str] | None = None,
    default: str = DEFAULT_SFE_PROVIDER,
) -> str:
    """Resolve the canonical SFE provider from SFE_PROVIDER or a default."""
    env = os.environ if environ is None else environ
    provider = _env_value(env, SFE_PROVIDER_ENV)
    if provider is None:
        return normalize_provider_name(default)
    return normalize_provider_name(provider)


def resolve_sfe_provider_with_legacy_fallback(
    environ: Mapping[str, str] | None = None,
    legacy_env_var: str = "SFE_PROXY_PROVIDER",
    default: str = DEFAULT_PROXY_STANDBY_PROVIDER,
) -> str:
    """Resolve SFE_PROVIDER, then a legacy provider variable, then a default."""
    env = os.environ if environ is None else environ
    provider = _env_value(env, SFE_PROVIDER_ENV)
    if provider is not None:
        return normalize_provider_name(provider)
    legacy_provider = _env_value(env, legacy_env_var)
    if legacy_provider is not None:
        return normalize_provider_name(legacy_provider)
    return normalize_provider_name(default)


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or value.strip() == "":
        return None
    return value
