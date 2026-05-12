"""Local provider rate-limit decision contracts for future proxy router dry-runs."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


SUPPORTED_PROVIDER_KEYS = ("openai", "anthropic", "lemonade", "disabled")
SUPPORTED_QUEUE_MODES = ("reject", "wait")


@dataclass(frozen=True)
class ProviderLimitConfig:
    provider: str
    enabled: bool = False
    min_interval_ms: int = 0
    max_input_tokens: int = 0
    max_requests_per_minute: int = 0
    queue_mode: str = "reject"


@dataclass(frozen=True)
class ProviderLimitDecision:
    allowed: bool
    rejected: bool
    wait_required: bool
    reason: str
    provider: str
    estimated_input_tokens: int
    configured_limits: dict[str, int | str | bool]
    wait_ms: int = 0

    def to_metadata(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "rejected": self.rejected,
            "wait_required": self.wait_required,
            "reason": self.reason,
            "provider": self.provider,
            "estimated_input_tokens": self.estimated_input_tokens,
            "configured_limits": self.configured_limits,
            "wait_ms": self.wait_ms,
        }


class ProviderRateLimiter:
    def __init__(self, config: ProviderLimitConfig) -> None:
        self.config = config

    def decide(
        self,
        *,
        estimated_input_tokens: int,
        elapsed_since_last_request_ms: int | None = None,
        requests_in_last_minute: int | None = None,
    ) -> ProviderLimitDecision:
        if estimated_input_tokens < 0:
            raise ValueError("estimated_input_tokens must be non-negative.")
        if not self.config.enabled or self.config.provider == "disabled":
            return self._allowed("limits_disabled", estimated_input_tokens)

        token_limit = self.config.max_input_tokens
        if token_limit and estimated_input_tokens > token_limit:
            return self._blocked(
                reason="max_input_tokens_exceeded",
                estimated_input_tokens=estimated_input_tokens,
                wait_ms=0,
            )

        min_interval = self.config.min_interval_ms
        if (
            min_interval
            and elapsed_since_last_request_ms is not None
            and elapsed_since_last_request_ms < min_interval
        ):
            return self._blocked(
                reason="min_interval_ms_not_elapsed",
                estimated_input_tokens=estimated_input_tokens,
                wait_ms=min_interval - elapsed_since_last_request_ms,
            )

        rpm_limit = self.config.max_requests_per_minute
        if (
            rpm_limit
            and requests_in_last_minute is not None
            and requests_in_last_minute >= rpm_limit
        ):
            return self._blocked(
                reason="max_requests_per_minute_exceeded",
                estimated_input_tokens=estimated_input_tokens,
                wait_ms=60000,
            )

        return self._allowed("within_limits", estimated_input_tokens)

    def _allowed(self, reason: str, estimated_input_tokens: int) -> ProviderLimitDecision:
        return ProviderLimitDecision(
            allowed=True,
            rejected=False,
            wait_required=False,
            reason=reason,
            provider=self.config.provider,
            estimated_input_tokens=estimated_input_tokens,
            configured_limits=self._configured_limits(),
        )

    def _blocked(
        self,
        *,
        reason: str,
        estimated_input_tokens: int,
        wait_ms: int,
    ) -> ProviderLimitDecision:
        wait_required = self.config.queue_mode == "wait" and wait_ms > 0
        return ProviderLimitDecision(
            allowed=False,
            rejected=not wait_required,
            wait_required=wait_required,
            reason=reason,
            provider=self.config.provider,
            estimated_input_tokens=estimated_input_tokens,
            configured_limits=self._configured_limits(),
            wait_ms=wait_ms if wait_required else 0,
        )

    def _configured_limits(self) -> dict[str, int | str | bool]:
        return {
            "enabled": self.config.enabled,
            "min_interval_ms": self.config.min_interval_ms,
            "max_input_tokens": self.config.max_input_tokens,
            "max_requests_per_minute": self.config.max_requests_per_minute,
            "queue_mode": self.config.queue_mode,
        }


class ProviderLimitRegistry:
    def __init__(self, configs: Mapping[str, ProviderLimitConfig]) -> None:
        self._configs = dict(configs)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "ProviderLimitRegistry":
        env = os.environ if environ is None else environ
        enabled = _parse_bool(env.get("SFE_PROXY_PROVIDER_LIMITS_ENABLED", "false"))
        default_config = _read_provider_config(env, "SFE_PROXY_PROVIDER_DEFAULT", "default", enabled)
        configs: dict[str, ProviderLimitConfig] = {}
        for provider in SUPPORTED_PROVIDER_KEYS:
            if provider == "disabled":
                configs[provider] = ProviderLimitConfig(provider="disabled", enabled=False)
                continue
            prefix = f"SFE_PROXY_{provider.upper()}"
            configs[provider] = _read_provider_config(env, prefix, provider, enabled, default_config)
        return cls(configs)

    def config_for(self, provider: str) -> ProviderLimitConfig:
        if provider not in SUPPORTED_PROVIDER_KEYS:
            supported = ", ".join(SUPPORTED_PROVIDER_KEYS)
            raise ValueError(f"Unsupported provider key {provider!r}; supported providers: {supported}.")
        return self._configs[provider]

    def limiter_for(self, provider: str) -> ProviderRateLimiter:
        return ProviderRateLimiter(self.config_for(provider))


def _read_provider_config(
    env: Mapping[str, str],
    prefix: str,
    provider: str,
    enabled: bool,
    defaults: ProviderLimitConfig | None = None,
) -> ProviderLimitConfig:
    return ProviderLimitConfig(
        provider=provider,
        enabled=enabled,
        min_interval_ms=_read_non_negative_int(
            env,
            f"{prefix}_MIN_INTERVAL_MS",
            defaults.min_interval_ms if defaults else 0,
        ),
        max_input_tokens=_read_non_negative_int(
            env,
            f"{prefix}_MAX_INPUT_TOKENS",
            defaults.max_input_tokens if defaults else 0,
        ),
        max_requests_per_minute=_read_non_negative_int(
            env,
            f"{prefix}_MAX_REQUESTS_PER_MINUTE",
            defaults.max_requests_per_minute if defaults else 0,
        ),
        queue_mode=_read_queue_mode(env, f"{prefix}_QUEUE_MODE", defaults.queue_mode if defaults else "reject"),
    )


def _read_non_negative_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < 0:
        raise ValueError(f"{name} must be non-negative.")
    return value


def _read_queue_mode(env: Mapping[str, str], name: str, default: str) -> str:
    value = env.get(name, default).strip().lower()
    if value not in SUPPORTED_QUEUE_MODES:
        supported = ", ".join(SUPPORTED_QUEUE_MODES)
        raise ValueError(f"{name} must be one of: {supported}.")
    return value


def _parse_bool(raw: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("SFE_PROXY_PROVIDER_LIMITS_ENABLED must be true or false.")
