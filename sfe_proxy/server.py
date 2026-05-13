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

from .config import DRY_RUN_ENABLED_MODE, SHADOW_MODE, ProxyConfig
from .shadow_router import ShadowRouterInput, create_shadow_router


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
    return config.mode in {SHADOW_MODE, DRY_RUN_ENABLED_MODE} and method == "POST" and path in SUPPORTED_POST_PATHS


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
    if config.shadow_selection_dry_run or config.mode == DRY_RUN_ENABLED_MODE:
        event.update(_safe_shadow_selection_fields(config, path, payload, rough_estimated_input_tokens))
    if config.shadow_router_dry_run:
        event.update(_safe_shadow_router_fields(config, event, path, payload))
    if config.mode == DRY_RUN_ENABLED_MODE:
        event.update(
            _safe_dry_run_enabled_fields(
                config,
                path,
                payload,
                event,
                rough_estimated_input_tokens,
            )
        )
    return event


def _safe_dry_run_enabled_fields(
    config: ProxyConfig,
    path: str,
    payload: dict[str, Any] | None,
    event: dict[str, Any],
    rough_estimated_input_tokens: int,
) -> dict[str, Any]:
    try:
        return _build_dry_run_enabled_fields(
            config,
            path,
            payload,
            event,
            rough_estimated_input_tokens,
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "dry_run_enabled_candidate_built": False,
            "dry_run_enabled_error_type": type(exc).__name__,
            "dry_run_enabled_reason": "candidate_request_build_error",
            "dry_run_enabled_is_real_execution": False,
        }


def _build_dry_run_enabled_fields(
    config: ProxyConfig,
    path: str,
    payload: dict[str, Any] | None,
    event: dict[str, Any],
    rough_estimated_input_tokens: int,
) -> dict[str, Any]:
    selected_segment_ids = _selected_segment_ids_for_dry_run(event)
    segments = _extract_candidate_text_segments(path, payload)
    segment_by_id = {segment["segment_id"]: segment for segment in segments}
    selected_segments = [
        segment_by_id[segment_id]
        for segment_id in selected_segment_ids
        if segment_id in segment_by_id
    ]
    question_text = _last_text_segment(segments)
    if not selected_segments:
        return {
            "dry_run_enabled_candidate_built": False,
            "dry_run_enabled_reason": "no_selected_segments",
            "dry_run_enabled_selected_segment_ids": selected_segment_ids,
            "dry_run_enabled_is_real_execution": False,
            "dry_run_enabled_replaces_upstream_request": False,
            "dry_run_enabled_changes_client_response": False,
            "dry_run_enabled_candidate_request_sent_to_upstream": False,
            "dry_run_enabled_experimental_response_exposed": False,
            "dry_run_enabled_original_upstream_request_unchanged": True,
            "dry_run_enabled_client_response_unchanged": True,
            "dry_run_enabled_candidate_request_estimated_tokens": None,
            "dry_run_enabled_estimated_token_reduction_pct": None,
            "dry_run_enabled_selected_segment_count": 0,
        }

    candidate_request = _candidate_request_for_endpoint(
        path,
        payload,
        selected_segments,
        question_text,
    )
    candidate_tokens = _rough_estimate_tokens_from_texts(
        _iter_text_values(candidate_request),
        json.dumps(candidate_request, sort_keys=True).encode("utf-8"),
    )
    reduction_pct = (
        round((1 - (candidate_tokens / rough_estimated_input_tokens)) * 100, 2)
        if rough_estimated_input_tokens > 0
        else 0.0
    )
    selected_metadata = [
        {
            "segment_id": segment["segment_id"],
            "source": segment["source"],
            "text_chars": segment["text_chars"],
            "text_bytes": segment["text_bytes"],
            "estimated_tokens": segment["estimated_tokens"],
        }
        for segment in selected_segments
    ]
    fields: dict[str, Any] = {
        "dry_run_enabled_candidate_built": True,
        "dry_run_enabled_reason": "candidate_request_built_for_diagnostics",
        "dry_run_enabled_is_real_execution": False,
        "dry_run_enabled_replaces_upstream_request": False,
        "dry_run_enabled_changes_client_response": False,
        "dry_run_enabled_candidate_request_sent_to_upstream": False,
        "dry_run_enabled_experimental_response_exposed": False,
        "dry_run_enabled_original_upstream_request_unchanged": True,
        "dry_run_enabled_client_response_unchanged": True,
        "dry_run_enabled_selected_segment_ids": selected_segment_ids,
        "dry_run_enabled_selected_segment_count": len(selected_segments),
        "dry_run_enabled_selected_segments_metadata": selected_metadata,
        "dry_run_enabled_full_request_estimated_tokens": rough_estimated_input_tokens,
        "dry_run_enabled_candidate_request_estimated_tokens": candidate_tokens,
        "dry_run_enabled_estimated_token_reduction_pct": reduction_pct,
        "dry_run_enabled_candidate_endpoint": path,
        "dry_run_enabled_candidate_contains_text": bool(
            _iter_text_values(candidate_request)
        ),
    }
    if config.shadow_log_full_payloads:
        fields["dry_run_enabled_candidate_request"] = candidate_request
    return fields


