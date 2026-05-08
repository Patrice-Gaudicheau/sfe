"""Tests for the minimal OpenAI API smoke-test script."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime import run_openai_api_smoke


class OpenAIAPISmokeTests(unittest.TestCase):
    def test_smoke_uses_executor_model_and_prints_sanitized_summary(self) -> None:
        class FakeProvider:
            def chat(self, messages, model, max_tokens, temperature):  # type: ignore[no-untyped-def]
                self.messages = messages
                self.model = model
                self.max_tokens = max_tokens
                self.temperature = temperature
                return {
                    "choices": [{"message": {"content": "OK"}}],
                    "usage": {
                        "prompt_tokens": 5,
                        "completion_tokens": 1,
                        "total_tokens": 6,
                    },
                }

        fake_provider = FakeProvider()

        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "sk-test-secret",
                "SFE_OPENAI_EXECUTOR_MODEL": "example-executor-model",
            },
            clear=True,
        ), patch.object(sys, "argv", ["run_openai_api_smoke.py"]), patch.object(
            run_openai_api_smoke, "load_repo_env"
        ), patch.object(
            run_openai_api_smoke,
            "OpenAIAPIProvider",
            return_value=fake_provider,
        ), patch(
            "builtins.print"
        ) as printed:
            exit_code = run_openai_api_smoke.main()

        self.assertEqual(exit_code, 0)
        self.assertEqual(fake_provider.messages, [{"role": "user", "content": "Reply with OK."}])
        self.assertEqual(fake_provider.model, "example-executor-model")
        self.assertEqual(fake_provider.max_tokens, 16)
        self.assertIsNone(fake_provider.temperature)

        output = "\n".join(" ".join(str(arg) for arg in call.args) for call in printed.call_args_list)
        self.assertIn("success: true", output)
        self.assertIn("model: example-executor-model", output)
        self.assertIn("response_text: OK", output)
        self.assertIn("input_tokens: 5", output)
        self.assertNotIn("sk-test-secret", output)

    def test_missing_model_fails_before_provider_call(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-secret"}, clear=True), patch.object(
            sys, "argv", ["run_openai_api_smoke.py"]
        ), patch.object(run_openai_api_smoke, "load_repo_env"), patch.object(
            run_openai_api_smoke, "OpenAIAPIProvider"
        ) as provider:
            exit_code = run_openai_api_smoke.main()

        self.assertEqual(exit_code, 2)
        provider.assert_not_called()


if __name__ == "__main__":
    unittest.main()
