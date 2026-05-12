"""Tests for the high-overlap policy-exception OpenAI selector smoke runner."""

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

from runtime.run_high_overlap_policy_exception_benchmark import (
    get_high_overlap_policy_exception_tasks,
)
from runtime.run_high_overlap_policy_exception_openai_selector_smoke import (
    BENCHMARK_TYPE,
    SelectorConfig,
    build_prompt_source_aliases,
    build_selector_prompt,
    build_skipped_report,
    evaluate_honest_selector_pass,
    execute_selector_smoke,
    main,
    parse_selector_output,
    run_smoke,
    validate_selector_selection,
    write_markdown,
    write_skipped_markdown,
)


class FakeSelectorProvider:
    def __init__(self, selected: list[str] | None = None, raw_output: str | None = None) -> None:
        self.selected = selected or []
        self.raw_output = raw_output
        self.calls: list[dict[str, object]] = []

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, object]:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system_instruction": system_instruction,
            }
        )
        content = self.raw_output
        if content is None:
            content = json.dumps(
                {
                    "selected_source_ids": self.selected,
                    "selection_rationale": {
                        source_id: "selected by final authority evidence"
                        for source_id in self.selected
                    },
                }
            )
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 432,
                "completion_tokens": 56,
                "total_tokens": 488,
            },
            "openai_api": {"latency_ms": 145},
        }


class RaisingSelectorProvider:
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, object]:
        raise RuntimeError("selector unavailable")