def _selected_segment_ids_for_dry_run(event: dict[str, Any]) -> list[str]:
    router_selected = event.get("shadow_router_candidate_selected_segment_ids")
    if isinstance(router_selected, list) and all(isinstance(item, str) for item in router_selected) and router_selected:
        return list(router_selected)
    metadata = event.get("candidate_segments_metadata")
    if not isinstance(metadata, list):
        return []
    selected = []
    for item in metadata:
        if not isinstance(item, dict) or item.get("selected") is not True:
            continue
        segment_id = item.get("segment_id")
        if isinstance(segment_id, str):
            selected.append(segment_id)
    return selected


def _last_text_segment(segments: list[dict[str, Any]]) -> str:
    for segment in reversed(segments):
        text = segment.get("text")
        if isinstance(text, str) and text:
            return text
    return ""


def _candidate_request_for_endpoint(
    path: str,
    payload: dict[str, Any] | None,
    selected_segments: list[dict[str, Any]],
    question_text: str,
) -> dict[str, Any]:
    selected_context = "\n\n".join(
        f"[{segment['segment_id']}]\n{segment['text']}" for segment in selected_segments
    )
    candidate_text = "\n\n".join(
        part
        for part in (
            "Selected context:",
            selected_context,
            "Question:",
            question_text,
        )
        if part
    )
    model = _payload_model(payload)
    if path == "/v1/responses":
        request: dict[str, Any] = {"input": candidate_text}
        if model is not None:
            request["model"] = model
        return request
    request = {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Dry-run SFE candidate request assembled from selected "
                    "segments. This request was not used for the client "
                    "response."
                ),
            },
            {"role": "user", "content": candidate_text},
        ],
        "stream": False,
    }
    if model is not None:
        request["model"] = model
    return request


