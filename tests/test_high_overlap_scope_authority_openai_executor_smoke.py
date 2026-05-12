"""Tests for the scope-authority OpenAI executor smoke runner."""

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
from runtime.run_high_overlap_scope_authority_benchmark import (
    get_high_overlap_scope_authority_tasks,
)
from runtime.run_high_overlap_scope_authority_openai_executor_smoke import (
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
            "usage": {"prompt_tokens": 410, "completion_tokens": 61, "total_tokens": 471},
            "openai_api": {"latency_ms": 203},
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


class HighOverlapScopeAuthorityOpenAIExecutorSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = get_high_overlap_scope_authority_tasks()[0]
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
        self.assertTrue(run["selected_context_only"])
        self.assertTrue(run["selected_context_excludes_scope_mismatch_sources"])
        self.assertTrue(run["selected_context_excludes_partial_sources"])
        self.assertTrue(run["output_validation_success"])
        self.assertTrue(run["honest_executor_pass"])
        self.assertEqual(run["copied_scope_mismatch_value_count"], 0)
        self.assertEqual(run["copied_partial_value_count"], 0)
        self.assertTrue(run["field_extraction_passed"])
        self.assertTrue(run["evidence_reference_passed"])
        self.assertTrue(run["contamination_free"])
        self.assertEqual(run["failure_flags"], [])
        self.assertEqual(run["usage"]["total_tokens"], 471)

    def test_executor_prompt_receives_only_authoritative_selected_context(self) -> None:
        provider = FakeExecutorProvider(output=self._valid_output())
        run = execute_executor_smoke(task=self.task, provider=provider, config=self.config)
        prompt = provider.calls[0]["messages"][0]["content"]

        self.assertTrue(run["selected_context_excludes_excluded_sources"])
        self.assertIn("aurelia-r19", prompt)
        self.assertIn("AURELIA_OWNER_NORTH", prompt)
        self.assertIn("Aurelia Guard 2028.02-NR", prompt)
        for forbidden in (
            "aurelia-q44",
            "aurelia-s08",
            "aurelia-n27",
            "AURELIA_OWNER_SOUTH",
            "AURELIA_OWNER_CATALOG",
            "Aurelia Guard 2028.02-SR",
            "Aurelia Guard 2028.02-CAT",
            "operator visibility",
        ):
            self.assertNotIn(forbidden, prompt)
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
        for source_id in ("aurelia-q44", "aurelia-s08", "aurelia-n27"):
            self.assertNotIn(source_id, prompt)

    def test_executor_fails_if_it_copies_scope_mismatch_values(self) -> None:
        output = self._valid_output()
        output["owner_id"] = "AURELIA_OWNER_SOUTH"
        output["threshold"] = "risk score <= 0.29 over 10h"
        output["required_action"] = "keep north-lane dual approval advisory"

        run = self._run_with_output(output)

        self.assertFalse(run["output_validation_success"])
        self.assertEqual(run["copied_scope_mismatch_value_count"], 3)
        self.assertFalse(run["contamination_free"])
        self.assertIn("contamination_indicator", run["failure_flags"])
        self.assertFalse(run["honest_executor_pass"])

    def test_executor_fails_if_it_cites_excluded_source(self) -> None:
        output = self._valid_output()
        output["evidence_source_ids"] = ["aurelia-q44"]

        run = self._run_with_output(output)

        self.assertFalse(run["output_validation_success"])
        self.assertTrue(run["excluded_source_citation"])
        self.assertTrue(run["scope_mismatch_source_citation"])
        self.assertFalse(run["evidence_reference_passed"])
        self.assertFalse(run["contamination_free"])
        self.assertIn("evidence_reference_failure", run["failure_flags"])
        self.assertIn("contamination_indicator", run["failure_flags"])
        self.assertFalse(run["honest_executor_pass"])

    def test_clean_exact_field_miss_is_field_extraction_failure_not_contamination(self) -> None:
        output = self._valid_output()
        output["active_protocol"] = "Aurelia Guard 2028.02"

        run = self._run_with_output(output)

        self.assertFalse(run["output_validation_success"])
        self.assertEqual(run["failed_field_names"], ["active_protocol"])
        self.assertIn("field_extraction_failure", run["failure_flags"])
        self.assertTrue(run["contamination_free"])
        self.assertEqual(run["copied_excluded_value_count"], 0)
        self.assertEqual(run["excluded_source_citation_count"], 0)
        self.assertNotIn("contamination_indicator", run["failure_flags"])

    def test_invalid_json_and_provider_error_fail_honestly(self) -> None:
        parse_run = execute_executor_smoke(
            task=self.task,
            provider=FakeExecutorProvider(raw_output="not json"),
            config=self.config,
        )
        provider_run = execute_executor_smoke(
            task=self.task,
            provider=RaisingExecutorProvider(),
            config=self.config,
        )

        self.assertFalse(parse_run["executor_output_parse_success"])
        self.assertIn("parse_failure", parse_run["failure_flags"])
        self.assertFalse(parse_run["honest_executor_pass"])
        self.assertTrue(provider_run["executor_provider_error"])
        self.assertIn("provider_error", provider_run["failure_flags"])
        self.assertIn("parse_failure", provider_run["failure_flags"])
        self.assertFalse(provider_run["honest_executor_pass"])

    def test_fallback_and_repair_cannot_count_as_success(self) -> None:
        selection = dict(fixture_source_selection(self.task))
        selection["selector_success"] = False
        selection["selector_used_fallback"] = True
        run = execute_executor_smoke(
            task=self.task,
            provider=FakeExecutorProvider(output=self._valid_output()),
            config=self.config,
            selection=selection,
        )
        selection_validation = validate_selection(self.task, fixture_source_selection(self.task))
        selected_context = compose_context(self.task, (self.task.authoritative_source_id,))
        context_check = validate_selected_context_only(
            self.task,
            selected_context,
            [self.task.authoritative_source_id],
        )

        self.assertTrue(run["output_validation_success"])
        self.assertIn("fallback_used", run["failure_flags"])
        self.assertFalse(run["honest_executor_pass"])
        self.assertFalse(
            evaluate_honest_executor_pass(
                selection=fixture_source_selection(self.task),
                selection_validation=selection_validation,
                context_check=context_check,
                provider_error_occurred=False,
                parse_success=True,
                output_validation=validate_output(self.task, self.task.expected_answer),
                fallback_used=False,
                repair_used=True,
            )
        )

    def test_run_smoke_and_markdown_are_cautious(self) -> None:
        report = run_smoke(
            tasks=[self.task],
            provider=FakeExecutorProvider(output=self._valid_output()),
            config=self.config,
        )

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["executor_scope"], "selected_context_only")
        self.assertFalse(report["metadata"]["full_context_contamination_tested"])
        self.assertEqual(report["summary"]["honest_executor_pass_count"], 1)
        self.assertEqual(report["summary"]["copied_scope_mismatch_value_count"], 0)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "executor_smoke.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("OpenAI executor smoke test", markdown)
        self.assertIn("selected context only", markdown)
        self.assertIn("No full-context comparison is tested here", markdown)
        self.assertIn("not statistical proof", markdown)
        self.assertIn("Executor failure is a valid observation", markdown)
        self.assertNotIn("proven robust", markdown)
        self.assertNotIn("safe in general", markdown)
        self.assertNotIn("statistically validated", markdown)

    def test_default_cli_parse_does_not_call_openai(self) -> None:
        with patch.object(sys, "argv", ["run_high_overlap_scope_authority_openai_executor_smoke.py"]):
            args = _parse_args()

        self.assertIsNone(args.model)
        self.assertEqual(args.max_output_tokens, DEFAULT_MAX_OUTPUT_TOKENS)

    def test_main_skips_cleanly_without_openai_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "executor_smoke.json"
            md_path = Path(temp_dir) / "executor_smoke.md"
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_high_overlap_scope_authority_openai_executor_smoke.py",
                        "--json",
                        str(json_path),
                        "--md",
                        str(md_path),
                    ],
                ):
                    with patch(
                        "runtime.high_overlap_openai_executor_smoke_helpers.load_repo_env"
                    ):
                        with patch(
                            "runtime.high_overlap_openai_executor_smoke_helpers.OpenAIAPIProvider.chat"
                        ) as chat:
                            main()

            self.assertFalse(chat.called)
            report = json.loads(json_path.read_text(encoding="utf-8"))
            markdown = md_path.read_text(encoding="utf-8")
            self.assertEqual(report["status"], "skipped")
            self.assertEqual(report["benchmark"], "high_overlap_scope_authority")
            self.assertEqual(report["executor_scope"], "selected_context_only")
            self.assertEqual(report["runs"], [])
            self.assertIn("Status: skipped", markdown)
            self.assertIn("No provider/API call was made.", markdown)

    def test_skipped_report_helpers_are_provider_free(self) -> None:
        report = build_skipped_report(
            model="example-openai-executor",
            timeout=12.5,
            reason="OpenAI API key is not configured.",
        )

        self.assertEqual(report["status"], "skipped")
        self.assertFalse(report["honest_executor_pass"])
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "skipped.md"
            write_skipped_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")
        self.assertIn("Status: skipped", markdown)
        self.assertIn("No provider/API call was made.", markdown)

    def test_parse_executor_output_rejects_non_object_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            parse_executor_output('["not", "an", "object"]')


if __name__ == "__main__":
    unittest.main()
