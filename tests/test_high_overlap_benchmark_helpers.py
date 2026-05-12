"""Tests for shared high-overlap benchmark diagnostic helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.high_overlap_benchmark_helpers import build_failure_diagnostics
from runtime.run_high_overlap_poison_pill_benchmark import (
    get_high_overlap_poison_pill_tasks,
    validate_output,
)


class HighOverlapBenchmarkHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_poison_pill_tasks()[0]
        self.valid_output = self.task.expected_answer

    def test_successful_output_has_no_failure_flags(self) -> None:
        diagnostics = build_failure_diagnostics(
            output_validation=validate_output(self.task, self.valid_output),
            provider_error_occurred=False,
            parse_success=True,
            fallback_used=False,
            repair_used=False,
            context_valid=True,
        )

        self.assertTrue(diagnostics["field_extraction_passed"])
        self.assertEqual(diagnostics["failed_field_names"], [])
        self.assertTrue(diagnostics["evidence_reference_passed"])
        self.assertTrue(diagnostics["contamination_free"])
        self.assertEqual(diagnostics["failure_flags"], [])

    def test_repair_is_classified_without_making_success(self) -> None:
        diagnostics = build_failure_diagnostics(
            output_validation=validate_output(self.task, self.valid_output),
            provider_error_occurred=False,
            parse_success=True,
            fallback_used=False,
            repair_used=True,
            context_valid=True,
        )

        self.assertIn("repair_used", diagnostics["failure_flags"])
        self.assertNotIn("field_extraction_failure", diagnostics["failure_flags"])
        self.assertTrue(diagnostics["field_extraction_passed"])


if __name__ == "__main__":
    unittest.main()
