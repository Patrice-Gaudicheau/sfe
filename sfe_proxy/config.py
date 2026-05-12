"""Configuration for SFE proxy mode."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17891
DEFAULT_UPSTREAM_BASE_URL = "https://api.openai.com"
DEFAULT_MODE = "pass_through"
SUPPORTED_MODES = (DEFAULT_MODE,)


@dataclass(frozen=True)
class ProxyConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    upstream_base_url: str = DEFAULT_UPSTREAM_BASE_URL
    upstream_api_key: str = ""
    mode: str = DEFAULT_MODE

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
        return cls(
            host=os.getenv("SFE_PROXY_HOST", DEFAULT_HOST),
            port=port,
            upstream_base_url=upstream_base_url,
            upstream_api_key=upstream_api_key,
            mode=os.getenv("SFE_PROXY_MODE", DEFAULT_MODE),
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
                "SFE_PROXY_UPSTREAM_API_KEY is required for pass_through mode; "
                "OPENAI_API_KEY may be used as a fallback only for OpenAI upstreams."
            )
        return self

    @property
    def normalized_upstream_base_url(self) -> str:
        return self.upstream_base_url.rstrip("/")


def _is_openai_upstream(base_url: str) -> bool:
    parsed = urlparse(base_url or DEFAULT_UPSTREAM_BASE_URL)
    hostname = (parsed.hostname or "").lower()
    return hostname == "api.openai.com"
