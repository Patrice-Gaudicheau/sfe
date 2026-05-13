"""Run one local proxy shadow smoke using a live Lemonade router endpoint."""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe_proxy.config import ProxyConfig
from sfe_proxy.shadow_router import DEFAULT_LEMONADE_ROUTER_BASE_URL
from sfe_proxy.server import create_server
from sfe_proxy.shadow_router import _reset_provider_call_state


EXPECTED_SEGMENT_ID = "segment-3"
DEFAULT_LIVE_TIMEOUT_SECONDS = 180
LIVE_TIMEOUT_ENV = "SFE_PROXY_SHADOW_LIVE_TIMEOUT_SECONDS"
UPSTREAM_RESPONSE = {
    "id": "live-lemonade-shadow-smoke",
    "object": "chat.completion",
    "choices": [],
}


class RecordingUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    records: list[dict[str, Any]] = []

    def do_POST(self) -> None:
        body = _read_request_body(self)
        self.__class__.records.append(
            {
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers.items()),
                "body": body,
            }
        )
        response_body = json.dumps(UPSTREAM_RESPONSE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def main() -> int:
    _reset_provider_call_state()
    RecordingUpstreamHandler.records = []
    payload = _build_payload()
    base_url = _lemonade_base_url()
    router_model = _router_model()
    timeout_seconds = _live_timeout_seconds()

    if not router_model:
        summary = _missing_model_summary(base_url, timeout_seconds)
        _print_summary(summary)
        return 1

    upstream = _start_server(RecordingUpstreamHandler)
    logs: list[str] = []
    response: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    request_error: BaseException | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="sfe_proxy_shadow_live_lemonade_") as shadow_log_dir:
            with _temporary_env(
                {
                    "SFE_LEMONADE_BASE_URL": base_url,
                    "SFE_LEMONADE_MODEL": router_model,
                    "SFE_PROXY_PROVIDER_LIMITS_ENABLED": None,
                }
            ):
                proxy = _start_proxy(upstream, shadow_log_dir, logs)
                try:
                    response = _request_json(
                        f"{_server_url(proxy)}/v1/chat/completions",
                        payload,
                        timeout_seconds=timeout_seconds,
                    )
                except TimeoutError as exc:
                    request_error = exc
                except (urllib.error.URLError, OSError) as exc:
                    request_error = exc
                finally:
                    proxy.shutdown()
                    proxy.server_close()
            event = _read_shadow_event_if_present(Path(shadow_log_dir))
    finally:
        upstream.shutdown()
        upstream.server_close()

    summary = _build_summary(
        payload,
        response,
        event,
        base_url,
        router_model,
        timeout_seconds,
        request_error,
    )
    _print_summary(summary)
    return 0 if summary["passed"] else 1


def _lemonade_base_url() -> str:
    return os.getenv("SFE_LEMONADE_BASE_URL") or DEFAULT_LEMONADE_ROUTER_BASE_URL


def _router_model() -> str:
    return (
        os.getenv("SFE_LEMONADE_ROUTER_MODEL")
        or os.getenv("SFE_LEMONADE_MODEL")
        or os.getenv("SFE_ROUTER_MODEL")
        or ""
    )


