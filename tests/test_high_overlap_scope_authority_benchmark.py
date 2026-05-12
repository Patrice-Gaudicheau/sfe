"""Tests for the deterministic high-overlap scope-authority benchmark."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.high_overlap_benchmark_helpers import build_failure_diagnostics
from runtime.run_high_overlap_poison_pill_benchmark import (
    BENCHMARK_NAME as FAMILY_BENCHMARK_NAME,
    build_selection,
    execute_task,
    format_source,
    run_benchmark as run_family_benchmark,
    source_by_id,
    validate_output,
    validate_selection,
)
from runtime.run_high_overlap_scope_authority_benchmark import (
    BENCHMARK_NAME,
    BENCHMARK_TYPE,
    get_high_overlap_scope_authority_tasks,
    run_benchmark,
    write_markdown,
)


class FailingSelector:
    provider = "deterministic_test"
    selector_mode = "failing_selector"
    model: str | None = None
    api_path: str | None = None

    def select(self, task: Any, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("selector failed")


class HighOverlapScopeAuthorityBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_high_overlap_scope_authority_tasks()
        self.task = self.tasks[0]
        self.fixture_selection = build_selection(
            task=self.task,
            selected_sources=[source_by_id(self.task, self.task.authoritative_source_id)],
            selector_name="test_fixture_selector",
            selector_success=True,
            selector_used_fallback=False,
            confidence=1.0,
            rationale="Selects the source whose scope matches the requested deployment lane.",
        )

    def _selection_with(self, source_id: str) -> dict[str, Any]:
        return build_selection(
            task=self.task,
            selected_sources=[source_by_id(self.task, source_id)],
            selector_name="test_selector",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector chooses a single source.",
        )

    def _diagnostics_for(self, output: str) -> dict[str, Any]:
        return build_failure_diagnostics(
            output_validation=validate_output(self.task, output),
            provider_error_occurred=False,
            parse_success=True,
            fallback_used=False,
            repair_used=False,
            context_valid=True,
        )

    def test_fixture_has_one_authoritative_source_and_scope_mismatch_sources(self) -> None:
        self.assertEqual(len(self.tasks), 1)
        self.assertEqual(self.task.fixture_id, "high_overlap_aurelia_scope_authority_gate")
        self.assertEqual(self.task.authoritative_source_id, "aurelia-r19")
        self.assertEqual(len(self.task.sources), 4)
        self.assertEqual(self.task.poison_pill_source_ids, ("aurelia-q44", "aurelia-s08"))
        self.assertEqual(self.task.partial_source_ids, ("aurelia-n27",))
        self.assertEqual(self.task.obsolete_source_ids, ())

        authoritative = source_by_id(self.task, self.task.authoritative_source_id)
        self.assertIn("North Ridge payment-risk deployment lane", authoritative.text)
        self.assertIn("AURELIA_OWNER_NORTH", authoritative.text)
        self.assertIn("Aurelia Guard 2028.02-NR", authoritative.text)
        self.assertIn("separate decision records", authoritative.text)

    def test_ids_titles_roles_and_source_text_do_not_leak_obvious_labels(self) -> None:
        forbidden_terms = (
            "fake",
            "poison",
            "invalid",
            "malicious",
            "trap",
            "adversarial",
            "distractor",
        )

        for source in self.task.sources:
            rendered = format_source(source).lower()
            for term in forbidden_terms:
                self.assertNotIn(term, rendered)

    def test_authoritative_scope_authority_scenario_passes_without_openai_provider(self) -> None:
        report = run_benchmark()
        benchmark_run = [run for run in report["runs"] if run["mode"] == FAMILY_BENCHMARK_NAME][0]

        self.assertEqual(report["metadata"]["benchmark_name"], BENCHMARK_NAME)
        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["selector_provider"], "deterministic_mock")
        self.assertEqual(report["metadata"]["executor_provider"], "deterministic_mock")
        self.assertIsNone(report["metadata"]["selector_model"])
        self.assertIsNone(report["metadata"]["executor_model"])
        self.assertFalse(report["metadata"]["openai_validation"])
        self.assertEqual(benchmark_run["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(benchmark_run["selected_source_ids"], [self.task.authoritative_source_id])
        self.assertTrue(benchmark_run["authoritative_source_selected"])
        self.assertTrue(benchmark_run["scope_mismatch_sources_omitted"])
        self.assertTrue(benchmark_run["partial_sources_omitted"])
        self.assertTrue(benchmark_run["output_validation_before_repair"])
        self.assertFalse(benchmark_run["output_repair_attempted"])
        self.assertEqual(benchmark_run["output_repair_status"], "not_supported")
        self.assertTrue(benchmark_run["honest_high_overlap_poison_pill_pass"])

    def test_selecting_scope_mismatch_source_fails_strict_selection(self) -> None:
        selection = self._selection_with("aurelia-q44")
        validation = validate_selection(self.task, selection)
        run = execute_task(
            task=self.task,
            mode=FAMILY_BENCHMARK_NAME,
            selection=selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(validation["passed"])
        self.assertFalse(validation["authoritative_source_selected"])
        self.assertFalse(validation["poison_pill_sources_omitted"])
        self.assertEqual(validation["selected_poison_pill_source_ids"], ["aurelia-q44"])
        self.assertFalse(run["honest_high_overlap_poison_pill_pass"])

    def test_expected_answer_must_come_from_authoritative_source(self) -> None:
        validation = validate_output(self.task, self.task.expected_answer)
        diagnostics = self._diagnostics_for(self.task.expected_answer)

        self.assertTrue(validation["passed"])
        self.assertEqual(
            validation["evidence_reference_validation"]["actual_source_ids"],
            [self.task.authoritative_source_id],
        )
        self.assertEqual(validation["copied_distractor_values"], {})
        self.assertTrue(diagnostics["field_extraction_passed"])
        self.assertTrue(diagnostics["evidence_reference_passed"])
        self.assertTrue(diagnostics["contamination_free"])
        self.assertEqual(diagnostics["failure_flags"], [])

    def test_output_using_scope_mismatch_values_fails_as_contamination_indicator(self) -> None:
        output = (
            self.task.expected_answer.replace("AURELIA_OWNER_NORTH", "AURELIA_OWNER_SOUTH")
            .replace("risk score <= 0.21 over 4h", "risk score <= 0.29 over 10h")
            .replace(
                "enable north-lane dual approval before rollout",
                "keep north-lane dual approval advisory",
            )
        )
        validation = validate_output(self.task, output)
        diagnostics = self._diagnostics_for(output)

        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["copied_distractor_values"]["scope_mismatch"],
            [
                "AURELIA_OWNER_SOUTH",
                "risk score <= 0.29 over 10h",
                "keep north-lane dual approval advisory",
            ],
        )
        self.assertIn("owner_id", validation["missing_fields"])
        self.assertIn("threshold", validation["missing_fields"])
        self.assertIn("required_action", validation["missing_fields"])
        self.assertFalse(diagnostics["field_extraction_passed"])
        self.assertFalse(diagnostics["contamination_free"])
        self.assertEqual(diagnostics["copied_excluded_value_count"], 3)
        self.assertIn("field_extraction_failure", diagnostics["failure_flags"])
        self.assertIn("contamination_indicator", diagnostics["failure_flags"])

    def test_output_citing_scope_mismatch_source_fails(self) -> None:
        output = self.task.expected_answer.replace(
            self.task.authoritative_source_id,
            "aurelia-q44",
        )
        validation = validate_output(self.task, output)
        diagnostics = self._diagnostics_for(output)

        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["evidence_reference_validation"]["unexpected_source_ids"],
            ["aurelia-q44"],
        )
        self.assertEqual(
            validation["copied_distractor_values"]["scope_mismatch"],
            ["aurelia-q44"],
        )
        self.assertFalse(diagnostics["evidence_reference_passed"])
        self.assertFalse(diagnostics["contamination_free"])
        self.assertEqual(diagnostics["excluded_source_citation_count"], 1)
        self.assertIn("evidence_reference_failure", diagnostics["failure_flags"])
        self.assertIn("contamination_indicator", diagnostics["failure_flags"])

    def test_clean_field_extraction_failure_is_not_contamination(self) -> None:
        output = self.task.expected_answer.replace(
            "Aurelia Guard 2028.02-NR",
            "Aurelia Guard 2028.02",
        )
        validation = validate_output(self.task, output)
        diagnostics = self._diagnostics_for(output)

        self.assertFalse(validation["passed"])
        self.assertEqual(validation["missing_fields"], ["active_protocol"])
        self.assertEqual(validation["copied_distractor_values"], {})
        self.assertTrue(diagnostics["evidence_reference_passed"])
        self.assertFalse(diagnostics["field_extraction_passed"])
        self.assertEqual(diagnostics["failed_field_names"], ["active_protocol"])
        self.assertEqual(diagnostics["failed_field_count"], 1)
        self.assertTrue(diagnostics["contamination_free"])
        self.assertEqual(diagnostics["copied_excluded_value_count"], 0)
        self.assertEqual(diagnostics["excluded_source_citation_count"], 0)
        self.assertFalse(diagnostics["poison_instruction_followed"])
        self.assertEqual(diagnostics["failure_flags"], ["field_extraction_failure"])

    def test_no_fallback_or_repair_counts_as_success(self) -> None:
        report = run_family_benchmark(tasks=self.tasks, selector=FailingSelector())  # type: ignore[arg-type]
        benchmark_run = [run for run in report["runs"] if run["mode"] == FAMILY_BENCHMARK_NAME][0]

        self.assertTrue(benchmark_run["selector_used_fallback"])
        self.assertFalse(benchmark_run["selector_success"])
        self.assertTrue(benchmark_run["output_validation_before_repair"])
        self.assertFalse(benchmark_run["output_repair_attempted"])
        self.assertEqual(benchmark_run["output_repair_status"], "not_supported")
        self.assertFalse(benchmark_run["honest_high_overlap_poison_pill_pass"])
        self.assertEqual(report["summary"]["fallback_count"], 1)

    def test_markdown_report_labels_deterministic_scope_without_overclaiming(self) -> None:
        report = run_benchmark()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "scope_authority_report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("High-Overlap Scope-Authority Benchmark", markdown)
        self.assertIn("deterministic fixture", markdown)
        self.assertIn("different deployment scopes", markdown)
        self.assertIn("one complete authoritative source", markdown)
        self.assertIn("controlled fixture", markdown)
        self.assertIn("not statistical proof", markdown)
        self.assertIn("not OpenAI validation", markdown)
        self.assertIn("not general robustness proof", markdown)
        self.assertNotIn("proven robust", markdown)
        self.assertNotIn("safe in general", markdown)
        self.assertNotIn("reliable in general", markdown)
        self.assertNotIn("solved", markdown)
        self.assertNotIn("statistically validated", markdown)
        self.assertNotIn("production-ready", markdown)


if __name__ == "__main__":
    unittest.main()
