"""Run a deterministic local proxy shadow mini benchmark with mocked routing."""

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
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe_proxy.config import ProxyConfig
from sfe_proxy.server import create_server
from sfe_proxy.shadow_router import _reset_provider_call_state


LIMITATION = (
    "Deterministic local proxy shadow mini benchmark using mocked router behavior; "
    "not a live model quality benchmark."
)


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    payload: dict[str, Any]
    upstream_response: dict[str, Any]
    expected_segment_id: str
    useful_marker: str


class RecordingUpstreamHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    records: list[dict[str, Any]] = []
    response_body: dict[str, Any] = {}

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
        response_body = json.dumps(self.__class__.response_body).encode("utf-8")
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
    useful_marker = ""

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
        response_body = _mock_lemonade_response(body, self.__class__.useful_marker)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def main() -> int:
    args = _parse_args()
    records = [_run_fixture(fixture) for fixture in _fixtures()]
    aggregate = _aggregate(records)
    report = {
        "fixtures": records,
        "aggregate": aggregate,
        "limitation": LIMITATION,
    }
    _print_report(records, aggregate)
    if args.json is not None:
        _write_json(args.json, report)
    return 0 if aggregate["failed_fixtures"] == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic local proxy shadow mini benchmark."
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Optional path for a JSON mini benchmark report.",
    )
    return parser.parse_args()


def _run_fixture(fixture: Fixture) -> dict[str, Any]:
    _reset_provider_call_state()
    RecordingUpstreamHandler.records = []
    RecordingUpstreamHandler.response_body = fixture.upstream_response
    MockLemonadeRouterHandler.records = []
    MockLemonadeRouterHandler.observed_segments = []
    MockLemonadeRouterHandler.useful_marker = fixture.useful_marker

    logs: list[str] = []
    upstream = _start_server(RecordingUpstreamHandler)
    lemonade = _start_server(MockLemonadeRouterHandler)
    try:
        with tempfile.TemporaryDirectory(
            prefix=f"sfe_proxy_shadow_mini_{fixture.fixture_id}_"
        ) as shadow_log_dir:
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
                        fixture.payload,
                    )
                finally:
                    proxy.shutdown()
                    proxy.server_close()

            event = _read_shadow_event(Path(shadow_log_dir))
    finally:
        upstream.shutdown()
        upstream.server_close()
        lemonade.shutdown()
        lemonade.server_close()

    return _fixture_record(fixture, response, event)


