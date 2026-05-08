"""Tests for Lemonade OpenAI-compatible provider URL handling."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.lemonade import _join_openai_compatible_url


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


if __name__ == "__main__":
    unittest.main()
