"""Run a controlled local smoke test for proxy mode=\"enabled\"."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe_proxy.config import ProxyConfig
from sfe_proxy.server import create_server
from sfe_proxy.shadow_router import _reset_provider_call_state


EXPECTED_SEGMENT_ID = "segment-3"
FIXTURE_ID = "tariff_policy_enabled_mode_smoke"
USEFUL_MARKER = "UTILITY-RATE-SCHEDULE-DELTA-17"
DISTRACTOR_A_MARKER = "CAFETERIA-BADGE-ROTATION-ALPHA"
DISTRACTOR_B_MARKER = "WAREHOUSE-PALLET-LABEL-BETA"
DISTRACTOR_C_MARKER = "SUPPORT-TICKET-ALIAS-GAMMA"
QUESTION_TEXT = (
    "Using the active utility tariff memo only, what battery dispatch "
    "threshold applies during the evening peak interval?"
)
UPSTREAM_RESPONSE = {
    "id": "enabled-mode-reduced-path-response",
    "object": "chat.completion",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": "response from reduced enabled request path",
            },
        }
    ],
}
LIMITATION = (
    "This runner validates proxy mode=\"enabled\" with mocked upstream and "
    "provider-neutral mocked selection only. It does not call live providers, "
    "does not validate answer quality under reduced context, and does not "
    "claim production readiness."
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


def main() -> int:
    args = _parse_args()
    _reset_state()

    payload = _build_payload()
    upstream = _start_server(RecordingUpstreamHandler)
    logs: list[str] = []

    try:
        with tempfile.TemporaryDirectory(
            prefix="sfe_proxy_enabled_mode_smoke_"
        ) as shadow_log_dir:
            proxy = _start_proxy(upstream, shadow_log_dir, logs, min_tokens=1)
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

        failure_check = _run_routing_failure_check(
            upstream=upstream,
            timeout_seconds=args.timeout_seconds,
        )
    finally:
        upstream.shutdown()
        upstream.server_close()

    summary = _build_summary(
        payload=payload,
        client_response=response,
        event=event,
        failure_check=failure_check,
    )
    report = {
        "summary": summary,
        "selected_segments": event.get("enabled_selected_segments_metadata") or [],
        "reduced_request_metadata": {
            "selected_segment_ids": summary["selected_segment_ids"],
            "full_request_estimated_tokens": summary[
                "full_request_estimated_tokens"
            ],
            "reduced_request_estimated_tokens": summary[
                "reduced_request_estimated_tokens"
            ],
            "estimated_reduction_percent": summary["estimated_reduction_percent"],
        },
        "enabled_path_verification": {
            "original_request_sent_upstream": summary[
                "original_request_sent_upstream"
            ],
            "reduced_request_sent_upstream": summary[
                "reduced_request_sent_upstream"
            ],
            "client_response_came_from_reduced_path": summary[
                "client_response_came_from_reduced_path"
            ],
        },
        "routing_failure_check": failure_check,
        "limitation": LIMITATION,
    }
    _print_summary(summary)
    if args.json is not None:
        _write_json(args.json, report)
    return 0 if summary["passed"] else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a controlled local smoke test for proxy mode=\"enabled\"."
    )
    parser.add_argument("--json", type=Path, help="Optional path for a JSON report.")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="Timeout for local proxy requests.",
    )
    args = parser.parse_args()
    if args.timeout_seconds <= 0:
        raise SystemExit("--timeout-seconds must be positive.")
    return args


def _reset_state() -> None:
    _reset_provider_call_state()
    RecordingUpstreamHandler.records = []


def _build_payload() -> dict[str, Any]:
    distractor_a = (
        "SEGMENT A - archived cafeteria operations. "
        f"{DISTRACTOR_A_MARKER} describes badge color rotation, break-room "
        "inventory, and coffee machine cleaning windows. "
    ) * 4
    distractor_b = (
        "SEGMENT B - historical logistics notes. "
        f"{DISTRACTOR_B_MARKER} covers dock assignments, pallet labels, "
        "and carrier calls. "
    ) * 4
    useful_segment = (
        "SEGMENT C - active utility tariff memo. "
        f"{USEFUL_MARKER} sets the battery dispatch threshold at 42 kilowatts "
        "during the evening peak interval. "
    ) * 9
    distractor_c = (
        "SEGMENT D - unrelated customer support transcript. "
        f"{DISTRACTOR_C_MARKER} discusses login retries, email aliases, and "
        "ticket tags. "
    ) * 4
    return {
        "model": "enabled-mode-smoke-model",
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


def _run_routing_failure_check(
    *,
    upstream: ThreadingHTTPServer,
    timeout_seconds: int,
) -> dict[str, Any]:
    records_before = len(RecordingUpstreamHandler.records)
    short_payload = {
        "model": "enabled-mode-smoke-model",
        "messages": [{"role": "user", "content": "short request"}],
        "stream": False,
    }
    with tempfile.TemporaryDirectory(
        prefix="sfe_proxy_enabled_mode_smoke_failure_"
    ) as shadow_log_dir:
        proxy = _start_proxy(
            upstream,
            shadow_log_dir,
            logs=[],
            min_tokens=50000,
        )
        try:
            response = _request_json(
                f"{_server_url(proxy)}/v1/chat/completions",
                short_payload,
                timeout_seconds=timeout_seconds,
            )
        finally:
            proxy.shutdown()
            proxy.server_close()
        event = _read_shadow_event(Path(shadow_log_dir))

    upstream_request_count_unchanged = (
        len(RecordingUpstreamHandler.records) == records_before
    )
    passed = (
        response["status"] == 422
        and response["body"].get("error", {}).get("type")
        == "sfe_enabled_routing_error"
        and upstream_request_count_unchanged
        and event.get("enabled_request_sent") is False
        and event.get("enabled_original_request_sent") is False
    )
    return {
        "passed": passed,
        "status": response["status"],
        "error_type": response["body"].get("error", {}).get("type"),
        "error_reason": response["body"].get("error", {}).get("reason"),
        "upstream_request_count_unchanged": upstream_request_count_unchanged,
        "enabled_request_sent": event.get("enabled_request_sent"),
        "enabled_original_request_sent": event.get("enabled_original_request_sent"),
        "enabled_candidate_request_sent_to_upstream": event.get(
            "enabled_candidate_request_sent_to_upstream"
        ),
    }


def _build_summary(
    *,
    payload: dict[str, Any],
    client_response: dict[str, Any],
    event: dict[str, Any],
    failure_check: dict[str, Any],
) -> dict[str, Any]:
    upstream_payload = _last_payload(RecordingUpstreamHandler.records)
    upstream_text = json.dumps(upstream_payload, sort_keys=True) if upstream_payload else ""
    selected_ids = event.get("enabled_selected_segment_ids")
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
    expected_segment_included = EXPECTED_SEGMENT_ID in selected_segment_ids
    exact_selection_match = selected_segment_ids == [EXPECTED_SEGMENT_ID]
    over_selected_segment_ids = [
        segment_id
        for segment_id in selected_segment_ids
        if segment_id != EXPECTED_SEGMENT_ID
    ]
    over_selected = expected_segment_included and bool(over_selected_segment_ids)
    original_request_sent_upstream = upstream_payload == payload
    reduced_request_sent_upstream = (
        upstream_payload is not None
        and upstream_payload != payload
        and event.get("enabled_request_sent") is True
        and event.get("enabled_candidate_request_sent_to_upstream") is True
    )
    client_response_came_from_reduced_path = (
        client_response.get("status") == 200
        and client_response.get("body") == UPSTREAM_RESPONSE
    )
    reduced_contains_expected = USEFUL_MARKER in upstream_text
    reduced_contains_question = QUESTION_TEXT in upstream_text
    reduced_excludes_unselected = all(
        marker not in upstream_text
        for marker in (
            DISTRACTOR_A_MARKER,
            DISTRACTOR_B_MARKER,
            DISTRACTOR_C_MARKER,
        )
    )
    full_tokens = event.get("enabled_full_request_estimated_tokens")
    reduced_tokens = event.get("enabled_candidate_request_estimated_tokens")
    reduction_pct = event.get("enabled_estimated_token_reduction_pct")
    diagnostics_usable = (
        event.get("mode") == "enabled"
        and event.get("enabled_candidate_built") is True
        and selected_segment_ids
        and isinstance(full_tokens, int)
        and isinstance(reduced_tokens, int)
        and isinstance(reduction_pct, (int, float))
        and event.get("enabled_original_request_sent") is False
    )
    passed = (
        diagnostics_usable
        and expected_segment_included
        and not original_request_sent_upstream
        and reduced_request_sent_upstream
        and client_response_came_from_reduced_path
        and reduced_contains_expected
        and reduced_contains_question
        and reduced_excludes_unselected
        and failure_check["passed"]
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
        "original_request_sent_upstream": original_request_sent_upstream,
        "reduced_request_sent_upstream": reduced_request_sent_upstream,
        "client_response_came_from_reduced_path": (
            client_response_came_from_reduced_path
        ),
        "reduced_request_contains_expected_segment": reduced_contains_expected,
        "reduced_request_preserves_question": reduced_contains_question,
        "reduced_request_excludes_unselected_segments": reduced_excludes_unselected,
        "full_request_estimated_tokens": full_tokens,
        "reduced_request_estimated_tokens": reduced_tokens,
        "estimated_reduction_percent": reduction_pct,
        "enabled_candidate_built": event.get("enabled_candidate_built"),
        "enabled_request_sent": event.get("enabled_request_sent"),
        "enabled_original_request_sent": event.get("enabled_original_request_sent"),
        "routing_failure_returns_422": failure_check["passed"],
        "routing_failure_status": failure_check["status"],
        "limitation": LIMITATION,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print("SFE proxy enabled mode smoke")
    print(LIMITATION)
    print(f"status: {summary['status']}")
    print(f"fixture id: {summary['fixture_id']}")
    print(f"expected segment ID: {summary['expected_segment_id']}")
    print(f"selected segment IDs: {summary['selected_segment_ids']}")
    print(
        "original request sent upstream: "
        f"{summary['original_request_sent_upstream']}"
    )
    print(
        "reduced request sent upstream: "
        f"{summary['reduced_request_sent_upstream']}"
    )
    print(
        "client response came from reduced path: "
        f"{summary['client_response_came_from_reduced_path']}"
    )
    print(
        "reduced request contains expected segment: "
        f"{summary['reduced_request_contains_expected_segment']}"
    )
    print(
        "reduced request excludes unselected segments: "
        f"{summary['reduced_request_excludes_unselected_segments']}"
    )
    print(
        "full request estimated tokens: "
        f"{summary['full_request_estimated_tokens']}"
    )
    print(
        "reduced request estimated tokens: "
        f"{summary['reduced_request_estimated_tokens']}"
    )
    print(
        "estimated reduction percent: "
        f"{summary['estimated_reduction_percent']}"
    )
    print(
        "routing failure returns 422: "
        f"{summary['routing_failure_returns_422']}"
    )


def _write_json(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _start_proxy(
    upstream: ThreadingHTTPServer,
    shadow_log_dir: str,
    logs: list[str],
    *,
    min_tokens: int,
) -> ThreadingHTTPServer:
    host, port = upstream.server_address
    proxy = create_server(
        ProxyConfig(
            host="127.0.0.1",
            port=_free_port(),
            upstream_base_url=f"http://{host}:{port}",
            upstream_api_key="upstream-secret",
            mode="enabled",
            shadow_log_dir=shadow_log_dir,
            shadow_log_full_payloads=True,
            shadow_min_input_tokens=min_tokens,
            shadow_selection_dry_run=True,
            shadow_router_dry_run=False,
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
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return {
                "status": response.status,
                "body": json.loads(response.read().decode("utf-8")),
            }
    except urllib.error.HTTPError as exc:
        return {
            "status": exc.code,
            "body": json.loads(exc.read().decode("utf-8")),
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


def _start_server(handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _server_url(server: ThreadingHTTPServer) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


if __name__ == "__main__":
    raise SystemExit(main())