def _fixture_record(
    fixture: Fixture,
    response: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    selected_ids = event.get("shadow_router_candidate_selected_segment_ids")
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
    upstream_payload = _last_upstream_payload()
    router_metadata_usable = (
        event.get("shadow_router_status") == "candidate_selected"
        and bool(selected_segment_ids)
        and event.get("shadow_router_dry_run_only") is True
    )
    selection_matched = selected_segment_ids == [fixture.expected_segment_id]
    upstream_request_unchanged = upstream_payload == fixture.payload
    client_response_unchanged = (
        response.get("status") == 200
        and response.get("body") == fixture.upstream_response
    )
    passed = (
        router_metadata_usable
        and selection_matched
        and upstream_request_unchanged
        and client_response_unchanged
    )
    return {
        "fixture_id": fixture.fixture_id,
        "passed": passed,
        "expected_segment_id": fixture.expected_segment_id,
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
        "router_metadata_usable": router_metadata_usable,
        "router_dry_run_only": event.get("shadow_router_dry_run_only"),
        "upstream_request_unchanged": upstream_request_unchanged,
        "client_response_unchanged": client_response_unchanged,
        "candidate_segment_count": event.get("candidate_segment_count"),
        "observed_router_segment_ids": [
            segment.get("segment_id")
            for segment in MockLemonadeRouterHandler.observed_segments
        ],
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    passed = sum(1 for record in records if record["passed"])
    matched = sum(1 for record in records if record["selection_matched"])
    reductions = [
        float(record["estimated_token_reduction_pct"])
        for record in records
        if record["passed"] and record["estimated_token_reduction_pct"] is not None
    ]
    return {
        "total_fixtures": total,
        "passed_fixtures": passed,
        "failed_fixtures": total - passed,
        "selection_accuracy": round(matched / total, 4) if total else 0.0,
        "average_estimated_token_reduction_pct": (
            round(sum(reductions) / len(reductions), 2) if reductions else None
        ),
        "upstream_transparency_all_passed": all(
            record["upstream_request_unchanged"] for record in records
        ),
        "client_response_transparency_all_passed": all(
            record["client_response_unchanged"] for record in records
        ),
    }


def _print_report(records: list[dict[str, Any]], aggregate: dict[str, Any]) -> None:
    print("SFE proxy shadow mini benchmark")
    print(LIMITATION)
    print()
    print(
        "fixture_id | expected | selected | pass | reduction_pct | "
        "router_status | transparency"
    )
    print("-" * 95)
    for record in records:
        transparency = (
            "pass"
            if record["upstream_request_unchanged"]
            and record["client_response_unchanged"]
            else "fail"
        )
        print(
            f"{record['fixture_id']} | "
            f"{record['expected_segment_id']} | "
            f"{record['selected_segment_ids']} | "
            f"{record['passed']} | "
            f"{record['estimated_token_reduction_pct']} | "
            f"{record['router_status']} | "
            f"{transparency}"
        )
    print()
    print(f"total fixtures: {aggregate['total_fixtures']}")
    print(f"passed fixtures: {aggregate['passed_fixtures']}")
    print(f"failed fixtures: {aggregate['failed_fixtures']}")
    print(f"selection accuracy: {aggregate['selection_accuracy']:.2%}")
    print(
        "average estimated token reduction pct: "
        f"{aggregate['average_estimated_token_reduction_pct']}"
    )
    print(
        "upstream transparency all passed: "
        f"{aggregate['upstream_transparency_all_passed']}"
    )
    print(
        "client response transparency all passed: "
        f"{aggregate['client_response_transparency_all_passed']}"
    )


def _fixtures() -> list[Fixture]:
    return [
        Fixture(
            fixture_id="tariff_policy",
            expected_segment_id="segment-3",
            useful_marker="UTILITY-RATE-SCHEDULE-DELTA-17",
            upstream_response=_upstream_response("tariff_policy"),
            payload=_chat_payload(
                "tariff-policy-model",
                [
                    "Answer from the supplied segments.",
                    _repeat(
                        "SEGMENT A - archived cafeteria operations. "
                        "Badge rotations and cleaning windows are historical notes.",
                        8,
                    ),
                    _repeat(
                        "SEGMENT C - active utility tariff memo. "
                        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the battery dispatch "
                        "threshold at 42 kilowatts during the evening peak interval.",
                        4,
                    ),
                    _repeat(
                        "SEGMENT B - historical logistics notes. "
                        "Dock assignments and pallet labels are not tariff policy.",
                        8,
                    ),
                    _repeat(
                        "SEGMENT D - unrelated support transcript. "
                        "Login retries and ticket tags do not answer the tariff question.",
                        8,
                    ),
                    "Using the active utility tariff memo only, what battery dispatch "
                    "threshold applies during the evening peak interval?",
                ],
            ),
        ),
        Fixture(
            fixture_id="incident_runbook",
            expected_segment_id="segment-2",
            useful_marker="RUNBOOK-DB-FAILOVER-9",
            upstream_response=_upstream_response("incident_runbook"),
            payload=_chat_payload(
                "incident-runbook-model",
                [
                    "Use the relevant operational segment only.",
                    _repeat(
                        "SEGMENT A - active incident runbook. "
                        "RUNBOOK-DB-FAILOVER-9 says promote replica blue-3, freeze "
                        "write jobs, and page storage on-call before reopening writes.",
                        5,
                    ),
                    _repeat(
                        "SEGMENT B - office facilities memo. "
                        "Badge printer maintenance and visitor desk coverage are unrelated.",
                        8,
                    ),
                    _repeat(
                        "SEGMENT C - onboarding notes. "
                        "Laptop pickup and account naming rules are historical references.",
                        8,
                    ),
                    "During the database incident, which replica should be promoted "
                    "before writes reopen?",
                ],
            ),
        ),
        Fixture(
            fixture_id="compatibility_matrix",
            expected_segment_id="segment-4",
            useful_marker="COMPAT-MATRIX-ORION-12",
            upstream_response=_upstream_response("compatibility_matrix"),
            payload=_chat_payload(
                "compatibility-model",
                [
                    "Answer from the compatibility information.",
                    _repeat(
                        "SEGMENT A - marketing launch checklist. "
                        "Press quotes and webinar dates are not compatibility data.",
                        8,
                    ),
                    _repeat(
                        "SEGMENT B - finance planning extract. "
                        "Budget owner initials and forecast buckets are distractors.",
                        8,
                    ),
                    _repeat(
                        "SEGMENT C - release compatibility matrix. "
                        "COMPAT-MATRIX-ORION-12 states client SDK 4.8 is compatible "
                        "with gateway API 2026-04 and requires schema adapter r3.",
                        5,
                    ),
                    _repeat(
                        "SEGMENT D - customer note archive. "
                        "Renewal timing and meeting notes are not release compatibility.",
                        8,
                    ),
                    "Which client SDK and schema adapter are required for gateway API "
                    "2026-04?",
                ],
            ),
        ),
        Fixture(
            fixture_id="billing_terms",
            expected_segment_id="segment-1",
            useful_marker="BILLING-TERM-NET45-AUDIT",
            upstream_response=_upstream_response("billing_terms"),
            payload=_chat_payload(
                "billing-terms-model",
                [
                    _repeat(
                        "SEGMENT A - controlling billing terms. "
                        "BILLING-TERM-NET45-AUDIT requires invoices to use net-45 "
                        "payment terms and retain audit attachments for seven years.",
                        5,
                    ),
                    _repeat(
                        "SEGMENT B - shipping exception memo. "
                        "Warehouse cutoffs and label reprints are unrelated to billing.",
                        8,
                    ),
                    _repeat(
                        "SEGMENT C - deprecated sales playbook. "
                        "Discount talk tracks and renewal scripts are distractors.",
                        8,
                    ),
                    "For the controlling billing terms, what payment period applies "
                    "and how long are audit attachments retained?",
                ],
            ),
        ),
    ]


def _chat_payload(model: str, segments: list[str]) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "user", "content": segment}
            for segment in segments
        ],
        "stream": False,
    }


