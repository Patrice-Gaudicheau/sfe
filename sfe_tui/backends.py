"""Backend adapter stubs for the SFE-aware TUI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import SFEContract


@dataclass(frozen=True)
class BackendResult:
    backend: str
    status: str
    provider_calls_made: int
    summary: dict[str, object]


class BackendAdapter(Protocol):
    name: str

    def dry_run(self, contract: SFEContract) -> BackendResult:
        ...

    def run(self, contract: SFEContract) -> BackendResult:
        ...


class DirectBackend:
    name = "direct"

    def dry_run(self, contract: SFEContract) -> BackendResult:
        return _dry_run_result(self.name, contract)

    def run(self, contract: SFEContract) -> BackendResult:
        raise NotImplementedError("Direct backend execution is not implemented yet.")


class ProxyBackend:
    name = "proxy"

    def dry_run(self, contract: SFEContract) -> BackendResult:
        return _dry_run_result(self.name, contract)

    def run(self, contract: SFEContract) -> BackendResult:
        raise NotImplementedError("Proxy backend execution is not implemented yet.")


def backend_by_name(name: str) -> BackendAdapter:
    normalized = name.strip().lower()
    if normalized == "direct":
        return DirectBackend()
    if normalized == "proxy":
        return ProxyBackend()
    raise ValueError("unsupported_backend")


def _dry_run_result(name: str, contract: SFEContract) -> BackendResult:
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
        },
    )
