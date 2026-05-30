"""Minimal Lemonade provider using OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from sfe.provider_progress import (
    ProviderCallIdleTimeoutError,
    ProviderCallSupervisor,
    ProviderProgressSink,
)


DEFAULT_BASE_URL = "http://127.0.0.1:13305"
DEFAULT_TIMEOUT = 30


class LemonadeProviderError(RuntimeError):
    """Sanitized Lemonade failure with a safe category for callers."""

    def __init__(
        self,
        error_category: str,
        *,
        parameter_rejection: bool = False,
    ) -> None:
        self.error_category = error_category
        self.parameter_rejection = parameter_rejection
        super().__init__(error_category)


class LemonadeProvider:
    """Small standard-library client for a Lemonade OpenAI-compatible server."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
    ):
        self.base_url = (base_url or os.getenv("SFE_LEMONADE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("SFE_LEMONADE_API_KEY")
        self.timeout = _resolve_timeout(timeout)

    def health(self) -> dict:
        """Check whether the Lemonade server responds to the models endpoint."""
        try:
            models = self.list_models()
        except Exception as exc:
            return {
                "ok": False,
                "base_url": self.base_url,
                "error": str(exc),
            }

        return {
            "ok": True,
            "base_url": self.base_url,
            "models_count": len(models),
        }

    def list_models(self) -> list[str]:
        """Return model ids from GET /v1/models."""
        response = self._request("GET", "/v1/models")
        models = response.get("data", [])

        if isinstance(models, list):
            return [str(model["id"]) for model in models if isinstance(model, dict) and "id" in model]

        return []

    def chat(
        self,
        messages: list[dict],
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
        chat_template_kwargs: dict | None = None,
        progress_sink: ProviderProgressSink | None = None,
    ) -> dict:
        """Send a chat completion request to POST /v1/chat/completions."""
        supervisor = ProviderCallSupervisor(
            provider="lemonade",
            model=model,
            progress_sink=progress_sink,
        )
        supervisor.start(
            {
                "base_url": self.base_url,
                "api_style": "openai_compatible_chat",
                "max_tokens_requested": max_tokens,
            }
        )
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        template_kwargs = dict(chat_template_kwargs or {})
        if _is_qwen_model(model) and "enable_thinking" not in template_kwargs:
            template_kwargs["enable_thinking"] = False
        uses_template_kwargs = bool(template_kwargs)
        if uses_template_kwargs:
            payload["chat_template_kwargs"] = template_kwargs

        try:
            response = self._request("POST", "/v1/chat/completions", payload, supervisor)
        except LemonadeProviderError as exc:
            if uses_template_kwargs and exc.parameter_rejection:
                payload.pop("chat_template_kwargs", None)
                supervisor.emit(
                    "retry_scheduled",
                    source="sfe_core",
                    real_provider_signal=False,
                    resets_idle_timer=False,
                    metadata={"reason": "template_kwargs_parameter_rejection"},
                )
                try:
                    response = self._request("POST", "/v1/chat/completions", payload, supervisor)
                except Exception as retry_exc:
                    supervisor.fail({"error_type": type(retry_exc).__name__})
                    raise
                supervisor.complete()
                return response
            supervisor.fail({"error_type": type(exc).__name__, "error_category": exc.error_category})
            raise
        except ProviderCallIdleTimeoutError as exc:
            supervisor.fail({"error_type": type(exc).__name__})
            raise

        if uses_template_kwargs and _is_parameter_rejection(response):
            payload.pop("chat_template_kwargs", None)
            supervisor.emit(
                "retry_scheduled",
                source="sfe_core",
                real_provider_signal=False,
                resets_idle_timer=False,
                metadata={"reason": "template_kwargs_parameter_rejection_response"},
            )
            try:
                response = self._request("POST", "/v1/chat/completions", payload, supervisor)
            except Exception as retry_exc:
                supervisor.fail({"error_type": type(retry_exc).__name__})
                raise

        supervisor.complete()
        return response

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        supervisor: ProviderCallSupervisor | None = None,
    ) -> dict:
        url = _join_openai_compatible_url(self.base_url, path)
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            local_supervisor = supervisor or ProviderCallSupervisor(
                provider="lemonade",
                model=None,
            )
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
                wait_metadata={"provider_call": "lemonade_http", "path": path},
            )
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise LemonadeProviderError(
                "http_error",
                parameter_rejection=_is_parameter_rejection_text(details),
            ) from exc
        except urllib.error.URLError as exc:
            if _is_timeout_reason(exc.reason):
                raise LemonadeProviderError("timeout") from exc
            raise LemonadeProviderError("network_error") from exc
        except ProviderCallIdleTimeoutError:
            raise
        except TimeoutError as exc:
            raise LemonadeProviderError("timeout") from exc

        if not body:
            return {}

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise LemonadeProviderError("invalid_json") from exc


def _join_openai_compatible_url(base_url: str, path: str) -> str:
    """Join root or /v1 OpenAI-compatible base URLs with versioned paths."""

    if base_url.endswith("/v1") and path.startswith("/v1/"):
        return f"{base_url}{path.removeprefix('/v1')}"
    return f"{base_url}{path}"


def _is_qwen_model(model: str) -> bool:
    return "qwen" in model.lower()


def _resolve_timeout(timeout: float | None) -> float:
    timeout_value = timeout if timeout is not None else DEFAULT_TIMEOUT
    parsed_timeout = float(timeout_value)
    if parsed_timeout <= 0:
        raise ValueError("Lemonade timeout must be greater than 0.")
    return parsed_timeout


def _is_timeout_reason(reason: object) -> bool:
    return isinstance(reason, TimeoutError) or "timed out" in str(reason).lower()


def _is_parameter_rejection(response: dict) -> bool:
    error = response.get("error")
    if not error:
        return False

    return _is_parameter_rejection_text(json.dumps(error))


def _is_parameter_rejection_text(error_text: str) -> bool:
    error_text = error_text.lower()
    return any(
        marker in error_text
        for marker in (
            "chat_template_kwargs",
            "enable_thinking",
            "unsupported",
            "unexpected",
            "unknown",
            "extra",
            "invalid",
        )
    )


if __name__ == "__main__":
    provider = LemonadeProvider()
    print(provider.health())
    print(provider.list_models())
