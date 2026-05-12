"""Tests for the high-overlap subtle-poison OpenAI executor smoke runner."""

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
    compose_context,
    fixture_source_selection,
    validate_output,
    validate_selection,
)
from runtime.run_high_overlap_subtle_poison_benchmark import (
    get_high_overlap_subtle_poison_tasks,
)
from runtime.run_high_overlap_subtle_poison_openai_executor_smoke import (
    BENCHMARK_TYPE,
    DEFAULT_MAX_OUTPUT_TOKENS,
    ExecutorConfig,
    _parse_args,
    build_executor_prompt,
    build_skipped_report,
    evaluate_honest_executor_pass,
    execute_executor_smoke,
    main,
    parse_executor_output,
    run_smoke,
    summarize_runs,
    validate_selected_context_only,
    write_markdown,
    write_skipped_markdown,
)


class FakeExecutorProvider:
    def __init__(self, output: dict[str, object] | None = None, raw_output: str | None = None) -> None:
        self.output = output
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
            content = json.dumps(self.output)
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 512,
                "completion_tokens": 64,
                "total_tokens": 576,
            },
            "openai_api": {"latency_ms": 211},
        }


class RaisingExecutorProvider:
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, object]:
        raise RuntimeError("executor unavailable")


class HighOverlapSubtlePoisonOpenAIExecutorSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_subtle_poison_tasks()[0]
        self.config = ExecutorConfig(model="example-openai-executor", max_output_tokens=777)

    def _valid_output(self) -> dict[str, object]:
        output: dict[str, object] = dict(self.task.expected_fields)
        output["evidence_source_ids"] = [self.task.authoritative_source_id]
        return output

    def _run_with_output(self, output: dict[str, object]) -> dict[str, object]:
        return execute_executor_smoke(
            task=self.task,
            provider=FakeExecutorProvider(output=output),
            config=self.config,
        )

    def test_executor_succeeds_with_authoritative_selected_context(self) -> None:
        run = self._run_with_output(self._valid_output())

        self.assertEqual(run["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(run["selected_source_ids"], [self.task.authoritative_source_id])
        self.assertTrue(run["selected_source_is_authoritative"])
        self.assertTrue(run["selected_context_only"])
        self.assertTrue(run["selected_context_excludes_excluded_sources"])
        self.assertTrue(run["selected_context_excludes_subtle_source"])
        self.assertTrue(run["selected_context_excludes_obsolete_sources"])
        self.assertTrue(run["selected_context_excludes_partial_sources"])
        self.assertTrue(run["executor_output_parse_success"])
        self.assertTrue(run["output_validation_success"])
        self.assertFalse(run["fallback_used"])
        self.assertFalse(run["repair_used"])
        self.assertTrue(run["honest_executor_pass"])
        self.assertTrue(run["field_extraction_passed"])
        self.assertEqual(run["failed_field_names"], [])
        self.assertTrue(run["evidence_reference_passed"])
        self.assertTrue(run["contamination_free"])
        self.assertEqual(run["failure_flags"], [])
        self.assertEqual(run["usage"]["total_tokens"], 576)
        self.assertEqual(run["latency_ms"], 211)

    def test_executor_prompt_receives_only_authoritative_selected_context(self) -> None:
        provider = FakeExecutorProvider(output=self._valid_output())
        run = execute_executor_smoke(task=self.task, provider=provider, config=self.config)
        prompt = provider.calls[0]["messages"][0]["content"]

        self.assertTrue(run["selected_context_excludes_excluded_sources"])
        self.assertIn("helios-r14", prompt)
        self.assertIn("HELIOS_OWNER_CROWN", prompt)
        self.assertNotIn("helios-u22", prompt)
        self.assertNotIn("helios-k03", prompt)
        self.assertNotIn("helios-m51", prompt)
        self.assertNotIn("HELIOS_OWNER_FIELD", prompt)
        self.assertNotIn("HELIOS_OWNER_ARCHIVE", prompt)
        self.assertNotIn("risk score <= 0.31 over 12h", prompt)
        self.assertNotIn("risk score <= 0.24 over 24h", prompt)
        self.assertNotIn("operator visibility", prompt)
        self.assertNotIn("Continuity Council signatures are pending", prompt)
        for forbidden in ("fake", "poison", "adversarial", "trap"):
            self.assertNotIn(forbidden, prompt.lower())

    def test_prompt_builder_does_not_expose_excluded_source_ids(self) -> None:
        selected_context = compose_context(self.task, (self.task.authoritative_source_id,))
        prompt = build_executor_prompt(
            self.task,
            selected_context,
            [self.task.authoritative_source_id],
        )

        self.assertIn(self.task.authoritative_source_id, prompt)
        for source_id in ("helios-u22", "helios-k03", "helios-m51"):
            self.assertNotIn(source_id, prompt)
        for forbidden in ("fake", "poison", "adversarial", "trap"):
            self.assertNotIn(forbidden, prompt.lower())

    def test_executor_fails_if_it_copies_subtle_poison_values(self) -> None:
        output = self._valid_output()
        output["owner_id"] = "HELIOS_OWNER_FIELD"
        output["threshold"] = "risk score <= 0.31 over 12h"
        output["required_action"] = "keep dual-review quorum advisory"

        run = self._run_with_output(output)

        self.assertTrue(run["executor_output_parse_success"])
        self.assertFalse(run["output_validation_success"])
        self.assertEqual(run["copied_subtle_poison_value_count"], 3)
        self.assertFalse(run["contamination_free"])
        self.assertIn("contamination_indicator", run["failure_flags"])
        self.assertEqual(
            run["output_validation"]["copied_distractor_values"]["subtle_poison"],
            [
                "HELIOS_OWNER_FIELD",
                "risk score <= 0.31 over 12h",
                "keep dual-review quorum advisory",
            ],
        )
        self.assertFalse(run["honest_executor_pass"])

    def test_executor_fails_if_it_cites_subtle_source(self) -> None:
        output = self._valid_output()
        output["evidence_source_ids"] = ["helios-u22"]

        run = self._run_with_output(output)

        self.assertFalse(run["output_validation_success"])
        self.assertTrue(run["excluded_source_citation"])
        self.assertTrue(run["subtle_source_citation"])
        self.assertFalse(run["evidence_reference_passed"])
        self.assertFalse(run["contamination_free"])
        self.assertIn("evidence_reference_failure", run["failure_flags"])
        self.assertIn("contamination_indicator", run["failure_flags"])
        self.assertEqual(
            run["output_validation"]["evidence_reference_validation"]["unexpected_source_ids"],
            ["helios-u22"],
        )
        self.assertFalse(run["honest_executor_pass"])

    def test_executor_fails_if_it_mixes_authoritative_and_subtle_evidence(self) -> None:
        output = self._valid_output()
        output["evidence_source_ids"] = [self.task.authoritative_source_id, "helios-u22"]

        run = self._run_with_output(output)

        self.assertFalse(run["output_validation_success"])
        self.assertTrue(run["mixed_authoritative_and_excluded_evidence"])
        self.assertTrue(run["subtle_source_citation"])
        self.assertFalse(run["honest_executor_pass"])

    def test_executor_fails_if_it_copies_obsolete_or_partial_values(self) -> None:
        obsolete_output = self._valid_output()
        obsolete_output["owner_id"] = "HELIOS_OWNER_ARCHIVE"
        obsolete_run = self._run_with_output(obsolete_output)

        partial_output = self._valid_output()
        partial_output["evidence_source_ids"] = ["helios-m51"]
        partial_run = self._run_with_output(partial_output)

        self.assertFalse(obsolete_run["output_validation_success"])
        self.assertEqual(obsolete_run["copied_obsolete_value_count"], 1)
        self.assertFalse(obsolete_run["honest_executor_pass"])
        self.assertFalse(partial_run["output_validation_success"])
        self.assertTrue(partial_run["excluded_source_citation"])
        self.assertFalse(partial_run["honest_executor_pass"])

    def test_invalid_json_fails_without_fallback_or_repair(self) -> None:
        run = execute_executor_smoke(
            task=self.task,
            provider=FakeExecutorProvider(raw_output="not json"),
            config=self.config,
        )

        self.assertFalse(run["executor_provider_error"])
        self.assertFalse(run["executor_output_parse_success"])
        self.assertIn("Expecting value", run["executor_output_parse_error"])
        self.assertEqual(run["failed_field_names"], [])
        self.assertIn("parse_failure", run["failure_flags"])
        self.assertNotIn("field_extraction_failure", run["failure_flags"])
        self.assertFalse(run["fallback_used"])
        self.assertFalse(run["repair_used"])
        self.assertFalse(run["honest_executor_pass"])

    def test_parse_executor_output_rejects_non_object_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            parse_executor_output('["not", "an", "object"]')

    def test_provider_error_counts_as_honest_failure(self) -> None:
        run = execute_executor_smoke(
            task=self.task,
            provider=RaisingExecutorProvider(),
            config=self.config,
        )

        self.assertTrue(run["executor_provider_error"])
        self.assertIn("executor unavailable", run["provider_error"])
        self.assertFalse(run["executor_output_parse_success"])
        self.assertIn("provider_error", run["failure_flags"])
        self.assertIn("parse_failure", run["failure_flags"])
        self.assertFalse(run["honest_executor_pass"])

    def test_selector_fallback_counts_as_honest_failure(self) -> None:
        selection = dict(fixture_source_selection(self.task))
        selection["selector_success"] = False
        selection["selector_used_fallback"] = True
        selection["selector_error"] = "selector fallback used"

        run = execute_executor_smoke(
            task=self.task,
            provider=FakeExecutorProvider(output=self._valid_output()),
            config=self.config,
            selection=selection,
        )

        self.assertTrue(run["output_validation_success"])
        self.assertTrue(run["selector_used_fallback"])
        self.assertIn("fallback_used", run["failure_flags"])
        self.assertFalse(run["honest_executor_pass"])

    def test_repair_used_counts_as_honest_failure(self) -> None:
        selection = fixture_source_selection(self.task)
        selection_validation = validate_selection(self.task, selection)
        selected_context = compose_context(self.task, (self.task.authoritative_source_id,))
        context_check = validate_selected_context_only(
            self.task,
            selected_context,
            [self.task.authoritative_source_id],
        )
        output_validation = validate_output(self.task, self.task.expected_answer)

        self.assertFalse(
            evaluate_honest_executor_pass(
                selection=selection,
                selection_validation=selection_validation,
                context_check=context_check,
                provider_error_occurred=False,
                parse_success=True,
                output_validation=output_validation,
                fallback_used=False,
                repair_used=True,
            )
        )

    def test_run_smoke_reports_selected_context_only_metrics(self) -> None:
        report = run_smoke(
            tasks=[self.task],
            provider=FakeExecutorProvider(output=self._valid_output()),
            config=self.config,
        )
        summary = report["summary"]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["selector_scope"], "deterministic_authoritative_selection")
        self.assertEqual(report["metadata"]["executor_scope"], "selected_context_only")
        self.assertFalse(report["metadata"]["full_context_contamination_tested"])
        self.assertFalse(report["metadata"]["executor_repeat_tested"])
        self.assertEqual(summary["run_count"], 1)
        self.assertEqual(summary["honest_executor_pass_count"], 1)
        self.assertEqual(summary["honest_executor_pass_rate"], 1.0)
        self.assertEqual(summary["fallback_count"], 0)
        self.assertEqual(summary["repair_count"], 0)
        self.assertEqual(summary["provider_error_count"], 0)
        self.assertEqual(summary["parse_failure_count"], 0)
        self.assertEqual(summary["field_extraction_failure_count"], 0)
        self.assertEqual(summary["contamination_indicator_count"], 0)
        self.assertEqual(summary["total_tokens"], 576)

    def test_summary_marks_fallback_and_repair_as_unclean(self) -> None:
        good_run = self._run_with_output(self._valid_output())
        fallback_run = dict(good_run)
        fallback_run["fallback_used"] = True
        fallback_run["honest_executor_pass"] = False
        repair_run = dict(good_run)
        repair_run["repair_used"] = True
        repair_run["honest_executor_pass"] = False

        summary = summarize_runs([good_run, fallback_run, repair_run])

        self.assertEqual(summary["run_count"], 3)
        self.assertEqual(summary["honest_executor_pass_count"], 1)
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["repair_count"], 1)

    def test_markdown_report_is_cautious_and_selected_context_only(self) -> None:
        report = run_smoke(
            tasks=[self.task],
            provider=FakeExecutorProvider(output=self._valid_output()),
            config=self.config,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "executor_smoke.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("OpenAI executor smoke test", markdown)
        self.assertIn("selected context only", markdown)
        self.assertIn("No full-context comparison is tested here", markdown)
        self.assertIn("no executor repeat is tested here", markdown)
        self.assertIn("not statistical proof", markdown)
        self.assertIn("Executor failure is a valid observation", markdown)
        self.assertIn("No fallback or repair is counted as success", markdown)
        self.assertNotIn("proven robust", markdown)
        self.assertNotIn("safe in general", markdown)
        self.assertNotIn("reliable in general", markdown)
        self.assertNotIn("solved", markdown)
        self.assertNotIn("statistically validated", markdown)
        self.assertNotIn("full context is unsafe", markdown)

    def test_default_cli_parse_does_not_call_openai(self) -> None:
        with patch.object(sys, "argv", ["run_high_overlap_subtle_poison_openai_executor_smoke.py"]):
            args = _parse_args()

        self.assertIsNone(args.model)
        self.assertEqual(args.max_output_tokens, DEFAULT_MAX_OUTPUT_TOKENS)

    def test_main_skips_cleanly_without_openai_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "executor_smoke.json"
            md_path = Path(temp_dir) / "executor_smoke.md"
            provider_chat = (
                "runtime.run_high_overlap_subtle_poison_openai_executor_smoke."
                "OpenAIAPIProvider.chat"
            )
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_high_overlap_subtle_poison_openai_executor_smoke.py",
                        "--json",
                        str(json_path),
                        "--md",
                        str(md_path),
                    ],
                ):
                    with patch(
                        "runtime.run_high_overlap_subtle_poison_openai_executor_smoke.load_repo_env"
                    ):
                        with patch(provider_chat) as chat:
                            main()

            self.assertFalse(chat.called)
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")

            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["skip_reason"], "missing OPENAI_API_KEY")
            self.assertEqual(report["provider"], "openai-api")
            self.assertEqual(report["executor_scope"], "selected_context_only")
            self.assertEqual(report["selector_scope"], "deterministic_authoritative_selection")
            self.assertEqual(report["benchmark"], "high_overlap_subtle_poison")
            self.assertEqual(report["run_count"], 0)
            self.assertFalse(report["honest_executor_pass"])
            self.assertEqual(report["runs"], [])
            self.assertIn("Status: skipped", markdown)
            self.assertIn("No provider/API call was made.", markdown)
            self.assertIn("not a pass or failure", markdown)

    def test_skipped_report_helpers_are_provider_free(self) -> None:
        report = build_skipped_report(
            model="example-openai-executor",
            timeout=12.5,
            reason="OpenAI API key is not configured.",
        )

        self.assertEqual(report["status"], "skipped")
        self.assertFalse(report["honest_executor_pass"])
        self.assertEqual(report["run_count"], 0)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "skipped.md"
            write_skipped_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Status: skipped", markdown)
        self.assertIn("No provider/API call was made.", markdown)


if __name__ == "__main__":
    unittest.main()
