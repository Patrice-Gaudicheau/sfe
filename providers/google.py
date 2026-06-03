"""Google Gemini OpenAI-compatible provider for benchmark calls."""

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


PROVIDER_NAME = "google"
API_STYLE = "openai_compatible_chat"
DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_MODEL = "gemini-2.5-flash-lite"
DEFAULT_TIMEOUT = 60


class MissingGoogleAPIKeyError(RuntimeError):
    """Raised when a Google API call is attempted without credentials."""


class GoogleAPIError(RuntimeError):
    """Raised with sanitized Google API error diagnostics."""

    def __init__(self, diagnostics: dict[str, Any]) -> None:
        self.diagnostics = dict(diagnostics)
        super().__init__(_format_api_error(self.diagnostics))


class GoogleAPIProvider:
    """Small standard-library client for Gemini's OpenAI-compatible endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("GOOGLE_API_KEY")
        self.base_url = (
            base_url or os.getenv("SFE_GOOGLE_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        timeout_value = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.timeout = float(timeout_value)
        if self.timeout <= 0:
            raise ValueError("Google API timeout must be greater than 0.")

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
        """Send one OpenAI-compatible Chat Completions request."""
        if not self.api_key:
            raise MissingGoogleAPIKeyError(_missing_api_key_message())

        started = time.perf_counter()
        supervisor = ProviderCallSupervisor(
            provider=PROVIDER_NAME,
            model=model,
            progress_sink=progress_sink,
        )
        supervisor.start(
            {
                "base_url": self.base_url,
                "api_style": API_STYLE,
                "max_tokens_requested": max_tokens,
            }
        )
        try:
            raw_response = self._chat_completions_create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                system_instruction=system_instruction,
                supervisor=supervisor,
            )
        except (GoogleAPIError, ProviderCallIdleTimeoutError) as exc:
            supervisor.fail({"error_type": type(exc).__name__})
            raise
        except Exception as exc:
            supervisor.fail({"error_type": type(exc).__name__})
            raise GoogleAPIError(_classify_api_error(exc)) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        normalized = normalize_google_response(raw_response)
        supervisor.complete({"latency_ms": latency_ms})
        return {
            "choices": [{"message": {"content": normalized["content"]}}],
            "usage": normalized["usage"],
            "google_api": {
                "provider": PROVIDER_NAME,
                "model": model,
                "latency_ms": latency_ms,
                "base_url": self.base_url,
                "api_style": API_STYLE,
                "max_tokens_requested": max_tokens,
                "temperature_requested": temperature,
                "api_error_status": None,
                "api_error_type": None,
                "api_error_code": None,
                "api_error_message": None,
                "api_error_retry_count": 0,
                "api_error_attempts": [],
            },
        }

    def _chat_completions_create(
        self,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
        supervisor: ProviderCallSupervisor,
    ) -> dict[str, Any]:
        payload = _chat_completions_payload(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            system_instruction=system_instruction,
        )
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
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
                metadata={"endpoint": "/chat/completions"},
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
                wait_metadata={"provider_call": "google_chat_completions_http"},
            )
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise GoogleAPIError(_classify_http_error(exc.code, details)) from exc
        except urllib.error.URLError as exc:
            raise GoogleAPIError(
                {
                    "api_error_status": None,
                    "api_error_type": "network_error",
                    "api_error_code": "network_error",
                    "api_error_message": _sanitize_error_message(str(exc.reason)),
                    "api_error_retry_count": 0,
                }
            ) from exc


def normalize_google_response(raw_response: Any) -> dict[str, Any]:
    response = _to_plain_data(raw_response)
    return {
        "content": extract_visible_text(response),
        "usage": normalize_usage(response.get("usage")),
    }


def extract_visible_text(response: dict[str, Any]) -> str:
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

    prompt_tokens = _first_int(usage, ("prompt_tokens", "input_tokens"))
    completion_tokens = _first_int(usage, ("completion_tokens", "output_tokens"))
    total_tokens = _first_int(usage, ("total_tokens",))
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _chat_completions_payload(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float | None,
    system_instruction: str | None,
) -> dict[str, Any]:
    payload_messages: list[dict[str, str]] = []
    if system_instruction:
        payload_messages.append({"role": "system", "content": system_instruction})
    payload_messages.extend(
        {
            "role": str(message.get("role") or "user"),
            "content": str(message.get("content") or ""),
        }
        for message in messages
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": payload_messages,
        "max_tokens": max_tokens,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    return payload


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
    if isinstance(exc, GoogleAPIError):
        return dict(exc.diagnostics)
    return {
        "api_error_status": None,
        "api_error_type": "unknown_api_error",
        "api_error_code": "unknown_api_error",
        "api_error_message": _sanitize_error_message(str(exc)),
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
            error_code = str(error.get("code") or error.get("status") or "")
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
    if "invalid_api_key" in marker or "api key" in marker or status == 401:
        return "authentication"
    if status == 403 or "permission" in marker or "forbidden" in marker:
        return "model_access"
    if status == 404 or ("model" in marker and "not" in marker and "found" in marker):
        return "model_access"
    if status == 429 or "rate" in marker or "quota" in marker:
        return "rate_limit"
    if "unsupported" in marker or "invalid" in marker:
        return "unsupported_parameter"
    return "unknown_api_error"


def _sanitize_error_message(message: str, limit: int = 500) -> str:
    sanitized = str(message)
    api_key = os.getenv("GOOGLE_API_KEY")
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    sanitized = re.sub(r"AIza[A-Za-z0-9_-]{20,}", "[REDACTED]", sanitized)
    sanitized = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", sanitized)
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", sanitized)
    sanitized = sanitized.replace("\n", " ").strip()
    if len(sanitized) > limit:
        return sanitized[: limit - 3].rstrip() + "..."
    return sanitized


def _format_api_error(diagnostics: dict[str, Any]) -> str:
    status = diagnostics.get("api_error_status")
    error_type = diagnostics.get("api_error_type") or "unknown_api_error"
    code = diagnostics.get("api_error_code") or error_type
    message = diagnostics.get("api_error_message") or ""
    prefix = f"Google API error {error_type}"
    if status is not None:
        prefix += f" HTTP {status}"
    return f"{prefix} ({code}): {message}".strip()


def _missing_api_key_message() -> str:
    return "GOOGLE_API_KEY is required for provider google."
