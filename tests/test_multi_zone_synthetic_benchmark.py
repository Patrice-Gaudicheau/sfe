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
    OpenAIExecutorSmoke,
    OpenAISelectorSmoke,
    _build_selector_from_args,
    _build_executor_from_args,
    _parse_args,
    build_selection,
    build_openai_executor_prompt,
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


class FakeOpenAIExecutorProvider:
    def __init__(self, content: str) -> None:
        self.content = content
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
            "choices": [{"message": {"content": self.content}}],
            "usage": {
                "prompt_tokens": 444,
                "completion_tokens": 111,
                "total_tokens": 555,
            },
        }


class SequencedExecutor:
    executor_mode = "sequenced_executor"
    provider = "deterministic_test"
    model: str | None = None
    api_path: str | None = None

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def execute(
        self,
        task: Any,
        selected_zone_ids: tuple[str, ...],
        composed_context: str,
    ) -> dict[str, Any]:
        output = self.outputs[self.calls]
        self.calls += 1
        return {
            "executor": "sequenced_executor",
            "executor_mode": self.executor_mode,
            "provider": self.provider,
            "model": self.model,
            "api_path": self.api_path,
            "output": output,
            "output_parse_success": True,
            "output_parse_error": "",
        }


class MultiZoneSyntheticBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_multi_zone_synthetic_tasks()
        self.task = self.tasks[0]
        self.quartz_task = self.tasks[1]
        self.fixture_selection = FixtureMultiZoneSelector().select(self.task, {})
        self.quartz_fixture_selection = FixtureMultiZoneSelector().select(self.quartz_task, {})

    def _selection_without(self, omitted_zone_id: str) -> dict[str, Any]:
        return self._selection_without_for_task(self.task, omitted_zone_id)

    def _selection_without_for_task(self, task: Any, omitted_zone_id: str) -> dict[str, Any]:
        zones = [
            zone_by_id(task, zone_id)
            for zone_id in task.required_zone_ids
            if zone_id != omitted_zone_id
        ]
        return build_selection(
            task=task,
            selected_zones=zones,
            selector_name="test_missing_required_zone",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector omits one required zone.",
        )

    def _selection_with_distractor(self) -> dict[str, Any]:
        return self._selection_with_distractor_for_task(self.task, self.task.distractor_zone_ids[0])

    def _selection_with_distractor_for_task(self, task: Any, distractor_zone_id: str) -> dict[str, Any]:
        zones = [zone_by_id(task, zone_id) for zone_id in task.required_zone_ids]
        zones.append(zone_by_id(task, distractor_zone_id))
        return build_selection(
            task=task,
            selected_zones=zones,
            selector_name="test_selects_distractor",
            selector_success=True,
            selector_used_fallback=False,
            confidence=0.7,
            rationale="Test selector includes an obsolete conflicting zone.",
        )

    def test_fixture_integrity_requires_multiple_explicit_zones(self) -> None:
        self.assertEqual(self.task.task_label, "multi_zone_synthetic_aurora_release_gate")
        self.assertEqual(len(self.tasks), 2)
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
        self.assertEqual(run["executor_mode"], "deterministic_fixture")
        self.assertTrue(run["executor_output_parse_success"])

    def test_composed_context_groups_selected_content_by_zone_role(self) -> None:
        context = compose_context(self.task, self.task.required_zone_ids)

        for zone_id in self.task.required_zone_ids:
            zone = zone_by_id(self.task, zone_id)
            self.assertIn(f"ZONE ROLE: {zone.role}", context)
            self.assertIn(f"ZONE ID: {zone.zone_id}", context)
        self.assertNotIn("distractor-aurora-mz1-draft", context)

    def test_second_fixture_happy_path_passes(self) -> None:
        run = execute_task(
            task=self.quartz_task,
            mode="spatial_multi_zone",
            selection=self.quartz_fixture_selection,
            fixture_selection=self.quartz_fixture_selection,
            repeat_index=1,
        )

        self.assertEqual(self.quartz_task.task_label, "multi_zone_synthetic_quartz_relay_gate")
        self.assertEqual(len(self.quartz_task.required_zone_ids), 4)
        self.assertTrue(run["selected_zone_complete"])
        self.assertTrue(run["distractors_omitted"])
        self.assertTrue(run["output_validation_before_repair"])
        self.assertTrue(run["honest_multi_zone_pass"])
        self.assertEqual(
            run["selected_zone_ids"],
            [
                "intent-quartz-relay",
                "constraints-quartz-global",
                "domain-quartz-threshold",
                "evidence-quartz-final",
            ],
        )

    def test_second_fixture_no_single_zone_contains_full_answer(self) -> None:
        core_answer_targets = {
            "QR-2026.10-hx4",
            "18.6 phase units",
            "engage_relay_dampening_mode",
            "Beacon Matrix drift vector exceeds 0.42",
            "QR-EVID-774",
            "quartz-cycle-2026-10-18",
        }

        for zone in self.quartz_task.zones:
            zone_text = zone.text.lower()
            present_targets = {
                target for target in core_answer_targets if target.lower() in zone_text
            }
            self.assertNotEqual(
                present_targets,
                core_answer_targets,
                f"{zone.zone_id} unexpectedly contains the full answer",
            )

    def test_second_fixture_missing_required_zone_fails(self) -> None:
        selection = self._selection_without_for_task(
            self.quartz_task,
            "domain-quartz-threshold",
        )
        run = execute_task(
            task=self.quartz_task,
            mode="spatial_multi_zone",
            selection=selection,
            fixture_selection=self.quartz_fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(run["selected_zone_complete"])
        self.assertIn("domain-quartz-threshold", run["missing_required_zone_ids"])
        self.assertFalse(run["honest_multi_zone_pass"])

    def test_second_fixture_partial_true_distractor_fails(self) -> None:
        selection = self._selection_with_distractor_for_task(
            self.quartz_task,
            "distractor-quartz-partial-threshold",
        )
        run = execute_task(
            task=self.quartz_task,
            mode="spatial_multi_zone",
            selection=selection,
            fixture_selection=self.quartz_fixture_selection,
            repeat_index=1,
        )

        self.assertTrue(run["selected_zone_complete"])
        self.assertFalse(run["distractors_omitted"])
        self.assertEqual(
            run["unexpected_distractor_zone_ids"],
            ["distractor-quartz-partial-threshold"],
        )
        self.assertFalse(run["honest_multi_zone_pass"])

    def test_second_fixture_previous_version_distractor_fails(self) -> None:
        selection = self._selection_with_distractor_for_task(
            self.quartz_task,
            "distractor-quartz-previous-protocol",
        )
        run = execute_task(
            task=self.quartz_task,
            mode="spatial_multi_zone",
            selection=selection,
            fixture_selection=self.quartz_fixture_selection,
            repeat_index=1,
        )

        self.assertFalse(run["distractors_omitted"])
        self.assertEqual(
            run["unexpected_distractor_zone_ids"],
            ["distractor-quartz-previous-protocol"],
        )
        self.assertFalse(run["honest_multi_zone_pass"])

    def test_second_fixture_evidence_mismatch_fails(self) -> None:
        wrong_evidence_output = self.quartz_task.expected_answer.replace(
            "evidence_zone_ids: intent-quartz-relay, constraints-quartz-global, "
            "domain-quartz-threshold, evidence-quartz-final",
            "evidence_zone_ids: intent-quartz-relay, constraints-quartz-global, "
            "evidence-quartz-final, distractor-quartz-partial-threshold",
        )
        output_validation = validate_output(self.quartz_task, wrong_evidence_output)
        run = execute_task(
            task=self.quartz_task,
            mode="spatial_multi_zone",
            selection=self.quartz_fixture_selection,
            fixture_selection=self.quartz_fixture_selection,
            repeat_index=1,
            output_override=wrong_evidence_output,
        )

        self.assertFalse(output_validation["passed"])
        self.assertEqual(
            output_validation["evidence_reference_validation"]["missing_zone_ids"],
            ["domain-quartz-threshold"],
        )
        self.assertEqual(
            output_validation["evidence_reference_validation"]["unexpected_zone_ids"],
            ["distractor-quartz-partial-threshold"],
        )
        self.assertFalse(run["honest_multi_zone_pass"])

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
            "openai_executor_actual_usage",
            "executor_output_parse_success_rate",
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
        self.assertIsNone(summary["openai_executor_actual_usage"]["total_tokens"])

    def test_multi_fixture_aggregate_report_is_correct(self) -> None:
        report = run_benchmark(self.tasks)
        summary = report["summary"]
        fixtures = {fixture["fixture_id"]: fixture for fixture in summary["fixtures"]}

        self.assertEqual(report["metadata"]["task_count"], 2)
        self.assertEqual(summary["run_count"], 4)
        self.assertEqual(summary["baseline_run_count"], 2)
        self.assertEqual(summary["spatial_multi_zone_run_count"], 2)
        self.assertEqual(summary["honest_multi_zone_pass_count"], 2)
        self.assertEqual(summary["honest_multi_zone_pass_rate"], 1.0)
        self.assertEqual(set(fixtures), {task.task_label for task in self.tasks})
        for fixture in fixtures.values():
            self.assertEqual(fixture["run_count"], 1)
            self.assertTrue(fixture["selected_zone_complete"])
            self.assertTrue(fixture["distractors_omitted"])
            self.assertFalse(fixture["fallback_used"])
            self.assertEqual(fixture["honest_multi_zone_pass_rate"], 1.0)
            self.assertGreater(fixture["average_token_reduction_percent"], 0)

    def test_markdown_report_includes_honest_pass_line(self) -> None:
        report = run_benchmark(self.tasks)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "multi_zone_report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Honest multi-zone pass rate:", markdown)
        self.assertIn("Zone selection success rate:", markdown)
        self.assertIn("Selected-zone completeness rate:", markdown)
        self.assertIn("Average token reduction:", markdown)
        self.assertIn("## Fixtures", markdown)
        self.assertIn("multi_zone_synthetic_aurora_release_gate", markdown)
        self.assertIn("multi_zone_synthetic_quartz_relay_gate", markdown)

    def test_default_cli_selector_remains_fixture_without_provider(self) -> None:
        with patch.object(sys, "argv", ["run_multi_zone_synthetic_benchmark.py"]):
            args = _parse_args()

        selector = _build_selector_from_args(args)
        executor = _build_executor_from_args(args)

        self.assertIsInstance(selector, FixtureMultiZoneSelector)
        self.assertEqual(args.selector, "fixture")
        self.assertEqual(args.executor, "fixture")
        self.assertEqual(executor.executor_mode, "deterministic_fixture")

    def test_repeat_openai_smoke_cli_sets_openai_selector_executor_and_repeat(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_multi_zone_synthetic_benchmark.py", "--repeat-openai-smoke", "3"],
        ):
            args = _parse_args()

        with patch("runtime.run_multi_zone_synthetic_benchmark.load_repo_env"):
            from runtime import run_multi_zone_synthetic_benchmark as runner

            runner._apply_openai_smoke_repeat_args(args)

        self.assertEqual(args.repeat, 3)
        self.assertEqual(args.selector, "openai")
        self.assertEqual(args.executor, "openai")

    def test_repeated_deterministic_fixture_runs_aggregate_correctly(self) -> None:
        report = run_benchmark(self.tasks, repeat=3)
        summary = report["summary"]
        stability = summary["stability"]

        self.assertEqual(stability["repeat_count"], 3)
        self.assertEqual(stability["total_fixture_executions"], 6)
        self.assertTrue(stability["all_repeats_passed"])
        self.assertTrue(stability["all_fixtures_passed"])
        self.assertEqual(summary["honest_multi_zone_pass_count"], 6)
        self.assertEqual(summary["honest_multi_zone_pass_rate"], 1.0)
        self.assertEqual(len(stability["per_run"]), 3)
        for result in stability["per_run"]:
            self.assertTrue(result["honest_multi_zone_pass"])
            self.assertEqual(result["fixture_execution_count"], 2)
            self.assertEqual(result["honest_multi_zone_pass_count"], 2)
            self.assertEqual(result["selector_fallback_count"], 0)
        for result in stability["per_fixture"]:
            self.assertTrue(result["honest_multi_zone_pass"])
            self.assertEqual(result["repeat_count"], 3)
            self.assertEqual(result["honest_multi_zone_pass_count"], 3)

    def test_one_failed_repeated_run_lowers_aggregate_pass_rate(self) -> None:
        bad_output = self.task.expected_answer.replace("AURORA_OWNER_MZ2", "")
        executor = SequencedExecutor([self.task.expected_answer, bad_output])

        report = run_benchmark([self.task], repeat=2, executor=executor)  # type: ignore[arg-type]
        summary = report["summary"]

        self.assertEqual(summary["honest_multi_zone_pass_count"], 1)
        self.assertEqual(summary["honest_multi_zone_pass_rate"], 0.5)
        self.assertFalse(summary["stability"]["all_repeats_passed"])
        self.assertFalse(summary["stability"]["all_fixtures_passed"])
        self.assertTrue(summary["stability"]["per_run"][0]["honest_multi_zone_pass"])
        self.assertFalse(summary["stability"]["per_run"][1]["honest_multi_zone_pass"])
        self.assertEqual(
            summary["stability"]["per_fixture"][0]["output_validation_complete_rate"],
            0.5,
        )

    def test_fallback_in_any_repeat_is_visible(self) -> None:
        report = run_benchmark([self.task], repeat=2, selector=FailingSelector())
        summary = report["summary"]

        self.assertEqual(summary["fallback_count"], 2)
        self.assertEqual(summary["fallback_rate"], 1.0)
        self.assertEqual(summary["honest_multi_zone_pass_count"], 0)
        self.assertFalse(summary["stability"]["all_repeats_passed"])
        for result in summary["stability"]["per_run"]:
            self.assertEqual(result["selector_fallback_count"], 1)
            self.assertFalse(result["honest_multi_zone_pass"])

    def test_mocked_token_usage_aggregates_across_repeats(self) -> None:
        selector = OpenAISelectorSmoke(
            model="example-openai-router",
            provider=FakeOpenAIProvider(),  # type: ignore[arg-type]
        )
        executor = OpenAIExecutorSmoke(
            model="example-openai-executor",
            provider=FakeOpenAIExecutorProvider(
                "{"
                '"active_version": "AUR-2026.09-mz2", '
                '"rollback_threshold": "27.4 credits per thousand governed requests for three consecutive ten-minute windows", '
                '"excluded_dataset": "RavenReplay-204", '
                '"launch_approval_owner": "AURORA_OWNER_MZ2", '
                '"mitigation_label": "aurora_mz2_epoch_lock", '
                '"governed_request_class": "customer-visible writes", '
                '"evidence_zone_ids": ["intent-aurora-gate", "constraints-aurora-active", '
                '"domain-aurora-governance", "evidence-aurora-final"]'
                "}"
            ),  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], repeat=2, selector=selector, executor=executor)

        self.assertEqual(report["summary"]["openai_selector_actual_usage"]["total_tokens"], 820)
        self.assertEqual(report["summary"]["openai_executor_actual_usage"]["total_tokens"], 1110)
        self.assertEqual(report["summary"]["stability"]["repeat_count"], 2)
        self.assertEqual(report["summary"]["stability"]["selector_total_tokens"], 820)
        self.assertEqual(report["summary"]["stability"]["executor_total_tokens"], 1110)
        for result in report["summary"]["stability"]["per_run"]:
            self.assertEqual(result["selector_total_tokens"], 410)
            self.assertEqual(result["executor_total_tokens"], 555)

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

    def test_openai_executor_prompt_uses_selected_context_and_schema(self) -> None:
        context = compose_context(self.task, self.task.required_zone_ids)
        prompt = build_openai_executor_prompt(self.task, self.task.required_zone_ids, context)

        self.assertIn("Return only one strict JSON object", prompt)
        self.assertIn('"active_version"', prompt)
        self.assertIn('"evidence_zone_ids"', prompt)
        self.assertIn("Valid evidence zone IDs", prompt)
        self.assertIn("intent-aurora-gate", prompt)
        self.assertNotIn("distractor-aurora-mz1-draft", prompt)

    def test_fixture_selector_and_mocked_openai_executor_valid_json_passes(self) -> None:
        provider = FakeOpenAIExecutorProvider(
            "{"
            '"active_version": "AUR-2026.09-mz2", '
            '"rollback_threshold": "27.4 credits per thousand governed requests for three consecutive ten-minute windows", '
            '"excluded_dataset": "RavenReplay-204", '
            '"launch_approval_owner": "AURORA_OWNER_MZ2", '
            '"mitigation_label": "aurora_mz2_epoch_lock", '
            '"governed_request_class": "customer-visible writes", '
            '"evidence_zone_ids": ["intent-aurora-gate", "constraints-aurora-active", '
            '"domain-aurora-governance", "evidence-aurora-final"]'
            "}"
        )
        executor = OpenAIExecutorSmoke(
            model="example-openai-executor",
            max_output_tokens=600,
            provider=provider,  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], executor=executor)
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertEqual(report["metadata"]["executor_mode"], "openai_executor_smoke")
        self.assertEqual(report["metadata"]["executor_provider"], "openai-api")
        self.assertEqual(report["metadata"]["executor_model"], "example-openai-executor")
        self.assertEqual(spatial_run["executor"], "openai_executor_smoke")
        self.assertTrue(spatial_run["executor_output_parse_success"])
        self.assertTrue(spatial_run["output_validation_before_repair"])
        self.assertTrue(spatial_run["honest_multi_zone_pass"])
        self.assertEqual(spatial_run["openai_executor"]["usage"]["total_tokens"], 555)
        self.assertEqual(report["summary"]["openai_executor_actual_usage"]["total_tokens"], 555)
        self.assertEqual(len(provider.calls), 1)
        self.assertIn("Selected-zone context:", provider.calls[0]["messages"][0]["content"])
        self.assertNotIn("distractor-aurora-mz1-draft", provider.calls[0]["messages"][0]["content"])

    def test_mocked_openai_executor_missing_required_field_fails(self) -> None:
        provider = FakeOpenAIExecutorProvider(
            "{"
            '"active_version": "AUR-2026.09-mz2", '
            '"rollback_threshold": "27.4 credits per thousand governed requests for three consecutive ten-minute windows", '
            '"excluded_dataset": "RavenReplay-204", '
            '"launch_approval_owner": "AURORA_OWNER_MZ2", '
            '"governed_request_class": "customer-visible writes", '
            '"evidence_zone_ids": ["intent-aurora-gate", "constraints-aurora-active", '
            '"domain-aurora-governance", "evidence-aurora-final"]'
            "}"
        )
        executor = OpenAIExecutorSmoke(
            model="example-openai-executor",
            provider=provider,  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], executor=executor)
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertFalse(spatial_run["executor_output_parse_success"])
        self.assertIn("missing required fields", spatial_run["executor_output_parse_error"])
        self.assertFalse(spatial_run["output_validation_before_repair"])
        self.assertFalse(spatial_run["honest_multi_zone_pass"])

    def test_mocked_openai_executor_wrong_evidence_zone_ids_fails(self) -> None:
        provider = FakeOpenAIExecutorProvider(
            "{"
            '"active_version": "AUR-2026.09-mz2", '
            '"rollback_threshold": "27.4 credits per thousand governed requests for three consecutive ten-minute windows", '
            '"excluded_dataset": "RavenReplay-204", '
            '"launch_approval_owner": "AURORA_OWNER_MZ2", '
            '"mitigation_label": "aurora_mz2_epoch_lock", '
            '"governed_request_class": "customer-visible writes", '
            '"evidence_zone_ids": ["intent-aurora-gate", "constraints-aurora-active", '
            '"evidence-aurora-final", "distractor-aurora-dashboard"]'
            "}"
        )
        executor = OpenAIExecutorSmoke(
            model="example-openai-executor",
            provider=provider,  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], executor=executor)
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertTrue(spatial_run["executor_output_parse_success"])
        self.assertFalse(spatial_run["output_validation_before_repair"])
        self.assertFalse(spatial_run["honest_multi_zone_pass"])
        self.assertEqual(
            spatial_run["output_validation"]["evidence_reference_validation"]["missing_zone_ids"],
            ["domain-aurora-governance"],
        )
        self.assertEqual(
            spatial_run["output_validation"]["evidence_reference_validation"]["unexpected_zone_ids"],
            ["distractor-aurora-dashboard"],
        )

    def test_mocked_openai_executor_malformed_json_fails(self) -> None:
        executor = OpenAIExecutorSmoke(
            model="example-openai-executor",
            provider=FakeOpenAIExecutorProvider("not-json"),  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], executor=executor)
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertFalse(spatial_run["executor_output_parse_success"])
        self.assertTrue(spatial_run["executor_output_parse_error"])
        self.assertFalse(spatial_run["output_validation_before_repair"])
        self.assertFalse(spatial_run["honest_multi_zone_pass"])

    def test_mocked_openai_executor_json_with_extra_text_fails(self) -> None:
        executor = OpenAIExecutorSmoke(
            model="example-openai-executor",
            provider=FakeOpenAIExecutorProvider(
                "Here is the answer: {\"active_version\": \"AUR-2026.09-mz2\"}"
            ),  # type: ignore[arg-type]
        )

        report = run_benchmark([self.task], executor=executor)
        spatial_run = [
            run for run in report["runs"] if run["mode"] == "spatial_multi_zone"
        ][0]

        self.assertFalse(spatial_run["executor_output_parse_success"])
        self.assertFalse(spatial_run["honest_multi_zone_pass"])

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