def _live_timeout_seconds() -> int:
    raw = os.getenv(LIVE_TIMEOUT_ENV, str(DEFAULT_LIVE_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{LIVE_TIMEOUT_ENV} must be an integer.") from exc
    if value <= 0:
        raise SystemExit(f"{LIVE_TIMEOUT_ENV} must be positive.")
    return value


def _missing_model_summary(base_url: str, timeout_seconds: int) -> dict[str, Any]:
    return {
        "passed": False,
        "status": "configuration_error",
        "timeout_seconds": timeout_seconds,
        "lemonade_base_url": base_url,
        "router_model": "",
        "expected_segment_id": EXPECTED_SEGMENT_ID,
        "selected_segment_ids": [],
        "selection_matched": False,
        "estimated_selected_tokens": None,
        "estimated_token_reduction_pct": None,
        "router_status": "not_run",
        "router_reason": "missing_router_model_env",
        "router_error_type": "MissingModel",
        "router_metadata_usable": False,
        "upstream_request_unchanged": False,
        "client_response_unchanged": False,
    }


def _build_payload() -> dict[str, Any]:
    distractor_a = (
        "SEGMENT A - archived cafeteria operations. "
        "Badge rotations, snack inventory, and cleaning windows are historical notes. "
    ) * 8
    distractor_b = (
        "SEGMENT B - historical logistics notes. "
        "Dock assignments, pallet labels, and carrier calls are not tariff policy. "
    ) * 8
    useful_segment = (
        "SEGMENT C - active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the battery dispatch threshold at "
        "42 kilowatts during the evening peak interval. "
    ) * 5
    distractor_c = (
        "SEGMENT D - unrelated support transcript. "
        "Login retries, email aliases, and ticket tags do not answer tariff questions. "
    ) * 8
    question = (
        "Using the active utility tariff memo only, what battery dispatch "
        "threshold applies during the evening peak interval?"
    )
    return {
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


def _build_summary(
    payload: dict[str, Any],
    response: dict[str, Any] | None,
    event: dict[str, Any] | None,
    base_url: str,
    router_model: str,
    timeout_seconds: int,
    request_error: BaseException | None,
) -> dict[str, Any]:
    event = event or {}
    selected_ids = event.get("shadow_router_candidate_selected_segment_ids")
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
    upstream_payload = _last_upstream_payload()
    router_metadata_usable = (
        bool(selected_segment_ids)
        and event.get("shadow_router_dry_run_only") is True
        and event.get("shadow_router_error_type") is None
    )
    selection_matched = selected_segment_ids == [EXPECTED_SEGMENT_ID]
    upstream_request_unchanged = None if upstream_payload is None else upstream_payload == payload
    client_response_unchanged = (
        None
        if response is None
        else response.get("status") == 200 and response.get("body") == UPSTREAM_RESPONSE
    )
    passed = (
        router_metadata_usable
        and selection_matched
        and upstream_request_unchanged is True
        and client_response_unchanged is True
    )
    status = "pass" if passed else "fail"
    if isinstance(request_error, TimeoutError) or event.get("shadow_router_reason") == "lemonade_router_timeout":
        status = "timeout"
    elif request_error is not None:
        status = "request_error"
    return {
        "passed": passed,
        "status": status,
        "timeout_seconds": timeout_seconds,
        "lemonade_base_url": base_url,
        "router_model": router_model,
        "expected_segment_id": EXPECTED_SEGMENT_ID,
        "selected_segment_ids": selected_segment_ids,
        "selection_matched": selection_matched,
        "estimated_selected_tokens": event.get(
            "shadow_router_estimated_selected_input_tokens"
        ),
        "estimated_token_reduction_pct": event.get(
            "shadow_router_estimated_token_reduction_pct"
        ),
        "router_status": event.get("shadow_router_status"),
        "router_reason": event.get("shadow_router_reason"),
        "router_error_type": event.get("shadow_router_error_type"),
        "request_error_type": type(request_error).__name__ if request_error else None,
        "request_error": str(request_error) if request_error else None,
        "router_metadata_usable": router_metadata_usable,
        "router_dry_run_only": event.get("shadow_router_dry_run_only"),
        "upstream_request_unchanged": upstream_request_unchanged,
        "client_response_unchanged": client_response_unchanged,
        "candidate_segment_count": event.get("candidate_segment_count"),
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print("SFE proxy shadow live Lemonade runner")
    print("scope: live local Lemonade router in proxy shadow dry-run mode")
    print(f"status: {summary['status']}")
    print(f"timeout seconds: {summary['timeout_seconds']}")
    print(f"lemonade base URL: {summary['lemonade_base_url']}")
    print(f"router model: {summary['router_model']}")
    print(f"selected segment IDs: {summary['selected_segment_ids']}")
    print(f"expected segment ID: {summary['expected_segment_id']}")
    print(f"selection matched: {summary['selection_matched']}")
    print(f"estimated selected tokens: {summary['estimated_selected_tokens']}")
    print(f"estimated token reduction pct: {summary['estimated_token_reduction_pct']}")
    print(f"router status: {summary['router_status']}")
    print(f"router reason: {summary['router_reason']}")
    print(f"router error type: {summary['router_error_type']}")
    print(f"request error type: {summary.get('request_error_type')}")
    print(f"request error: {summary.get('request_error')}")
    print(f"router metadata usable: {summary['router_metadata_usable']}")
    print(f"upstream request unchanged: {summary['upstream_request_unchanged']}")
    print(f"client response unchanged: {summary['client_response_unchanged']}")


def _start_server(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _start_proxy(
    upstream: ThreadingHTTPServer,
    shadow_log_dir: str,
    logs: list[str],
) -> ThreadingHTTPServer:
    host, port = upstream.server_address
    proxy = create_server(
        ProxyConfig(
            host="127.0.0.1",
            port=_free_port(),
            upstream_base_url=f"http://{host}:{port}",
            upstream_api_key="upstream-secret",
            mode="shadow",
            shadow_log_dir=shadow_log_dir,
            shadow_min_input_tokens=1,
            shadow_selection_dry_run=True,
            shadow_router_dry_run=True,
            shadow_router_provider="lemonade",
        ),
        log_sink=logs.append,
    )
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    return proxy


def _request_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": "Bearer placeholder-client-token",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return {
            "status": response.status,
            "body": json.loads(response.read().decode("utf-8")),
        }


def _last_upstream_payload() -> dict[str, Any] | None:
    if not RecordingUpstreamHandler.records:
        return None
    body = RecordingUpstreamHandler.records[-1]["body"]
    return json.loads(body.decode("utf-8"))


def _read_shadow_event(log_dir: Path) -> dict[str, Any]:
    lines = (log_dir / "shadow_events.jsonl").read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise RuntimeError(f"expected exactly one shadow event, found {len(lines)}")
    return json.loads(lines[0])


def _read_shadow_event_if_present(log_dir: Path) -> dict[str, Any] | None:
    path = log_dir / "shadow_events.jsonl"
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return None
    return json.loads(lines[-1])


def _read_request_body(handler: BaseHTTPRequestHandler) -> bytes:
    length = int(handler.headers.get("Content-Length") or "0")
    return handler.rfile.read(length) if length else b""


def _server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextmanager
def _temporary_env(values: dict[str, str | None]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    raise SystemExit(main())
