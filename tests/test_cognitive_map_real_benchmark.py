"""Tests for the Cognitive Map real execution benchmark dry-run path."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_cognitive_map_real_benchmark import (
    REAL_BENCHMARK_TASKS,
    build_reflection_payload,
    build_payload,
    execute_payload,
    run_real_benchmark,
    summarize_results,
    verify_task_output,
    write_jsonl,
)


class CognitiveMapRealBenchmarkTests(unittest.TestCase):
    def test_verify_task_output_passes_non_empty_generic_task(self) -> None:
        result = verify_task_output(
            task_label="analysis",
            task_prompt="Compare two benchmark payload styles.",
            output="Structured payloads can make benchmark traces easier to inspect.",
        )

        self.assertTrue(result["passed"])
        self.assertIsNone(result["failed_constraint"])

    def test_verify_task_output_fails_generic_label_like_analysis_output(self) -> None:
        result = verify_task_output(
            task_label="analysis",
            task_prompt="Compare two benchmark payload styles.",
            output="analysis",
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_constraint"], "label_like_output")

    def test_verify_task_output_fails_generic_too_short_output(self) -> None:
        result = verify_task_output(
            task_label="analysis",
            task_prompt="Compare two benchmark payload styles.",
            output="Too brief.",
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_constraint"], "minimum_word_count")

    def test_verify_task_output_fails_generic_scaffold_status_text(self) -> None:
        result = verify_task_output(
            task_label="writing",
            task_prompt="Write one concise update.",
            output="Final output ready from verified cognitive-map flow.",
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_constraint"], "non_scaffold_output")

    def test_verify_task_output_classification_passes_exact_allowed_label(self) -> None:
        result = verify_task_output(
            task_label="classification",
            task_prompt=(
                "Classify this task as writing, analysis, coding, review, or "
                "planning: check benchmark output."
            ),
            output="review",
        )

        self.assertTrue(result["passed"])

    def test_verify_task_output_classification_fails_explanation_or_invalid_label(self) -> None:
        task_prompt = (
            "Classify this task as writing, analysis, coding, review, or "
            "planning: check benchmark output."
        )

        explained = verify_task_output(
            task_label="classification",
            task_prompt=task_prompt,
            output="review because it checks output",
        )
        invalid = verify_task_output(
            task_label="classification",
            task_prompt=task_prompt,
            output="validation",
        )

        self.assertFalse(explained["passed"])
        self.assertFalse(invalid["passed"])
        self.assertEqual(explained["failed_constraint"], "classification_label")
        self.assertEqual(invalid["failed_constraint"], "classification_label")

    def test_verify_task_output_detects_wrong_bullet_count(self) -> None:
        result = verify_task_output(
            task_label="constraint_following",
            task_prompt="Answer in exactly two bullet points about concise prompts.",
            output="- One bullet only.",
        )

        self.assertFalse(result["passed"])
        self.assertEqual(result["failed_constraint"], "bullet_count")

    def test_build_reflection_payload_is_compact_and_visible_answer_only(self) -> None:
        payload = build_reflection_payload(
            original_payload="Task: Answer in exactly two bullet points.",
            previous_output="- One bullet only.",
            verification_result={
                "passed": False,
                "reason": "Expected exactly 2 bullet points, found 1.",
                "failed_constraint": "bullet_count",
            },
        )

        self.assertIn("Answer in exactly two bullet points.", payload)
        self.assertIn("- One bullet only.", payload)
        self.assertIn("Expected exactly 2 bullet points, found 1.", payload)
        self.assertNotIn("chain-of-thought", payload.lower())

    def test_cognitive_map_retry_uses_reflection_and_aggregates_metrics(self) -> None:
        class FakeProvider:
            def __init__(self) -> None:
                self.prompts: list[str] = []
                self.outputs = ["review because it checks output", "review"]

            def chat(self, messages: list[dict[str, str]], **_: object) -> dict[str, object]:
                self.prompts.append(messages[0]["content"])
                output = self.outputs.pop(0)
                return {
                    "choices": [{"message": {"content": output}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    },
                }

        task = next(
            task for task in REAL_BENCHMARK_TASKS if task["task_label"] == "classification"
        )
        provider = FakeProvider()
        result = execute_payload(
            task_label=task["task_label"],
            mode="cognitive_map",
            payload_data=build_payload(task, "cognitive_map"),
            provider=provider,  # type: ignore[arg-type]
            model="fake-model",
            base_url="http://127.0.0.1:13305",
            dry_run=False,
            repeat_index=1,
            max_reflection_attempts=1,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["verification_passed"])
        self.assertTrue(result["reflection_triggered"])
        self.assertEqual(result["reflection_attempts_used"], 1)
        self.assertEqual(result["final_attempt_index"], 1)
        self.assertEqual(result["provider_reported_prompt_tokens"], 20)
        self.assertEqual(result["provider_reported_completion_tokens"], 10)
        self.assertEqual(result["provider_reported_total_tokens"], 30)
        self.assertEqual(result["output_text"], "review")
        self.assertIn("Verification failure", provider.prompts[1])

    def test_cognitive_map_retry_triggers_for_too_short_generic_output(self) -> None:
        class FakeProvider:
            def __init__(self) -> None:
                self.prompts: list[str] = []
                self.outputs = [
                    "analysis",
                    "Structured payloads make benchmark traces easier to inspect.",
                ]

            def chat(self, messages: list[dict[str, str]], **_: object) -> dict[str, object]:
                self.prompts.append(messages[0]["content"])
                output = self.outputs.pop(0)
                return {
                    "choices": [{"message": {"content": output}}],
                    "usage": {
                        "prompt_tokens": 8,
                        "completion_tokens": 4,
                        "total_tokens": 12,
                    },
                }

        task = next(task for task in REAL_BENCHMARK_TASKS if task["task_label"] == "analysis")
        provider = FakeProvider()
        result = execute_payload(
            task_label=task["task_label"],
            mode="cognitive_map",
            payload_data=build_payload(task, "cognitive_map"),
            provider=provider,  # type: ignore[arg-type]
            model="fake-model",
            base_url="http://127.0.0.1:13305",
            dry_run=False,
            repeat_index=1,
            max_reflection_attempts=1,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["verification_passed"])
        self.assertTrue(result["reflection_triggered"])
        self.assertEqual(result["reflection_attempts_used"], 1)
        self.assertEqual(result["provider_reported_total_tokens"], 24)
        self.assertEqual(
            result["output_text"],
            "Structured payloads make benchmark traces easier to inspect.",
        )
        self.assertIn("exactly one known task label", provider.prompts[1])

    def test_explicit_metadata_output_is_verified_when_valid(self) -> None:
        class FakeProvider:
            def chat(self, messages: list[dict[str, str]], **_: object) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": "review"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }

        task = next(
            task for task in REAL_BENCHMARK_TASKS if task["task_label"] == "classification"
        )
        result = execute_payload(
            task_label=task["task_label"],
            mode="explicit_metadata",
            payload_data=build_payload(task, "explicit_metadata"),
            provider=FakeProvider(),  # type: ignore[arg-type]
            model="fake-model",
            base_url="http://127.0.0.1:13305",
            dry_run=False,
            repeat_index=1,
            max_reflection_attempts=1,
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["verification_passed"])
        self.assertEqual(result["verification_reason"], "Output is exactly one allowed label.")
        self.assertIsNone(result["verification_failed_constraint"])
        self.assertEqual(result["reflection_attempts_used"], 0)
        self.assertFalse(result["reflection_triggered"])
        self.assertEqual(result["final_attempt_index"], 1)

    def test_invalid_explicit_metadata_output_can_fail_verification(self) -> None:
        class FakeProvider:
            def chat(self, messages: list[dict[str, str]], **_: object) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": "review because it checks output"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 6,
                        "total_tokens": 16,
                    },
                }

        task = next(
            task for task in REAL_BENCHMARK_TASKS if task["task_label"] == "classification"
        )
        result = execute_payload(
            task_label=task["task_label"],
            mode="explicit_metadata",
            payload_data=build_payload(task, "explicit_metadata"),
            provider=FakeProvider(),  # type: ignore[arg-type]
            model="fake-model",
            base_url="http://127.0.0.1:13305",
            dry_run=False,
            repeat_index=1,
            max_reflection_attempts=1,
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["verification_passed"])
        self.assertEqual(result["verification_failed_constraint"], "classification_label")
        self.assertEqual(result["reflection_attempts_used"], 0)
        self.assertFalse(result["reflection_triggered"])
        self.assertEqual(result["final_attempt_index"], 1)

    def test_default_task_set_has_ten_unique_labels(self) -> None:
        labels = [task["task_label"] for task in REAL_BENCHMARK_TASKS]

        self.assertEqual(len(REAL_BENCHMARK_TASKS), 10)
        self.assertEqual(len(labels), len(set(labels)))

    def test_full_dry_run_produces_twenty_results(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS,
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
        )

        self.assertEqual(len(results), 20)

    def test_repeat_dry_run_produces_expected_number_of_results(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:2],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
            repeat=3,
            max_reflection_attempts=1,
        )

        self.assertEqual(len(results), 12)
        self.assertEqual(
            [result["repeat_index"] for result in results],
            [1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3],
        )

    def test_default_repeat_remains_one(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual({result["repeat_index"] for result in results}, {1})

    def test_aggregate_summary_works(self) -> None:
        results = [
            {
                "mode": "explicit_metadata",
                "provider_reported_prompt_tokens": 10,
                "provider_reported_completion_tokens": 5,
                "provider_reported_total_tokens": 15,
                "latency_ms": 100,
                "success": True,
            },
            {
                "mode": "explicit_metadata",
                "provider_reported_prompt_tokens": 20,
                "provider_reported_completion_tokens": 10,
                "provider_reported_total_tokens": 30,
                "latency_ms": 200,
                "success": False,
            },
            {
                "mode": "cognitive_map",
                "provider_reported_prompt_tokens": None,
                "provider_reported_completion_tokens": None,
                "provider_reported_total_tokens": None,
                "latency_ms": 0,
                "success": True,
            },
        ]

        summary = summarize_results(results)

        self.assertEqual(summary["explicit_metadata"]["runs"], 2)
        self.assertEqual(summary["explicit_metadata"]["prompt_tokens_sum"], 30)
        self.assertEqual(summary["explicit_metadata"]["completion_tokens_sum"], 15)
        self.assertEqual(summary["explicit_metadata"]["total_tokens_sum"], 45)
        self.assertEqual(summary["explicit_metadata"]["mean_total_tokens"], 22.5)
        self.assertEqual(summary["explicit_metadata"]["latency_ms_sum"], 300)
        self.assertEqual(summary["explicit_metadata"]["mean_latency_ms"], 150)
        self.assertEqual(summary["explicit_metadata"]["min_latency_ms"], 100)
        self.assertEqual(summary["explicit_metadata"]["max_latency_ms"], 200)
        self.assertEqual(summary["explicit_metadata"]["success_count"], 1)
        self.assertEqual(summary["explicit_metadata"]["failure_count"], 1)
        self.assertEqual(summary["cognitive_map"]["total_tokens_sum"], 0)

    def test_combined_token_metrics_stay_null_when_executor_usage_is_unavailable(self) -> None:
        class TimeoutLikeProvider:
            def chat(self, messages: list[dict[str, str]], **_: object) -> dict[str, object]:
                raise RuntimeError("timeout")

        task = REAL_BENCHMARK_TASKS[0]
        result = execute_payload(
            task_label=task["task_label"],
            mode="explicit_metadata",
            payload_data=build_payload(task, "explicit_metadata"),
            provider=TimeoutLikeProvider(),  # type: ignore[arg-type]
            model="fake-model",
            base_url="http://127.0.0.1:13305",
            dry_run=False,
            repeat_index=1,
            max_reflection_attempts=1,
        )

        self.assertIsNone(result["executor_total_tokens"])
        self.assertIsNone(result["combined_prompt_tokens"])
        self.assertIsNone(result["combined_completion_tokens"])
        self.assertIsNone(result["combined_total_tokens"])
        self.assertGreaterEqual(result["combined_latency_ms"], result["executor_latency_ms"])

    def test_dry_run_produces_results_for_both_modes(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
        )

        self.assertEqual(
            [result["mode"] for result in results],
            ["explicit_metadata", "cognitive_map"],
        )
        self.assertTrue(all(result["dry_run"] for result in results))

    def test_deterministic_zone_builder_metrics_are_recorded(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
            cognitive_map_zone_builder="deterministic",
        )
        cognitive_map = next(result for result in results if result["mode"] == "cognitive_map")

        self.assertEqual(cognitive_map["comparison_mode"], "cognitive_map_deterministic")
        self.assertEqual(cognitive_map["zone_builder_mode"], "deterministic")
        self.assertEqual(cognitive_map["zone_builder_latency_ms"], 0)
        self.assertEqual(cognitive_map["zone_builder_total_tokens"], 0)
        self.assertTrue(cognitive_map["zone_builder_success"])
        self.assertFalse(cognitive_map["zone_builder_fallback_used"])
        self.assertEqual(cognitive_map["combined_latency_ms"], cognitive_map["latency_ms"])

    def test_llm_intent_zone_builder_replaces_user_intent_zone_when_valid(self) -> None:
        class FakeRouterProvider:
            def chat(self, messages: list[dict[str, str]], **_: object) -> dict[str, object]:
                self.messages = messages
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "intent": "write project update",
                                        "task_label": "writing",
                                        "constraints": ["concise"],
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 11,
                        "completion_tokens": 7,
                        "total_tokens": 18,
                    },
                }

        task = REAL_BENCHMARK_TASKS[0]
        payload = build_payload(
            task,
            "cognitive_map",
            cognitive_map_zone_builder="llm_intent",
            zone_router_provider=FakeRouterProvider(),  # type: ignore[arg-type]
            zone_router_model="router-model",
            dry_run=False,
        )

        self.assertEqual(payload["comparison_mode"], "cognitive_map_llm_intent")
        self.assertIn("Intent extracted from router: write project update", payload["audit_text"])
        self.assertIn(task["task"], payload["llm_payload"])
        self.assertEqual(payload["zone_builder_metrics"]["zone_builder_model"], "router-model")
        self.assertEqual(payload["zone_builder_metrics"]["zone_builder_total_tokens"], 18)
        self.assertTrue(payload["zone_builder_metrics"]["zone_builder_success"])
        self.assertFalse(payload["zone_builder_metrics"]["zone_builder_fallback_used"])

    def test_invalid_llm_intent_zone_builder_falls_back_deterministically(self) -> None:
        class FakeRouterProvider:
            def chat(self, messages: list[dict[str, str]], **_: object) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": "not json"}}],
                    "usage": {
                        "prompt_tokens": 3,
                        "completion_tokens": 2,
                        "total_tokens": 5,
                    },
                }

        task = REAL_BENCHMARK_TASKS[0]
        payload = build_payload(
            task,
            "cognitive_map",
            cognitive_map_zone_builder="llm_intent",
            zone_router_provider=FakeRouterProvider(),  # type: ignore[arg-type]
            zone_router_model="router-model",
            dry_run=False,
        )

        self.assertEqual(payload["comparison_mode"], "cognitive_map_llm_intent")
        self.assertIn("Intent extracted from prompt:", payload["audit_text"])
        self.assertEqual(payload["zone_builder_metrics"]["zone_builder_total_tokens"], 5)
        self.assertFalse(payload["zone_builder_metrics"]["zone_builder_success"])
        self.assertTrue(payload["zone_builder_metrics"]["zone_builder_fallback_used"])
        self.assertEqual(
            payload["zone_builder_metrics"]["zone_builder_fallback_reason"],
            "invalid_json",
        )

    def test_dry_run_with_max_reflection_attempts_keeps_zero_attempts_used(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
            max_reflection_attempts=1,
        )
        cognitive_map = next(result for result in results if result["mode"] == "cognitive_map")
        explicit_metadata = next(
            result for result in results if result["mode"] == "explicit_metadata"
        )

        self.assertEqual(cognitive_map["reflection_attempts_used"], 0)
        self.assertFalse(cognitive_map["reflection_triggered"])
        self.assertTrue(cognitive_map["verification_passed"])
        self.assertEqual(explicit_metadata["reflection_attempts_used"], 0)
        self.assertFalse(explicit_metadata["reflection_triggered"])
        self.assertTrue(explicit_metadata["verification_passed"])
        self.assertEqual(explicit_metadata["final_attempt_index"], 1)

    def test_cli_dry_run_accepts_max_reflection_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "results.jsonl"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PROJECT_ROOT / "runtime" / "run_cognitive_map_real_benchmark.py"),
                    "--dry-run",
                    "--limit-tasks",
                    "1",
                    "--max-reflection-attempts",
                    "1",
                    "--output-path",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

        self.assertIn("refl", completed.stdout)
        self.assertIn("verif", completed.stdout)

    def test_jsonl_result_is_serializable(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
        )

        for result in results:
            json.dumps(result, sort_keys=True)

    def test_jsonl_result_contains_reflection_fields(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
            max_reflection_attempts=1,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "results.jsonl"
            write_jsonl(output_path, results)
            row = json.loads(output_path.read_text(encoding="utf-8").splitlines()[0])

        for field in (
            "verification_passed",
            "verification_reason",
            "verification_failed_constraint",
            "reflection_attempts_used",
            "reflection_triggered",
            "final_attempt_index",
            "zone_builder_mode",
            "zone_builder_latency_ms",
            "zone_builder_prompt_tokens",
            "zone_builder_completion_tokens",
            "zone_builder_total_tokens",
            "zone_builder_success",
            "zone_builder_fallback_used",
            "zone_builder_fallback_reason",
            "combined_prompt_tokens",
            "combined_completion_tokens",
            "combined_total_tokens",
            "combined_latency_ms",
        ):
            self.assertIn(field, row)

    def test_cognitive_map_payload_is_smaller_than_audit_snapshot(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
        )
        cognitive_map = next(result for result in results if result["mode"] == "cognitive_map")

        self.assertLess(
            cognitive_map["llm_payload_size_chars"],
            cognitive_map["audit_size_chars"],
        )

    def test_cognitive_map_payload_includes_original_task_intent(self) -> None:
        task = REAL_BENCHMARK_TASKS[0]
        payload = build_payload(task, "cognitive_map")

        self.assertIn(task["task"], payload["llm_payload"])

    def test_cognitive_map_payload_is_not_generic_scaffold_text(self) -> None:
        payload = build_payload(REAL_BENCHMARK_TASKS[0], "cognitive_map")

        self.assertNotEqual(
            payload["llm_payload"],
            "Final output ready from verified cognitive-map flow.",
        )
        self.assertNotIn(
            "output_zone received handoff_verified_output",
            payload["llm_payload"],
        )
        self.assertNotIn(
            "Final output ready from verified cognitive-map flow.",
            payload["llm_payload"],
        )

    def test_classification_payload_preserves_label_choices(self) -> None:
        task = next(
            task for task in REAL_BENCHMARK_TASKS if task["task_label"] == "classification"
        )
        payload = build_payload(task, "cognitive_map")

        self.assertIn(task["task"], payload["llm_payload"])
        for label in ("writing", "analysis", "coding", "review", "planning"):
            self.assertIn(label, payload["llm_payload"])
        self.assertIn(
            "For checking or validating benchmark output/results, choose review.",
            payload["llm_payload"],
        )
        self.assertIn(
            "Return exactly one of the allowed labels. Do not explain.",
            payload["llm_payload"],
        )

    def test_debugging_payload_preserves_edge_case_language(self) -> None:
        task = next(
            task for task in REAL_BENCHMARK_TASKS if task["task_label"] == "debugging"
        )
        payload = build_payload(task, "cognitive_map")

        self.assertIn("run_count is zero", payload["llm_payload"])
        self.assertIn("zero-count", payload["llm_payload"])

    def test_explicit_metadata_audit_and_payload_are_equal(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
        )
        explicit_metadata = next(
            result for result in results if result["mode"] == "explicit_metadata"
        )

        self.assertEqual(
            explicit_metadata["audit_size_chars"],
            explicit_metadata["llm_payload_size_chars"],
        )

    def test_trace_availability_by_mode(self) -> None:
        results = run_real_benchmark(
            tasks=REAL_BENCHMARK_TASKS[:1],
            model="dry-run-model",
            base_url="http://127.0.0.1:13305",
            timeout_seconds=1,
            dry_run=True,
        )
        explicit_metadata = next(
            result for result in results if result["mode"] == "explicit_metadata"
        )
        cognitive_map = next(result for result in results if result["mode"] == "cognitive_map")

        self.assertFalse(explicit_metadata["trace_available"])
        self.assertTrue(cognitive_map["trace_available"])
        self.assertEqual(cognitive_map["handoff_count"], 5)


if __name__ == "__main__":
    unittest.main()
