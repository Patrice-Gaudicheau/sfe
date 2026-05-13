"""Run controlled live Lemonade multi-fixture validation for proxy enabled mode."""

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
    "Controlled local live Lemonade Qwen-only enabled-mode multi-fixture "
    "validation. Expected useful-segment inclusion is the pass criterion; "
    "exact selection is tracked as a precision and reduction metric. This "
    "does not test OpenAI or Anthropic, does not validate production "
    "reliability, and does not claim production readiness."
)


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    payload: dict[str, Any]
    expected_segment_id: str
    expected_marker: str
    distractor_markers_by_segment: dict[str, str]


def main() -> int:
    args = _parse_args()
    base_url = _lemonade_base_url()
    router_model = _router_model()
    executor_model = _executor_model()
    timeout_seconds = _live_timeout_seconds()

    if not router_model or not executor_model:
        report = _configuration_error_report(
            base_url=base_url,
            router_model=router_model,
            executor_model=executor_model,
            timeout_seconds=timeout_seconds,
        )
        _print_report(report["fixtures"], report["aggregate"])
        _maybe_write_json(args.json, report)
        return 1

    reachability = _probe_lemonade_models(base_url, timeout_seconds)
    if not reachability["reachable"]:
        report = _reachability_error_report(
            base_url=base_url,
            router_model=router_model,
            executor_model=executor_model,
            timeout_seconds=timeout_seconds,
            reachability=reachability,
        )
        _print_report(report["fixtures"], report["aggregate"])
        _maybe_write_json(args.json, report)
        return 1

    records = [
        _run_fixture(
            fixture,
            base_url=base_url,
            router_model=router_model,
            executor_model=executor_model,
            timeout_seconds=timeout_seconds,
            reachability=reachability,
        )
        for fixture in _fixtures(executor_model)
    ]
    aggregate = _aggregate(records)
    report = {
        "fixtures": records,
        "aggregate": aggregate,
        "limitation": LIMITATION,
        "lemonade_base_url": base_url,
        "router_model": router_model,
        "executor_model": executor_model,
        "timeout_seconds": timeout_seconds,
        "reachability": reachability,
    }
    _print_report(records, aggregate)
    _maybe_write_json(args.json, report)
    return 0 if aggregate["failed_fixtures"] == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run controlled live Lemonade Qwen-only multi-fixture validation "
            "for proxy mode=\"enabled\"."
        )
    )
    parser.add_argument("--json", type=Path, help="Optional path for a JSON report.")
    return parser.parse_args()


def _run_fixture(
    fixture: Fixture,
    *,
    base_url: str,
    router_model: str,
    executor_model: str,
    timeout_seconds: int,
    reachability: dict[str, Any],
) -> dict[str, Any]:
    _reset_provider_call_state()
    logs: list[str] = []
    response: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    request_error: BaseException | None = None
    with tempfile.TemporaryDirectory(
        prefix=f"sfe_proxy_enabled_live_lemonade_{fixture.fixture_id}_"
    ) as shadow_log_dir:
        proxy = _start_proxy(
            base_url=base_url,
            shadow_log_dir=shadow_log_dir,
            logs=logs,
            timeout_seconds=timeout_seconds,
        )
        try:
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

    return _fixture_record(
        fixture=fixture,
        response=response,
        event=event,
        request_error=request_error,
        base_url=base_url,
        router_model=router_model,
        executor_model=executor_model,
        timeout_seconds=timeout_seconds,
        reachability=reachability,
    )


