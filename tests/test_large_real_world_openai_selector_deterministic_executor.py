"""Tests for OpenAI selector plus deterministic executor benchmark."""

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
from runtime.run_large_real_world_openai_selector_deterministic_executor import (
    BENCHMARK_TYPE,
    SelectorConfig,
    _parse_args,
    execute_selector_deterministic_executor,
    main,
    run_benchmark,
    run_deterministic_executor,
    write_markdown,
)
from providers.openai_api import MissingOpenAIAPIKeyError


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
                        source_id: "selected by fake provider" for source_id in selected
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


class LargeRealWorldOpenAISelectorDeterministicExecutorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_large_real_world_tasks()
        self.gateway_task = self.tasks[0]
        self.roadmap_task = self.tasks[1]
        self.config = SelectorConfig(model="example-router", max_output_tokens=777)

    def test_exact_openai_selected_ids_flow_into_deterministic_executor(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        provider = FakeSelectorProvider(selections=[selected])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertEqual(run["selected_source_ids"], selected)
        self.assertEqual(run["executor_used_selected_source_ids"], selected)
        self.assertTrue(run["selector_exact_match"])
        self.assertTrue(run["deterministic_executor_validation_passed"])
        self.assertTrue(run["honest_selector_deterministic_executor_pass"])

    def test_deterministic_executor_does_not_receive_oracle_ids_when_selector_fails(self) -> None:
        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=RaisingSelectorProvider(),
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertEqual(run["executor_used_selected_source_ids"], [])
        self.assertFalse(run["deterministic_executor_validation_passed"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_missing_required_source_fails_contract(self) -> None:
        selected = list(self.gateway_task.required_source_ids[:-1])
        provider = FakeSelectorProvider(selections=[selected])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertFalse(run["selector_exact_match"])
        self.assertIn("doc-gateway-owner-decision-record", run["missing_required_source_ids"])
        self.assertFalse(run["deterministic_executor_validation_passed"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_distractor_selected_fails_honest_pass(self) -> None:
        selected = list(self.gateway_task.required_source_ids[:-1]) + [
            "doc-gateway-glossary"
        ]
        provider = FakeSelectorProvider(selections=[selected])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertFalse(run["selector_exact_match"])
        self.assertIn("doc-gateway-glossary", run["selected_distractor_source_ids"])
        self.assertFalse(run["deterministic_executor_validation_passed"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_parser_failure_fails_honest_pass(self) -> None:
        provider = FakeSelectorProvider(raw_outputs=["not json"])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["parse_success"])
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["deterministic_executor_validation_passed"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_missing_selected_source_ids_parse_failure_fails_honest_pass(self) -> None:
        provider = FakeSelectorProvider(raw_outputs=[json.dumps({"selection_rationale": {}})])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_non_list_selected_source_ids_parse_failure_fails_honest_pass(self) -> None:
        provider = FakeSelectorProvider(
            raw_outputs=[
                json.dumps(
                    {
                        "selected_source_ids": "doc-gateway-architecture-current",
                        "selection_rationale": {},
                    }
                )
            ]
        )

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_duplicate_selected_source_ids_parse_failure_fails_honest_pass(self) -> None:
        duplicated = [
            self.gateway_task.required_source_ids[0],
            self.gateway_task.required_source_ids[0],
        ]
        provider = FakeSelectorProvider(
            raw_outputs=[
                json.dumps(
                    {
                        "selected_source_ids": duplicated,
                        "selection_rationale": {},
                    }
                )
            ]
        )

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_decorated_id_fails_without_oracle_substitution(self) -> None:
        decorated = f"SOURCE {self.gateway_task.required_source_ids[0]}"
        selected = [decorated] + list(self.gateway_task.required_source_ids[1:])
        provider = FakeSelectorProvider(selections=[selected])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertIn(decorated, run["unknown_selected_source_ids"])
        self.assertIn(self.gateway_task.required_source_ids[0], run["missing_required_source_ids"])
        self.assertNotIn(decorated, run["executor_used_selected_source_ids"])
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["deterministic_executor_validation_passed"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_unknown_extra_id_fails_honest_pass_even_if_required_sources_are_selected(self) -> None:
        selected = list(self.gateway_task.required_source_ids) + ["doc-invented-source"]
        provider = FakeSelectorProvider(selections=[selected])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertIn("doc-invented-source", run["unknown_selected_source_ids"])
        self.assertNotIn("doc-invented-source", run["executor_used_selected_source_ids"])
        self.assertTrue(run["deterministic_executor_validation_passed"])
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_fallback_fails_honest_pass(self) -> None:
        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=RaisingSelectorProvider(),
            config=self.config,
        )

        self.assertTrue(run["fallback_used"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_deterministic_executor_validation_failure_fails_honest_pass(self) -> None:
        selected = [
            "doc-gateway-architecture-current",
            "doc-gateway-routing-policy",
            "doc-gateway-exclusions-current",
        ]
        executor_result = run_deterministic_executor(self.gateway_task, selected)

        self.assertNotIn("responsible_owner", executor_result["output"])
        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=FakeSelectorProvider(selections=[selected]),
            config=self.config,
        )

        self.assertFalse(run["deterministic_executor_validation_passed"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_report_metrics_from_mocked_exact_results(self) -> None:
        provider = FakeSelectorProvider(
            selections=[list(task.required_source_ids) for task in self.tasks]
        )

        report = run_benchmark(tasks=self.tasks, provider=provider, config=self.config)
        summary = report["summary"]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual(summary["selector_exact_match_rate"], 1.0)
        self.assertEqual(summary["deterministic_executor_validation_rate"], 1.0)
        self.assertEqual(summary["honest_end_to_contract_pass_rate"], 1.0)
        self.assertEqual(summary["fallback_count"], 0)
        self.assertEqual(summary["parse_failure_count"], 0)
        self.assertEqual(summary["repair_status"], "not_supported")
        self.assertEqual(summary["total_prompt_tokens"], 2001)
        self.assertEqual(summary["total_completion_tokens"], 201)
        self.assertEqual(summary["total_tokens"], 2202)
        self.assertGreater(summary["average_token_reduction_percent"], 70.0)

    def test_report_metrics_from_mocked_bad_selector_result(self) -> None:
        provider = FakeSelectorProvider(
            selections=[
                list(self.gateway_task.required_source_ids),
                list(self.roadmap_task.required_source_ids[:-1])
                + ["doc-token-savings-analysis-draft"],
            ]
        )

        report = run_benchmark(tasks=self.tasks, provider=provider, config=self.config)
        summary = report["summary"]
        bad_run = report["runs"][1]

        self.assertEqual(summary["selector_exact_match_rate"], 0.5)
        self.assertEqual(summary["deterministic_executor_validation_rate"], 0.5)
        self.assertEqual(summary["honest_end_to_contract_pass_rate"], 0.5)
        self.assertIn("doc-honest-validation-policy", bad_run["missing_required_source_ids"])
        self.assertIn("doc-token-savings-analysis-draft", bad_run["selected_distractor_source_ids"])
        self.assertFalse(bad_run["honest_selector_deterministic_executor_pass"])

    def test_token_reduction_uses_openai_selected_ids_not_oracle_ids(self) -> None:
        selected = ["doc-gateway-glossary"]
        provider = FakeSelectorProvider(selections=[selected])

        run = execute_selector_deterministic_executor(
            task=self.gateway_task,
            provider=provider,
            config=self.config,
        )

        self.assertEqual(run["selected_source_ids"], selected)
        self.assertLess(
            run["selected_context_token_estimate"],
            run["full_context_token_estimate"],
        )
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["honest_selector_deterministic_executor_pass"])

    def test_default_cli_parse_does_not_call_openai(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_large_real_world_openai_selector_deterministic_executor.py"],
        ):
            args = _parse_args()

        self.assertIsNone(args.model)
        self.assertEqual(args.max_output_tokens, 900)

    def test_missing_openai_api_key_fails_live_cli_without_fallback(self) -> None:
        class MissingKeyProvider:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def health(self) -> dict[str, object]:
                return {
                    "ok": False,
                    "error": "OPENAI_API_KEY is required for provider openai-api.",
                }

        with patch(
            "runtime.run_large_real_world_openai_selector_deterministic_executor.load_repo_env",
            return_value={},
        ):
            with patch(
                "runtime.run_large_real_world_openai_selector_deterministic_executor.OpenAIAPIProvider",
                MissingKeyProvider,
            ):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_large_real_world_openai_selector_deterministic_executor.py",
                        "--json",
                        "/tmp/large_real_world_no_key.json",
                        "--md",
                        "/tmp/large_real_world_no_key.md",
                    ],
                ):
                    with self.assertRaises(MissingOpenAIAPIKeyError):
                        main()

    def test_markdown_report_states_limited_scope(self) -> None:
        provider = FakeSelectorProvider(
            selections=[list(task.required_source_ids) for task in self.tasks]
        )
        report = run_benchmark(tasks=self.tasks, provider=provider, config=self.config)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "selector_deterministic_executor.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("OpenAI selector and a deterministic executor", markdown)
        self.assertIn("not OpenAI end-to-end answer generation", markdown)
        self.assertIn("Deterministic validation is the source of truth", markdown)
        self.assertIn("no oracle fallback is counted as success", markdown)
        self.assertIn("Honest end-to-contract pass rate: 100.00%", markdown)


if __name__ == "__main__":
    unittest.main()
