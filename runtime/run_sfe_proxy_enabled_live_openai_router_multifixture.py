"""Run a controlled live OpenAI-router/OpenAI-executor multi-fixture check."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import DEFAULT_BASE_URL as OPENAI_DEFAULT_BASE_URL
from sfe_proxy.config import ProxyConfig
from sfe_proxy.server import create_server
from sfe_proxy.shadow_router import _reset_provider_call_state


LIMITATION = (
    "Controlled mini multi-fixture OpenAI router plus OpenAI executor "
    "enabled-mode validation. OpenAI is used for live routing and for reduced "
    "upstream requests. Expected useful-segment inclusion is the pass metric; "
    "exact selection is tracked as precision. This is narrow, cost-controlled "
    "validation only; Anthropic is not tested here, and production readiness "
    "is not claimed."
)


@dataclass(frozen=True)
class Fixture:
    fixture_id: str
    expected_segment_id: str
    useful_marker: str
    distractor_markers_by_segment: dict[str, str]
    question: str
    expected_answer_hint: str
    messages: list[dict[str, str]]


def main() -> int:
    args = _parse_args()
    _reset_provider_call_state()

    config = _openai_config()
    fixtures = _fixtures(config["executor_model"])
    configuration_error = _configuration_error(config)
    if configuration_error is not None:
        report = _configuration_error_report(config, configuration_error, fixtures)
        _print_report(report)
        _maybe_write_json(args.json, report)
        return 1

    records = [_run_fixture(fixture, config) for fixture in fixtures]
    aggregate = _aggregate(records, config)
    report = {
        "fixtures": records,
        "aggregate": aggregate,
        "limitation": LIMITATION,
    }
    _print_report(report)
    _maybe_write_json(args.json, report)
    return 0 if aggregate["failed_fixtures"] == 0 else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a controlled live OpenAI router plus OpenAI executor "
            "multi-fixture validation for proxy mode=\"enabled\"."
        )
    )
    parser.add_argument("--json", type=Path, help="Optional path for a JSON report.")
    return parser.parse_args()


def _openai_config() -> dict[str, Any]:
    base_url = os.getenv("OPENAI_BASE_URL") or OPENAI_DEFAULT_BASE_URL
    timeout_raw = os.getenv("SFE_OPENAI_API_TIMEOUT") or "60"
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError as exc:
        raise SystemExit("SFE_OPENAI_API_TIMEOUT must be a number.") from exc
    if timeout_seconds <= 0:
        raise SystemExit("SFE_OPENAI_API_TIMEOUT must be positive.")
    return {
        "api_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "openai_base_url": base_url.rstrip("/"),
        "timeout_seconds": timeout_seconds,
        "router_model": os.getenv("SFE_OPENAI_ROUTER_MODEL") or "",
        "executor_model": os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or "",
        "routing_provider": "openai",
    }


def _configuration_error(config: dict[str, Any]) -> str | None:
    if not config["api_key_set"]:
        return "missing_OPENAI_API_KEY"
    if not config["router_model"]:
        return "missing_SFE_OPENAI_ROUTER_MODEL"
    if not config["executor_model"]:
        return "missing_SFE_OPENAI_EXECUTOR_MODEL"
    return None


def _fixtures(executor_model: str) -> list[Fixture]:
    del executor_model
    return [
        _tariff_policy_fixture(),
        _compatibility_matrix_fixture(),
        _billing_terms_fixture(),
    ]


def _tariff_policy_fixture() -> Fixture:
    distractor_a = (
        "SEGMENT A - archived cafeteria operations. "
        "CAFETERIA-BADGE-ROTATION-ALPHA describes badge color rotation, "
        "break-room inventory, and coffee machine cleaning windows. "
    ) * 3
    useful_segment = (
        "SEGMENT C - active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the battery dispatch threshold at "
        "42 kilowatts during the evening peak interval. "
    ) * 7
    distractor_b = (
        "SEGMENT B - historical logistics notes. "
        "WAREHOUSE-PALLET-LABEL-BETA covers dock assignments, pallet labels, "
        "and carrier calls. "
    ) * 3
    distractor_c = (
        "SEGMENT D - unrelated support transcript. "
        "SUPPORT-TICKET-ALIAS-GAMMA discusses login retries, email aliases, "
        "and ticket tags. "
    ) * 3
    question = (
        "Using the active utility tariff memo only, reply with only the "
        "battery dispatch threshold value for the evening peak interval."
    )
    return Fixture(
        fixture_id="tariff_policy",
        expected_segment_id="segment-3",
        useful_marker="UTILITY-RATE-SCHEDULE-DELTA-17",
        distractor_markers_by_segment={
            "segment-2": "CAFETERIA-BADGE-ROTATION-ALPHA",
            "segment-4": "WAREHOUSE-PALLET-LABEL-BETA",
            "segment-5": "SUPPORT-TICKET-ALIAS-GAMMA",
        },
        question=question,
        expected_answer_hint="42",
        messages=[
            _system_message(),
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": useful_segment},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": distractor_c},
            {"role": "user", "content": question},
        ],
    )


def _compatibility_matrix_fixture() -> Fixture:
    distractor_a = (
        "SEGMENT A - cafeteria seating inventory. "
        "CAFETERIA-SEATING-GRID-RHO describes chair counts, table spacing, "
        "and lunchroom signage. "
    ) * 3
    distractor_b = (
        "SEGMENT B - travel policy archive. "
        "TRAVEL-RECEIPT-RULE-SIGMA covers taxi receipts, hotel folios, and "
        "expense submission windows. "
    ) * 3
    distractor_c = (
        "SEGMENT C - printer fleet maintenance. "
        "PRINTER-FIRMWARE-CYCLE-TAU discusses toner, trays, and copier queue "
        "renaming. "
    ) * 3
    useful_segment = (
        "SEGMENT D - release compatibility matrix. "
        "COMPAT-MATRIX-ORION-9 states that runtime 2.8 supports plugin API "
        "version 14 as the minimum compatible plugin API. "
    ) * 7
    question = (
        "Using the release compatibility matrix only, reply with only the "
        "minimum compatible plugin API version for runtime 2.8."
    )
    return Fixture(
        fixture_id="compatibility_matrix",
        expected_segment_id="segment-5",
        useful_marker="COMPAT-MATRIX-ORION-9",
        distractor_markers_by_segment={
            "segment-2": "CAFETERIA-SEATING-GRID-RHO",
            "segment-3": "TRAVEL-RECEIPT-RULE-SIGMA",
            "segment-4": "PRINTER-FIRMWARE-CYCLE-TAU",
        },
        question=question,
        expected_answer_hint="14",
        messages=[
            _system_message(),
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": distractor_c},
            {"role": "user", "content": useful_segment},
            {"role": "user", "content": question},
        ],
    )


def _billing_terms_fixture() -> Fixture:
    useful_segment = (
        "SEGMENT A - current billing terms. "
        "BILLING-TERM-MERCURY-4 says invoices enter late-fee status after a "
        "12 day grace period from the invoice due date. "
    ) * 7
    distractor_a = (
        "SEGMENT B - office access policy. "
        "OFFICE-ACCESS-PIN-VIOLET describes visitor badges, elevator hours, "
        "and reception desk coverage. "
    ) * 3
    distractor_b = (
        "SEGMENT C - equipment disposal notes. "
        "EQUIPMENT-DISPOSAL-LEDGER-WEST covers monitor recycling and asset "
        "tag removal. "
    ) * 3
    distractor_c = (
        "SEGMENT D - survey invitation archive. "
        "SURVEY-LINK-ARCHIVE-NORTH discusses response windows and reminder "
        "email cadence. "
    ) * 3
    question = (
        "Using the current billing terms only, reply with only the late-fee "
        "grace period in days."
    )
    return Fixture(
        fixture_id="billing_terms",
        expected_segment_id="segment-2",
        useful_marker="BILLING-TERM-MERCURY-4",
        distractor_markers_by_segment={
            "segment-3": "OFFICE-ACCESS-PIN-VIOLET",
            "segment-4": "EQUIPMENT-DISPOSAL-LEDGER-WEST",
            "segment-5": "SURVEY-LINK-ARCHIVE-NORTH",
        },
        question=question,
        expected_answer_hint="12",
        messages=[
            _system_message(),
            {"role": "user", "content": useful_segment},
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": distractor_c},
            {"role": "user", "content": question},
        ],
    )


def _system_message() -> dict[str, str]:
    return {
        "role": "system",
        "content": "Answer from the supplied segments. Keep the answer as short as possible.",
    }


def _payload_for_fixture(fixture: Fixture, executor_model: str) -> dict[str, Any]:
    return {
        "model": executor_model,
        "messages": fixture.messages,
        "stream": False,
        "max_tokens": 24,
    }


def _run_fixture(fixture: Fixture, config: dict[str, Any]) -> dict[str, Any]:
    payload = _payload_for_fixture(fixture, config["executor_model"])
    response: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    request_error: BaseException | None = None
    logs: list[str] = []
    with tempfile.TemporaryDirectory(
        prefix=f"sfe_proxy_enabled_live_openai_router_{fixture.fixture_id}_"
    ) as shadow_log_dir:
        proxy = _start_proxy(
            openai_base_url=config["openai_base_url"],
            api_key=os.environ["OPENAI_API_KEY"],
            shadow_log_dir=shadow_log_dir,
            timeout_seconds=config["timeout_seconds"],
            logs=logs,
        )
        try:
            try:
                response = _request_json(
                    f"{_server_url(proxy)}/v1/chat/completions",
                    payload,
                    timeout_seconds=config["timeout_seconds"],
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
        payload=payload,
        response=response,
        event=event,
        request_error=request_error,
        config=config,
    )


def _fixture_record(
    *,
    fixture: Fixture,
    payload: dict[str, Any],
    response: dict[str, Any] | None,
    event: dict[str, Any] | None,
    request_error: BaseException | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    event = event or {}
    enabled_selected_ids = event.get("enabled_selected_segment_ids")
    enabled_selected_segment_ids = (
        enabled_selected_ids if isinstance(enabled_selected_ids, list) else []
    )
    router_selected_ids = event.get("shadow_router_candidate_selected_segment_ids")
    router_selected_segment_ids = (
        router_selected_ids if isinstance(router_selected_ids, list) else []
    )
    openai_router_used = (
        event.get("shadow_router_provider") == "openai"
        and event.get("shadow_router_name") == "openai"
    )
    selected_segment_ids = (
        router_selected_segment_ids
        if openai_router_used
        else enabled_selected_segment_ids
    )
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
    reduced_contains_expected = fixture.useful_marker in candidate_text
    reduced_excludes_unselected = _candidate_excludes_unselected_markers(
        candidate_text,
        enabled_selected_segment_ids,
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
    router_status = event.get("shadow_router_status")
    router_error_type = event.get("shadow_router_error_type")
    router_selection_usable = (
        openai_router_used
        and bool(router_selected_segment_ids)
        and router_error_type is None
        and isinstance(router_status, str)
    )
    executor_status = "success" if client_response_success else "error"
    if request_error is not None:
        executor_status = "request_error"
    passed = (
        config["api_key_set"] is True
        and router_selection_usable
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
        "status": status,
        "passed": passed,
        "openai_router_used": openai_router_used,
        "router_model": config["router_model"],
        "executor_model": config["executor_model"],
        "expected_segment_id": fixture.expected_segment_id,
        "selected_segment_ids": selected_segment_ids,
        "expected_segment_included": expected_included,
        "exact_selection_match": exact_selection_match,
        "over_selected": over_selected,
        "over_selected_segment_ids": over_selected_segment_ids,
        "selected_segment_count": len(selected_segment_ids),
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
        "client_response_preview": _response_preview(response),
        "router_status": router_status,
        "router_reason": event.get("shadow_router_reason"),
        "router_error_type": router_error_type,
        "executor_status": executor_status,
        "executor_error_type": type(request_error).__name__ if request_error else None,
        "executor_error": str(request_error) if request_error else None,
        "expected_answer_hint": fixture.expected_answer_hint,
        "original_payload_model": payload.get("model"),
    }


def _configuration_error_report(
    config: dict[str, Any],
    reason: str,
    fixtures: list[Fixture],
) -> dict[str, Any]:
    records = [
        {
            "fixture_id": fixture.fixture_id,
            "status": "configuration_error",
            "passed": False,
            "expected_segment_id": fixture.expected_segment_id,
            "selected_segment_ids": [],
            "expected_segment_included": False,
            "exact_selection_match": False,
            "over_selected": False,
            "client_response_status": None,
            "router_status": "not_run",
            "router_error_type": "MissingConfiguration",
            "router_reason": reason,
            "executor_status": "not_run",
            "executor_error_type": None,
        }
        for fixture in fixtures
    ]
    return {
        "fixtures": records,
        "aggregate": _aggregate(records, config),
        "limitation": LIMITATION,
    }


def _aggregate(records: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    total = len(records)
    passed = sum(1 for record in records if record.get("passed") is True)
    failed = total - passed
    inclusion_count = sum(
        1 for record in records if record.get("expected_segment_included") is True
    )
    exact_count = sum(
        1 for record in records if record.get("exact_selection_match") is True
    )
    over_selection_count = sum(
        1 for record in records if record.get("over_selected") is True
    )
    client_success_count = sum(
        1 for record in records if record.get("client_response_success") is True
    )
    original_not_sent_count = sum(
        1 for record in records if record.get("original_request_sent_upstream") is False
    )
    reduced_sent_count = sum(
        1 for record in records if record.get("enabled_request_sent") is True
    )
    return {
        "status": "pass" if failed == 0 else "fail",
        "total_fixtures": total,
        "passed_fixtures": passed,
        "failed_fixtures": failed,
        "expected_inclusion_accuracy": _pct(inclusion_count, total),
        "exact_selection_accuracy": _pct(exact_count, total),
        "over_selection_count": over_selection_count,
        "average_selected_segment_count": _mean_field(records, "selected_segment_count"),
        "average_full_request_estimated_tokens": _mean_field(
            records,
            "full_request_estimated_tokens",
        ),
        "average_reduced_request_estimated_tokens": _mean_field(
            records,
            "reduced_request_estimated_tokens",
        ),
        "average_estimated_reduction_percent": _mean_field(
            records,
            "estimated_reduction_percent",
        ),
        "client_success_count": client_success_count,
        "original_request_not_sent_upstream_count": original_not_sent_count,
        "reduced_request_sent_upstream_count": reduced_sent_count,
        "router_model": config["router_model"],
        "executor_model": config["executor_model"],
        "openai_base_url": config["openai_base_url"],
        "limitation": LIMITATION,
    }


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _mean_field(records: list[dict[str, Any]], key: str) -> float | None:
    values = [
        float(record[key])
        for record in records
        if isinstance(record.get(key), int | float)
    ]
    if not values:
        return None
    return round(mean(values), 2)


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


def _response_preview(response: dict[str, Any] | None) -> str:
    if response is None:
        return ""
    body = response.get("body")
    text = ""
    if isinstance(body, dict):
        choices = body.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    text = message["content"]
    if not text and body is not None:
        text = json.dumps(body, sort_keys=True)
    text = " ".join(text.split())
    return text[:160]


def _print_report(report: dict[str, Any]) -> None:
    aggregate = report["aggregate"]
    print("SFE proxy enabled live OpenAI router multi-fixture runner")
    print(f"status: {aggregate['status']}")
    print(f"total fixtures: {aggregate['total_fixtures']}")
    print(f"passed fixtures: {aggregate['passed_fixtures']}")
    print(f"failed fixtures: {aggregate['failed_fixtures']}")
    print(f"expected inclusion accuracy: {aggregate['expected_inclusion_accuracy']}")
    print(f"exact selection accuracy: {aggregate['exact_selection_accuracy']}")
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
    print(f"router model: {aggregate['router_model']}")
    print(f"executor model: {aggregate['executor_model']}")
    print("fixtures:")
    for record in report["fixtures"]:
        print(
            "- "
            f"{record['fixture_id']}: expected={record['expected_segment_id']} "
            f"selected={record['selected_segment_ids']} "
            f"included={record['expected_segment_included']} "
            f"exact={record['exact_selection_match']} "
            f"over_selected={record['over_selected']} "
            f"full_tokens={record.get('full_request_estimated_tokens')} "
            f"reduced_tokens={record.get('reduced_request_estimated_tokens')} "
            f"reduction={record.get('estimated_reduction_percent')} "
            f"client_status={record.get('client_response_status')} "
            f"router_status={record.get('router_status')} "
            f"router_error={record.get('router_error_type')} "
            f"executor_status={record.get('executor_status')} "
            f"executor_error={record.get('executor_error_type')} "
            f"preview={record.get('client_response_preview')!r}"
        )
    print(f"limitation: {aggregate['limitation']}")


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
    openai_base_url: str,
    api_key: str,
    shadow_log_dir: str,
    timeout_seconds: float,
    logs: list[str],
) -> Any:
    proxy = create_server(
        ProxyConfig(
            host="127.0.0.1",
            port=_free_port(),
            upstream_base_url=_proxy_upstream_base_url(openai_base_url),
            upstream_api_key=api_key,
            mode="enabled",
            shadow_log_dir=shadow_log_dir,
            shadow_log_full_payloads=True,
            shadow_min_input_tokens=1,
            shadow_selection_dry_run=True,
            shadow_router_dry_run=True,
            shadow_router_provider="openai",
            shadow_router_timeout_seconds=max(1, int(timeout_seconds)),
        ),
        log_sink=logs.append,
    )
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    return proxy


def _proxy_upstream_base_url(openai_base_url: str) -> str:
    stripped = openai_base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(stripped)
    if parsed.path.rstrip("/") == "/v1":
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "", parsed.query, parsed.fragment)
        ).rstrip("/")
    return stripped


def _request_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
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
        body = exc.read().decode("utf-8", errors="replace")
        try:
            decoded: Any = json.loads(body) if body else {}
        except json.JSONDecodeError:
            decoded = {"error": {"message": body[:300]}}
        return {
            "status": exc.code,
            "body": decoded,
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


if __name__ == "__main__":
    raise SystemExit(main())
