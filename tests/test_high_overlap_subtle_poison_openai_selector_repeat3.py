"""Tests for the high-overlap subtle-poison OpenAI selector repeat-3 smoke."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_high_overlap_subtle_poison_benchmark import get_high_overlap_subtle_poison_tasks
from runtime.run_high_overlap_subtle_poison_openai_selector_repeat3 import (
    BENCHMARK_TYPE,
    DEFAULT_REPEAT,
    SelectorConfig,
    _parse_args,
    build_skipped_report,
    main,
    run_repeat_smoke,
    summarize_repeat_runs,
    write_markdown,
    write_skipped_markdown,
)
from runtime.run_high_overlap_subtle_poison_openai_selector_smoke import (
    build_prompt_source_aliases,
    build_selector_prompt,
)


class SequencedSelectorProvider:
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
            selected = list(output)
            content = json.dumps(
                {
                    "selected_source_ids": selected,
                    "selection_rationale": {
                        source_id: "test rationale" for source_id in selected
                    },
                }
            )
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 120 + index,
                "completion_tokens": 12 + index,
                "total_tokens": 132 + (index * 2),
            },
            "openai_api": {"latency_ms": 30 + index},
        }


class HighOverlapSubtlePoisonOpenAISelectorRepeat3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_subtle_poison_tasks()[0]
        self.tasks = [self.task]
        self.alias_map = build_prompt_source_aliases(self.task)
        self.config = SelectorConfig(model="example-openai-router", max_output_tokens=700)

    def _alias_for_source(self, source_id: str) -> str:
        for alias, actual_source_id in self.alias_map.items():
            if actual_source_id == source_id:
                return alias
        raise AssertionError(f"No alias for source {source_id}")

    def _report(self, outputs: list[object]) -> dict[str, object]:
        return run_repeat_smoke(
            tasks=self.tasks,
            provider=SequencedSelectorProvider(outputs),
            config=self.config,
        )

    def test_default_cli_repeat_is_three(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_high_overlap_subtle_poison_openai_selector_repeat3.py"],
        ):
            args = _parse_args()

        self.assertEqual(args.repeat, DEFAULT_REPEAT)
        self.assertEqual(args.repeat, 3)

    def test_cli_rejects_non_three_repeat_before_provider_work(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_high_overlap_subtle_poison_openai_selector_repeat3.py", "--repeat", "1"],
        ):
            with patch(
                "runtime.run_high_overlap_subtle_poison_openai_selector_repeat3.load_repo_env"
            ) as load_env:
                with patch(
                    "runtime.run_high_overlap_subtle_poison_openai_selector_repeat3.OpenAIAPIProvider"
                ) as provider:
                    with self.assertRaises(SystemExit):
                        main()

        self.assertFalse(load_env.called)
        self.assertFalse(provider.called)

    def test_prompt_remains_blind_for_repeat_runner(self) -> None:
        prompt = build_selector_prompt(self.task, self.alias_map)

        self.assertIn("candidate handles only", prompt)
        self.assertNotIn(self.task.authoritative_source_id, prompt)
        self.assertNotIn("helios-u22", prompt)
        self.assertNotIn("helios-k03", prompt)
        self.assertNotIn("helios-m51", prompt)
        for forbidden in ("fake", "poison", "invalid", "adversarial", "trap", "distractor"):
            self.assertNotIn(forbidden, prompt.lower())

    def test_all_three_runs_pass(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = self._report(
            [[authoritative_alias], [authoritative_alias], [authoritative_alias]]
        )
        summary = report["summary"]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["repeat"], 3)
        self.assertEqual(report["metadata"]["selector_scope"], "source_selection_only")
        self.assertEqual(report["metadata"]["executor"], "not_tested")
        self.assertEqual(report["metadata"]["comparison_scope"], "not_tested")
        self.assertEqual(summary["total_runs"], 3)
        self.assertEqual(summary["honest_pass_count"], 3)
        self.assertEqual(summary["honest_fail_count"], 0)
        self.assertTrue(summary["all_runs_honest_pass"])
        self.assertFalse(summary["any_selector_failure"])
        self.assertFalse(summary["any_provider_error"])
        self.assertFalse(summary["any_parse_failure"])
        self.assertFalse(summary["any_fallback"])
        self.assertFalse(summary["any_repair"])
        self.assertEqual(summary["total_prompt_tokens"], 363)
        self.assertEqual(summary["total_completion_tokens"], 39)
        self.assertEqual(summary["total_tokens"], 402)
        self.assertEqual(summary["total_latency_ms"], 93)
        self.assertEqual([run["run_index"] for run in report["runs"]], [1, 2, 3])
        self.assertEqual(
            [run["selected_prompt_source_ids"] for run in report["runs"]],
            [[authoritative_alias], [authoritative_alias], [authoritative_alias]],
        )
        self.assertTrue(all(run["honest_selector_pass"] for run in report["runs"]))

    def test_one_failed_run_makes_all_runs_honest_pass_false(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        subtle_alias = self._alias_for_source("helios-u22")
        report = self._report([[authoritative_alias], [subtle_alias], [authoritative_alias]])
        summary = report["summary"]

        self.assertEqual(summary["honest_pass_count"], 2)
        self.assertEqual(summary["honest_fail_count"], 1)
        self.assertFalse(summary["all_runs_honest_pass"])
        self.assertTrue(summary["any_selector_failure"])
        self.assertEqual(summary["subtle_poison_selection_count"], 1)
        self.assertFalse(report["runs"][1]["subtle_poison_sources_omitted"])
        self.assertEqual(report["runs"][1]["selected_subtle_poison_source_ids"], ["helios-u22"])

    def test_obsolete_or_partial_selection_in_any_run_is_counted(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        obsolete_alias = self._alias_for_source("helios-k03")
        partial_alias = self._alias_for_source("helios-m51")
        obsolete_report = self._report(
            [[authoritative_alias], [obsolete_alias], [authoritative_alias]]
        )
        partial_report = self._report(
            [[authoritative_alias], [partial_alias], [authoritative_alias]]
        )

        self.assertEqual(obsolete_report["summary"]["obsolete_selection_count"], 1)
        self.assertTrue(obsolete_report["summary"]["any_selector_failure"])
        self.assertFalse(obsolete_report["runs"][1]["obsolete_sources_omitted"])
        self.assertEqual(partial_report["summary"]["partial_selection_count"], 1)
        self.assertTrue(partial_report["summary"]["any_selector_failure"])
        self.assertFalse(partial_report["runs"][1]["partial_sources_omitted"])

    def test_provider_error_in_any_run_is_honest_failure(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = self._report(
            [[authoritative_alias], RuntimeError("selector unavailable"), [authoritative_alias]]
        )
        summary = report["summary"]

        self.assertEqual(summary["honest_pass_count"], 2)
        self.assertEqual(summary["honest_fail_count"], 1)
        self.assertTrue(summary["any_selector_failure"])
        self.assertTrue(summary["any_provider_error"])
        self.assertTrue(summary["any_parse_failure"])
        self.assertFalse(summary["any_fallback"])
        self.assertFalse(report["runs"][1]["parse_success"])
        self.assertTrue(report["runs"][1]["selector_provider_error"])
        self.assertIn("selector unavailable", report["runs"][1]["selector_error"])

    def test_parse_failure_in_any_run_is_honest_failure(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = self._report([[authoritative_alias], "not json", [authoritative_alias]])
        summary = report["summary"]

        self.assertEqual(summary["honest_pass_count"], 2)
        self.assertEqual(summary["honest_fail_count"], 1)
        self.assertTrue(summary["any_selector_failure"])
        self.assertFalse(summary["any_provider_error"])
        self.assertTrue(summary["any_parse_failure"])
        self.assertFalse(summary["any_fallback"])
        self.assertFalse(report["runs"][1]["parse_success"])
        self.assertIn("Expecting value", report["runs"][1]["parse_error"])

    def test_unknown_candidate_handle_is_honest_failure(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = self._report([[authoritative_alias], ["candidate-99"], [authoritative_alias]])

        self.assertTrue(report["summary"]["any_selector_failure"])
        self.assertEqual(report["runs"][1]["unknown_selected_source_ids"], ["candidate-99"])
        self.assertFalse(report["runs"][1]["honest_selector_pass"])

    def test_fallback_or_repair_in_any_run_prevents_clean_aggregate(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = self._report(
            [[authoritative_alias], [authoritative_alias], [authoritative_alias]]
        )
        runs = [dict(run) for run in report["runs"]]
        runs[1]["fallback_used"] = True
        runs[1]["honest_selector_pass"] = False
        fallback_summary = summarize_repeat_runs(runs)
        runs[1]["fallback_used"] = False
        runs[1]["repair_used"] = True
        repair_summary = summarize_repeat_runs(runs)

        self.assertTrue(fallback_summary["any_fallback"])
        self.assertFalse(fallback_summary["all_runs_honest_pass"])
        self.assertTrue(repair_summary["any_repair"])
        self.assertFalse(repair_summary["all_runs_honest_pass"])

    def test_summarize_repeat_runs_handles_missing_usage_and_latency(self) -> None:
        runs = [
            {
                "honest_selector_pass": False,
                "fallback_used": False,
                "repair_used": False,
                "selector_provider_error": True,
                "parse_success": False,
                "selected_subtle_poison_source_ids": [],
                "selected_obsolete_source_ids": [],
                "selected_partial_source_ids": [],
                "authoritative_source_selected": False,
                "extra_selected_source_ids": [],
                "usage": {
                    "input_tokens": None,
                    "output_tokens": None,
                    "total_tokens": None,
                },
                "latency_ms": None,
            }
        ]

        summary = summarize_repeat_runs(runs)

        self.assertEqual(summary["total_runs"], 1)
        self.assertEqual(summary["honest_fail_count"], 1)
        self.assertTrue(summary["any_provider_error"])
        self.assertIsNone(summary["total_tokens"])
        self.assertIsNone(summary["total_latency_ms"])

    def test_markdown_report_is_cautious_repeat3_observation(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = self._report(
            [[authoritative_alias], [authoritative_alias], [authoritative_alias]]
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "repeat3.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("OpenAI selector repeat-3 smoke", markdown)
        self.assertIn("controlled subtle-poison", markdown)
        self.assertIn("authority-gap reasoning", markdown)
        self.assertIn("selector-only", markdown)
        self.assertIn("no executor was tested", markdown)
        self.assertIn("not statistical proof", markdown)
        self.assertIn("not a reliability benchmark", markdown)
        self.assertIn("Selector failure is a valid observation", markdown)
        self.assertIn("Honest selector pass count: 3/3", markdown)
        self.assertNotIn("proven robust", markdown)
        self.assertNotIn("reliable in general", markdown)
        self.assertNotIn("safe in general", markdown)
        self.assertNotIn("solved", markdown)
        self.assertNotIn("statistically validated", markdown)

    def test_missing_api_key_writes_structured_skipped_reports_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "repeat3.json"
            md_path = Path(temp_dir) / "repeat3.md"
            provider_chat = (
                "runtime.run_high_overlap_subtle_poison_openai_selector_repeat3."
                "OpenAIAPIProvider.chat"
            )
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_high_overlap_subtle_poison_openai_selector_repeat3.py",
                        "--json",
                        str(json_path),
                        "--md",
                        str(md_path),
                    ],
                ):
                    with patch(
                        "runtime.run_high_overlap_subtle_poison_openai_selector_repeat3.load_repo_env"
                    ):
                        with patch(provider_chat) as chat:
                            main()

            self.assertFalse(chat.called)
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")
            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["skip_reason"], "missing OPENAI_API_KEY")
            self.assertTrue(report["skipped"])
            self.assertEqual(report["total_runs"], 0)
            self.assertEqual(report["repeat"], 3)
            self.assertFalse(report["honest_selector_pass"])
            self.assertEqual(report["runs"], [])
            self.assertIn("Status: skipped", markdown)
            self.assertIn("Repeat count: 3", markdown)
            self.assertIn("No provider/API call was made.", markdown)

    def test_skipped_report_helpers_are_provider_free(self) -> None:
        report = build_skipped_report(
            model="example-router",
            timeout=10.0,
            repeat=3,
            reason="OpenAI API key is not configured.",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "skipped.md"
            write_skipped_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertEqual(report["status"], "skipped")
        self.assertTrue(report["skipped"])
        self.assertFalse(report["honest_selector_pass"])
        self.assertIn("Status: skipped", markdown)
        self.assertIn("No provider/API call was made.", markdown)


if __name__ == "__main__":
    unittest.main()
