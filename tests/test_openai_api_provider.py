"""Tests for the direct OpenAI API benchmark provider."""

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

from providers.openai_api import (
    DEFAULT_ROUTER_MODEL,
    OpenAIAPIError,
    MissingOpenAIAPIKeyError,
    OpenAIAPIProvider,
    PROVIDER_NAME,
    _classify_http_error,
    _responses_payload,
    extract_visible_text,
    normalize_usage,
)
from router import llm_router
from runtime import run_effectiveness_benchmark, run_experiment
from sfe.provider_progress import collect_progress_events


class OpenAIAPIProviderTests(unittest.TestCase):
    def test_openai_api_default_router_model_is_nano(self) -> None:
        self.assertEqual(DEFAULT_ROUTER_MODEL, "gpt-5.4-nano")

    def test_missing_api_key_raises_clear_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            provider = OpenAIAPIProvider()

        self.assertFalse(provider.health()["ok"])
        with self.assertRaisesRegex(MissingOpenAIAPIKeyError, "OPENAI_API_KEY"):
            provider.chat([{"role": "user", "content": "hello"}], model="gpt-5.5")

    def test_visible_text_extraction_from_responses_output_text(self) -> None:
        text = extract_visible_text({"output_text": " Final answer. "})

        self.assertEqual(text, "Final answer.")

    def test_visible_text_extraction_from_responses_output_items(self) -> None:
        text = extract_visible_text(
            {
                "output": [
                    {
                        "content": [
                            {"type": "output_text", "text": "First."},
                            {"type": "output_text", "text": "Second."},
                        ]
                    }
                ]
            }
        )

        self.assertEqual(text, "First.\nSecond.")

    def test_usage_normalization_accepts_responses_and_chat_names(self) -> None:
        responses_usage = normalize_usage(
            {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
        )
        chat_usage = normalize_usage({"prompt_tokens": 3, "completion_tokens": 2})

        self.assertEqual(
            responses_usage,
            {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
        )
        self.assertEqual(
            chat_usage,
            {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        )

    def test_chat_normalizes_response_without_codexcli_metadata(self) -> None:
        class FakeProvider(OpenAIAPIProvider):
            def _responses_create(self, **_: object) -> dict[str, object]:
                return {
                    "output_text": "Clean answer.",
                    "usage": {
                        "input_tokens": 9,
                        "output_tokens": 4,
                        "total_tokens": 13,
                    },
                }

        provider = FakeProvider(api_key="test-key", timeout=1)
        response = provider.chat(
            [{"role": "user", "content": "hello"}],
            model="gpt-5.5",
            max_tokens=32,
            temperature=0.0,
        )

        self.assertEqual(response["choices"][0]["message"]["content"], "Clean answer.")
        self.assertEqual(
            response["usage"],
            {"prompt_tokens": 9, "completion_tokens": 4, "total_tokens": 13},
        )
        self.assertEqual(response["openai_api"]["provider"], PROVIDER_NAME)
        self.assertNotIn("codexcli", response)

    def test_chat_emits_core_provider_progress_events(self) -> None:
        class FakeProvider(OpenAIAPIProvider):
            def _responses_create(self, **_: object) -> dict[str, object]:
                return {
                    "output_text": "Clean answer.",
                    "usage": {"input_tokens": 9, "output_tokens": 4},
                }

        events, sink = collect_progress_events()
        provider = FakeProvider(api_key="test-key", timeout=1)
        response = provider.chat(
            [{"role": "user", "content": "hello"}],
            model="gpt-5.5",
            progress_sink=sink,
        )

        self.assertEqual(response["choices"][0]["message"]["content"], "Clean answer.")
        self.assertEqual([event.kind for event in events], ["call_started", "call_completed"])
        self.assertTrue(all(event.provider == PROVIDER_NAME for event in events))

    def test_gpt_5_5_payload_omits_temperature(self) -> None:
        payload = _responses_payload(
            model="gpt-5.5",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=32,
            temperature=0.0,
            system_instruction=None,
        )

        self.assertNotIn("temperature", payload)

    def test_gpt_5_nano_router_payload_omits_temperature(self) -> None:
        payload = _responses_payload(
            model="gpt-5.4-nano",
            messages=[{"role": "user", "content": "route this"}],
            max_tokens=32,
            temperature=0.0,
            system_instruction=None,
        )

        self.assertNotIn("temperature", payload)

    def test_unsupported_temperature_error_is_surfaced_clearly(self) -> None:
        class FakeProvider(OpenAIAPIProvider):
            def _responses_create(self, **_: object) -> dict[str, object]:
                raise RuntimeError("HTTP 400: unsupported temperature parameter")

        provider = FakeProvider(api_key="test-key", timeout=1)

        with self.assertRaisesRegex(RuntimeError, "unsupported temperature parameter"):
            provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
                max_tokens=32,
                temperature=0.0,
            )

    def test_unsupported_temperature_is_classified(self) -> None:
        diagnostics = _classify_http_error(
            400,
            json.dumps(
                {
                    "error": {
                        "message": "Unsupported parameter: temperature",
                        "type": "invalid_request_error",
                        "code": None,
                    }
                }
            ),
        )

        self.assertEqual(diagnostics["api_error_type"], "unsupported_parameter")

    def test_rate_limit_is_retryable_and_retry_count_is_reported(self) -> None:
        class FakeProvider(OpenAIAPIProvider):
            def __init__(self, **kwargs: object) -> None:
                super().__init__(**kwargs)
                self.calls = 0

            def _responses_create(self, **_: object) -> dict[str, object]:
                self.calls += 1
                if self.calls == 1:
                    raise OpenAIAPIError(
                        {
                            "api_error_status": 429,
                            "api_error_type": "rate_limit",
                            "api_error_code": "rate_limit_exceeded",
                            "api_error_message": "slow down",
                            "api_error_retry_count": 0,
                        }
                    )
                return {"output_text": "ok", "usage": {"input_tokens": 2, "output_tokens": 1}}

        provider = FakeProvider(api_key="test-key", timeout=1)
        with patch("providers.openai_api.time.sleep") as sleep:
            response = provider.chat([{"role": "user", "content": "hello"}], model="gpt-5.5")

        self.assertEqual(provider.calls, 2)
        sleep.assert_called_once()
        self.assertEqual(response["openai_api"]["api_error_retry_count"], 1)
        self.assertEqual(response["openai_api"]["api_error_type"], "rate_limit")

    def test_insufficient_quota_gets_at_most_one_short_retry(self) -> None:
        class FakeProvider(OpenAIAPIProvider):
            def __init__(self, **kwargs: object) -> None:
                super().__init__(**kwargs)
                self.calls = 0

            def _responses_create(self, **_: object) -> dict[str, object]:
                self.calls += 1
                raise OpenAIAPIError(
                    {
                        "api_error_status": 429,
                        "api_error_type": "insufficient_quota",
                        "api_error_code": "insufficient_quota",
                        "api_error_message": "billing propagation pending",
                        "api_error_retry_count": 0,
                    }
                )

        provider = FakeProvider(api_key="test-key", timeout=1)
        with patch("providers.openai_api.time.sleep") as sleep:
            with self.assertRaises(OpenAIAPIError) as raised:
                provider.chat([{"role": "user", "content": "hello"}], model="gpt-5.5")

        self.assertEqual(provider.calls, 2)
        sleep.assert_called_once_with(0.5)
        self.assertEqual(raised.exception.diagnostics["api_error_type"], "insufficient_quota")
        self.assertEqual(raised.exception.diagnostics["api_error_retry_count"], 1)

    def test_error_diagnostics_do_not_include_secrets(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-secret1234567890"}):
            diagnostics = _classify_http_error(
                401,
                json.dumps(
                    {
                        "error": {
                            "message": "Bad key sk-secret1234567890 in Authorization header",
                            "type": "invalid_request_error",
                            "code": "invalid_api_key",
                        }
                    }
                ),
            )

        self.assertNotIn("sk-secret1234567890", diagnostics["api_error_message"])
        self.assertIn("[REDACTED]", diagnostics["api_error_message"])

    def test_router_json_handling_adds_openai_api_backend_and_metrics(self) -> None:
        class FakeProvider:
            def __init__(self, **_: object) -> None:
                self.timeout = 12

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "task_type": "analysis",
                                        "role": "reviewer",
                                        "provider": "local",
                                        "model": llm_router.DEFAULT_EXECUTION_MODEL,
                                        "memory_zones": [],
                                        "execution_mode": "direct",
                                        "max_input_tokens": 4000,
                                        "max_output_tokens": 1000,
                                        "requires_review": False,
                                        "confidence": 0.9,
                                        "rationale": "analysis task",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 101,
                        "completion_tokens": 21,
                        "total_tokens": 122,
                    },
                    "openai_api": {"latency_ms": 1234},
                }

        with patch.object(llm_router, "OpenAIAPIProvider", FakeProvider):
            decision, diagnostics = llm_router.route_with_openai_api_diagnostics(
                "Compare two methods.",
                router_model="gpt-5.4-mini",
                executor_model="gpt-5.5",
                timeout_seconds=12,
            )

        self.assertFalse(diagnostics["used_fallback"])
        self.assertEqual(decision["provider"], PROVIDER_NAME)
        self.assertEqual(decision["router_model"], "gpt-5.4-mini")
        self.assertEqual(decision["model"], "gpt-5.5")
        self.assertEqual(decision["router_latency_ms"], 1234)
        self.assertEqual(decision["router_total_tokens"], 122)
        self.assertEqual(decision["router_error"], "")

    def test_router_successful_retry_is_visible_in_diagnostics(self) -> None:
        class FakeProvider:
            def __init__(self, **_: object) -> None:
                self.timeout = 12

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "task_type": "writing",
                                        "role": "writer",
                                        "provider": "local",
                                        "model": llm_router.DEFAULT_EXECUTION_MODEL,
                                        "memory_zones": [],
                                        "execution_mode": "direct",
                                        "max_input_tokens": 4000,
                                        "max_output_tokens": 1000,
                                        "requires_review": False,
                                        "confidence": 0.9,
                                        "rationale": "writing task",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 101,
                        "completion_tokens": 21,
                        "total_tokens": 122,
                    },
                    "openai_api": {
                        "latency_ms": 1234,
                        "api_error_retry_count": 1,
                        "api_error_type": "rate_limit",
                        "api_error_code": "rate_limit_exceeded",
                        "api_error_message": "slow down",
                        "api_error_attempts": [
                            {
                                "api_error_status": 429,
                                "api_error_type": "rate_limit",
                                "api_error_code": "rate_limit_exceeded",
                                "api_error_message": "slow down",
                            }
                        ],
                    },
                }

        with patch.object(llm_router, "OpenAIAPIProvider", FakeProvider):
            decision, diagnostics = llm_router.route_with_openai_api_diagnostics(
                "Write a project update.",
                router_model="gpt-5.4-nano",
                executor_model="gpt-5.5",
                timeout_seconds=12,
            )

        self.assertTrue(diagnostics["success"])
        self.assertEqual(diagnostics["api_error_retry_count"], 1)
        self.assertEqual(decision["api_error_retry_count"], 1)
        self.assertEqual(decision["api_error_type"], "rate_limit")

    def test_insufficient_quota_router_does_not_try_second_prompt(self) -> None:
        class FakeProvider:
            call_count = 0

            def __init__(self, **_: object) -> None:
                self.timeout = 12

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                FakeProvider.call_count += 1
                raise OpenAIAPIError(
                    {
                        "api_error_status": 429,
                        "api_error_type": "insufficient_quota",
                        "api_error_code": "insufficient_quota",
                        "api_error_message": "billing propagation pending",
                        "api_error_retry_count": 1,
                    }
                )

        with patch.object(llm_router, "OpenAIAPIProvider", FakeProvider):
            decision, diagnostics = llm_router.route_with_openai_api_diagnostics(
                "Write a project update.",
                router_model="gpt-5.4-nano",
                executor_model="gpt-5.5",
                timeout_seconds=12,
            )

        self.assertEqual(FakeProvider.call_count, 1)
        self.assertTrue(diagnostics["used_fallback"])
        self.assertEqual(diagnostics["api_errors"][0]["api_error_type"], "insufficient_quota")
        self.assertEqual(decision["api_error_retry_count"], 1)
        self.assertEqual(decision["api_error_type"], "insufficient_quota")

    def test_runtime_cli_accepts_openai_api_router_and_executor(self) -> None:
        argv = [
            "run_experiment.py",
            "--router",
            PROVIDER_NAME,
            "--executor",
            PROVIDER_NAME,
            "--router-model",
            "gpt-5.4-mini",
            "--executor-model",
            "gpt-5.5",
        ]

        with patch.object(sys, "argv", argv):
            args = run_experiment._parse_args()

        self.assertEqual(args.router, PROVIDER_NAME)
        self.assertEqual(args.executor, PROVIDER_NAME)

    def test_effectiveness_cli_accepts_openai_api_router_and_executor(self) -> None:
        argv = [
            "run_effectiveness_benchmark.py",
            "--router",
            PROVIDER_NAME,
            "--executor",
            PROVIDER_NAME,
            "--router-model",
            "gpt-5.4-mini",
            "--executor-model",
            "gpt-5.5",
        ]

        with patch.object(sys, "argv", argv):
            args = run_effectiveness_benchmark._parse_args()

        self.assertEqual(args.router, PROVIDER_NAME)
        self.assertEqual(args.executor, PROVIDER_NAME)

    def test_runtime_openai_api_executor_uses_provider_backend_name(self) -> None:
        class FakeProvider:
            def __init__(self, **_: object) -> None:
                pass

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": "answer"}}],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 3,
                        "total_tokens": 11,
                    },
                    "openai_api": {"latency_ms": 99},
                }

        decision = {
            "task_type": "writing",
            "role": "writer",
            "provider": PROVIDER_NAME,
            "router_model": "gpt-5.4-mini",
            "model": "gpt-5.5",
            "memory_zones": [],
            "router_total_tokens": 12,
        }

        with patch.object(run_experiment, "OpenAIAPIProvider", FakeProvider):
            execution = run_experiment._execute_with_openai_api(
                task="Write one sentence.",
                task_label="writing",
                routing_decision=decision,
                mode="baseline",
                router_name=PROVIDER_NAME,
                executor_name=PROVIDER_NAME,
                executor_model="gpt-5.5",
                timeout_seconds=1,
                debug_raw_response=False,
            )

        self.assertTrue(execution["run_data"]["success"])
        self.assertEqual(execution["run_data"]["provider"], PROVIDER_NAME)
        self.assertEqual(execution["run_data"]["executor"], PROVIDER_NAME)
        self.assertEqual(execution["tokens"]["total_tokens"], 11)


if __name__ == "__main__":
    unittest.main()
