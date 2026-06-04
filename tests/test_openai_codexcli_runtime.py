"""Tests for OpenAI/CodexCLI runtime wiring."""

from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.codexcli import (
    DEFAULT_EXECUTOR_MODEL as CODEXCLI_DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as CODEXCLI_DEFAULT_ROUTER_MODEL,
    PROVIDER_NAME,
)
from router import llm_router
from runtime import run_effectiveness_benchmark, run_experiment
from runtime.logger import list_runs, log_run


class OpenAICodexCLIRuntimeTests(unittest.TestCase):
    def test_codexcli_default_models_match_openai_api_pairing(self) -> None:
        self.assertEqual(CODEXCLI_DEFAULT_ROUTER_MODEL, "gpt-5.4")
        self.assertEqual(CODEXCLI_DEFAULT_EXECUTOR_MODEL, "gpt-5.4")

    def test_cli_parses_openai_router_executor_and_models(self) -> None:
        argv = [
            "run_experiment.py",
            "--router",
            PROVIDER_NAME,
            "--executor",
            PROVIDER_NAME,
            "--router-model",
            "gpt-5.4-mini",
            "--executor-model",
            "gpt-5.5",
            "--timeout-seconds",
            "12",
        ]

        with patch.object(sys, "argv", argv):
            args = run_experiment._parse_args()

        self.assertEqual(args.router, PROVIDER_NAME)
        self.assertEqual(args.executor, PROVIDER_NAME)
        self.assertEqual(args.router_model, "gpt-5.4-mini")
        self.assertEqual(args.executor_model, "gpt-5.5")
        self.assertEqual(args.timeout_seconds, 12)

    def test_openai_executor_failure_is_logged_as_failed_run_data(self) -> None:
        class FailingProvider:
            def __init__(self, **_: object) -> None:
                pass

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                raise RuntimeError("missing OpenAI credentials")

        decision = {
            "task_type": "writing",
            "role": "writer",
            "provider": PROVIDER_NAME,
            "router_model": "gpt-5.4-mini",
            "model": "gpt-5.5",
            "memory_zones": [],
            "router_latency_ms": 1234,
            "router_input_tokens": 100,
            "router_output_tokens": 20,
            "router_total_tokens": 120,
            "router_error": "",
        }

        with patch.object(run_experiment, "CodexCLIProvider", FailingProvider):
            execution = run_experiment._execute_with_codexcli(
                task="Write one sentence.",
                task_label="writing",
                routing_decision=decision,
                mode="baseline",
                router_name=PROVIDER_NAME,
                executor_name=PROVIDER_NAME,
                executor_model="gpt-5.5",
                timeout_seconds=1,
                debug_raw_response=False,
            )

        self.assertFalse(execution["run_data"]["success"])
        self.assertEqual(execution["run_data"]["provider"], PROVIDER_NAME)
        self.assertEqual(execution["run_data"]["router_model"], "gpt-5.4-mini")
        self.assertEqual(execution["run_data"]["executor_model"], "gpt-5.5")
        self.assertEqual(execution["run_data"]["router_latency_ms"], 1234)
        self.assertEqual(execution["run_data"]["router_total_tokens"], 120)
        self.assertIn("missing OpenAI credentials", execution["run_data"]["error"])

    def test_logger_persists_openai_metadata_and_router_metric_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "runs.sqlite")
            run_id = log_run(
                {
                    "task_type": "writing",
                    "mode": "baseline",
                    "provider": PROVIDER_NAME,
                    "model": "gpt-5.5",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "latency_ms": 42,
                    "success": False,
                    "router": PROVIDER_NAME,
                    "executor": PROVIDER_NAME,
                    "router_model": "gpt-5.4-mini",
                    "executor_model": "gpt-5.5",
                    "router_latency_ms": 1234,
                    "router_input_tokens": 100,
                    "router_output_tokens": 20,
                    "router_total_tokens": 120,
                    "router_error": "",
                    "prompt_style": "baseline_direct",
                    "task_label": "writing",
                    "error": "missing OpenAI credentials",
                },
                db_path=db_path,
            )
            rows = list_runs(db_path=db_path)

        self.assertEqual(rows[0]["run_id"], run_id)
        self.assertEqual(rows[0]["router_model"], "gpt-5.4-mini")
        self.assertEqual(rows[0]["executor_model"], "gpt-5.5")
        self.assertEqual(rows[0]["router_latency_ms"], 1234)
        self.assertEqual(rows[0]["router_input_tokens"], 100)
        self.assertEqual(rows[0]["router_output_tokens"], 20)
        self.assertEqual(rows[0]["router_total_tokens"], 120)
        self.assertEqual(rows[0]["router_error"], "")
        self.assertEqual(rows[0]["error"], "missing OpenAI credentials")

    def test_logger_migrates_old_schema_for_router_metric_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = str(Path(tmpdir) / "runs.sqlite")
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE runs (
                        run_id TEXT PRIMARY KEY,
                        timestamp TEXT NOT NULL,
                        task_type TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        provider TEXT NOT NULL,
                        model TEXT NOT NULL,
                        input_tokens INTEGER NOT NULL,
                        output_tokens INTEGER NOT NULL,
                        total_tokens INTEGER NOT NULL,
                        latency_ms INTEGER NOT NULL,
                        success INTEGER NOT NULL,
                        structural_consistency REAL,
                        router TEXT,
                        executor TEXT,
                        prompt_style TEXT,
                        task_label TEXT,
                        notes TEXT
                    )
                    """
                )

            log_run(
                {
                    "task_type": "writing",
                    "mode": "baseline",
                    "provider": PROVIDER_NAME,
                    "model": "gpt-5.5",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "latency_ms": 42,
                    "success": True,
                    "router_model": "gpt-5.4-mini",
                    "executor_model": "gpt-5.5",
                    "router_latency_ms": 1234,
                    "router_total_tokens": 120,
                },
                db_path=db_path,
            )
            rows = list_runs(db_path=db_path)

        self.assertEqual(rows[0]["router_model"], "gpt-5.4-mini")
        self.assertEqual(rows[0]["executor_model"], "gpt-5.5")
        self.assertEqual(rows[0]["router_latency_ms"], 1234)
        self.assertIsNone(rows[0]["router_input_tokens"])
        self.assertEqual(rows[0]["router_total_tokens"], 120)

    def test_main_prints_router_model_separately_from_executor_model(self) -> None:
        decision = {
            "task_type": "writing",
            "role": "writer",
            "provider": PROVIDER_NAME,
            "router_model": "gpt-5.4-mini",
            "model": "gpt-5.5",
            "memory_zones": [],
        }
        execution = {
            "executor_model": "gpt-5.5",
            "error_marker": "",
            "response_text": "answer",
            "tokens": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            "latency_ms": 10,
            "run_data": {
                "task_type": "writing",
                "mode": "baseline",
                "provider": PROVIDER_NAME,
                "model": "gpt-5.5",
                "input_tokens": 1,
                "output_tokens": 1,
                "total_tokens": 2,
                "latency_ms": 10,
                "success": True,
            },
        }
        argv = [
            "run_experiment.py",
            "--router",
            PROVIDER_NAME,
            "--executor",
            PROVIDER_NAME,
            "--task",
            "Write one sentence.",
        ]

        output = io.StringIO()
        with patch.object(sys, "argv", argv), patch.object(
            run_experiment, "_route_task", return_value=decision
        ), patch.object(
            run_experiment, "_execute_task", return_value=execution
        ), patch.object(
            run_experiment, "log_run", return_value="run-id"
        ), contextlib.redirect_stdout(output):
            run_experiment.main()

        text = output.getvalue()
        self.assertIn("router model: gpt-5.4-mini", text)
        self.assertIn("executor model: gpt-5.5", text)
        self.assertNotIn("routing model: gpt-5.5", text)

    def test_codexcli_router_adds_separate_router_metrics_to_decision(self) -> None:
        class FakeProvider:
            def __init__(self, **_: object) -> None:
                self.timeout = 12

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "task_type": "writing",
                                        "role": "writer",
                                        "provider": "local",
                                        "model": llm_router.DEFAULT_EXECUTION_MODEL,
                                        "memory_zones": [],
                                        "execution_mode": "direct",
                                        "max_input_tokens": 4000,
                                        "max_output_tokens": 1000,
                                        "requires_review": False,
                                        "confidence": 0.9,
                                        "rationale": "writing task",
                                    }
                                )
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 101,
                        "completion_tokens": 21,
                        "total_tokens": 122,
                    },
                    "codexcli": {"latency_ms": 1234},
                }

        with patch.object(llm_router, "CodexCLIProvider", FakeProvider):
            decision, diagnostics = llm_router.route_with_codexcli_diagnostics(
                "Write one sentence.",
                router_model="gpt-5.4-mini",
                executor_model="gpt-5.5",
                timeout_seconds=12,
            )

        self.assertFalse(diagnostics["used_fallback"])
        self.assertEqual(decision["router_model"], "gpt-5.4-mini")
        self.assertEqual(decision["model"], "gpt-5.5")
        self.assertEqual(decision["router_latency_ms"], 1234)
        self.assertEqual(decision["router_input_tokens"], 101)
        self.assertEqual(decision["router_output_tokens"], 21)
        self.assertEqual(decision["router_total_tokens"], 122)
        self.assertEqual(decision["router_error"], "")

    def test_route_task_openai_uses_configured_models(self) -> None:
        fake_decision = {
            "task_type": "analysis",
            "role": "reviewer",
            "provider": PROVIDER_NAME,
            "router_model": "gpt-5.4-mini",
            "model": "gpt-5.5",
            "memory_zones": [],
        }

        with patch.object(run_experiment, "route_with_codexcli", return_value=fake_decision) as router:
            decision = run_experiment._route_task(
                "Compare two options.",
                PROVIDER_NAME,
                router_model="gpt-5.4-mini",
                executor_model="gpt-5.5",
                timeout_seconds=12,
            )

        self.assertEqual(decision, fake_decision)
        router.assert_called_once_with(
            "Compare two options.",
            router_model="gpt-5.4-mini",
            executor_model="gpt-5.5",
            timeout_seconds=12,
        )

    def test_effectiveness_cli_accepts_openai_codexcli_models(self) -> None:
        argv = [
            "run_effectiveness_benchmark.py",
            "--router",
            PROVIDER_NAME,
            "--executor",
            PROVIDER_NAME,
            "--router-model",
            "gpt-5.4-mini",
            "--executor-model",
            "gpt-5.5",
            "--repeat",
            "1",
        ]

        with patch.object(sys, "argv", argv):
            args = run_effectiveness_benchmark._parse_args()

        self.assertEqual(args.router, PROVIDER_NAME)
        self.assertEqual(args.executor, PROVIDER_NAME)
        self.assertEqual(args.router_model, "gpt-5.4-mini")
        self.assertEqual(args.executor_model, "gpt-5.5")
        self.assertEqual(args.repeat, 1)

    def test_effectiveness_deltas_include_executor_only_and_end_to_end_costs(self) -> None:
        baseline = {
            "total_tokens": 100,
            "prompt_tokens": 80,
            "completion_tokens": 20,
            "latency_ms": 1000,
            "output_quality_score": 1.0,
            "constraint_following_score": 1.0,
            "factuality_or_correctness_score": None,
            "success": True,
            "token_usage_scientific": True,
        }
        spatial = {
            "total_tokens": 90,
            "prompt_tokens": 75,
            "completion_tokens": 15,
            "latency_ms": 900,
            "output_quality_score": 1.0,
            "constraint_following_score": 1.0,
            "factuality_or_correctness_score": None,
            "success": True,
            "token_usage_scientific": True,
        }
        routing_decision = {
            "router_total_tokens": 30,
            "router_latency_ms": 200,
        }

        deltas = run_effectiveness_benchmark._compute_deltas(
            baseline,
            spatial,
            routing_latency_ms=250,
            routing_decision=routing_decision,
        )

        self.assertEqual(deltas["baseline_total_tokens"], 100)
        self.assertEqual(deltas["spatial_executor_total_tokens"], 90)
        self.assertEqual(deltas["spatial_router_total_tokens"], 30)
        self.assertEqual(deltas["spatial_end_to_end_total_tokens"], 120)
        self.assertEqual(deltas["executor_only_token_delta"], -10)
        self.assertEqual(deltas["executor_only_token_savings_pct"], 10.0)
        self.assertEqual(deltas["end_to_end_token_delta"], 20)
        self.assertEqual(deltas["end_to_end_token_savings_pct"], -20.0)
        self.assertEqual(deltas["baseline_latency_ms"], 1000)
        self.assertEqual(deltas["spatial_executor_latency_ms"], 900)
        self.assertEqual(deltas["spatial_router_latency_ms"], 200)
        self.assertEqual(deltas["spatial_end_to_end_latency_ms"], 1100)
        self.assertEqual(deltas["executor_only_latency_delta_ms"], -100)
        self.assertEqual(deltas["end_to_end_latency_delta_ms"], 100)

    def test_effectiveness_pair_exposes_top_level_end_to_end_fields(self) -> None:
        task = {
            "id": "writing_update",
            "task_type_expected": "writing",
            "prompt": "Write a concise project update.",
            "expected_constraints": {"required_keywords": []},
            "difficulty": "easy",
            "requires_code": False,
            "requires_reasoning": False,
            "scoring_mode": "heuristic",
        }
        routing_decision = {
            "task_type": "writing",
            "role": "writer",
            "provider": PROVIDER_NAME,
            "model": "gpt-5.5",
            "memory_zones": [],
            "router_total_tokens": 30,
            "router_latency_ms": 200,
        }

        with patch.object(
            run_effectiveness_benchmark,
            "_route_for_spatial",
            return_value=(
                routing_decision,
                {
                    "success": True,
                    "json_valid": True,
                    "used_fallback": False,
                    "decision_source": PROVIDER_NAME,
                    "attempt_count": 1,
                    "errors": [],
                },
            ),
        ), patch.object(
            run_effectiveness_benchmark,
            "_execute_and_score",
            side_effect=[
                {
                    "mode": "baseline",
                    "executor": PROVIDER_NAME,
                    "model": "gpt-5.5",
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "total_tokens": 100,
                    "latency_ms": 1000,
                    "success": True,
                    "token_usage_scientific": True,
                    "token_usage_source": "provider_reported",
                    "error": "",
                    "output": "baseline",
                    "output_quality_score": 1.0,
                    "constraint_following_score": 1.0,
                    "factuality_or_correctness_score": None,
                    "interference_score": 0.0,
                    "interference_hits": [],
                    "zone_path": "",
                    "score_checks": [],
                },
                {
                    "mode": "spatial",
                    "executor": PROVIDER_NAME,
                    "model": "gpt-5.5",
                    "prompt_tokens": 75,
                    "completion_tokens": 15,
                    "total_tokens": 90,
                    "latency_ms": 900,
                    "success": True,
                    "token_usage_scientific": True,
                    "token_usage_source": "provider_reported",
                    "error": "",
                    "output": "spatial",
                    "output_quality_score": 1.0,
                    "constraint_following_score": 1.0,
                    "factuality_or_correctness_score": None,
                    "interference_score": 0.0,
                    "interference_hits": [],
                    "zone_path": "",
                    "score_checks": [],
                },
            ],
        ):
            pair = run_effectiveness_benchmark._run_pair(
                task=task,
                executor_name=PROVIDER_NAME,
                executor_model="gpt-5.5",
                router_name=PROVIDER_NAME,
                repeat_index=1,
                max_tokens=256,
                timeout_seconds=30,
                router_model="gpt-5.4-mini",
                router_timeout_seconds=30,
                router_disable_thinking=False,
                debug_raw_response=False,
            )

        self.assertEqual(pair["baseline_total_tokens"], 100)
        self.assertEqual(pair["spatial_executor_total_tokens"], 90)
        self.assertEqual(pair["spatial_router_total_tokens"], 30)
        self.assertEqual(pair["spatial_end_to_end_total_tokens"], 120)
        self.assertEqual(pair["executor_only_token_savings_pct"], 10.0)
        self.assertEqual(pair["end_to_end_token_savings_pct"], -20.0)

    def test_markdown_separates_executor_only_and_end_to_end_sections(self) -> None:
        report = {
            "metadata": {
                "generated_at": "2026-05-07T00:00:00+00:00",
                "executor": PROVIDER_NAME,
                "router": PROVIDER_NAME,
                "router_model": "gpt-5.4-mini",
                "router_timeout_seconds": 30,
                "router_disable_thinking": False,
                "timeout_seconds": 30,
                "repeat": 1,
                "strict": True,
                "success_metric": "test",
            },
            "summary": {
                "effective": False,
                "paired_run_count": 1,
                "scoring_paired_run_count": 1,
                "token_savings_sample_count": 1,
                "router_success_rate": 1.0,
                "json_valid_rate": 1.0,
                "fallback_rate": 0.0,
                "routing_accuracy": 1.0,
                "real_routing_accuracy": 1.0,
                "real_routing_sample_count": 1,
                "fallback_assisted_routing_accuracy": 1.0,
                "fallback_assisted_routing_sample_count": 1,
                "openai_api_failure_count": 0,
                "fallback_used_count": 0,
                "estimated_token_usage_count": 0,
                "mean_quality_delta": 0.0,
                "mean_spatial_interference_score": 0.0,
                "mean_quality_preservation_ratio": 1.0,
                "quality_preserving_savings_rate": 0.0,
                "baseline_failure_rate": 0.0,
                "spatial_failure_rate": 0.0,
                "win_count": 0,
                "loss_count": 1,
                "tie_count": 0,
                "router_collapse_warning": "",
                "strict": True,
                "mean_executor_only_token_savings_pct": 10.0,
                "median_executor_only_token_savings_pct": 10.0,
                "mean_end_to_end_token_savings_pct": -20.0,
                "median_end_to_end_token_savings_pct": -20.0,
                "mean_executor_only_latency_delta_ms": -100.0,
                "median_executor_only_latency_delta_ms": -100.0,
                "mean_end_to_end_latency_delta_ms": 100.0,
                "median_end_to_end_latency_delta_ms": 100.0,
            },
            "role_by_task_type": {},
            "task_type_breakdown": {},
            "successful_pairs_only": {
                "summary": {
                    "paired_run_count": 1,
                    "mean_total_token_savings_percent": 10.0,
                    "median_total_token_savings_percent": 10.0,
                    "mean_end_to_end_token_savings_pct": -20.0,
                    "mean_quality_delta": 0.0,
                    "quality_preserving_savings_rate": 0.0,
                    "win_count": 0,
                    "loss_count": 1,
                    "tie_count": 0,
                },
                "task_type_breakdown": {},
            },
            "pairs": [],
        }

        markdown = run_effectiveness_benchmark._render_markdown(report)

        self.assertIn("## Executor-Only Comparison", markdown)
        self.assertIn("## End-to-End Comparison", markdown)
        self.assertIn("large fixed context overhead", markdown)

    def test_failed_router_fallback_does_not_count_as_real_routing_accuracy(self) -> None:
        pair = {
            "task_type_expected": "writing",
            "routed_task_type": "writing",
            "routing_correct": True,
            "routing": {
                "success": False,
                "json_valid": False,
                "used_fallback": True,
                "real_routing_evaluated": False,
            },
            "baseline": {"success": False, "token_usage_scientific": False},
            "spatial": {"success": False, "token_usage_scientific": False},
            "deltas": {
                "token_usage_scientific": False,
                "quality_preservation_ratio": 0.0,
                "executor_only_token_savings_pct": None,
                "end_to_end_token_savings_pct": None,
                "executor_only_latency_delta_ms": 0,
                "end_to_end_latency_delta_ms": 0,
                "quality_delta": 0.0,
                "constraint_following_delta": 0.0,
            },
            "outcome": "loss",
        }

        summary = run_effectiveness_benchmark._summarize([pair], strict=True)

        self.assertIsNone(summary["real_routing_accuracy"])
        self.assertEqual(summary["real_routing_sample_count"], 0)
        self.assertEqual(summary["fallback_assisted_routing_accuracy"], 1.0)
        self.assertEqual(summary["fallback_rate"], 1.0)

    def test_failed_executor_estimates_do_not_produce_scientific_savings(self) -> None:
        baseline = {
            "total_tokens": 100,
            "prompt_tokens": 100,
            "completion_tokens": 0,
            "latency_ms": 100,
            "output_quality_score": 0.0,
            "constraint_following_score": 0.0,
            "factuality_or_correctness_score": None,
            "success": False,
            "token_usage_scientific": False,
        }
        spatial = {
            "total_tokens": 90,
            "prompt_tokens": 90,
            "completion_tokens": 0,
            "latency_ms": 90,
            "output_quality_score": 0.0,
            "constraint_following_score": 0.0,
            "factuality_or_correctness_score": None,
            "success": False,
            "token_usage_scientific": False,
        }

        deltas = run_effectiveness_benchmark._compute_deltas(
            baseline,
            spatial,
            routing_decision={"router_total_tokens": 20},
        )

        self.assertFalse(deltas["token_usage_scientific"])
        self.assertIsNone(deltas["spatial_end_to_end_total_tokens"])
        self.assertEqual(deltas["spatial_end_to_end_total_tokens_estimated"], 110)
        self.assertIsNone(deltas["executor_only_token_savings_pct"])
        self.assertIsNone(deltas["end_to_end_token_savings_pct"])
        self.assertEqual(run_effectiveness_benchmark._token_savings_pairs([]), [])

    def test_markdown_uses_na_for_failed_executor_scientific_savings(self) -> None:
        report = {
            "metadata": {
                "generated_at": "2026-05-07T00:00:00+00:00",
                "executor": "openai-api",
                "router": "openai-api",
                "router_model": "gpt-5.4-nano",
                "router_timeout_seconds": 30,
                "router_disable_thinking": False,
                "timeout_seconds": 30,
                "repeat": 1,
                "strict": True,
                "success_metric": "test",
            },
            "summary": {
                "effective": False,
                "paired_run_count": 1,
                "scoring_paired_run_count": 0,
                "token_savings_sample_count": 0,
                "router_success_rate": 1.0,
                "json_valid_rate": 1.0,
                "fallback_rate": 0.0,
                "routing_accuracy": 1.0,
                "real_routing_accuracy": 1.0,
                "real_routing_sample_count": 1,
                "fallback_assisted_routing_accuracy": 1.0,
                "fallback_assisted_routing_sample_count": 1,
                "openai_api_failure_count": 2,
                "fallback_used_count": 0,
                "estimated_token_usage_count": 2,
                "mean_quality_delta": 0.0,
                "mean_spatial_interference_score": 0.0,
                "mean_quality_preservation_ratio": 0.0,
                "quality_preserving_savings_rate": 0.0,
                "baseline_failure_rate": 1.0,
                "spatial_failure_rate": 1.0,
                "win_count": 0,
                "loss_count": 1,
                "tie_count": 0,
                "router_collapse_warning": "",
                "strict": True,
                "mean_executor_only_token_savings_pct": None,
                "median_executor_only_token_savings_pct": None,
                "mean_end_to_end_token_savings_pct": None,
                "median_end_to_end_token_savings_pct": None,
                "mean_executor_only_latency_delta_ms": 0.0,
                "median_executor_only_latency_delta_ms": 0.0,
                "mean_end_to_end_latency_delta_ms": 0.0,
                "median_end_to_end_latency_delta_ms": 0.0,
            },
            "role_by_task_type": {},
            "task_type_breakdown": {},
            "successful_pairs_only": {
                "summary": {
                    "paired_run_count": 0,
                    "mean_total_token_savings_percent": None,
                    "median_total_token_savings_percent": None,
                    "mean_end_to_end_token_savings_pct": None,
                    "mean_quality_delta": 0.0,
                    "quality_preserving_savings_rate": 0.0,
                    "win_count": 0,
                    "loss_count": 0,
                    "tie_count": 0,
                },
                "task_type_breakdown": {},
            },
            "pairs": [
                {
                    "task_id": "writing_update",
                    "task_type_expected": "writing",
                    "routed_task_type": "writing",
                    "deltas": {
                        "executor_only_token_savings_pct": None,
                        "end_to_end_token_savings_pct": None,
                        "quality_delta": 0.0,
                        "constraint_following_delta": 0.0,
                    },
                    "outcome": "loss",
                    "routing": {"error": ""},
                    "baseline": {"success": False, "error": "unsupported temperature parameter"},
                    "spatial": {
                        "success": False,
                        "error": "unsupported temperature parameter",
                        "interference_score": 0.0,
                    },
                }
            ],
        }

        markdown = run_effectiveness_benchmark._render_markdown(report)

        self.assertIn("| Mean token savings | n/a |", markdown)
        self.assertNotIn("-222.73%", markdown)
        self.assertIn("unsupported temperature parameter", markdown)

    def test_insufficient_quota_is_visible_in_report_warnings(self) -> None:
        report = {
            "summary": {
                "openai_api_failure_count": 1,
                "fallback_used_count": 1,
                "estimated_token_usage_count": 2,
            },
            "pairs": [
                {
                    "routing": {"error": "OpenAI API request failed: insufficient_quota"},
                    "baseline": {"error": ""},
                    "spatial": {"error": ""},
                }
            ],
        }

        warnings = run_effectiveness_benchmark._report_warnings(report)

        self.assertTrue(any("insufficient_quota" in warning for warning in warnings))
        self.assertTrue(any("Fallback routing was used" in warning for warning in warnings))
        self.assertTrue(any("token fields are estimates" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