def _fixture_record(
    *,
    fixture: Fixture,
    response: dict[str, Any] | None,
    event: dict[str, Any] | None,
    request_error: BaseException | None,
    base_url: str,
    router_model: str,
    executor_model: str,
    timeout_seconds: int,
    reachability: dict[str, Any],
) -> dict[str, Any]:
    event = event or {}
    selected_ids = event.get("enabled_selected_segment_ids")
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
    expected_included = fixture.expected_segment_id in selected_segment_ids
    exact_selection_match = selected_segment_ids == [fixture.expected_segment_id]
    over_selected_segment_ids = [
        segment_id
        for segment_id in selected_segment_ids
        if segment_id != fixture.expected_segment_id
    ]
    over_selected = expected_included and bool(over_selected_segment_ids)

    candidate_request = event.get("enabled_candidate_request")
    candidate_text = (
        json.dumps(candidate_request, sort_keys=True)
        if isinstance(candidate_request, dict)
        else ""
    )
    reduced_built = event.get("enabled_candidate_built") is True
    reduced_contains_expected = fixture.expected_marker in candidate_text
    reduced_excludes_unselected = _candidate_excludes_unselected_markers(
        candidate_text,
        selected_segment_ids,
        fixture.distractor_markers_by_segment,
    )
    client_response_status = response.get("status") if response is not None else None
    client_response_success = (
        isinstance(client_response_status, int)
        and 200 <= client_response_status < 300
    )
    enabled_request_sent = event.get("enabled_request_sent") is True
    original_request_sent_upstream = event.get("enabled_original_request_sent")
    original_request_not_sent = original_request_sent_upstream is False
    router_metadata_usable = (
        bool(selected_segment_ids)
        and event.get("shadow_router_error_type") is None
        and event.get("shadow_router_dry_run_only") is True
    )
    passed = (
        reachability["reachable"] is True
        and router_metadata_usable
        and expected_included
        and reduced_built
        and reduced_contains_expected
        and reduced_excludes_unselected
        and enabled_request_sent
        and original_request_not_sent
        and client_response_success
        and request_error is None
    )
    status = "pass" if passed else "fail"
    if isinstance(request_error, TimeoutError):
        status = "timeout"
    elif request_error is not None:
        status = "request_error"

    return {
        "fixture_id": fixture.fixture_id,
        "passed": passed,
        "status": status,
        "lemonade_base_url": base_url,
        "router_model": router_model,
        "executor_model": executor_model,
        "timeout_seconds": timeout_seconds,
        "expected_segment_id": fixture.expected_segment_id,
        "selected_segment_ids": selected_segment_ids,
        "selected_segment_count": len(selected_segment_ids),
        "expected_segment_included": expected_included,
        "exact_selection_match": exact_selection_match,
        "over_selected": over_selected,
        "over_selected_segment_ids": over_selected_segment_ids,
        "full_request_estimated_tokens": event.get(
            "enabled_full_request_estimated_tokens"
        ),
        "reduced_request_estimated_tokens": event.get(
            "enabled_candidate_request_estimated_tokens"
        ),
        "estimated_reduction_percent": event.get(
            "enabled_estimated_token_reduction_pct"
        ),
        "enabled_request_sent": enabled_request_sent,
        "original_request_sent_upstream": original_request_sent_upstream,
        "reduced_request_built": reduced_built,
        "reduced_request_contains_expected_segment": reduced_contains_expected,
        "reduced_request_excludes_unselected_segments": reduced_excludes_unselected,
        "client_response_status": client_response_status,
        "client_response_success": client_response_success,
        "routing_status": event.get("shadow_router_status"),
        "routing_reason": event.get("shadow_router_reason"),
        "routing_error_type": event.get("shadow_router_error_type"),
        "router_metadata_usable": router_metadata_usable,
        "request_error_type": type(request_error).__name__ if request_error else None,
        "request_error": str(request_error) if request_error else None,
    }


def _aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    passed = sum(1 for record in records if record["passed"])
    included = sum(1 for record in records if record["expected_segment_included"])
    exact = sum(1 for record in records if record["exact_selection_match"])
    over_selected = sum(1 for record in records if record["over_selected"])
    client_success = sum(1 for record in records if record["client_response_success"])
    original_not_sent = sum(
        1 for record in records if record["original_request_sent_upstream"] is False
    )
    reduced_sent = sum(1 for record in records if record["enabled_request_sent"])
    selected_counts = [int(record["selected_segment_count"]) for record in records]
    full_tokens = [
        int(record["full_request_estimated_tokens"])
        for record in records
        if isinstance(record["full_request_estimated_tokens"], int)
    ]
    reduced_tokens = [
        int(record["reduced_request_estimated_tokens"])
        for record in records
        if isinstance(record["reduced_request_estimated_tokens"], int)
    ]
    reductions = [
        float(record["estimated_reduction_percent"])
        for record in records
        if isinstance(record["estimated_reduction_percent"], (int, float))
    ]
    return {
        "total_fixtures": total,
        "passed_fixtures": passed,
        "failed_fixtures": total - passed,
        "expected_inclusion_accuracy": round(included / total, 4) if total else 0.0,
        "exact_selection_accuracy": round(exact / total, 4) if total else 0.0,
        "over_selection_count": over_selected,
        "average_selected_segment_count": _average(selected_counts),
        "average_full_request_estimated_tokens": _average(full_tokens),
        "average_reduced_request_estimated_tokens": _average(reduced_tokens),
        "average_estimated_reduction_percent": _average(reductions),
        "client_success_count": client_success,
        "original_request_not_sent_upstream_count": original_not_sent,
        "reduced_request_sent_upstream_count": reduced_sent,
    }


