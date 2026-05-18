"""Tests for SFE proxy mode."""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sfe_proxy.server as proxy_server
import sfe_proxy.shadow_router as shadow_router_module
from sfe_proxy.config import (
    DEFAULT_ALIBABA_UPSTREAM_BASE_URL,
    DEFAULT_HOST,
    DEFAULT_LEMONADE_UPSTREAM_BASE_URL,
    DEFAULT_MODE,
    DEFAULT_PORT,
    DEFAULT_SHADOW_LOG_DIR,
    DEFAULT_SHADOW_MIN_INPUT_TOKENS,
    DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS,
    DEFAULT_UPSTREAM_BASE_URL,
    ProxyConfig,
)
from sfe_proxy.provider_limits import ProviderLimitRegistry, ProviderRateLimiter
from sfe_proxy.server import (
    ENABLED_MIN_REDUCTION_PCT,
    _is_sse_response,
    _request_upstream_url,
    create_server,
)
from sfe_proxy.shadow_router import (
    DisabledShadowRouter,
    LemonadeShadowRouter,
    SAFE_SHADOW_ROUTER_REASONS,
    ShadowRouterInput,
    ShadowRouterResult,
)


class RecordingUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    records: list[dict[str, Any]] = []
    response_status = 200
    response_body: bytes = b'{"ok":true}'
    response_headers = {"Content-Type": "application/json"}

    def do_GET(self) -> None:
        self._record_and_reply()

    def do_POST(self) -> None:
        self._record_and_reply()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def _record_and_reply(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else b""
        self.__class__.records.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        self.send_response(self.__class__.response_status)
        for key, value in self.__class__.response_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(self.__class__.response_body)))
        self.end_headers()
        self.wfile.write(self.__class__.response_body)


class RecordingLemonadeRouterHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    records: list[dict[str, Any]] = []
    response_status = 200
    response_body: bytes = b'{"choices":[{"message":{"content":"{}"}}]}'
    response_headers = {"Content-Type": "application/json"}
    response_factory: Any = None

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else b""
        self.__class__.records.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        response_body = (
            self.__class__.response_factory(body)
            if self.__class__.response_factory is not None
            else self.__class__.response_body
        )
        self.send_response(self.__class__.response_status)
        for key, value in self.__class__.response_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


class RecordingAnthropicHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    records: list[dict[str, Any]] = []
    response_status = 200
    response_body: bytes = b'{"id":"msg_test","type":"message","role":"assistant","model":"claude-test","content":[{"type":"text","text":"hello from anthropic"}]}'
    response_headers = {"Content-Type": "application/json"}
    response_delay_seconds = 0.0

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        body = self.rfile.read(length) if length else b""
        self.__class__.records.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        if self.__class__.response_delay_seconds:
            time.sleep(self.__class__.response_delay_seconds)
        self.send_response(self.__class__.response_status)
        for key, value in self.__class__.response_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(self.__class__.response_body)))
        self.end_headers()
        try:
            self.wfile.write(self.__class__.response_body)
        except BrokenPipeError:
            return

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def test_proxy_config_defaults_and_required_key(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_HOST", raising=False)
    monkeypatch.delenv("SFE_PROXY_PORT", raising=False)
    monkeypatch.delenv("SFE_PROXY_PROVIDER", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_MODE", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_LOG_DIR", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_LOG_FULL_PAYLOADS", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_SELECTION_DRY_RUN", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_ROUTER_DRY_RUN", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_ROUTER_PROVIDER", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("SFE_PROXY_ENABLED_FALLBACK_TO_ORIGINAL", raising=False)
    monkeypatch.delenv("SFE_PROXY_ENABLED_STREAMING_REPLACEMENT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "SFE_PROXY_UPSTREAM_API_KEY" in str(exc)
    else:
        raise AssertionError("missing proxy API key should fail")

    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    config = ProxyConfig.from_env()
    assert config.host == DEFAULT_HOST
    assert config.port == DEFAULT_PORT
    assert config.upstream_base_url == DEFAULT_UPSTREAM_BASE_URL
    assert config.mode == DEFAULT_MODE
    assert config.shadow_min_input_tokens == DEFAULT_SHADOW_MIN_INPUT_TOKENS
    assert config.shadow_log_dir == DEFAULT_SHADOW_LOG_DIR
    assert config.shadow_log_full_payloads is False
    assert config.shadow_selection_dry_run is False
    assert config.shadow_router_dry_run is False
    assert config.shadow_router_provider == "disabled"
    assert config.shadow_router_timeout_seconds == DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS
    assert config.enabled_fallback_to_original is False
    assert config.enabled_streaming_replacement is False


def test_proxy_config_accepts_openai_proxy_provider_alias(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")

    config = ProxyConfig.from_env()

    assert config.provider == "openai"
    assert config.upstream_base_url == DEFAULT_UPSTREAM_BASE_URL
    assert config.upstream_api_key == "openai-fallback-key"


def test_proxy_config_openai_alias_keeps_explicit_upstream_override(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "openai")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "explicit-proxy-key")

    config = ProxyConfig.from_env()

    assert config.provider == "openai"
    assert config.upstream_base_url == "https://example.invalid"
    assert config.upstream_api_key == "explicit-proxy-key"


def test_proxy_config_accepts_lemonade_proxy_provider_alias(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "lemonade")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "local-placeholder-key")

    config = ProxyConfig.from_env()

    assert config.provider == "lemonade"
    assert config.upstream_base_url == DEFAULT_LEMONADE_UPSTREAM_BASE_URL
    assert config.upstream_api_key == "local-placeholder-key"


def test_proxy_config_empty_upstream_uses_provider_default(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "lemonade")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_BASE_URL", "")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "local-placeholder-key")

    config = ProxyConfig.from_env()

    assert config.upstream_base_url == DEFAULT_LEMONADE_UPSTREAM_BASE_URL


def test_proxy_config_lemonade_alias_keeps_explicit_upstream_override(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "lemonade")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "local-placeholder-key")

    config = ProxyConfig.from_env()

    assert config.provider == "lemonade"
    assert config.upstream_base_url == "http://127.0.0.1:18080"


def test_proxy_config_accepts_alibaba_proxy_provider_alias(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "alibaba")
    monkeypatch.setenv("ALIBABA_API_KEY", "alibaba-key")

    config = ProxyConfig.from_env()

    assert config.provider == "alibaba"
    assert config.upstream_base_url == DEFAULT_ALIBABA_UPSTREAM_BASE_URL
    assert config.upstream_api_key == "alibaba-key"


def test_proxy_config_alibaba_uses_dashscope_key_fallback(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("ALIBABA_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "alibaba")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    config = ProxyConfig.from_env()

    assert config.upstream_base_url == DEFAULT_ALIBABA_UPSTREAM_BASE_URL
    assert config.upstream_api_key == "dashscope-key"


def test_proxy_config_prefers_specific_alibaba_key(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "alibaba")
    monkeypatch.setenv("ALIBABA_API_KEY", "alibaba-key")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "dashscope-key")

    config = ProxyConfig.from_env()

    assert config.upstream_api_key == "alibaba-key"


def test_proxy_config_alibaba_base_url_overrides_default(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "alibaba")
    monkeypatch.setenv("SFE_ALIBABA_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode")
    monkeypatch.setenv("ALIBABA_API_KEY", "alibaba-key")

    config = ProxyConfig.from_env()

    assert config.upstream_base_url == "https://dashscope-us.aliyuncs.com/compatible-mode"


def test_proxy_config_alibaba_keeps_explicit_upstream_override(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "alibaba")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("SFE_ALIBABA_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "explicit-proxy-key")
    monkeypatch.setenv("ALIBABA_API_KEY", "alibaba-key")

    config = ProxyConfig.from_env()

    assert config.upstream_base_url == "https://example.invalid/v1"
    assert config.upstream_api_key == "explicit-proxy-key"


def test_proxy_config_rejects_alibaba_provider_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("ALIBABA_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "alibaba")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "ALIBABA_API_KEY" in str(exc)
        assert "DASHSCOPE_API_KEY" in str(exc)
    else:
        raise AssertionError("alibaba proxy provider should require an API key")


def test_openai_compatible_default_upstream_url_appends_proxy_path() -> None:
    config = ProxyConfig(upstream_api_key="upstream-secret")

    assert (
        _request_upstream_url(config, "/v1/chat/completions")
        == "https://api.openai.com/v1/chat/completions"
    )


def test_lemonade_default_upstream_url_appends_proxy_path() -> None:
    config = ProxyConfig(
        provider="lemonade",
        upstream_base_url=DEFAULT_LEMONADE_UPSTREAM_BASE_URL,
        upstream_api_key="upstream-secret",
    )

    assert (
        _request_upstream_url(config, "/v1/chat/completions")
        == "http://127.0.0.1:13305/v1/chat/completions"
    )


def test_alibaba_default_upstream_url_appends_proxy_path() -> None:
    config = ProxyConfig(
        provider="alibaba",
        upstream_base_url=DEFAULT_ALIBABA_UPSTREAM_BASE_URL,
        upstream_api_key="upstream-secret",
    )

    assert (
        _request_upstream_url(config, "/v1/chat/completions")
        == "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def test_alibaba_base_url_override_appends_proxy_path() -> None:
    config = ProxyConfig(
        provider="alibaba",
        upstream_base_url="https://dashscope-us.aliyuncs.com/compatible-mode",
        upstream_api_key="upstream-secret",
    )

    assert (
        _request_upstream_url(config, "/v1/chat/completions")
        == "https://dashscope-us.aliyuncs.com/compatible-mode/v1/chat/completions"
    )


def test_alibaba_generic_upstream_override_appends_proxy_path(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "alibaba")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_BASE_URL", "https://example.invalid/custom")
    monkeypatch.setenv("SFE_ALIBABA_BASE_URL", "https://dashscope-us.aliyuncs.com/compatible-mode")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "explicit-proxy-key")

    config = ProxyConfig.from_env()

    assert config.upstream_base_url == "https://example.invalid/custom"
    assert (
        _request_upstream_url(config, "/v1/chat/completions")
        == "https://example.invalid/custom/v1/chat/completions"
    )


def test_proxy_config_accepts_shadow_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_MODE", "shadow")
    monkeypatch.setenv("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS", "123")
    monkeypatch.setenv("SFE_PROXY_SHADOW_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("SFE_PROXY_SHADOW_SELECTION_DRY_RUN", "true")

    config = ProxyConfig.from_env()

    assert config.mode == "shadow"
    assert config.shadow_min_input_tokens == 123
    assert config.shadow_log_dir == str(tmp_path)
    assert config.shadow_selection_dry_run is True


def test_proxy_config_accepts_dry_run_enabled_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "upstream-secret")
    monkeypatch.setenv("SFE_PROXY_MODE", "dry_run_enabled")
    monkeypatch.setenv("SFE_PROXY_SHADOW_LOG_DIR", str(tmp_path))

    config = ProxyConfig.from_env()

    assert config.mode == "dry_run_enabled"
    assert config.shadow_log_dir == str(tmp_path)


def test_proxy_config_accepts_enabled_mode(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "upstream-secret")
    monkeypatch.setenv("SFE_PROXY_MODE", "enabled")
    monkeypatch.setenv("SFE_PROXY_SHADOW_LOG_DIR", str(tmp_path))

    config = ProxyConfig.from_env()

    assert config.mode == "enabled"
    assert config.shadow_log_dir == str(tmp_path)


def test_proxy_config_parses_enabled_fallback_to_original(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "upstream-secret")
    monkeypatch.setenv("SFE_PROXY_ENABLED_FALLBACK_TO_ORIGINAL", "true")

    config = ProxyConfig.from_env()

    assert config.enabled_fallback_to_original is True


def test_proxy_config_parses_enabled_streaming_replacement(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "upstream-secret")
    monkeypatch.setenv("SFE_PROXY_ENABLED_STREAMING_REPLACEMENT", "true")

    config = ProxyConfig.from_env()

    assert config.enabled_streaming_replacement is True


def test_proxy_config_rejects_unsupported_shadow_router_provider(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_PROVIDER", "unsupported-provider")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "Unsupported SFE_PROXY_SHADOW_ROUTER_PROVIDER" in str(exc)
        assert "disabled" in str(exc)
        assert "lemonade" in str(exc)
        assert "openai" in str(exc)
    else:
        raise AssertionError("unsupported shadow router provider should fail")


def test_proxy_config_accepts_lemonade_router_provider_without_provider_details(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_MODE", "shadow")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_PROVIDER", "lemonade")
    monkeypatch.delenv("SFE_LEMONADE_MODEL", raising=False)
    monkeypatch.delenv("SFE_ROUTER_MODEL", raising=False)

    config = ProxyConfig.from_env()

    assert config.shadow_router_dry_run is True
    assert config.shadow_router_provider == "lemonade"


def test_proxy_config_accepts_openai_router_provider_without_provider_details(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_MODE", "shadow")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_DRY_RUN", "true")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SFE_OPENAI_ROUTER_MODEL", raising=False)

    config = ProxyConfig.from_env()

    assert config.shadow_router_dry_run is True
    assert config.shadow_router_provider == "openai"


def test_proxy_config_accepts_anthropic_provider_from_env(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-key")
    monkeypatch.setenv("SFE_ANTHROPIC_BASE_URL", "http://127.0.0.1:12345")
    monkeypatch.setenv("SFE_ANTHROPIC_VERSION", "2023-06-01")
    monkeypatch.setenv("SFE_ANTHROPIC_MODEL", "claude-test")
    monkeypatch.setenv("SFE_ANTHROPIC_API_TIMEOUT", "17")
    monkeypatch.setenv("SFE_ANTHROPIC_MAX_TOKENS", "256")
    monkeypatch.setenv("SFE_ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS", "2.5")
    monkeypatch.setenv("SFE_ANTHROPIC_MAX_INPUT_CHARS", "12345")
    monkeypatch.setenv("SFE_ANTHROPIC_RETRY_ON_RATE_LIMIT", "true")
    monkeypatch.setenv("SFE_ANTHROPIC_MAX_RETRY_SLEEP_SECONDS", "4.5")

    config = ProxyConfig.from_env()

    assert config.provider == "anthropic"
    assert config.anthropic_api_key == "anthropic-key"
    assert config.anthropic_base_url == "http://127.0.0.1:12345"
    assert config.anthropic_version == "2023-06-01"
    assert config.anthropic_model == "claude-test"
    assert config.anthropic_timeout_seconds == 17
    assert config.anthropic_max_tokens == 256
    assert config.anthropic_min_request_interval_seconds == 2.5
    assert config.anthropic_max_input_chars == 12345
    assert config.anthropic_retry_on_rate_limit is True
    assert config.anthropic_max_retry_sleep_seconds == 4.5


def test_proxy_config_prefers_specific_anthropic_api_key(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "anthropic")
    monkeypatch.setenv("SFE_ANTHROPIC_API_KEY", "specific-anthropic-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "generic-anthropic-key")

    config = ProxyConfig.from_env()

    assert config.anthropic_api_key == "specific-anthropic-key"


def test_proxy_config_rejects_anthropic_provider_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SFE_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "anthropic")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "ANTHROPIC_API_KEY or SFE_ANTHROPIC_API_KEY" in str(exc)
    else:
        raise AssertionError("anthropic proxy provider should require an API key")


def test_proxy_config_parses_shadow_router_timeout(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS", "75")

    config = ProxyConfig.from_env()

    assert config.shadow_router_timeout_seconds == 75


def test_proxy_config_rejects_invalid_shadow_router_timeout(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS", "not-an-int")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS must be an integer" in str(exc)
    else:
        raise AssertionError("invalid shadow router timeout should fail")


def test_proxy_config_rejects_non_positive_shadow_router_timeout(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    for value in ("0", "-1"):
        monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS", value)
        try:
            ProxyConfig.from_env()
        except ValueError as exc:
            assert "SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS must be positive" in str(exc)
        else:
            raise AssertionError("non-positive shadow router timeout should fail")



def test_proxy_config_rejects_invalid_shadow_threshold(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS", "not-an-int")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "SFE_PROXY_SHADOW_MIN_INPUT_TOKENS must be an integer" in str(exc)
    else:
        raise AssertionError("invalid shadow threshold should fail")


def test_proxy_config_rejects_negative_shadow_threshold(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS", "-1")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "SFE_PROXY_SHADOW_MIN_INPUT_TOKENS must be non-negative" in str(exc)
    else:
        raise AssertionError("negative shadow threshold should fail")


def test_proxy_config_explicit_upstream_key_wins_over_openai_fallback(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "explicit-proxy-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")

    config = ProxyConfig.from_env()

    assert config.upstream_api_key == "explicit-proxy-key"


def test_proxy_config_falls_back_to_openai_key_for_default_upstream(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")

    config = ProxyConfig.from_env()

    assert config.upstream_base_url == DEFAULT_UPSTREAM_BASE_URL
    assert config.upstream_api_key == "openai-fallback-key"


def test_proxy_config_falls_back_to_openai_key_for_openai_upstream(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_BASE_URL", "https://api.openai.com")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")

    config = ProxyConfig.from_env()

    assert config.upstream_api_key == "openai-fallback-key"


def test_proxy_config_does_not_use_openai_key_for_non_openai_upstream(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-fallback-key")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "OPENAI_API_KEY may be used as a fallback only for OpenAI upstreams" in str(exc)
    else:
        raise AssertionError("non-OpenAI upstream should require explicit proxy key")


def test_proxy_config_rejects_unsupported_provider(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_PROVIDER", "unsupported-provider")
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "Unsupported SFE_PROXY_PROVIDER" in str(exc)
        assert "openai-compatible" in str(exc)
        assert "openai" in str(exc)
        assert "lemonade" in str(exc)
        assert "alibaba" in str(exc)
        assert "anthropic" in str(exc)
    else:
        raise AssertionError("unsupported proxy provider should fail")


def test_proxy_config_rejects_unsupported_mode(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_MODE", "sfe_enabled")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "Unsupported SFE_PROXY_MODE" in str(exc)
    else:
        raise AssertionError("unsupported proxy mode should fail")


def test_pass_through_preserves_json_body_status_and_safe_auth_logging() -> None:
    upstream = _start_upstream(
        status=201,
        body=b'{"id":"chatcmpl-test","object":"chat.completion"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(upstream, logs)
    try:
        payload = {
            "model": "example-model",
            "messages": [{"role": "user", "content": "hello"}],
            "stream": False,
        }
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 201
    assert response["body"] == {"id": "chatcmpl-test", "object": "chat.completion"}
    assert RecordingUpstreamHandler.records[-1]["path"] == "/v1/chat/completions"
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    assert RecordingUpstreamHandler.records[-1]["headers"]["Authorization"] == "Bearer upstream-secret"

    joined_logs = "\n".join(logs)
    assert "placeholder-client-token" not in joined_logs
    assert "upstream-secret" not in joined_logs
    assert "Authorization" not in joined_logs
    assert '"model": "example-model"' in joined_logs
    assert '"stream": false' in joined_logs


def test_openai_lemonade_and_alibaba_provider_aliases_use_openai_compatible_path() -> None:
    for provider in ("openai", "lemonade", "alibaba"):
        upstream = _start_upstream(
            status=200,
            body=b'{"id":"alias-upstream","object":"chat.completion"}',
        )
        proxy = _start_proxy(upstream, [], provider=provider)
        try:
            payload = {
                "model": "example-model",
                "messages": [{"role": "user", "content": f"hello {provider}"}],
            }
            response = _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                payload,
            )
        finally:
            proxy.shutdown()
            proxy.server_close()
            upstream.shutdown()
            upstream.server_close()

        assert response["status"] == 200
        assert response["body"] == {
            "id": "alias-upstream",
            "object": "chat.completion",
        }
        assert RecordingUpstreamHandler.records[-1]["path"] == "/v1/chat/completions"
        assert json.loads(
            RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
        ) == payload
        assert (
            RecordingUpstreamHandler.records[-1]["headers"]["Authorization"]
            == "Bearer upstream-secret"
        )


def test_anthropic_provider_maps_chat_request_and_response() -> None:
    anthropic = _start_anthropic_provider(
        body=json.dumps(
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [
                    {"type": "text", "text": "first block"},
                    {"type": "text", "text": "second block"},
                ],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 11, "output_tokens": 7},
            }
        ).encode("utf-8")
    )
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-configured",
        anthropic_timeout_seconds=5,
        anthropic_max_tokens=256,
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {
                "model": "client-model",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": False,
            },
            api_key="client-key",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    assert response["status"] == 200
    assert response["body"]["provider"] == "anthropic"
    assert response["body"]["choices"][0]["message"]["content"] == "first block\nsecond block"
    assert response["body"]["choices"][0]["finish_reason"] == "stop"
    assert response["body"]["usage"]["prompt_tokens"] == 11
    assert response["body"]["usage"]["completion_tokens"] == 7
    assert response["body"]["usage"]["total_tokens"] == 18
    assert response["body"]["usage"]["anthropic_input_tokens"] == 11
    assert response["body"]["usage"]["anthropic_output_tokens"] == 7

    record = RecordingAnthropicHandler.records[-1]
    assert record["path"] == "/v1/messages"
    headers = {key.lower(): value for key, value in record["headers"].items()}
    assert headers["x-api-key"] == "anthropic-secret"
    assert headers["anthropic-version"] == "2023-06-01"
    assert "authorization" not in headers
    provider_payload = json.loads(record["body"].decode("utf-8"))
    assert provider_payload == {
        "model": "claude-configured",
        "max_tokens": 256,
        "messages": [{"role": "user", "content": "hello"}],
    }


def test_anthropic_provider_maps_system_messages_to_top_level_system() -> None:
    anthropic = _start_anthropic_provider()
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {
                "messages": [
                    {"role": "system", "content": "first system"},
                    {"role": "system", "content": "second system"},
                    {"role": "user", "content": "hello"},
                    {"role": "assistant", "content": "hi"},
                ],
            },
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    provider_payload = json.loads(RecordingAnthropicHandler.records[-1]["body"].decode("utf-8"))
    assert provider_payload["system"] == "first system\n\nsecond system"
    assert provider_payload["messages"] == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
    ]


def test_anthropic_provider_maps_responses_request_and_response() -> None:
    anthropic = _start_anthropic_provider(
        body=json.dumps(
            {
                "id": "msg_response_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "responses text"}],
                "usage": {"input_tokens": 5, "output_tokens": 3},
            }
        ).encode("utf-8")
    )
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
        anthropic_max_tokens=128,
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            {
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": "system text"}],
                    },
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": "question text"}],
                    },
                    {"type": "input_text", "text": "follow-up text"},
                ],
            },
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    provider_payload = json.loads(RecordingAnthropicHandler.records[-1]["body"].decode("utf-8"))
    assert provider_payload == {
        "model": "claude-test",
        "max_tokens": 128,
        "messages": [
            {"role": "user", "content": "question text"},
            {"role": "user", "content": "follow-up text"},
        ],
        "system": "system text",
    }
    assert response["status"] == 200
    assert response["body"]["object"] == "response"
    assert response["body"]["output_text"] == "responses text"
    assert response["body"]["output"][0]["content"] == [
        {"type": "output_text", "text": "responses text"}
    ]
    assert response["body"]["usage"]["prompt_tokens"] == 5
    assert response["body"]["usage"]["completion_tokens"] == 3
    assert response["body"]["usage"]["total_tokens"] == 8


def test_anthropic_provider_input_guard_rejects_before_provider_call() -> None:
    anthropic = _start_anthropic_provider()
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
        anthropic_max_input_chars=5,
    )
    try:
        try:
            _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                {"messages": [{"role": "user", "content": "too much text"}]},
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected Anthropic input guard to fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    assert status == 413
    assert body == {
        "error": {
            "message": "Anthropic proxy input exceeds configured max input character guard",
            "type": "anthropic_input_guard_exceeded",
            "provider": "anthropic",
        }
    }
    assert RecordingAnthropicHandler.records == []


def test_anthropic_provider_min_request_interval_sleeps_when_configured(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(proxy_server.time, "sleep", sleeps.append)
    anthropic = _start_anthropic_provider()
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
        anthropic_min_request_interval_seconds=5.0,
    )
    try:
        url = f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions"
        _request_json(url, {"messages": [{"role": "user", "content": "first"}]})
        _request_json(url, {"messages": [{"role": "user", "content": "second"}]})
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    assert len(RecordingAnthropicHandler.records) == 2
    assert sleeps
    assert sleeps[0] > 0
    assert sleeps[0] <= 5.0


def test_anthropic_provider_reports_rate_limit_without_retry_safely() -> None:
    anthropic = _start_anthropic_provider(
        status=429,
        body=b'{"error":{"message":"provider rate limit includes details"}}',
    )
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
    )
    try:
        try:
            _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hello"}]},
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected Anthropic rate limit response to fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    assert status == 429
    assert body == {
        "error": {
            "message": "Anthropic provider rate limit",
            "type": "anthropic_rate_limit",
            "provider": "anthropic",
        }
    }


def test_anthropic_provider_retries_rate_limit_once_and_caps_retry_after(
    monkeypatch,
) -> None:
    calls: list[dict[str, Any]] = []
    sleeps: list[float] = []

    def fake_call_once(server: Any, request_body: dict[str, Any]) -> dict[str, Any]:
        calls.append(request_body)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "http://anthropic.test/v1/messages",
                429,
                "Too Many Requests",
                {"Retry-After": "99"},
                None,
            )
        return {
            "id": "msg_retry",
            "model": "claude-test",
            "content": [{"type": "text", "text": "retried ok"}],
        }

    monkeypatch.setattr(proxy_server, "_call_anthropic_once", fake_call_once)
    monkeypatch.setattr(proxy_server.time, "sleep", sleeps.append)
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url="http://anthropic.test",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
        anthropic_retry_on_rate_limit=True,
        anthropic_max_retry_sleep_seconds=3.0,
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert len(calls) == 2
    assert sleeps == [3.0]
    assert response["status"] == 200
    assert response["body"]["choices"][0]["message"]["content"] == "retried ok"


def test_anthropic_provider_reports_retry_exhausted_safely(monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_call_once(server: Any, request_body: dict[str, Any]) -> dict[str, Any]:
        calls.append(request_body)
        raise urllib.error.HTTPError(
            "http://anthropic.test/v1/messages",
            429,
            "Too Many Requests",
            {},
            None,
        )

    monkeypatch.setattr(proxy_server, "_call_anthropic_once", fake_call_once)
    monkeypatch.setattr(proxy_server.time, "sleep", lambda seconds: None)
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url="http://anthropic.test",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
        anthropic_retry_on_rate_limit=True,
    )
    try:
        try:
            _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hello"}]},
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected Anthropic rate limit retry exhaustion")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert len(calls) == 2
    assert status == 429
    assert body == {
        "error": {
            "message": "Anthropic provider rate limit retry exhausted",
            "type": "anthropic_rate_limit_retry_exhausted",
            "provider": "anthropic",
        }
    }


def test_anthropic_provider_reports_non_rate_limit_http_error_safely() -> None:
    anthropic = _start_anthropic_provider(
        status=500,
        body=b'{"error":{"message":"provider overloaded details"}}',
    )
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
    )
    try:
        try:
            _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hello"}]},
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected Anthropic non-rate-limit HTTP error")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    assert status == 500
    assert body == {
        "error": {
            "message": "Anthropic provider request failed",
            "type": "anthropic_provider_error",
            "provider": "anthropic",
            "status_code": 500,
        }
    }


def test_anthropic_provider_reports_timeout_safely() -> None:
    anthropic = _start_anthropic_provider(response_delay_seconds=2.0)
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
        anthropic_timeout_seconds=1,
    )
    try:
        try:
            _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hello"}]},
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected Anthropic timeout to fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    assert status == 504
    assert body == {
        "error": {
            "message": "Anthropic provider request timed out",
            "type": "anthropic_provider_timeout",
            "provider": "anthropic",
        }
    }


def test_anthropic_provider_reports_malformed_response_safely() -> None:
    anthropic = _start_anthropic_provider(body=b'{"content":[{"type":"image"}]}')
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        provider="anthropic",
        anthropic_base_url=f"http://{anthropic.server_address[0]}:{anthropic.server_address[1]}",
        anthropic_api_key="anthropic-secret",
        anthropic_model="claude-test",
    )
    try:
        try:
            _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                {"messages": [{"role": "user", "content": "hello"}]},
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected malformed Anthropic response to fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        anthropic.shutdown()
        anthropic.server_close()

    assert status == 502
    assert body == {
        "error": {
            "message": "Anthropic provider response did not include text content",
            "type": "anthropic_malformed_response",
            "provider": "anthropic",
        }
    }


def test_models_and_responses_endpoints_are_forwarded() -> None:
    upstream = _start_upstream(body=b'{"data":[{"id":"m"}]}')
    logs: list[str] = []
    proxy = _start_proxy(upstream, logs)
    try:
        models = _request_raw(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/models",
            method="GET",
        )
        responses = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            {"model": "example-model", "input": "hello"},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert models["status"] == 200
    assert json.loads(models["body"].decode("utf-8")) == {"data": [{"id": "m"}]}
    assert responses["status"] == 200
    assert RecordingUpstreamHandler.records[-2]["path"] == "/v1/models"
    assert RecordingUpstreamHandler.records[-1]["path"] == "/v1/responses"
    response_log = _last_proxy_log(logs, path="/v1/responses")
    assert response_log["sfe_mode"] == "pass_through"
    assert response_log["model"] == "example-model"
    assert response_log["path"] == "/v1/responses"
    assert response_log["status_code"] == 200
    assert response_log["stream"] is None
    assert response_log["upstream_url"].endswith("/v1/responses")
    assert response_log["provider"] == "openai-compatible"
    assert response_log["fallback_used"] is False
    assert response_log["selection_applied"] is False


def test_upstream_error_status_and_json_body_are_preserved() -> None:
    upstream = _start_upstream(
        status=429,
        body=b'{"error":{"message":"rate limited","type":"rate_limit"}}',
    )
    proxy = _start_proxy(upstream, [])
    try:
        try:
            _request_json(
                f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
                {"model": "example-model", "messages": []},
            )
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("expected HTTPError")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert status == 429
    assert body == {"error": {"message": "rate limited", "type": "rate_limit"}}


def test_downstream_headers_avoid_duplicates_and_cookie_passthrough() -> None:
    upstream = _start_upstream(
        body=b'{"ok":true}',
        headers={
            "Content-Type": "application/json",
            "Date": "Wed, 01 Jan 2025 00:00:00 GMT",
            "Server": "upstream-test",
            "Set-Cookie": "session=upstream",
            "Connection": "keep-alive",
        },
    )
    proxy = _start_proxy(upstream, [])
    try:
        response = _request_raw(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/models",
            method="GET",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    headers = response["headers"]
    assert headers.get_all("Date") is not None
    assert len(headers.get_all("Date")) == 1
    assert headers.get_all("Server") is not None
    assert len(headers.get_all("Server")) == 1
    assert headers.get_all("Set-Cookie") is None
    assert headers.get_all("Connection") == ["close"]


def test_streaming_sse_bytes_are_passed_through() -> None:
    sse = b"data: {\"delta\":\"a\"}\n\ndata: [DONE]\n\n"
    upstream = _start_upstream(
        body=sse,
        headers={"Content-Type": "text/event-stream"},
    )
    logs: list[str] = []
    proxy = _start_proxy(upstream, logs)
    try:
        response = _request_raw(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            method="POST",
            payload={"model": "example-model", "messages": [], "stream": True},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == sse
    assert response["content_type"] == "text/event-stream"
    assert '"stream": true' in "\n".join(logs)


def test_shadow_mode_preserves_upstream_body_status_and_logs_safe_below_threshold(tmp_path) -> None:
    upstream = _start_upstream(
        status=202,
        body=b'{"id":"shadow-test","object":"chat.completion"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=50000,
    )
    prompt = "sensitive prompt content"
    try:
        payload = {
            "model": "example-model",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 202
    assert response["body"] == {"id": "shadow-test", "object": "chat.completion"}
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload

    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "shadow"
    assert event["endpoint"] == "/v1/chat/completions"
    assert event["model"] == "example-model"
    assert event["stream"] is False
    assert event["request_body_bytes"] == len(json.dumps(payload).encode("utf-8"))
    assert event["message_count"] == 1
    assert event["input_item_count"] is None
    assert event["sfe_routing_eligible"] is False
    assert event["eligibility_reason"] == "rough_estimated_input_tokens_below_threshold"
    assert event["upstream_status_code"] == 202

    serialized_event = json.dumps(event)
    joined_logs = "\n".join(logs)
    assert "placeholder-client-token" not in serialized_event
    assert "Authorization" not in serialized_event
    assert prompt not in serialized_event
    assert prompt not in joined_logs


def test_shadow_mode_logs_above_threshold_responses_metadata(tmp_path) -> None:
    upstream = _start_upstream(body=b'{"id":"resp-test","object":"response"}')
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
    )
    try:
        payload = {
            "model": "example-model",
            "input": [
                {"role": "user", "content": [{"type": "input_text", "text": "hello"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "world"}]},
            ],
            "stream": True,
        }
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["endpoint"] == "/v1/responses"
    assert event["stream"] is True
    assert event["input_item_count"] == 2
    assert event["message_count"] is None
    assert event["sfe_routing_eligible"] is True
    assert event["eligibility_reason"] == "rough_estimated_input_tokens_above_threshold"
    assert event["rough_estimated_input_tokens"] >= 1
    response_log = _last_proxy_log(logs, path="/v1/responses")
    assert response_log["sfe_mode"] == "shadow"
    assert response_log["selection_applied"] is False
    assert response_log["selected_blocks_count"] is None


def test_shadow_selection_dry_run_adds_fields_for_above_threshold_chat(tmp_path) -> None:
    upstream = _start_upstream(
        status=203,
        body=b'{"id":"dry-run-test","object":"chat.completion"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
    )
    dominant_prompt = "dominant private context " * 40
    smaller_prompt = "small private context"
    try:
        payload = {
            "model": "example-model",
            "messages": [
                {"role": "system", "content": smaller_prompt},
                {"role": "user", "content": dominant_prompt},
            ],
            "stream": False,
        }
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 203
    assert response["body"] == {"id": "dry-run-test", "object": "chat.completion"}
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload

    event = _read_shadow_event(tmp_path)
    assert event["shadow_selection_enabled"] is True
    assert event["would_activate_sfe_is_dry_run_only"] is True
    assert event["would_activate_sfe"] is True
    assert event["selection_strategy"] == "largest_text_segment_baseline"
    assert event["selection_status"] == "candidate_selected"
    assert event["selection_reason"] == "largest_text_segment_selected_for_dry_run_estimate"
    assert event["estimated_full_input_tokens"] == event["rough_estimated_input_tokens"]
    assert event["estimated_selected_input_tokens"] > 0
    assert event["estimated_token_reduction_pct"] is not None
    assert event["candidate_segment_count"] == 2
    assert event["candidate_selected_segment_count"] == 1
    assert len(event["candidate_segments_metadata"]) == 2
    assert event["candidate_segments_metadata"][1]["selected"] is True

    serialized_event = json.dumps(event)
    joined_logs = "\n".join(logs)
    assert dominant_prompt not in serialized_event
    assert smaller_prompt not in serialized_event
    assert "placeholder-client-token" not in serialized_event
    assert "Authorization" not in serialized_event
    assert dominant_prompt not in joined_logs


def test_dry_run_enabled_builds_candidate_request_without_changing_client_path(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"normal-upstream","object":"chat.completion"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="dry_run_enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_log_full_payloads=True,
    )
    distractor_a = "SEGMENT A distractor cafeteria operations. " * 4
    useful = (
        "SEGMENT C active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the threshold at 42 kilowatts. "
    ) * 8
    distractor_b = "SEGMENT B distractor logistics notes. " * 4
    question = "What threshold does the active utility tariff memo set?"
    payload = {
        "model": "example-model",
        "messages": [
            {"role": "system", "content": "Answer from supplied segments."},
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": useful},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": question},
        ],
        "stream": False,
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {"id": "normal-upstream", "object": "chat.completion"}
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload

    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "dry_run_enabled"
    assert event["dry_run_enabled_candidate_built"] is True
    assert event["dry_run_enabled_is_real_execution"] is False
    assert event["dry_run_enabled_replaces_upstream_request"] is False
    assert event["dry_run_enabled_changes_client_response"] is False
    assert event["dry_run_enabled_candidate_request_sent_to_upstream"] is False
    assert event["dry_run_enabled_experimental_response_exposed"] is False
    assert event["dry_run_enabled_original_upstream_request_unchanged"] is True
    assert event["dry_run_enabled_client_response_unchanged"] is True
    assert event["dry_run_enabled_selected_segment_ids"] == ["segment-3"]
    assert event["dry_run_enabled_candidate_request_estimated_tokens"] > 0
    assert event["dry_run_enabled_full_request_estimated_tokens"] == event[
        "rough_estimated_input_tokens"
    ]
    assert event["dry_run_enabled_estimated_token_reduction_pct"] > 0
    assert "shadow_router_status" not in event

    candidate_request = event["dry_run_enabled_candidate_request"]
    serialized_candidate = json.dumps(candidate_request)
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" in serialized_candidate
    assert question in serialized_candidate
    assert "SEGMENT A distractor cafeteria" not in serialized_candidate
    assert "SEGMENT B distractor logistics" not in serialized_candidate
    assert "placeholder-client-token" not in serialized_candidate
    assert "placeholder-client-token" not in "\n".join(logs)


def test_dry_run_enabled_candidate_diagnostics_do_not_require_payload_logging(
    tmp_path,
) -> None:
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        mode="dry_run_enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_log_full_payloads=False,
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {
                "model": "example-model",
                "messages": [
                    {"role": "user", "content": "small"},
                    {"role": "user", "content": "larger selected segment " * 80},
                    {"role": "user", "content": "distractor context " * 60},
                    {"role": "user", "content": "What is selected?"},
                ],
            },
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    event = _read_shadow_event(tmp_path)
    assert event["dry_run_enabled_candidate_built"] is True
    assert event["dry_run_enabled_selected_segment_ids"] == ["segment-2"]
    assert event["dry_run_enabled_candidate_request_estimated_tokens"] > 0
    assert "dry_run_enabled_candidate_request" not in event


def test_enabled_mode_sends_reduced_candidate_request_to_upstream(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"enabled-upstream","object":"chat.completion"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_log_full_payloads=True,
    )
    distractor_a = "SEGMENT A distractor cafeteria operations. " * 4
    useful = (
        "SEGMENT C active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the threshold at 42 kilowatts. "
    ) * 8
    distractor_b = "SEGMENT B distractor logistics notes. " * 4
    question = "What threshold does the active utility tariff memo set?"
    payload = {
        "model": "example-model",
        "messages": [
            {"role": "system", "content": "Answer from supplied segments."},
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": useful},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": question},
        ],
        "stream": False,
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {"id": "enabled-upstream", "object": "chat.completion"}
    assert len(RecordingUpstreamHandler.records) == 1
    upstream_payload = json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    )
    assert upstream_payload != payload
    serialized_upstream = json.dumps(upstream_payload)
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" in serialized_upstream
    assert question in serialized_upstream
    assert "SEGMENT A distractor cafeteria" not in serialized_upstream
    assert "SEGMENT B distractor logistics" not in serialized_upstream
    assert "placeholder-client-token" not in serialized_upstream

    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "enabled"
    assert event["enabled_candidate_built"] is True
    assert event["enabled_is_real_execution"] is True
    assert event["enabled_replaces_upstream_request"] is True
    assert event["enabled_changes_client_response"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is True
    assert event["enabled_request_sent"] is True
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_selected_segment_ids"] == ["segment-3"]
    assert event["enabled_full_request_estimated_tokens"] == event[
        "rough_estimated_input_tokens"
    ]
    assert event["enabled_candidate_request_estimated_tokens"] > 0
    assert event["enabled_estimated_token_reduction_pct"] > 0
    assert "enabled_streaming_bypass" not in event
    assert event["upstream_status_code"] == 200
    assert "shadow_router_status" not in event
    request_log = _last_proxy_log(logs)
    assert request_log["sfe_mode"] == "enabled"
    assert request_log["fallback_used"] is False
    assert request_log["selection_applied"] is True
    assert request_log["selected_blocks_count"] == 1
    assert "placeholder-client-token" not in "\n".join(logs)


def test_enabled_mode_streaming_request_falls_back_to_original_when_enabled(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"streaming-fallback-upstream","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
    )
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            "SEGMENT A obsolete context.",
            "SEGMENT B active context.",
            "Question: which segment is active?",
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {
        "id": "streaming-fallback-upstream",
        "object": "response",
    }
    assert len(RecordingUpstreamHandler.records) == 1
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload

    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "enabled"
    assert event["stream"] is True
    assert event["enabled_candidate_built"] is False
    assert event["enabled_request_sent"] is True
    assert event["enabled_original_request_sent"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["enabled_replaces_upstream_request"] is False
    assert event["enabled_changes_client_response"] is False
    assert event["enabled_fallback_to_original"] is True
    assert event["enabled_streaming_bypass"] is True
    assert event["enabled_streaming_bypass_reason"] == "streaming_not_supported"
    assert event["enabled_reason"] == "streaming_not_supported"
    assert event["upstream_status_code"] == 200

    request_log = _last_proxy_log(logs)
    assert request_log["sfe_mode"] == "enabled"
    assert request_log["status_code"] == 200
    assert request_log["stream"] is True
    assert request_log["fallback_used"] is True
    assert request_log["selection_applied"] is False
    assert request_log["enabled_reason"] == "streaming_not_supported"
    assert request_log["enabled_streaming_bypass"] is True
    assert request_log["enabled_streaming_bypass_reason"] == "streaming_not_supported"
    joined_logs = "\n".join(logs)
    assert "placeholder-client-token" not in joined_logs
    assert "upstream-secret" not in joined_logs


def test_enabled_mode_streaming_request_rejects_when_fallback_disabled(
    tmp_path,
) -> None:
    upstream = _start_upstream()
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
    )
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            "SEGMENT A obsolete context.",
            "SEGMENT B active context.",
            "Question: which segment is active?",
        ],
    }
    try:
        request = urllib.request.Request(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer placeholder-client-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("streaming enabled mode without fallback should fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert status == 422
    assert body["error"]["type"] == "sfe_enabled_routing_error"
    assert body["error"]["reason"] == "streaming_not_supported"
    assert RecordingUpstreamHandler.records == []

    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "enabled"
    assert event["stream"] is True
    assert event["enabled_candidate_built"] is False
    assert event["enabled_request_sent"] is False
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["enabled_replaces_upstream_request"] is False
    assert event["enabled_changes_client_response"] is False
    assert event["enabled_fallback_to_original"] is False
    assert event["enabled_streaming_bypass"] is True
    assert event["enabled_streaming_bypass_reason"] == "streaming_not_supported"
    assert event["enabled_reason"] == "streaming_not_supported"
    assert event["upstream_status_code"] == 422

    request_log = _last_proxy_log(logs)
    assert request_log["sfe_mode"] == "rejected"
    assert request_log["status_code"] == 422
    assert request_log["stream"] is True
    assert request_log["fallback_used"] is False
    assert request_log["selection_applied"] is False
    joined_logs = "\n".join(logs)
    assert "placeholder-client-token" not in joined_logs
    assert "upstream-secret" not in joined_logs


def test_enabled_mode_low_value_reduction_falls_back_to_original_when_enabled(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"low-value-fallback","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            "Selected-but-not-worth-reducing context. " * 80,
            "Tiny distractor.",
            "What is the answer?",
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert len(RecordingUpstreamHandler.records) == 1
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "insufficient_token_reduction"
    assert event["enabled_min_reduction_pct"] == ENABLED_MIN_REDUCTION_PCT
    assert event["enabled_reduction_gate_passed"] is False
    assert event["enabled_estimated_token_reduction_pct"] < ENABLED_MIN_REDUCTION_PCT
    assert event["enabled_original_request_sent"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["enabled_fallback_to_original"] is True

    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["sfe_mode"] == "enabled"
    assert request_log["fallback_used"] is True
    assert request_log["selection_applied"] is False
    assert request_log["enabled_reason"] == "insufficient_token_reduction"
    assert request_log["enabled_min_reduction_pct"] == ENABLED_MIN_REDUCTION_PCT
    assert request_log["enabled_reduction_gate_passed"] is False
    assert request_log["enabled_estimated_token_reduction_pct"] < ENABLED_MIN_REDUCTION_PCT
    joined_logs = "\n".join(logs)
    assert "placeholder-client-token" not in joined_logs
    assert "Authorization" not in joined_logs
    assert "input" not in joined_logs
    assert "Selected-but-not-worth-reducing" not in joined_logs


def test_enabled_mode_low_value_reduction_rejects_when_fallback_disabled(
    tmp_path,
) -> None:
    upstream = _start_upstream()
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_streaming_replacement=True,
    )
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            "Selected-but-not-worth-reducing context. " * 80,
            "Tiny distractor.",
            "What is the answer?",
        ],
    }
    try:
        request = urllib.request.Request(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer placeholder-client-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("low-value enabled replacement should fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert status == 422
    assert body["error"]["reason"] == "insufficient_token_reduction"
    assert RecordingUpstreamHandler.records == []

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "insufficient_token_reduction"
    assert event["enabled_min_reduction_pct"] == ENABLED_MIN_REDUCTION_PCT
    assert event["enabled_reduction_gate_passed"] is False
    assert event["enabled_request_sent"] is False
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["upstream_status_code"] == 422


def test_enabled_mode_structured_responses_envelope_falls_back_to_original_when_enabled(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"unsafe-envelope-fallback","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    unsupported_selected_context = "UNSUPPORTED_SELECTED_CONTEXT preserve only. " * 520
    safe_reducible_context = "SAFE_REDUCIBLE_CONTEXT should not be selected. " * 260
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            {
                "content": [
                    {
                        "type": "input_text",
                        "text": unsupported_selected_context,
                    }
                ],
            },
            _responses_text_item("user", safe_reducible_context),
            _responses_text_item("user", "Summarize the selected text."),
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert len(RecordingUpstreamHandler.records) == 1
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "selected_segment_not_reducible"
    assert event["enabled_reduction_gate_passed"] is False
    assert event["enabled_original_request_sent"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["enabled_fallback_to_original"] is True
    assert event["responses_input_envelope_kind"] == "structured_list"
    assert event["responses_input_item_count"] == 3
    assert event["responses_input_role_distribution"] == {"missing": 1, "user": 2}
    assert event["responses_input_content_part_counts"] == [1, 1, 1]
    assert event["responses_input_content_part_type_distribution"] == {"input_text": 3}
    assert event["responses_input_unsupported_item_count"] == 1
    assert event["responses_input_candidate_rejected"] is True
    assert event["responses_input_candidate_rejection_reason"] == "selected_segment_not_reducible"
    topology = event["responses_input_topology_items"]
    assert topology[0]["role"] == "missing"
    assert topology[0]["selected"] is True
    assert topology[0]["is_protected"] is True
    assert topology[0]["unsupported_reason"] == "missing_or_non_string_role"
    assert topology[2]["is_latest_user_task"] is True
    assert topology[2]["appears_task_like"] is True
    serialized_event = json.dumps(event)
    assert "UNSUPPORTED_SELECTED_CONTEXT" not in serialized_event
    assert "SAFE_REDUCIBLE_CONTEXT" not in serialized_event
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["enabled_reason"] == "selected_segment_not_reducible"
    assert request_log["enabled_reduction_gate_passed"] is False
    assert not any(key.startswith("responses_input_") for key in request_log)
    joined_logs = "\n".join(logs)
    assert "UNSUPPORTED_SELECTED_CONTEXT" not in joined_logs
    assert "SAFE_REDUCIBLE_CONTEXT" not in joined_logs
    assert "Authorization" not in joined_logs


def test_enabled_mode_structured_responses_envelope_rejects_when_fallback_disabled(
    tmp_path,
) -> None:
    upstream = _start_upstream()
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_streaming_replacement=True,
    )
    unsupported_selected_context = "UNSUPPORTED_SELECTED_CONTEXT strict reject. " * 520
    safe_reducible_context = "SAFE_REDUCIBLE_CONTEXT strict path. " * 260
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            {
                "content": [
                    {
                        "type": "input_text",
                        "text": unsupported_selected_context,
                    }
                ],
            },
            _responses_text_item("user", safe_reducible_context),
            _responses_text_item("user", "Summarize the selected text."),
        ],
    }
    try:
        request = urllib.request.Request(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer placeholder-client-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("unsafe task envelope should fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert status == 422
    assert body["error"]["reason"] == "selected_segment_not_reducible"
    assert RecordingUpstreamHandler.records == []

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "selected_segment_not_reducible"
    assert event["enabled_reduction_gate_passed"] is False
    assert event["enabled_request_sent"] is False
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["upstream_status_code"] == 422


def test_enabled_mode_structured_responses_preserves_task_envelope(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"structured-safe","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    file_list = "Review these files only: src/alpha.py, src/beta.py, and tests/test_alpha.py."
    unselected_context = "UNSELECTED_BACKGROUND obsolete release note. " * 260
    selected_context = (
        "SELECTED_BACKGROUND authoritative review note. "
        "ACTIVE_REVIEW_VALUE is 42. "
    ) * 340
    latest_task = "Use the authoritative review note and answer with ACTIVE_REVIEW_VALUE."
    latest_item = _responses_text_item("user", latest_task)
    payload = {
        "model": "example-model",
        "stream": True,
        "instructions": "Preserve the user task.",
        "input": [
            _responses_text_item("developer", "Keep the task constraints intact."),
            _responses_text_item("user", file_list),
            _responses_text_item("user", unselected_context),
            _responses_text_item("user", selected_context),
            latest_item,
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert len(RecordingUpstreamHandler.records) == 1
    upstream_payload = json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    )
    assert upstream_payload != payload
    assert upstream_payload["stream"] is True
    assert upstream_payload["instructions"] == payload["instructions"]
    assert isinstance(upstream_payload["input"], list)
    assert upstream_payload["input"][-1] == latest_item
    assert _responses_text_item("user", file_list) in upstream_payload["input"]
    candidate_text = json.dumps(upstream_payload["input"])
    assert "SFE selected context" in candidate_text
    assert "ACTIVE_REVIEW_VALUE is 42" in candidate_text
    assert "UNSELECTED_BACKGROUND obsolete" not in candidate_text

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is True
    assert event["enabled_reduction_gate_passed"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is True
    assert event["enabled_original_request_sent"] is False
    serialized_event = json.dumps(event)
    assert "src/alpha.py" not in serialized_event
    assert "ACTIVE_REVIEW_VALUE" not in serialized_event
    assert "UNSELECTED_BACKGROUND" not in serialized_event
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["fallback_used"] is False
    assert request_log["selection_applied"] is True
    assert request_log["enabled_reduction_gate_passed"] is True
    joined_logs = "\n".join(logs)
    assert "src/alpha.py" not in joined_logs
    assert "ACTIVE_REVIEW_VALUE" not in joined_logs
    assert "UNSELECTED_BACKGROUND" not in joined_logs
    assert "placeholder-client-token" not in joined_logs
    assert "Authorization" not in joined_logs


def test_enabled_mode_structured_responses_selected_segment_must_be_reducible(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"selected-not-reducible","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    reducible_context = "REDUCIBLE_BACKGROUND safe to reduce. " * 260
    latest_task = "LATEST_TASK_NOT_REDUCIBLE keep this instruction. " * 360
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("user", reducible_context),
            _responses_text_item("user", latest_task),
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload
    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "selected_segment_not_reducible"
    assert event["enabled_fallback_to_original"] is True
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["enabled_reason"] == "selected_segment_not_reducible"
    joined_logs = "\n".join(logs)
    assert "LATEST_TASK_NOT_REDUCIBLE" not in joined_logs


def test_enabled_mode_structured_responses_rejects_selected_file_path_context(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"selected-file-path-context","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    file_path_context = (
        "FILE_PATH_CONTEXT review src/alpha.py and src/beta.py before changing "
        "behavior. "
    ) * 360
    reducible_context = "REDUCIBLE_BACKGROUND safe to reduce. " * 260
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("user", file_path_context),
            _responses_text_item("user", reducible_context),
            _responses_text_item("user", "What should be reviewed?"),
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload
    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "file_paths_in_dropped_context"
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["enabled_reason"] == "file_paths_in_dropped_context"
    joined_logs = "\n".join(logs)
    assert "src/alpha.py" not in joined_logs
    assert "FILE_PATH_CONTEXT" not in joined_logs


def test_enabled_mode_structured_responses_requires_reducible_context(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"no-reducible","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("developer", "Keep answers short."),
            _responses_text_item("user", "Read src/alpha.py and src/beta.py."),
            _responses_text_item("user", "What should be reviewed?"),
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload
    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "no_reducible_context_segments"
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["enabled_reason"] == "no_reducible_context_segments"
    joined_logs = "\n".join(logs)
    assert "src/alpha.py" not in joined_logs


def test_enabled_mode_structured_responses_no_reducible_context_rejects_when_strict(
    tmp_path,
) -> None:
    upstream = _start_upstream()
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_streaming_replacement=True,
    )
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("developer", "Keep answers short."),
            _responses_text_item("user", "Read src/alpha.py and src/beta.py."),
            _responses_text_item("user", "What should be reviewed?"),
        ],
    }
    try:
        request = urllib.request.Request(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": "Bearer placeholder-client-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("strict no-reducible structured request should fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert status == 422
    assert body["error"]["reason"] == "no_reducible_context_segments"
    assert RecordingUpstreamHandler.records == []
    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "no_reducible_context_segments"
    assert event["enabled_request_sent"] is False
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["enabled_reason"] == "no_reducible_context_segments"
    joined_logs = "\n".join(logs)
    assert "src/alpha.py" not in joined_logs
    assert "placeholder-client-token" not in joined_logs


def test_enabled_mode_structured_responses_requires_latest_user_task(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"latest-task-missing","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("developer", "Large background without user task. " * 360),
            _responses_text_item("assistant", "Prior assistant text."),
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload
    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "latest_task_not_identified"
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["enabled_reason"] == "latest_task_not_identified"


def test_enabled_mode_structured_responses_low_reduction_still_blocks(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"structured-low-reduction","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    selected_context = "SELECTED_ONLY_BACKGROUND retained context. " * 260
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("user", selected_context),
            _responses_text_item("user", "What is in the retained context?"),
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload
    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is False
    assert event["enabled_reason"] == "insufficient_token_reduction"
    assert event["enabled_estimated_token_reduction_pct"] < ENABLED_MIN_REDUCTION_PCT
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["enabled_reason"] == "insufficient_token_reduction"
    assert request_log["enabled_estimated_token_reduction_pct"] < ENABLED_MIN_REDUCTION_PCT


def test_enabled_mode_structured_responses_streaming_forwards_sse(
    tmp_path,
) -> None:
    sse = (
        b'event: response.created\n'
        b'data: {"type":"response.created","response":{"id":"resp-structured"}}\n\n'
        b'event: response.output_text.delta\n'
        b'data: {"type":"response.output_text.delta","delta":"42"}\n\n'
        b'event: response.completed\n'
        b'data: {"type":"response.completed","response":{"id":"resp-structured"}}\n\n'
    )
    upstream = _start_upstream(
        status=200,
        body=sse,
        headers={"Content-Type": "text/event-stream"},
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    unselected_context = "STRUCTURED_UNSELECTED obsolete background. " * 260
    selected_context = (
        "STRUCTURED_SELECTED authoritative streaming context. "
        "STREAMING_STRUCTURED_VALUE is 42. "
    ) * 340
    latest_task = "Answer with STREAMING_STRUCTURED_VALUE."
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("developer", "Do not alter the latest task."),
            _responses_text_item("user", "Inspect docs/smoke.md only."),
            _responses_text_item("user", unselected_context),
            _responses_text_item("user", selected_context),
            _responses_text_item("user", latest_task),
        ],
    }
    try:
        response = _request_raw(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            method="POST",
            payload=payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["content_type"] == "text/event-stream"
    assert response["body"] == sse
    assert b"response.completed" in response["body"]
    upstream_payload = json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    )
    assert upstream_payload["stream"] is True
    assert isinstance(upstream_payload["input"], list)
    assert upstream_payload["input"][-1] == _responses_text_item("user", latest_task)
    assert _responses_text_item("user", "Inspect docs/smoke.md only.") in upstream_payload["input"]
    candidate_text = json.dumps(upstream_payload["input"])
    assert "SFE selected context" in candidate_text
    assert "STREAMING_STRUCTURED_VALUE is 42" in candidate_text
    assert "STRUCTURED_UNSELECTED obsolete" not in candidate_text

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is True
    assert event["enabled_reduction_gate_passed"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is True
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["fallback_used"] is False
    assert request_log["enabled_reduction_gate_passed"] is True
    joined_logs = "\n".join(logs)
    assert "docs/smoke.md" not in joined_logs
    assert "STREAMING_STRUCTURED_VALUE" not in joined_logs
    assert "response.completed" not in joined_logs
    assert "placeholder-client-token" not in joined_logs
    assert "Authorization" not in joined_logs


def test_enabled_mode_codexcli_like_structured_responses_replaces_streaming_context(
    tmp_path,
) -> None:
    sse = (
        b'event: response.created\n'
        b'data: {"type":"response.created","response":{"id":"resp-codexlike"}}\n\n'
        b'event: response.output_text.delta\n'
        b'data: {"type":"response.output_text.delta","delta":"done"}\n\n'
        b'event: response.completed\n'
        b'data: {"type":"response.completed","response":{"id":"resp-codexlike"}}\n\n'
    )
    upstream = _start_upstream(
        status=200,
        body=sse,
        headers={"Content-Type": "text/event-stream"},
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    preserved_file_task = "Review only src/proxy.py and tests/test_proxy.py."
    # The selected block is reinserted, so this dropped block makes the
    # reduction gate exercise meaningful instead of falling back.
    stale_context = "CODEXCLI_STALE_REDUCIBLE_TRANSCRIPT remove this context. " * 260
    selected_context = (
        "CODEXCLI_SELECTED_REDUCIBLE_BACKGROUND authoritative context. "
        "CONTROLLED_STRUCTURED_VALUE is present. "
    ) * 420
    latest_task = "Preserve this final task and answer from the selected context."
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("developer", "Keep the current user task intact."),
            _responses_text_item("user", preserved_file_task),
            _responses_text_item("user", stale_context),
            _responses_text_item("user", selected_context),
            _responses_text_item("user", latest_task),
        ],
    }
    try:
        response = _request_raw(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            method="POST",
            payload=payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["content_type"] == "text/event-stream"
    assert b"response.completed" in response["body"]

    upstream_payload = json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    )
    assert upstream_payload != payload
    assert upstream_payload["stream"] is True
    assert isinstance(upstream_payload["input"], list)
    assert all(isinstance(item, dict) for item in upstream_payload["input"])
    assert (
        _responses_text_item("developer", "Keep the current user task intact.")
        in upstream_payload["input"]
    )
    assert _responses_text_item("user", preserved_file_task) in upstream_payload["input"]
    assert upstream_payload["input"][-1] == _responses_text_item("user", latest_task)

    selected_items = [
        item
        for item in upstream_payload["input"]
        if isinstance(item, dict)
        and item.get("role") == "user"
        and "SFE selected context" in json.dumps(item)
    ]
    assert len(selected_items) == 1
    selected_item = selected_items[0]
    assert selected_item["content"][0]["type"] == "input_text"
    assert (
        "CODEXCLI_SELECTED_REDUCIBLE_BACKGROUND"
        in selected_item["content"][0]["text"]
    )
    candidate_text = json.dumps(upstream_payload["input"])
    assert "CONTROLLED_STRUCTURED_VALUE is present" in candidate_text
    assert "CODEXCLI_STALE_REDUCIBLE_TRANSCRIPT" not in candidate_text

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is True
    assert event["enabled_reason"] == "structured_candidate_request_built_for_diagnostics"
    assert event["enabled_replaces_upstream_request"] is True
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_candidate_request_sent_to_upstream"] is True
    assert event["enabled_selected_segment_ids"] == ["segment-4"]
    assert event["enabled_selected_segment_count"] == 1
    assert event["enabled_reduction_gate_passed"] is True
    assert event["enabled_estimated_token_reduction_pct"] >= ENABLED_MIN_REDUCTION_PCT
    assert event["responses_input_candidate_rejected"] is False
    assert event["responses_input_candidate_rejection_reason"] is None
    topology = event["responses_input_topology_items"]
    assert topology[1]["has_file_path"] is True
    assert topology[1]["is_protected"] is True
    assert topology[3]["selected"] is True
    assert topology[3]["appears_context_like"] is True
    assert topology[4]["is_latest_user_task"] is True
    assert topology[4]["is_protected"] is True
    serialized_event = json.dumps(event)
    assert "src/proxy.py" not in serialized_event
    assert "CONTROLLED_STRUCTURED_VALUE" not in serialized_event

    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["fallback_used"] is False
    assert request_log["enabled_reason"] == "structured_candidate_request_built_for_diagnostics"
    assert request_log["enabled_reduction_gate_passed"] is True
    joined_logs = "\n".join(logs)
    assert "src/proxy.py" not in joined_logs
    assert "tests/test_proxy.py" not in joined_logs
    assert "CODEXCLI_SELECTED_REDUCIBLE_BACKGROUND" not in joined_logs
    assert "CODEXCLI_STALE_REDUCIBLE_TRANSCRIPT" not in joined_logs
    assert "response.completed" not in joined_logs
    assert "placeholder-client-token" not in joined_logs
    assert "Authorization" not in joined_logs


def test_enabled_mode_structured_responses_preserves_unsupported_items_and_reduces_safe_text(
    tmp_path,
) -> None:
    sse = (
        b'event: response.created\n'
        b'data: {"type":"response.created","response":{"id":"resp-preserve-unsupported"}}\n\n'
        b'event: response.output_text.delta\n'
        b'data: {"type":"response.output_text.delta","delta":"ok"}\n\n'
        b'event: response.completed\n'
        b'data: {"type":"response.completed","response":{"id":"resp-preserve-unsupported"}}\n\n'
    )
    upstream = _start_upstream(
        status=200,
        body=sse,
        headers={"Content-Type": "text/event-stream"},
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_fallback_to_original=True,
        enabled_streaming_replacement=True,
    )
    no_role_metadata = {"type": "reasoning", "summary": []}
    no_role_tool_item = {
        "content": [
            {
                "type": "output_text",
                "text": "UNSUPPORTED_TOOL_PAYLOAD preserve this exactly. " * 8,
            }
        ],
        "status": "completed",
    }
    unsupported_part_item = {
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": "UNSUPPORTED_ASSISTANT_PART preserve this exactly. " * 8,
            }
        ],
    }
    preserved_file_task = "Review only src/proxy.py and tests/test_proxy.py."
    stale_context = "CODEXCLI_STALE_REDUCIBLE_TRANSCRIPT remove this context. " * 280
    selected_context = (
        "CODEXCLI_SELECTED_SAFE_TEXT_CONTEXT authoritative context. "
        "PRESERVED_UNSUPPORTED_VALUE is present. "
    ) * 460
    latest_task = "Use the selected safe text context and preserve the final task."
    payload = {
        "model": "example-model",
        "stream": True,
        "input": [
            _responses_text_item("developer", "Keep the task envelope intact."),
            no_role_metadata,
            no_role_tool_item,
            _responses_text_item("user", preserved_file_task),
            _responses_text_item("user", stale_context),
            unsupported_part_item,
            _responses_text_item("user", selected_context),
            _responses_text_item("assistant", "Prior short assistant note."),
            _responses_text_item("user", latest_task),
        ],
    }
    try:
        response = _request_raw(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            method="POST",
            payload=payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["content_type"] == "text/event-stream"
    assert b"response.completed" in response["body"]

    upstream_payload = json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    )
    assert upstream_payload != payload
    assert upstream_payload["stream"] is True
    assert no_role_metadata in upstream_payload["input"]
    assert no_role_tool_item in upstream_payload["input"]
    assert unsupported_part_item in upstream_payload["input"]
    assert _responses_text_item("user", preserved_file_task) in upstream_payload["input"]
    assert upstream_payload["input"][-1] == _responses_text_item("user", latest_task)
    candidate_text = json.dumps(upstream_payload["input"])
    assert "SFE selected context" in candidate_text
    assert "PRESERVED_UNSUPPORTED_VALUE is present" in candidate_text
    assert "CODEXCLI_STALE_REDUCIBLE_TRANSCRIPT" not in candidate_text

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is True
    assert event["enabled_reason"] == "structured_candidate_request_built_for_diagnostics"
    assert event["enabled_candidate_request_sent_to_upstream"] is True
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_reduction_gate_passed"] is True
    assert event["responses_input_candidate_rejected"] is False
    assert event["responses_input_candidate_rejection_reason"] is None
    assert event["responses_input_unsupported_item_count"] == 3
    topology = event["responses_input_topology_items"]
    assert topology[1]["unsupported_reason"] == "missing_or_non_string_role"
    assert topology[2]["unsupported_reason"] == "missing_or_non_string_role"
    assert topology[5]["unsupported_reason"] == "unsupported_content_part_type"
    assert topology[6]["selected"] is True
    assert topology[6]["appears_context_like"] is True
    assert topology[8]["is_latest_user_task"] is True
    serialized_event = json.dumps(event)
    assert "UNSUPPORTED_TOOL_PAYLOAD" not in serialized_event
    assert "UNSUPPORTED_ASSISTANT_PART" not in serialized_event
    assert "src/proxy.py" not in serialized_event
    assert "PRESERVED_UNSUPPORTED_VALUE" not in serialized_event

    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["fallback_used"] is False
    assert request_log["selection_applied"] is True
    assert not any(key.startswith("responses_input_") for key in request_log)
    joined_logs = "\n".join(logs)
    assert "UNSUPPORTED_TOOL_PAYLOAD" not in joined_logs
    assert "UNSUPPORTED_ASSISTANT_PART" not in joined_logs
    assert "src/proxy.py" not in joined_logs
    assert "PRESERVED_UNSUPPORTED_VALUE" not in joined_logs
    assert "response.completed" not in joined_logs
    assert "placeholder-client-token" not in joined_logs
    assert "Authorization" not in joined_logs


def test_enabled_mode_responses_replaces_safe_shape_with_meaningful_reduction(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"safe-replacement","object":"response"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
    )
    selected_context = (
        "SEGMENT B active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the threshold at 42 kilowatts. "
    ) * 80
    distractor_a = "SEGMENT A irrelevant cafeteria operations. " * 60
    distractor_b = "SEGMENT C obsolete billing notes. " * 60
    final_question = "What threshold does the active utility tariff memo set?"
    payload = {
        "model": "example-model",
        "stream": False,
        "input": [
            distractor_a,
            selected_context,
            distractor_b,
            final_question,
        ],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert len(RecordingUpstreamHandler.records) == 1
    upstream_payload = json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    )
    assert upstream_payload != payload
    assert upstream_payload["stream"] is False
    assert isinstance(upstream_payload["input"], str)
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" in upstream_payload["input"]
    assert final_question in upstream_payload["input"]
    assert "SEGMENT A irrelevant cafeteria" not in upstream_payload["input"]
    assert "SEGMENT C obsolete billing" not in upstream_payload["input"]

    event = _read_shadow_event(tmp_path)
    assert event["enabled_candidate_built"] is True
    assert event["enabled_reduction_gate_passed"] is True
    assert event["enabled_min_reduction_pct"] == ENABLED_MIN_REDUCTION_PCT
    assert event["enabled_estimated_token_reduction_pct"] >= ENABLED_MIN_REDUCTION_PCT
    assert event["enabled_candidate_request_sent_to_upstream"] is True
    assert event["enabled_original_request_sent"] is False
    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["fallback_used"] is False
    assert request_log["selection_applied"] is True
    assert request_log["enabled_reduction_gate_passed"] is True
    assert request_log["enabled_min_reduction_pct"] == ENABLED_MIN_REDUCTION_PCT
    assert request_log["enabled_estimated_token_reduction_pct"] >= ENABLED_MIN_REDUCTION_PCT


def test_enabled_mode_opt_in_streaming_responses_replaces_context_and_forwards_sse(
    tmp_path,
) -> None:
    sse = (
        b'event: response.created\n'
        b'data: {"type":"response.created","response":{"id":"resp-test"}}\n\n'
        b'event: response.output_text.delta\n'
        b'data: {"type":"response.output_text.delta","delta":"42"}\n\n'
        b'event: response.completed\n'
        b'data: {"type":"response.completed","response":{"id":"resp-test"}}\n\n'
    )
    upstream = _start_upstream(
        status=200,
        body=sse,
        headers={"Content-Type": "text/event-stream"},
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        enabled_streaming_replacement=True,
    )
    unselected_context = "SEGMENT A obsolete cafeteria note. " * 60
    selected_context = (
        "SEGMENT B active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the threshold at 42 kilowatts. "
    ) * 80
    second_unselected_context = "SEGMENT C unrelated logistics note. " * 60
    final_question = "What threshold does the active utility tariff memo set?"
    payload = {
        "model": "example-model",
        "stream": True,
        "stream_options": {"include_usage": True},
        "instructions": "Answer only from supplied context.",
        "tools": [{"type": "web_search_preview"}],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "reasoning": {"effort": "low"},
        "text": {"format": {"type": "text"}},
        "temperature": 0.2,
        "top_p": 0.9,
        "max_output_tokens": 128,
        "metadata": {"suite": "proxy-test"},
        "store": False,
        "include": ["reasoning.encrypted_content"],
        "previous_response_id": "resp-prev",
        "truncation": "auto",
        "service_tier": "auto",
        "unknown_future_field": {"preserve": True},
        "input": [
            unselected_context,
            selected_context,
            second_unselected_context,
            final_question,
        ],
    }
    try:
        response = _request_raw(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/responses",
            method="POST",
            payload=payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["content_type"] == "text/event-stream"
    assert response["body"] == sse
    assert b"response.completed" in response["body"]

    assert len(RecordingUpstreamHandler.records) == 1
    upstream_payload = json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    )
    assert upstream_payload != payload
    assert upstream_payload["stream"] is True
    assert upstream_payload["stream_options"] == payload["stream_options"]
    assert upstream_payload["instructions"] == payload["instructions"]
    assert upstream_payload["tools"] == payload["tools"]
    assert upstream_payload["tool_choice"] == payload["tool_choice"]
    assert upstream_payload["parallel_tool_calls"] is False
    assert upstream_payload["reasoning"] == payload["reasoning"]
    assert upstream_payload["text"] == payload["text"]
    assert upstream_payload["temperature"] == payload["temperature"]
    assert upstream_payload["top_p"] == payload["top_p"]
    assert upstream_payload["max_output_tokens"] == payload["max_output_tokens"]
    assert upstream_payload["metadata"] == payload["metadata"]
    assert upstream_payload["store"] is False
    assert upstream_payload["include"] == payload["include"]
    assert upstream_payload["previous_response_id"] == payload["previous_response_id"]
    assert upstream_payload["truncation"] == payload["truncation"]
    assert upstream_payload["service_tier"] == payload["service_tier"]
    assert upstream_payload["unknown_future_field"] == payload["unknown_future_field"]
    assert isinstance(upstream_payload["input"], str)
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" in upstream_payload["input"]
    assert final_question in upstream_payload["input"]
    assert "SEGMENT A obsolete cafeteria" not in upstream_payload["input"]
    assert "SEGMENT C unrelated logistics" not in upstream_payload["input"]
    assert "placeholder-client-token" not in upstream_payload["input"]

    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "enabled"
    assert event["stream"] is True
    assert event["enabled_candidate_built"] is True
    assert event["enabled_is_real_execution"] is True
    assert event["enabled_replaces_upstream_request"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is True
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_reduction_gate_passed"] is True
    assert event["enabled_estimated_token_reduction_pct"] >= ENABLED_MIN_REDUCTION_PCT
    assert "enabled_streaming_bypass" not in event
    assert "enabled_candidate_request" not in event
    assert event["upstream_status_code"] == 200

    request_log = _last_proxy_log(logs, path="/v1/responses")
    assert request_log["sfe_mode"] == "enabled"
    assert request_log["status_code"] == 200
    assert request_log["stream"] is True
    assert request_log["fallback_used"] is False
    assert request_log["selection_applied"] is True
    assert request_log["enabled_reduction_gate_passed"] is True
    assert request_log["enabled_estimated_token_reduction_pct"] >= ENABLED_MIN_REDUCTION_PCT
    joined_logs = "\n".join(logs)
    assert "placeholder-client-token" not in joined_logs
    assert "upstream-secret" not in joined_logs
    assert "Authorization" not in joined_logs
    assert "SEGMENT A obsolete cafeteria" not in joined_logs
    assert "SEGMENT C unrelated logistics" not in joined_logs
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" not in joined_logs
    assert "response.completed" not in joined_logs


def test_enabled_mode_rejects_when_no_candidate_request_is_available(
    tmp_path,
) -> None:
    upstream = _start_upstream()
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=50000,
    )
    try:
        request = urllib.request.Request(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            data=json.dumps(
                {
                    "model": "example-model",
                    "messages": [{"role": "user", "content": "short"}],
                }
            ).encode("utf-8"),
            headers={
                "Authorization": "Bearer placeholder-client-token",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            urllib.request.urlopen(request, timeout=5)
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = json.loads(exc.read().decode("utf-8"))
        else:
            raise AssertionError("enabled mode without a candidate should fail")
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert status == 422
    assert body["error"]["type"] == "sfe_enabled_routing_error"
    assert RecordingUpstreamHandler.records == []
    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "enabled"
    assert event["enabled_candidate_built"] is False
    assert event["enabled_request_sent"] is False
    assert event["enabled_original_request_sent"] is False
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["enabled_replaces_upstream_request"] is False
    assert event["enabled_changes_client_response"] is False
    assert event["enabled_reason"] == "no_selected_segments"
    assert event["upstream_status_code"] == 422
    request_log = _last_proxy_log(logs)
    assert request_log["sfe_mode"] == "rejected"
    assert request_log["status_code"] == 422
    assert request_log["fallback_used"] is False
    assert request_log["selection_applied"] is False


def test_enabled_mode_falls_back_to_original_when_candidate_unavailable_and_enabled(
    tmp_path,
) -> None:
    upstream = _start_upstream(
        status=200,
        body=b'{"id":"fallback-upstream","object":"chat.completion"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="enabled",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=50000,
        enabled_fallback_to_original=True,
    )
    payload = {
        "model": "example-model",
        "messages": [{"role": "user", "content": "short"}],
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {"id": "fallback-upstream", "object": "chat.completion"}
    assert len(RecordingUpstreamHandler.records) == 1
    assert json.loads(
        RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")
    ) == payload
    assert (
        RecordingUpstreamHandler.records[-1]["headers"]["Authorization"]
        == "Bearer upstream-secret"
    )

    event = _read_shadow_event(tmp_path)
    assert event["mode"] == "enabled"
    assert event["enabled_candidate_built"] is False
    assert event["enabled_request_sent"] is True
    assert event["enabled_original_request_sent"] is True
    assert event["enabled_candidate_request_sent_to_upstream"] is False
    assert event["enabled_replaces_upstream_request"] is False
    assert event["enabled_changes_client_response"] is False
    assert event["enabled_fallback_to_original"] is True
    assert event["enabled_reason"] == "no_selected_segments"
    assert event["upstream_status_code"] == 200

    request_log = _last_proxy_log(logs)
    assert request_log["sfe_mode"] == "enabled"
    assert request_log["status_code"] == 200
    assert request_log["fallback_used"] is True
    assert request_log["selection_applied"] is False
    assert request_log["selected_blocks_count"] == 0
    joined_logs = "\n".join(logs)
    assert "placeholder-client-token" not in joined_logs
    assert "upstream-secret" not in joined_logs


def test_shadow_selection_dry_run_below_threshold_does_not_activate(tmp_path) -> None:
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=50000,
        shadow_selection_dry_run=True,
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    event = _read_shadow_event(tmp_path)
    assert event["sfe_routing_eligible"] is False
    assert event["shadow_selection_enabled"] is True
    assert event["would_activate_sfe_is_dry_run_only"] is True
    assert event["would_activate_sfe"] is False
    assert event["selection_status"] == "no_selection"
    assert event["selection_reason"] == "rough_estimated_input_tokens_below_threshold"
    assert event["candidate_segment_count"] == 0


def test_shadow_selection_dry_run_disabled_by_default_has_no_selection_fields(tmp_path) -> None:
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    event = _read_shadow_event(tmp_path)
    assert "shadow_selection_enabled" not in event
    assert "would_activate_sfe" not in event
    assert "candidate_segments_metadata" not in event
    assert "shadow_router_enabled" not in event


def test_shadow_router_contract_objects_are_safe_json_metadata() -> None:
    router_input = ShadowRouterInput(
        request_id="request-1",
        endpoint="/v1/chat/completions",
        model="example-model",
        rough_estimated_input_tokens=100,
        candidate_segments_metadata=[
            {
                "segment_id": "segment-1",
                "source": "chat_message_1",
                "text_chars": 40,
                "text_bytes": 40,
                "estimated_tokens": 10,
                "selected": False,
            }
        ],
        eligibility_metadata={"sfe_routing_eligible": True},
        request_body_bytes=400,
        stream=False,
    )
    result = DisabledShadowRouter().analyze(router_input)
    event_fields = result.to_event_fields("disabled")

    json.dumps(event_fields)
    assert event_fields == {
        "shadow_router_enabled": False,
        "shadow_router_provider": "disabled",
        "shadow_router_name": "disabled",
        "shadow_router_status": "disabled",
        "shadow_router_reason": "disabled",
        "shadow_router_latency_ms": 0,
        "shadow_router_candidate_selected_segment_ids": [],
        "shadow_router_estimated_selected_input_tokens": None,
        "shadow_router_estimated_token_reduction_pct": None,
        "shadow_router_error_type": None,
        "shadow_router_dry_run_only": True,
    }


def test_shadow_router_result_serializes_error_metadata() -> None:
    result = ShadowRouterResult(
        router_enabled=False,
        router_name="disabled",
        router_status="error",
        router_reason="contract_error",
        router_latency_ms=0,
        error_type="RuntimeError",
    )

    event_fields = result.to_event_fields("disabled")

    json.dumps(event_fields)
    assert event_fields["shadow_router_error_type"] == "RuntimeError"
    assert event_fields["shadow_router_reason"] == "router_call_failed"
    assert event_fields["shadow_router_dry_run_only"] is True


def test_shadow_router_reason_is_category_only() -> None:
    raw_reason = (
        "Use docs/private/path.py because the prompt says internal details "
        "and arbitrary router prose."
    )
    result = ShadowRouterResult(
        router_enabled=True,
        router_name="openai",
        router_status="candidate_selected",
        router_reason=raw_reason,
        router_latency_ms=12,
        candidate_selected_segment_ids=["segment-1"],
    )

    event_fields = result.to_event_fields("openai")

    assert event_fields["shadow_router_reason"] == "router_call_succeeded"
    assert event_fields["shadow_router_reason"] in SAFE_SHADOW_ROUTER_REASONS
    assert raw_reason not in json.dumps(event_fields)
    assert "docs/private/path.py" not in json.dumps(event_fields)
    assert "arbitrary router prose" not in json.dumps(event_fields)


def test_shadow_router_dry_run_disabled_provider_preserves_pass_through(tmp_path) -> None:
    upstream = _start_upstream(
        status=207,
        body=b'{"id":"router-contract-test","object":"chat.completion"}',
    )
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_router_dry_run=True,
        shadow_router_provider="disabled",
    )
    prompt = "private router contract prompt"
    try:
        payload = {
            "model": "example-model",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 207
    assert response["body"] == {"id": "router-contract-test", "object": "chat.completion"}
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    assert RecordingUpstreamHandler.records[-1]["headers"]["Authorization"] == "Bearer upstream-secret"

    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_enabled"] is False
    assert event["shadow_router_provider"] == "disabled"
    assert event["shadow_router_name"] == "disabled"
    assert event["shadow_router_status"] == "disabled"
    assert event["shadow_router_reason"] == "disabled"
    assert event["shadow_router_dry_run_only"] is True
    assert event["shadow_router_candidate_selected_segment_ids"] == []

    serialized_event = json.dumps(event)
    joined_logs = "\n".join(logs)
    assert prompt not in serialized_event
    assert "placeholder-client-token" not in serialized_event
    assert "Authorization" not in serialized_event
    assert prompt not in joined_logs


def test_shadow_router_lemonade_success_adds_safe_metadata(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_LEMONADE_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(
        status=208,
        body=b'{"id":"lemonade-router-test","object":"chat.completion"}',
    )
    lemonade_response = {
        "router_status": "candidate_selected",
        "router_reason": "metadata_only_dry_run_selection",
        "candidate_selected_segment_ids": ["segment-1"],
        "estimated_router_selected_input_tokens": 12,
        "estimated_router_token_reduction_pct": 80.0,
        "confidence": 0.42,
        "dry_run_only": True,
    }
    lemonade = _start_lemonade_router(
        body=json.dumps(
            {"choices": [{"message": {"content": json.dumps(lemonade_response)}}]}
        ).encode("utf-8")
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    prompt = "synthetic segment " * 20
    try:
        payload = {
            "model": "example-model",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
        }
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 208
    assert response["body"] == {"id": "lemonade-router-test", "object": "chat.completion"}
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    assert len(RecordingLemonadeRouterHandler.records) == 1

    lemonade_payload = json.loads(RecordingLemonadeRouterHandler.records[-1]["body"].decode("utf-8"))
    assert RecordingLemonadeRouterHandler.records[-1]["path"] == "/v1/chat/completions"
    assert RecordingLemonadeRouterHandler.records[-1]["headers"].get("Authorization") is None
    serialized_lemonade_payload = json.dumps(lemonade_payload)
    assert prompt in serialized_lemonade_payload
    assert "placeholder-client-token" not in serialized_lemonade_payload
    assert "Authorization" not in serialized_lemonade_payload
    assert "candidate_segments" in serialized_lemonade_payload
    assert lemonade_payload["chat_template_kwargs"] == {"enable_thinking": False}
    system_prompt = lemonade_payload["messages"][0]["content"]
    assert system_prompt.startswith("/no_think")
    assert "Return only one JSON object" in system_prompt
    assert "No Markdown" in system_prompt
    assert "No code fences" in system_prompt
    assert "No prose" in system_prompt
    assert "No explanation" in system_prompt
    assert "No reasoning" in system_prompt
    assert "No text before or after the JSON object" in system_prompt

    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_enabled"] is True
    assert event["shadow_router_provider"] == "lemonade"
    assert event["shadow_router_name"] == "lemonade"
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"
    assert event["shadow_router_candidate_selected_segment_ids"] == ["segment-1"]
    assert event["shadow_router_estimated_selected_input_tokens"] == 12
    assert event["shadow_router_estimated_token_reduction_pct"] == 80.0
    assert event["shadow_router_confidence"] == 0.42
    assert event["shadow_router_dry_run_only"] is True
    assert event["shadow_router_rate_limit_decision"]["allowed"] is True

    serialized_event = json.dumps(event)
    assert prompt not in serialized_event
    assert "placeholder-client-token" not in serialized_event
    assert "Authorization" not in serialized_event
    assert prompt not in "\n".join(logs)


def test_shadow_router_openai_success_adds_safe_metadata(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(
        status=208,
        body=b'{"id":"openai-router-test","object":"chat.completion"}',
    )
    raw_router_reason = (
        "Select docs/private/router_note.md because the prompt contains "
        "arbitrary router free text."
    )
    router_response = {
        "router_status": "candidate_selected",
        "router_reason": raw_router_reason,
        "candidate_selected_segment_ids": ["segment-3"],
        "estimated_router_selected_input_tokens": 42,
        "estimated_router_token_reduction_pct": 75.5,
        "confidence": 0.87,
        "dry_run_only": True,
    }
    openai_router = _start_lemonade_router(
        body=json.dumps({"output_text": json.dumps(router_response)}).encode("utf-8")
    )
    monkeypatch.setenv(
        "OPENAI_BASE_URL",
        f"http://{openai_router.server_address[0]}:{openai_router.server_address[1]}/v1",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "placeholder-openai-router-key")
    monkeypatch.setenv("SFE_OPENAI_ROUTER_MODEL", "mock-openai-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="openai",
    )
    distractor_a = "SEGMENT A distractor cafeteria operations. " * 4
    useful_segment = (
        "SEGMENT C active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the threshold at 42 kilowatts. "
    ) * 8
    distractor_b = "SEGMENT B distractor logistics notes. " * 4
    question = "What threshold does the active utility tariff memo set?"
    payload = {
        "model": "example-model",
        "messages": [
            {"role": "system", "content": "Answer from supplied segments."},
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": useful_segment},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": question},
        ],
        "stream": False,
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        openai_router.shutdown()
        openai_router.server_close()

    assert response["status"] == 208
    assert response["body"] == {"id": "openai-router-test", "object": "chat.completion"}
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    assert len(RecordingLemonadeRouterHandler.records) == 1

    router_record = RecordingLemonadeRouterHandler.records[-1]
    router_payload = json.loads(router_record["body"].decode("utf-8"))
    assert router_record["path"] == "/v1/responses"
    assert router_record["headers"]["Authorization"] == "Bearer placeholder-openai-router-key"
    assert router_payload["model"] == "mock-openai-router"
    assert router_payload["max_output_tokens"] == 160
    assert "chat_template_kwargs" not in router_payload
    serialized_router_payload = json.dumps(router_payload)
    assert "candidate_segments" in serialized_router_payload
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" in serialized_router_payload
    assert "placeholder-client-token" not in serialized_router_payload
    assert "Authorization" not in serialized_router_payload

    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_enabled"] is True
    assert event["shadow_router_provider"] == "openai"
    assert event["shadow_router_name"] == "openai"
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"
    assert event["shadow_router_reason"] in SAFE_SHADOW_ROUTER_REASONS
    assert event["shadow_router_candidate_selected_segment_ids"] == ["segment-3"]
    assert event["shadow_router_estimated_selected_input_tokens"] == 42
    assert event["shadow_router_estimated_token_reduction_pct"] == 75.5
    assert event["shadow_router_confidence"] == 0.87
    assert event["shadow_router_dry_run_only"] is True
    assert event["shadow_router_rate_limit_decision"]["allowed"] is True

    serialized_event = json.dumps(event)
    joined_logs = "\n".join(logs)
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" not in serialized_event
    assert raw_router_reason not in serialized_event
    assert "docs/private/router_note.md" not in serialized_event
    assert "arbitrary router free text" not in serialized_event
    assert raw_router_reason not in joined_logs
    assert "docs/private/router_note.md" not in joined_logs
    assert "arbitrary router free text" not in joined_logs
    assert "placeholder-openai-router-key" not in serialized_event
    assert "placeholder-client-token" not in serialized_event
    assert "Authorization" not in serialized_event
    assert "UTILITY-RATE-SCHEDULE-DELTA-17" not in joined_logs


def test_shadow_router_openai_missing_api_key_records_safe_error(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(
        status=208,
        body=b'{"id":"openai-router-missing-key-test","object":"chat.completion"}',
    )
    openai_router = _start_lemonade_router()
    monkeypatch.setenv(
        "OPENAI_BASE_URL",
        f"http://{openai_router.server_address[0]}:{openai_router.server_address[1]}/v1",
    )
    monkeypatch.setenv("SFE_OPENAI_ROUTER_MODEL", "mock-openai-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="openai",
    )
    prompt = "synthetic segment " * 20
    payload = {
        "model": "example-model",
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        openai_router.shutdown()
        openai_router.server_close()

    assert response["status"] == 208
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    assert RecordingLemonadeRouterHandler.records == []
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_enabled"] is True
    assert event["shadow_router_provider"] == "openai"
    assert event["shadow_router_status"] == "provider_error"
    assert event["shadow_router_reason"] == "router_call_failed"
    assert event["shadow_router_error_type"] == "MissingAPIKey"
    assert event["shadow_router_candidate_selected_segment_ids"] == []
    assert event["shadow_router_dry_run_only"] is True
    serialized_event = json.dumps(event)
    assert prompt not in serialized_event
    assert "placeholder-client-token" not in serialized_event
    assert prompt not in "\n".join(logs)


def test_shadow_router_lemonade_multisegment_smoke_selects_expected_segment(
    monkeypatch,
    tmp_path,
) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_LEMONADE_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream_body = b'{"id":"multisegment-smoke","object":"chat.completion","choices":[]}'
    upstream = _start_upstream(status=200, body=upstream_body)
    expected_segment_id = "segment-3"
    observed_router_segments: list[dict[str, Any]] = []

    def select_policy_segment(body: bytes) -> bytes:
        lemonade_payload = json.loads(body.decode("utf-8"))
        router_prompt = json.loads(lemonade_payload["messages"][1]["content"])
        segments = router_prompt["candidate_segments"]
        observed_router_segments[:] = segments
        selected = next(
            segment
            for segment in segments
            if "UTILITY-RATE-SCHEDULE-DELTA-17" in segment["text"]
        )
        assert selected["segment_id"] == expected_segment_id
        selected_tokens = int(selected["estimated_tokens"])
        full_tokens = int(router_prompt["rough_estimated_input_tokens"])
        reduction_pct = round((1 - (selected_tokens / full_tokens)) * 100, 2)
        router_output = {
            "router_status": "candidate_selected",
            "router_reason": "selected_tariff_policy_segment_for_question",
            "candidate_selected_segment_ids": [selected["segment_id"]],
            "estimated_router_selected_input_tokens": selected_tokens,
            "estimated_router_token_reduction_pct": reduction_pct,
            "confidence": 0.91,
            "dry_run_only": True,
        }
        return _lemonade_router_body(content=json.dumps(router_output))

    lemonade = _start_lemonade_router(response_factory=select_policy_segment)
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    distractor_a = (
        "SEGMENT A - archived cafeteria operations. "
        "This segment describes badge color rotation, break-room inventory, "
        "and coffee machine cleaning windows. "
    ) * 8
    distractor_b = (
        "SEGMENT B - historical logistics notes. "
        "This segment covers dock assignments, pallet labels, and carrier calls. "
    ) * 8
    useful_segment = (
        "SEGMENT C - active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the battery dispatch threshold at "
        "42 kilowatts during the evening peak interval. "
    ) * 4
    distractor_c = (
        "SEGMENT D - unrelated customer support transcript. "
        "This segment discusses login retries, email aliases, and ticket tags. "
    ) * 8
    question = (
        "Using the active utility tariff memo only, what battery dispatch "
        "threshold applies during the evening peak interval?"
    )
    payload = {
        "model": "example-model",
        "messages": [
            {"role": "system", "content": "Answer from the supplied segments."},
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": useful_segment},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": distractor_c},
            {"role": "user", "content": question},
        ],
        "stream": False,
    }
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
            api_key="placeholder-client-token",
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    assert response["body"] == json.loads(upstream_body.decode("utf-8"))
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    assert RecordingUpstreamHandler.records[-1]["headers"]["Authorization"] == "Bearer upstream-secret"
    assert len(RecordingLemonadeRouterHandler.records) == 1
    assert [segment["segment_id"] for segment in observed_router_segments] == [
        "segment-1",
        "segment-2",
        "segment-3",
        "segment-4",
        "segment-5",
        "segment-6",
    ]

    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_enabled"] is True
    assert event["shadow_router_provider"] == "lemonade"
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"
    assert event["shadow_router_candidate_selected_segment_ids"] == [expected_segment_id]
    assert event["shadow_router_estimated_selected_input_tokens"] > 0
    assert event["shadow_router_estimated_token_reduction_pct"] is not None
    assert event["shadow_router_estimated_token_reduction_pct"] > 0
    assert event["shadow_router_confidence"] == 0.91
    assert event["shadow_router_dry_run_only"] is True
    assert event["selection_status"] == "candidate_selected"
    assert event["would_activate_sfe"] is True
    assert event["candidate_segment_count"] == 6

    serialized_event = json.dumps(event)
    joined_logs = "\n".join(logs)
    assert useful_segment not in serialized_event
    assert question not in serialized_event
    assert "placeholder-client-token" not in serialized_event
    assert "Authorization" not in serialized_event
    assert useful_segment not in joined_logs
    assert question not in joined_logs


def test_shadow_router_lemonade_json_code_fence_succeeds(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(
        status=209,
        body=b'{"id":"fenced-router-test","object":"chat.completion"}',
    )
    router_output = _lemonade_router_result(reason="fenced_json_selection")
    fenced_output = "```json\n" + json.dumps(router_output) + "\n```"
    lemonade = _start_lemonade_router(body=_lemonade_router_body(content=fenced_output))
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    prompt = "synthetic segment"
    try:
        payload = {"model": "example-model", "messages": [{"role": "user", "content": prompt}]}
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 209
    assert response["body"] == {"id": "fenced-router-test", "object": "chat.completion"}
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"
    serialized_event = json.dumps(event)
    assert "```json" not in serialized_event
    assert prompt not in serialized_event
    assert prompt not in "\n".join(logs)


def test_shadow_router_lemonade_prose_wrapped_json_succeeds_without_logging_raw_output(
    monkeypatch,
    tmp_path,
) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    router_output = _lemonade_router_result(reason="prose_wrapped_json_selection")
    raw_prefix = "Local router draft follows:"
    raw_suffix = "End local router draft."
    wrapped_output = f"{raw_prefix}\n{json.dumps(router_output)}\n{raw_suffix}"
    lemonade = _start_lemonade_router(body=_lemonade_router_body(content=wrapped_output))
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    prompt = "synthetic segment"
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": prompt}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"
    serialized_event = json.dumps(event)
    assert raw_prefix not in serialized_event
    assert raw_suffix not in serialized_event
    assert prompt not in serialized_event
    assert raw_prefix not in "\n".join(logs)


def test_shadow_router_lemonade_reasoning_content_fallback_succeeds(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    router_output = _lemonade_router_result(reason="reasoning_content_selection")
    lemonade = _start_lemonade_router(
        body=_lemonade_router_body(content="", reasoning_content=json.dumps(router_output))
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"


def test_shadow_router_lemonade_choice_text_fallback_succeeds(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    router_output = _lemonade_router_result(reason="choice_text_selection")
    lemonade = _start_lemonade_router(body=_lemonade_router_body(text=json.dumps(router_output)))
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"


def test_shadow_router_lemonade_uses_router_model_fallback(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_LEMONADE_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    monkeypatch.delenv("SFE_LEMONADE_MODEL", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade_response = {
        "router_status": "candidate_selected",
        "router_reason": "fallback_model_selection",
        "candidate_selected_segment_ids": ["segment-1"],
        "estimated_router_selected_input_tokens": 5,
        "estimated_router_token_reduction_pct": 60.0,
        "confidence": 0.5,
        "dry_run_only": True,
    }
    lemonade = _start_lemonade_router(
        body=json.dumps(
            {"choices": [{"message": {"content": json.dumps(lemonade_response)}}]}
        ).encode("utf-8")
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_ROUTER_MODEL", "router-fallback-model")
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    assert len(RecordingLemonadeRouterHandler.records) == 1
    lemonade_payload = json.loads(RecordingLemonadeRouterHandler.records[-1]["body"].decode("utf-8"))
    assert lemonade_payload["model"] == "router-fallback-model"
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "candidate_selected"


def test_shadow_router_lemonade_uses_optional_project_api_key_without_logging(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade_response = {
        "router_status": "candidate_selected",
        "router_reason": "api_key_header_selection",
        "candidate_selected_segment_ids": ["segment-1"],
        "estimated_router_selected_input_tokens": 5,
        "estimated_router_token_reduction_pct": 60.0,
        "confidence": 0.5,
        "dry_run_only": True,
    }
    lemonade = _start_lemonade_router(
        body=json.dumps(
            {"choices": [{"message": {"content": json.dumps(lemonade_response)}}]}
        ).encode("utf-8")
    )
    placeholder_key = "placeholder-local-lemonade-key"
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_API_KEY", placeholder_key)
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    prompt = "synthetic segment"
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": prompt}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    assert RecordingLemonadeRouterHandler.records[-1]["headers"]["Authorization"] == (
        f"Bearer {placeholder_key}"
    )
    event = _read_shadow_event(tmp_path)
    serialized_event = json.dumps(event)
    assert event["shadow_router_status"] == "candidate_selected"
    assert placeholder_key not in serialized_event
    assert placeholder_key not in "\n".join(logs)
    assert prompt not in serialized_event


def test_shadow_router_lemonade_missing_model_is_safe_and_skips_call(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    monkeypatch.delenv("SFE_LEMONADE_MODEL", raising=False)
    monkeypatch.delenv("SFE_ROUTER_MODEL", raising=False)
    monkeypatch.delenv("SFE_LEMONADE_API_KEY", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade = _start_lemonade_router()
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    prompt = "synthetic segment"
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": prompt}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    assert response["body"] == {"ok": True}
    assert len(RecordingLemonadeRouterHandler.records) == 0
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "provider_error"
    assert event["shadow_router_reason"] == "router_call_failed"
    assert event["shadow_router_error_type"] == "MissingModel"
    serialized_event = json.dumps(event)
    assert prompt not in serialized_event
    assert "Authorization" not in serialized_event
    assert prompt not in "\n".join(logs)


def test_shadow_router_lemonade_below_threshold_skips_call(tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade = _start_lemonade_router()
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=50000,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "short synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    assert len(RecordingLemonadeRouterHandler.records) == 0
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "not_eligible"
    assert event["shadow_router_reason"] == "not_eligible_below_threshold"


def test_shadow_router_lemonade_invalid_json_is_safe(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade = _start_lemonade_router(
        body=b'{"choices":[{"message":{"content":"not-json"}}]}',
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "invalid_output"
    assert event["shadow_router_reason"] == "router_response_invalid"
    assert event["shadow_router_error_type"] == "JSONDecodeError"


def test_shadow_router_lemonade_reasoning_prose_without_json_stays_invalid_output(
    monkeypatch,
    tmp_path,
) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    reasoning_prose = "This is local router reasoning prose without any JSON braces."
    lemonade = _start_lemonade_router(
        body=_lemonade_router_body(content="", reasoning_content=reasoning_prose)
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    prompt = "synthetic segment"
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": prompt}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "invalid_output"
    assert event["shadow_router_reason"] == "router_response_invalid"
    assert event["shadow_router_error_type"] == "JSONDecodeError"
    serialized_event = json.dumps(event)
    assert reasoning_prose not in serialized_event
    assert prompt not in serialized_event
    assert reasoning_prose not in "\n".join(logs)


def test_shadow_router_lemonade_missing_required_fields_is_safe(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade = _start_lemonade_router(
        body=_lemonade_router_body(content=json.dumps({"router_status": "candidate_selected"}))
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "invalid_output"
    assert event["shadow_router_reason"] == "router_response_invalid"
    assert event["shadow_router_error_type"] == "KeyError"


def test_shadow_router_lemonade_unknown_segment_id_is_safe(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade_response = {
        "router_status": "candidate_selected",
        "router_reason": "unknown_id",
        "candidate_selected_segment_ids": ["segment-999"],
        "estimated_router_selected_input_tokens": 12,
        "estimated_router_token_reduction_pct": 80.0,
        "confidence": 0.42,
        "dry_run_only": True,
    }
    lemonade = _start_lemonade_router(
        body=json.dumps(
            {"choices": [{"message": {"content": json.dumps(lemonade_response)}}]}
        ).encode("utf-8")
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "invalid_output"
    assert event["shadow_router_reason"] == "router_response_invalid"
    assert event["shadow_router_error_type"] == "ValueError"
    assert event["shadow_router_candidate_selected_segment_ids"] == []


def test_shadow_router_lemonade_uses_generic_timeout(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    upstream = _start_upstream(body=b'{"ok":true}')
    observed: dict[str, int] = {}
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
        shadow_router_timeout_seconds=77,
    )

    def observe_timeout(self: LemonadeShadowRouter, router_input: ShadowRouterInput) -> dict[str, Any]:
        observed["timeout_seconds"] = self.config.timeout_seconds
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(_lemonade_router_result(reason="timeout_config_seen"))
                    }
                }
            ]
        }

    monkeypatch.setattr(LemonadeShadowRouter, "_call_lemonade", observe_timeout)
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert observed["timeout_seconds"] == 77
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "candidate_selected"
    assert event["shadow_router_reason"] == "router_call_succeeded"


def test_shadow_router_lemonade_timeout_is_safe(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    upstream = _start_upstream(body=b'{"ok":true}')
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )

    def timeout_call(self: LemonadeShadowRouter, router_input: ShadowRouterInput) -> dict[str, Any]:
        raise TimeoutError("timed out")

    monkeypatch.setattr(LemonadeShadowRouter, "_call_lemonade", timeout_call)
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {"ok": True}
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "provider_error"
    assert event["shadow_router_reason"] == "router_timeout"
    assert event["shadow_router_error_type"] == "TimeoutError"


def test_shadow_router_lemonade_provider_error_is_safe(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.delenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", raising=False)
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    upstream = _start_upstream(body=b'{"ok":true}')
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )

    def fail_call(self: LemonadeShadowRouter, router_input: ShadowRouterInput) -> dict[str, Any]:
        raise urllib.error.URLError("provider unavailable")

    monkeypatch.setattr(LemonadeShadowRouter, "_call_lemonade", fail_call)
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {"ok": True}
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "provider_error"
    assert event["shadow_router_reason"] == "router_call_failed"
    assert event["shadow_router_error_type"] == "URLError"


def test_shadow_router_lemonade_rate_limit_reject_skips_call(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.setenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", "true")
    monkeypatch.setenv("SFE_PROXY_LEMONADE_MAX_INPUT_TOKENS", "1")
    monkeypatch.setenv("SFE_PROXY_LEMONADE_QUEUE_MODE", "reject")
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade = _start_lemonade_router()
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "large synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert response["status"] == 200
    assert len(RecordingLemonadeRouterHandler.records) == 0
    event = _read_shadow_event(tmp_path)
    assert event["shadow_router_status"] == "rate_limited"
    assert event["shadow_router_reason"] == "skipped_for_safety"
    assert event["shadow_router_rate_limit_decision"]["rejected"] is True


def test_shadow_router_lemonade_rate_limit_wait_skips_call_without_sleeping(monkeypatch, tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    monkeypatch.setenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", "true")
    monkeypatch.setenv("SFE_PROXY_LEMONADE_MIN_INTERVAL_MS", "60000")
    monkeypatch.setenv("SFE_PROXY_LEMONADE_QUEUE_MODE", "wait")
    upstream = _start_upstream(body=b'{"ok":true}')
    lemonade_response = {
        "router_status": "candidate_selected",
        "router_reason": "first_call_allowed",
        "candidate_selected_segment_ids": ["segment-1"],
        "estimated_router_selected_input_tokens": 1,
        "estimated_router_token_reduction_pct": 50.0,
        "confidence": 0.1,
        "dry_run_only": True,
    }
    lemonade = _start_lemonade_router(
        body=json.dumps(
            {"choices": [{"message": {"content": json.dumps(lemonade_response)}}]}
        ).encode("utf-8")
    )
    monkeypatch.setenv("SFE_LEMONADE_BASE_URL", f"http://{lemonade.server_address[0]}:{lemonade.server_address[1]}")
    monkeypatch.setenv("SFE_LEMONADE_MODEL", "local-router")
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        url = f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions"
        payload = {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]}
        first = _request_json(url, payload)
        second = _request_json(url, payload)
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert first["status"] == 200
    assert second["status"] == 200
    assert len(RecordingLemonadeRouterHandler.records) == 1
    events = _read_shadow_events(tmp_path)
    assert events[0]["shadow_router_status"] == "candidate_selected"
    assert events[1]["shadow_router_status"] == "rate_limited"
    assert events[1]["shadow_router_reason"] == "skipped_for_safety"
    assert events[1]["shadow_router_rate_limit_decision"]["wait_required"] is True


def test_pass_through_mode_does_not_call_lemonade_router(tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    upstream = _start_upstream()
    lemonade = _start_lemonade_router()
    proxy = _start_proxy(
        upstream,
        [],
        mode="pass_through",
        shadow_log_dir=str(tmp_path),
        shadow_router_dry_run=True,
        shadow_router_provider="lemonade",
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert len(RecordingLemonadeRouterHandler.records) == 0
    assert not (tmp_path / "shadow_events.jsonl").exists()


def test_shadow_mode_router_disabled_does_not_call_lemonade(tmp_path) -> None:
    shadow_router_module._reset_provider_call_state()
    upstream = _start_upstream()
    lemonade = _start_lemonade_router()
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_router_dry_run=False,
        shadow_router_provider="lemonade",
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "synthetic segment"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    assert len(RecordingLemonadeRouterHandler.records) == 0
    event = _read_shadow_event(tmp_path)
    assert "shadow_router_enabled" not in event


def test_provider_limit_defaults_are_disabled_and_unlimited() -> None:
    registry = ProviderLimitRegistry.from_env({})
    config = registry.config_for("openai")

    assert config.enabled is False
    assert config.min_interval_ms == 0
    assert config.max_input_tokens == 0
    assert config.max_requests_per_minute == 0
    assert config.queue_mode == "reject"

    decision = registry.limiter_for("openai").decide(estimated_input_tokens=999999)
    assert decision.allowed is True
    assert decision.reason == "limits_disabled"


def test_provider_limit_explicit_empty_env_ignores_process_env(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_PROVIDER_LIMITS_ENABLED", "true")
    monkeypatch.setenv("SFE_PROXY_OPENAI_MAX_INPUT_TOKENS", "1")

    registry = ProviderLimitRegistry.from_env({})
    config = registry.config_for("openai")

    assert config.enabled is False
    assert config.max_input_tokens == 0


def test_provider_specific_values_override_defaults() -> None:
    registry = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_PROVIDER_DEFAULT_MIN_INTERVAL_MS": "100",
            "SFE_PROXY_PROVIDER_DEFAULT_MAX_INPUT_TOKENS": "1000",
            "SFE_PROXY_PROVIDER_DEFAULT_MAX_REQUESTS_PER_MINUTE": "10",
            "SFE_PROXY_PROVIDER_DEFAULT_QUEUE_MODE": "reject",
            "SFE_PROXY_OPENAI_MIN_INTERVAL_MS": "250",
            "SFE_PROXY_OPENAI_MAX_INPUT_TOKENS": "2000",
            "SFE_PROXY_OPENAI_MAX_REQUESTS_PER_MINUTE": "20",
            "SFE_PROXY_OPENAI_QUEUE_MODE": "wait",
        }
    )

    openai_config = registry.config_for("openai")
    anthropic_config = registry.config_for("anthropic")

    assert openai_config.enabled is True
    assert openai_config.min_interval_ms == 250
    assert openai_config.max_input_tokens == 2000
    assert openai_config.max_requests_per_minute == 20
    assert openai_config.queue_mode == "wait"
    assert anthropic_config.min_interval_ms == 100
    assert anthropic_config.max_input_tokens == 1000
    assert anthropic_config.max_requests_per_minute == 10
    assert anthropic_config.queue_mode == "reject"


def test_anthropic_provider_limits_parse_explicit_values() -> None:
    registry = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_ANTHROPIC_MIN_INTERVAL_MS": "600000",
            "SFE_PROXY_ANTHROPIC_MAX_INPUT_TOKENS": "40000",
            "SFE_PROXY_ANTHROPIC_MAX_REQUESTS_PER_MINUTE": "1",
            "SFE_PROXY_ANTHROPIC_QUEUE_MODE": "wait",
        }
    )

    config = registry.config_for("anthropic")

    assert config.enabled is True
    assert config.min_interval_ms == 600000
    assert config.max_input_tokens == 40000
    assert config.max_requests_per_minute == 1
    assert config.queue_mode == "wait"


def test_provider_limit_zero_means_unlimited() -> None:
    limiter = ProviderRateLimiter(
        ProviderLimitRegistry.from_env(
            {
                "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
                "SFE_PROXY_OPENAI_MAX_INPUT_TOKENS": "0",
                "SFE_PROXY_OPENAI_MAX_REQUESTS_PER_MINUTE": "0",
                "SFE_PROXY_OPENAI_MIN_INTERVAL_MS": "0",
            }
        ).config_for("openai")
    )

    decision = limiter.decide(
        estimated_input_tokens=500000,
        elapsed_since_last_request_ms=0,
        requests_in_last_minute=1000,
    )

    assert decision.allowed is True
    assert decision.reason == "within_limits"


def test_provider_limit_invalid_numeric_values_fail_clearly() -> None:
    try:
        ProviderLimitRegistry.from_env({"SFE_PROXY_OPENAI_MAX_INPUT_TOKENS": "not-an-int"})
    except ValueError as exc:
        assert "SFE_PROXY_OPENAI_MAX_INPUT_TOKENS must be an integer" in str(exc)
    else:
        raise AssertionError("invalid numeric limit should fail")


def test_provider_limit_negative_numeric_values_fail_clearly() -> None:
    try:
        ProviderLimitRegistry.from_env({"SFE_PROXY_OPENAI_MIN_INTERVAL_MS": "-1"})
    except ValueError as exc:
        assert "SFE_PROXY_OPENAI_MIN_INTERVAL_MS must be non-negative" in str(exc)
    else:
        raise AssertionError("negative numeric limit should fail")


def test_provider_limit_invalid_queue_mode_fails_clearly() -> None:
    try:
        ProviderLimitRegistry.from_env({"SFE_PROXY_OPENAI_QUEUE_MODE": "sleep"})
    except ValueError as exc:
        assert "SFE_PROXY_OPENAI_QUEUE_MODE must be one of" in str(exc)
    else:
        raise AssertionError("invalid queue mode should fail")


def test_provider_limit_allows_under_limits() -> None:
    limiter = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_OPENAI_MAX_INPUT_TOKENS": "100",
            "SFE_PROXY_OPENAI_MIN_INTERVAL_MS": "100",
            "SFE_PROXY_OPENAI_MAX_REQUESTS_PER_MINUTE": "10",
        }
    ).limiter_for("openai")

    decision = limiter.decide(
        estimated_input_tokens=50,
        elapsed_since_last_request_ms=100,
        requests_in_last_minute=9,
    )

    assert decision.allowed is True
    assert decision.rejected is False
    assert decision.wait_required is False
    assert decision.reason == "within_limits"


def test_provider_limit_rejects_when_input_tokens_exceeded() -> None:
    limiter = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_OPENAI_MAX_INPUT_TOKENS": "100",
            "SFE_PROXY_OPENAI_QUEUE_MODE": "reject",
        }
    ).limiter_for("openai")

    decision = limiter.decide(estimated_input_tokens=101)

    assert decision.allowed is False
    assert decision.rejected is True
    assert decision.wait_required is False
    assert decision.reason == "max_input_tokens_exceeded"


def test_provider_limit_token_cap_rejects_even_in_wait_mode() -> None:
    limiter = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_OPENAI_MAX_INPUT_TOKENS": "100",
            "SFE_PROXY_OPENAI_QUEUE_MODE": "wait",
        }
    ).limiter_for("openai")

    decision = limiter.decide(estimated_input_tokens=101)

    assert decision.allowed is False
    assert decision.rejected is True
    assert decision.wait_required is False
    assert decision.reason == "max_input_tokens_exceeded"


def test_provider_limit_wait_required_without_sleeping_for_pacing() -> None:
    limiter = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_ANTHROPIC_MIN_INTERVAL_MS": "1000",
            "SFE_PROXY_ANTHROPIC_QUEUE_MODE": "wait",
        }
    ).limiter_for("anthropic")

    decision = limiter.decide(
        estimated_input_tokens=50,
        elapsed_since_last_request_ms=250,
    )

    assert decision.allowed is False
    assert decision.rejected is False
    assert decision.wait_required is True
    assert decision.reason == "min_interval_ms_not_elapsed"
    assert decision.wait_ms == 750


def test_provider_limit_wait_required_without_sleeping_for_rpm() -> None:
    limiter = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_ANTHROPIC_MAX_REQUESTS_PER_MINUTE": "1",
            "SFE_PROXY_ANTHROPIC_QUEUE_MODE": "wait",
        }
    ).limiter_for("anthropic")

    decision = limiter.decide(
        estimated_input_tokens=50,
        requests_in_last_minute=1,
    )

    assert decision.allowed is False
    assert decision.rejected is False
    assert decision.wait_required is True
    assert decision.reason == "max_requests_per_minute_exceeded"
    assert decision.wait_ms == 60000


def test_provider_limit_disabled_provider_is_harmless() -> None:
    registry = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_PROVIDER_DEFAULT_MAX_INPUT_TOKENS": "1",
        }
    )

    config = registry.config_for("disabled")
    decision = registry.limiter_for("disabled").decide(estimated_input_tokens=999999)

    assert config.enabled is False
    assert decision.allowed is True
    assert decision.reason == "limits_disabled"


def test_provider_limit_unknown_provider_fails_clearly() -> None:
    registry = ProviderLimitRegistry.from_env({})

    try:
        registry.config_for("unknown")
    except ValueError as exc:
        assert "Unsupported provider key" in str(exc)
    else:
        raise AssertionError("unknown provider key should fail")


def test_provider_limit_decision_metadata_is_json_compatible() -> None:
    decision = ProviderLimitRegistry.from_env(
        {
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": "true",
            "SFE_PROXY_OPENAI_MAX_INPUT_TOKENS": "100",
        }
    ).limiter_for("openai").decide(estimated_input_tokens=101)

    metadata = decision.to_metadata()

    json.dumps(metadata)
    assert metadata["configured_limits"]["max_input_tokens"] == 100
    assert metadata["estimated_input_tokens"] == 101


def test_shadow_selection_dry_run_failure_does_not_break_pass_through(
    monkeypatch,
    tmp_path,
) -> None:
    upstream = _start_upstream(body=b'{"ok":true}')
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
    )

    def fail_selection(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("selection failed")

    monkeypatch.setattr(proxy_server, "_build_shadow_selection_fields", fail_selection)
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {"ok": True}
    event = _read_shadow_event(tmp_path)
    assert event["shadow_selection_enabled"] is True
    assert event["would_activate_sfe_is_dry_run_only"] is True
    assert event["would_activate_sfe"] is False
    assert event["selection_status"] == "error"
    assert event["selection_reason"] == "dry_run_analysis_error"
    assert event["selection_error_type"] == "RuntimeError"


def test_shadow_selection_dry_run_mixed_non_text_payload_does_not_break_pass_through(
    tmp_path,
) -> None:
    upstream = _start_upstream(body=b'{"ok":true}')
    proxy = _start_proxy(
        upstream,
        [],
        mode="shadow",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
    )
    try:
        payload = {
            "model": "example-model",
            "messages": [
                {"role": "user", "content": [{"type": "input_image", "image_url": "https://example.invalid/x.png"}]},
                {"role": "user", "content": [{"type": "input_text", "text": "safe text"}]},
            ],
        }
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            payload,
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert json.loads(RecordingUpstreamHandler.records[-1]["body"].decode("utf-8")) == payload
    event = _read_shadow_event(tmp_path)
    assert event["shadow_selection_enabled"] is True
    assert event["selection_status"] in {"candidate_selected", "no_selection"}
    assert "https://example.invalid/x.png" not in json.dumps(event)


def test_shadow_log_write_failure_does_not_break_pass_through(tmp_path) -> None:
    upstream = _start_upstream(body=b'{"ok":true}')
    log_path = tmp_path / "not-a-directory"
    log_path.write_text("already a file", encoding="utf-8")
    logs: list[str] = []
    proxy = _start_proxy(
        upstream,
        logs,
        mode="shadow",
        shadow_log_dir=str(log_path),
        shadow_min_input_tokens=1,
    )
    try:
        response = _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert response["status"] == 200
    assert response["body"] == {"ok": True}
    assert "shadow_log_write_failed" in "\n".join(logs)


def test_pass_through_mode_does_not_write_shadow_log(tmp_path) -> None:
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        mode="pass_through",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert not (tmp_path / "shadow_events.jsonl").exists()


def test_pass_through_mode_does_not_write_selection_log(tmp_path) -> None:
    upstream = _start_upstream()
    proxy = _start_proxy(
        upstream,
        [],
        mode="pass_through",
        shadow_log_dir=str(tmp_path),
        shadow_min_input_tokens=1,
        shadow_selection_dry_run=True,
    )
    try:
        _request_json(
            f"http://{proxy.server_address[0]}:{proxy.server_address[1]}/v1/chat/completions",
            {"model": "example-model", "messages": [{"role": "user", "content": "hello"}]},
        )
    finally:
        proxy.shutdown()
        proxy.server_close()
        upstream.shutdown()
        upstream.server_close()

    assert not (tmp_path / "shadow_events.jsonl").exists()


def test_sse_content_type_detection_allows_parameters() -> None:
    assert _is_sse_response("text/event-stream")
    assert _is_sse_response("text/event-stream; charset=utf-8")
    assert not _is_sse_response("application/json")


def _start_upstream(
    *,
    status: int = 200,
    body: bytes = b'{"ok":true}',
    headers: dict[str, str] | None = None,
) -> ThreadingHTTPServer:
    RecordingUpstreamHandler.records = []
    RecordingUpstreamHandler.response_status = status
    RecordingUpstreamHandler.response_body = body
    RecordingUpstreamHandler.response_headers = headers or {"Content-Type": "application/json"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingUpstreamHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _start_lemonade_router(
    *,
    status: int = 200,
    body: bytes = b'{"choices":[{"message":{"content":"{}"}}]}',
    headers: dict[str, str] | None = None,
    response_factory: Any = None,
) -> ThreadingHTTPServer:
    RecordingLemonadeRouterHandler.records = []
    RecordingLemonadeRouterHandler.response_status = status
    RecordingLemonadeRouterHandler.response_body = body
    RecordingLemonadeRouterHandler.response_headers = headers or {"Content-Type": "application/json"}
    RecordingLemonadeRouterHandler.response_factory = response_factory
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingLemonadeRouterHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _start_anthropic_provider(
    *,
    status: int = 200,
    body: bytes = b'{"id":"msg_test","type":"message","role":"assistant","model":"claude-test","content":[{"type":"text","text":"hello from anthropic"}]}',
    headers: dict[str, str] | None = None,
    response_delay_seconds: float = 0.0,
) -> ThreadingHTTPServer:
    RecordingAnthropicHandler.records = []
    RecordingAnthropicHandler.response_status = status
    RecordingAnthropicHandler.response_body = body
    RecordingAnthropicHandler.response_headers = headers or {"Content-Type": "application/json"}
    RecordingAnthropicHandler.response_delay_seconds = response_delay_seconds
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingAnthropicHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _lemonade_router_result(reason: str = "test_router_selection") -> dict[str, Any]:
    return {
        "router_status": "candidate_selected",
        "router_reason": reason,
        "candidate_selected_segment_ids": ["segment-1"],
        "estimated_router_selected_input_tokens": 12,
        "estimated_router_token_reduction_pct": 80.0,
        "confidence": 0.42,
        "dry_run_only": True,
    }


def _lemonade_router_body(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    text: str | None = None,
) -> bytes:
    choice: dict[str, Any] = {}
    message: dict[str, Any] = {}
    if content is not None:
        message["content"] = content
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    if message:
        choice["message"] = message
    if text is not None:
        choice["text"] = text
    return json.dumps({"choices": [choice]}).encode("utf-8")


def _responses_text_item(role: str, text: str) -> dict[str, Any]:
    return {
        "role": role,
        "content": [{"type": "input_text", "text": text}],
    }


def _start_proxy(
    upstream: ThreadingHTTPServer,
    logs: list[str],
    **config_overrides: Any,
) -> ThreadingHTTPServer:
    host, port = upstream.server_address
    config_values = {
        "host": "127.0.0.1",
        "port": _free_port(),
        "upstream_base_url": f"http://{host}:{port}",
        "upstream_api_key": "upstream-secret",
    }
    config_values.update(config_overrides)
    proxy = create_server(
        ProxyConfig(**config_values),
        log_sink=logs.append,
    )
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    return proxy


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _request_json(url: str, payload: dict[str, Any], api_key: str = "client-key") -> dict[str, Any]:
    raw = _request_raw(url, method="POST", payload=payload, api_key=api_key)
    return {"status": raw["status"], "body": json.loads(raw["body"].decode("utf-8"))}


def _request_raw(
    url: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    api_key: str = "client-key",
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {api_key}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return {
            "status": response.status,
            "body": response.read(),
            "content_type": response.headers.get("Content-Type"),
            "headers": response.headers,
        }


def _read_shadow_event(log_dir: Path) -> dict[str, Any]:
    events = _read_shadow_events(log_dir)
    assert len(events) == 1
    return events[0]


def _read_shadow_events(log_dir: Path) -> list[dict[str, Any]]:
    lines = (log_dir / "shadow_events.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def _last_proxy_log(logs: list[str], path: str | None = None) -> dict[str, Any]:
    events = [json.loads(line) for line in logs]
    if path is not None:
        events = [event for event in events if event.get("path") == path]
    assert events
    return events[-1]
