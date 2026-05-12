"""Tests for SFE proxy mode."""

from __future__ import annotations

import json
import socket
import sys
import threading
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
    DEFAULT_HOST,
    DEFAULT_MODE,
    DEFAULT_PORT,
    DEFAULT_SHADOW_LOG_DIR,
    DEFAULT_SHADOW_MIN_INPUT_TOKENS,
    DEFAULT_SHADOW_ROUTER_TIMEOUT_SECONDS,
    DEFAULT_UPSTREAM_BASE_URL,
    ProxyConfig,
)
from sfe_proxy.provider_limits import ProviderLimitRegistry, ProviderRateLimiter
from sfe_proxy.server import _is_sse_response, create_server
from sfe_proxy.shadow_router import (
    DisabledShadowRouter,
    LemonadeShadowRouter,
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
        self.send_response(self.__class__.response_status)
        for key, value in self.__class__.response_headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(self.__class__.response_body)))
        self.end_headers()
        self.wfile.write(self.__class__.response_body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def test_proxy_config_defaults_and_required_key(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_HOST", raising=False)
    monkeypatch.delenv("SFE_PROXY_PORT", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_MODE", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_MIN_INPUT_TOKENS", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_LOG_DIR", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_LOG_FULL_PAYLOADS", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_SELECTION_DRY_RUN", raising=False)
    monkeypatch.delenv("SFE_PROXY_SHADOW_ROUTER_TIMEOUT_SECONDS", raising=False)
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


def test_proxy_config_rejects_unsupported_shadow_router_provider(monkeypatch) -> None:
    monkeypatch.setenv("SFE_PROXY_UPSTREAM_API_KEY", "placeholder")
    monkeypatch.setenv("SFE_PROXY_SHADOW_ROUTER_PROVIDER", "openai")

    try:
        ProxyConfig.from_env()
    except ValueError as exc:
        assert "Unsupported SFE_PROXY_SHADOW_ROUTER_PROVIDER" in str(exc)
        assert "disabled" in str(exc)
        assert "lemonade" in str(exc)
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


def test_models_and_responses_endpoints_are_forwarded() -> None:
    upstream = _start_upstream(body=b'{"data":[{"id":"m"}]}')
    proxy = _start_proxy(upstream, [])
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
    proxy = _start_proxy(
        upstream,
        [],
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
        "shadow_router_reason": "shadow_router_provider_disabled",
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
    assert event_fields["shadow_router_dry_run_only"] is True


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
    assert event["shadow_router_reason"] == "shadow_router_provider_disabled"
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
    assert event["shadow_router_reason"] == "metadata_only_dry_run_selection"
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
    assert event["shadow_router_reason"] == "fenced_json_selection"
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
    assert event["shadow_router_reason"] == "prose_wrapped_json_selection"
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
    assert event["shadow_router_reason"] == "reasoning_content_selection"


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
    assert event["shadow_router_reason"] == "choice_text_selection"


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
    assert event["shadow_router_reason"] == "lemonade_router_missing_model"
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
    assert event["shadow_router_reason"] == "sfe_routing_eligible_false"


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
    assert event["shadow_router_reason"] == "lemonade_router_invalid_json"
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
    assert event["shadow_router_reason"] == "lemonade_router_invalid_json"
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
    assert event["shadow_router_reason"] == "lemonade_router_malformed_result"
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
    assert event["shadow_router_reason"] == "lemonade_router_malformed_result"
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
    assert event["shadow_router_reason"] == "timeout_config_seen"


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
    assert event["shadow_router_reason"] == "lemonade_router_timeout"
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
    assert event["shadow_router_reason"] == "lemonade_router_provider_error"
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
    assert event["shadow_router_reason"] == "max_input_tokens_exceeded"
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
    assert events[1]["shadow_router_reason"] == "min_interval_ms_not_elapsed"
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
) -> ThreadingHTTPServer:
    RecordingLemonadeRouterHandler.records = []
    RecordingLemonadeRouterHandler.response_status = status
    RecordingLemonadeRouterHandler.response_body = body
    RecordingLemonadeRouterHandler.response_headers = headers or {"Content-Type": "application/json"}
    server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingLemonadeRouterHandler)
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
