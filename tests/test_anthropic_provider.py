"""Tests for the native Anthropic Messages API benchmark provider."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.anthropic import (
    API_STYLE,
    DEFAULT_ANTHROPIC_VERSION,
    DEFAULT_ROUTER_MODEL,
    AnthropicAPIError,
    AnthropicProvider,
    MissingAnthropicAPIKeyError,
    PROVIDER_NAME,
    _classify_http_error,
    _messages_payload,
    extract_visible_text,
    normalize_usage,
)


class AnthropicProviderTests(unittest.TestCase):
    def test_default_router_model_is_configurable_haiku_family(self) -> None:
        self.assertIn("haiku", DEFAULT_ROUTER_MODEL)

    def test_missing_api_key_raises_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = AnthropicProvider()

        self.assertFalse(provider.health()["ok"])
        self.assertEqual(provider.health()["api_style"], API_STYLE)
        with self.assertRaisesRegex(MissingAnthropicAPIKeyError, "ANTHROPIC_API_KEY"):
            provider.chat([{"role": "user", "content": "hello"}], model="claude-test")

    def test_messages_payload_uses_native_anthropic_shape(self) -> None:
        payload = _messages_payload(
            model="claude-test",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=32,
            temperature=0.0,
            system_instruction="Return JSON.",
        )

        self.assertEqual(payload["model"], "claude-test")
        self.assertEqual(payload["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(payload["max_tokens"], 32)
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["system"], "Return JSON.")
        self.assertNotIn("input", payload)
        self.assertNotIn("max_output_tokens", payload)

    def test_visible_text_extraction_from_content_blocks(self) -> None:
        text = extract_visible_text(
            {
                "content": [
                    {"type": "text", "text": " First. "},
                    {"type": "thinking", "text": "hidden"},
                    {"type": "text", "text": "Second."},
                ]
            }
        )

        self.assertEqual(text, "First.\nSecond.")

    def test_usage_normalization_maps_anthropic_usage(self) -> None:
        usage = normalize_usage({"input_tokens": 11, "output_tokens": 7})

        self.assertEqual(
            usage,
            {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        )

    def test_chat_normalizes_native_response_for_existing_benchmark_extractors(self) -> None:
        class FakeProvider(AnthropicProvider):
            def _messages_create(self, **_: object) -> dict[str, object]:
                return {
                    "content": [{"type": "text", "text": "Clean answer."}],
                    "usage": {"input_tokens": 9, "output_tokens": 4},
                }

        provider = FakeProvider(api_key="test-key", timeout=1)
        response = provider.chat(
            [{"role": "user", "content": "hello"}],
            model="claude-test",
            max_tokens=32,
            temperature=0.0,
        )

        self.assertEqual(response["choices"][0]["message"]["content"], "Clean answer.")
        self.assertEqual(
            response["usage"],
            {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
        )
        self.assertEqual(response["anthropic_api"]["provider"], PROVIDER_NAME)
        self.assertEqual(response["anthropic_api"]["api_style"], API_STYLE)
        self.assertEqual(
            response["anthropic_api"]["anthropic_version"],
            DEFAULT_ANTHROPIC_VERSION,
        )

    def test_http_request_uses_native_messages_endpoint_and_headers(self) -> None:
        captured: dict[str, object] = {}

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps(
                    {
                        "content": [{"type": "text", "text": "ok"}],
                        "usage": {"input_tokens": 2, "output_tokens": 1},
                    }
                ).encode("utf-8")

        def fake_urlopen(request: object, timeout: float) -> FakeResponse:
            captured["full_url"] = getattr(request, "full_url")
            captured["headers"] = dict(getattr(request, "headers"))
            captured["body"] = json.loads(getattr(request, "data").decode("utf-8"))
            captured["timeout"] = timeout
            return FakeResponse()

        provider = AnthropicProvider(
            api_key="test-key",
            base_url="https://api.anthropic.example",
            timeout=3,
        )
        with patch("providers.anthropic.urllib.request.urlopen", side_effect=fake_urlopen):
            response = provider.chat([{"role": "user", "content": "hello"}], model="claude-test")

        self.assertEqual(captured["full_url"], "https://api.anthropic.example/v1/messages")
        headers = {str(key).lower(): value for key, value in dict(captured["headers"]).items()}
        self.assertEqual(headers["x-api-key"], "test-key")
        self.assertEqual(headers["anthropic-version"], DEFAULT_ANTHROPIC_VERSION)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertNotIn("authorization", headers)
        self.assertEqual(captured["body"]["model"], "claude-test")
        self.assertEqual(response["usage"]["total_tokens"], 3)

    def test_rate_limit_is_retryable_and_retry_count_is_reported(self) -> None:
        class FakeProvider(AnthropicProvider):
            def __init__(self, **kwargs: object) -> None:
                super().__init__(**kwargs)
                self.calls = 0

            def _messages_create(self, **_: object) -> dict[str, object]:
                self.calls += 1
                if self.calls == 1:
                    raise AnthropicAPIError(
                        {
                            "api_error_status": 429,
                            "api_error_type": "rate_limit",
                            "api_error_code": "rate_limit_error",
                            "api_error_message": "slow down",
                            "api_error_retry_count": 0,
                        }
                    )
                return {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 2, "output_tokens": 1},
                }

        provider = FakeProvider(api_key="test-key", timeout=1)
        with patch("providers.anthropic.time.sleep") as sleep:
            response = provider.chat([{"role": "user", "content": "hello"}], model="claude-test")

        self.assertEqual(provider.calls, 2)
        sleep.assert_called_once()
        self.assertEqual(response["anthropic_api"]["api_error_retry_count"], 1)
        self.assertEqual(response["anthropic_api"]["api_error_type"], "rate_limit")

    def test_error_diagnostics_do_not_include_secrets(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-secret1234567890"}):
            diagnostics = _classify_http_error(
                401,
                json.dumps(
                    {
                        "error": {
                            "type": "authentication_error",
                            "message": (
                                "Bad key sk-ant-secret1234567890 in x-api-key header"
                            ),
                        }
                    }
                ),
            )

        self.assertNotIn("sk-ant-secret1234567890", diagnostics["api_error_message"])
        self.assertIn("[REDACTED]", diagnostics["api_error_message"])


if __name__ == "__main__":
    unittest.main()
