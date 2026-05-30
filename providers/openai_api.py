"""Direct OpenAI API provider for clean benchmark measurements."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

from sfe.provider_progress import (
    ProviderCallIdleTimeoutError,
    ProviderCallSupervisor,
    ProviderProgressSink,
)


PROVIDER_NAME = "openai-api"
# Environment-dependent example defaults retained for compatibility with
# existing benchmark tests. Model identifiers are configurable through
# SFE_OPENAI_ROUTER_MODEL and SFE_OPENAI_EXECUTOR_MODEL in the runtime layer.
# These identifiers may depend on the user's account, provider availability, or
# date, so public users should explicitly configure their own model IDs.
DEFAULT_ROUTER_MODEL = "gpt-5.4-nano"
DEFAULT_EXECUTOR_MODEL = "gpt-5.5"
DEFAULT_TIMEOUT = 60
DEFAULT_BASE_URL = "https://api.openai.com/v1"


class MissingOpenAIAPIKeyError(RuntimeError):
    """Raised when a direct OpenAI API call is attempted without credentials."""


class OpenAIAPIError(RuntimeError):
    """Raised with sanitized OpenAI API error diagnostics."""

    def __init__(self, diagnostics: dict[str, Any]) -> None:
        self.diagnostics = dict(diagnostics)
        super().__init__(_format_api_error(self.diagnostics))


class OpenAIAPIProvider:
    """Minimal direct OpenAI Responses API adapter for benchmark calls."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        timeout_value = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.timeout = float(timeout_value)
        if self.timeout <= 0:
            raise ValueError("OpenAI API timeout must be greater than 0.")

    def health(self) -> dict[str, Any]:
        return {
            "ok": bool(self.api_key),
            "provider": PROVIDER_NAME,
            "base_url": self.base_url,
            "error": "" if self.api_key else _missing_api_key_message(),
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 512,
        temperature: float | None = None,
        system_instruction: str | None = None,
        progress_sink: ProviderProgressSink | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Send a minimal direct OpenAI request and normalize the response."""
        if not self.api_key:
            raise MissingOpenAIAPIKeyError(_missing_api_key_message())

        started = time.perf_counter()
        retry_diagnostics: list[dict[str, Any]] = []
        supervisor = ProviderCallSupervisor(
            provider=PROVIDER_NAME,
            model=model,
            progress_sink=progress_sink,
        )
        supervisor.start(
            {
                "base_url": self.base_url,
                "api_style": "openai_responses",
                "max_tokens_requested": max_tokens,
            }
        )
        try:
            raw_response = self._responses_create_with_retries(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_instruction=system_instruction,
                retry_diagnostics=retry_diagnostics,
                supervisor=supervisor,
            )
        except (OpenAIAPIError, ProviderCallIdleTimeoutError) as exc:
            supervisor.fail({"error_type": type(exc).__name__})
            raise
        except Exception as exc:
            supervisor.fail({"error_type": type(exc).__name__})
            diagnostics = _classify_api_error(exc)
            diagnostics["api_error_retry_count"] = len(retry_diagnostics)
            diagnostics["api_error_attempts"] = retry_diagnostics
            raise OpenAIAPIError(diagnostics) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        normalized = normalize_openai_response(raw_response)
        supervisor.complete({"latency_ms": latency_ms})
        retry_count = len(retry_diagnostics)
        last_retry_error = retry_diagnostics[-1] if retry_diagnostics else {}
        return {
            "choices": [{"message": {"content": normalized["content"]}}],
            "usage": normalized["usage"],
            "openai_api": {
                "provider": PROVIDER_NAME,
                "model": model,
                "latency_ms": latency_ms,
                "base_url": self.base_url,
                "max_tokens_requested": max_tokens,
                "temperature_requested": temperature,
                "temperature_sent": _model_supports_temperature(model)
                and temperature is not None,
                "api_error_retry_count": retry_count,
                "api_error_attempts": retry_diagnostics,
                "api_error_status": last_retry_error.get("api_error_status"),
                "api_error_type": last_retry_error.get("api_error_type"),
                "api_error_code": last_retry_error.get("api_error_code"),
                "api_error_message": last_retry_error.get("api_error_message"),
            },
        }

    def _responses_create_with_retries(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
        retry_diagnostics: list[dict[str, Any]],
        supervisor: ProviderCallSupervisor,
    ) -> Any:
        retry_count = 0
        while True:
            try:
                return self._responses_create(
                    model=model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system_instruction=system_instruction,
                    supervisor=supervisor,
                )
            except Exception as exc:
                diagnostics = _classify_api_error(exc)
                diagnostics["api_error_retry_count"] = retry_count
                retry_diagnostics.append(dict(diagnostics))
                if not _should_retry_api_error(diagnostics, retry_count):
                    diagnostics["api_error_retry_count"] = retry_count
                    diagnostics["api_error_attempts"] = retry_diagnostics
                    raise OpenAIAPIError(diagnostics) from exc
                backoff = _retry_backoff_seconds(diagnostics, retry_count)
                supervisor.emit(
                    "retry_scheduled",
                    source="sfe_core",
                    real_provider_signal=False,
                    resets_idle_timer=False,
                    metadata={
                        "retry_count": retry_count + 1,
                        "sleep_seconds": backoff,
                        "api_error_type": diagnostics.get("api_error_type"),
                    },
                )
                time.sleep(backoff)
                retry_count += 1

    def _responses_create(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
        supervisor: ProviderCallSupervisor,
    ) -> Any:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError:
            return self._responses_create_http(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_instruction=system_instruction,
                supervisor=supervisor,
            )

        client_kwargs: dict[str, Any] = {
            "api_key": self.api_key,
            "timeout": max(self.timeout, supervisor.idle_timeout_seconds),
        }
        if self.base_url != DEFAULT_BASE_URL:
            client_kwargs["base_url"] = self.base_url
        client = OpenAI(**client_kwargs)
        request_payload = _responses_payload(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            system_instruction=system_instruction,
        )
        supervisor.emit(
            "request_sent",
            source="openai_sdk",
            real_provider_signal=False,
            resets_idle_timer=False,
            metadata={"endpoint": "responses"},
        )
        return supervisor.run_blocking(
            lambda: client.responses.create(**request_payload),
            wait_metadata={"provider_call": "openai_responses_sdk"},
        )

    def _responses_create_http(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
        supervisor: ProviderCallSupervisor,
    ) -> dict[str, Any]:
        payload = _responses_payload(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            system_instruction=system_instruction,
        )
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            supervisor.emit(
                "request_sent",
                source="http_client",
                real_provider_signal=False,
                resets_idle_timer=False,
                metadata={"endpoint": "/responses"},
            )

            def read_response() -> dict[str, Any]:
                with urllib.request.urlopen(
                    request,
                    timeout=max(self.timeout, supervisor.idle_timeout_seconds),
                ) as response:
                    supervisor.emit(
                        "response_headers",
                        source="http_client",
                        real_provider_signal=True,
                        metadata={"status": getattr(response, "status", None)},
                    )
                    return json.loads(response.read().decode("utf-8"))

            return supervisor.run_blocking(
                read_response,
                wait_metadata={"provider_call": "openai_responses_http"},
            )
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise OpenAIAPIError(_classify_http_error(exc.code, details)) from exc
        except urllib.error.URLError as exc:
            raise OpenAIAPIError(
                {
                    "api_error_status": None,
                    "api_error_type": "network_error",
                    "api_error_code": "network_error",
                    "api_error_message": _sanitize_error_message(str(exc.reason)),
                    "api_error_retry_count": 0,
                }
            ) from exc


def normalize_openai_response(raw_response: Any) -> dict[str, Any]:
    response = _to_plain_data(raw_response)
    return {
        "content": extract_visible_text(response),
        "usage": normalize_usage(response.get("usage")),
    }


def extract_visible_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if output_text is not None:
        text = str(output_text).strip()
        if text:
            return text

    output_parts: list[str] = []
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for content_item in content:
                    if not isinstance(content_item, dict):
                        continue
                    text = content_item.get("text")
                    if text is not None:
                        output_parts.append(str(text))
            text = item.get("text")
            if text is not None:
                output_parts.append(str(text))
    if output_parts:
        return "\n".join(part.strip() for part in output_parts if part.strip()).strip()

    choices = response.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict) and message.get("content") is not None:
                return str(message["content"]).strip()
            if first.get("text") is not None:
                return str(first["text"]).strip()

    return ""


def normalize_usage(raw_usage: Any) -> dict[str, int | None]:
    usage = _to_plain_data(raw_usage)
    if not isinstance(usage, dict):
        usage = {}

    input_tokens = _first_int(usage, ("input_tokens", "prompt_tokens"))
    output_tokens = _first_int(usage, ("output_tokens", "completion_tokens"))
    total_tokens = _first_int(usage, ("total_tokens",))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    return {
        "prompt_tokens": input_tokens,
        "completion_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def _responses_payload(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float | None,
    system_instruction: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model,
        "input": _messages_to_input(messages),
        "max_output_tokens": max_tokens,
    }
    if temperature is not None and _model_supports_temperature(model):
        payload["temperature"] = temperature
    if system_instruction:
        payload["instructions"] = system_instruction
    return payload


def _model_supports_temperature(model: str) -> bool:
    """Return whether the benchmark adapter should send temperature."""
    normalized = model.strip().lower()
    if normalized.startswith("gpt-5."):
        return False
    return True


def _messages_to_input(messages: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [
        {
            "role": str(message.get("role") or "user"),
            "content": str(message.get("content") or ""),
        }
        for message in messages
    ]


def _to_plain_data(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


def _first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return int(value)
    return None


def _classify_api_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, OpenAIAPIError):
        return dict(exc.diagnostics)

    status = getattr(exc, "status_code", None)
    body = _to_plain_data(getattr(exc, "body", None))
    response = getattr(exc, "response", None)
    if body is None and response is not None:
        status = status or getattr(response, "status_code", None)
        try:
            body = response.json()
        except Exception:
            body = getattr(response, "text", None)

    raw_message = str(exc)
    error_type = ""
    error_code = ""
    message = raw_message
    if isinstance(body, dict):
        error = body.get("error", body)
        if isinstance(error, dict):
            error_type = str(error.get("type") or "")
            error_code = str(error.get("code") or error.get("param") or "")
            message = str(error.get("message") or raw_message)

    normalized_type = _classify_error_name(status, error_type, error_code, message)
    return {
        "api_error_status": int(status) if status is not None else None,
        "api_error_type": normalized_type,
        "api_error_code": error_code or normalized_type,
        "api_error_message": _sanitize_error_message(message),
        "api_error_retry_count": 0,
    }


def _classify_http_error(status: int, details: str) -> dict[str, Any]:
    error_type = ""
    error_code = ""
    message = details
    try:
        parsed = json.loads(details)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error", parsed)
        if isinstance(error, dict):
            error_type = str(error.get("type") or "")
            error_code = str(error.get("code") or error.get("param") or "")
            message = str(error.get("message") or details)

    normalized_type = _classify_error_name(status, error_type, error_code, message)
    return {
        "api_error_status": int(status),
        "api_error_type": normalized_type,
        "api_error_code": error_code or normalized_type,
        "api_error_message": _sanitize_error_message(message),
        "api_error_retry_count": 0,
    }


def _classify_error_name(
    status: int | None, error_type: str, error_code: str, message: str
) -> str:
    marker = " ".join((error_type, error_code, message)).lower()
    if "insufficient_quota" in marker or "insufficient quota" in marker:
        return "insufficient_quota"
    if "unsupported" in marker and "temperature" in marker:
        return "unsupported_parameter"
    if "unsupported parameter" in marker:
        return "unsupported_parameter"
    if "invalid_api_key" in marker or "incorrect api key" in marker:
        return "invalid_api_key"
    if status == 401 or "authentication" in marker:
        return "authentication"
    if status == 403 or "model_access" in marker or "permission" in marker:
        return "model_access"
    if status == 429 or any(
        token in marker
        for token in ("rate_limit", "rate limit", "rate_limit_exceeded", "too_many_requests")
    ):
        return "rate_limit"
    return "unknown_api_error"


def _should_retry_api_error(diagnostics: dict[str, Any], retry_count: int) -> bool:
    error_type = diagnostics.get("api_error_type")
    if error_type == "rate_limit":
        return retry_count < 2
    if error_type == "insufficient_quota":
        return retry_count < 1
    return False


def _retry_backoff_seconds(diagnostics: dict[str, Any], retry_count: int) -> float:
    if diagnostics.get("api_error_type") == "insufficient_quota":
        return 0.5
    return min(4.0, 1.0 * (2**retry_count))


def _sanitize_error_message(message: str, limit: int = 500) -> str:
    sanitized = str(message)
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", sanitized)
    sanitized = re.sub(r"Bearer\\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", sanitized)
    sanitized = sanitized.replace("\n", " ").strip()
    if len(sanitized) > limit:
        return sanitized[: limit - 3].rstrip() + "..."
    return sanitized


def _format_api_error(diagnostics: dict[str, Any]) -> str:
    status = diagnostics.get("api_error_status")
    error_type = diagnostics.get("api_error_type") or "unknown_api_error"
    code = diagnostics.get("api_error_code") or error_type
    message = diagnostics.get("api_error_message") or ""
    prefix = f"OpenAI API error {error_type}"
    if status is not None:
        prefix += f" HTTP {status}"
    return f"{prefix} ({code}): {message}".strip()


def _missing_api_key_message() -> str:
    return "OPENAI_API_KEY is required for provider openai-api."
