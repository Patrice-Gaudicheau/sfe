"""Tests for the deterministic multi-zone synthetic benchmark."""

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

from runtime.run_multi_zone_synthetic_benchmark import (
    BENCHMARK_TYPE,
    FixtureMultiZoneSelector,
    OPENAI_SELECTOR_API_PATH,
    OpenAISelectorSmoke,
    _build_selector_from_args,
    _parse_args,
    build_selection,
    build_openai_selector_prompt,
    compose_context,
    execute_task,
    get_multi_zone_synthetic_tasks,
    parse_openai_selector_output,
    run_benchmark,
    validate_output,
    validate_selection,
    write_markdown,
    zone_by_id,
)


class FailingSelector:
    def select(self, task: Any, fixture_selection: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("selector failed")


class FakeOpenAIProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_instruction": system_instruction,
            }
        )
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            "{"
                            '"selected_zone_ids": ['
                            '"intent-aurora-gate", '
                            '"constraints-aurora-active", '
                            '"domain-aurora-governance", '
                            '"evidence-aurora-final"'
                            "], "
                            '"zone_roles": {'
                            '"intent-aurora-gate": "task_intent", '
                            '"constraints-aurora-active": "hard_constraints", '
                            '"domain-aurora-governance": "domain_context", '
                            '"evidence-aurora-final": "evidence_records"'
                            "}, "
                            '"confidence": 0.93, '
                            '"evidence_rationale": "Intent, constraints, domain, and final evidence are all needed.", '
                            '"fallback_used": false'
                            "}"
                        )
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 321,
                "completion_tokens": 89,
                "total_tokens": 410,
            },
        }


