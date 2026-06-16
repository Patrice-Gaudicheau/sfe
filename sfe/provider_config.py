"""Shared provider selection helpers for SFE surfaces.

The helpers in this module are intentionally pure: they do not load .env files,
print environment values, or instantiate provider clients.
"""

from __future__ import annotations

import os
from typing import Mapping


SFE_PROVIDER_ENV = "SFE_PROVIDER"
SFE_PROVIDER_ROUTER_ENV = "SFE_PROVIDER_ROUTER"
SFE_PROVIDER_DISCOVERY_ENV = "SFE_PROVIDER_DISCOVERY"
SFE_PROVIDER_EXECUTOR_ENV = "SFE_PROVIDER_EXECUTOR"
SFE_PROVIDER_VERIFIER_ENV = "SFE_PROVIDER_VERIFIER"
DEFAULT_SFE_PROVIDER = "openai"
CODEXCLI_SFE_PROVIDER = "codexcli"
OLLAMA_SFE_PROVIDER = "ollama"

CANONICAL_PROVIDER_VALUES = (
    "openai-compatible",
    "openai",
    "lemonade",
    "alibaba",
    "anthropic",
    "google",
    OLLAMA_SFE_PROVIDER,
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


def resolve_sfe_router_provider(
    environ: Mapping[str, str] | None = None,
    default: str = DEFAULT_SFE_PROVIDER,
) -> str:
    """Resolve the router provider from SFE_PROVIDER_ROUTER, SFE_PROVIDER, or default."""
    return _resolve_sfe_role_provider(
        environ=environ,
        role_env_var=SFE_PROVIDER_ROUTER_ENV,
        default=default,
    )


def resolve_sfe_discovery_provider(
    environ: Mapping[str, str] | None = None,
    default: str = DEFAULT_SFE_PROVIDER,
) -> str:
    """Resolve the discovery provider from discovery, router, shared, or default."""
    env = os.environ if environ is None else environ
    provider = _env_value(env, SFE_PROVIDER_DISCOVERY_ENV)
    if provider is not None:
        return normalize_provider_name(provider)
    return resolve_sfe_router_provider(env, default=default)


def resolve_sfe_executor_provider(
    environ: Mapping[str, str] | None = None,
    default: str = DEFAULT_SFE_PROVIDER,
) -> str:
    """Resolve the executor provider from SFE_PROVIDER_EXECUTOR, SFE_PROVIDER, or default."""
    return _resolve_sfe_role_provider(
        environ=environ,
        role_env_var=SFE_PROVIDER_EXECUTOR_ENV,
        default=default,
    )


def resolve_sfe_verifier_provider(
    environ: Mapping[str, str] | None = None,
    default: str = DEFAULT_SFE_PROVIDER,
) -> str:
    """Resolve the Real Loop verifier provider from verifier, router, or shared config."""
    env = os.environ if environ is None else environ
    provider = _env_value(env, SFE_PROVIDER_VERIFIER_ENV)
    if provider is not None:
        return normalize_provider_name(provider)
    return resolve_sfe_router_provider(env, default=default)


def _resolve_sfe_role_provider(
    *,
    environ: Mapping[str, str] | None,
    role_env_var: str,
    default: str,
) -> str:
    env = os.environ if environ is None else environ
    provider = _env_value(env, role_env_var)
    if provider is not None:
        return normalize_provider_name(provider)
    shared_provider = _env_value(env, SFE_PROVIDER_ENV)
    if shared_provider is not None:
        return normalize_provider_name(shared_provider)
    return normalize_provider_name(default)


def _env_value(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or value.strip() == "":
        return None
    return value
