"""Tests for Alibaba Model Studio benchmark provider wiring."""

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

from providers.alibaba import (
    DEFAULT_BASE_URL,
    DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL,
    PROVIDER_NAME,
    AlibabaAPIProvider,
    MissingAlibabaAPIKeyError,
    _chat_completions_payload,
    _classify_http_error,
    normalize_usage,
)
from router import llm_router
from runtime import run_effectiveness_benchmark, run_experiment


class AlibabaProviderTests(unittest.TestCase):
    def test_defaults_are_benchmark_only_alibaba_values(self) -> None:
        self.assertEqual(PROVIDER_NAME, "alibaba-api")
        self.assertEqual(DEFAULT_BASE_URL, "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")
        self.assertEqual(DEFAULT_ROUTER_MODEL, "qwen3.6-flash")
        self.assertEqual(DEFAULT_EXECUTOR_MODEL, "qwen3.6-plus")

    def test_missing_api_key_raises_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = AlibabaAPIProvider()

        self.assertFalse(provider.health()["ok"])
        with self.assertRaisesRegex(MissingAlibabaAPIKeyError, "ALIBABA_API_KEY"):
            provider.chat([{"role": "user", "content": "hello"}], model=DEFAULT_EXECUTOR_MODEL)

    def test_payload_disables_thinking_at_top_level_by_default(self) -> None:
        payload = _chat_completions_payload(
            model=DEFAULT_ROUTER_MODEL,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=16,
            temperature=0.0,
            system_instruction=None,
            disable_thinking=True,
        )

        self.assertIs(payload["enable_thinking"], False)
        self.assertNotIn("extra_body", payload)
        self.assertNotIn("chat_template_kwargs", payload)

    def test_payload_can_omit_disable_thinking_when_configured(self) -> None:
        payload = _chat_completions_payload(
            model=DEFAULT_ROUTER_MODEL,
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=16,
            temperature=0.0,
            system_instruction=None,
            disable_thinking=False,
        )

        self.assertNotIn("enable_thinking", payload)

    def test_disable_thinking_env_defaults_true_and_parses_false(self) -> None:
        with patch.dict(os.environ, {"ALIBABA_API_KEY": "test-key"}, clear=True):
            self.assertTrue(AlibabaAPIProvider().disable_thinking)
        with patch.dict(
            os.environ,
            {"ALIBABA_API_KEY": "test-key", "SFE_ALIBABA_DISABLE_THINKING": "false"},
            clear=True,
        ):
            self.assertFalse(AlibabaAPIProvider().disable_thinking)

    def test_usage_normalization_includes_reasoning_tokens_when_present(self) -> None:
        usage = normalize_usage(
            {
                "prompt_tokens": 18,
                "completion_tokens": 251,
                "total_tokens": 269,
                "completion_tokens_details": {"reasoning_tokens": 242},
            }
        )

        self.assertEqual(
            usage,
            {
                "prompt_tokens": 18,
                "completion_tokens": 251,
                "total_tokens": 269,
                "reasoning_tokens": 242,
            },
        )

    def test_error_diagnostics_do_not_include_secrets(self) -> None:
        with patch.dict(os.environ, {"ALIBABA_API_KEY": "secret-alibaba-key"}, clear=True):
            diagnostics = _classify_http_error(
                401,
                json.dumps(
                    {
                        "error": {
                            "message": "bad key secret-alibaba-key",
                            "code": "InvalidApiKey",
                        }
                    }
                ),
            )

        self.assertNotIn("secret-alibaba-key", diagnostics["api_error_message"])
        self.assertIn("[REDACTED]", diagnostics["api_error_message"])

    def test_router_uses_alibaba_env_defaults_and_strict_json_provider(self) -> None:
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
            disable_thinking = True

            def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
                self.messages = messages
                self.kwargs = kwargs
                return {
                    "choices": [{"message": {"content": json.dumps(decision_payload)}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    "alibaba_api": {"latency_ms": 123},
                }

        fake = FakeProvider()
        with patch.object(llm_router, "AlibabaAPIProvider", return_value=fake), patch.dict(
            os.environ,
            {
                "SFE_ALIBABA_ROUTER_MODEL": "router-env",
                "SFE_ALIBABA_EXECUTOR_MODEL": "executor-env",
            },
            clear=True,
        ):
            decision, diagnostics = llm_router.route_with_alibaba_api_diagnostics(
                "Write a Python function."
            )

        self.assertEqual(fake.kwargs["model"], "router-env")
        self.assertEqual(decision["provider"], PROVIDER_NAME)
        self.assertEqual(decision["router_model"], "router-env")
        self.assertEqual(decision["model"], "executor-env")
        self.assertEqual(decision["router_total_tokens"], 15)
        self.assertTrue(diagnostics["success"])
        self.assertFalse(diagnostics["used_fallback"])

    def test_benchmark_model_resolution_uses_alibaba_env_names(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_ALIBABA_ROUTER_MODEL": "alibaba-router",
                "SFE_ALIBABA_EXECUTOR_MODEL": "alibaba-executor",
            },
            clear=True,
        ):
            router_model = run_effectiveness_benchmark._resolve_router_model(
                PROVIDER_NAME, None
            )
            executor_model = run_effectiveness_benchmark._resolve_executor_model(
                PROVIDER_NAME, None
            )

        self.assertEqual(router_model, "alibaba-router")
        self.assertEqual(executor_model, "alibaba-executor")

    def test_run_experiment_routes_alibaba_without_openai_model_leakage(self) -> None:
        with patch.object(run_experiment, "route_with_alibaba_api", return_value={"ok": True}) as router:
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
