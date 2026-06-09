"""Tests for the local Ollama provider adapter."""

from __future__ import annotations

import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.ollama import (
    OllamaProvider,
    OllamaProviderError,
    build_ollama_chat_payload,
    normalize_ollama_chat_response,
)


class FakeHTTPResponse:
    status = 200

    def __init__(self, body: dict[str, object]) -> None:
        self.body = json.dumps(body).encode("utf-8")

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_ollama_provider_builds_expected_chat_payload() -> None:
    payload = build_ollama_chat_payload(
        messages=[{"role": "user", "content": "Return OK."}],
        model="qwen3.5:4b",
        max_tokens=8,
        temperature=0.0,
    )

    assert payload == {
        "model": "qwen3.5:4b",
        "messages": [{"role": "user", "content": "Return OK."}],
        "stream": False,
        "options": {"num_predict": 8, "temperature": 0.0},
        "think": False,
    }


def test_ollama_provider_extracts_response_text_and_usage() -> None:
    response = normalize_ollama_chat_response(
        {
            "model": "qwen3.5:4b",
            "message": {"role": "assistant", "content": " OK\n"},
            "done": True,
            "prompt_eval_count": 5,
            "eval_count": 1,
        }
    )

    assert response["choices"][0]["message"]["content"] == "OK"
    assert response["usage"] == {
        "prompt_tokens": 5,
        "completion_tokens": 1,
        "total_tokens": 6,
    }
    assert response["ollama"]["provider"] == "ollama"


@pytest.mark.parametrize(
    "raw_response",
    (
        {},
        {"message": None},
        {"message": {}},
        {"message": {"content": ""}},
    ),
)
def test_ollama_invalid_response_raises_useful_error(raw_response: dict[str, object]) -> None:
    with pytest.raises(OllamaProviderError) as exc_info:
        normalize_ollama_chat_response(raw_response)

    assert exc_info.value.error_category == "invalid_response"
    assert str(exc_info.value)


def test_ollama_chat_validates_requested_model_before_completion(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_urlopen(request: urllib.request.Request, **_: object) -> FakeHTTPResponse:
        calls.append({"url": request.full_url, "data": request.data})
        if request.full_url.endswith("/api/tags"):
            return FakeHTTPResponse({"models": [{"name": "qwen3.5:4b"}]})
        if request.full_url.endswith("/api/chat"):
            assert request.data is not None
            payload = json.loads(request.data.decode("utf-8"))
            assert payload["model"] == "qwen3.5:4b"
            assert payload["stream"] is False
            assert payload["think"] is False
            assert payload["messages"][0] == {
                "role": "system",
                "content": "System.",
            }
            return FakeHTTPResponse(
                {
                    "model": "qwen3.5:4b",
                    "message": {"role": "assistant", "content": "OK"},
                    "done": True,
                }
            )
        raise AssertionError(f"unexpected URL {request.full_url}")

    monkeypatch.setattr("providers.ollama.urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider(base_url="http://ollama.local", timeout=1)

    response = provider.chat(
        [{"role": "user", "content": "Return OK."}],
        model="qwen3.5:4b",
        max_tokens=3,
        system_instruction="System.",
    )

    assert response["choices"][0]["message"]["content"] == "OK"
    assert [call["url"] for call in calls] == [
        "http://ollama.local/api/tags",
        "http://ollama.local/api/chat",
    ]


def test_ollama_missing_model_reports_model_not_found(monkeypatch) -> None:
    def fake_urlopen(*_: object, **__: object) -> FakeHTTPResponse:
        return FakeHTTPResponse({"models": [{"name": "gemma4:12b"}]})

    monkeypatch.setattr("providers.ollama.urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider(base_url="http://ollama.local", timeout=1)

    with pytest.raises(OllamaProviderError) as exc_info:
        provider.chat([{"role": "user", "content": "OK?"}], model="qwen3.5:4b")

    assert exc_info.value.error_category == "model_not_found"
    assert "ollama pull qwen3.5:4b" in str(exc_info.value)


def test_ollama_server_not_running_reports_clear_error(monkeypatch) -> None:
    def fake_urlopen(*_: object, **__: object) -> object:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("providers.ollama.urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider(base_url="http://ollama.local", timeout=1)

    health = provider.health()

    assert health["ok"] is False
    assert "Ollama is not reachable at http://ollama.local" in str(health["error"])


def test_ollama_http_404_maps_to_model_not_found(monkeypatch) -> None:
    def fake_urlopen(*_: object, **__: object) -> object:
        raise urllib.error.HTTPError(
            "redacted",
            404,
            "not found",
            {},
            io.BytesIO(b'{"error":"model not found"}'),
        )

    monkeypatch.setattr("providers.ollama.urllib.request.urlopen", fake_urlopen)
    provider = OllamaProvider(base_url="http://ollama.local", timeout=1)

    with pytest.raises(OllamaProviderError) as exc_info:
        provider.list_models()

    assert exc_info.value.error_category == "model_not_found"
