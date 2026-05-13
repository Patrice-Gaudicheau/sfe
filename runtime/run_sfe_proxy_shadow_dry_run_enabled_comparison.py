"""Compare original proxy path with a dry-run reduced candidate request."""

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
FIXTURE_ID = "tariff_policy_dry_run_enabled_comparison"
USEFUL_MARKER = "UTILITY-RATE-SCHEDULE-DELTA-17"
QUESTION_TEXT = (
    "Using the active utility tariff memo only, what battery dispatch "
    "threshold applies during the evening peak interval?"
)
NORMAL_UPSTREAM_RESPONSE = {
    "id": "normal-upstream-response",
    "object": "chat.completion",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "normal upstream response",
            },
        }
    ],
}
EXPERIMENTAL_UPSTREAM_RESPONSE = {
    "id": "experimental-reduced-candidate-response",
    "object": "chat.completion",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "experimental response hidden from client",
            },
        }
    ],
}
LIMITATION = (
    "This runner simulates an SFE-enabled request in a dry-run comparison path "
    "only. It does not replace the real upstream request, does not change the "
    "client-visible response, does not validate answer quality under reduced "
    "context, and is not production SFE-enabled execution."
)


class NormalUpstreamHandler(BaseHTTPRequestHandler):
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
        response_body = json.dumps(NORMAL_UPSTREAM_RESPONSE).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


class ExperimentalUpstreamHandler(BaseHTTPRequestHandler):
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
        response_body = json.dumps(EXPERIMENTAL_UPSTREAM_RESPONSE).encode("utf-8")
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
    normal_upstream = _start_server(NormalUpstreamHandler)
    experimental_upstream = _start_server(ExperimentalUpstreamHandler)
    lemonade = _start_server(MockLemonadeRouterHandler)

    try:
        with tempfile.TemporaryDirectory(
            prefix="sfe_proxy_shadow_dry_run_enabled_comparison_"
        ) as shadow_log_dir:
            with _temporary_env(
                {
                    "SFE_LEMONADE_BASE_URL": _server_url(lemonade),
                    "SFE_LEMONADE_MODEL": "mock-dry-run-comparison-router",
                    "SFE_LEMONADE_API_KEY": None,
                    "SFE_PROXY_PROVIDER_LIMITS_ENABLED": None,
                }
            ):
                proxy = _start_proxy(normal_upstream, shadow_log_dir, logs)
                try:
                    client_response = _request_json(
                        f"{_server_url(proxy)}/v1/chat/completions",
                        payload,
                        timeout_seconds=args.timeout_seconds,
                    )
                finally:
                    proxy.shutdown()
                    proxy.server_close()
            event = _read_shadow_event(Path(shadow_log_dir))

        reduced_request = _build_reduced_candidate_request(
            payload=payload,
            event=event,
            candidate_segments=MockLemonadeRouterHandler.observed_segments,
        )
        experimental_response = _request_json(
            f"{_server_url(experimental_upstream)}/v1/chat/completions",
            reduced_request["request"],
            timeout_seconds=args.timeout_seconds,
        )
    finally:
        normal_upstream.shutdown()
        normal_upstream.server_close()
        experimental_upstream.shutdown()
        experimental_upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    summary = _build_summary(
        payload=payload,
        client_response=client_response,
        event=event,
        reduced_request=reduced_request,
        experimental_response=experimental_response,
    )
    report = {
        "summary": summary,
        "selected_segments": reduced_request["selected_segments"],
        "reduced_candidate_request_metadata": reduced_request["metadata"],
        "normal_path_transparency": {
            "normal_upstream_received_original_request": summary[
                "normal_upstream_received_original_request"
            ],
            "client_response_came_from_normal_upstream": summary[
                "client_response_came_from_normal_upstream"
            ],
        },
        "experimental_path_verification": {
            "experimental_upstream_received_reduced_request": summary[
                "experimental_upstream_received_reduced_request"
            ],
            "experimental_response_hidden_from_client": summary[
                "experimental_response_hidden_from_client"
            ],
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
            "Run a proxy shadow scenario and send the reduced candidate request "
            "only to a mocked experimental upstream."
        )
    )
    parser.add_argument("--json", type=Path, help="Optional path for a JSON report.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="Timeout for local proxy and mocked experimental requests.",
    )
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive.")
    return args


def _reset_state() -> None:
    _reset_provider_call_state()
    NormalUpstreamHandler.records = []
    ExperimentalUpstreamHandler.records = []
    MockLemonadeRouterHandler.records = []
    MockLemonadeRouterHandler.observed_segments = []


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
        "model": "dry-run-comparison-model",
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
        "router_reason": "selected_tariff_policy_segment_for_dry_run_comparison",
        "candidate_selected_segment_ids": [selected["segment_id"]],
        "estimated_router_selected_input_tokens": selected_tokens,
        "estimated_router_token_reduction_pct": reduction_pct,
        "confidence": 0.93,
        "dry_run_only": True,
    }
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(router_output)}}]}
    ).encode("utf-8")


