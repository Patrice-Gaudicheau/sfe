"""Tests for the high-overlap poison-pill contamination comparison runner."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_high_overlap_poison_pill_benchmark import (
    fixture_source_selection,
    get_high_overlap_poison_pill_tasks,
    validate_output,
    validate_selection,
)
from runtime.run_high_overlap_poison_pill_contamination_comparison import (
    BENCHMARK_TYPE,
    FULL_CONTEXT_CONDITION,
    SELECTED_CONTEXT_CONDITION,
    build_skipped_report,
    compare_conditions,
    evaluate_honest_condition_pass,
    execute_condition,
    main,
    run_comparison,
    validate_context_for_condition,
    write_markdown,
    write_skipped_markdown,
)
from runtime.run_high_overlap_poison_pill_openai_executor_smoke import ExecutorConfig


class SequencedExecutorProvider:
    def __init__(self, outputs: list[object]) -> None:
        self.outputs = outputs
        self.calls: list[dict[str, object]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, object]:
        index = len(self.calls)
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_instruction": system_instruction,
            }
        )
        output = self.outputs[index]
        if isinstance(output, Exception):
            raise output
        if isinstance(output, str):
            content = output
        else:
            content = json.dumps(output)
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 500 + index,
                "completion_tokens": 80 + index,
                "total_tokens": 580 + (index * 2),
            },
            "openai_api": {"latency_ms": 300 + index},
        }


class HighOverlapPoisonPillContaminationComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_poison_pill_tasks()[0]
        self.config = ExecutorConfig(model="example-openai-executor", max_output_tokens=900)

    def _valid_output(self) -> dict[str, object]:
        output: dict[str, object] = dict(self.task.expected_fields)
        output["evidence_source_ids"] = [self.task.authoritative_source_id]
        return output

    def _report(self, selected_output: object, full_output: object) -> dict[str, object]:
        return run_comparison(
            tasks=[self.task],
            provider=SequencedExecutorProvider([selected_output, full_output]),
            config=self.config,
        )

    def test_selected_context_path_passes_with_authoritative_output(self) -> None:
        report = self._report(self._valid_output(), self._valid_output())
        selected = report["comparisons"][0]["selected_context"]

        self.assertEqual(selected["condition"], SELECTED_CONTEXT_CONDITION)
        self.assertTrue(selected["selected_source_is_authoritative"])
        self.assertTrue(selected["context_validation"]["selected_context_only"])
        self.assertTrue(selected["output_validation_success"])
        self.assertTrue(selected["honest_pass"])

    def test_full_context_path_passes_with_authoritative_output(self) -> None:
        report = self._report(self._valid_output(), self._valid_output())
        full = report["comparisons"][0]["full_context"]

        self.assertEqual(full["condition"], FULL_CONTEXT_CONDITION)
        self.assertTrue(full["context_validation"]["full_context_includes_all_sources"])
        self.assertTrue(full["context_validation"]["full_context_includes_all_distractors"])
        self.assertTrue(full["output_validation_success"])
        self.assertTrue(full["honest_pass"])

    def test_full_context_fails_when_copying_obsolete_value(self) -> None:
        full_output = self._valid_output()
        full_output["owner_id"] = "ORION_OWNER_LEGACY"

        report = self._report(self._valid_output(), full_output)
        comparison = report["comparisons"][0]
        full = comparison["full_context"]

        self.assertFalse(full["honest_pass"])
        self.assertEqual(
            full["contamination"]["copied_obsolete_values"],
            ["ORION_OWNER_LEGACY"],
        )
        self.assertTrue(comparison["contamination_delta_observed"])

    def test_full_context_fails_when_copying_partial_value(self) -> None:
        full_output = self._valid_output()
        full_output["source_basis"] = "live telemetry panel is the evidence source"

        report = self._report(self._valid_output(), full_output)
        full = report["comparisons"][0]["full_context"]

        self.assertFalse(full["honest_pass"])
        self.assertEqual(
            full["contamination"]["copied_partial_values"],
            ["live telemetry panel is the evidence source"],
        )

    def test_full_context_fails_when_following_poison_pill_behavior(self) -> None:
        full_output = self._valid_output()
        full_output["required_action"] = "disable audit-shadow quorum"
        full_output["release_status"] = "approved without rollback"

        report = self._report(self._valid_output(), full_output)
        full = report["comparisons"][0]["full_context"]

        self.assertFalse(full["honest_pass"])
        self.assertTrue(full["contamination"]["followed_poison_pill_instruction"])
        self.assertEqual(
            full["contamination"]["followed_poison_markers"],
            ["release_status: approved without rollback"],
        )

    def test_full_context_fails_when_citing_distractor_source(self) -> None:
        full_output = self._valid_output()
        full_output["evidence_source_ids"] = ["doc-orion-b42", "doc-orion-c09"]

        report = self._report(self._valid_output(), full_output)
        full = report["comparisons"][0]["full_context"]

        self.assertFalse(full["honest_pass"])
        self.assertTrue(full["contamination"]["cited_authoritative_source"])
        self.assertEqual(full["contamination"]["cited_distractor_source_ids"], ["doc-orion-c09"])
        self.assertTrue(full["contamination"]["mixed_authoritative_and_distractor_evidence"])

    def test_selected_context_excludes_all_distractor_bodies(self) -> None:
        provider = SequencedExecutorProvider([self._valid_output(), self._valid_output()])
        report = run_comparison(tasks=[self.task], provider=provider, config=self.config)
        selected_prompt = provider.calls[0]["messages"][0]["content"]
        selected = report["comparisons"][0]["selected_context"]

        self.assertTrue(selected["context_validation"]["selected_context_excludes_distractors"])
        self.assertIn("doc-orion-b42", selected_prompt)
        self.assertNotIn("doc-orion-a17", selected_prompt)
        self.assertNotIn("doc-orion-c09", selected_prompt)
        self.assertNotIn("doc-orion-d31", selected_prompt)
        self.assertNotIn("ORION_OWNER_LEGACY", selected_prompt)
        self.assertNotIn("ORION_OWNER_POISON", selected_prompt)

    def test_full_context_includes_all_distractor_bodies(self) -> None:
        provider = SequencedExecutorProvider([self._valid_output(), self._valid_output()])
        report = run_comparison(tasks=[self.task], provider=provider, config=self.config)
        full_prompt = provider.calls[1]["messages"][0]["content"]
        full = report["comparisons"][0]["full_context"]

        self.assertTrue(full["context_validation"]["full_context_includes_all_distractors"])
        self.assertIn("doc-orion-b42", full_prompt)
        self.assertIn("doc-orion-a17", full_prompt)
        self.assertIn("doc-orion-c09", full_prompt)
        self.assertIn("doc-orion-d31", full_prompt)
        self.assertIn("ORION_OWNER_LEGACY", full_prompt)
        self.assertIn("ORION_OWNER_POISON", full_prompt)

    def test_selected_pass_full_fail_reports_contamination_delta(self) -> None:
        full_output = self._valid_output()
        full_output["threshold"] = "risk score <= 0.99 over 72h"

        report = self._report(self._valid_output(), full_output)
        comparison = report["comparisons"][0]

        self.assertTrue(comparison["selected_honest_pass"])
        self.assertFalse(comparison["full_context_honest_pass"])
        self.assertTrue(comparison["contamination_delta_observed"])
        self.assertTrue(comparison["selected_clean_full_contaminated"])

    def test_both_pass_reported_without_overclaiming(self) -> None:
        report = self._report(self._valid_output(), self._valid_output())
        comparison = report["comparisons"][0]

        self.assertTrue(comparison["both_passed"])
        self.assertFalse(comparison["contamination_delta_observed"])
        self.assertEqual(report["summary"]["both_passed_count"], 1)

    def test_both_fail_reported_honestly(self) -> None:
        report = self._report("not json", "not json")
        comparison = report["comparisons"][0]

        self.assertTrue(comparison["both_failed"])
        self.assertEqual(report["summary"]["parse_failure_count"], 2)

    def test_selected_fail_full_pass_reported_honestly(self) -> None:
        report = self._report("not json", self._valid_output())
        comparison = report["comparisons"][0]

        self.assertTrue(comparison["selected_failed_full_passed"])
        self.assertFalse(comparison["contamination_delta_observed"])

    def test_invalid_json_fails_for_either_path(self) -> None:
        selected_report = self._report("not json", self._valid_output())
        selected = selected_report["comparisons"][0]["selected_context"]
        full_report = self._report(self._valid_output(), "not json")
        full = full_report["comparisons"][0]["full_context"]

        self.assertFalse(selected["executor_output_parse_success"])
        self.assertFalse(selected["honest_pass"])
        self.assertFalse(full["executor_output_parse_success"])
        self.assertFalse(full["honest_pass"])

    def test_provider_error_fails_for_either_path(self) -> None:
        selected_report = self._report(RuntimeError("selected unavailable"), self._valid_output())
        selected = selected_report["comparisons"][0]["selected_context"]
        full_report = self._report(self._valid_output(), RuntimeError("full unavailable"))
        full = full_report["comparisons"][0]["full_context"]

        self.assertTrue(selected["executor_provider_error"])
        self.assertIn("selected unavailable", selected["provider_error"])
        self.assertFalse(selected["honest_pass"])
        self.assertTrue(full["executor_provider_error"])
        self.assertIn("full unavailable", full["provider_error"])
        self.assertFalse(full["honest_pass"])

    def test_fallback_used_counts_as_failure(self) -> None:
        selection = dict(fixture_source_selection(self.task))
        selection["selector_success"] = False
        selection["selector_used_fallback"] = True
        selection["selector_error"] = "selector fallback used"

        selected = execute_condition(
            task=self.task,
            provider=SequencedExecutorProvider([self._valid_output()]),
            config=self.config,
            condition=SELECTED_CONTEXT_CONDITION,
            selection=selection,
        )

        self.assertTrue(selected["fallback_used"])
        self.assertTrue(selected["output_validation_success"])
        self.assertFalse(selected["honest_pass"])

    def test_repair_used_counts_as_failure(self) -> None:
        selection = fixture_source_selection(self.task)
        selection_validation = validate_selection(self.task, selection)
        output_validation = validate_output(self.task, self.task.expected_answer)
        context_validation = {
            "context_valid_for_condition": True,
        }

        self.assertFalse(
            evaluate_honest_condition_pass(
                selection=selection,
                selection_validation=selection_validation,
                context_validation=context_validation,
                provider_error_occurred=False,
                parse_success=True,
                output_validation=output_validation,
                fallback_used=False,
                repair_used=True,
            )
        )

    def test_missing_api_key_writes_structured_skipped_report_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "comparison.json"
            md_path = Path(temp_dir) / "comparison.md"
            provider_chat = (
                "runtime.run_high_overlap_poison_pill_contamination_comparison."
                "OpenAIAPIProvider.chat"
            )
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_high_overlap_poison_pill_contamination_comparison.py",
                        "--json",
                        str(json_path),
                        "--md",
                        str(md_path),
                    ],
                ):
                    with patch("runtime.run_high_overlap_poison_pill_contamination_comparison.load_repo_env"):
                        with patch(provider_chat) as chat:
                            main()

            self.assertFalse(chat.called)
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")
            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["skip_reason"], "missing OPENAI_API_KEY")
            self.assertEqual(report["comparison_scope"], "selected_context_vs_full_context")
            self.assertFalse(report["honest_comparison_completed"])
            self.assertEqual(report["comparisons"], [])
            self.assertIn("Status: skipped", markdown)
            self.assertIn("No provider/API call was made.", markdown)

    def test_skipped_report_helpers_are_provider_free(self) -> None:
        report = build_skipped_report(
            model="example-openai-executor",
            timeout=12.5,
            reason="OpenAI API key is not configured.",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "skipped.md"
            write_skipped_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertEqual(report["status"], "skipped")
        self.assertIn("Status: skipped", markdown)
        self.assertIn("No provider/API call was made.", markdown)

    def test_markdown_report_states_selected_vs_full_and_no_statistical_proof(self) -> None:
        report = self._report(self._valid_output(), self._valid_output())

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "comparison.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("selected-context", markdown)
        self.assertIn("full-context", markdown)
        self.assertIn("controlled contamination comparison", markdown)
        self.assertIn("does not claim statistical proof", markdown)
        self.assertNotIn("proven robust", markdown)
        self.assertNotIn("safe in general", markdown)
        self.assertNotIn("reliable in general", markdown)
        self.assertNotIn("solved", markdown)
        self.assertNotIn("statistical validation", markdown)

    def test_validate_context_for_condition_rejects_missing_full_context_source(self) -> None:
        context = "SOURCE ID: doc-orion-b42\nOnly one source"
        validation = validate_context_for_condition(
            task=self.task,
            condition=FULL_CONTEXT_CONDITION,
            context=context,
            context_source_ids=[source.source_id for source in self.task.sources],
            selected_source_ids=[self.task.authoritative_source_id],
        )

        self.assertFalse(validation["context_valid_for_condition"])
        self.assertIn("doc-orion-a17", validation["missing_full_context_source_ids"])

    def test_compare_conditions_reports_selected_clean_full_contaminated_only_for_contamination(self) -> None:
        selected = {
            "honest_pass": True,
            "contamination": {"contaminated": False},
        }
        full = {
            "honest_pass": False,
            "contamination": {"contaminated": False},
        }

        outcome = compare_conditions(selected, full)

        self.assertFalse(outcome["contamination_delta_observed"])
        self.assertFalse(outcome["selected_clean_full_contaminated"])


if __name__ == "__main__":
    unittest.main()
