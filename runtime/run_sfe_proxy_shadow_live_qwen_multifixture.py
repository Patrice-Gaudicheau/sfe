"""Run a controlled live Lemonade Qwen-only proxy shadow multi-fixture check."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import urllib.error
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
from sfe_proxy.shadow_router import DEFAULT_LEMONADE_ROUTER_BASE_URL
from sfe_proxy.shadow_router import _reset_provider_call_state


DEFAULT_LIVE_TIMEOUT_SECONDS = 180
LIVE_TIMEOUT_ENV = "SFE_PROXY_SHADOW_LIVE_TIMEOUT_SECONDS"
LIMITATION = (
    "Controlled live Lemonade Qwen-only shadow-routing runner; not production "
    "validation, not statistical proof, and not SFE-enabled execution. This "
    "runner separates useful-segment inclusion from exact-selection precision "
    "because live LLM routers may safely over-select while still preserving "
    "the required context."
)


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    payload: dict[str, Any]
    upstream_response: dict[str, Any]
    expected_segment_id: str


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


def main() -> int:
    args = _parse_args()
    base_url = _lemonade_base_url()
    router_model = _router_model()
    timeout_seconds = _live_timeout_seconds()
    if not router_model:
        report = _configuration_error_report(base_url, timeout_seconds)
        _print_report(report["fixtures"], report["aggregate"])
        if args.json is not None:
            _write_json(args.json, report)
        return 1

    records = [
        _run_fixture(
            fixture,
            base_url=base_url,
            router_model=router_model,
            timeout_seconds=timeout_seconds,
        )
        for fixture in _fixtures()
    ]
    aggregate = _aggregate(records)
    report = {
        "fixtures": records,
        "aggregate": aggregate,
        "limitation": LIMITATION,
        "lemonade_base_url": base_url,
        "router_model": router_model,
        "timeout_seconds": timeout_seconds,
    }
    _print_report(records, aggregate)
    if args.json is not None:
        _write_json(args.json, report)
    return 0 if aggregate["failed_fixtures"] == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a controlled live Lemonade Qwen-only proxy shadow multi-fixture check."
    )
    parser.add_argument(
        "--json",
        type=Path,
        help="Optional path for a JSON report.",
    )
    return parser.parse_args()


def _run_fixture(
    fixture: Fixture,
    *,
    base_url: str,
    router_model: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    _reset_provider_call_state()
    RecordingUpstreamHandler.records = []
    RecordingUpstreamHandler.response_body = fixture.upstream_response

    logs: list[str] = []
    response: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    request_error: BaseException | None = None
    upstream = _start_server(RecordingUpstreamHandler)
    try:
        with tempfile.TemporaryDirectory(
            prefix=f"sfe_proxy_shadow_live_qwen_{fixture.fixture_id}_"
        ) as shadow_log_dir:
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
                        fixture.payload,
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

    return _fixture_record(fixture, response, event, request_error)


def _fixture_record(
    fixture: Fixture,
    response: dict[str, Any] | None,
    event: dict[str, Any] | None,
    request_error: BaseException | None,
) -> dict[str, Any]:
    event = event or {}
    selected_ids = event.get("shadow_router_candidate_selected_segment_ids")
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
    upstream_payload = _last_upstream_payload()
    upstream_request_unchanged = (
        None if upstream_payload is None else upstream_payload == fixture.payload
    )
    client_response_unchanged = (
        None
        if response is None
        else response.get("status") == 200
        and response.get("body") == fixture.upstream_response
    )
    router_metadata_usable = (
        bool(selected_segment_ids)
        and event.get("shadow_router_dry_run_only") is True
        and event.get("shadow_router_error_type") is None
    )
    expected_segment_included = fixture.expected_segment_id in selected_segment_ids
    exact_selection_match = selected_segment_ids == [fixture.expected_segment_id]
    over_selected_segment_ids = [
        segment_id
        for segment_id in selected_segment_ids
        if segment_id != fixture.expected_segment_id
    ]
    over_selected = expected_segment_included and bool(over_selected_segment_ids)
    passed = (
        router_metadata_usable
        and expected_segment_included
        and upstream_request_unchanged is True
        and client_response_unchanged is True
    )
    status = "pass" if passed else "fail"
    if isinstance(request_error, TimeoutError) or event.get("shadow_router_reason") == "lemonade_router_timeout":
        status = "timeout"
    elif request_error is not None:
        status = "request_error"
    return {
        "fixture_id": fixture.fixture_id,
        "passed": passed,
        "status": status,
        "expected_segment_id": fixture.expected_segment_id,
        "selected_segment_ids": selected_segment_ids,
        "selected_segment_count": len(selected_segment_ids),
        "expected_segment_included": expected_segment_included,
        "exact_selection_match": exact_selection_match,
        "over_selected": over_selected,
        "over_selected_segment_ids": over_selected_segment_ids,
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


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    passed = sum(1 for record in records if record["passed"])
    included = sum(1 for record in records if record["expected_segment_included"])
    exact = sum(1 for record in records if record["exact_selection_match"])
    over_selected = sum(1 for record in records if record["over_selected"])
    selected_counts = [int(record["selected_segment_count"]) for record in records]
    reductions = [
        float(record["estimated_token_reduction_pct"])
        for record in records
        if record["passed"] and record["estimated_token_reduction_pct"] is not None
    ]
    return {
        "total_fixtures": total,
        "passed_fixtures": passed,
        "failed_fixtures": total - passed,
        "expected_inclusion_accuracy": round(included / total, 4) if total else 0.0,
        "exact_selection_accuracy": round(exact / total, 4) if total else 0.0,
        "over_selection_count": over_selected,
        "average_selected_segment_count": (
            round(sum(selected_counts) / len(selected_counts), 2)
            if selected_counts
            else 0.0
        ),
        "average_estimated_token_reduction_pct": (
            round(sum(reductions) / len(reductions), 2) if reductions else None
        ),
        "upstream_transparency_all_passed": all(
            record["upstream_request_unchanged"] is True for record in records
        ),
        "client_response_transparency_all_passed": all(
            record["client_response_unchanged"] is True for record in records
        ),
    }


def _print_report(records: list[dict[str, Any]], aggregate: dict[str, Any]) -> None:
    print("SFE proxy shadow live Qwen multi-fixture runner")
    print(LIMITATION)
    print()
    print(
        "fixture_id | expected | selected | included | exact | over_selected | "
        "pass | reduction_pct | router_status | transparency"
    )
    print("-" * 130)
    for record in records:
        transparency = (
            "pass"
            if record["upstream_request_unchanged"] is True
            and record["client_response_unchanged"] is True
            else "fail"
        )
        print(
            f"{record['fixture_id']} | "
            f"{record['expected_segment_id']} | "
            f"{record['selected_segment_ids']} | "
            f"{record['expected_segment_included']} | "
            f"{record['exact_selection_match']} | "
            f"{record['over_selected']} | "
            f"{record['passed']} | "
            f"{record['estimated_token_reduction_pct']} | "
            f"{record['router_status']} | "
            f"{transparency}"
        )
    print()
    print(f"total fixtures: {aggregate['total_fixtures']}")
    print(f"passed fixtures: {aggregate['passed_fixtures']}")
    print(f"failed fixtures: {aggregate['failed_fixtures']}")
    print(
        "expected inclusion accuracy: "
        f"{aggregate['expected_inclusion_accuracy']:.2%}"
    )
    print(f"exact selection accuracy: {aggregate['exact_selection_accuracy']:.2%}")
    print(f"over-selection count: {aggregate['over_selection_count']}")
    print(
        "average selected segment count: "
        f"{aggregate['average_selected_segment_count']}"
    )
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


def _configuration_error_report(base_url: str, timeout_seconds: int) -> dict[str, Any]:
    record = {
        "fixture_id": "configuration",
        "passed": False,
        "status": "configuration_error",
        "expected_segment_id": "",
        "selected_segment_ids": [],
        "selected_segment_count": 0,
        "expected_segment_included": False,
        "exact_selection_match": False,
        "over_selected": False,
        "over_selected_segment_ids": [],
        "estimated_selected_tokens": None,
        "estimated_token_reduction_pct": None,
        "router_status": "not_run",
        "router_reason": "missing_SFE_ROUTER_MODEL",
        "router_error_type": "MissingModel",
        "request_error_type": None,
        "request_error": None,
        "router_metadata_usable": False,
        "router_dry_run_only": None,
        "upstream_request_unchanged": None,
        "client_response_unchanged": None,
        "candidate_segment_count": None,
    }
    return {
        "fixtures": [record],
        "aggregate": _aggregate([record]),
        "limitation": LIMITATION,
        "lemonade_base_url": base_url,
        "router_model": "",
        "timeout_seconds": timeout_seconds,
    }


def _fixtures() -> list[Fixture]:
    return [
        Fixture(
            fixture_id="tariff_policy",
            expected_segment_id="segment-3",
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
        "id": f"mock-live-qwen-{fixture_id}",
        "object": "chat.completion",
        "choices": [],
    }


def _lemonade_base_url() -> str:
    return os.getenv("SFE_LEMONADE_BASE_URL") or DEFAULT_LEMONADE_ROUTER_BASE_URL


def _router_model() -> str:
    return os.getenv("SFE_ROUTER_MODEL", "")


def _live_timeout_seconds() -> int:
    raw = os.getenv(LIVE_TIMEOUT_ENV, str(DEFAULT_LIVE_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{LIVE_TIMEOUT_ENV} must be an integer.") from exc
    if value <= 0:
        raise SystemExit(f"{LIVE_TIMEOUT_ENV} must be positive.")
    return value


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
