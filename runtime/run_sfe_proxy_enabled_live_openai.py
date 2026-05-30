"""Run one controlled live OpenAI validation for proxy mode=\"enabled\"."""

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
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import DEFAULT_BASE_URL as OPENAI_DEFAULT_BASE_URL
from sfe_proxy.config import ProxyConfig
from sfe_proxy.server import create_server
from sfe_proxy.shadow_router import _reset_provider_call_state


EXPECTED_SEGMENT_ID = "segment-3"
FIXTURE_ID = "tariff_policy_enabled_live_openai"
USEFUL_MARKER = "UTILITY-RATE-SCHEDULE-DELTA-17"
DISTRACTOR_MARKERS_BY_SEGMENT = {
    "segment-2": "CAFETERIA-BADGE-ROTATION-ALPHA",
    "segment-4": "WAREHOUSE-PALLET-LABEL-BETA",
    "segment-5": "SUPPORT-TICKET-ALIAS-GAMMA",
}
QUESTION_TEXT = (
    "Using the active utility tariff memo only, reply with only the battery "
    "dispatch threshold value for the evening peak interval."
)
LIMITATION = (
    "Controlled single-fixture OpenAI enabled-mode validation. The proxy uses "
    "provider-neutral deterministic selection, sends the reduced request to "
    "OpenAI, and returns the reduced-path response to the client. Anthropic is "
    "not tested here, and production readiness is not claimed."
)


def main() -> int:
    args = _parse_args()
    _reset_provider_call_state()

    config = _openai_config()
    payload = _build_payload(config["executor_model"])
    if not config["api_key_set"]:
        report = _configuration_error_report(config, "missing_OPENAI_API_KEY")
        _print_summary(report["summary"])
        _maybe_write_json(args.json, report)
        return 1
    if not config["executor_model"]:
        report = _configuration_error_report(
            config,
            "missing_SFE_OPENAI_EXECUTOR_MODEL",
        )
        _print_summary(report["summary"])
        _maybe_write_json(args.json, report)
        return 1

    response: dict[str, Any] | None = None
    event: dict[str, Any] | None = None
    request_error: BaseException | None = None
    logs: list[str] = []
    with tempfile.TemporaryDirectory(
        prefix="sfe_proxy_enabled_live_openai_"
    ) as shadow_log_dir:
        proxy = _start_proxy(
            openai_base_url=config["openai_base_url"],
            api_key=os.environ["OPENAI_API_KEY"],
            shadow_log_dir=shadow_log_dir,
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

    summary = _build_summary(
        payload=payload,
        response=response,
        event=event,
        request_error=request_error,
        config=config,
    )
    report = {
        "summary": summary,
        "selected_segments": (event or {}).get("enabled_selected_segments_metadata")
        or [],
        "enabled_candidate_request_metadata": {
            "selected_segment_ids": summary["selected_segment_ids"],
            "full_request_estimated_tokens": summary[
                "full_request_estimated_tokens"
            ],
            "reduced_request_estimated_tokens": summary[
                "reduced_request_estimated_tokens"
            ],
            "estimated_reduction_percent": summary["estimated_reduction_percent"],
        },
        "limitation": LIMITATION,
    }
    _print_summary(summary)
    _maybe_write_json(args.json, report)
    return 0 if summary["passed"] else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one controlled live OpenAI validation for proxy mode=\"enabled\"."
    )
    parser.add_argument("--json", type=Path, help="Optional path for a JSON report.")
    return parser.parse_args()


def _openai_config() -> dict[str, Any]:
    base_url = os.getenv("OPENAI_BASE_URL") or OPENAI_DEFAULT_BASE_URL
    timeout_seconds = 60.0
    return {
        "api_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "openai_base_url": base_url.rstrip("/"),
        "proxy_upstream_base_url": _proxy_upstream_base_url(base_url),
        "timeout_seconds": timeout_seconds,
        "router_model": os.getenv("SFE_OPENAI_ROUTER_MODEL") or "",
        "executor_model": os.getenv("SFE_OPENAI_EXECUTOR_MODEL") or "",
        "routing_provider": "provider_neutral_deterministic_selection",
    }


def _proxy_upstream_base_url(openai_base_url: str) -> str:
    stripped = openai_base_url.rstrip("/")
    parsed = urllib.parse.urlsplit(stripped)
    if parsed.path.rstrip("/") == "/v1":
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, "", parsed.query, parsed.fragment)
        ).rstrip("/")
    return stripped


def _build_payload(executor_model: str) -> dict[str, Any]:
    distractor_a = (
        "SEGMENT A - archived cafeteria operations. "
        "CAFETERIA-BADGE-ROTATION-ALPHA describes badge color rotation, "
        "break-room inventory, and coffee machine cleaning windows. "
    ) * 4
    useful_segment = (
        "SEGMENT C - active utility tariff memo. "
        "UTILITY-RATE-SCHEDULE-DELTA-17 sets the battery dispatch threshold at "
        "42 kilowatts during the evening peak interval. "
    ) * 9
    distractor_b = (
        "SEGMENT B - historical logistics notes. "
        "WAREHOUSE-PALLET-LABEL-BETA covers dock assignments, pallet labels, "
        "and carrier calls. "
    ) * 4
    distractor_c = (
        "SEGMENT D - unrelated support transcript. "
        "SUPPORT-TICKET-ALIAS-GAMMA discusses login retries, email aliases, "
        "and ticket tags. "
    ) * 4
    return {
        "model": executor_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Answer from the supplied segments. Keep the answer as "
                    "short as possible."
                ),
            },
            {"role": "user", "content": distractor_a},
            {"role": "user", "content": useful_segment},
            {"role": "user", "content": distractor_b},
            {"role": "user", "content": distractor_c},
            {"role": "user", "content": QUESTION_TEXT},
        ],
        "stream": False,
        "temperature": 0,
        "max_tokens": 24,
    }


