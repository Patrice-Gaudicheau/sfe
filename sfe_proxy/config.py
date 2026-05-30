"""Configuration for SFE proxy mode."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from sfe.provider_config import resolve_sfe_provider_with_legacy_fallback


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17891
DEFAULT_UPSTREAM_BASE_URL = "https://api.openai.com"
DEFAULT_LEMONADE_UPSTREAM_BASE_URL = "http://127.0.0.1:13305"
DEFAULT_ALIBABA_UPSTREAM_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode"
DEFAULT_PROXY_PROVIDER = "openai-compatible"
OPENAI_PROXY_PROVIDER = "openai"
LEMONADE_PROXY_PROVIDER = "lemonade"
ALIBABA_PROXY_PROVIDER = "alibaba"
ANTHROPIC_PROXY_PROVIDER = "anthropic"
OPENAI_COMPATIBLE_PROXY_PROVIDERS = (
    DEFAULT_PROXY_PROVIDER,
    OPENAI_PROXY_PROVIDER,
    LEMONADE_PROXY_PROVIDER,
    ALIBABA_PROXY_PROVIDER,
)
SUPPORTED_PROXY_PROVIDERS = (
    DEFAULT_PROXY_PROVIDER,
    OPENAI_PROXY_PROVIDER,
    LEMONADE_PROXY_PROVIDER,
    ALIBABA_PROXY_PROVIDER,
    ANTHROPIC_PROXY_PROVIDER,
)
DEFAULT_ANTHROPIC_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ANTHROPIC_TIMEOUT_SECONDS = 60
DEFAULT_ANTHROPIC_MAX_TOKENS = 1024
DEFAULT_ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS = 0.0
DEFAULT_ANTHROPIC_MAX_INPUT_CHARS = 0
DEFAULT_ANTHROPIC_RETRY_ON_RATE_LIMIT = False
DEFAULT_ANTHROPIC_MAX_RETRY_SLEEP_SECONDS = 10.0
DEFAULT_MODE = "pass_through"
SHADOW_MODE = "shadow"
DRY_RUN_ENABLED_MODE = "dry_run_enabled"
ENABLED_MODE = "enabled"
SUPPORTED_MODES = (DEFAULT_MODE, SHADOW_MODE, DRY_RUN_ENABLED_MODE, ENABLED_MODE)
DEFAULT_SHADOW_MIN_INPUT_TOKENS = 50000
DEFAULT_SHADOW_LOG_DIR = "logs/sfe_proxy_shadow"
DEFAULT_SHADOW_ROUTER_PROVIDER = "disabled"
DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS = 30
LEMONADE_SHADOW_ROUTER_PROVIDER = "lemonade"
OPENAI_SHADOW_ROUTER_PROVIDER = "openai"
SUPPORTED_SHADOW_ROUTER_PROVIDERS = (
    DEFAULT_SHADOW_ROUTER_PROVIDER,
    LEMONADE_SHADOW_ROUTER_PROVIDER,
    OPENAI_SHADOW_ROUTER_PROVIDER,
)


@dataclass(frozen=True)
class ProxyConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    provider: str = DEFAULT_PROXY_PROVIDER
    upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL
    upstream_api_key: str = ""
    anthropic_base_url: str = DEFAULT_ANTHROPIC_BASE_URL
    anthropic_api_key: str = ""
    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    anthropic_model: str = ""
    anthropic_timeout_seconds: float = DEFAULT_ANTHROPIC_TIMEOUT_SECONDS
    anthropic_max_tokens: int = DEFAULT_ANTHROPIC_MAX_TOKENS
    anthropic_min_request_interval_seconds: float = (
        DEFAULT_ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS
    )
    anthropic_max_input_chars: int = DEFAULT_ANTHROPIC_MAX_INPUT_CHARS
    anthropic_retry_on_rate_limit: bool = DEFAULT_ANTHROPIC_RETRY_ON_RATE_LIMIT
    anthropic_max_retry_sleep_seconds: float = DEFAULT_ANTHROPIC_MAX_RETRY_SLEEP_SECONDS
    mode: str = DEFAULT_MODE
    shadow_min_input_tokens: int = DEFAULT_SHADOW_MIN_INPUT_TOKENS
    shadow_log_dir: str = DEFAULT_SHADOW_LOG_DIR
    shadow_log_full_payloads: bool = False
    shadow_selection_dry_run: bool = False
    shadow_router_dry_run: bool = False
    shadow_router_provider: str = DEFAULT_SHADOW_ROUTER_PROVIDER
    shadow_router_timeout_seconds: int = DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS
    enabled_fallback_to_original: bool = False
    enabled_streaming_replacement: bool = False

    @classmethod
    def from_env(cls) -> "ProxyConfig":
        port_raw = os.getenv("SFE_PROXY_PORT", str(DEFAULT_PORT))
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError("SFE_PROXY_PORT must be an integer.") from exc
        provider = resolve_sfe_provider_with_legacy_fallback(
            default=DEFAULT_PROXY_PROVIDER
        )
        upstream_base_url = os.getenv("SFE_PROXY_UPSTREAM_BASE_URL", "").strip()
        if not upstream_base_url:
            upstream_base_url = _default_upstream_base_url(provider)
        upstream_api_key = os.getenv("SFE_PROXY_UPSTREAM_API_KEY", "")
        if provider == ALIBABA_PROXY_PROVIDER and not upstream_api_key:
            upstream_api_key = (
                os.getenv("ALIBABA_API_KEY", "")
                or os.getenv("DASHSCOPE_API_KEY", "")
            )
        if (
            provider in OPENAI_COMPATIBLE_PROXY_PROVIDERS
            and not upstream_api_key
            and _is_openai_upstream(upstream_base_url)
        ):
            upstream_api_key = os.getenv("OPENAI_API_KEY", "")
        shadow_min_input_tokens_raw = os.getenv(
            "SFE_PROXY_SHADOW_MIN_INPUT_TOKENS", str(DEFAULT_SHADOW_MIN_INPUT_TOKENS)
        )
        try:
            shadow_min_input_tokens = int(shadow_min_input_tokens_raw)
        except ValueError as exc:
            raise ValueError("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS must be an integer.") from exc
        mode = os.getenv("SFE_PROXY_MODE", DEFAULT_MODE)
        shadow_router_dry_run = _parse_bool(
            os.getenv("SFE_PROXY_SHADOW_ROUTER_DRY_RUN", "false"),
            "SFE_PROXY_SHADOW_ROUTER_DRY_RUN",
        )
        shadow_router_provider = os.getenv(
            "SFE_PROXY_SHADOW_ROUTER_PROVIDER", DEFAULT_SHADOW_ROUTER_PROVIDER
        )
        return cls(
            host=os.getenv("SFE_PROXY_HOST", DEFAULT_HOST),
            port=port,
            provider=provider,
            upstream_base_url=upstream_base_url,
            upstream_api_key=upstream_api_key,
            anthropic_base_url=os.getenv(
                "SFE_ANTHROPIC_BASE_URL", DEFAULT_ANTHROPIC_BASE_URL
            ),
            anthropic_api_key=(
                os.getenv("SFE_ANTHROPIC_API_KEY", "")
                or os.getenv("ANTHROPIC_API_KEY", "")
            ),
            anthropic_version=os.getenv(
                "SFE_ANTHROPIC_VERSION", DEFAULT_ANTHROPIC_VERSION
            ),
            anthropic_model=os.getenv("SFE_ANTHROPIC_MODEL", ""),
            anthropic_timeout_seconds=DEFAULT_ANTHROPIC_TIMEOUT_SECONDS,
            anthropic_max_tokens=_parse_int(
                os.getenv(
                    "SFE_ANTHROPIC_MAX_TOKENS",
                    str(DEFAULT_ANTHROPIC_MAX_TOKENS),
                ),
                "SFE_ANTHROPIC_MAX_TOKENS",
            ),
            anthropic_min_request_interval_seconds=_parse_float(
                os.getenv(
                    "SFE_ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS",
                    str(DEFAULT_ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS),
                ),
                "SFE_ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS",
            ),
            anthropic_max_input_chars=_parse_int(
                os.getenv(
                    "SFE_ANTHROPIC_MAX_INPUT_CHARS",
                    str(DEFAULT_ANTHROPIC_MAX_INPUT_CHARS),
                ),
                "SFE_ANTHROPIC_MAX_INPUT_CHARS",
            ),
            anthropic_retry_on_rate_limit=_parse_bool(
                os.getenv(
                    "SFE_ANTHROPIC_RETRY_ON_RATE_LIMIT",
                    str(DEFAULT_ANTHROPIC_RETRY_ON_RATE_LIMIT).lower(),
                ),
                "SFE_ANTHROPIC_RETRY_ON_RATE_LIMIT",
            ),
            anthropic_max_retry_sleep_seconds=_parse_float(
                os.getenv(
                    "SFE_ANTHROPIC_MAX_RETRY_SLEEP_SECONDS",
                    str(DEFAULT_ANTHROPIC_MAX_RETRY_SLEEP_SECONDS),
                ),
                "SFE_ANTHROPIC_MAX_RETRY_SLEEP_SECONDS",
            ),
            mode=mode,
            shadow_min_input_tokens=shadow_min_input_tokens,
            shadow_log_dir=os.getenv("SFE_PROXY_SHADOW_LOG_DIR", DEFAULT_SHADOW_LOG_DIR),
            shadow_log_full_payloads=_parse_bool(
                os.getenv("SFE_PROXY_SHADOW_LOG_FULL_PAYLOADS", "false"),
                "SFE_PROXY_SHADOW_LOG_FULL_PAYLOADS",
            ),
            shadow_selection_dry_run=_parse_bool(
                os.getenv("SFE_PROXY_SHADOW_SELECTION_DRY_RUN", "false"),
                "SFE_PROXY_SHADOW_SELECTION_DRY_RUN",
            ),
            shadow_router_dry_run=shadow_router_dry_run,
            shadow_router_provider=shadow_router_provider,
            shadow_router_timeout_seconds=DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS,
            enabled_fallback_to_original=_parse_bool(
                os.getenv("SFE_PROXY_ENABLED_FALLBACK_TO_ORIGINAL", "false"),
                "SFE_PROXY_ENABLED_FALLBACK_TO_ORIGINAL",
            ),
            enabled_streaming_replacement=_parse_bool(
                os.getenv("SFE_PROXY_ENABLED_STREAMING_REPLACEMENT", "false"),
                "SFE_PROXY_ENABLED_STREAMING_REPLACEMENT",
            ),
        ).validated()

    def validated(self) -> "ProxyConfig":
        if self.provider not in SUPPORTED_PROXY_PROVIDERS:
            supported = ", ".join(SUPPORTED_PROXY_PROVIDERS)
            raise ValueError(
                f"Unsupported SFE_PROXY_PROVIDER {self.provider!r}; supported providers: {supported}."
            )
        if self.mode not in SUPPORTED_MODES:
            supported = ", ".join(SUPPORTED_MODES)
            raise ValueError(
                f"Unsupported SFE_PROXY_MODE {self.mode!r}; supported modes: {supported}."
            )
        if not self.host:
            raise ValueError("SFE_PROXY_HOST must not be empty.")
        if not (1 <= self.port <= 65535):
            raise ValueError("SFE_PROXY_PORT must be between 1 and 65535.")
        if self.provider in OPENAI_COMPATIBLE_PROXY_PROVIDERS and not self.upstream_base_url:
            raise ValueError("SFE_PROXY_UPSTREAM_BASE_URL must not be empty.")
        if self.provider == ALIBABA_PROXY_PROVIDER and not self.upstream_api_key:
            raise ValueError(
                "SFE_PROXY_UPSTREAM_API_KEY, ALIBABA_API_KEY, or DASHSCOPE_API_KEY "
                "is required for alibaba proxy provider."
            )
        if self.provider in OPENAI_COMPATIBLE_PROXY_PROVIDERS and not self.upstream_api_key:
            raise ValueError(
                "SFE_PROXY_UPSTREAM_API_KEY is required for proxy mode; "
                "OPENAI_API_KEY may be used as a fallback only for OpenAI upstreams."
            )
        if self.provider == ANTHROPIC_PROXY_PROVIDER:
            if not self.anthropic_base_url:
                raise ValueError("SFE_ANTHROPIC_BASE_URL must not be empty.")
            if not self.anthropic_api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY or SFE_ANTHROPIC_API_KEY is required for anthropic proxy provider."
                )
            if not self.anthropic_version:
                raise ValueError("SFE_ANTHROPIC_VERSION must not be empty.")
            if self.anthropic_timeout_seconds <= 0:
                raise ValueError("Anthropic transport timeout must be positive.")
            if self.anthropic_max_tokens <= 0:
                raise ValueError("SFE_ANTHROPIC_MAX_TOKENS must be positive.")
            if self.anthropic_min_request_interval_seconds < 0:
                raise ValueError(
                    "SFE_ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS must be non-negative."
                )
            if self.anthropic_max_input_chars < 0:
                raise ValueError("SFE_ANTHROPIC_MAX_INPUT_CHARS must be non-negative.")
            if self.anthropic_max_retry_sleep_seconds < 0:
                raise ValueError(
                    "SFE_ANTHROPIC_MAX_RETRY_SLEEP_SECONDS must be non-negative."
                )
        if self.shadow_min_input_tokens < 0:
            raise ValueError("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS must be non-negative.")
        if not self.shadow_log_dir:
            raise ValueError("SFE_PROXY_SHADOW_LOG_DIR must not be empty.")
        if self.shadow_router_timeout_seconds <= 0:
            raise ValueError("Shadow router transport timeout must be positive.")
        if self.shadow_router_provider not in SUPPORTED_SHADOW_ROUTER_PROVIDERS:
            raise ValueError(
                "Unsupported SFE_PROXY_SHADOW_ROUTER_PROVIDER "
                f"{self.shadow_router_provider!r}; supported providers: "
                f"{', '.join(SUPPORTED_SHADOW_ROUTER_PROVIDERS)}."
            )
        return self

    @property
    def normalized_upstream_base_url(self) -> str:
        return self.upstream_base_url.rstrip("/")

    @property
    def normalized_anthropic_base_url(self) -> str:
        return self.anthropic_base_url.rstrip("/")


def _is_openai_upstream(base_url: str) -> bool:
    parsed = urlparse(base_url or DEFAULT_UPSTREAM_BASE_URL)
    hostname = (parsed.hostname or "").lower()
    return hostname == "api.openai.com"


def _default_upstream_base_url(provider: str) -> str:
    if provider == LEMONADE_PROXY_PROVIDER:
        return DEFAULT_LEMONADE_UPSTREAM_BASE_URL
    if provider == ALIBABA_PROXY_PROVIDER:
        return (
            os.getenv("SFE_ALIBABA_BASE_URL", "").strip()
            or DEFAULT_ALIBABA_UPSTREAM_BASE_URL
        )
    return DEFAULT_UPSTREAM_BASE_URL


def _parse_bool(raw: str, name: str) -> bool:
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false.")


def _parse_int(raw: str, name: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _parse_float(raw: str, name: str) -> float:
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
