"""Tests for the large real-world inspired multi-zone benchmark."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_large_real_world_multi_zone_benchmark import (
    BENCHMARK_TYPE,
    TOKEN_REDUCTION_TARGET_PERCENT,
    FixtureLargeRealWorldExecutor,
    FixtureLargeRealWorldSelector,
    _parse_args,
    build_selection,
    execute_task,
    get_large_real_world_tasks,
    run_benchmark,
    source_by_id,
    validate_output,
    validate_selection,
    write_markdown,
)


class FailingSelector:
    provider = "deterministic_test"
    selector_mode = "failing_selector"
    model: str | None = None
    api_path: str | None = None

    def select(self, task: Any, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("selector failed")


class LargeRealWorldBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_large_real_world_tasks()
        self.gateway_task = self.tasks[0]
        self.roadmap_task = self.tasks[1]
        self.selector = FixtureLargeRealWorldSelector()
        self.gateway_selection = self.selector.select(self.gateway_task, {})
        self.roadmap_selection = self.selector.select(self.roadmap_task, {})

    def _selection_without(self, task: Any, omitted_source_id: str) -> dict[str, Any]:
        sources = [
            source_by_id(task, source_id)
            for source_id in task.required_source_ids
            if source_id != omitted_source_id
        ]
        return build_selection(
            task=task,
            selected_sources=sources,
            selector_name="test_missing_required_source",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector omits one required source.",
        )

    def _selection_with_distractor(self, task: Any, distractor_source_id: str) -> dict[str, Any]:
        sources = [source_by_id(task, source_id) for source_id in task.required_source_ids]
        sources.append(source_by_id(task, distractor_source_id))
        return build_selection(
            task=task,
            selected_sources=sources,
            selector_name="test_selects_distractor",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector includes a distractor source.",
        )

    def test_fixture_count_and_structure(self) -> None:
        self.assertEqual(len(self.tasks), 2)
        self.assertEqual(
            {task.fixture_id for task in self.tasks},
            {
                "large_real_world_gateway_integration_gate",
                "large_real_world_benchmark_roadmap_gate",
            },
        )
        for task in self.tasks:
            self.assertEqual(len(task.sources), 14)
            self.assertGreaterEqual(len(task.required_source_ids), 3)
            self.assertLessEqual(len(task.required_source_ids), 5)
            self.assertEqual(len(task.required_source_ids), 4)
            self.assertEqual(len(task.distractor_source_ids), 10)
            self.assertEqual(
                {source.source_id for source in task.sources if source.required},
                set(task.required_source_ids),
            )
            self.assertEqual(
                {source.source_id for source in task.sources if source.distractor},
                set(task.distractor_source_ids),
            )

    def test_unique_source_ids(self) -> None:
        for task in self.tasks:
            source_ids = [source.source_id for source in task.sources]

            self.assertEqual(len(source_ids), len(set(source_ids)))
            self.assertTrue(all(source.source_id and source.role for source in task.sources))

    def test_fixture_themes_cover_required_scenarios(self) -> None:
        themes = {task.task_theme for task in self.tasks}

        self.assertIn("gateway_integration_decision", themes)
        self.assertIn("benchmark_result_roadmap_decision", themes)

    def test_no_single_source_contains_complete_final_answer(self) -> None:
        for task in self.tasks:
            required_values = set(task.expected_fields.values())
            for source in task.sources:
                source_text = source.text.lower()
                present_values = {
                    value for value in required_values if value.lower() in source_text
                }
                self.assertNotEqual(
                    present_values,
                    required_values,
                    f"{task.fixture_id}:{source.source_id} unexpectedly contains the full answer",
                )

    def test_valid_deterministic_result_acceptance(self) -> None:
        report = run_benchmark(self.tasks)
        large_runs = [
            run for run in report["runs"] if run["mode"] == "large_real_world_multi_zone"
        ]

        self.assertEqual(len(large_runs), 2)
        for run in large_runs:
            self.assertTrue(run["required_source_complete"])
            self.assertTrue(run["distractors_omitted"])
            self.assertTrue(run["output_validation_before_repair"])
            self.assertEqual(run["output_repair_status"], "not_supported")
            self.assertTrue(run["honest_large_real_world_pass"])
        self.assertEqual(report["summary"]["honest_large_real_world_pass_rate"], 1.0)
        self.assertEqual(report["summary"]["fallback_count"], 0)

    def test_missing_every_required_source_is_rejected(self) -> None:
        cases = [
            (self.gateway_task, self.gateway_selection, source_id)
            for source_id in self.gateway_task.required_source_ids
        ] + [
            (self.roadmap_task, self.roadmap_selection, source_id)
            for source_id in self.roadmap_task.required_source_ids
        ]

        for task, fixture_selection, missing_source_id in cases:
            with self.subTest(task=task.fixture_id, missing=missing_source_id):
                selection = self._selection_without(task, missing_source_id)
                run = execute_task(
                    task=task,
                    mode="large_real_world_multi_zone",
                    selection=selection,
                    fixture_selection=fixture_selection,
                    repeat_index=1,
                )

                self.assertFalse(run["required_source_complete"])
                self.assertIn(missing_source_id, run["missing_required_source_ids"])
                self.assertFalse(run["honest_large_real_world_pass"])

    def test_selecting_each_distractor_is_rejected(self) -> None:
        cases = [
            (self.gateway_task, self.gateway_selection, source_id)
            for source_id in self.gateway_task.distractor_source_ids
        ] + [
            (self.roadmap_task, self.roadmap_selection, source_id)
            for source_id in self.roadmap_task.distractor_source_ids
        ]

        for task, fixture_selection, distractor_source_id in cases:
            with self.subTest(task=task.fixture_id, distractor=distractor_source_id):
                selection = self._selection_with_distractor(task, distractor_source_id)
                run = execute_task(
                    task=task,
                    mode="large_real_world_multi_zone",
                    selection=selection,
                    fixture_selection=fixture_selection,
                    repeat_index=1,
                )

                self.assertFalse(run["distractors_omitted"])
                self.assertEqual(
                    run["unexpected_distractor_source_ids"],
                    [distractor_source_id],
                )
                self.assertFalse(run["honest_large_real_world_pass"])

    def test_role_mismatch_is_rejected(self) -> None:
        selection = dict(self.gateway_selection)
        selection["source_roles"] = dict(selection["source_roles"])
        selection["source_roles"]["doc-gateway-exclusions-current"] = "architecture_note"

        validation = validate_selection(self.gateway_task, selection)
        run = execute_task(
            task=self.gateway_task,
            mode="large_real_world_multi_zone",
            selection=selection,
            fixture_selection=self.gateway_selection,
            repeat_index=1,
        )

        self.assertFalse(validation["source_roles_valid"])
        self.assertFalse(validation["required_source_complete"])
        self.assertFalse(run["honest_large_real_world_pass"])

    def test_obsolete_answer_is_rejected(self) -> None:
        obsolete_output = self.gateway_task.expected_answer.replace(
            "gateway integration is planned but not implemented",
            "transparent gateway shipped in beta",
        )
        validation = validate_output(self.gateway_task, obsolete_output)

        self.assertFalse(validation["passed"])
        self.assertIn("gateway_status", validation["missing_fields"])

    def test_partial_answer_is_rejected(self) -> None:
        partial_output = self.roadmap_task.expected_answer.replace(
            "broad real-world generalization remains unproven",
            "",
        )
        validation = validate_output(self.roadmap_task, partial_output)
        run = execute_task(
            task=self.roadmap_task,
            mode="large_real_world_multi_zone",
            selection=self.roadmap_selection,
            fixture_selection=self.roadmap_selection,
            repeat_index=1,
            output_override=partial_output,
        )

        self.assertFalse(validation["passed"])
        self.assertIn("unproven_scope", validation["missing_fields"])
        self.assertFalse(run["honest_large_real_world_pass"])

    def test_misleading_answer_is_rejected(self) -> None:
        misleading_output = self.roadmap_task.expected_answer.replace(
            "large real-world inspired multi-zone benchmark",
            "broad repository corpus benchmark",
        )
        validation = validate_output(self.roadmap_task, misleading_output)

        self.assertFalse(validation["passed"])
        self.assertIn("next_benchmark", validation["missing_fields"])

    def test_decorated_evidence_ids_are_rejected(self) -> None:
        decorated_output = self.gateway_task.expected_answer.replace(
            "doc-gateway-routing-policy",
            "SOURCE doc-gateway-routing-policy (routing_policy)",
        )
        validation = validate_output(self.gateway_task, decorated_output)

        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["evidence_reference_validation"]["missing_source_ids"],
            ["doc-gateway-routing-policy"],
        )
        self.assertEqual(
            validation["evidence_reference_validation"]["unexpected_source_ids"],
            ["SOURCE doc-gateway-routing-policy (routing_policy)"],
        )

    def test_fallback_disqualifies_honest_pass(self) -> None:
        report = run_benchmark([self.gateway_task], selector=FailingSelector())  # type: ignore[arg-type]
        large_run = [
            run for run in report["runs"] if run["mode"] == "large_real_world_multi_zone"
        ][0]

        self.assertEqual(large_run["selector"], "fixture_fallback_after_selector_error")
        self.assertFalse(large_run["selector_success"])
        self.assertTrue(large_run["selector_used_fallback"])
        self.assertTrue(large_run["output_validation_before_repair"])
        self.assertFalse(large_run["honest_large_real_world_pass"])
        self.assertEqual(report["summary"]["fallback_count"], 1)

    def test_token_accounting_consistency_and_threshold(self) -> None:
        report = run_benchmark(self.tasks)
        summary = report["summary"]
        large_runs = [
            run for run in report["runs"] if run["mode"] == "large_real_world_multi_zone"
        ]

        self.assertGreaterEqual(
            summary["average_token_reduction_percent"],
            TOKEN_REDUCTION_TARGET_PERCENT,
        )
        self.assertTrue(summary["token_reduction_target_met"])
        for run in large_runs:
            self.assertLess(
                run["total_composed_context_token_estimate"],
                run["full_context_baseline_token_estimate"],
            )
            self.assertGreaterEqual(
                run["token_reduction_percent"],
                TOKEN_REDUCTION_TARGET_PERCENT,
            )
            self.assertEqual(
                run["selected_source_token_estimate"],
                sum(run["selected_source_token_estimates"].values()),
            )
            self.assertEqual(
                run["total_composed_context_token_estimate"],
                sum(run["selected_source_token_estimates"].values()),
            )
            self.assertEqual(
                run["suppressed_source_token_estimate"],
                sum(run["suppressed_source_token_estimates"].values()),
            )
            self.assertEqual(
                run["full_context_baseline_token_estimate"],
                run["selected_source_token_estimate"]
                + run["suppressed_source_token_estimate"],
            )
            self.assertEqual(
                set(run["suppressed_source_ids"]),
                set(run["distractor_source_ids"]),
            )

    def test_default_cli_is_provider_free(self) -> None:
        with patch.object(sys, "argv", ["run_large_real_world_multi_zone_benchmark.py"]):
            args = _parse_args()

        self.assertEqual(args.repeat, 1)
        self.assertIsNone(args.limit)
        report = run_benchmark(self.tasks)

        self.assertEqual(report["metadata"]["selector_provider"], "deterministic_mock")
        self.assertEqual(report["metadata"]["executor_provider"], "deterministic_mock")
        self.assertIsNone(report["metadata"]["selector_model"])
        self.assertIsNone(report["metadata"]["executor_model"])

    def test_report_includes_required_fields(self) -> None:
        report = run_benchmark(self.tasks)
        summary = report["summary"]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        for field in (
            "honest_large_real_world_pass_rate",
            "required_source_completeness_rate",
            "distractor_rejection_rate",
            "fallback_count",
            "output_validation_complete_rate",
            "average_full_context_baseline_tokens",
            "average_selected_source_tokens",
            "average_composed_context_tokens",
            "average_token_reduction_percent",
            "token_reduction_target_met",
            "fixtures",
        ):
            self.assertIn(field, summary)
        self.assertEqual(len(summary["fixtures"]), 2)
        for fixture in summary["fixtures"]:
            self.assertIn("selected_source_ids", fixture)
            self.assertIn("suppressed_source_ids", fixture)
            self.assertGreater(len(fixture["suppressed_source_ids"]), len(fixture["selected_source_ids"]))

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "large_real_world_report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Large Real-World Inspired Multi-Zone Benchmark", markdown)
        self.assertIn("not proof of broad real-world generalization", markdown)
        self.assertIn("Deterministic validation is the source of truth", markdown)
        self.assertIn("Honest large real-world pass rate:", markdown)
        self.assertIn("Fallback count:", markdown)
        self.assertIn("Token reduction target met: True", markdown)
        self.assertIn("Suppressed sources", markdown)
        self.assertIn("large_real_world_gateway_integration_gate", markdown)
        self.assertIn("large_real_world_benchmark_roadmap_gate", markdown)


if __name__ == "__main__":
    unittest.main()