class DecoratedIDOpenAIProvider:
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            "{"
                            '"selected_zone_ids": ['
                            '"ZONE intent-aurora-gate (task_intent)", '
                            '"ZONE constraints-aurora-active (hard_constraints)", '
                            '"ZONE domain-aurora-governance (domain_context)", '
                            '"ZONE evidence-aurora-final (evidence_records)"'
                            "], "
                            '"zone_roles": {'
                            '"ZONE intent-aurora-gate (task_intent)": "task_intent", '
                            '"ZONE constraints-aurora-active (hard_constraints)": "hard_constraints", '
                            '"ZONE domain-aurora-governance (domain_context)": "domain_context", '
                            '"ZONE evidence-aurora-final (evidence_records)": "evidence_records"'
                            "}, "
                            '"confidence": 0.91, '
                            '"evidence_rationale": "Selected the logical zones but used decorated IDs.", '
                            '"fallback_used": false'
                            "}"
                        )
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 222,
                "completion_tokens": 77,
                "total_tokens": 299,
            },
        }


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
            "openai_selector_actual_usage",
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
        self.assertIsNone(summary["openai_selector_actual_usage"]["total_tokens"])

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

    def test_default_cli_selector_remains_fixture_without_provider(self) -> None:
        with patch.object(sys, "argv", ["run_multi_zone_synthetic_benchmark.py"]):
            args = _parse_args()

        selector = _build_selector_from_args(args)

        self.assertIsInstance(selector, FixtureMultiZoneSelector)
        self.assertEqual(args.selector, "fixture")

    def test_openai_selector_prompt_requests_schema_only(self) -> None:
        prompt = build_openai_selector_prompt(self.task)

        self.assertIn('"selected_zone_ids"', prompt)
        self.assertIn('"zone_roles"', prompt)
        self.assertIn('"confidence"', prompt)
        self.assertIn('"evidence_rationale"', prompt)
        self.assertIn('"fallback_used"', prompt)
        self.assertIn("selected_zone_ids must contain exact canonical zone IDs only", prompt)
        self.assertIn('Do not prefix IDs with "ZONE"', prompt)
        self.assertIn("Do not append roles in parentheses", prompt)
        self.assertIn("Valid canonical zone IDs:", prompt)
        self.assertIn('"intent-aurora-gate"', prompt)
        self.assertIn("Do not generate the final answer", prompt)
        self.assertIn("distractor-aurora-mz1-draft", prompt)

    def test_parse_openai_selector_output_accepts_json_fence(self) -> None:
        parsed = parse_openai_selector_output(
            "```json\n"
            "{"
            '"selected_zone_ids": ["intent-aurora-gate"], '
            '"zone_roles": {"intent-aurora-gate": "task_intent"}, '
            '"confidence": 0.5, '
            '"evidence_rationale": "intent", '
            '"fallback_used": false'
            "}\n```"
        )

        self.assertEqual(parsed["selected_zone_ids"], ["intent-aurora-gate"])
        self.assertEqual(parsed["zone_roles"], {"intent-aurora-gate": "task_intent"})
        self.assertEqual(parsed["confidence"], 0.5)
        self.assertFalse(parsed["fallback_used"])

    def test_openai_selector_smoke_uses_real_selector_with_deterministic_executor(self) -> None:
        fake_provider = FakeOpenAIProvider()
        selector = OpenAISelectorSmoke(
            model="example-openai-router",
            max_output_tokens=500,
            provider=fake_provider,  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], selector=selector)
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertEqual(report["metadata"]["selector_mode"], "openai_selector_smoke")
        self.assertEqual(report["metadata"]["provider"], "openai-api")
        self.assertEqual(report["metadata"]["model"], "example-openai-router")
        self.assertEqual(report["metadata"]["api_path"], OPENAI_SELECTOR_API_PATH)
        self.assertEqual(report["metadata"]["executor"], "deterministic_fixture")
        self.assertEqual(spatial_run["selector"], "openai_selector_smoke")
        self.assertEqual(spatial_run["selector_validation_result"], "complete")
        self.assertTrue(spatial_run["honest_multi_zone_pass"])
        self.assertEqual(spatial_run["openai_selector"]["usage"]["total_tokens"], 410)
        self.assertEqual(report["summary"]["openai_selector_actual_usage"]["total_tokens"], 410)
        self.assertEqual(len(fake_provider.calls), 1)
        self.assertEqual(fake_provider.calls[0]["model"], "example-openai-router")
        self.assertEqual(fake_provider.calls[0]["max_tokens"], 500)
        self.assertIsNone(fake_provider.calls[0]["temperature"])

    def test_openai_selector_decorated_ids_are_rejected_and_metadata_preserved(self) -> None:
        selector = OpenAISelectorSmoke(
            model="example-openai-router",
            provider=DecoratedIDOpenAIProvider(),  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], selector=selector)
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]
        openai_metadata = spatial_run["openai_selector"]

        self.assertEqual(spatial_run["selector"], "fixture_fallback_after_selector_error")
        self.assertFalse(spatial_run["selector_success"])
        self.assertTrue(spatial_run["selector_used_fallback"])
        self.assertFalse(spatial_run["honest_multi_zone_pass"])
        self.assertEqual(spatial_run["selector_validation_result"], "complete")
        self.assertIn("non-canonical zone IDs", spatial_run["selector_error"])
        self.assertEqual(openai_metadata["provider"], "openai-api")
        self.assertEqual(openai_metadata["model"], "example-openai-router")
        self.assertEqual(openai_metadata["api_path"], OPENAI_SELECTOR_API_PATH)
        self.assertEqual(openai_metadata["usage"]["total_tokens"], 299)
        self.assertEqual(
            openai_metadata["raw_selected_zone_ids"],
            [
                "ZONE intent-aurora-gate (task_intent)",
                "ZONE constraints-aurora-active (hard_constraints)",
                "ZONE domain-aurora-governance (domain_context)",
                "ZONE evidence-aurora-final (evidence_records)",
            ],
        )
        self.assertEqual(report["summary"]["fallback_count"], 1)
        self.assertEqual(report["summary"]["honest_multi_zone_pass_count"], 0)
        self.assertEqual(report["summary"]["openai_selector_actual_usage"]["total_tokens"], 299)

    def test_openai_selector_wrong_role_fails_selector_validation(self) -> None:
        selection = dict(self.fixture_selection)
        selection["selector"] = "openai_selector_smoke"
        selection["zone_roles"] = dict(selection["zone_roles"])
        selection["zone_roles"]["domain-aurora-governance"] = "evidence_records"
        run = execute_task(
            task=self.task,
            mode="spatial_multi_zone",
            selection=selection,
            fixture_selection=self.fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(run["selected_zone_complete"])
        self.assertFalse(run["selection_validation"]["zone_roles_valid"])
        self.assertEqual(run["selector_validation_result"], "incomplete")
        self.assertFalse(run["honest_multi_zone_pass"])


if __name__ == "__main__":
    unittest.main()
