"""Tests for the Google Gemini OpenAI-compatible provider wiring."""

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

from providers.google import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PROVIDER_NAME,
    GoogleAPIProvider,
    MissingGoogleAPIKeyError,
    _chat_completions_payload,
    _classify_http_error,
    normalize_usage,
)
from router import llm_router
from runtime import run_effectiveness_benchmark, run_experiment


class GoogleProviderTests(unittest.TestCase):
    def test_defaults_are_gemini_openai_compatible_values(self) -> None:
        self.assertEqual(PROVIDER_NAME, "google")
        self.assertEqual(DEFAULT_BASE_URL, "https://generativelanguage.googleapis.com/v1beta/openai")
        self.assertEqual(DEFAULT_MODEL, "gemini-2.5-flash-lite")

    def test_missing_api_key_raises_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = GoogleAPIProvider()

        self.assertFalse(provider.health()["ok"])
        with self.assertRaisesRegex(MissingGoogleAPIKeyError, "GOOGLE_API_KEY"):
            provider.chat([{"role": "user", "content": "hello"}], model=DEFAULT_MODEL)

    def test_env_base_url_is_used_without_trailing_slash(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GOOGLE_API_KEY": "configured-value",
                "SFE_GOOGLE_BASE_URL": "https://example.test/v1beta/openai/",
            },
            clear=True,
        ):
            provider = GoogleAPIProvider()

        self.assertEqual(provider.base_url, "https://example.test/v1beta/openai")

    def test_payload_uses_chat_completions_shape(self) -> None:
        payload = _chat_completions_payload(
            model=DEFAULT_MODEL,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=16,
            temperature=0.0,
            system_instruction="Return a short answer.",
        )

        self.assertEqual(payload["model"], DEFAULT_MODEL)
        self.assertEqual(payload["max_tokens"], 16)
        self.assertEqual(payload["temperature"], 0.0)
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")

    def test_usage_normalization_accepts_chat_and_input_output_names(self) -> None:
        self.assertEqual(
            normalize_usage({"prompt_tokens": 3, "completion_tokens": 2}),
            {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        )
        self.assertEqual(
            normalize_usage({"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}),
            {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        )

    def test_error_diagnostics_do_not_include_secrets(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_API_KEY": "redact-me"}, clear=True):
            diagnostics = _classify_http_error(
                401,
                json.dumps(
                    {
                        "error": {
                            "message": "bad credential redact-me",
                            "status": "UNAUTHENTICATED",
                        }
                    }
                ),
            )

        self.assertNotIn("redact-me", diagnostics["api_error_message"])
        self.assertIn("[REDACTED]", diagnostics["api_error_message"])

    def test_router_uses_google_env_model_and_strict_json_provider(self) -> None:
        decision_payload = {
            "task_type": "coding",
            "role": "executor",
            "provider": "local",
            "model": "unused",
            "memory_zones": [],
            "execution_mode": "direct",
            "max_input_tokens": 4000,
            "max_output_tokens": 1000,
            "requires_review": False,
            "confidence": 0.9,
            "rationale": "The task asks for code.",
        }

        class FakeProvider:
            timeout = 12.0

            def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
                self.messages = messages
                self.kwargs = kwargs
                return {
                    "choices": [{"message": {"content": json.dumps(decision_payload)}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    "google_api": {"latency_ms": 123},
                }

        fake = FakeProvider()
        with patch.object(llm_router, "GoogleAPIProvider", return_value=fake), patch.dict(
            os.environ,
            {"SFE_GOOGLE_MODEL": "gemini-env"},
            clear=True,
        ):
            decision, diagnostics = llm_router.route_with_google_diagnostics(
                "Write a Python function."
            )

        self.assertEqual(fake.kwargs["model"], "gemini-env")
        self.assertEqual(decision["provider"], PROVIDER_NAME)
        self.assertEqual(decision["router_model"], "gemini-env")
        self.assertEqual(decision["model"], "gemini-env")
        self.assertEqual(decision["router_total_tokens"], 15)
        self.assertTrue(diagnostics["success"])
        self.assertFalse(diagnostics["used_fallback"])

    def test_benchmark_model_resolution_uses_google_env_name(self) -> None:
        with patch.dict(os.environ, {"SFE_GOOGLE_MODEL": "google-model"}, clear=True):
            router_model = run_effectiveness_benchmark._resolve_router_model(
                PROVIDER_NAME, None
            )
            executor_model = run_effectiveness_benchmark._resolve_executor_model(
                PROVIDER_NAME, None
            )

        self.assertEqual(router_model, "google-model")
        self.assertEqual(executor_model, "google-model")

    def test_run_experiment_routes_google_without_openai_model_leakage(self) -> None:
        with patch.object(run_experiment, "route_with_google", return_value={"ok": True}) as router:
            decision = run_experiment._route_task(
                "Classify this.",
                router_name=PROVIDER_NAME,
                router_model=None,
                executor_model="gpt-5.5",
                timeout_seconds=1,
            )

        self.assertEqual(decision, {"ok": True})
        self.assertIsNone(router.call_args.kwargs["executor_model"])


if __name__ == "__main__":
    unittest.main()