def _build_reduced_candidate_request(
    *,
    payload: dict[str, Any],
    event: dict[str, Any],
    candidate_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_ids = event.get("shadow_router_candidate_selected_segment_ids")
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
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
    reduced_context = "\n\n".join(
        [
            "Selected context:",
            *[
                f"[{segment['segment_id']}]\n{segment['text']}"
                for segment in selected_segments
            ],
            "Question:",
            QUESTION_TEXT,
        ]
    )
    reduced_request = {
        "model": payload.get("model"),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Dry-run SFE candidate request assembled from proxy "
                    "shadow-selected segments. This request is sent only to "
                    "the mocked experimental upstream."
                ),
            },
            {"role": "user", "content": reduced_context},
        ],
        "stream": False,
    }
    full_tokens = _estimate_tokens_from_payload(payload)
    reduced_tokens = _estimate_tokens_from_payload(reduced_request)
    reduction_pct = (
        round((1 - (reduced_tokens / full_tokens)) * 100, 2)
        if full_tokens > 0
        else 0.0
    )
    return {
        "request": reduced_request,
        "selected_segments": selected_segments,
        "text": reduced_context,
        "metadata": {
            "selected_segment_ids": selected_segment_ids,
            "full_request_estimated_tokens": full_tokens,
            "reduced_candidate_request_estimated_tokens": reduced_tokens,
            "estimated_reduction_percent": reduction_pct,
        },
    }


def _build_summary(
    *,
    payload: dict[str, Any],
    client_response: dict[str, Any],
    event: dict[str, Any],
    reduced_request: dict[str, Any],
    experimental_response: dict[str, Any],
) -> dict[str, Any]:
    selected_segment_ids = reduced_request["metadata"]["selected_segment_ids"]
    expected_segment_included = EXPECTED_SEGMENT_ID in selected_segment_ids
    exact_selection_match = selected_segment_ids == [EXPECTED_SEGMENT_ID]
    over_selected_segment_ids = [
        segment_id
        for segment_id in selected_segment_ids
        if segment_id != EXPECTED_SEGMENT_ID
    ]
    over_selected = expected_segment_included and bool(over_selected_segment_ids)

    normal_payload = _last_payload(NormalUpstreamHandler.records)
    experimental_payload = _last_payload(ExperimentalUpstreamHandler.records)
    normal_upstream_received_original = normal_payload == payload
    experimental_upstream_received_reduced = (
        experimental_payload == reduced_request["request"]
    )
    client_response_came_from_normal = (
        client_response.get("status") == 200
        and client_response.get("body") == NORMAL_UPSTREAM_RESPONSE
    )
    experimental_response_hidden = (
        client_response.get("body") != EXPERIMENTAL_UPSTREAM_RESPONSE
        and experimental_response.get("body") == EXPERIMENTAL_UPSTREAM_RESPONSE
    )
    router_metadata_usable = (
        bool(selected_segment_ids)
        and event.get("shadow_router_dry_run_only") is True
        and event.get("shadow_router_error_type") is None
    )
    reduced_text = json.dumps(reduced_request["request"], sort_keys=True)
    reduced_contains_expected = USEFUL_MARKER in reduced_text
    reduced_excludes_unselected = _reduced_excludes_unselected_segments(
        reduced_text,
        MockLemonadeRouterHandler.observed_segments,
        selected_segment_ids,
    )
    reduced_built = bool(reduced_request["selected_segments"])
    passed = (
        normal_upstream_received_original
        and client_response_came_from_normal
        and experimental_response_hidden
        and router_metadata_usable
        and expected_segment_included
        and reduced_built
        and reduced_contains_expected
        and reduced_excludes_unselected
        and experimental_upstream_received_reduced
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
        "full_request_estimated_tokens": reduced_request["metadata"][
            "full_request_estimated_tokens"
        ],
        "reduced_candidate_request_estimated_tokens": reduced_request["metadata"][
            "reduced_candidate_request_estimated_tokens"
        ],
        "estimated_reduction_percent": reduced_request["metadata"][
            "estimated_reduction_percent"
        ],
        "normal_upstream_received_original_request": (
            normal_upstream_received_original
        ),
        "experimental_upstream_received_reduced_request": (
            experimental_upstream_received_reduced
        ),
        "client_response_came_from_normal_upstream": client_response_came_from_normal,
        "experimental_response_hidden_from_client": experimental_response_hidden,
        "reduced_request_built": reduced_built,
        "reduced_request_contains_expected_segment": reduced_contains_expected,
        "reduced_request_excludes_unselected_segments": reduced_excludes_unselected,
        "router_status": event.get("shadow_router_status"),
        "router_reason": event.get("shadow_router_reason"),
        "router_error_type": event.get("shadow_router_error_type"),
        "router_metadata_usable": router_metadata_usable,
        "limitation": LIMITATION,
    }


def _reduced_excludes_unselected_segments(
    reduced_text: str,
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
        if marker and marker in reduced_text:
            return False
    return True


def _print_summary(summary: dict[str, Any]) -> None:
    print("SFE proxy shadow dry-run enabled comparison")
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
        "reduced candidate request estimated tokens: "
        f"{summary['reduced_candidate_request_estimated_tokens']}"
    )
    print(
        "estimated reduction percent: "
        f"{summary['estimated_reduction_percent']}"
    )
    print(
        "normal upstream received original request: "
        f"{summary['normal_upstream_received_original_request']}"
    )
    print(
        "experimental upstream received reduced request: "
        f"{summary['experimental_upstream_received_reduced_request']}"
    )
    print(
        "client response came from normal upstream: "
        f"{summary['client_response_came_from_normal_upstream']}"
    )
    print(
        "experimental response hidden from client: "
        f"{summary['experimental_response_hidden_from_client']}"
    )
    print(
        "reduced request contains expected segment: "
        f"{summary['reduced_request_contains_expected_segment']}"
    )
    print(
        "reduced request excludes unselected segments: "
        f"{summary['reduced_request_excludes_unselected_segments']}"
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


def _last_payload(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    body = records[-1]["body"]
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
