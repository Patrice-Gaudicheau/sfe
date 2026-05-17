"""Tests for the minimal real-world inspired multi-zone benchmark."""

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

from runtime.run_minimal_real_world_multi_zone_benchmark import (
    BENCHMARK_TYPE,
    FixtureRealWorldExecutor,
    FixtureRealWorldSelector,
    _parse_args,
    build_selection,
    execute_task,
    get_minimal_real_world_tasks,
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


class MinimalRealWorldBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_minimal_real_world_tasks()
        self.licensing_task = self.tasks[0]
        self.roadmap_task = self.tasks[1]
        self.selector = FixtureRealWorldSelector()
        self.licensing_selection = self.selector.select(self.licensing_task, {})
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

    def test_fixture_structure(self) -> None:
        self.assertEqual(len(self.tasks), 2)
        self.assertEqual(
            {task.fixture_id for task in self.tasks},
            {
                "minimal_real_world_licensing_policy_gate",
                "minimal_real_world_benchmark_roadmap_gate",
            },
        )
        for task in self.tasks:
            self.assertEqual(len(task.required_source_ids), 4)
            self.assertEqual(len(task.distractor_source_ids), 3)
            self.assertEqual(len(task.sources), 7)
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

    def test_licensing_fixture_reflects_apache_open_contribution_posture(self) -> None:
        fields = self.licensing_task.expected_fields

        self.assertEqual(fields["license_marker"], "Apache License 2.0")
        self.assertEqual(
            fields["commercial_permission"],
            "commercial use is permitted under Apache-2.0",
        )
        self.assertIn("issues and pull requests are welcome", fields["contribution_policy"])

    def test_no_single_document_contains_all_required_answer_fields(self) -> None:
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

    def test_complete_required_source_selection_passes(self) -> None:
        report = run_benchmark(self.tasks)
        real_world_runs = [
            run for run in report["runs"] if run["mode"] == "minimal_real_world_multi_zone"
        ]

        self.assertEqual(len(real_world_runs), 2)
        for run in real_world_runs:
            self.assertTrue(run["required_source_complete"])
            self.assertTrue(run["distractors_omitted"])
            self.assertTrue(run["output_validation_before_repair"])
            self.assertTrue(run["honest_minimal_real_world_pass"])
        self.assertEqual(report["summary"]["honest_minimal_real_world_pass_rate"], 1.0)

    def test_missing_required_source_fails_for_each_fixture(self) -> None:
        cases = [
            (self.licensing_task, self.licensing_selection, source_id)
            for source_id in self.licensing_task.required_source_ids
        ] + [
            (self.roadmap_task, self.roadmap_selection, source_id)
            for source_id in self.roadmap_task.required_source_ids
        ]

        for task, fixture_selection, missing_source_id in cases:
            with self.subTest(task=task.fixture_id, missing=missing_source_id):
                selection = self._selection_without(task, missing_source_id)
                run = execute_task(
                    task=task,
                    mode="minimal_real_world_multi_zone",
                    selection=selection,
                    fixture_selection=fixture_selection,
                    repeat_index=1,
                )

                self.assertFalse(run["required_source_complete"])
                self.assertIn(missing_source_id, run["missing_required_source_ids"])
                self.assertFalse(run["honest_minimal_real_world_pass"])

    def test_wrong_source_role_fails_selection_completeness(self) -> None:
        selection = dict(self.licensing_selection)
        selection["source_roles"] = dict(selection["source_roles"])
        selection["source_roles"]["doc-optional-services-note"] = "readme_license_summary"

        validation = validate_selection(self.licensing_task, selection)
        run = execute_task(
            task=self.licensing_task,
            mode="minimal_real_world_multi_zone",
            selection=selection,
            fixture_selection=self.licensing_selection,
            repeat_index=1,
        )

        self.assertFalse(validation["source_roles_valid"])
        self.assertFalse(validation["required_source_complete"])
        self.assertFalse(run["honest_minimal_real_world_pass"])

    def test_plausible_obsolete_and_insufficient_distractors_fail(self) -> None:
        cases = [
            (self.licensing_task, self.licensing_selection, "doc-legacy-mit-license-note"),
            (self.licensing_task, self.licensing_selection, "doc-hosted-demo-operations-note"),
            (self.licensing_task, self.licensing_selection, "doc-community-fork-faq-draft"),
            (self.roadmap_task, self.roadmap_selection, "doc-openai-smoke-announcement"),
            (self.roadmap_task, self.roadmap_selection, "doc-old-roadmap-real-corpus"),
            (self.roadmap_task, self.roadmap_selection, "doc-token-savings-note"),
        ]

        for task, fixture_selection, distractor_source_id in cases:
            with self.subTest(task=task.fixture_id, distractor=distractor_source_id):
                selection = self._selection_with_distractor(task, distractor_source_id)
                run = execute_task(
                    task=task,
                    mode="minimal_real_world_multi_zone",
                    selection=selection,
                    fixture_selection=fixture_selection,
                    repeat_index=1,
                )

                self.assertFalse(run["distractors_omitted"])
                self.assertEqual(
                    run["unexpected_distractor_source_ids"],
                    [distractor_source_id],
                )
                self.assertFalse(run["honest_minimal_real_world_pass"])

    def test_wrong_evidence_source_ids_fail(self) -> None:
        wrong_output = self.licensing_task.expected_answer.replace(
            "doc-contribution-policy-note",
            "doc-legacy-mit-license-note",
        )
        output_validation = validate_output(self.licensing_task, wrong_output)
        run = execute_task(
            task=self.licensing_task,
            mode="minimal_real_world_multi_zone",
            selection=self.licensing_selection,
            fixture_selection=self.licensing_selection,
            repeat_index=1,
            output_override=wrong_output,
        )

        self.assertFalse(output_validation["passed"])
        self.assertEqual(
            output_validation["evidence_reference_validation"]["missing_source_ids"],
            ["doc-contribution-policy-note"],
        )
        self.assertEqual(
            output_validation["evidence_reference_validation"]["unexpected_source_ids"],
            ["doc-legacy-mit-license-note"],
        )
        self.assertFalse(run["output_validation_before_repair"])
        self.assertFalse(run["honest_minimal_real_world_pass"])

    def test_decorated_evidence_source_ids_fail(self) -> None:
        decorated_output = self.licensing_task.expected_answer.replace(
            "doc-readme-licensing-note",
            "SOURCE doc-readme-licensing-note (readme_license_summary)",
        )

        validation = validate_output(self.licensing_task, decorated_output)

        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["evidence_reference_validation"]["missing_source_ids"],
            ["doc-readme-licensing-note"],
        )
        self.assertEqual(
            validation["evidence_reference_validation"]["unexpected_source_ids"],
            ["SOURCE doc-readme-licensing-note (readme_license_summary)"],
        )

    def test_partial_answer_rejected(self) -> None:
        partial_output = self.roadmap_task.expected_answer.replace(
            "broad real-world generalization is not proven",
            "",
        )
        validation = validate_output(self.roadmap_task, partial_output)
        run = execute_task(
            task=self.roadmap_task,
            mode="minimal_real_world_multi_zone",
            selection=self.roadmap_selection,
            fixture_selection=self.roadmap_selection,
            repeat_index=1,
            output_override=partial_output,
        )

        self.assertFalse(validation["passed"])
        self.assertIn("not_proven", validation["missing_fields"])
        self.assertFalse(run["honest_minimal_real_world_pass"])

    def test_obsolete_or_misleading_answer_rejected(self) -> None:
        obsolete_answer = self.licensing_task.expected_answer.replace(
            "Apache License 2.0",
            "MIT-style license",
        )

        validation = validate_output(self.licensing_task, obsolete_answer)

        self.assertFalse(validation["passed"])
        self.assertIn("license_marker", validation["missing_fields"])

    def test_fallback_makes_honest_pass_false(self) -> None:
        report = run_benchmark([self.licensing_task], selector=FailingSelector())  # type: ignore[arg-type]
        real_world_run = [
            run for run in report["runs"] if run["mode"] == "minimal_real_world_multi_zone"
        ][0]

        self.assertEqual(real_world_run["selector"], "fixture_fallback_after_selector_error")
        self.assertFalse(real_world_run["selector_success"])
        self.assertTrue(real_world_run["selector_used_fallback"])
        self.assertTrue(real_world_run["output_validation_before_repair"])
        self.assertFalse(real_world_run["honest_minimal_real_world_pass"])
        self.assertEqual(report["summary"]["fallback_count"], 1)

    def test_output_validation_failure_makes_honest_pass_false(self) -> None:
        incomplete_output = self.licensing_task.expected_answer.replace(
            "commercial use is permitted under Apache-2.0",
            "",
        )
        run = execute_task(
            task=self.licensing_task,
            mode="minimal_real_world_multi_zone",
            selection=self.licensing_selection,
            fixture_selection=self.licensing_selection,
            repeat_index=1,
            output_override=incomplete_output,
        )

        self.assertFalse(run["output_validation_before_repair"])
        self.assertIsNone(run["output_validation_after_repair"])
        self.assertEqual(run["output_repair_status"], "not_supported")
        self.assertFalse(run["honest_minimal_real_world_pass"])

    def test_default_cli_is_provider_free(self) -> None:
        with patch.object(sys, "argv", ["run_minimal_real_world_multi_zone_benchmark.py"]):
            args = _parse_args()

        self.assertEqual(args.repeat, 1)
        self.assertIsNone(args.limit)
        report = run_benchmark(self.tasks)

        self.assertEqual(report["metadata"]["selector_provider"], "deterministic_mock")
        self.assertEqual(report["metadata"]["executor_provider"], "deterministic_mock")
        self.assertIsNone(report["metadata"]["selector_model"])
        self.assertIsNone(report["metadata"]["executor_model"])

    def test_report_includes_honest_fields_and_token_estimates(self) -> None:
        report = run_benchmark(self.tasks)
        summary = report["summary"]
        real_world_runs = [
            run for run in report["runs"] if run["mode"] == "minimal_real_world_multi_zone"
        ]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        for field in (
            "honest_minimal_real_world_pass_rate",
            "required_source_completeness_rate",
            "distractor_rejection_rate",
            "fallback_count",
            "output_validation_complete_rate",
            "output_validation_after_repair_rate",
            "average_token_reduction_percent",
            "actual_usage",
            "fixtures",
        ):
            self.assertIn(field, summary)
        self.assertEqual(len(summary["fixtures"]), 2)
        for run in real_world_runs:
            for field in (
                "selected_source_token_estimate",
                "suppressed_source_token_estimate",
                "total_composed_context_token_estimate",
                "full_context_baseline_token_estimate",
                "token_reduction_percent",
            ):
                self.assertIn(field, run)
            self.assertEqual(run["output_repair_status"], "not_supported")
            self.assertGreater(run["token_reduction_percent"], 0)
            self.assertLess(
                run["total_composed_context_token_estimate"],
                run["full_context_baseline_token_estimate"],
            )
            self.assertEqual(
                run["selected_source_token_estimate"],
                sum(run["selected_source_token_estimates"].values()),
            )
            self.assertEqual(
                run["suppressed_source_token_estimate"],
                sum(run["suppressed_source_token_estimates"].values()),
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "minimal_real_world_report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Minimal Real-World Inspired Multi-Zone Benchmark", markdown)
        self.assertIn("not broad real-world generalization", markdown)
        self.assertIn("Deterministic validation is the source of truth", markdown)
        self.assertIn("Honest minimal real-world pass rate:", markdown)
        self.assertIn("Required source completeness rate:", markdown)
        self.assertIn("Distractor rejection rate:", markdown)
        self.assertIn("Output repair status: not_supported", markdown)
        self.assertIn("minimal_real_world_licensing_policy_gate", markdown)
        self.assertIn("minimal_real_world_benchmark_roadmap_gate", markdown)
        self.assertIn("Full-context baseline", markdown)
        self.assertIn("Selected sources", markdown)
        self.assertIn("Suppressed sources", markdown)
        self.assertIn("Composed context", markdown)


if __name__ == "__main__":
    unittest.main()
