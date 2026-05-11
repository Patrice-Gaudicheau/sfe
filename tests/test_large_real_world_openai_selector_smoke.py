"""Tests for the large real-world OpenAI selector smoke runner."""

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

from runtime.run_large_real_world_multi_zone_benchmark import get_large_real_world_tasks
from runtime.run_large_real_world_openai_selector_smoke import (
    BENCHMARK_TYPE,
    SelectorConfig,
    _parse_args,
    build_selector_prompt,
    execute_selector_smoke,
    parse_selector_output,
    run_smoke,
    validate_selection,
    write_markdown,
)


class FakeSelectorProvider:
    def __init__(self, selections: list[list[str]] | None = None, raw_outputs: list[str] | None = None) -> None:
        self.selections = selections or []
        self.raw_outputs = raw_outputs or []
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
        index = len(self.calls) - 1
        if self.raw_outputs:
            content = self.raw_outputs[index]
        else:
            selected = self.selections[index]
            content = json.dumps(
                {
                    "selected_source_ids": selected,
                    "selection_rationale": {
                        source_id: "required source" for source_id in selected
                    },
                }
            )
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 1000 + index,
                "completion_tokens": 100 + index,
                "total_tokens": 1100 + (index * 2),
            },
            "openai_api": {"latency_ms": 200 + index},
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


class LargeRealWorldOpenAISelectorSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_large_real_world_tasks()
        self.gateway_task = self.tasks[0]
        self.roadmap_task = self.tasks[1]
        self.config = SelectorConfig(model="example-router", max_output_tokens=777)

    def test_prompt_includes_all_candidate_source_ids_and_exactly_four_instruction(self) -> None:
        prompt = build_selector_prompt(self.gateway_task)

        self.assertIn(self.gateway_task.fixture_id, prompt)
        self.assertIn("Exactly 4 source IDs are required", prompt)
        self.assertIn("Select by sufficiency, not topical similarity", prompt)
        self.assertIn("Return strict JSON only", prompt)
        self.assertIn("Do not prefix IDs with DOC or SOURCE", prompt)
        for source in self.gateway_task.sources:
            self.assertIn(source.source_id, prompt)
            self.assertIn(source.role, prompt)
            self.assertIn(source.title, prompt)

    def test_parser_accepts_strict_valid_json(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        parsed = parse_selector_output(
            json.dumps(
                {
                    "selected_source_ids": selected,
                    "selection_rationale": {selected[0]: "needed"},
                }
            )
        )

        self.assertEqual(parsed["selected_source_ids"], selected)
        self.assertEqual(parsed["selection_rationale"][selected[0]], "needed")

    def test_parser_rejects_invalid_json(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            parse_selector_output("not json")

    def test_parser_rejects_missing_selected_source_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "selected_source_ids must be a list"):
            parse_selector_output(json.dumps({"selection_rationale": {}}))

    def test_parser_rejects_non_list_selected_source_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "selected_source_ids must be a list"):
            parse_selector_output(
                json.dumps(
                    {
                        "selected_source_ids": "doc-gateway-architecture-current",
                        "selection_rationale": {},
                    }
                )
            )

    def test_parser_rejects_duplicate_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not contain duplicates"):
            parse_selector_output(
                json.dumps(
                    {
                        "selected_source_ids": [
                            "doc-gateway-architecture-current",
                            "doc-gateway-architecture-current",
                        ],
                        "selection_rationale": {},
                    }
                )
            )

    def test_parser_handles_selection_rationale_safely(self) -> None:
        parsed = parse_selector_output(
            json.dumps(
                {
                    "selected_source_ids": ["doc-gateway-architecture-current"],
                    "selection_rationale": {123: 456},
                }
            )
        )

        self.assertEqual(parsed["selection_rationale"], {"123": "456"})

    def test_parser_rejects_non_object_selection_rationale(self) -> None:
        with self.assertRaisesRegex(ValueError, "selection_rationale must be an object"):
            parse_selector_output(
                json.dumps(
                    {
                        "selected_source_ids": ["doc-gateway-architecture-current"],
                        "selection_rationale": ["not", "object"],
                    }
                )
            )

    def test_validator_rejects_decorated_ids(self) -> None:
        selected = [
            "SOURCE doc-gateway-architecture-current (architecture_note)",
            "doc-gateway-routing-policy",
            "doc-gateway-exclusions-current",
            "doc-gateway-owner-decision-record",
        ]
        validation = validate_selection(self.gateway_task, selected)

        self.assertFalse(validation["exact_selector_match"])
        self.assertIn(
            "SOURCE doc-gateway-architecture-current (architecture_note)",
            validation["unknown_selected_source_ids"],
        )
        self.assertIn(
            "SOURCE doc-gateway-architecture-current (architecture_note)",
            validation["extra_selected_source_ids"],
        )

    def test_validator_rejects_duplicate_ids(self) -> None:
        selected = [
            "doc-gateway-architecture-current",
            "doc-gateway-architecture-current",
            "doc-gateway-routing-policy",
            "doc-gateway-exclusions-current",
        ]
        validation = validate_selection(self.gateway_task, selected)

        self.assertFalse(validation["exact_selector_match"])
        self.assertEqual(
            validation["duplicate_selected_source_ids"],
            ["doc-gateway-architecture-current"],
        )

    def test_validator_accepts_exact_required_selection(self) -> None:
        validation = validate_selection(self.gateway_task, list(self.gateway_task.required_source_ids))

        self.assertTrue(validation["exact_selector_match"])
        self.assertTrue(validation["required_source_complete"])
        self.assertTrue(validation["distractors_omitted"])
        self.assertEqual(validation["missing_required_source_ids"], [])
        self.assertEqual(validation["extra_selected_source_ids"], [])

    def test_validator_rejects_missing_required_source(self) -> None:
        selected = list(self.gateway_task.required_source_ids[:-1])
        validation = validate_selection(self.gateway_task, selected)

        self.assertFalse(validation["exact_selector_match"])
        self.assertFalse(validation["required_source_complete"])
        self.assertEqual(
            validation["missing_required_source_ids"],
            ["doc-gateway-owner-decision-record"],
        )

    def test_validator_rejects_distractor_selection(self) -> None:
        selected = list(self.gateway_task.required_source_ids[:-1]) + [
            "doc-gateway-glossary"
        ]
        validation = validate_selection(self.gateway_task, selected)

        self.assertFalse(validation["exact_selector_match"])
        self.assertFalse(validation["distractors_omitted"])
        self.assertEqual(validation["selected_distractor_source_ids"], ["doc-gateway-glossary"])
        self.assertEqual(validation["extra_selected_source_ids"], ["doc-gateway-glossary"])

    def test_mocked_exact_selection_passes_and_reports_metrics(self) -> None:
        provider = FakeSelectorProvider(
            selections=[list(task.required_source_ids) for task in self.tasks]
        )

        report = run_smoke(tasks=self.tasks, provider=provider, config=self.config)
        summary = report["summary"]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(summary["selector_exact_match_rate"], 1.0)
        self.assertEqual(summary["honest_selector_pass_rate"], 1.0)
        self.assertEqual(summary["fallback_count"], 0)
        self.assertEqual(summary["parse_failure_count"], 0)
        self.assertEqual(summary["total_prompt_tokens"], 2001)
        self.assertEqual(summary["total_completion_tokens"], 201)
        self.assertEqual(summary["total_tokens"], 2202)
        self.assertGreater(summary["average_token_reduction_percent"], 70.0)
        for run in report["runs"]:
            self.assertTrue(run["honest_selector_pass"])
            self.assertTrue(run["exact_selector_match"])
            self.assertGreater(run["token_reduction_percent"], 70.0)

    def test_fallback_disqualifies_honest_selector_pass(self) -> None:
        run = execute_selector_smoke(
            task=self.gateway_task,
            provider=RaisingSelectorProvider(),
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["parse_success"])
        self.assertFalse(run["honest_selector_pass"])
        self.assertFalse(run["exact_selector_match"])
        self.assertIn("selector unavailable", run["selector_error"])

    def test_report_metrics_show_failures_from_mocked_bad_selection(self) -> None:
        provider = FakeSelectorProvider(
            selections=[
                list(self.gateway_task.required_source_ids),
                list(self.roadmap_task.required_source_ids[:-1])
                + ["doc-token-savings-analysis-draft"],
            ]
        )

        report = run_smoke(tasks=self.tasks, provider=provider, config=self.config)
        summary = report["summary"]
        bad_run = report["runs"][1]

        self.assertEqual(summary["selector_exact_match_rate"], 0.5)
        self.assertEqual(summary["honest_selector_pass_rate"], 0.5)
        self.assertEqual(summary["required_source_completeness_rate"], 0.5)
        self.assertEqual(summary["distractor_rejection_rate"], 0.5)
        self.assertEqual(summary["fallback_count"], 0)
        self.assertEqual(summary["parse_failure_count"], 0)
        self.assertFalse(bad_run["honest_selector_pass"])
        self.assertIn("doc-honest-validation-policy", bad_run["missing_required_source_ids"])
        self.assertIn("doc-token-savings-analysis-draft", bad_run["selected_distractor_source_ids"])

    def test_parse_failure_is_reported_without_oracle_fallback_success(self) -> None:
        provider = FakeSelectorProvider(raw_outputs=["not json"])

        run = execute_selector_smoke(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["parse_success"])
        self.assertFalse(run["honest_selector_pass"])
        self.assertEqual(run["selected_source_ids"], [])

    def test_default_cli_parse_does_not_construct_provider_or_call_openai(self) -> None:
        with patch.object(sys, "argv", ["run_large_real_world_openai_selector_smoke.py"]):
            args = _parse_args()

        self.assertIsNone(args.model)
        self.assertEqual(args.max_output_tokens, 900)

    def test_markdown_report_states_selector_only_scope(self) -> None:
        provider = FakeSelectorProvider(
            selections=[list(task.required_source_ids) for task in self.tasks]
        )
        report = run_smoke(tasks=self.tasks, provider=provider, config=self.config)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "selector_smoke.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("OpenAI selector smoke test", markdown)
        self.assertIn("source selection only", markdown)
        self.assertIn("not end-to-end answer quality", markdown)
        self.assertIn("Deterministic validation is the source of truth", markdown)
        self.assertIn("No oracle fallback is counted as success", markdown)
        self.assertIn("Selector exact match rate: 100.00%", markdown)


if __name__ == "__main__":
    unittest.main()
