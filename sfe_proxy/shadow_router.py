"""Provider-neutral contract for future SFE proxy shadow router dry-runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


DISABLED_ROUTER_PROVIDER = "disabled"


@dataclass(frozen=True)
class ShadowRouterInput:
    """Safe metadata for router dry-runs, never raw prompts, headers, or responses."""

    request_id: str
    endpoint: str
    model: str | None
    rough_estimated_input_tokens: int
    candidate_segments_metadata: list[dict[str, Any]]
    eligibility_metadata: dict[str, Any]
    request_body_bytes: int
    stream: bool | None


@dataclass(frozen=True)
class ShadowRouterResult:
    """JSON-compatible router dry-run result fields for shadow observations."""

    router_enabled: bool
    router_name: str
    router_status: str
    router_reason: str
    router_latency_ms: int
    candidate_selected_segment_ids: list[str] = field(default_factory=list)
    estimated_router_selected_input_tokens: int | None = None
    estimated_router_token_reduction_pct: float | None = None
    error_type: str | None = None
    dry_run_only: bool = True

    def to_event_fields(self, provider: str) -> dict[str, Any]:
        return {
            "shadow_router_enabled": self.router_enabled,
            "shadow_router_provider": provider,
            "shadow_router_name": self.router_name,
            "shadow_router_status": self.router_status,
            "shadow_router_reason": self.router_reason,
            "shadow_router_latency_ms": self.router_latency_ms,
            "shadow_router_candidate_selected_segment_ids": self.candidate_selected_segment_ids,
            "shadow_router_estimated_selected_input_tokens": (
                self.estimated_router_selected_input_tokens
            ),
            "shadow_router_estimated_token_reduction_pct": (
                self.estimated_router_token_reduction_pct
            ),
            "shadow_router_error_type": self.error_type,
            "shadow_router_dry_run_only": self.dry_run_only,
        }


class ShadowRouter(Protocol):
    name: str

    def analyze(self, router_input: ShadowRouterInput) -> ShadowRouterResult:
        """Return shadow router dry-run metadata without changing proxy behavior."""


class DisabledShadowRouter:
    name = DISABLED_ROUTER_PROVIDER

    def analyze(self, router_input: ShadowRouterInput) -> ShadowRouterResult:
        return ShadowRouterResult(
            router_enabled=False,
            router_name=self.name,
            router_status="disabled",
            router_reason="shadow_router_provider_disabled",
            router_latency_ms=0,
        )


def create_shadow_router(provider: str) -> ShadowRouter:
    if provider == DISABLED_ROUTER_PROVIDER:
        return DisabledShadowRouter()
    raise ValueError(
        f"Unsupported shadow router provider {provider!r}; supported providers: disabled."
    )