def _configuration_error_report(
    config: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    summary = _base_summary(config)
    summary.update(
        {
            "status": "configuration_error",
            "passed": False,
            "routing_status": "not_run",
            "routing_error_type": "MissingConfiguration",
            "routing_reason": reason,
        }
    )
    return {"summary": summary, "limitation": LIMITATION}


def _build_summary(
    *,
    payload: dict[str, Any],
    response: dict[str, Any] | None,
    event: dict[str, Any] | None,
    request_error: BaseException | None,
    config: dict[str, Any],
) -> dict[str, Any]:
    event = event or {}
    selected_ids = event.get("enabled_selected_segment_ids")
    selected_segment_ids = selected_ids if isinstance(selected_ids, list) else []
    expected_included = EXPECTED_SEGMENT_ID in selected_segment_ids
    exact_selection_match = selected_segment_ids == [EXPECTED_SEGMENT_ID]
    over_selected_segment_ids = [
        segment_id
        for segment_id in selected_segment_ids
        if segment_id != EXPECTED_SEGMENT_ID
    ]
    over_selected = expected_included and bool(over_selected_segment_ids)
    candidate_request = event.get("enabled_candidate_request")
    candidate_text = (
        json.dumps(candidate_request, sort_keys=True)
        if isinstance(candidate_request, dict)
        else ""
    )
    reduced_built = event.get("enabled_candidate_built") is True
    reduced_contains_expected = USEFUL_MARKER in candidate_text
    reduced_excludes_unselected = _candidate_excludes_unselected_markers(
        candidate_text,
        selected_segment_ids,
    )
    client_response_status = response.get("status") if response is not None else None
    client_response_success = (
        isinstance(client_response_status, int)
        and 200 <= client_response_status < 300
    )
    enabled_request_sent = event.get("enabled_request_sent") is True
    original_request_sent_upstream = event.get("enabled_original_request_sent")
    original_request_not_sent = original_request_sent_upstream is False
    response_preview = _response_preview(response)
    routing_status = event.get("selection_status")
    routing_error_type = event.get("selection_error_type")
    router_metadata_usable = (
        bool(selected_segment_ids)
        and routing_error_type is None
        and event.get("enabled_candidate_built") is True
    )
    passed = (
        config["api_key_set"] is True
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

    summary = _base_summary(config)
    summary.update(
        {
            "status": status,
            "passed": passed,
            "expected_segment_id": EXPECTED_SEGMENT_ID,
            "selected_segment_ids": selected_segment_ids,
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
            "client_response_preview": response_preview,
            "routing_status": routing_status,
            "routing_reason": event.get("selection_reason"),
            "routing_error_type": routing_error_type,
            "router_metadata_usable": router_metadata_usable,
            "request_error_type": type(request_error).__name__
            if request_error
            else None,
            "request_error": str(request_error) if request_error else None,
            "original_payload_model": payload.get("model"),
        }
    )
    return summary


def _base_summary(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "not_run",
        "passed": False,
        "fixture_id": FIXTURE_ID,
        "openai_base_url": config["openai_base_url"],
        "routing_provider": config["routing_provider"],
        "router_model": config["router_model"],
        "executor_model": config["executor_model"],
        "timeout_seconds": config["timeout_seconds"],
        "limitation": LIMITATION,
        "expected_segment_id": EXPECTED_SEGMENT_ID,
        "selected_segment_ids": [],
        "expected_segment_included": False,
        "exact_selection_match": False,
        "over_selected": False,
        "full_request_estimated_tokens": None,
        "reduced_request_estimated_tokens": None,
        "estimated_reduction_percent": None,
        "enabled_request_sent": False,
        "original_request_sent_upstream": None,
        "client_response_status": None,
        "client_response_preview": "",
    }


def _candidate_excludes_unselected_markers(
    candidate_text: str,
    selected_segment_ids: list[str],
) -> bool:
    selected = set(selected_segment_ids)
    for segment_id, marker in DISTRACTOR_MARKERS_BY_SEGMENT.items():
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


def _print_summary(summary: dict[str, Any]) -> None:
    print("SFE proxy enabled live OpenAI runner")
    print(f"status: {summary['status']}")
    print(f"fixture id: {summary['fixture_id']}")
    print(f"OpenAI base URL: {summary['openai_base_url']}")
    print(f"routing provider: {summary['routing_provider']}")
    print(f"router model: {summary['router_model']}")
    print(f"executor/upstream model: {summary['executor_model']}")
    print(f"timeout seconds: {summary['timeout_seconds']}")
    print(f"expected segment ID: {summary['expected_segment_id']}")
    print(f"selected segment IDs: {summary['selected_segment_ids']}")
    print(f"expected segment included: {summary['expected_segment_included']}")
    print(f"exact selection match: {summary['exact_selection_match']}")
    print(f"over-selected: {summary['over_selected']}")
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
    print(f"enabled request sent: {summary['enabled_request_sent']}")
    print(
        "original request sent upstream: "
        f"{summary['original_request_sent_upstream']}"
    )
    print(f"client response status: {summary['client_response_status']}")
    print(f"routing status: {summary.get('routing_status')}")
    print(f"routing reason: {summary.get('routing_reason')}")
    print(f"routing error type: {summary.get('routing_error_type')}")
    print(f"client response preview: {summary['client_response_preview']}")
    print(f"limitation: {summary['limitation']}")


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
