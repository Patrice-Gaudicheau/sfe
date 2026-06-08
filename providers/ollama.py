"""Minimal Ollama provider using the local Ollama HTTP API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from sfe.provider_progress import (
    ProviderCallIdleTimeoutError,
    ProviderCallSupervisor,
    ProviderProgressSink,
)


PROVIDER_NAME = "ollama"
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen3.5:4b"
DEFAULT_TIMEOUT = 120


class OllamaProviderError(RuntimeError):
    """Sanitized Ollama failure with a safe category for callers."""

    def __init__(self, error_category: str, message: str | None = None) -> None:
        self.error_category = error_category
        self.message = message or error_category
        super().__init__(self.message)


class OllamaProvider:
    """Small standard-library client for a local Ollama server."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (
            base_url or os.getenv("SFE_OLLAMA_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = _resolve_timeout(timeout)

    def health(self) -> dict[str, Any]:
        """Check whether the Ollama server responds to the tags endpoint."""
        try:
            models = self.list_models()
        except Exception as exc:
            return {
                "ok": False,
                "provider": PROVIDER_NAME,
                "base_url": self.base_url,
                "error": str(exc),
            }
        return {
            "ok": True,
            "provider": PROVIDER_NAME,
            "base_url": self.base_url,
            "models_count": len(models),
        }

    def list_models(self) -> list[str]:
        """Return local model names from GET /api/tags."""
        response = self._request("GET", "/api/tags")
        models = response.get("models")
        if not isinstance(models, list):
            raise OllamaProviderError(
                "invalid_response",
                "Ollama /api/tags response did not contain a models list.",
            )
        names: list[str] = []
        for model in models:
            if not isinstance(model, dict):
                continue
            name = model.get("name") or model.get("model")
            if name is not None:
                names.append(str(name))
        return names

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
        """Send a non-streaming Ollama chat request and normalize the response."""
        supervisor = ProviderCallSupervisor(
            provider=PROVIDER_NAME,
            model=model,
            progress_sink=progress_sink,
        )
        supervisor.start(
            {
                "base_url": self.base_url,
                "api_style": "ollama_chat",
                "max_tokens_requested": max_tokens,
            }
        )
        try:
            local_models = self.list_models()
            if model not in local_models:
                raise OllamaProviderError(
                    "model_not_found",
                    (
                        f"Ollama model {model!r} is not available locally. "
                        f"Pull it with: ollama pull {model}"
                    ),
                )
            payload = build_ollama_chat_payload(
                messages=_messages_with_system_instruction(messages, system_instruction),
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            raw_response = self._request("POST", "/api/chat", payload, supervisor)
            normalized = normalize_ollama_chat_response(raw_response)
        except (OllamaProviderError, ProviderCallIdleTimeoutError) as exc:
            supervisor.fail(
                {
                    "error_type": type(exc).__name__,
                    "error_category": getattr(exc, "error_category", None),
                }
            )
            raise
        except Exception as exc:
            supervisor.fail({"error_type": type(exc).__name__})
            raise OllamaProviderError(
                "provider_error",
                "Ollama provider failed while calling the local server.",
            ) from exc
        supervisor.complete()
        return normalized

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        supervisor: ProviderCallSupervisor | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        local_supervisor = supervisor or ProviderCallSupervisor(
            provider=PROVIDER_NAME,
            model=None,
        )
        try:
            local_supervisor.emit(
                "request_sent",
                source="http_client",
                real_provider_signal=False,
                resets_idle_timer=False,
                metadata={"method": method, "path": path},
            )

            def read_response() -> str:
                with urllib.request.urlopen(
                    request,
                    timeout=max(self.timeout, local_supervisor.idle_timeout_seconds),
                ) as response:
                    local_supervisor.emit(
                        "response_headers",
                        source="http_client",
                        real_provider_signal=True,
                        metadata={"status": getattr(response, "status", None)},
                    )
                    return response.read().decode("utf-8")

            body = local_supervisor.run_blocking(
                read_response,
                wait_metadata={"provider_call": "ollama_http", "path": path},
            )
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            category = _http_error_category(exc, details)
            raise OllamaProviderError(category, _http_error_message(category, details)) from exc
        except urllib.error.URLError as exc:
            if _is_timeout_reason(exc.reason):
                raise OllamaProviderError(
                    "timeout",
                    f"Ollama request to {self.base_url} timed out.",
                ) from exc
            raise OllamaProviderError(
                "server_not_running",
                f"Ollama is not reachable at {self.base_url}. Start it with: ollama serve",
            ) from exc
        except ProviderCallIdleTimeoutError:
            raise
        except TimeoutError as exc:
            raise OllamaProviderError(
                "timeout",
                f"Ollama request to {self.base_url} timed out.",
            ) from exc

        if not body:
            raise OllamaProviderError(
                "invalid_response",
                "Ollama returned an empty response body.",
            )
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise OllamaProviderError(
                "invalid_json",
                "Ollama returned a response body that was not valid JSON.",
            ) from exc
        if not isinstance(parsed, dict):
            raise OllamaProviderError(
                "invalid_response",
                "Ollama returned a JSON response that was not an object.",
            )
        return parsed


def build_ollama_chat_payload(
    *,
    messages: list[dict[str, str]],
    model: str,
    max_tokens: int,
    temperature: float | None,
) -> dict[str, Any]:
    options: dict[str, Any] = {"num_predict": int(max_tokens)}
    if temperature is not None:
        options["temperature"] = float(temperature)
    return {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": options,
    }


def normalize_ollama_chat_response(response: dict[str, Any]) -> dict[str, Any]:
    message = response.get("message")
    if not isinstance(message, dict):
        raise OllamaProviderError(
            "invalid_response",
            "Ollama chat response did not contain a message object.",
        )
    content = message.get("content")
    if content is None:
        raise OllamaProviderError(
            "invalid_response",
            "Ollama chat response message did not contain content.",
        )
    text = str(content).strip()
    if not text:
        raise OllamaProviderError(
            "invalid_response",
            "Ollama chat response content was empty.",
        )
    usage = {
        "prompt_tokens": _optional_int(response.get("prompt_eval_count")),
        "completion_tokens": _optional_int(response.get("eval_count")),
        "total_tokens": None,
    }
    if usage["prompt_tokens"] is not None and usage["completion_tokens"] is not None:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return {
        "choices": [{"message": {"content": text}}],
        "usage": usage,
        "ollama": {
            "provider": PROVIDER_NAME,
            "model": response.get("model"),
            "done": response.get("done"),
            "total_duration": response.get("total_duration"),
            "load_duration": response.get("load_duration"),
            "prompt_eval_count": response.get("prompt_eval_count"),
            "eval_count": response.get("eval_count"),
        },
    }


def _resolve_timeout(timeout: float | None) -> float:
    timeout_value = (
        timeout
        if timeout is not None
        else os.getenv("SFE_OLLAMA_TIMEOUT_SECONDS") or DEFAULT_TIMEOUT
    )
    parsed_timeout = float(timeout_value)
    if parsed_timeout <= 0:
        raise ValueError("Ollama timeout must be greater than 0.")
    return parsed_timeout


def _http_error_category(exc: urllib.error.HTTPError, details: str) -> str:
    details_lower = details.lower()
    if exc.code == 404 or "not found" in details_lower or "pull" in details_lower:
        return "model_not_found"
    return "http_error"


def _http_error_message(category: str, details: str) -> str:
    if category == "model_not_found":
        return "Ollama reported that the requested model is not available locally."
    if details.strip():
        return "Ollama HTTP request failed."
    return category


def _is_timeout_reason(reason: object) -> bool:
    return isinstance(reason, TimeoutError) or "timed out" in str(reason).lower()


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _messages_with_system_instruction(
    messages: list[dict[str, str]],
    system_instruction: str | None,
) -> list[dict[str, str]]:
    if system_instruction is None or not system_instruction.strip():
        return messages
    if messages and messages[0].get("role") == "system":
        return messages
    return [{"role": "system", "content": system_instruction}, *messages]
