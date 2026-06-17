"""LLM verifier/governor for bounded Real Loop workspace_write retries."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Protocol

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
from providers.codexcli import (
    DEFAULT_ROUTER_MODEL as DEFAULT_CODEXCLI_ROUTER_MODEL,
    CodexCLIProvider,
)
from providers.google import (
    DEFAULT_MODEL as DEFAULT_GOOGLE_MODEL,
    GoogleAPIError,
    GoogleAPIProvider,
    MissingGoogleAPIKeyError,
)
from providers.lemonade import LemonadeProvider, LemonadeProviderError
from providers.ollama import (
    DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL,
    OllamaProvider,
    OllamaProviderError,
)
from providers.openai_api import (
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
    MissingOpenAIAPIKeyError,
    OpenAIAPIError,
    OpenAIAPIProvider,
)
from sfe.execution_mode_router import DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL
from sfe.provider_config import (
    CODEXCLI_SFE_PROVIDER,
    OLLAMA_SFE_PROVIDER,
    resolve_sfe_verifier_provider,
)
from sfe.provider_progress import ProviderCallIdleTimeoutError


REAL_LOOP_VERIFIER_SCHEMA_VERSION = "sfe.real_loop.governor.v1"
REAL_LOOP_VERDICTS = frozenset({"pass", "needs_retry", "blocked", "abort"})
REAL_LOOP_CONFIDENCE_LEVELS = frozenset({"low", "medium", "high"})
REAL_LOOP_PROGRESS_LEVELS = frozenset({"none", "minor", "meaningful", "unknown"})
DEFAULT_REAL_LOOP_VERIFIER_MAX_TOKENS = 1600
REAL_LOOP_VERIFIER_SYSTEM_INSTRUCTION = (
    "You are the SFE Real Loop verifier and loop governor. Return exactly one "
    "strict JSON object and no Markdown. Compare the final workspace state "
    "against the original user task. Decide whether the result satisfies the "
    "task, whether retry is possible, whether retry is worth spending tokens "
    "on, whether progress has stalled, and whether you can provide a materially "
    "useful targeted correction task for the executor. Do not claim formal, "
    "deterministic, guaranteed, or proven correctness. If retry is useful, "
    "executor_retry_task must be a focused correction task, not a repetition "
    "of the original task."
)


@dataclass(frozen=True)
class RealLoopVerifierDecision:
    schema_version: str
    verdict: str
    confidence: str
    satisfied_requirements: tuple[str, ...]
    missing_or_failed_requirements: tuple[str, ...]
    progress_since_previous_iteration: str
    repeated_failure: bool
    retry_worthwhile: bool
    failure_category: str | None
    detected_issues: tuple[str, ...]
    correction_objective: str | None
    executor_retry_task: str | None
    files_or_areas_to_focus: tuple[str, ...]
    reason: str
    stop_reason: str | None
    provider_name: str | None = None
    model: str | None = None
    provider_calls_made: int = 0


@dataclass(frozen=True)
class RealLoopVerifierRequest:
    original_task: str
    current_task: str
    attempt_index: int
    max_iterations: int
    previous_retry_tasks: tuple[str, ...]
    previous_failure_categories: tuple[str, ...]
    run_result: dict[str, object]
    workspace_snapshot: dict[str, object]


@dataclass(frozen=True)
class RealLoopVerifierIssue:
    category: str
    reason: str
    provider_name: str | None = None
    model: str | None = None
    provider_calls_made: int = 0
    diagnostics: dict[str, object] | None = None


@dataclass(frozen=True)
class RealLoopVerifierResponse:
    decision: RealLoopVerifierDecision | None
    issue: RealLoopVerifierIssue | None = None
    raw_answer: str | None = None


class RealLoopVerifierError(RuntimeError):
    def __init__(self, category: str, reason: str) -> None:
        self.category = category
        self.reason = reason
        super().__init__(reason)


class RealLoopVerifier(Protocol):
    provider_name: str | None
    model: str | None

    def is_available(self) -> bool:
        ...

    def verify(self, request: RealLoopVerifierRequest) -> RealLoopVerifierResponse:
        ...


class ConfiguredLLMRealLoopVerifier:
    def __init__(
        self,
        *,
        provider: Any,
        provider_name: str,
        model: str,
        call_style: str,
        max_tokens: int = DEFAULT_REAL_LOOP_VERIFIER_MAX_TOKENS,
        missing_key_errors: tuple[type[Exception], ...] = (),
        provider_error_types: tuple[type[Exception], ...] = (),
        provider_error_classifier: Callable[[Exception], str | None] | None = None,
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model = model
        self.call_style = call_style
        self.max_tokens = max_tokens
        self.missing_key_errors = missing_key_errors
        self.provider_error_types = provider_error_types
        self.provider_error_classifier = provider_error_classifier

    def is_available(self) -> bool:
        try:
            health = self.provider.health()
        except Exception:
            return False
        return bool(isinstance(health, dict) and health.get("ok"))

    def verify(self, request: RealLoopVerifierRequest) -> RealLoopVerifierResponse:
        health = self.provider.health()
        if not health.get("ok"):
            return self._issue("verifier_not_configured", provider_calls_made=0)
        try:
            response = _call_provider_chat(
                provider=self.provider,
                call_style=self.call_style,
                user_prompt=build_real_loop_verifier_prompt(request),
                model=self.model,
                max_tokens=self.max_tokens,
            )
        except self.missing_key_errors:
            return self._issue("verifier_not_configured", provider_calls_made=0)
        except ProviderCallIdleTimeoutError:
            return self._issue("verifier_provider_idle_timeout", provider_calls_made=1)
        except TimeoutError:
            return self._issue("verifier_timeout", provider_calls_made=1)
        except self.provider_error_types:
            return self._issue("verifier_provider_error", provider_calls_made=1)
        except LemonadeProviderError as exc:
            return self._issue(f"verifier_{exc.error_category}", provider_calls_made=1)
        except OllamaProviderError as exc:
            return self._issue(f"verifier_{exc.error_category}", provider_calls_made=1)
        except Exception as exc:
            return self._issue(
                _classify_provider_error(exc, self.provider_error_classifier),
                provider_calls_made=1,
            )

        answer = _extract_answer(response)
        if not answer:
            return self._issue("invalid_verifier_response", provider_calls_made=1)
        try:
            decision = parse_real_loop_verifier_json(answer)
        except RealLoopVerifierError as exc:
            return RealLoopVerifierResponse(
                decision=None,
                issue=RealLoopVerifierIssue(
                    exc.category,
                    exc.reason,
                    provider_name=self.provider_name,
                    model=self.model,
                    provider_calls_made=1,
                    diagnostics={
                        "schema_validation_reason": exc.reason,
                        "raw_answer_preview": _safe_verifier_output_preview(answer),
                    },
                ),
                raw_answer=answer,
            )
        return RealLoopVerifierResponse(
            decision=RealLoopVerifierDecision(
                **{
                    **decision.__dict__,
                    "provider_name": self.provider_name,
                    "model": self.model,
                    "provider_calls_made": 1,
                }
            ),
            raw_answer=answer,
        )

    def _issue(
        self,
        reason: str,
        *,
        provider_calls_made: int,
    ) -> RealLoopVerifierResponse:
        return RealLoopVerifierResponse(
            decision=None,
            issue=RealLoopVerifierIssue(
                "real_loop_verifier",
                reason,
                provider_name=self.provider_name,
                model=self.model,
                provider_calls_made=provider_calls_made,
            ),
        )


class ProviderConfigurationErrorRealLoopVerifier:
    provider_name = "invalid"
    model = None

    def is_available(self) -> bool:
        return False

    def verify(self, request: RealLoopVerifierRequest) -> RealLoopVerifierResponse:
        del request
        return RealLoopVerifierResponse(
            None,
            RealLoopVerifierIssue(
                "real_loop_verifier",
                "provider_configuration_error",
                provider_name=self.provider_name,
            ),
        )


class UnsupportedProviderRealLoopVerifier:
    model = None

    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    def is_available(self) -> bool:
        return False

    def verify(self, request: RealLoopVerifierRequest) -> RealLoopVerifierResponse:
        del request
        return RealLoopVerifierResponse(
            None,
            RealLoopVerifierIssue(
                "real_loop_verifier",
                "verifier_provider_not_supported",
                provider_name=self.provider_name,
            ),
        )


def create_configured_real_loop_verifier(
    *,
    environ: Mapping[str, str] | None = None,
    provider_factories: Mapping[str, Any] | None = None,
    max_tokens: int | None = None,
) -> RealLoopVerifier:
    try:
        provider_name = resolve_sfe_verifier_provider(environ, default="openai")
    except ValueError:
        return ProviderConfigurationErrorRealLoopVerifier()

    factory = _provider_factory_for(provider_name, provider_factories)
    tokens = max_tokens or resolve_real_loop_verifier_max_tokens(environ)
    common = {"max_tokens": tokens}
    if provider_name in ("openai", "openai-compatible"):
        return ConfiguredLLMRealLoopVerifier(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                ("SFE_OPENAI_VERIFIER_MODEL", "SFE_OPENAI_ROUTER_MODEL"),
            )
            or DEFAULT_OPENAI_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingOpenAIAPIKeyError,),
            provider_error_types=(OpenAIAPIError,),
            **common,
        )
    if provider_name == CODEXCLI_SFE_PROVIDER:
        return ConfiguredLLMRealLoopVerifier(
            provider=_instantiate_codexcli_provider(
                provider_name,
                factory,
                provider_factories,
                environ,
            ),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                ("SFE_CODEXCLI_VERIFIER_MODEL", "SFE_CODEXCLI_ROUTER_MODEL"),
            )
            or DEFAULT_CODEXCLI_ROUTER_MODEL,
            call_style="system_instruction",
            **common,
        )
    if provider_name == "lemonade":
        return ConfiguredLLMRealLoopVerifier(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                (
                    "SFE_LEMONADE_VERIFIER_MODEL",
                    "SFE_ROUTER_MODEL",
                    "SFE_LEMONADE_MODEL",
                ),
            )
            or DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL,
            call_style="system_message",
            provider_error_classifier=_classify_lemonade_error,
            **common,
        )
    if provider_name == "alibaba":
        return ConfiguredLLMRealLoopVerifier(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                ("SFE_ALIBABA_VERIFIER_MODEL", "SFE_ALIBABA_ROUTER_MODEL"),
            )
            or DEFAULT_ALIBABA_ROUTER_MODEL,
            call_style="system_message",
            missing_key_errors=(MissingAlibabaAPIKeyError,),
            provider_error_types=(AlibabaAPIError,),
            **common,
        )
    if provider_name == "anthropic":
        return ConfiguredLLMRealLoopVerifier(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                ("SFE_ANTHROPIC_VERIFIER_MODEL", "SFE_ANTHROPIC_ROUTER_MODEL"),
            )
            or DEFAULT_ANTHROPIC_ROUTER_MODEL,
            call_style="system_instruction",
            missing_key_errors=(MissingAnthropicAPIKeyError,),
            provider_error_types=(AnthropicAPIError,),
            **common,
        )
    if provider_name == "google":
        return ConfiguredLLMRealLoopVerifier(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                ("SFE_GOOGLE_VERIFIER_MODEL", "SFE_GOOGLE_MODEL"),
            )
            or DEFAULT_GOOGLE_MODEL,
            call_style="system_message",
            missing_key_errors=(MissingGoogleAPIKeyError,),
            provider_error_types=(GoogleAPIError,),
            **common,
        )
    if provider_name == OLLAMA_SFE_PROVIDER:
        return ConfiguredLLMRealLoopVerifier(
            provider=factory(),
            provider_name=provider_name,
            model=_first_env_value(
                environ,
                (
                    "SFE_OLLAMA_VERIFIER_MODEL",
                    "SFE_OLLAMA_ROUTER_MODEL",
                    "SFE_OLLAMA_MODEL",
                ),
            )
            or DEFAULT_OLLAMA_MODEL,
            call_style="system_message",
            provider_error_classifier=_classify_ollama_error,
            **common,
        )
    return UnsupportedProviderRealLoopVerifier(provider_name)


def resolve_real_loop_verifier_max_tokens(
    environ: Mapping[str, str] | None = None,
) -> int:
    env = os.environ if environ is None else environ
    value = env.get("SFE_REAL_LOOP_VERIFIER_MAX_TOKENS")
    if value is None or not value.strip():
        return DEFAULT_REAL_LOOP_VERIFIER_MAX_TOKENS
    try:
        parsed = int(value.strip())
    except ValueError:
        return DEFAULT_REAL_LOOP_VERIFIER_MAX_TOKENS
    return parsed if parsed > 0 else DEFAULT_REAL_LOOP_VERIFIER_MAX_TOKENS


def build_real_loop_verifier_prompt(request: RealLoopVerifierRequest) -> str:
    payload = {
        "schema_version": REAL_LOOP_VERIFIER_SCHEMA_VERSION,
        "original_task": request.original_task,
        "current_task": request.current_task,
        "attempt_index": request.attempt_index,
        "max_iterations": request.max_iterations,
        "previous_retry_tasks": list(request.previous_retry_tasks),
        "previous_failure_categories": list(request.previous_failure_categories),
        "run_result": request.run_result,
        "workspace_snapshot": request.workspace_snapshot,
        "required_output_schema": {
            "schema_version": REAL_LOOP_VERIFIER_SCHEMA_VERSION,
            "verdict": "pass|needs_retry|blocked|abort",
            "confidence": "low|medium|high",
            "satisfied_requirements": ["string"],
            "missing_or_failed_requirements": ["string"],
            "progress_since_previous_iteration": "none|minor|meaningful|unknown",
            "repeated_failure": False,
            "retry_worthwhile": False,
            "failure_category": None,
            "detected_issues": ["string"],
            "correction_objective": None,
            "executor_retry_task": None,
            "files_or_areas_to_focus": ["string"],
            "reason": "short explanation",
            "stop_reason": None,
        },
        "hard_rules": [
            "Return strict JSON only.",
            "Do not claim deterministic, proven, guaranteed, or formal correctness.",
            "Use needs_retry only when retry is worthwhile and executor_retry_task is materially useful.",
            "executor_retry_task must target only missing or failed requirements.",
            "Use abort when progress has stalled or retry would waste tokens.",
            "workspace_snapshot.inspected_root is the exact root inspected for this verdict.",
            "workspace_snapshot.workspace_files is a bounded recursive file listing; do not report files as missing when they appear there.",
            "For modular JavaScript projects, accept recursive src/**/*.js files unless the task explicitly requires files directly under src/.",
        ],
    }
    return (
        "Verify and govern this SFE Real Loop workspace_write attempt. Return "
        "strict JSON only.\n\nReal Loop verification payload JSON:\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
    )


def parse_real_loop_verifier_json(output: str) -> RealLoopVerifierDecision:
    parse_errors: list[RealLoopVerifierError] = []
    for candidate in _json_object_candidates(output):
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        try:
            return _parse_real_loop_verifier_object(payload)
        except RealLoopVerifierError as exc:
            parse_errors.append(exc)
    if parse_errors:
        raise parse_errors[-1]
    raise RealLoopVerifierError(
        "invalid_verifier_response",
        "verifier did not return valid JSON",
    )


def _parse_real_loop_verifier_object(payload: Any) -> RealLoopVerifierDecision:
    if not isinstance(payload, dict):
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier JSON was not an object",
        )
    schema_version = _required_string(payload, "schema_version")
    if schema_version != REAL_LOOP_VERIFIER_SCHEMA_VERSION:
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier schema_version was invalid",
        )
    verdict = _required_string(payload, "verdict")
    confidence = _required_string(payload, "confidence")
    progress = _required_string(payload, "progress_since_previous_iteration")
    if verdict not in REAL_LOOP_VERDICTS:
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier verdict was invalid",
        )
    if confidence not in REAL_LOOP_CONFIDENCE_LEVELS:
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier confidence was invalid",
        )
    if progress not in REAL_LOOP_PROGRESS_LEVELS:
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier progress_since_previous_iteration was invalid",
        )
    repeated_failure = payload.get("repeated_failure")
    retry_worthwhile = payload.get("retry_worthwhile")
    if not isinstance(repeated_failure, bool):
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier repeated_failure was invalid",
        )
    if not isinstance(retry_worthwhile, bool):
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier retry_worthwhile was invalid",
        )
    failure_category = _optional_string(payload, "failure_category")
    correction_objective = _optional_string(payload, "correction_objective")
    executor_retry_task = _optional_string(payload, "executor_retry_task")
    stop_reason = _optional_string(payload, "stop_reason")
    decision = RealLoopVerifierDecision(
        schema_version=schema_version,
        verdict=verdict,
        confidence=confidence,
        satisfied_requirements=_string_tuple(payload.get("satisfied_requirements")),
        missing_or_failed_requirements=_string_tuple(
            payload.get("missing_or_failed_requirements")
        ),
        progress_since_previous_iteration=progress,
        repeated_failure=repeated_failure,
        retry_worthwhile=retry_worthwhile,
        failure_category=failure_category,
        detected_issues=_string_tuple(payload.get("detected_issues")),
        correction_objective=correction_objective,
        executor_retry_task=executor_retry_task,
        files_or_areas_to_focus=_string_tuple(payload.get("files_or_areas_to_focus")),
        reason=_required_string(payload, "reason"),
        stop_reason=stop_reason,
    )
    _validate_verdict_contract(decision)
    return decision


def _validate_verdict_contract(decision: RealLoopVerifierDecision) -> None:
    if decision.verdict == "pass":
        if decision.retry_worthwhile or decision.executor_retry_task is not None:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                "pass verdict cannot request retry",
            )
        if not decision.stop_reason:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                "pass verdict requires stop_reason",
            )
        return
    if decision.verdict == "needs_retry":
        if not decision.retry_worthwhile:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                "needs_retry verdict requires retry_worthwhile",
            )
        if not decision.detected_issues:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                "needs_retry verdict requires detected_issues",
            )
        if not decision.correction_objective:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                "needs_retry verdict requires correction_objective",
            )
        if not decision.executor_retry_task:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                "needs_retry verdict requires executor_retry_task",
            )
        return
    if decision.verdict in {"blocked", "abort"}:
        if decision.retry_worthwhile or decision.executor_retry_task is not None:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                f"{decision.verdict} verdict cannot request retry",
            )
        if not decision.stop_reason:
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                f"{decision.verdict} verdict requires stop_reason",
            )


def _safe_verifier_output_preview(output: str, limit: int = 500) -> str:
    preview = " ".join(output.replace("\x00", "").split())
    preview = _redact_secret_like(preview)
    return preview[:limit]


def _redact_secret_like(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("api_key", "apikey", "token", "secret")):
        return "[redacted]"
    return text


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            f"verifier {key} was invalid",
        )
    return value.strip()


def _optional_string(payload: Mapping[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            f"verifier {key} was invalid",
        )
    return value.strip()


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RealLoopVerifierError(
            "invalid_verifier_response",
            "verifier list field was invalid",
        )
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise RealLoopVerifierError(
                "invalid_verifier_response",
                "verifier list item was invalid",
            )
        items.append(item.strip())
    return tuple(items)


def _call_provider_chat(
    *,
    provider: Any,
    call_style: str,
    user_prompt: str,
    model: str,
    max_tokens: int,
) -> dict[str, Any]:
    if call_style == "system_message":
        return provider.chat(
            [
                {"role": "system", "content": REAL_LOOP_VERIFIER_SYSTEM_INSTRUCTION},
                {"role": "user", "content": user_prompt},
            ],
            model=model,
            max_tokens=max_tokens,
            temperature=None,
            provider_role="verifier",
        )
    return provider.chat(
        [{"role": "user", "content": user_prompt}],
        model=model,
        max_tokens=max_tokens,
        temperature=None,
        system_instruction=REAL_LOOP_VERIFIER_SYSTEM_INSTRUCTION,
        provider_role="verifier",
    )


def _extract_answer(response: object) -> str:
    if not isinstance(response, dict):
        return ""
    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"]).strip()
    return ""


def _json_object_candidates(output: str) -> list[str]:
    text = _strip_json_fence(output)
    candidates = [text, *_balanced_json_objects(text)]
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        stripped = candidate.strip()
        if stripped and stripped not in seen:
            unique.append(stripped)
            seen.add(stripped)
    return unique


def _strip_json_fence(output: str) -> str:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _balanced_json_objects(text: str) -> list[str]:
    objects: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(text[start : index + 1])
                start = None
    return objects


def _provider_factory_for(
    provider_name: str,
    provider_factories: Mapping[str, Any] | None,
) -> Any:
    if provider_factories and provider_name in provider_factories:
        return provider_factories[provider_name]
    if provider_name in ("openai", "openai-compatible"):
        return OpenAIAPIProvider
    if provider_name == CODEXCLI_SFE_PROVIDER:
        return CodexCLIProvider
    if provider_name == "lemonade":
        return LemonadeProvider
    if provider_name == "alibaba":
        return AlibabaAPIProvider
    if provider_name == "anthropic":
        return AnthropicProvider
    if provider_name == "google":
        return GoogleAPIProvider
    if provider_name == OLLAMA_SFE_PROVIDER:
        return OllamaProvider
    return lambda: None


def _instantiate_codexcli_provider(
    provider_name: str,
    factory: Any,
    provider_factories: Mapping[str, Any] | None,
    environ: Mapping[str, str] | None,
) -> Any:
    if provider_factories and provider_name in provider_factories:
        return factory()
    return factory(
        reasoning_effort=_first_env_value(
            environ,
            (
                "SFE_CODEXCLI_VERIFIER_EFFORT",
                "SFE_CODEXCLI_ROUTER_EFFORT",
                "SFE_CODEXCLI_REASONING_EFFORT",
            ),
        )
    )


def _classify_provider_error(
    exc: Exception,
    classifier: Callable[[Exception], str | None] | None,
) -> str:
    if classifier is None:
        return "verifier_provider_error"
    return classifier(exc) or "verifier_provider_error"


def _classify_lemonade_error(exc: Exception) -> str | None:
    if isinstance(exc, LemonadeProviderError):
        return f"verifier_{exc.error_category}"
    return None


def _classify_ollama_error(exc: Exception) -> str | None:
    if isinstance(exc, OllamaProviderError):
        return f"verifier_{exc.error_category}"
    return None


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