def _repeat(text: str, count: int) -> str:
    return (text + " ") * count


def _upstream_response(fixture_id: str) -> dict[str, Any]:
    return {
        "id": f"mock-{fixture_id}",
        "object": "chat.completion",
        "choices": [],
    }


def _mock_lemonade_response(body: bytes, useful_marker: str) -> bytes:
    lemonade_payload = json.loads(body.decode("utf-8"))
    router_prompt = json.loads(lemonade_payload["messages"][1]["content"])
    segments = router_prompt["candidate_segments"]
    MockLemonadeRouterHandler.observed_segments = segments
    selected = next(
        segment for segment in segments if useful_marker in segment["text"]
    )
    selected_tokens = int(selected["estimated_tokens"])
    full_tokens = int(router_prompt["rough_estimated_input_tokens"])
    reduction_pct = round((1 - (selected_tokens / full_tokens)) * 100, 2)
    router_output = {
        "router_status": "candidate_selected",
        "router_reason": f"selected_segment_for_marker:{useful_marker}",
        "candidate_selected_segment_ids": [selected["segment_id"]],
        "estimated_router_selected_input_tokens": selected_tokens,
        "estimated_router_token_reduction_pct": reduction_pct,
        "confidence": 0.91,
        "dry_run_only": True,
    }
    return json.dumps(
        {"choices": [{"message": {"content": json.dumps(router_output)}}]}
    ).encode("utf-8")


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