def _safe_shadow_router_fields(
    config: ProxyConfig,
    event: dict[str, Any],
    path: str,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    try:
        router = create_shadow_router(config.shadow_router_provider, config=config)
        router_input = ShadowRouterInput(
            request_id=str(event["timestamp"]),
            endpoint=str(event["endpoint"]),
            model=event["model"] if isinstance(event.get("model"), str) else None,
            rough_estimated_input_tokens=int(event["rough_estimated_input_tokens"]),
            candidate_segments_metadata=list(event.get("candidate_segments_metadata") or []),
            eligibility_metadata={
                "sfe_routing_eligible": event["sfe_routing_eligible"],
                "eligibility_reason": event["eligibility_reason"],
                "eligibility_threshold_tokens": event["eligibility_threshold_tokens"],
            },
            request_body_bytes=int(event["request_body_bytes"]),
            stream=event["stream"] if isinstance(event.get("stream"), bool) else None,
            candidate_text_segments=_extract_candidate_text_segments(path, payload),
        )
        return router.analyze(router_input).to_event_fields(config.shadow_router_provider)
    except Exception as exc:  # noqa: BLE001
        return {
            "shadow_router_enabled": False,
            "shadow_router_provider": config.shadow_router_provider,
            "shadow_router_name": config.shadow_router_provider,
            "shadow_router_status": "error",
            "shadow_router_reason": "shadow_router_contract_error",
            "shadow_router_latency_ms": 0,
            "shadow_router_candidate_selected_segment_ids": [],
            "shadow_router_estimated_selected_input_tokens": None,
            "shadow_router_estimated_token_reduction_pct": None,
            "shadow_router_error_type": type(exc).__name__,
            "shadow_router_dry_run_only": True,
        }


def _safe_shadow_selection_fields(
    config: ProxyConfig,
    path: str,
    payload: dict[str, Any] | None,
    rough_estimated_input_tokens: int,
) -> dict[str, Any]:
    try:
        return _build_shadow_selection_fields(config, path, payload, rough_estimated_input_tokens)
    except Exception as exc:  # noqa: BLE001
        return {
            "shadow_selection_enabled": True,
            "would_activate_sfe_is_dry_run_only": True,
            "would_activate_sfe": False,
            "selection_strategy": "largest_text_segment_baseline",
            "selection_status": "error",
            "selection_reason": "dry_run_analysis_error",
            "selection_error_type": type(exc).__name__,
            "estimated_full_input_tokens": rough_estimated_input_tokens,
            "estimated_selected_input_tokens": None,
            "estimated_token_reduction_pct": None,
            "candidate_segment_count": 0,
            "candidate_selected_segment_count": 0,
            "candidate_segments_metadata": [],
        }


def _build_shadow_selection_fields(
    config: ProxyConfig,
    path: str,
    payload: dict[str, Any] | None,
    rough_estimated_input_tokens: int,
) -> dict[str, Any]:
    base = {
        "shadow_selection_enabled": True,
        "would_activate_sfe_is_dry_run_only": True,
        "would_activate_sfe": False,
        "selection_strategy": "largest_text_segment_baseline",
        "selection_status": "no_selection",
        "selection_reason": "rough_estimated_input_tokens_below_threshold",
        "estimated_full_input_tokens": rough_estimated_input_tokens,
        "estimated_selected_input_tokens": None,
        "estimated_token_reduction_pct": None,
        "candidate_segment_count": 0,
        "candidate_selected_segment_count": 0,
        "candidate_segments_metadata": [],
    }
    if rough_estimated_input_tokens <= config.shadow_min_input_tokens:
        return base

    segments = _extract_candidate_segments(path, payload)
    if not segments:
        base["selection_reason"] = "no_safe_text_segments"
        return base

    selected_index = max(
        range(len(segments)),
        key=lambda index: (segments[index]["estimated_tokens"], segments[index]["text_chars"]),
    )
    selected_tokens = int(segments[selected_index]["estimated_tokens"])
    reduction_pct = (
        round((1 - (selected_tokens / rough_estimated_input_tokens)) * 100, 2)
        if rough_estimated_input_tokens > 0
        else 0.0
    )
    metadata = []
    for index, segment in enumerate(segments):
        metadata.append(
            {
                "segment_id": f"segment-{index + 1}",
                "source": segment["source"],
                "text_chars": segment["text_chars"],
                "text_bytes": segment["text_bytes"],
                "estimated_tokens": segment["estimated_tokens"],
                "selected": index == selected_index,
            }
        )

    return {
        "shadow_selection_enabled": True,
        "would_activate_sfe_is_dry_run_only": True,
        "would_activate_sfe": True,
        "selection_strategy": "largest_text_segment_baseline",
        "selection_status": "candidate_selected",
        "selection_reason": "largest_text_segment_selected_for_dry_run_estimate",
        "estimated_full_input_tokens": rough_estimated_input_tokens,
        "estimated_selected_input_tokens": selected_tokens,
        "estimated_token_reduction_pct": reduction_pct,
        "candidate_segment_count": len(segments),
        "candidate_selected_segment_count": 1,
        "candidate_segments_metadata": metadata,
    }


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


def _extract_candidate_segments(
    path: str,
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if payload is None:
        return []
    if path == "/v1/chat/completions":
        return _extract_chat_candidate_segments(payload)
    if path == "/v1/responses":
        return _extract_responses_candidate_segments(payload)
    return []


def _extract_candidate_text_segments(
    path: str,
    payload: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    segments = []
    for index, segment in enumerate(_extract_candidate_segments(path, payload)):
        text = segment.get("text")
        if not isinstance(text, str) or not text:
            continue
        segments.append(
            {
                "segment_id": f"segment-{index + 1}",
                "source": segment["source"],
                "text": text,
                "text_chars": segment["text_chars"],
                "text_bytes": segment["text_bytes"],
                "estimated_tokens": segment["estimated_tokens"],
            }
        )
    return segments


def _extract_chat_candidate_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return []
    segments: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        text = _extract_text_content(content)
        if text:
            segments.append(_segment_metadata(text, f"chat_message_{index + 1}"))
    return segments


def _extract_responses_candidate_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    input_value = payload.get("input")
    if input_value is None:
        return []
    items = input_value if isinstance(input_value, list) else [input_value]
    segments: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        text = _extract_text_content(item)
        if text:
            segments.append(_segment_metadata(text, f"responses_input_{index + 1}"))
    return segments


def _extract_text_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        text_parts: list[str] = []
        for key in ("text", "content", "input_text"):
            part = value.get(key)
            if isinstance(part, str):
                text_parts.append(part)
            elif isinstance(part, list):
                text_parts.extend(_extract_text_content(child) for child in part)
        return "\n".join(part for part in text_parts if part)
    if isinstance(value, list):
        return "\n".join(part for part in (_extract_text_content(child) for child in value) if part)
    return ""


def _segment_metadata(text: str, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "text": text,
        "text_chars": len(text),
        "text_bytes": len(text.encode("utf-8")),
        "estimated_tokens": (len(text) + 3) // 4,
    }


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
