"""Run one local SFE proxy shadow multi-segment smoke scenario."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe_proxy.config import ProxyConfig
from sfe_proxy.server import create_server
from sfe_proxy.shadow_router import _reset_provider_call_state


EXPECTED_SEGMENT_ID = "segment-3"
UPSTREAM_RESPONSE = {
    "id": "multisegment-smoke",
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


class MockLemonadeRouterHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    records: list[dict[str, Any]] = []
    observed_segments: list[dict[str, Any]] = []

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
        response_body = _mock_lemonade_response(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def main() -> int:
    args = _parse_args()
    _reset_provider_call_state()
    RecordingUpstreamHandler.records = []
    MockLemonadeRouterHandler.records = []
    MockLemonadeRouterHandler.observed_segments = []

    payload = _build_payload()
    logs: list[str] = []
    upstream = _start_server(RecordingUpstreamHandler)
    lemonade = _start_server(MockLemonadeRouterHandler)

    with tempfile.TemporaryDirectory(prefix="sfe_proxy_shadow_smoke_") as shadow_log_dir:
        with _temporary_env(
            {
                "SFE_LEMONADE_BASE_URL": _server_url(lemonade),
                "SFE_LEMONADE_MODEL": "local-router",
                "SFE_LEMONADE_API_KEY": None,
                "SFE_PROXY_PROVIDER_LIMITS_ENABLED": None,
            }
        ):
            proxy = _start_proxy(upstream, shadow_log_dir, logs)
            try:
                response = _request_json(
                    f"{_server_url(proxy)}/v1/chat/completions",
                    payload,
                )
            finally:
                proxy.shutdown()
                proxy.server_close()

        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

        event = _read_shadow_event(Path(shadow_log_dir))

    summary = _build_summary(payload, response, event)
    _print_summary(summary)
    if args.jsonl is not None:
        _write_jsonl(args.jsonl, summary)
    return 0 if summary["passed"] else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one local proxy shadow multi-segment smoke scenario."
    )
    parser.add_argument(
        "--jsonl",
        type=Path,
        help="Optional path for one JSONL summary record.",
    )
    return parser.parse_args()


def _build_payload() -> dict[str, Any]:
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


def _mock_lemonade_response(body: bytes) -> bytes:
    lemonade_payload = json.loads(body.decode("utf-8"))
    router_prompt = json.loads(lemonade_payload["messages"][1]["content"])
    segments = router_prompt["candidate_segments"]
    MockLemonadeRouterHandler.observed_segments = segments
    selected = next(
        segment
        for segment in segments
        if "UTILITY-RATE-SCHEDULE-DELTA-17" in segment["text"]
    )
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
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(router_output)}}]}
    ).encode("utf-8")


def _build_summary(
    payload: dict[str, Any],
    response: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    upstream_payload = _last_upstream_payload()
    selected_ids = event.get("shadow_router_candidate_selected_segment_ids")
    router_metadata_usable = (
        event.get("shadow_router_status") == "candidate_selected"
        and isinstance(selected_ids, list)
        and bool(selected_ids)
        and event.get("shadow_router_dry_run_only") is True
    )
    selection_matched = selected_ids == [EXPECTED_SEGMENT_ID]
    upstream_request_unchanged = upstream_payload == payload
    client_response_unchanged = (
        response.get("status") == 200 and response.get("body") == UPSTREAM_RESPONSE
    )
    observed_segment_ids = [
        segment.get("segment_id")
        for segment in MockLemonadeRouterHandler.observed_segments
    ]
    passed = (
        router_metadata_usable
        and selection_matched
        and upstream_request_unchanged
        and client_response_unchanged
    )
    return {
        "passed": passed,
        "selected_segment_ids": selected_ids if isinstance(selected_ids, list) else [],
        "expected_segment_id": EXPECTED_SEGMENT_ID,
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
        "router_metadata_usable": router_metadata_usable,
        "router_dry_run_only": event.get("shadow_router_dry_run_only"),
        "upstream_request_unchanged": upstream_request_unchanged,
        "client_response_unchanged": client_response_unchanged,
        "candidate_segment_count": event.get("candidate_segment_count"),
        "observed_router_segment_ids": observed_segment_ids,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print("SFE proxy shadow multi-segment smoke")
    print(f"status: {'pass' if summary['passed'] else 'fail'}")
    print(f"selected segment IDs: {summary['selected_segment_ids']}")
    print(f"expected segment ID: {summary['expected_segment_id']}")
    print(f"selection matched: {summary['selection_matched']}")
    print(f"estimated selected tokens: {summary['estimated_selected_tokens']}")
    print(f"estimated token reduction pct: {summary['estimated_token_reduction_pct']}")
    print(f"router status: {summary['router_status']}")
    print(f"router reason: {summary['router_reason']}")
    print(f"router error type: {summary['router_error_type']}")
    print(f"router metadata usable: {summary['router_metadata_usable']}")
    print(f"upstream request unchanged: {summary['upstream_request_unchanged']}")
    print(f"client response unchanged: {summary['client_response_unchanged']}")


def _write_jsonl(path: Path, summary: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(summary, sort_keys=True) + "\n")


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


def _request_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
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
    with urllib.request.urlopen(request, timeout=5) as response:
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
