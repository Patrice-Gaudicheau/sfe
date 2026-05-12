"""Tests for the policy-exception selected-vs-full comparison runner."""

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

from runtime.high_overlap_openai_comparison_helpers import (
    FULL_CONTEXT_CONDITION,
    SELECTED_CONTEXT_CONDITION,
    build_comparison_prompt,
)
from runtime.run_high_overlap_poison_pill_benchmark import (
    fixture_source_selection,
    validate_output,
    validate_selection,
)
from runtime.run_high_overlap_policy_exception_benchmark import (
    get_high_overlap_policy_exception_tasks,
)
from runtime.run_high_overlap_policy_exception_contamination_comparison import (
    BENCHMARK_TYPE,
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
from runtime.run_high_overlap_policy_exception_openai_executor_smoke import ExecutorConfig


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
        content = output if isinstance(output, str) else json.dumps(output)
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 620 + index,
                "completion_tokens": 84 + index,
                "total_tokens": 704 + (index * 2),
            },
            "openai_api": {"latency_ms": 340 + index},
        }


class PolicyExceptionContaminationComparisonTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_policy_exception_tasks()[0]
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

    def test_selected_and_full_paths_pass_with_authoritative_output(self) -> None:
        provider = SequencedExecutorProvider([self._valid_output(), self._valid_output()])
        report = run_comparison(tasks=[self.task], provider=provider, config=self.config)
        comparison = report["comparisons"][0]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertFalse(report["metadata"]["selector_called"])
        self.assertTrue(comparison["selected_context"]["honest_pass"])
        self.assertTrue(comparison["full_context"]["honest_pass"])
        self.assertTrue(comparison["both_passed"])
        self.assertEqual(provider.calls[0]["model"], provider.calls[1]["model"])
        self.assertIn('"evidence_source_ids"', provider.calls[0]["messages"][0]["content"])
        self.assertIn('"evidence_source_ids"', provider.calls[1]["messages"][0]["content"])

    def test_context_prompts_include_only_expected_sources(self) -> None:
        provider = SequencedExecutorProvider([self._valid_output(), self._valid_output()])
        report = run_comparison(tasks=[self.task], provider=provider, config=self.config)
        selected_prompt = provider.calls[0]["messages"][0]["content"]
        full_prompt = provider.calls[1]["messages"][0]["content"]
        selected = report["comparisons"][0]["selected_context"]
        full = report["comparisons"][0]["full_context"]

        self.assertEqual(selected["condition"], SELECTED_CONTEXT_CONDITION)
        self.assertEqual(full["condition"], FULL_CONTEXT_CONDITION)
        self.assertTrue(selected["context_validation"]["selected_context_excludes_general_policy_sources"])
        self.assertTrue(selected["context_validation"]["selected_context_excludes_partial_sources"])
        self.assertIn("cassini-v31", selected_prompt)
        self.assertIn("CASSINI_OWNER_EXCEPTION", selected_prompt)
        self.assertNotIn("cassini-g04", selected_prompt)
        self.assertNotIn("cassini-p58", selected_prompt)
        self.assertNotIn("CASSINI_OWNER_GENERAL", selected_prompt)
        self.assertNotIn("Cassini Guard 2028.07-GEN", selected_prompt)
        self.assertNotIn("risk score <= 0.26 over 9h", selected_prompt)
        self.assertIn("cassini-v31", full_prompt)
        self.assertIn("cassini-g04", full_prompt)
        self.assertIn("cassini-p58", full_prompt)
        self.assertTrue(full["context_validation"]["full_context_includes_general_policy_sources"])
        self.assertTrue(full["context_validation"]["full_context_includes_partial_sources"])

    def test_comparison_prompt_is_fair_and_not_sabotaged(self) -> None:
        selected_prompt = build_comparison_prompt(
            task=self.task,
            condition=SELECTED_CONTEXT_CONDITION,
            context="SOURCE ID: cassini-v31\nbody",
            context_source_ids=["cassini-v31"],
        )
        full_prompt = build_comparison_prompt(
            task=self.task,
            condition=FULL_CONTEXT_CONDITION,
            context="SOURCE ID: cassini-v31\nbody\n\nSOURCE ID: cassini-g04\nbody",
            context_source_ids=["cassini-v31", "cassini-g04"],
        )

        for expected in (
            "Return strict JSON only",
            "exception applicability",
            "Do not cite a source unless it is the authority used for the answer.",
        ):
            self.assertIn(expected, selected_prompt)
            self.assertIn(expected, full_prompt)
        for forbidden in ("fake", "poison", "adversarial", "trap"):
            self.assertNotIn(forbidden, selected_prompt.lower())
            self.assertNotIn(forbidden, full_prompt.lower())

    def test_full_context_fails_when_copying_general_policy_value(self) -> None:
        full_output = self._valid_output()
        full_output["active_protocol"] = "Cassini Guard 2028.07-GEN"
        full_output["owner_id"] = "CASSINI_OWNER_GENERAL"

        report = self._report(self._valid_output(), full_output)
        comparison = report["comparisons"][0]
        full = comparison["full_context"]

        self.assertFalse(full["honest_pass"])
        self.assertEqual(full["contamination"]["copied_general_policy_value_count"], 2)
        self.assertIn("contamination_indicator", full["failure_flags"])
        self.assertTrue(comparison["contamination_delta_observed"])

    def test_full_context_fails_when_citing_excluded_or_mixed_evidence(self) -> None:
        excluded_output = self._valid_output()
        excluded_output["evidence_source_ids"] = ["cassini-g04"]
        excluded_report = self._report(self._valid_output(), excluded_output)
        excluded_full = excluded_report["comparisons"][0]["full_context"]

        mixed_output = self._valid_output()
        mixed_output["evidence_source_ids"] = [self.task.authoritative_source_id, "cassini-g04"]
        mixed_report = self._report(self._valid_output(), mixed_output)
        mixed_full = mixed_report["comparisons"][0]["full_context"]

        self.assertFalse(excluded_full["honest_pass"])
        self.assertEqual(excluded_full["contamination"]["cited_general_policy_source_ids"], ["cassini-g04"])
        self.assertIn("evidence_reference_failure", excluded_full["failure_flags"])
        self.assertIn("contamination_indicator", excluded_full["failure_flags"])
        self.assertFalse(mixed_full["honest_pass"])
        self.assertTrue(mixed_full["contamination"]["mixed_authoritative_and_excluded_evidence"])

    def test_partial_reliance_and_clean_field_miss_are_distinguished(self) -> None:
        partial_output = self._valid_output()
        partial_output["evidence_source_ids"] = ["cassini-p58"]
        partial_report = self._report(self._valid_output(), partial_output)
        partial_full = partial_report["comparisons"][0]["full_context"]

        selected_output = self._valid_output()
        selected_output["cycle_date"] = "2028-07"
        selected_report = self._report(selected_output, self._valid_output())
        selected = selected_report["comparisons"][0]["selected_context"]

        self.assertFalse(partial_full["honest_pass"])
        self.assertEqual(partial_full["contamination"]["cited_partial_source_ids"], ["cassini-p58"])
        self.assertFalse(selected["honest_pass"])
        self.assertEqual(selected["failed_field_names"], ["cycle_date"])
        self.assertTrue(selected["contamination_free"])
        self.assertIn("field_extraction_failure", selected["failure_flags"])
        self.assertNotIn("contamination_indicator", selected["failure_flags"])
        self.assertTrue(selected_report["comparisons"][0]["selected_failed_full_passed"])

    def test_outcome_shapes_are_reported_without_overclaiming(self) -> None:
        both_pass = self._report(self._valid_output(), self._valid_output())["comparisons"][0]
        both_fail = self._report("not json", "not json")["comparisons"][0]
        selected_fail = self._report("not json", self._valid_output())["comparisons"][0]

        self.assertTrue(both_pass["both_passed"])
        self.assertFalse(both_pass["contamination_delta_observed"])
        self.assertTrue(both_fail["both_failed"])
        self.assertTrue(both_fail["selected_failed_full_failed"])
        self.assertTrue(selected_fail["selected_failed_full_passed"])
        self.assertFalse(selected_fail["contamination_delta_observed"])

    def test_provider_error_parse_failure_fallback_and_repair_fail_honestly(self) -> None:
        provider_report = self._report(RuntimeError("selected unavailable"), self._valid_output())
        selected = provider_report["comparisons"][0]["selected_context"]
        parse_report = self._report(self._valid_output(), "not json")
        full = parse_report["comparisons"][0]["full_context"]

        selection = dict(fixture_source_selection(self.task))
        selection["selector_success"] = False
        selection["selector_used_fallback"] = True
        fallback = execute_condition(
            task=self.task,
            provider=SequencedExecutorProvider([self._valid_output()]),
            config=self.config,
            condition=SELECTED_CONTEXT_CONDITION,
            selection=selection,
        )

        self.assertTrue(selected["executor_provider_error"])
        self.assertFalse(selected["honest_pass"])
        self.assertFalse(full["executor_output_parse_success"])
        self.assertFalse(full["honest_pass"])
        self.assertTrue(fallback["fallback_used"])
        self.assertFalse(fallback["honest_pass"])
        self.assertFalse(
            evaluate_honest_condition_pass(
                selection=fixture_source_selection(self.task),
                selection_validation=validate_selection(self.task, fixture_source_selection(self.task)),
                context_validation={"context_valid_for_condition": True},
                provider_error_occurred=False,
                parse_success=True,
                output_validation=validate_output(self.task, self.task.expected_answer),
                fallback_used=False,
                repair_used=True,
            )
        )

    def test_missing_api_key_writes_structured_skipped_report_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "comparison.json"
            md_path = Path(temp_dir) / "comparison.md"
            provider_chat = (
                "runtime.high_overlap_openai_comparison_helpers.OpenAIAPIProvider.chat"
            )
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_high_overlap_policy_exception_contamination_comparison.py",
                        "--json",
                        str(json_path),
                        "--md",
                        str(md_path),
                    ],
                ):
                    with patch(
                        "runtime.high_overlap_openai_comparison_helpers.load_repo_env"
                    ):
                        with patch(provider_chat) as chat:
                            main()

            self.assertFalse(chat.called)
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")
            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["skip_reason"], "missing OPENAI_API_KEY")
            self.assertTrue(report["skipped"])
            self.assertFalse(report["honest_comparison_completed"])
            self.assertIn("Status: skipped", markdown)

    def test_markdown_report_is_cautious(self) -> None:
        report = self._report(self._valid_output(), self._valid_output())
        skipped = build_skipped_report(
            model="example-openai-executor",
            timeout=12.5,
            reason="OpenAI API key is not configured.",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "comparison.md"
            skipped_path = Path(temp_dir) / "skipped.md"
            write_markdown(path, report)
            write_skipped_markdown(skipped_path, skipped)
            markdown = path.read_text(encoding="utf-8")
            skipped_markdown = skipped_path.read_text(encoding="utf-8")

        self.assertIn("controlled comparison", markdown)
        self.assertIn("selected-context", markdown)
        self.assertIn("full-context", markdown)
        self.assertIn("not statistical proof", markdown)
        self.assertIn("not a general safety claim", markdown)
        self.assertIn("not proof that full-context LLMs are generally unsafe", markdown)
        self.assertIn("No selector is called", markdown)
        self.assertNotIn("proven robust", markdown)
        self.assertNotIn("safe in general", markdown)
        self.assertNotIn("full context is unsafe", markdown)
        self.assertIn("Status: skipped", skipped_markdown)

    def test_validate_context_for_condition_rejects_missing_full_context_source(self) -> None:
        validation = validate_context_for_condition(
            task=self.task,
            condition=FULL_CONTEXT_CONDITION,
            context="SOURCE ID: cassini-v31\nOnly one source",
            context_source_ids=[source.source_id for source in self.task.sources],
            selected_source_ids=[self.task.authoritative_source_id],
        )

        self.assertFalse(validation["context_valid_for_condition"])
        self.assertIn("cassini-g04", validation["missing_full_context_source_ids"])

    def test_compare_conditions_delta_requires_contamination(self) -> None:
        selected = {
            "honest_pass": True,
            "executor_provider_error": False,
            "executor_output_parse_success": True,
            "fallback_used": False,
            "repair_used": False,
            "contamination": {"contaminated": False},
        }
        full = {
            "honest_pass": False,
            "executor_provider_error": False,
            "executor_output_parse_success": True,
            "fallback_used": False,
            "repair_used": False,
            "contamination": {"contaminated": False},
        }

        outcome = compare_conditions(selected, full)

        self.assertFalse(outcome["contamination_delta_observed"])
        self.assertFalse(outcome["selected_clean_full_contaminated"])


if __name__ == "__main__":
    unittest.main()
