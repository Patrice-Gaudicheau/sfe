"""Build and inspect a reduced candidate context from proxy shadow routing."""

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
from sfe_proxy.shadow_router import DEFAULT_LEMONADE_ROUTER_BASE_URL
from sfe_proxy.shadow_router import _reset_provider_call_state


EXPECTED_SEGMENT_ID = "segment-3"
FIXTURE_ID = "tariff_policy_candidate_context"
USEFUL_MARKER = "UTILITY-RATE-SCHEDULE-DELTA-17"
QUESTION_TEXT = (
    "Using the active utility tariff memo only, what battery dispatch "
    "threshold applies during the evening peak interval?"
)
UPSTREAM_RESPONSE = {
    "id": "candidate-context-smoke",
    "object": "chat.completion",
    "choices": [],
}
LIMITATION = (
    "This runner builds and validates a candidate reduced context in shadow "
    "only. It does not send the reduced request to upstream, does not change "
    "the client response, does not validate answer quality under reduced "
    "context, and is not SFE-enabled execution."
)


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
    _reset_state()

    payload = _build_payload()
    logs: list[str] = []
    upstream = _start_server(RecordingUpstreamHandler)
    lemonade = None if args.live_lemonade else _start_server(MockLemonadeRouterHandler)

    try:
        with tempfile.TemporaryDirectory(
            prefix="sfe_proxy_shadow_candidate_context_"
        ) as shadow_log_dir:
            with _temporary_env(_router_env(args, lemonade)):
                proxy = _start_proxy(upstream, shadow_log_dir, logs)
                try:
                    response = _request_json(
                        f"{_server_url(proxy)}/v1/chat/completions",
                        payload,
                        timeout_seconds=args.timeout_seconds,
                    )
                finally:
                    proxy.shutdown()
                    proxy.server_close()
            event = _read_shadow_event(Path(shadow_log_dir))
    finally:
        upstream.shutdown()
        upstream.server_close()
        if lemonade is not None:
            lemonade.shutdown()
            lemonade.server_close()

    summary = _build_summary(payload, response, event)
    report = {
        "summary": summary,
        "selected_segments": summary["candidate_context"]["selected_segments"],
        "candidate_context_metadata": summary["candidate_context"]["metadata"],
        "transparency": {
            "upstream_request_unchanged": summary["upstream_request_unchanged"],
            "client_response_unchanged": summary["client_response_unchanged"],
        },
        "limitation": LIMITATION,
    }
    _print_summary(summary)
    if args.json is not None:
        _write_json(args.json, report)
    return 0 if summary["passed"] else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a proxy shadow scenario and build the reduced candidate "
            "context that selected segments would produce."
        )
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Optional path for a JSON report.",
    )
    parser.add_argument(
        "--live-lemonade",
        action="store_true",
        help=(
            "Use the configured live Lemonade-compatible router endpoint. "
            "The default uses a local mocked Lemonade-compatible router."
        ),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="Timeout for the local proxy request.",
    )
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive.")
    return args


def _reset_state() -> None:
    _reset_provider_call_state()
    RecordingUpstreamHandler.records = []
    MockLemonadeRouterHandler.records = []
    MockLemonadeRouterHandler.observed_segments = []


def _router_env(
    args: argparse.Namespace,
    lemonade: ThreadingHTTPServer | None,
) -> dict[str, str | None]:
    if args.live_lemonade:
        return {
            "SFE_LEMONADE_BASE_URL": os.getenv(
                "SFE_LEMONADE_BASE_URL", DEFAULT_LEMONADE_ROUTER_BASE_URL
            ),
            "SFE_LEMONADE_MODEL": os.getenv("SFE_ROUTER_MODEL", ""),
            "SFE_PROXY_PROVIDER_LIMITS_ENABLED": None,
        }
    if lemonade is None:
        raise RuntimeError("mock Lemonade server was not started")
    return {
        "SFE_LEMONADE_BASE_URL": _server_url(lemonade),
        "SFE_LEMONADE_MODEL": "mock-candidate-context-router",
        "SFE_LEMONADE_API_KEY": None,
        "SFE_PROXY_PROVIDER_LIMITS_ENABLED": None,
    }


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
    return {
        "model": "candidate-context-model",
        "messages": [
            {"role": "system", "content": "Answer from the supplied segments."},
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": useful_segment},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": distractor_c},
            {"role": "user", "content": QUESTION_TEXT},
        ],
        "stream": False,
    }


