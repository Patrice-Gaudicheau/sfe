"""Tests for the deterministic multi-zone synthetic benchmark."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_multi_zone_synthetic_benchmark import (
    BENCHMARK_TYPE,
    FixtureMultiZoneSelector,
    build_selection,
    compose_context,
    execute_task,
    get_multi_zone_synthetic_tasks,
    run_benchmark,
    validate_output,
    validate_selection,
    write_markdown,
    zone_by_id,
)


class FailingSelector:
    def select(self, task: Any, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("selector failed")


class MultiZoneSyntheticBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_multi_zone_synthetic_tasks()[0]
        self.fixture_selection = FixtureMultiZoneSelector().select(self.task, {})

    def _selection_without(self, omitted_zone_id: str) -> dict[str, Any]:
        zones = [
            zone_by_id(self.task, zone_id)
            for zone_id in self.task.required_zone_ids
            if zone_id != omitted_zone_id
        ]
        return build_selection(
            task=self.task,
            selected_zones=zones,
            selector_name="test_missing_required_zone",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector omits one required zone.",
        )

    def _selection_with_distractor(self) -> dict[str, Any]:
        zones = [zone_by_id(self.task, zone_id) for zone_id in self.task.required_zone_ids]
        zones.append(zone_by_id(self.task, self.task.distractor_zone_ids[0]))
        return build_selection(
            task=self.task,
            selected_zones=zones,
            selector_name="test_selects_distractor",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector includes an obsolete conflicting zone.",
        )

    def test_fixture_integrity_requires_multiple_explicit_zones(self) -> None:
        self.assertEqual(self.task.task_label, "multi_zone_synthetic_aurora_release_gate")
        self.assertGreaterEqual(len(self.task.required_zone_ids), 3)

        zone_ids = [zone.zone_id for zone in self.task.zones]
        self.assertEqual(len(zone_ids), len(set(zone_ids)))
        self.assertTrue(all(zone.zone_id and zone.role for zone in self.task.zones))
        self.assertEqual(
            {zone.zone_id for zone in self.task.zones if zone.required},
            set(self.task.required_zone_ids),
        )
        self.assertEqual(
            {zone.zone_id for zone in self.task.zones if zone.distractor},
            set(self.task.distractor_zone_ids),
        )

        core_answer_targets = {
            "AUR-2026.09-mz2",
            "27.4",
            "RavenReplay-204",
            "AURORA_OWNER_MZ2",
            "aurora_mz2_epoch_lock",
            "customer-visible writes",
        }
        for zone in self.task.zones:
            zone_text = zone.text.lower()
            present_targets = {
                target for target in core_answer_targets if target.lower() in zone_text
            }
            self.assertNotEqual(
                present_targets,
                core_answer_targets,
                f"{zone.zone_id} unexpectedly contains the full answer",
            )

    def test_validation_contract_accepts_complete_required_selection(self) -> None:
        validation = validate_selection(self.task, self.fixture_selection)

        self.assertTrue(validation["selected_zone_complete"])
        self.assertTrue(validation["distractors_omitted"])
        self.assertEqual(validation["missing_required_zone_ids"], [])
        self.assertEqual(validation["unexpected_distractor_zone_ids"], [])
        self.assertTrue(validation["contains_all_context_targets"])
        self.assertEqual(
            self.fixture_selection["selected_zone_ids"],
            list(self.task.required_zone_ids),
        )
        self.assertEqual(
            set(self.fixture_selection["zone_roles"]),
            set(self.task.required_zone_ids),
        )
        self.assertEqual(self.fixture_selection["confidence"], 1.0)
        self.assertTrue(self.fixture_selection["evidence_rationale"])

    def test_selected_zone_completeness_fails_when_required_zone_missing(self) -> None:
        selection = self._selection_without("evidence-aurora-final")
        validation = validate_selection(self.task, selection)
        run = execute_task(
            task=self.task,
            mode="spatial_multi_zone",
            selection=selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(validation["selected_zone_complete"])
        self.assertIn("evidence-aurora-final", validation["missing_required_zone_ids"])
        self.assertFalse(validation["contains_all_context_targets"])
        self.assertFalse(run["honest_multi_zone_pass"])

    def test_distractor_rejection_fails_when_obsolete_zone_selected(self) -> None:
        selection = self._selection_with_distractor()
        validation = validate_selection(self.task, selection)
        run = execute_task(
            task=self.task,
            mode="spatial_multi_zone",
            selection=selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(validation["distractors_omitted"])
        self.assertEqual(
            validation["unexpected_distractor_zone_ids"],
            ["distractor-aurora-mz1-draft"],
        )
        self.assertFalse(run["honest_multi_zone_pass"])

    def test_honest_pass_fails_when_selector_fallback_is_used(self) -> None:
        report = run_benchmark([self.task], selector=FailingSelector())
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertEqual(spatial_run["selector"], "fixture_fallback_after_selector_error")
        self.assertFalse(spatial_run["selector_success"])
        self.assertTrue(spatial_run["selector_used_fallback"])
        self.assertTrue(spatial_run["output_validation_before_repair"])
        self.assertFalse(spatial_run["honest_multi_zone_pass"])
        self.assertEqual(report["summary"]["fallback_count"], 1)
        self.assertEqual(report["summary"]["honest_multi_zone_pass_count"], 0)

    def test_honest_pass_fails_when_output_validation_fails(self) -> None:
        incomplete_output = self.task.expected_answer.replace("AURORA_OWNER_MZ2", "")
        run = execute_task(
            task=self.task,
            mode="spatial_multi_zone",
            selection=self.fixture_selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
            output_override=incomplete_output,
        )

        self.assertFalse(validate_output(self.task, incomplete_output)["passed"])
        self.assertFalse(run["output_validation_before_repair"])
        self.assertIsNone(run["output_validation_after_repair"])
        self.assertFalse(run["honest_multi_zone_pass"])
        self.assertIsNone(run["honest_multi_zone_pass_after_repair"])

    def test_honest_pass_fails_when_evidence_references_are_wrong(self) -> None:
        wrong_evidence_output = self.task.expected_answer.replace(
            "evidence_zone_ids: intent-aurora-gate, constraints-aurora-active, "
            "domain-aurora-governance, evidence-aurora-final",
            "evidence_zone_ids: intent-aurora-gate, constraints-aurora-active, "
            "evidence-aurora-final, distractor-aurora-mz1-draft",
        )
        output_validation = validate_output(self.task, wrong_evidence_output)
        run = execute_task(
            task=self.task,
            mode="spatial_multi_zone",
            selection=self.fixture_selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
            output_override=wrong_evidence_output,
        )

        self.assertFalse(output_validation["passed"])
        self.assertEqual(
            output_validation["evidence_reference_validation"]["missing_zone_ids"],
            ["domain-aurora-governance"],
        )
        self.assertEqual(
            output_validation["evidence_reference_validation"]["unexpected_zone_ids"],
            ["distractor-aurora-mz1-draft"],
        )
        self.assertFalse(run["output_validation_before_repair"])
        self.assertFalse(run["honest_multi_zone_pass"])

    def test_honest_pass_requires_no_fallback_complete_selection_and_raw_output(self) -> None:
        run = execute_task(
            task=self.task,
            mode="spatial_multi_zone",
            selection=self.fixture_selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertTrue(run["selector_success"])
        self.assertFalse(run["selector_used_fallback"])
        self.assertTrue(run["selected_zone_complete"])
        self.assertTrue(run["distractors_omitted"])
        self.assertTrue(run["output_validation_before_repair"])
        self.assertTrue(run["honest_multi_zone_pass"])
        self.assertIsNone(run["output_validation_after_repair"])

    def test_composed_context_groups_selected_content_by_zone_role(self) -> None:
        context = compose_context(self.task, self.task.required_zone_ids)

        for zone_id in self.task.required_zone_ids:
            zone = zone_by_id(self.task, zone_id)
            self.assertIn(f"ZONE ROLE: {zone.role}", context)
            self.assertIn(f"ZONE ID: {zone.zone_id}", context)
        self.assertNotIn("distractor-aurora-mz1-draft", context)

    def test_report_fields_and_token_accounting_are_present(self) -> None:
        report = run_benchmark([self.task])
        summary = report["summary"]
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["provider"], "deterministic_mock")
        for field in (
            "zone_selection_success_rate",
            "selected_zone_completeness_rate",
            "distractor_rejection_rate",
            "fallback_count",
            "output_validation_complete_rate",
            "output_validation_after_repair_rate",
            "honest_multi_zone_pass_count",
            "honest_multi_zone_pass_rate",
            "average_token_reduction_percent",
        ):
            self.assertIn(field, summary)

        self.assertIn("selected_zone_token_estimate", spatial_run)
        self.assertIn("suppressed_zone_token_estimate", spatial_run)
        self.assertIn("total_composed_context_token_estimate", spatial_run)
        self.assertIn("full_context_baseline_token_estimate", spatial_run)
        self.assertLess(
            spatial_run["total_composed_context_token_estimate"],
            spatial_run["full_context_baseline_token_estimate"],
        )
        self.assertGreater(spatial_run["token_reduction_percent"], 0)
        self.assertIsNone(summary["output_validation_after_repair_rate"])

    def test_markdown_report_includes_honest_pass_line(self) -> None:
        report = run_benchmark([self.task])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "multi_zone_report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Honest multi-zone pass rate:", markdown)
        self.assertIn("Zone selection success rate:", markdown)
        self.assertIn("Selected-zone completeness rate:", markdown)
        self.assertIn("Average token reduction:", markdown)


if __name__ == "__main__":
    unittest.main()
