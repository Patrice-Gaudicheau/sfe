"""Backend adapter stubs for the SFE-aware TUI."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from .contracts import SFEContract


DETERMINISTIC_PREVIEW_MODE = "deterministic_preview"
MAX_PREVIEW_SEGMENTS = 3


@dataclass(frozen=True)
class BackendResult:
    backend: str
    status: str
    provider_calls_made: int
    summary: dict[str, object]
    contract: SFEContract


class BackendAdapter(Protocol):
    name: str

    def dry_run(self, contract: SFEContract) -> BackendResult:
        ...

    def run(self, contract: SFEContract) -> BackendResult:
        ...


class DirectBackend:
    name = "direct"

    def dry_run(self, contract: SFEContract) -> BackendResult:
        return _deterministic_preview_result(self.name, contract)

    def run(self, contract: SFEContract) -> BackendResult:
        raise NotImplementedError("Direct backend execution is not implemented yet.")


class ProxyBackend:
    name = "proxy"

    def dry_run(self, contract: SFEContract) -> BackendResult:
        return _dry_run_result(self.name, contract, selector_mode="proxy_not_connected")

    def run(self, contract: SFEContract) -> BackendResult:
        raise NotImplementedError("Proxy backend execution is not implemented yet.")


def backend_by_name(name: str) -> BackendAdapter:
    normalized = name.strip().lower()
    if normalized == "direct":
        return DirectBackend()
    if normalized == "proxy":
        return ProxyBackend()
    raise ValueError("unsupported_backend")


def _deterministic_preview_result(name: str, contract: SFEContract) -> BackendResult:
    eligible = [
        segment
        for segment in contract.context_segments
        if segment.reducible and bool(segment.text)
    ]
    selected = eligible[:MAX_PREVIEW_SEGMENTS]
    selected_ids = [segment.id for segment in selected]
    input_tokens = sum(segment.approx_tokens for segment in contract.context_segments)
    selected_tokens = sum(segment.approx_tokens for segment in selected)
    reduction_pct = _estimated_reduction_pct(input_tokens, selected_tokens)
    fallback_reason = None if selected else "no_reducible_context_segments"
    audit = {
        **contract.audit,
        "selected_segment_ids": selected_ids,
        "selector_mode": DETERMINISTIC_PREVIEW_MODE,
        "router_mode": DETERMINISTIC_PREVIEW_MODE,
        "fallback_reason": fallback_reason,
        "input_segment_count": len(contract.context_segments),
        "eligible_segment_count": len(eligible),
        "selected_segment_count": len(selected),
        "estimated_input_tokens": input_tokens,
        "estimated_selected_tokens": selected_tokens,
        "estimated_reduction_pct": reduction_pct,
        "provider_calls_made": 0,
    }
    updated = replace(contract, audit=audit)
    return _dry_run_result(
        name,
        updated,
        selector_mode=DETERMINISTIC_PREVIEW_MODE,
    )


def _dry_run_result(
    name: str,
    contract: SFEContract,
    *,
    selector_mode: str,
) -> BackendResult:
    return BackendResult(
        backend=name,
        status="dry_run_only",
        provider_calls_made=0,
        summary={
            "context_segment_count": len(contract.context_segments),
            "protected_segment_count": len(contract.protected_segments),
            "reducible_segment_count": contract.metadata["reducible_segment_count"],
            "protected_instruction_count": contract.metadata[
                "protected_instruction_count"
            ],
            "task_present": contract.task is not None,
            "selector_mode": selector_mode,
            "selected_segment_ids": contract.audit.get("selected_segment_ids", []),
            "fallback_reason": contract.audit.get("fallback_reason"),
            "input_segment_count": contract.audit.get("input_segment_count"),
            "eligible_segment_count": contract.audit.get("eligible_segment_count"),
            "selected_segment_count": contract.audit.get("selected_segment_count"),
            "estimated_input_tokens": contract.audit.get("estimated_input_tokens"),
            "estimated_selected_tokens": contract.audit.get("estimated_selected_tokens"),
            "estimated_reduction_pct": contract.audit.get("estimated_reduction_pct"),
        },
        contract=contract,
    )


def _estimated_reduction_pct(
    input_tokens: int,
    selected_tokens: int,
) -> float | None:
    if input_tokens <= 0:
        return None
    return round((1 - (selected_tokens / input_tokens)) * 100, 2)
