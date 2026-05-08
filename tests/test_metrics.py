"""Tests for shared benchmark metric helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.metrics import (
    average,
    estimate_char_count_tokens,
    estimate_text_tokens,
    estimated_token_usage,
    percent_reduction,
    percentage,
    success_rate,
)
from runtime.run_large_contextual_benchmark import estimate_tokens


class MetricsTests(unittest.TestCase):
    def test_text_and_char_token_estimates_use_same_chars_per_token_rule(self) -> None:
        text = "a" * 41

        self.assertEqual(estimate_text_tokens(text), 10)
        self.assertEqual(estimate_char_count_tokens(len(text)), 10)
        self.assertEqual(estimate_tokens(text), estimate_text_tokens(text))

    def test_empty_token_estimates_are_zero(self) -> None:
        self.assertEqual(estimate_text_tokens(""), 0)
        self.assertEqual(estimate_char_count_tokens(0), 0)
        self.assertEqual(
            estimated_token_usage("", ""),
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )

    def test_estimated_token_usage_combines_prompt_and_response(self) -> None:
        usage = estimated_token_usage("a" * 20, "b" * 9)

        self.assertEqual(usage["input_tokens"], 5)
        self.assertEqual(usage["output_tokens"], 2)
        self.assertEqual(usage["total_tokens"], 7)

    def test_average_percentage_reduction_and_success_rate(self) -> None:
        self.assertEqual(average([1, 2, 3]), 2.0)
        self.assertEqual(average([]), 0.0)
        self.assertEqual(percentage(25, 100), 25.0)
        self.assertEqual(percentage(25, 0), 0.0)
        self.assertEqual(percent_reduction(100, 40), 60.0)
        self.assertIsNone(percent_reduction(0, 40))
        self.assertEqual(success_rate([{"success": True}, {"success": False}]), 0.5)
        self.assertEqual(success_rate([]), 0.0)


if __name__ == "__main__":
    unittest.main()
