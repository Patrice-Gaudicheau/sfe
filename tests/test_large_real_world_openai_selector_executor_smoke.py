"""Tests for OpenAI selector plus OpenAI executor smoke benchmark."""

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

from providers.openai_api import MissingOpenAIAPIKeyError
from runtime.run_large_real_world_multi_zone_benchmark import get_large_real_world_tasks
from runtime.run_large_real_world_openai_selector_executor_smoke import (
    BENCHMARK_TYPE,
    ExecutorConfig,
    SelectorConfig,
    _parse_args,
    build_executor_prompt,
    execute_selector_executor_smoke,
    main,
    parse_executor_output,
    run_benchmark,
    write_markdown,
)


class FakeProvider:
    def __init__(
        self,
        *,
        selections: list[list[str]] | None = None,
        executor_payloads: list[dict[str, object]] | None = None,
        selector_raw_outputs: list[str] | None = None,
        executor_raw_outputs: list[str] | None = None,
    ) -> None:
        self.selections = selections or []
        self.executor_payloads = executor_payloads or []
        self.selector_raw_outputs = selector_raw_outputs or []
        self.executor_raw_outputs = executor_raw_outputs or []
        self.calls: list[dict[str, object]] = []
        self.selector_calls = 0
        self.executor_calls = 0

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
        if system_instruction and "selecting source documents" in system_instruction:
            index = self.selector_calls
            self.selector_calls += 1
            if self.selector_raw_outputs:
                content = self.selector_raw_outputs[index]
            else:
                selected = self.selections[index]
                content = json.dumps(
                    {
                        "selected_source_ids": selected,
                        "selection_rationale": {
                            source_id: "selected by fake selector" for source_id in selected
                        },
                    }
                )
            return _fake_response(content, 1000 + index, 100 + index, 200 + index)

        index = self.executor_calls
        self.executor_calls += 1
        if self.executor_raw_outputs:
            content = self.executor_raw_outputs[index]
        else:
            content = json.dumps(self.executor_payloads[index])
        return _fake_response(content, 500 + index, 80 + index, 300 + index)


class RaisingProvider:
    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int,
        temperature: float | None,
        system_instruction: str | None,
    ) -> dict[str, object]:
        raise RuntimeError("provider unavailable")


