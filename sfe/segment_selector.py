"""Provider-backed segment selection for neutral SFE contexts."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

from providers.alibaba import (
    DEFAULT_ROUTER_MODEL as DEFAULT_ALIBABA_ROUTER_MODEL,
    AlibabaAPIError,
    AlibabaAPIProvider,
    MissingAlibabaAPIKeyError,
)
from providers.anthropic import (
    DEFAULT_ROUTER_MODEL as DEFAULT_ANTHROPIC_ROUTER_MODEL,
    AnthropicAPIError,
    AnthropicProvider,
    MissingAnthropicAPIKeyError,
)
from providers.google import (
    DEFAULT_MODEL as DEFAULT_GOOGLE_MODEL,
    GoogleAPIError,
    GoogleAPIProvider,
    MissingGoogleAPIKeyError,
)
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from runtime.metrics import estimate_text_tokens, percent_reduction
from runtime.run_experiment import _extract_response_text, _extract_token_usage
from sfe.provider_config import normalize_provider_name, resolve_sfe_provider
from sfe.provider_progress import ProviderCallIdleTimeoutError


SEGMENT_SELECTOR_MODE = "sfe_segment_selector"
SEGMENT_SELECTOR_MAX_TOKENS = 220
SUPPORTED_SEGMENT_SELECTOR_PROVIDERS = ("openai", "anthropic", "alibaba", "google")
KNOWN_SEGMENT_SELECTION_STATUSES = frozenset(
    {
        "approved",
        "candidate_selected",
        "eligible",
        "ok",
        "ready",
        "selected",
        "select_segments",
        "success",
    }
)
SEGMENT_SELECTOR_SYSTEM_INSTRUCTION = (
    "You are the neutral SFE segment selector. Select only candidate segment IDs "
    "that are needed to answer the task. Return exactly one JSON object. Do not "
    "return Markdown, code fences, prose, or hidden reasoning."
)


@dataclass(frozen=True)
class CandidateSegment:
    id: str
    source: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SegmentSelectionInput:
    request_id: str
    task: str
    output_contract: str
    candidate_segments: tuple[CandidateSegment, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    model: str | None = None


@dataclass(frozen=True)
class SegmentSelectionResult:
    selected_segment_ids: tuple[str, ...]
    router_status: str | None
    router_status_known: bool | None
    reason: str
    provider_name: str | None = None
    model: str | None = None
    confidence: float | None = None
    error_type: str | None = None
    latency_ms: int | None = None
    estimated_selected_input_tokens: int | None = None
    estimated_token_reduction_pct: float | None = None
    provider_usage: dict[str, int | None] | None = None

    @property
    def selection_usable(self) -> bool:
        return (
            self.error_type is None
            and bool(self.selected_segment_ids)
        )


class SegmentSelectionError(RuntimeError):
    def __init__(self, category: str, reason: str) -> None:
        self.category = category
        self.reason = reason
        super().__init__(reason)


class SegmentSelector(Protocol):
    provider_name: str | None
    model: str | None

    def select(self, selection_input: SegmentSelectionInput) -> SegmentSelectionResult:
        ...


ProviderFactory = Callable[[], Any]


class ProviderBackedSegmentSelector:
    def __init__(
        self,
        *,
        provider: Any,
        provider_name: str,
        model: str,
        max_tokens: int = SEGMENT_SELECTOR_MAX_TOKENS,
        missing_key_errors: tuple[type[Exception], ...] = (),
        provider_error_types: tuple[type[Exception], ...] = (),
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.max_tokens = int(max_tokens)
        self.missing_key_errors = missing_key_errors
        self.provider_error_types = provider_error_types

    def select(self, selection_input: SegmentSelectionInput) -> SegmentSelectionResult:
        started = time.perf_counter()
        prompt = build_segment_selection_prompt(selection_input)
        response: dict[str, Any] = {}
        output = ""
        if not self._provider_available():
            return _selection_failure(
                selection_input,
                provider_name=self.provider_name,
                model=self.model,
                started=started,
                reason="configured segment selector is not available",
                error_type="SegmentSelectorNotConfigured",
            )
        try:
            response = self.provider.chat(
                [{"role": "user", "content": prompt}],
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=0.0,
                system_instruction=SEGMENT_SELECTOR_SYSTEM_INSTRUCTION,
            )
            output = _extract_response_text(response)
            parsed = parse_segment_selection_output(
                output,
                candidate_ids={segment.id for segment in selection_input.candidate_segments},
            )
        except self.missing_key_errors:
            return _selection_failure(
                selection_input,
                provider_name=self.provider_name,
                model=self.model,
                started=started,
                reason="configured segment selector is not available",
                error_type="MissingAPIKey",
                response=response,
                prompt=prompt,
                output=output,
            )
        except ProviderCallIdleTimeoutError:
            return _selection_failure(
                selection_input,
                provider_name=self.provider_name,
                model=self.model,
                started=started,
                reason="segment selector provider stopped producing progress",
                error_type="ProviderCallIdleTimeoutError",
                response=response,
                prompt=prompt,
                output=output,
            )
        except TimeoutError:
            return _selection_failure(
                selection_input,
                provider_name=self.provider_name,
                model=self.model,
                started=started,
                reason="segment selector provider timed out",
                error_type="TimeoutError",
                response=response,
                prompt=prompt,
                output=output,
            )
        except self.provider_error_types as exc:
            return _selection_failure(
                selection_input,
                provider_name=self.provider_name,
                model=self.model,
                started=started,
                reason="segment selector provider failed",
                error_type=type(exc).__name__,
                response=response,
                prompt=prompt,
                output=output,
            )
        except SegmentSelectionError as exc:
            return _selection_failure(
                selection_input,
                provider_name=self.provider_name,
                model=self.model,
                started=started,
                reason=exc.reason,
                error_type=exc.category,
                response=response,
                prompt=prompt,
                output=output,
                router_status=exc.category,
            )
        except Exception as exc:  # noqa: BLE001
            return _selection_failure(
                selection_input,
                provider_name=self.provider_name,
                model=self.model,
                started=started,
                reason="segment selector provider failed",
                error_type=type(exc).__name__,
                response=response,
                prompt=prompt,
                output=output,
            )

        selected_tokens = _estimated_tokens_for_ids(
            selection_input,
            parsed.selected_segment_ids,
        )
        total_tokens = sum(
            estimate_text_tokens(segment.text) for segment in selection_input.candidate_segments
        )
        return SegmentSelectionResult(
            selected_segment_ids=parsed.selected_segment_ids,
            router_status=parsed.router_status,
            router_status_known=_status_known(parsed.router_status),
            reason=parsed.reason,
            provider_name=self.provider_name,
            model=self.model,
            confidence=parsed.confidence,
            error_type=None,
            latency_ms=_elapsed_ms(started),
            estimated_selected_input_tokens=selected_tokens,
            estimated_token_reduction_pct=percent_reduction(total_tokens, selected_tokens),
            provider_usage=_extract_token_usage(response, prompt, output),
        )

    def _provider_available(self) -> bool:
        health = self.provider.health() if hasattr(self.provider, "health") else {"ok": True}
        return bool(health.get("ok"))


def create_configured_segment_selector(
    *,
    provider_name: str | None = None,
    model: str | None = None,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, ProviderFactory] | None = None,
    max_tokens: int = SEGMENT_SELECTOR_MAX_TOKENS,
) -> SegmentSelector:
    resolved_provider = _resolve_segment_selector_provider(provider_name, environ)
    if resolved_provider not in SUPPORTED_SEGMENT_SELECTOR_PROVIDERS:
        raise SegmentSelectionError(
            "segment_selector_provider_not_supported",
            "configured segment selector provider is not supported",
        )
    provider_factory = _provider_factory_for(
        resolved_provider,
        provider_factories=provider_factories,
    )
    return ProviderBackedSegmentSelector(
        provider=provider_factory(),
        provider_name=resolved_provider,
        model=model or _default_router_model(resolved_provider, environ),
        max_tokens=max_tokens,
        missing_key_errors=_missing_key_errors(resolved_provider),
        provider_error_types=_provider_error_types(resolved_provider),
    )


@dataclass(frozen=True)
class _ParsedSegmentSelection:
    selected_segment_ids: tuple[str, ...]
    router_status: str | None
    reason: str
    confidence: float | None


def parse_segment_selection_output(
    output: str,
    *,
    candidate_ids: set[str] | frozenset[str],
) -> _ParsedSegmentSelection:
    try:
        parsed = json.loads(strip_json_fence(output))
    except json.JSONDecodeError as exc:
        raise SegmentSelectionError(
            "invalid_segment_selection_response",
            "segment selector did not return valid JSON",
        ) from exc
    if not isinstance(parsed, dict):
        raise SegmentSelectionError(
            "invalid_segment_selection_response",
            "segment selector JSON was not an object",
        )
    raw_selected = (
        parsed.get("selected_segment_ids")
        if "selected_segment_ids" in parsed
        else parsed.get("candidate_selected_segment_ids")
    )
    if not isinstance(raw_selected, list):
        raise SegmentSelectionError(
            "invalid_segment_selection_response",
            "segment selector selected IDs were invalid",
        )
    if not all(isinstance(item, str) for item in raw_selected):
        raise SegmentSelectionError(
            "invalid_segment_selection_response",
            "segment selector selected IDs must contain only strings",
        )
    selected_ids = tuple(raw_selected)
    if not selected_ids:
        raise SegmentSelectionError(
            "segment_selection_empty",
            "segment selector returned no selected IDs",
        )
    unknown_ids = [segment_id for segment_id in selected_ids if segment_id not in candidate_ids]
    if unknown_ids:
        raise SegmentSelectionError(
            "segment_selection_unknown_ids",
            "segment selector returned unknown selected IDs",
        )
    status = parsed.get("router_status")
    if status is not None and not isinstance(status, str):
        raise SegmentSelectionError(
            "invalid_segment_selection_response",
            "segment selector status was invalid",
        )
    reason = str(parsed.get("router_reason") or parsed.get("reason") or "").strip()
    if not reason:
        reason = "segment_selector_selected_context"
    confidence = _coerce_confidence(parsed.get("confidence"))
    return _ParsedSegmentSelection(
        selected_segment_ids=selected_ids,
        router_status=status,
        reason=reason,
        confidence=confidence,
    )


def build_segment_selection_prompt(selection_input: SegmentSelectionInput) -> str:
    payload = {
        "request_id": selection_input.request_id,
        "task": selection_input.task,
        "output_contract": selection_input.output_contract,
        "metadata": selection_input.metadata,
        "candidate_segments": [
            {
                "id": segment.id,
                "source": segment.source,
                "text": segment.text,
                "metadata": segment.metadata,
                "estimated_tokens": estimate_text_tokens(segment.text),
            }
            for segment in selection_input.candidate_segments
        ],
        "required_output_schema": {
            "router_status": "diagnostic status string",
            "router_reason": "short explanation",
            "selected_segment_ids": ["candidate id copied exactly"],
            "estimated_selected_input_tokens": "integer or null",
            "estimated_token_reduction_pct": "number or null",
            "confidence": "number from 0 to 1 or null",
        },
    }
    return (
        "Select the candidate segments needed to answer the task from the supplied "
        "candidate text. Return strict JSON only.\n\nSegment selection payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def strip_json_fence(output: str) -> str:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _resolve_segment_selector_provider(
    provider_name: str | None,
    environ: Mapping[str, str] | None,
) -> str:
    if provider_name is not None:
        return normalize_provider_name(provider_name)
    return resolve_sfe_provider(environ, default="openai")


def _default_router_model(provider_name: str, environ: Mapping[str, str] | None) -> str:
    if provider_name in ("openai", "openai-compatible"):
        return _first_env_value(environ, ("SFE_OPENAI_ROUTER_MODEL",)) or DEFAULT_OPENAI_ROUTER_MODEL
    if provider_name == "anthropic":
        return _first_env_value(environ, ("SFE_ANTHROPIC_ROUTER_MODEL",)) or DEFAULT_ANTHROPIC_ROUTER_MODEL
    if provider_name == "alibaba":
        return _first_env_value(environ, ("SFE_ALIBABA_ROUTER_MODEL",)) or DEFAULT_ALIBABA_ROUTER_MODEL
    if provider_name == "google":
        return _first_env_value(environ, ("SFE_GOOGLE_MODEL",)) or DEFAULT_GOOGLE_MODEL
    raise SegmentSelectionError(
        "segment_selector_provider_not_supported",
        "configured segment selector provider is not supported",
    )


def _provider_factory_for(
    provider_name: str,
    *,
    provider_factories: Mapping[str, ProviderFactory] | None,
) -> ProviderFactory:
    if provider_factories and provider_name in provider_factories:
        return provider_factories[provider_name]
    if provider_name in ("openai", "openai-compatible"):
        return OpenAIAPIProvider
    if provider_name == "anthropic":
        return AnthropicProvider
    if provider_name == "alibaba":
        return AlibabaAPIProvider
    if provider_name == "google":
        return GoogleAPIProvider
    return lambda: None


def _missing_key_errors(provider_name: str) -> tuple[type[Exception], ...]:
    if provider_name in ("openai", "openai-compatible"):
        return (MissingOpenAIAPIKeyError,)
    if provider_name == "anthropic":
        return (MissingAnthropicAPIKeyError,)
    if provider_name == "alibaba":
        return (MissingAlibabaAPIKeyError,)
    if provider_name == "google":
        return (MissingGoogleAPIKeyError,)
    return ()


def _provider_error_types(provider_name: str) -> tuple[type[Exception], ...]:
    if provider_name in ("openai", "openai-compatible"):
        return (OpenAIAPIError,)
    if provider_name == "anthropic":
        return (AnthropicAPIError,)
    if provider_name == "alibaba":
        return (AlibabaAPIError,)
    if provider_name == "google":
        return (GoogleAPIError,)
    return ()


def _first_env_value(
    environ: Mapping[str, str] | None,
    names: tuple[str, ...],
) -> str | None:
    env = os.environ if environ is None else environ
    for name in names:
        value = env.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _selection_failure(
    selection_input: SegmentSelectionInput,
    *,
    provider_name: str | None,
    model: str | None,
    started: float,
    reason: str,
    error_type: str,
    response: dict[str, Any] | None = None,
    prompt: str | None = None,
    output: str = "",
    router_status: str | None = None,
) -> SegmentSelectionResult:
    usage = None
    if response is not None and prompt is not None:
        usage = _extract_token_usage(response, prompt, output)
    return SegmentSelectionResult(
        selected_segment_ids=(),
        router_status=router_status or "error",
        router_status_known=False,
        reason=reason,
        provider_name=provider_name,
        model=model,
        confidence=None,
        error_type=error_type,
        latency_ms=_elapsed_ms(started),
        estimated_selected_input_tokens=None,
        estimated_token_reduction_pct=None,
        provider_usage=usage,
    )


def _estimated_tokens_for_ids(
    selection_input: SegmentSelectionInput,
    selected_ids: tuple[str, ...],
) -> int:
    selected = set(selected_ids)
    return sum(
        estimate_text_tokens(segment.text)
        for segment in selection_input.candidate_segments
        if segment.id in selected
    )


def _status_known(status: str | None) -> bool | None:
    if status is None:
        return None
    return status in KNOWN_SEGMENT_SELECTION_STATUSES


def _coerce_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