def _mock_lemonade_response(body: bytes) -> bytes:
    lemonade_payload = json.loads(body.decode("utf-8"))
    router_prompt = json.loads(lemonade_payload["messages"][1]["content"])
    segments = router_prompt["candidate_segments"]
    MockLemonadeRouterHandler.observed_segments = segments
    selected = next(segment for segment in segments if USEFUL_MARKER in segment["text"])
    selected_tokens = int(selected["estimated_tokens"])
    full_tokens = int(router_prompt["rough_estimated_input_tokens"])
    reduction_pct = round((1 - (selected_tokens / full_tokens)) * 100, 2)
    router_output = {
        "router_status": "candidate_selected",
        "router_reason": "selected_tariff_policy_segment_for_candidate_context",
        "candidate_selected_segment_ids": [selected["segment_id"]],
        "estimated_router_selected_input_tokens": selected_tokens,
        "estimated_router_token_reduction_pct": reduction_pct,
        "confidence": 0.92,
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
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
    candidate_segments = _candidate_segments(event)
    candidate_context = _build_candidate_context(
        payload=payload,
        selected_segment_ids=selected_segment_ids,
        candidate_segments=candidate_segments,
    )

    router_metadata_usable = (
        bool(selected_segment_ids)
        and event.get("shadow_router_dry_run_only") is True
        and event.get("shadow_router_error_type") is None
    )
    expected_segment_included = EXPECTED_SEGMENT_ID in selected_segment_ids
    exact_selection_match = selected_segment_ids == [EXPECTED_SEGMENT_ID]
    over_selected_segment_ids = [
        segment_id
        for segment_id in selected_segment_ids
        if segment_id != EXPECTED_SEGMENT_ID
    ]
    over_selected = expected_segment_included and bool(over_selected_segment_ids)
    upstream_request_unchanged = upstream_payload == payload
    client_response_unchanged = (
        response.get("status") == 200 and response.get("body") == UPSTREAM_RESPONSE
    )
    candidate_contains_expected = USEFUL_MARKER in candidate_context["text"]
    candidate_excludes_unselected = _candidate_excludes_unselected_segments(
        candidate_context["text"],
        candidate_segments,
        selected_segment_ids,
    )
    candidate_context_built = bool(candidate_context["selected_segments"])
    passed = (
        upstream_request_unchanged
        and client_response_unchanged
        and router_metadata_usable
        and expected_segment_included
        and candidate_context_built
        and candidate_contains_expected
        and candidate_excludes_unselected
    )
    return {
        "status": "pass" if passed else "fail",
        "passed": passed,
        "fixture_id": FIXTURE_ID,
        "expected_segment_id": EXPECTED_SEGMENT_ID,
        "selected_segment_ids": selected_segment_ids,
        "expected_segment_included": expected_segment_included,
        "exact_selection_match": exact_selection_match,
        "over_selected": over_selected,
        "over_selected_segment_ids": over_selected_segment_ids,
        "full_request_estimated_tokens": event.get("rough_estimated_input_tokens"),
        "candidate_context_estimated_tokens": candidate_context["metadata"][
            "estimated_tokens"
        ],
        "estimated_reduction_percent": candidate_context["metadata"][
            "estimated_reduction_percent"
        ],
        "upstream_request_unchanged": upstream_request_unchanged,
        "client_response_unchanged": client_response_unchanged,
        "router_status": event.get("shadow_router_status"),
        "router_reason": event.get("shadow_router_reason"),
        "router_error_type": event.get("shadow_router_error_type"),
        "router_metadata_usable": router_metadata_usable,
        "candidate_context_built": candidate_context_built,
        "candidate_contains_expected_segment": candidate_contains_expected,
        "candidate_excludes_unselected_segments": candidate_excludes_unselected,
        "candidate_context": candidate_context,
        "limitation": LIMITATION,
    }


def _candidate_segments(event: dict[str, Any]) -> list[dict[str, Any]]:
    if MockLemonadeRouterHandler.observed_segments:
        return MockLemonadeRouterHandler.observed_segments
    metadata = event.get("candidate_segments_metadata")
    if not isinstance(metadata, list):
        return []
    return [
        {
            "segment_id": item.get("segment_id"),
            "source": item.get("source"),
            "text": "",
            "estimated_tokens": item.get("estimated_tokens"),
        }
        for item in metadata
        if isinstance(item, dict)
    ]


def _build_candidate_context(
    *,
    payload: dict[str, Any],
    selected_segment_ids: list[str],
    candidate_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    segment_by_id = {
        segment["segment_id"]: segment
        for segment in candidate_segments
        if isinstance(segment.get("segment_id"), str)
    }
    selected_segments = [
        {
            "segment_id": segment_id,
            "source": segment_by_id[segment_id].get("source"),
            "estimated_tokens": segment_by_id[segment_id].get("estimated_tokens"),
            "text": segment_by_id[segment_id].get("text", ""),
        }
        for segment_id in selected_segment_ids
        if segment_id in segment_by_id
    ]
    question = _question_text(payload)
    text = "\n\n".join(
        [
            "Selected context:",
            *[
                f"[{segment['segment_id']}]\n{segment['text']}"
                for segment in selected_segments
            ],
            "Question:",
            question,
        ]
    )
    full_tokens = _estimate_tokens_from_payload(payload)
    candidate_tokens = _estimate_tokens(text)
    reduction_pct = (
        round((1 - (candidate_tokens / full_tokens)) * 100, 2)
        if full_tokens > 0
        else 0.0
    )
    return {
        "messages": [
            {
                "role": "system",
                "content": (
                    "Candidate context assembled from proxy shadow-selected "
                    "segments. This request was not sent upstream."
                ),
            },
            {"role": "user", "content": text},
        ],
        "selected_segments": selected_segments,
        "question": question,
        "text": text,
        "metadata": {
            "selected_segment_ids": selected_segment_ids,
            "estimated_tokens": candidate_tokens,
            "full_request_estimated_tokens": full_tokens,
            "estimated_reduction_percent": reduction_pct,
        },
    }


def _question_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in reversed(messages):
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and content:
            return content
    return ""


def _candidate_excludes_unselected_segments(
    candidate_text: str,
    candidate_segments: list[dict[str, Any]],
    selected_segment_ids: list[str],
) -> bool:
    selected = set(selected_segment_ids)
    for segment in candidate_segments:
        segment_id = segment.get("segment_id")
        text = segment.get("text")
        if not isinstance(segment_id, str) or not isinstance(text, str) or not text:
            continue
        if segment_id in selected or text == QUESTION_TEXT:
            continue
        marker = text[: min(len(text), 80)]
        if marker and marker in candidate_text:
            return False
    return True


def _print_summary(summary: dict[str, Any]) -> None:
    print("SFE proxy shadow candidate context runner")
    print(LIMITATION)
    print(f"status: {summary['status']}")
    print(f"fixture id: {summary['fixture_id']}")
    print(f"expected segment ID: {summary['expected_segment_id']}")
    print(f"selected segment IDs: {summary['selected_segment_ids']}")
    print(f"expected segment included: {summary['expected_segment_included']}")
    print(f"exact selection match: {summary['exact_selection_match']}")
    print(f"over-selected: {summary['over_selected']}")
    print(f"over-selected segment IDs: {summary['over_selected_segment_ids']}")
    print(
        "full request estimated tokens: "
        f"{summary['full_request_estimated_tokens']}"
    )
    print(
        "candidate context estimated tokens: "
        f"{summary['candidate_context_estimated_tokens']}"
    )
    print(
        "estimated reduction percent: "
        f"{summary['estimated_reduction_percent']}"
    )
    print(f"upstream request unchanged: {summary['upstream_request_unchanged']}")
    print(f"client response unchanged: {summary['client_response_unchanged']}")
    print(
        "candidate contains expected segment: "
        f"{summary['candidate_contains_expected_segment']}"
    )
    print(
        "candidate excludes unselected segments: "
        f"{summary['candidate_excludes_unselected_segments']}"
    )
    print(f"router status: {summary['router_status']}")
    print(f"router reason: {summary['router_reason']}")
    print(f"router error type: {summary['router_error_type']}")


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


def _estimate_tokens_from_payload(payload: dict[str, Any]) -> int:
    return _estimate_tokens(json.dumps(payload, sort_keys=True))


def _estimate_tokens(text: str) -> int:
    return (len(text) + 3) // 4


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