class HighOverlapPolicyExceptionOpenAISelectorSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_policy_exception_tasks()[0]
        self.alias_map = build_prompt_source_aliases(self.task)
        self.config = SelectorConfig(model="example-openai-router", max_output_tokens=777)

    def _alias_for_source(self, source_id: str) -> str:
        for alias, actual_source_id in self.alias_map.items():
            if actual_source_id == source_id:
                return alias
        raise AssertionError(f"No alias for source {source_id}")

    def _run_with_selection(self, selected: list[str]) -> dict[str, object]:
        return execute_selector_smoke(
            task=self.task,
            provider=FakeSelectorProvider(selected=selected),
            config=self.config,
        )

    def test_prompt_uses_neutral_candidate_handles_without_source_id_leakage(self) -> None:
        prompt = build_selector_prompt(self.task, self.alias_map)

        self.assertIn("candidate handles only", prompt)
        self.assertIn("current authority evidence", prompt)
        self.assertIn("current authority evidence", prompt)
        self.assertIn("requested exception case", prompt)
        self.assertIn("candidate-1", prompt)
        self.assertNotIn(self.task.authoritative_source_id, prompt)
        self.assertNotIn("cassini-g04", prompt)
        self.assertNotIn("cassini-g04", prompt)
        self.assertNotIn("cassini-p58", prompt)
        for forbidden in ("fake", "poison", "invalid", "adversarial", "trap", "distractor"):
            self.assertNotIn(forbidden, prompt.lower())

    def test_parse_selector_output_accepts_strict_json(self) -> None:
        parsed = parse_selector_output(
            json.dumps(
                {
                    "selected_source_ids": ["candidate-1"],
                    "selection_rationale": {"candidate-1": "complete final authority evidence"},
                }
            )
        )

        self.assertEqual(parsed["selected_source_ids"], ["candidate-1"])
        self.assertEqual(
            parsed["selection_rationale"],
            {"candidate-1": "complete final authority evidence"},
        )

    def test_parse_selector_output_rejects_invalid_json(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            parse_selector_output("not json")

    def test_parse_selector_output_rejects_duplicate_candidate(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicates"):
            parse_selector_output(
                json.dumps(
                    {
                        "selected_source_ids": ["candidate-1", "candidate-1"],
                        "selection_rationale": {"candidate-1": "duplicate"},
                    }
                )
            )

    def test_correct_authoritative_selection_passes(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        run = self._run_with_selection([authoritative_alias])

        self.assertTrue(run["parse_success"])
        self.assertFalse(run["fallback_used"])
        self.assertFalse(run["repair_used"])
        self.assertEqual(run["repair_status"], "not_supported")
        self.assertTrue(run["exact_authoritative_selection"])
        self.assertTrue(run["honest_selector_pass"])
        self.assertEqual(run["selected_source_ids"], [self.task.authoritative_source_id])
        self.assertEqual(run["selected_prompt_source_ids"], [authoritative_alias])
        self.assertEqual(run["usage"]["total_tokens"], 488)
        self.assertEqual(run["latency_ms"], 145)

    def test_general_policy_selection_fails(self) -> None:
        general_alias = self._alias_for_source("cassini-g04")
        run = self._run_with_selection([general_alias])

        self.assertFalse(run["exact_authoritative_selection"])
        self.assertFalse(run["general_policy_sources_omitted"])
        self.assertEqual(run["selected_general_policy_source_ids"], ["cassini-g04"])
        self.assertFalse(run["honest_selector_pass"])

    def test_general_policy_or_partial_selection_fails(self) -> None:
        general_run = self._run_with_selection([self._alias_for_source("cassini-g04")])
        partial_run = self._run_with_selection([self._alias_for_source("cassini-p58")])

        self.assertFalse(general_run["general_policy_sources_omitted"])
        self.assertEqual(general_run["selected_general_policy_source_ids"], ["cassini-g04"])
        self.assertFalse(general_run["honest_selector_pass"])
        self.assertFalse(partial_run["partial_sources_omitted"])
        self.assertEqual(partial_run["selected_partial_source_ids"], ["cassini-p58"])
        self.assertFalse(partial_run["honest_selector_pass"])

    def test_provider_error_counts_as_honest_failure_without_fallback(self) -> None:
        run = execute_selector_smoke(
            task=self.task,
            provider=RaisingSelectorProvider(),
            config=self.config,
        )

        self.assertFalse(run["parse_success"])
        self.assertTrue(run["selector_provider_error"])
        self.assertIn("selector unavailable", run["selector_error"])
        self.assertFalse(run["fallback_used"])
        self.assertFalse(run["honest_selector_pass"])

    def test_invalid_json_counts_as_honest_failure_without_fallback(self) -> None:
        run = execute_selector_smoke(
            task=self.task,
            provider=FakeSelectorProvider(raw_output="not json"),
            config=self.config,
        )

        self.assertFalse(run["parse_success"])
        self.assertFalse(run["selector_provider_error"])
        self.assertFalse(run["fallback_used"])
        self.assertIn("Expecting value", run["parse_error"])
        self.assertFalse(run["honest_selector_pass"])

    def test_unknown_prompt_source_id_counts_as_honest_failure(self) -> None:
        run = self._run_with_selection(["candidate-99"])

        self.assertTrue(run["parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertEqual(run["unknown_selected_source_ids"], ["candidate-99"])
        self.assertFalse(run["honest_selector_pass"])

    def test_fallback_or_repair_used_counts_as_honest_failure(self) -> None:
        validation = validate_selector_selection(
            task=self.task,
            selected_source_ids=[self.task.authoritative_source_id],
            unknown_prompt_source_ids=[],
            selected_prompt_source_ids=[self._alias_for_source(self.task.authoritative_source_id)],
        )

        self.assertFalse(
            evaluate_honest_selector_pass(
                parse_success=True,
                provider_error=False,
                validation=validation,
                fallback_used=True,
                repair_used=False,
            )
        )
        self.assertFalse(
            evaluate_honest_selector_pass(
                parse_success=True,
                provider_error=False,
                validation=validation,
                fallback_used=False,
                repair_used=True,
            )
        )

    def test_run_smoke_summary_is_selector_only(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = run_smoke(
            tasks=[self.task],
            provider=FakeSelectorProvider(selected=[authoritative_alias]),
            config=self.config,
        )

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["selector_scope"], "source_selection_only")
        self.assertEqual(report["metadata"]["executor"], "not_tested")
        self.assertEqual(report["metadata"]["comparison_scope"], "not_tested")
        self.assertEqual(report["metadata"]["repair_policy"], "no repair; repair is not supported")
        self.assertEqual(report["summary"]["honest_selector_pass_count"], 1)
        self.assertEqual(report["summary"]["fallback_count"], 0)
        self.assertEqual(report["summary"]["repair_count"], 0)

    def test_missing_api_key_writes_skipped_report_without_provider_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "selector.json"
            md_path = Path(temp_dir) / "selector.md"
            provider_chat = (
                "runtime.run_high_overlap_policy_exception_openai_selector_smoke."
                "OpenAIAPIProvider.chat"
            )
            with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_high_overlap_policy_exception_openai_selector_smoke.py",
                        "--json",
                        str(json_path),
                        "--md",
                        str(md_path),
                    ],
                ):
                    with patch(
                        "runtime.run_high_overlap_policy_exception_openai_selector_smoke.load_repo_env"
                    ):
                        with patch(provider_chat) as chat:
                            main()

            self.assertFalse(chat.called)
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")
            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["skip_reason"], "missing OPENAI_API_KEY")
            self.assertEqual(report["selector_scope"], "source_selection_only")
            self.assertEqual(report["executor"], "not_tested")
            self.assertEqual(report["runs"], [])
            self.assertIn("Status: skipped", markdown)
            self.assertIn("No provider/API call was made.", markdown)

    def test_skipped_report_helpers_are_provider_free(self) -> None:
        report = build_skipped_report(
            model="example-openai-router",
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

    def test_markdown_report_labels_cautious_selector_only_scope(self) -> None:
        authoritative_alias = self._alias_for_source(self.task.authoritative_source_id)
        report = run_smoke(
            tasks=[self.task],
            provider=FakeSelectorProvider(selected=[authoritative_alias]),
            config=self.config,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "selector.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("OpenAI selector smoke", markdown)
        self.assertIn("controlled policy-exception fixture", markdown)
        self.assertIn("exception-scope reasoning", markdown)
        self.assertIn("no executor was tested", markdown)
        self.assertIn("no selected-vs-full comparison was tested", markdown)
        self.assertIn("Selector failure is a valid observation", markdown)
        self.assertIn("not statistical proof", markdown)
        self.assertIn("not general robustness proof", markdown)
        self.assertNotIn("proven robust", markdown)
        self.assertNotIn("safe in general", markdown)
        self.assertNotIn("reliable in general", markdown)
        self.assertNotIn("solved", markdown)
        self.assertNotIn("statistically validated", markdown)


if __name__ == "__main__":
    unittest.main()