class LargeRealWorldOpenAISelectorExecutorSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_large_real_world_tasks()
        self.gateway_task = self.tasks[0]
        self.roadmap_task = self.tasks[1]
        self.selector_config = SelectorConfig(model="example-router", max_output_tokens=777)
        self.executor_config = ExecutorConfig(model="example-executor", max_output_tokens=888)

    def test_selector_exact_ids_flow_into_executor_context(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        provider = FakeProvider(
            selections=[selected],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertEqual(run["selected_source_ids"], selected)
        self.assertEqual(run["executor_prompt_context_source_ids"], selected)
        self.assertTrue(run["selector_exact_match"])
        self.assertTrue(run["executor_validation_passed"])
        self.assertTrue(run["honest_end_to_end_pass"])

    def test_executor_receives_selected_context_only_not_full_context(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        provider = FakeProvider(
            selections=[selected],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        executor_prompt = str(provider.calls[1]["messages"][0]["content"])
        self.assertIn("doc-gateway-architecture-current", executor_prompt)
        self.assertIn("doc-gateway-owner-decision-record", executor_prompt)
        self.assertNotIn("doc-gateway-beta-archive", executor_prompt)
        self.assertNotIn("doc-gateway-glossary", executor_prompt)

    def test_executor_does_not_receive_oracle_ids_when_selector_fails(self) -> None:
        provider = FakeProvider(
            selector_raw_outputs=["not json"],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertTrue(run["selector_fallback_used"])
        self.assertFalse(run["selector_parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertEqual(run["executor_prompt_context_source_ids"], [])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_deterministic_executor_is_not_used_as_fallback(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=FakeProvider(selections=[selected]),
            executor_provider=RaisingProvider(),
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertTrue(run["executor_fallback_used"])
        self.assertEqual(run["output"], "")
        self.assertFalse(run["executor_output_parse_success"])
        self.assertFalse(run["executor_validation_passed"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_selector_parse_failure_fails_honest_end_to_end_pass(self) -> None:
        provider = FakeProvider(
            selector_raw_outputs=["not json"],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertTrue(run["selector_fallback_used"])
        self.assertFalse(run["selector_parse_success"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_selector_missing_selected_source_ids_fails_honest_end_to_end_pass(self) -> None:
        provider = FakeProvider(
            selector_raw_outputs=[json.dumps({"selection_rationale": {}})],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertTrue(run["selector_fallback_used"])
        self.assertFalse(run["selector_parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_selector_non_list_selected_source_ids_fails_honest_end_to_end_pass(self) -> None:
        provider = FakeProvider(
            selector_raw_outputs=[
                json.dumps(
                    {
                        "selected_source_ids": "doc-gateway-architecture-current",
                        "selection_rationale": {},
                    }
                )
            ],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertTrue(run["selector_fallback_used"])
        self.assertFalse(run["selector_parse_success"])
        self.assertEqual(run["selected_source_ids"], [])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_selector_duplicate_ids_fail_honest_end_to_end_pass(self) -> None:
        duplicate = self.gateway_task.required_source_ids[0]
        provider = FakeProvider(
            selector_raw_outputs=[
                json.dumps(
                    {
                        "selected_source_ids": [duplicate, duplicate],
                        "selection_rationale": {},
                    }
                )
            ],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertTrue(run["selector_fallback_used"])
        self.assertFalse(run["selector_parse_success"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_selector_decorated_id_fails_without_oracle_substitution(self) -> None:
        decorated = f"SOURCE {self.gateway_task.required_source_ids[0]}"
        selected = [decorated] + list(self.gateway_task.required_source_ids[1:])
        provider = FakeProvider(
            selections=[selected],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertIn(decorated, run["unknown_selected_source_ids"])
        self.assertIn(self.gateway_task.required_source_ids[0], run["missing_required_source_ids"])
        self.assertNotIn(decorated, run["executor_prompt_context_source_ids"])
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_selector_unknown_extra_id_fails_even_if_required_sources_are_selected(self) -> None:
        selected = list(self.gateway_task.required_source_ids) + ["doc-invented-source"]
        provider = FakeProvider(
            selections=[selected],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertIn("doc-invented-source", run["unknown_selected_source_ids"])
        self.assertNotIn("doc-invented-source", run["executor_prompt_context_source_ids"])
        self.assertTrue(run["executor_validation_passed"])
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_executor_parse_failure_fails_honest_end_to_end_pass(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        provider = FakeProvider(
            selections=[selected],
            executor_raw_outputs=["not json"],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertFalse(run["executor_output_parse_success"])
        self.assertTrue(run["executor_fallback_used"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_executor_validation_failure_fails_honest_end_to_end_pass(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        payload = _expected_executor_payload(self.gateway_task)
        payload["gateway_status"] = "transparent gateway is live"
        provider = FakeProvider(selections=[selected], executor_payloads=[payload])

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertTrue(run["executor_output_parse_success"])
        self.assertFalse(run["executor_validation_passed"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_missing_required_source_fails(self) -> None:
        selected = list(self.gateway_task.required_source_ids[:-1])
        provider = FakeProvider(
            selections=[selected],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertIn("doc-gateway-owner-decision-record", run["missing_required_source_ids"])
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_distractor_selected_fails(self) -> None:
        selected = list(self.gateway_task.required_source_ids[:-1]) + ["doc-gateway-glossary"]
        provider = FakeProvider(
            selections=[selected],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertIn("doc-gateway-glossary", run["selected_distractor_source_ids"])
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_executor_output_with_decorated_evidence_ids_fails_parse(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        payload = _expected_executor_payload(self.gateway_task)
        payload["evidence_source_ids"] = [
            f"SOURCE {source_id}" for source_id in self.gateway_task.required_source_ids
        ]
        provider = FakeProvider(selections=[selected], executor_payloads=[payload])

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertFalse(run["executor_output_parse_success"])
        self.assertIn("outside selected context", run["executor_output_parse_error"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_executor_output_with_non_list_evidence_ids_fails_parse(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        payload = _expected_executor_payload(self.gateway_task)
        payload["evidence_source_ids"] = "doc-gateway-architecture-current"
        provider = FakeProvider(selections=[selected], executor_payloads=[payload])

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertFalse(run["executor_output_parse_success"])
        self.assertIn("must be a JSON array", run["executor_output_parse_error"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_executor_output_with_duplicate_evidence_ids_fails_parse(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        payload = _expected_executor_payload(self.gateway_task)
        payload["evidence_source_ids"] = [
            self.gateway_task.required_source_ids[0],
            self.gateway_task.required_source_ids[0],
        ]
        provider = FakeProvider(selections=[selected], executor_payloads=[payload])

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertFalse(run["executor_output_parse_success"])
        self.assertIn("must not contain duplicates", run["executor_output_parse_error"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_executor_output_with_evidence_ids_outside_selected_context_fails_parse(self) -> None:
        selected = list(self.gateway_task.required_source_ids)
        payload = _expected_executor_payload(self.gateway_task)
        payload["evidence_source_ids"] = list(self.gateway_task.required_source_ids[:-1]) + [
            "doc-gateway-glossary"
        ]
        provider = FakeProvider(selections=[selected], executor_payloads=[payload])

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertFalse(run["executor_output_parse_success"])
        self.assertIn("outside selected context", run["executor_output_parse_error"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_parse_executor_output_rejects_missing_and_extra_fields(self) -> None:
        payload = _expected_executor_payload(self.gateway_task)
        del payload["gateway_status"]
        with self.assertRaisesRegex(ValueError, "missing required fields"):
            parse_executor_output(
                task=self.gateway_task,
                response_text=json.dumps(payload),
                selected_source_ids=self.gateway_task.required_source_ids,
            )

        payload = _expected_executor_payload(self.gateway_task)
        payload["extra"] = "not allowed"
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            parse_executor_output(
                task=self.gateway_task,
                response_text=json.dumps(payload),
                selected_source_ids=self.gateway_task.required_source_ids,
            )

    def test_report_metrics_from_mocked_selector_and_executor_results(self) -> None:
        provider = FakeProvider(
            selections=[list(task.required_source_ids) for task in self.tasks],
            executor_payloads=[_expected_executor_payload(task) for task in self.tasks],
        )

        report = run_benchmark(
            tasks=self.tasks,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )
        summary = report["summary"]

        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(summary["selector_exact_match_rate"], 1.0)
        self.assertEqual(summary["executor_parse_success_rate"], 1.0)
        self.assertEqual(summary["executor_validation_rate"], 1.0)
        self.assertEqual(summary["honest_end_to_end_pass_rate"], 1.0)
        self.assertEqual(summary["selector_fallback_count"], 0)
        self.assertEqual(summary["executor_fallback_count"], 0)
        self.assertEqual(summary["selector_parse_failure_count"], 0)
        self.assertEqual(summary["executor_parse_failure_count"], 0)
        self.assertEqual(summary["total_selector_tokens"], 2202)
        self.assertEqual(summary["total_executor_tokens"], 1162)
        self.assertEqual(summary["total_tokens"], 3364)
        self.assertGreater(summary["average_token_reduction_percent"], 70.0)

    def test_report_metrics_from_bad_mocked_executor_result(self) -> None:
        provider = FakeProvider(
            selections=[list(self.gateway_task.required_source_ids)],
            executor_raw_outputs=["not json"],
        )

        report = run_benchmark(
            tasks=[self.gateway_task],
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )
        summary = report["summary"]

        self.assertEqual(summary["selector_exact_match_rate"], 1.0)
        self.assertEqual(summary["executor_parse_success_rate"], 0.0)
        self.assertEqual(summary["executor_validation_rate"], 0.0)
        self.assertEqual(summary["honest_end_to_end_pass_rate"], 0.0)
        self.assertEqual(summary["executor_fallback_count"], 1)
        self.assertEqual(summary["executor_parse_failure_count"], 1)

    def test_selected_context_token_reduction_uses_openai_selected_ids_not_oracle(self) -> None:
        selected = ["doc-gateway-glossary"]
        provider = FakeProvider(
            selections=[selected],
            executor_payloads=[_expected_executor_payload(self.gateway_task)],
        )

        run = execute_selector_executor_smoke(
            task=self.gateway_task,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        self.assertEqual(run["selected_source_ids"], selected)
        self.assertLess(
            run["selected_context_token_estimate"],
            run["full_context_token_estimate"],
        )
        self.assertFalse(run["selector_exact_match"])
        self.assertFalse(run["honest_end_to_end_pass"])

    def test_build_executor_prompt_lists_selected_ids_and_schema(self) -> None:
        selected = self.gateway_task.required_source_ids
        prompt = build_executor_prompt(
            self.gateway_task,
            selected,
            "SOURCE ID: doc-gateway-architecture-current\ncontent",
        )

        self.assertIn('"current_runtime_mode"', prompt)
        self.assertIn('"evidence_source_ids"', prompt)
        self.assertIn("use only the selected source context", prompt.lower())
        self.assertIn("doc-gateway-architecture-current", prompt)
        self.assertIn(self.gateway_task.question, prompt)
        self.assertNotIn("doc-gateway-glossary", prompt)
        self.assertNotIn(self.gateway_task.expected_answer, prompt)

    def test_default_cli_parse_does_not_call_openai(self) -> None:
        with patch.object(
            sys,
            "argv",
            ["run_large_real_world_openai_selector_executor_smoke.py"],
        ):
            args = _parse_args()

        self.assertIsNone(args.model)
        self.assertIsNone(args.executor_model)
        self.assertEqual(args.max_output_tokens, 900)
        self.assertEqual(args.executor_max_output_tokens, 1000)

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
            "runtime.run_large_real_world_openai_selector_executor_smoke.load_repo_env",
            return_value={},
        ):
            with patch(
                "runtime.run_large_real_world_openai_selector_executor_smoke.OpenAIAPIProvider",
                MissingKeyProvider,
            ):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "run_large_real_world_openai_selector_executor_smoke.py",
                        "--json",
                        "/tmp/no_key.json",
                        "--md",
                        "/tmp/no_key.md",
                    ],
                ):
                    with self.assertRaises(MissingOpenAIAPIKeyError):
                        main()

    def test_markdown_report_states_limited_scope(self) -> None:
        provider = FakeProvider(
            selections=[list(task.required_source_ids) for task in self.tasks],
            executor_payloads=[_expected_executor_payload(task) for task in self.tasks],
        )
        report = run_benchmark(
            tasks=self.tasks,
            selector_provider=provider,
            executor_provider=provider,
            selector_config=self.selector_config,
            executor_config=self.executor_config,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "selector_executor.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("OpenAI selector + OpenAI executor smoke test", markdown)
        self.assertIn("Deterministic validation is still the source of truth", markdown)
        self.assertIn("not broad real-world proof", markdown)
        self.assertIn("repeat-N stability is not established", markdown)
        self.assertIn("Honest end-to-end pass rate: 100.00%", markdown)


def _expected_executor_payload(task: object) -> dict[str, object]:
    expected_fields = getattr(task, "expected_fields")
    required_source_ids = getattr(task, "required_source_ids")
    payload: dict[str, object] = dict(expected_fields)
    payload["evidence_source_ids"] = list(required_source_ids)
    return payload


def _fake_response(
    content: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_ms: int,
) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "openai_api": {"latency_ms": latency_ms},
    }


if __name__ == "__main__":
    unittest.main()
