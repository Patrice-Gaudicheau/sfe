"""Tests for the high-overlap poison-pill OpenAI selector repeat-3 smoke."""

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
    get_high_overlap_poison_pill_tasks,
)
from runtime.run_high_overlap_poison_pill_openai_selector_repeat3 import (
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
                "prompt_tokens": 100 + index,
                "completion_tokens": 10 + index,
                "total_tokens": 110 + (index * 2),
            },
            "openai_api": {"latency_ms": 20 + index},
        }


class HighOverlapPoisonPillOpenAISelectorRepeat3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_poison_pill_tasks()[0]
        self.tasks = [self.task]
        self.config = SelectorConfig(model="example-openai-router", max_output_tokens=700)

    def _report(self, outputs: list[object]) -> dict[str, object]:
        return run_repeat_smoke(
            tasks=self.tasks,
            provider=SequencedSelectorProvider(outputs),
            config=self.config,
        )

    def test_default_cli_repeat_is_three(self) -> None:
        with patch.object(sys, "argv", ["run_high_overlap_poison_pill_openai_selector_repeat3.py"]):
            args = _parse_args()

        self.assertEqual(args.repeat, DEFAULT_REPEAT)
        self.assertEqual(args.repeat, 3)

    def test_cli_accepts_explicit_repeat_three(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_high_overlap_poison_pill_openai_selector_repeat3.py", "--repeat", "3"],
        ):
            args = _parse_args()

        self.assertEqual(args.repeat, 3)

    def test_cli_rejects_repeat_one_before_provider_work(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_high_overlap_poison_pill_openai_selector_repeat3.py", "--repeat", "1"],
        ):
            with patch(
                "runtime.run_high_overlap_poison_pill_openai_selector_repeat3.load_repo_env"
            ) as load_env:
                with patch(
                    "runtime.run_high_overlap_poison_pill_openai_selector_repeat3.OpenAIAPIProvider"
                ) as provider:
                    with self.assertRaises(SystemExit):
                        main()

        self.assertFalse(load_env.called)
        self.assertFalse(provider.called)

    def test_cli_rejects_repeat_four_before_provider_work(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_high_overlap_poison_pill_openai_selector_repeat3.py", "--repeat", "4"],
        ):
            with patch(
                "runtime.run_high_overlap_poison_pill_openai_selector_repeat3.load_repo_env"
            ) as load_env:
                with patch(
                    "runtime.run_high_overlap_poison_pill_openai_selector_repeat3.OpenAIAPIProvider"
                ) as provider:
                    with self.assertRaises(SystemExit):
                        main()

        self.assertFalse(load_env.called)
        self.assertFalse(provider.called)

    def test_all_three_runs_pass(self) -> None:
        report = self._report([["doc-orion-b42"], ["doc-orion-b42"], ["doc-orion-b42"]])
        summary = report["summary"]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["repeat"], 3)
        self.assertEqual(summary["run_count"], 3)
        self.assertEqual(summary["honest_selector_pass_count"], 3)
        self.assertEqual(summary["honest_selector_pass_rate"], 1.0)
        self.assertEqual(summary["fallback_count"], 0)
        self.assertEqual(summary["parse_failure_count"], 0)
        self.assertEqual(summary["poison_selection_count"], 0)
        self.assertEqual(summary["obsolete_selection_count"], 0)
        self.assertEqual(summary["partial_selection_count"], 0)
        self.assertEqual(summary["mixed_selection_count"], 0)
        self.assertEqual(summary["total_prompt_tokens"], 303)
        self.assertEqual(summary["total_completion_tokens"], 33)
        self.assertEqual(summary["total_tokens"], 336)
        self.assertEqual(summary["total_latency_ms"], 63)
        self.assertEqual([run["run_index"] for run in report["runs"]], [1, 2, 3])
        self.assertTrue(all(run["honest_selector_pass"] for run in report["runs"]))

    def test_one_run_selects_poison_and_aggregate_counts_it(self) -> None:
        report = self._report([["doc-orion-b42"], ["doc-orion-d31"], ["doc-orion-b42"]])
        summary = report["summary"]

        self.assertEqual(summary["honest_selector_pass_count"], 2)
        self.assertEqual(summary["poison_selection_count"], 1)
        self.assertEqual(summary["obsolete_selection_count"], 0)
        self.assertEqual(summary["partial_selection_count"], 0)
        self.assertFalse(report["runs"][1]["poison_pill_sources_omitted"])

    def test_one_run_selects_obsolete_and_aggregate_counts_it(self) -> None:
        report = self._report([["doc-orion-b42"], ["doc-orion-a17"], ["doc-orion-b42"]])
        summary = report["summary"]

        self.assertEqual(summary["honest_selector_pass_count"], 2)
        self.assertEqual(summary["obsolete_selection_count"], 1)
        self.assertEqual(summary["poison_selection_count"], 0)
        self.assertEqual(summary["partial_selection_count"], 0)
        self.assertFalse(report["runs"][1]["obsolete_sources_omitted"])

    def test_one_run_selects_partial_and_aggregate_counts_it(self) -> None:
        report = self._report([["doc-orion-b42"], ["doc-orion-c09"], ["doc-orion-b42"]])
        summary = report["summary"]

        self.assertEqual(summary["honest_selector_pass_count"], 2)
        self.assertEqual(summary["partial_selection_count"], 1)
        self.assertEqual(summary["poison_selection_count"], 0)
        self.assertEqual(summary["obsolete_selection_count"], 0)
        self.assertFalse(report["runs"][1]["partial_sources_omitted"])

    def test_one_run_returns_invalid_json_and_aggregate_counts_parse_failure(self) -> None:
        report = self._report([["doc-orion-b42"], "not json", ["doc-orion-b42"]])
        summary = report["summary"]

        self.assertEqual(summary["honest_selector_pass_count"], 2)
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["parse_failure_count"], 1)
        self.assertFalse(report["runs"][1]["parse_success"])
        self.assertTrue(report["runs"][1]["fallback_used"])

    def test_one_run_triggers_provider_fallback_and_aggregate_counts_it(self) -> None:
        report = self._report(
            [["doc-orion-b42"], RuntimeError("selector unavailable"), ["doc-orion-b42"]]
        )
        summary = report["summary"]

        self.assertEqual(summary["honest_selector_pass_count"], 2)
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["parse_failure_count"], 1)
        self.assertFalse(report["runs"][1]["parse_success"])
        self.assertTrue(report["runs"][1]["fallback_used"])
        self.assertIn("selector unavailable", report["runs"][1]["selector_error"])

    def test_mixed_authoritative_plus_poison_selection_is_counted(self) -> None:
        report = self._report(
            [["doc-orion-b42"], ["doc-orion-b42", "doc-orion-d31"], ["doc-orion-b42"]]
        )
        summary = report["summary"]

        self.assertEqual(summary["honest_selector_pass_count"], 2)
        self.assertEqual(summary["poison_selection_count"], 1)
        self.assertEqual(summary["mixed_selection_count"], 1)
        self.assertTrue(report["runs"][1]["authoritative_source_selected"])
        self.assertFalse(report["runs"][1]["exact_authoritative_selection"])

    def test_summarize_repeat_runs_handles_missing_usage_and_latency(self) -> None:
        runs = [
            {
                "honest_selector_pass": False,
                "fallback_used": True,
                "parse_success": False,
                "selected_poison_pill_source_ids": [],
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

        self.assertEqual(summary["run_count"], 1)
        self.assertEqual(summary["fallback_count"], 1)
        self.assertIsNone(summary["total_tokens"])
        self.assertIsNone(summary["total_latency_ms"])

    def test_markdown_report_is_cautious_repeat3_observation(self) -> None:
        report = self._report([["doc-orion-b42"], ["doc-orion-b42"], ["doc-orion-b42"]])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "repeat3.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("repeat-3 smoke observation", markdown)
        self.assertIn("selector-only", markdown)
        self.assertIn("does not run an executor", markdown)
        self.assertIn("does not provide statistical proof", markdown)
        self.assertIn("Honest selector pass count: 3/3", markdown)

    def test_missing_api_key_writes_structured_skipped_reports_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "repeat3.json"
            md_path = Path(temp_dir) / "repeat3.md"
            provider_chat = (
                "runtime.run_high_overlap_poison_pill_openai_selector_repeat3."
                "OpenAIAPIProvider.chat"
            )
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_high_overlap_poison_pill_openai_selector_repeat3.py",
                        "--json",
                        str(json_path),
                        "--md",
                        str(md_path),
                    ],
                ):
                    with patch("runtime.run_high_overlap_poison_pill_openai_selector_repeat3.load_repo_env"):
                        with patch(provider_chat) as chat:
                            main()

            self.assertFalse(chat.called)
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")
            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["skip_reason"], "missing OPENAI_API_KEY")
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
        self.assertFalse(report["honest_selector_pass"])
        self.assertIn("Status: skipped", markdown)
        self.assertIn("No provider/API call was made.", markdown)


if __name__ == "__main__":
    unittest.main()
