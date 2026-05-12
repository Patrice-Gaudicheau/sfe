"""Configuration for SFE proxy mode."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17891
DEFAULT_UPSTREAM_BASE_URL = "https://api.openai.com"
DEFAULT_MODE = "pass_through"
SHADOW_MODE = "shadow"
SUPPORTED_MODES = (DEFAULT_MODE, SHADOW_MODE)
DEFAULT_SHADOW_MIN_INPUT_TOKENS = 50000
DEFAULT_SHADOW_LOG_DIR = "logs/sfe_proxy_shadow"
DEFAULT_SHADOW_ROUTER_PROVIDER = "disabled"
DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS = 30
LEMONADE_SHADOW_ROUTER_PROVIDER = "lemonade"
SUPPORTED_SHADOW_ROUTER_PROVIDERS = (
    DEFAULT_SHADOW_ROUTER_PROVIDER,
    LEMONADE_SHADOW_ROUTER_PROVIDER,
)


@dataclass(frozen=True)
class ProxyConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL
    upstream_api_key: str = ""
    mode: str = DEFAULT_MODE
    shadow_min_input_tokens: int = DEFAULT_SHADOW_MIN_INPUT_TOKENS
    shadow_log_dir: str = DEFAULT_SHADOW_LOG_DIR
    shadow_log_full_payloads: bool = False
    shadow_selection_dry_run: bool = False
    shadow_router_dry_run: bool = False
    shadow_router_provider: str = DEFAULT_SHADOW_ROUTER_PROVIDER
    shadow_router_timeout_seconds: int = DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS

    @classmethod
    def from_env(cls) -> "ProxyConfig":
        port_raw = os.getenv("SFE_PROXY_PORT", str(DEFAULT_PORT))
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ValueError("SFE_PROXY_PORT must be an integer.") from exc
        upstream_base_url = os.getenv(
            "SFE_PROXY_UPSTREAM_BASE_URL", DEFAULT_UPSTREAM_BASE_URL
        )
        upstream_api_key = os.getenv("SFE_PROXY_UPSTREAM_API_KEY", "")
        if not upstream_api_key and _is_openai_upstream(upstream_base_url):
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
        shadow_router_timeout_seconds = _parse_int(
            os.getenv(
                "SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS",
                str(DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS),
            ),
            "SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS",
        )
        return cls(
            host=os.getenv("SFE_PROXY_HOST", DEFAULT_HOST),
            port=port,
            upstream_base_url=upstream_base_url,
            upstream_api_key=upstream_api_key,
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
            shadow_router_timeout_seconds=shadow_router_timeout_seconds,
        ).validated()

    def validated(self) -> "ProxyConfig":
        if self.mode not in SUPPORTED_MODES:
            supported = ", ".join(SUPPORTED_MODES)
            raise ValueError(
                f"Unsupported SFE_PROXY_MODE {self.mode!r}; supported modes: {supported}."
            )
        if not self.host:
            raise ValueError("SFE_PROXY_HOST must not be empty.")
        if not (1 <= self.port <= 65535):
            raise ValueError("SFE_PROXY_PORT must be between 1 and 65535.")
        if not self.upstream_base_url:
            raise ValueError("SFE_PROXY_UPSTREAM_BASE_URL must not be empty.")
        if not self.upstream_api_key:
            raise ValueError(
                "SFE_PROXY_UPSTREAM_API_KEY is required for proxy mode; "
                "OPENAI_API_KEY may be used as a fallback only for OpenAI upstreams."
            )
        if self.shadow_min_input_tokens < 0:
            raise ValueError("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS must be non-negative.")
        if not self.shadow_log_dir:
            raise ValueError("SFE_PROXY_SHADOW_LOG_DIR must not be empty.")
        if self.shadow_router_timeout_seconds <= 0:
            raise ValueError("SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS must be positive.")
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


def _is_openai_upstream(base_url: str) -> bool:
    parsed = urlparse(base_url or DEFAULT_UPSTREAM_BASE_URL)
    hostname = (parsed.hostname or "").lower()
    return hostname == "api.openai.com"


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
