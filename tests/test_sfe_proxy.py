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

from sfe_proxy.config import (
    DEFAULT_HOST,
    DEFAULT_MODE,
    DEFAULT_PORT,
    DEFAULT_UPSTREAM_BASE_URL,
    ProxyConfig,
)
from sfe_proxy.server import _is_sse_response, create_server


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


def test_proxy_config_defaults_and_required_key(monkeypatch) -> None:
    monkeypatch.delenv("SFE_PROXY_HOST", raising=False)
    monkeypatch.delenv("SFE_PROXY_PORT", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_BASE_URL", raising=False)
    monkeypatch.delenv("SFE_PROXY_UPSTREAM_API_KEY", raising=False)
    monkeypatch.delenv("SFE_PROXY_MODE", raising=False)
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
    monkeypatch.setenv("SFE_PROXY_MODE", "shadow")

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
            api_key="client-secret",
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
    assert "client-secret" not in joined_logs
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


def _start_proxy(upstream: ThreadingHTTPServer, logs: list[str]) -> ThreadingHTTPServer:
    host, port = upstream.server_address
    proxy = create_server(
        ProxyConfig(
            host="127.0.0.1",
            port=_free_port(),
            upstream_base_url=f"http://{host}:{port}",
            upstream_api_key="upstream-secret",
        ),
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
