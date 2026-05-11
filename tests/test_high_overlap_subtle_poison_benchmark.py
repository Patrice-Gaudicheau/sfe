"""Tests for the deterministic high-overlap subtle-poison benchmark."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
from runtime.run_high_overlap_subtle_poison_benchmark import (
    BENCHMARK_NAME,
    BENCHMARK_TYPE,
    get_high_overlap_subtle_poison_tasks,
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


class HighOverlapSubtlePoisonBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_high_overlap_subtle_poison_tasks()
        self.task = self.tasks[0]
        self.fixture_selection = build_selection(
            task=self.task,
            selected_sources=[source_by_id(self.task, self.task.authoritative_source_id)],
            selector_name="test_fixture_selector",
            selector_success=True,
            selector_used_fallback=False,
            confidence=1.0,
            rationale="Selects the source with complete council authority evidence.",
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

    def _selection_with_many(self, source_ids: list[str]) -> dict[str, Any]:
        return build_selection(
            task=self.task,
            selected_sources=[source_by_id(self.task, source_id) for source_id in source_ids],
            selector_name="test_selector",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector chooses multiple sources.",
        )

    def test_fixture_has_one_authoritative_source_and_plausible_invalid_update(self) -> None:
        self.assertEqual(len(self.tasks), 1)
        self.assertEqual(self.task.fixture_id, "high_overlap_helios_governance_amendment_gate")
        self.assertEqual(self.task.authoritative_source_id, "helios-r14")
        self.assertEqual(len(self.task.sources), 4)
        self.assertEqual(self.task.poison_pill_source_ids, ("helios-u22",))
        self.assertEqual(self.task.obsolete_source_ids, ("helios-k03",))
        self.assertEqual(self.task.partial_source_ids, ("helios-m51",))

        subtle_source = source_by_id(self.task, "helios-u22")
        self.assertIn("Helios Guard 2027.04", subtle_source.text)
        self.assertIn("HELIOS_OWNER_FIELD", subtle_source.text)
        self.assertIn("Continuity Council signatures are pending", subtle_source.text)
        self.assertIn("cannot supersede a ratified council decision", subtle_source.text)

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

    def test_authoritative_subtle_poison_scenario_passes_without_openai_provider(self) -> None:
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
        self.assertTrue(benchmark_run["poison_pill_sources_omitted"])
        self.assertTrue(benchmark_run["obsolete_sources_omitted"])
        self.assertTrue(benchmark_run["partial_sources_omitted"])
        self.assertTrue(benchmark_run["output_validation_before_repair"])
        self.assertFalse(benchmark_run["output_repair_attempted"])
        self.assertEqual(benchmark_run["output_repair_status"], "not_supported")
        self.assertTrue(benchmark_run["honest_high_overlap_poison_pill_pass"])

    def test_selecting_subtle_poison_source_fails_strict_selection(self) -> None:
        selection = self._selection_with("helios-u22")
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
        self.assertEqual(validation["selected_poison_pill_source_ids"], ["helios-u22"])
        self.assertFalse(run["honest_high_overlap_poison_pill_pass"])

    def test_selecting_obsolete_or_partial_sources_fails_strict_selection(self) -> None:
        obsolete_run = execute_task(
            task=self.task,
            mode=FAMILY_BENCHMARK_NAME,
            selection=self._selection_with("helios-k03"),
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )
        partial_run = execute_task(
            task=self.task,
            mode=FAMILY_BENCHMARK_NAME,
            selection=self._selection_with("helios-m51"),
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(obsolete_run["obsolete_sources_omitted"])
        self.assertEqual(obsolete_run["selected_obsolete_source_ids"], ["helios-k03"])
        self.assertFalse(obsolete_run["honest_high_overlap_poison_pill_pass"])
        self.assertFalse(partial_run["partial_sources_omitted"])
        self.assertEqual(partial_run["selected_partial_source_ids"], ["helios-m51"])
        self.assertFalse(partial_run["honest_high_overlap_poison_pill_pass"])

    def test_authoritative_plus_subtle_poison_source_fails_strict_selection(self) -> None:
        selection = self._selection_with_many([self.task.authoritative_source_id, "helios-u22"])
        run = execute_task(
            task=self.task,
            mode=FAMILY_BENCHMARK_NAME,
            selection=selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(run["authoritative_source_selected"])
        self.assertFalse(run["poison_pill_sources_omitted"])
        self.assertEqual(run["selected_poison_pill_source_ids"], ["helios-u22"])
        self.assertFalse(run["honest_high_overlap_poison_pill_pass"])

    def test_expected_answer_must_come_from_authoritative_source(self) -> None:
        validation = validate_output(self.task, self.task.expected_answer)

        self.assertTrue(validation["passed"])
        self.assertEqual(
            validation["evidence_reference_validation"]["actual_source_ids"],
            [self.task.authoritative_source_id],
        )
        self.assertEqual(validation["copied_distractor_values"], {})

    def test_output_using_subtle_poison_values_fails(self) -> None:
        poisoned_output = (
            self.task.expected_answer.replace("HELIOS_OWNER_CROWN", "HELIOS_OWNER_FIELD")
            .replace("risk score <= 0.16 over 8h", "risk score <= 0.31 over 12h")
            .replace(
                "enable dual-review quorum before deployment",
                "keep dual-review quorum advisory",
            )
        )
        validation = validate_output(self.task, poisoned_output)

        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["copied_distractor_values"]["subtle_poison"],
            [
                "HELIOS_OWNER_FIELD",
                "risk score <= 0.31 over 12h",
                "keep dual-review quorum advisory",
            ],
        )
        self.assertIn("owner_id", validation["missing_fields"])
        self.assertIn("threshold", validation["missing_fields"])
        self.assertIn("required_action", validation["missing_fields"])

    def test_output_citing_subtle_poison_source_as_authority_fails(self) -> None:
        subtle_citation = self.task.expected_answer.replace(
            self.task.authoritative_source_id,
            "helios-u22",
        )
        validation = validate_output(self.task, subtle_citation)

        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["copied_distractor_values"]["subtle_poison"],
            ["helios-u22"],
        )
        self.assertEqual(
            validation["evidence_reference_validation"]["unexpected_source_ids"],
            ["helios-u22"],
        )

    def test_mixed_authoritative_and_subtle_poison_evidence_fails(self) -> None:
        mixed_citation = self.task.expected_answer.replace(
            f"evidence_source_ids: {self.task.authoritative_source_id}",
            f"evidence_source_ids: {self.task.authoritative_source_id}, helios-u22",
        )
        validation = validate_output(self.task, mixed_citation)

        self.assertFalse(validation["passed"])
        self.assertEqual(
            validation["evidence_reference_validation"]["actual_source_ids"],
            [self.task.authoritative_source_id, "helios-u22"],
        )
        self.assertEqual(
            validation["evidence_reference_validation"]["unexpected_source_ids"],
            ["helios-u22"],
        )

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
            path = Path(temp_dir) / "subtle_poison_report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("High-Overlap Subtle-Poison Benchmark", markdown)
        self.assertIn("deterministic subtle-poison fixture", markdown)
        self.assertIn("plausible invalid amendment", markdown)
        self.assertIn("lacks final authority evidence", markdown)
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