def _average(values: list[int] | list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _print_report(records: list[dict[str, Any]], aggregate: dict[str, Any]) -> None:
    print("SFE proxy enabled live Lemonade multi-fixture runner")
    print(LIMITATION)
    print()
    print(
        "fixture_id | expected | selected | included | exact | over_selected | "
        "pass | full_tokens | reduced_tokens | reduction_pct | client_status | "
        "routing_status | enabled_sent | original_sent"
    )
    print("-" * 170)
    for record in records:
        print(
            f"{record['fixture_id']} | "
            f"{record['expected_segment_id']} | "
            f"{record['selected_segment_ids']} | "
            f"{record['expected_segment_included']} | "
            f"{record['exact_selection_match']} | "
            f"{record['over_selected']} | "
            f"{record['passed']} | "
            f"{record['full_request_estimated_tokens']} | "
            f"{record['reduced_request_estimated_tokens']} | "
            f"{record['estimated_reduction_percent']} | "
            f"{record['client_response_status']} | "
            f"{record['routing_status']} | "
            f"{record['enabled_request_sent']} | "
            f"{record['original_request_sent_upstream']}"
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
        "average full request estimated tokens: "
        f"{aggregate['average_full_request_estimated_tokens']}"
    )
    print(
        "average reduced request estimated tokens: "
        f"{aggregate['average_reduced_request_estimated_tokens']}"
    )
    print(
        "average estimated reduction percent: "
        f"{aggregate['average_estimated_reduction_percent']}"
    )
    print(f"client success count: {aggregate['client_success_count']}")
    print(
        "original request not sent upstream count: "
        f"{aggregate['original_request_not_sent_upstream_count']}"
    )
    print(
        "reduced request sent upstream count: "
        f"{aggregate['reduced_request_sent_upstream_count']}"
    )


def _configuration_error_report(
    *,
    base_url: str,
    router_model: str,
    executor_model: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    missing = []
    if not router_model:
        missing.append("SFE_ROUTER_MODEL")
    if not executor_model:
        missing.append("SFE_EXECUTOR_MODEL")
    record = _error_record(
        fixture_id="configuration",
        status="configuration_error",
        router_model=router_model,
        executor_model=executor_model,
        timeout_seconds=timeout_seconds,
        routing_error_type="MissingConfiguration",
        routing_reason=f"missing_required_env:{','.join(missing)}",
    )
    return {
        "fixtures": [record],
        "aggregate": _aggregate([record]),
        "limitation": LIMITATION,
        "lemonade_base_url": base_url,
        "router_model": router_model,
        "executor_model": executor_model,
        "timeout_seconds": timeout_seconds,
    }


def _reachability_error_report(
    *,
    base_url: str,
    router_model: str,
    executor_model: str,
    timeout_seconds: int,
    reachability: dict[str, Any],
) -> dict[str, Any]:
    record = _error_record(
        fixture_id="reachability",
        status="lemonade_unreachable",
        router_model=router_model,
        executor_model=executor_model,
        timeout_seconds=timeout_seconds,
        routing_error_type=reachability["error_type"],
        routing_reason="lemonade_models_probe_failed",
    )
    return {
        "fixtures": [record],
        "aggregate": _aggregate([record]),
        "limitation": LIMITATION,
        "lemonade_base_url": base_url,
        "router_model": router_model,
        "executor_model": executor_model,
        "timeout_seconds": timeout_seconds,
        "reachability": reachability,
    }


def _error_record(
    *,
    fixture_id: str,
    status: str,
    router_model: str,
    executor_model: str,
    timeout_seconds: int,
    routing_error_type: str | None,
    routing_reason: str,
) -> dict[str, Any]:
    return {
        "fixture_id": fixture_id,
        "passed": False,
        "status": status,
        "router_model": router_model,
        "executor_model": executor_model,
        "timeout_seconds": timeout_seconds,
        "expected_segment_id": "",
        "selected_segment_ids": [],
        "selected_segment_count": 0,
        "expected_segment_included": False,
        "exact_selection_match": False,
        "over_selected": False,
        "over_selected_segment_ids": [],
        "full_request_estimated_tokens": None,
        "reduced_request_estimated_tokens": None,
        "estimated_reduction_percent": None,
        "enabled_request_sent": False,
        "original_request_sent_upstream": None,
        "reduced_request_built": False,
        "reduced_request_contains_expected_segment": False,
        "reduced_request_excludes_unselected_segments": False,
        "client_response_status": None,
        "client_response_success": False,
        "routing_status": "not_run",
        "routing_reason": routing_reason,
        "routing_error_type": routing_error_type,
        "router_metadata_usable": False,
        "request_error_type": None,
        "request_error": None,
    }


def _fixtures(executor_model: str) -> list[Fixture]:
    return [
        Fixture(
            fixture_id="tariff_policy",
            expected_segment_id="segment-3",
            expected_marker="UTILITY-RATE-SCHEDULE-DELTA-17",
            distractor_markers_by_segment={
                "segment-2": "CAFETERIA-BADGE-ROTATION-ALPHA",
                "segment-4": "WAREHOUSE-PALLET-LABEL-BETA",
                "segment-5": "SUPPORT-TICKET-ALIAS-GAMMA",
            },
            payload=_chat_payload(
                executor_model,
                [
                    ("system", "Answer from the supplied segments."),
                    (
                        "user",
                        _repeat(
                            "SEGMENT A - archived cafeteria operations. "
                            "CAFETERIA-BADGE-ROTATION-ALPHA describes badge "
                            "rotation and cleaning windows.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT C - active utility tariff memo. "
                            "UTILITY-RATE-SCHEDULE-DELTA-17 sets the battery "
                            "dispatch threshold at 42 kilowatts during the "
                            "evening peak interval.",
                            5,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT B - historical logistics notes. "
                            "WAREHOUSE-PALLET-LABEL-BETA covers dock assignments "
                            "and carrier calls.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT D - unrelated support transcript. "
                            "SUPPORT-TICKET-ALIAS-GAMMA discusses login retries "
                            "and ticket tags.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        "Using the active utility tariff memo only, what battery "
                        "dispatch threshold applies during the evening peak interval?",
                    ),
                ],
            ),
        ),
        Fixture(
            fixture_id="compatibility_matrix",
            expected_segment_id="segment-4",
            expected_marker="COMPAT-MATRIX-ORION-12",
            distractor_markers_by_segment={
                "segment-2": "MARKETING-WEBINAR-ALPHA",
                "segment-3": "FINANCE-FORECAST-BETA",
                "segment-5": "CUSTOMER-RENEWAL-GAMMA",
            },
            payload=_chat_payload(
                executor_model,
                [
                    ("system", "Answer from the compatibility information."),
                    (
                        "user",
                        _repeat(
                            "SEGMENT A - marketing launch checklist. "
                            "MARKETING-WEBINAR-ALPHA lists press quotes and "
                            "webinar dates.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT B - finance planning extract. "
                            "FINANCE-FORECAST-BETA lists budget owner initials "
                            "and forecast buckets.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT C - release compatibility matrix. "
                            "COMPAT-MATRIX-ORION-12 states client SDK 4.8 is "
                            "compatible with gateway API 2026-04 and requires "
                            "schema adapter r3.",
                            5,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT D - customer note archive. "
                            "CUSTOMER-RENEWAL-GAMMA lists renewal timing and "
                            "meeting notes.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        "Which client SDK and schema adapter are required for "
                        "gateway API 2026-04?",
                    ),
                ],
            ),
        ),
        Fixture(
            fixture_id="billing_terms",
            expected_segment_id="segment-1",
            expected_marker="BILLING-TERM-NET45-AUDIT",
            distractor_markers_by_segment={
                "segment-2": "SHIPPING-LABEL-REPRINT-ALPHA",
                "segment-3": "SALES-PLAYBOOK-DISCOUNT-BETA",
            },
            payload=_chat_payload(
                executor_model,
                [
                    (
                        "user",
                        _repeat(
                            "SEGMENT A - controlling billing terms. "
                            "BILLING-TERM-NET45-AUDIT requires invoices to use "
                            "net-45 payment terms and retain audit attachments "
                            "for seven years.",
                            5,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT B - shipping exception memo. "
                            "SHIPPING-LABEL-REPRINT-ALPHA covers warehouse "
                            "cutoffs and label reprints.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        _repeat(
                            "SEGMENT C - deprecated sales playbook. "
                            "SALES-PLAYBOOK-DISCOUNT-BETA covers discount talk "
                            "tracks and renewal scripts.",
                            6,
                        ),
                    ),
                    (
                        "user",
                        "For the controlling billing terms, what payment period "
                        "applies and how long are audit attachments retained?",
                    ),
                ],
            ),
        ),
    ]


def _chat_payload(model: str, messages: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": role, "content": content}
            for role, content in messages
        ],
        "stream": False,
        "temperature": 0,
    }


def _repeat(text: str, count: int) -> str:
    return (text + " ") * count


def _lemonade_base_url() -> str:
    return os.getenv("SFE_LEMONADE_BASE_URL") or DEFAULT_LEMONADE_ROUTER_BASE_URL


def _router_model() -> str:
    return os.getenv("SFE_ROUTER_MODEL") or ""


def _executor_model() -> str:
    return os.getenv("SFE_EXECUTOR_MODEL") or ""


def _live_timeout_seconds() -> int:
    raw = os.getenv(LIVE_TIMEOUT_ENV, str(DEFAULT_LIVE_TIMEOUT_SECONDS))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{LIVE_TIMEOUT_ENV} must be an integer.") from exc
    if value <= 0:
        raise SystemExit(f"{LIVE_TIMEOUT_ENV} must be positive.")
    return value


def _probe_lemonade_models(base_url: str, timeout_seconds: int) -> dict[str, Any]:
    url = _join_url(base_url, "/v1/models")
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            decoded = json.loads(body) if body else {}
            return {
                "reachable": 200 <= int(response.status) < 300,
                "status": int(response.status),
                "model_names": _model_names(decoded),
                "error_type": None,
                "error": None,
            }
    except (urllib.error.URLError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "reachable": False,
            "status": None,
            "model_names": [],
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _model_names(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [
        item["id"]
        for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    ]


def _candidate_excludes_unselected_markers(
    candidate_text: str,
    selected_segment_ids: list[str],
    distractor_markers_by_segment: dict[str, str],
) -> bool:
    selected = set(selected_segment_ids)
    for segment_id, marker in distractor_markers_by_segment.items():
        if segment_id in selected:
            continue
        if marker in candidate_text:
            return False
    return True


def _maybe_write_json(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _start_proxy(
    *,
    base_url: str,
    shadow_log_dir: str,
    logs: list[str],
    timeout_seconds: int,
) -> Any:
    proxy = create_server(
        ProxyConfig(
            host="127.0.0.1",
            port=_free_port(),
            upstream_base_url=base_url,
            upstream_api_key="local-lemonade-placeholder",
            mode="enabled",
            shadow_log_dir=shadow_log_dir,
            shadow_log_full_payloads=True,
            shadow_min_input_tokens=1,
            shadow_selection_dry_run=True,
            shadow_router_dry_run=True,
            shadow_router_provider="lemonade",
            shadow_router_timeout_seconds=timeout_seconds,
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
            "Authorization": "Bearer local-placeholder-token",
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
        body = exc.read().decode("utf-8")
        return {
            "status": exc.code,
            "body": json.loads(body) if body else {},
        }


def _read_shadow_event_if_present(log_dir: Path) -> dict[str, Any] | None:
    path = log_dir / "shadow_events.jsonl"
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        return None
    return json.loads(lines[-1])


def _server_url(server: Any) -> str:
    host, port = server.server_address
    return f"http://{host}:{port}"


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _join_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


if __name__ == "__main__":
    raise SystemExit(main())
