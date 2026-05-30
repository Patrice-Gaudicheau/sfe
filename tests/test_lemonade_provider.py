"""Tests for Lemonade OpenAI-compatible provider URL handling."""

from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.lemonade import LemonadeProvider, _join_openai_compatible_url
from sfe.provider_progress import ProviderCallIdleTimeoutError, collect_progress_events


class LemonadeProviderTests(unittest.TestCase):
    def test_openai_base_url_with_v1_suffix_is_not_double_versioned(self) -> None:
        url = _join_openai_compatible_url(
            "http://127.0.0.1:13305/v1",
            "/v1/chat/completions",
        )

        self.assertEqual(url, "http://127.0.0.1:13305/v1/chat/completions")

    def test_root_base_url_keeps_existing_endpoint_behavior(self) -> None:
        url = _join_openai_compatible_url(
            "http://127.0.0.1:13305",
            "/v1/chat/completions",
        )

        self.assertEqual(url, "http://127.0.0.1:13305/v1/chat/completions")

    def test_non_streaming_call_stalls_when_no_provider_progress_arrives(self) -> None:
        class FakeResponse:
            status = 200

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({"choices": [{"message": {"content": "late"}}]}).encode(
                    "utf-8"
                )

        def slow_urlopen(*_: object, **__: object) -> FakeResponse:
            time.sleep(0.1)
            return FakeResponse()

        events, sink = collect_progress_events()
        provider = LemonadeProvider(base_url="http://local.invalid", timeout=1)
        with patch.dict(
            "os.environ",
            {
                "SFE_PROVIDER_IDLE_TIMEOUT_SECONDS": "0.02",
                "SFE_PROVIDER_INTERNAL_HEARTBEAT_SECONDS": "0.01",
            },
        ), patch("providers.lemonade.urllib.request.urlopen", side_effect=slow_urlopen):
            with self.assertRaises(ProviderCallIdleTimeoutError):
                provider.chat(
                    [{"role": "user", "content": "hello"}],
                    model="qwen-test",
                    progress_sink=sink,
                )

        kinds = [event.kind for event in events]
        self.assertIn("internal_wait", kinds)
        self.assertIn("idle_timeout", kinds)
        self.assertTrue(
            all(
                event.real_provider_signal is False
                for event in events
                if event.kind == "internal_wait"
            )
        )


if __name__ == "__main__":
    unittest.main()
