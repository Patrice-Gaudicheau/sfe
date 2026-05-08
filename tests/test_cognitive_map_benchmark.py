"""Tests for the Cognitive Map micro-benchmark."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cognitive_map.zones import REQUIRED_ZONE_NAMES
from runtime.run_cognitive_map_benchmark import (
    BENCHMARK_TASKS,
    run_benchmark,
    run_cognitive_map_mode,
    run_explicit_metadata_mode,
)


class CognitiveMapBenchmarkTests(unittest.TestCase):
    def test_benchmark_task_set_exists(self) -> None:
        labels = {task["task_label"] for task in BENCHMARK_TASKS}

        self.assertGreaterEqual(len(BENCHMARK_TASKS), 5)
        self.assertTrue({"writing", "analysis", "coding", "review", "multi_context"} <= labels)

    def test_explicit_metadata_mode_returns_metrics(self) -> None:
        result = run_explicit_metadata_mode(BENCHMARK_TASKS[0])

        self.assertEqual(result["mode"], "explicit_metadata")
        self.assertTrue(result["success"])
        self.assertGreater(result["audit_size_chars"], 0)
        self.assertEqual(result["audit_size_chars"], result["llm_payload_size_chars"])
        self.assertGreater(result["approximate_token_estimate_audit"], 0)
        self.assertEqual(
            result["approximate_token_estimate_audit"],
            result["approximate_token_estimate_llm_payload"],
        )
        self.assertIn("constructed_prompt", result)
        self.assertNotIn("prompt_or_workspace_size_chars", result)

    def test_cognitive_map_mode_returns_metrics(self) -> None:
        result = run_cognitive_map_mode(BENCHMARK_TASKS[0])

        self.assertEqual(result["mode"], "cognitive_map")
        self.assertTrue(result["success"])
        self.assertGreater(result["audit_size_chars"], 0)
        self.assertGreater(result["llm_payload_size_chars"], 0)
        self.assertLess(result["llm_payload_size_chars"], result["audit_size_chars"])
        self.assertGreater(result["approximate_token_estimate_audit"], 0)
        self.assertGreater(result["approximate_token_estimate_llm_payload"], 0)
        self.assertGreater(result["number_of_fragments"], 0)
        self.assertIn("llm_payload", result)
        self.assertNotIn("prompt_or_workspace_size_chars", result)

    def test_jsonl_result_is_serializable(self) -> None:
        results = run_benchmark(BENCHMARK_TASKS[:1])

        for result in results:
            json.dumps(result, sort_keys=True)

    def test_cognitive_map_mode_has_trace_available(self) -> None:
        result = run_cognitive_map_mode(BENCHMARK_TASKS[0])

        self.assertTrue(result["trace_available"])
        self.assertEqual(result["handoff_count"], 5)
        self.assertEqual(len(result["fragment_hashes"]), 5)
        self.assertEqual(len(result["handoff_trace"]), 5)
        self.assertIn("fragment_hash", result["handoff_trace"][0])

    def test_cognitive_map_mode_activates_all_expected_zones(self) -> None:
        result = run_cognitive_map_mode(BENCHMARK_TASKS[0])

        self.assertEqual(tuple(result["active_zone_names"]), REQUIRED_ZONE_NAMES)


if __name__ == "__main__":
    unittest.main()
