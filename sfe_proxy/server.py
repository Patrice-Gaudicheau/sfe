"""OpenAI-compatible pass-through proxy server."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socket import socket
from typing import Any, Callable

from .config import ProxyConfig


SUPPORTED_GET_PATHS = {"/v1/models"}
SUPPORTED_POST_PATHS = {"/v1/chat/completions", "/v1/responses"}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
SENSITIVE_HEADERS = {"authorization", "x-api-key", "api-key"}
DOWNSTREAM_RESPONSE_HEADERS_TO_STRIP = HOP_BY_HOP_HEADERS | {
    "content-length",
    "date",
    "server",
    "set-cookie",
}


class SFEProxyServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        config: ProxyConfig,
        log_sink: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.config = config
        self.log_sink = log_sink or (lambda line: print(line, file=sys.stderr, flush=True))


class ProxyHandler(BaseHTTPRequestHandler):
    server: SFEProxyServer
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._proxy_request()

    def do_POST(self) -> None:
        self._proxy_request()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Request logging is handled by _log_request without prompt or secret data.
        return

    def _proxy_request(self) -> None:
        started = time.perf_counter()
        path = _path_without_query(self.path)
        body = self._read_body()
        model, stream = _request_metadata(body)
        upstream_url = _upstream_url(self.server.config, self.path)
        status_code = 502
        shadow_event = (
            _build_shadow_event(self.server.config, self.command, path, body)
            if _should_shadow_observe(self.server.config, self.command, path)
            else None
        )
        try:
            if not _allowed_path(self.command, path):
                self._send_json(
                    404,
                    {"error": {"message": "Unsupported proxy endpoint", "path": path}},
                )
                status_code = 404
                return
            request = self._build_upstream_request(upstream_url, body)
            try:
                with urllib.request.urlopen(request, timeout=300) as upstream:
                    status_code = int(upstream.status)
                    self._send_upstream_response(upstream)
            except urllib.error.HTTPError as exc:
                status_code = int(exc.code)
                self._send_upstream_response(exc)
            except urllib.error.URLError as exc:
                status_code = 502
                self._send_json(
                    502,
                    {"error": {"message": "Upstream request failed", "type": "upstream_error"}},
                )
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            if shadow_event is not None:
                shadow_event["upstream_status_code"] = status_code
                shadow_event["upstream_latency_ms"] = latency_ms
                self._write_shadow_event(shadow_event)
            self._log_request(
                upstream_url=upstream_url,
                status_code=status_code,
                latency_ms=latency_ms,
                model=model,
                stream=stream,
            )

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _build_upstream_request(self, upstream_url: str, body: bytes) -> urllib.request.Request:
        headers = _forward_headers(self.headers)
        headers["Authorization"] = f"Bearer {self.server.config.upstream_api_key}"
        if body and "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(
            upstream_url,
            data=body if self.command == "POST" else None,
            headers=headers,
            method=self.command,
        )

    def _send_upstream_response(self, upstream: Any) -> None:
        self.close_connection = True
        self.send_response(int(upstream.status if hasattr(upstream, "status") else upstream.code))
        content_type = ""
        for key, value in upstream.headers.items():
            if key.lower() in DOWNSTREAM_RESPONSE_HEADERS_TO_STRIP:
                continue
            if key.lower() == "content-type":
                content_type = value
            self.send_header(key, value)
        self.send_header("Connection", "close")
        self.end_headers()
        if _is_sse_response(content_type):
            self._stream_sse_response(upstream)
        else:
            self._stream_chunked_response(upstream)

    def _stream_chunked_response(self, upstream: Any) -> None:
        while True:
            chunk = upstream.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)
            self.wfile.flush()

    def _stream_sse_response(self, upstream: Any) -> None:
        while True:
            line = upstream.readline()
            if not line:
                break
            self.wfile.write(line)
            self.wfile.flush()

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _log_request(
        self,
        *,
        upstream_url: str,
        status_code: int,
        latency_ms: int,
        model: str | None,
        stream: bool | None,
    ) -> None:
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "method": self.command,
            "path": _path_without_query(self.path),
            "upstream_url": upstream_url,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "model": model,
            "stream": stream,
        }
        self.server.log_sink(json.dumps(event, sort_keys=True))

    def _write_shadow_event(self, event: dict[str, Any]) -> None:
        try:
            log_dir = Path(self.server.config.shadow_log_dir)
            log_dir.mkdir(parents=True, exist_ok=True)
            with (log_dir / "shadow_events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
        except OSError as exc:
            self.server.log_sink(
                json.dumps(
                    {
                        "event": "shadow_log_write_failed",
                        "message": str(exc),
                        "path": _path_without_query(self.path),
                    },
                    sort_keys=True,
                )
            )


def create_server(
    config: ProxyConfig,
    log_sink: Callable[[str], None] | None = None,
) -> SFEProxyServer:
    config = config.validated()
    _ensure_port_available(config.host, config.port)
    return SFEProxyServer((config.host, config.port), ProxyHandler, config, log_sink=log_sink)


def run_server(config: ProxyConfig) -> None:
    server = create_server(config)
    print(
        f"SFE proxy mode listening on http://{config.host}:{config.port} "
        f"and forwarding to {config.normalized_upstream_base_url}",
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _allowed_path(method: str, path: str) -> bool:
    if method == "GET":
        return path in SUPPORTED_GET_PATHS
    if method == "POST":
        return path in SUPPORTED_POST_PATHS
    return False


def _path_without_query(path: str) -> str:
    return urllib.parse.urlsplit(path).path


def _upstream_url(config: ProxyConfig, path: str) -> str:
    return f"{config.normalized_upstream_base_url}{path}"


def _request_metadata(body: bytes) -> tuple[str | None, bool | None]:
    if not body:
        return None, None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, None
    if not isinstance(payload, dict):
        return None, None
    model = payload.get("model")
    stream = payload.get("stream")
    return (model if isinstance(model, str) else None, stream if isinstance(stream, bool) else None)


def _forward_headers(headers: Any) -> dict[str, str]:
    forwarded: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if lowered in HOP_BY_HOP_HEADERS or lowered in SENSITIVE_HEADERS:
            continue
        if lowered == "host":
            continue
        forwarded[key] = value
    return forwarded


def _is_sse_response(content_type: str) -> bool:
    return content_type.lower().split(";", 1)[0].strip() == "text/event-stream"


def _should_shadow_observe(config: ProxyConfig, method: str, path: str) -> bool:
    return config.mode == "shadow" and method == "POST" and path in SUPPORTED_POST_PATHS


def _build_shadow_event(
    config: ProxyConfig,
    method: str,
    path: str,
    body: bytes,
) -> dict[str, Any]:
    payload = _decode_json_object(body)
    texts = list(_iter_text_values(payload)) if payload is not None else []
    largest_text_chars = max((len(text) for text in texts), default=0)
    largest_text_bytes = max((len(text.encode("utf-8")) for text in texts), default=0)
    rough_estimated_input_tokens = _rough_estimate_tokens_from_texts(texts, body)
    eligible = rough_estimated_input_tokens > config.shadow_min_input_tokens
    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": "sfe_proxy_shadow_observation",
        "mode": config.mode,
        "method": method,
        "endpoint": path,
        "model": _payload_model(payload),
        "stream": _payload_stream(payload),
        "request_body_bytes": len(body),
        "rough_estimated_input_tokens": rough_estimated_input_tokens,
        "rough_token_estimate_method": "text_chars_div_4_min_body_bytes_div_4",
        "message_count": _chat_message_count(path, payload),
        "input_item_count": _responses_input_item_count(path, payload),
        "largest_text_field_chars": largest_text_chars,
        "largest_text_field_bytes": largest_text_bytes,
        "sfe_routing_eligible": eligible,
        "eligibility_reason": (
            "rough_estimated_input_tokens_above_threshold"
            if eligible
            else "rough_estimated_input_tokens_below_threshold"
        ),
        "eligibility_threshold_tokens": config.shadow_min_input_tokens,
        "full_payload_logging_enabled": False,
        "full_payload_logging_requested": config.shadow_log_full_payloads,
    }
    return event


def _decode_json_object(body: bytes) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _payload_model(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    model = payload.get("model")
    return model if isinstance(model, str) else None


def _payload_stream(payload: dict[str, Any] | None) -> bool | None:
    if payload is None:
        return None
    stream = payload.get("stream")
    return stream if isinstance(stream, bool) else None


def _chat_message_count(path: str, payload: dict[str, Any] | None) -> int | None:
    if path != "/v1/chat/completions" or payload is None:
        return None
    messages = payload.get("messages")
    return len(messages) if isinstance(messages, list) else None


def _responses_input_item_count(path: str, payload: dict[str, Any] | None) -> int | None:
    if path != "/v1/responses" or payload is None:
        return None
    input_value = payload.get("input")
    return len(input_value) if isinstance(input_value, list) else (1 if input_value is not None else None)


def _iter_text_values(value: Any) -> list[str]:
    texts: list[str] = []
    if isinstance(value, str):
        texts.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            texts.extend(_iter_text_values(child))
    elif isinstance(value, list):
        for child in value:
            texts.extend(_iter_text_values(child))
    return texts


def _rough_estimate_tokens_from_texts(texts: list[str], body: bytes) -> int:
    text_chars = sum(len(text) for text in texts)
    text_estimate = (text_chars + 3) // 4
    body_estimate = (len(body) + 3) // 4
    return max(text_estimate, body_estimate)


def _ensure_port_available(host: str, port: int) -> None:
    with socket() as probe:
        try:
            probe.bind((host, port))
        except OSError as exc:
            raise RuntimeError(f"Proxy port {host}:{port} is not available.") from exc
