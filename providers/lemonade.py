"""Minimal Lemonade provider using OpenAI-compatible endpoints."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:13305"
DEFAULT_TIMEOUT = 30


class LemonadeProvider:
    """Small standard-library client for a Lemonade OpenAI-compatible server."""

    def __init__(self, base_url: str | None = None, api_key: str | None = None):
        self.base_url = (base_url or os.getenv("SFE_LEMONADE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.getenv("SFE_LEMONADE_API_KEY")
        self.timeout = DEFAULT_TIMEOUT

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
    ) -> dict:
        """Send a chat completion request to POST /v1/chat/completions."""
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
            response = self._request("POST", "/v1/chat/completions", payload)
        except RuntimeError as exc:
            if uses_template_kwargs and _is_parameter_rejection_text(str(exc)):
                payload.pop("chat_template_kwargs", None)
                return self._request("POST", "/v1/chat/completions", payload)
            raise

        if uses_template_kwargs and _is_parameter_rejection(response):
            payload.pop("chat_template_kwargs", None)
            return self._request("POST", "/v1/chat/completions", payload)

        return response

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        url = _join_openai_compatible_url(self.base_url, path)
        headers = {"Content-Type": "application/json"}

        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        request = urllib.request.Request(url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} from {url}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise RuntimeError(f"Timed out after {self.timeout} seconds calling {url}") from exc

        if not body:
            return {}

        return json.loads(body)


def _join_openai_compatible_url(base_url: str, path: str) -> str:
    """Join root or /v1 OpenAI-compatible base URLs with versioned paths."""

    if base_url.endswith("/v1") and path.startswith("/v1/"):
        return f"{base_url}{path.removeprefix('/v1')}"
    return f"{base_url}{path}"


def _is_qwen_model(model: str) -> bool:
    return "qwen" in model.lower()


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
