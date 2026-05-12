"""Provider-neutral contract for future SFE proxy shadow router dry-runs."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol

from .provider_limits import ProviderLimitRegistry

DISABLED_ROUTER_PROVIDER = "disabled"
LEMONADE_ROUTER_PROVIDER = "lemonade"
DEFAULT_LEMONADE_ROUTER_BASE_URL = "http://127.0.0.1:13305"
DEFAULT_LEMONADE_ROUTER_TIMEOUT_SECONDS = 30
DEFAULT_LEMONADE_ROUTER_MAX_OUTPUT_TOKENS = 160


@dataclass(frozen=True)
class ShadowRouterInput:
    """Router dry-run input. Text segments are for explicit local providers only."""

    request_id: str
    endpoint: str
    model: str | None
    rough_estimated_input_tokens: int
    candidate_segments_metadata: list[dict[str, Any]]
    eligibility_metadata: dict[str, Any]
    request_body_bytes: int
    stream: bool | None
    candidate_text_segments: list[dict[str, Any]] = field(default_factory=list)


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
    rate_limit_decision: dict[str, object] | None = None
    confidence: float | None = None
    error_type: str | None = None
    dry_run_only: bool = True

    def to_event_fields(self, provider: str) -> dict[str, Any]:
        fields: dict[str, Any] = {
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
        if self.rate_limit_decision is not None:
            fields["shadow_router_rate_limit_decision"] = self.rate_limit_decision
        if self.confidence is not None:
            fields["shadow_router_confidence"] = self.confidence
        return fields


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


@dataclass(frozen=True)
class LemonadeShadowRouterConfig:
    base_url: str = DEFAULT_LEMONADE_ROUTER_BASE_URL
    model: str = ""
    timeout_seconds: int = DEFAULT_LEMONADE_ROUTER_TIMEOUT_SECONDS
    max_output_tokens: int = DEFAULT_LEMONADE_ROUTER_MAX_OUTPUT_TOKENS


class LemonadeShadowRouter:
    name = LEMONADE_ROUTER_PROVIDER

    def __init__(
        self,
        config: LemonadeShadowRouterConfig,
        limit_registry: ProviderLimitRegistry | None = None,
    ) -> None:
        self.config = config
        self.limit_registry = limit_registry or ProviderLimitRegistry.from_env()

    def analyze(self, router_input: ShadowRouterInput) -> ShadowRouterResult:
        started = time.perf_counter()
        if router_input.eligibility_metadata.get("sfe_routing_eligible") is not True:
            return ShadowRouterResult(
                router_enabled=True,
                router_name=self.name,
                router_status="not_eligible",
                router_reason="sfe_routing_eligible_false",
                router_latency_ms=_elapsed_ms(started),
            )
        limit_decision = self._limit_decision(router_input)
        if not limit_decision.allowed:
            return ShadowRouterResult(
                router_enabled=True,
                router_name=self.name,
                router_status="rate_limited",
                router_reason=limit_decision.reason,
                router_latency_ms=_elapsed_ms(started),
                rate_limit_decision=limit_decision.to_metadata(),
            )
        _record_provider_call(self.name)

        try:
            response = self._call_lemonade(router_input)
            content = _extract_chat_content(response)
            parsed = json.loads(content)
            return self._parse_result(parsed, router_input, started, limit_decision.to_metadata())
        except json.JSONDecodeError:
            return self._failure(
                started,
                "invalid_output",
                "lemonade_router_invalid_json",
                "JSONDecodeError",
                limit_decision.to_metadata(),
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._failure(
                started,
                "invalid_output",
                "lemonade_router_malformed_result",
                type(exc).__name__,
                limit_decision.to_metadata(),
            )
        except TimeoutError as exc:
            return self._failure(
                started,
                "provider_error",
                "lemonade_router_timeout",
                type(exc).__name__,
                limit_decision.to_metadata(),
            )
        except (urllib.error.URLError, OSError, RuntimeError) as exc:
            return self._failure(
                started,
                "provider_error",
                "lemonade_router_provider_error",
                type(exc).__name__,
                limit_decision.to_metadata(),
            )

    def _limit_decision(self, router_input: ShadowRouterInput):
        limiter = self.limit_registry.limiter_for(LEMONADE_ROUTER_PROVIDER)
        state = _provider_state(self.name)
        now_ms = _monotonic_ms()
        recent = [stamp for stamp in state["recent_request_ms"] if now_ms - stamp < 60000]
        state["recent_request_ms"] = recent
        last_request_ms = state.get("last_request_ms")
        elapsed_ms = None if last_request_ms is None else now_ms - int(last_request_ms)
        return limiter.decide(
            estimated_input_tokens=router_input.rough_estimated_input_tokens,
            elapsed_since_last_request_ms=elapsed_ms,
            requests_in_last_minute=len(recent),
        )

    def _call_lemonade(self, router_input: ShadowRouterInput) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an SFE proxy shadow router dry-run. Return strict JSON only. "
                        "Select candidate segment ids using only the provided extracted text "
                        "segments and metadata. This is dry-run analysis only."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(_safe_router_prompt_metadata(router_input), sort_keys=True),
                },
            ],
            "max_tokens": self.config.max_output_tokens,
            "temperature": 0,
        }
        request = urllib.request.Request(
            _join_openai_compatible_url(self.config.base_url.rstrip("/"), "/v1/chat/completions"),
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            body = response.read().decode("utf-8")
        if not body:
            raise ValueError("empty Lemonade router response")
        decoded = json.loads(body)
        if not isinstance(decoded, dict):
            raise ValueError("Lemonade router response must be a JSON object")
        return decoded

    def _parse_result(
        self,
        parsed: Any,
        router_input: ShadowRouterInput,
        started: float,
        rate_limit_metadata: dict[str, object],
    ) -> ShadowRouterResult:
        if not isinstance(parsed, dict):
            raise ValueError("router result must be a JSON object")
        status = parsed["router_status"]
        reason = parsed["router_reason"]
        selected_ids = parsed["candidate_selected_segment_ids"]
        selected_tokens = parsed["estimated_router_selected_input_tokens"]
        reduction_pct = parsed["estimated_router_token_reduction_pct"]
        dry_run_only = parsed["dry_run_only"]
        confidence = parsed.get("confidence")
        if not isinstance(status, str):
            raise ValueError("router_status must be a string")
        if not isinstance(reason, str):
            raise ValueError("router_reason must be a string")
        if not isinstance(selected_ids, list) or not all(isinstance(item, str) for item in selected_ids):
            raise ValueError("candidate_selected_segment_ids must be a list of strings")
        allowed_ids = _known_segment_ids(router_input)
        unknown_ids = [item for item in selected_ids if item not in allowed_ids]
        if unknown_ids:
            raise ValueError("candidate_selected_segment_ids contains unknown segment ids")
        if selected_tokens is not None and (not isinstance(selected_tokens, int) or selected_tokens < 0):
            raise ValueError("estimated_router_selected_input_tokens must be a non-negative integer or null")
        if reduction_pct is not None and not isinstance(reduction_pct, int | float):
            raise ValueError("estimated_router_token_reduction_pct must be numeric or null")
        if dry_run_only is not True:
            raise ValueError("dry_run_only must be true")
        if confidence is not None and not isinstance(confidence, int | float):
            raise ValueError("confidence must be numeric or null")
        return ShadowRouterResult(
            router_enabled=True,
            router_name=self.name,
            router_status=status,
            router_reason=reason,
            router_latency_ms=_elapsed_ms(started),
            candidate_selected_segment_ids=selected_ids,
            estimated_router_selected_input_tokens=selected_tokens,
            estimated_router_token_reduction_pct=(
                round(float(reduction_pct), 2) if reduction_pct is not None else None
            ),
            rate_limit_decision=rate_limit_metadata,
            confidence=round(float(confidence), 4) if confidence is not None else None,
        )

    def _failure(
        self,
        started: float,
        status: str,
        reason: str,
        error_type: str,
        rate_limit_metadata: dict[str, object],
    ) -> ShadowRouterResult:
        return ShadowRouterResult(
            router_enabled=True,
            router_name=self.name,
            router_status=status,
            router_reason=reason,
            router_latency_ms=_elapsed_ms(started),
            rate_limit_decision=rate_limit_metadata,
            error_type=error_type,
        )


def create_shadow_router(
    provider: str,
    *,
    config: Any | None = None,
    limit_registry: ProviderLimitRegistry | None = None,
) -> ShadowRouter:
    if provider == DISABLED_ROUTER_PROVIDER:
        return DisabledShadowRouter()
    if provider == LEMONADE_ROUTER_PROVIDER:
        lemonade_config = LemonadeShadowRouterConfig(
            base_url=getattr(config, "lemonade_router_base_url", DEFAULT_LEMONADE_ROUTER_BASE_URL),
            model=getattr(config, "lemonade_router_model", ""),
            timeout_seconds=getattr(
                config,
                "lemonade_router_timeout_seconds",
                DEFAULT_LEMONADE_ROUTER_TIMEOUT_SECONDS,
            ),
            max_output_tokens=getattr(
                config,
                "lemonade_router_max_output_tokens",
                DEFAULT_LEMONADE_ROUTER_MAX_OUTPUT_TOKENS,
            ),
        )
        return LemonadeShadowRouter(lemonade_config, limit_registry=limit_registry)
    raise ValueError(
        f"Unsupported shadow router provider {provider!r}; supported providers: disabled, lemonade."
    )


def _safe_router_prompt_metadata(router_input: ShadowRouterInput) -> dict[str, Any]:
    return {
        "request_id": router_input.request_id,
        "endpoint": router_input.endpoint,
        "model": router_input.model,
        "rough_estimated_input_tokens": router_input.rough_estimated_input_tokens,
        "candidate_segments": router_input.candidate_text_segments,
        "eligibility_metadata": router_input.eligibility_metadata,
        "request_body_bytes": router_input.request_body_bytes,
        "stream": router_input.stream,
        "instruction": (
            "Choose candidate segment ids from candidate_segments. Return JSON with "
            "router_status, router_reason, candidate_selected_segment_ids, "
            "estimated_router_selected_input_tokens, "
            "estimated_router_token_reduction_pct, confidence, and dry_run_only=true."
        ),
    }


def _known_segment_ids(router_input: ShadowRouterInput) -> set[str]:
    ids: set[str] = set()
    for segment in router_input.candidate_text_segments:
        segment_id = segment.get("segment_id")
        if isinstance(segment_id, str):
            ids.add(segment_id)
    for segment in router_input.candidate_segments_metadata:
        segment_id = segment.get("segment_id")
        if isinstance(segment_id, str):
            ids.add(segment_id)
    return ids


def _extract_chat_content(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Lemonade response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("Lemonade response choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("Lemonade response missing message")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Lemonade response content must be a string")
    return content


def _join_openai_compatible_url(base_url: str, path: str) -> str:
    if base_url.endswith("/v1") and path.startswith("/v1/"):
        return f"{base_url}{path.removeprefix('/v1')}"
    return f"{base_url}{path}"


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _monotonic_ms() -> int:
    return int(time.monotonic() * 1000)


_PROVIDER_CALL_STATE: dict[str, dict[str, Any]] = {}


def _provider_state(provider: str) -> dict[str, Any]:
    return _PROVIDER_CALL_STATE.setdefault(
        provider,
        {"last_request_ms": None, "recent_request_ms": []},
    )


def _record_provider_call(provider: str) -> None:
    now_ms = _monotonic_ms()
    state = _provider_state(provider)
    state["last_request_ms"] = now_ms
    recent = [stamp for stamp in state["recent_request_ms"] if now_ms - stamp < 60000]
    recent.append(now_ms)
    state["recent_request_ms"] = recent


def _reset_provider_call_state() -> None:
    _PROVIDER_CALL_STATE.clear()
