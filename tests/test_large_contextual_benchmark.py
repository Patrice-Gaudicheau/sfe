"""Tests for the large/contextual benchmark."""

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

from runtime.run_large_contextual_benchmark import (
    ALIBABA_API_EXECUTOR,
    ALIBABA_API_JSON_PATH,
    ANTHROPIC_EXECUTOR,
    ANTHROPIC_JSON_PATH,
    BENCHMARK_TYPE,
    FINAL_PHASE_CONCLUSION,
    LemonadeBlockSelector,
    OPENAI_API_EXECUTOR,
    OPENAI_API_JSON_PATH,
    TASK_TIER_HIGH_CONTEXT,
    TASK_TIER_LONG,
    TASK_TIER_PRACTICAL,
    TASK_TIER_STANDARD,
    TASK_TIER_STRUCTURAL,
    _parse_args,
    build_prompt,
    build_selector_prompt,
    estimate_tokens,
    filter_tasks_by_label,
    get_large_contextual_tasks,
    normalize_task_tier,
    parse_selector_output,
    run_benchmark,
    select_relevant_block,
)


class LargeContextualBenchmarkTests(unittest.TestCase):
    def test_default_task_tier_remains_standard(self) -> None:
        default_tasks = get_large_contextual_tasks()
        standard_tasks = get_large_contextual_tasks(TASK_TIER_STANDARD)

        self.assertEqual(
            [task.task_label for task in default_tasks],
            [task.task_label for task in standard_tasks],
        )
        self.assertEqual(len(default_tasks), 7)

    def test_task_set_includes_harder_fixtures(self) -> None:
        tasks = get_large_contextual_tasks()
        labels = {task.task_label for task in tasks}
        patterns = {
            pattern
            for task in tasks
            for pattern in task.difficulty_patterns
        }

        self.assertGreaterEqual(len(tasks), 7)
        self.assertTrue(
            {
                "large_contextual_cache_failover_keyscope",
                "large_contextual_rollback_false_owner",
                "large_contextual_temporal_evaluation_gate",
                "large_contextual_near_relevant_allocation_exception",
            }
            <= labels
        )
        self.assertTrue(
            {
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
            }
            <= patterns
        )
        for task in tasks:
            if task.task_label in labels - {
                "large_contextual_payments_failover",
                "large_contextual_inventory_allocation",
                "large_contextual_eval_rollback",
            }:
                self.assertTrue(task.difficulty_patterns)

    def test_standard_tier_still_has_existing_seven_tasks(self) -> None:
        tasks = get_large_contextual_tasks(TASK_TIER_STANDARD)

        self.assertEqual(len(tasks), 7)
        self.assertEqual(
            {task.task_label for task in tasks},
            {
                "large_contextual_payments_failover",
                "large_contextual_inventory_allocation",
                "large_contextual_eval_rollback",
                "large_contextual_cache_failover_keyscope",
                "large_contextual_rollback_false_owner",
                "large_contextual_temporal_evaluation_gate",
                "large_contextual_near_relevant_allocation_exception",
            },
        )

    def test_practical_tier_exists_with_10k_to_20k_context_tasks(self) -> None:
        tasks = get_large_contextual_tasks(TASK_TIER_PRACTICAL)

        self.assertGreaterEqual(len(tasks), 3)
        for task in tasks:
            self.assertGreaterEqual(len(task.blocks), 8)
            self.assertLessEqual(len(task.blocks), 12)
            relevant_blocks = [block for block in task.blocks if block.relevant]
            self.assertEqual(len(relevant_blocks), 1)
            route = select_relevant_block(task)
            baseline_prompt = build_prompt(task, "baseline", route)
            spatial_prompt = build_prompt(task, "spatial", route)
            self.assertGreaterEqual(estimate_tokens(baseline_prompt), 10000)
            self.assertLessEqual(estimate_tokens(baseline_prompt), 20000)
            self.assertGreaterEqual(estimate_tokens(spatial_prompt), 1000)
            self.assertLessEqual(estimate_tokens(spatial_prompt), 3000)
            self.assertTrue(
                {
                    "same_keyword_distractor",
                    "false_answer_distractor",
                    "temporal_distractor",
                    "near_relevant_block",
                }
                <= set(task.difficulty_patterns)
            )

    def test_high_context_tier_exists_with_20k_to_50k_context_tasks(self) -> None:
        tasks = get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT)

        self.assertGreaterEqual(len(tasks), 2)
        for task in tasks:
            self.assertGreaterEqual(len(task.blocks), 10)
            self.assertLessEqual(len(task.blocks), 16)
            relevant_blocks = [block for block in task.blocks if block.relevant]
            self.assertEqual(len(relevant_blocks), 1)
            route = select_relevant_block(task)
            baseline_prompt = build_prompt(task, "baseline", route)
            spatial_prompt = build_prompt(task, "spatial", route)
            self.assertGreaterEqual(estimate_tokens(baseline_prompt), 20000)
            self.assertLessEqual(estimate_tokens(baseline_prompt), 50000)
            self.assertGreaterEqual(estimate_tokens(spatial_prompt), 2000)
            self.assertLessEqual(estimate_tokens(spatial_prompt), 5000)
            self.assertLess(estimate_tokens(spatial_prompt), estimate_tokens(baseline_prompt))
            self.assertTrue(
                {
                    "same_keyword_distractor",
                    "false_answer_distractor",
                    "temporal_distractor",
                    "near_relevant_block",
                    "same_owner_distractor",
                    "obsolete_rule_distractor",
                }
                <= set(task.difficulty_patterns)
            )

    def test_structural_tier_exists_with_one_50k_plus_context_task(self) -> None:
        tasks = get_large_contextual_tasks(TASK_TIER_STRUCTURAL)

        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(
            task.task_label,
            "large_contextual_structural_atlas_policy_mesh_gate",
        )
        self.assertGreaterEqual(len(task.blocks), 16)
        self.assertLessEqual(len(task.blocks), 20)
        relevant_blocks = [block for block in task.blocks if block.relevant]
        self.assertEqual(len(relevant_blocks), 1)
        self.assertEqual(relevant_blocks[0].block_id, "atlas-mesh-s9-final")
        self.assertIn("ATLAS_OWNER_S9", task.validation_targets)
        self.assertFalse(any("Nadia" in target for target in task.validation_targets))
        route = select_relevant_block(task)
        baseline_prompt = build_prompt(task, "baseline", route)
        spatial_prompt = build_prompt(task, "spatial", route)
        self.assertGreaterEqual(estimate_tokens(baseline_prompt), 50000)
        self.assertGreaterEqual(estimate_tokens(spatial_prompt), 4000)
        self.assertLessEqual(estimate_tokens(spatial_prompt), 8000)
        self.assertLess(estimate_tokens(spatial_prompt), estimate_tokens(baseline_prompt))
        self.assertTrue(
            {
                "same_keyword_distractor",
                "false_answer_distractor",
                "temporal_distractor",
                "near_relevant_block",
                "same_owner_distractor",
                "obsolete_rule_distractor",
                "structural_record_navigation",
                "partial_field_distractor",
            }
            <= set(task.difficulty_patterns)
        )

    def test_long_tier_alias_maps_to_practical(self) -> None:
        practical_tasks = get_large_contextual_tasks(TASK_TIER_PRACTICAL)
        alias_tasks = get_large_contextual_tasks(TASK_TIER_LONG)

        self.assertEqual(normalize_task_tier(TASK_TIER_LONG), TASK_TIER_PRACTICAL)
        self.assertEqual(
            [task.task_label for task in alias_tasks],
            [task.task_label for task in practical_tasks],
        )

    def test_task_label_filter_selects_exact_existing_task(self) -> None:
        tasks = get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT)
        selected = filter_tasks_by_label(
            tasks,
            "large_contextual_high_context_boreal_eval_release_gate",
            TASK_TIER_HIGH_CONTEXT,
        )

        self.assertEqual(len(selected), 1)
        self.assertEqual(
            selected[0].task_label,
            "large_contextual_high_context_boreal_eval_release_gate",
        )

    def test_task_label_filter_rejects_unknown_label_clearly(self) -> None:
        tasks = get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT)

        with self.assertRaisesRegex(ValueError, "not found in task tier 'high_context'") as raised:
            filter_tasks_by_label(tasks, "missing-task", TASK_TIER_HIGH_CONTEXT)

        self.assertIn("large_contextual_high_context_orion_router_budget_gate", str(raised.exception))
        self.assertIn("large_contextual_high_context_boreal_eval_release_gate", str(raised.exception))

    def test_cli_accepts_task_label_without_changing_default_tier(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "run_large_contextual_benchmark.py",
                "--task-label",
                "large_contextual_payments_failover",
                "--dry-run",
            ],
        ):
            args = _parse_args()

        self.assertEqual(args.task_tier, TASK_TIER_STANDARD)
        self.assertEqual(args.task_label, "large_contextual_payments_failover")

    def test_task_label_filter_is_applied_before_limit(self) -> None:
        tasks = get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT)
        selected = filter_tasks_by_label(
            tasks,
            "large_contextual_high_context_boreal_eval_release_gate",
            TASK_TIER_HIGH_CONTEXT,
        )
        limited = selected[:1]

        self.assertEqual(len(limited), 1)
        self.assertEqual(
            limited[0].task_label,
            "large_contextual_high_context_boreal_eval_release_gate",
        )

    def test_tasks_have_multiple_blocks_and_large_context(self) -> None:
        tasks = get_large_contextual_tasks()

        self.assertGreaterEqual(len(tasks), 7)
        for task in tasks:
            self.assertGreaterEqual(len(task.blocks), 4)
            baseline_prompt = build_prompt(task, "baseline", select_relevant_block(task))
            self.assertGreaterEqual(estimate_tokens(baseline_prompt), 2000)
            self.assertLessEqual(estimate_tokens(baseline_prompt), 5000)

    def test_each_task_has_exactly_one_relevant_block(self) -> None:
        for task in get_large_contextual_tasks():
            relevant_blocks = [block for block in task.blocks if block.relevant]
            route = select_relevant_block(task)

            self.assertEqual(len(relevant_blocks), 1)
            self.assertEqual(route["selected_block_id"], relevant_blocks[0].block_id)
            self.assertEqual(route["selected_block_count"], 1)

    def test_baseline_prompt_includes_all_blocks(self) -> None:
        for task in get_large_contextual_tasks():
            route = select_relevant_block(task)
            prompt = build_prompt(task, "baseline", route)

            for block in task.blocks:
                self.assertIn(f"BLOCK {block.block_id}", prompt)
            self.assertIn("Mode: baseline", prompt)

    def test_practical_tier_baseline_prompt_includes_all_blocks(self) -> None:
        for task in get_large_contextual_tasks(TASK_TIER_PRACTICAL):
            route = select_relevant_block(task)
            prompt = build_prompt(task, "baseline", route)

            for block in task.blocks:
                self.assertIn(f"BLOCK {block.block_id}", prompt)

    def test_high_context_tier_baseline_prompt_includes_all_blocks(self) -> None:
        for task in get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT):
            route = select_relevant_block(task)
            prompt = build_prompt(task, "baseline", route)

            for block in task.blocks:
                self.assertIn(f"BLOCK {block.block_id}", prompt)

    def test_structural_tier_baseline_prompt_includes_all_blocks(self) -> None:
        for task in get_large_contextual_tasks(TASK_TIER_STRUCTURAL):
            route = select_relevant_block(task)
            prompt = build_prompt(task, "baseline", route)

            for block in task.blocks:
                self.assertIn(f"BLOCK {block.block_id}", prompt)

    def test_spatial_prompt_includes_only_selected_block(self) -> None:
        for task in get_large_contextual_tasks():
            route = select_relevant_block(task)
            prompt = build_prompt(task, "spatial", route)

            self.assertIn(f"BLOCK {route['selected_block_id']}", prompt)
            for block in task.blocks:
                if block.block_id != route["selected_block_id"]:
                    self.assertNotIn(f"BLOCK {block.block_id}", prompt)
            self.assertLess(
                estimate_tokens(prompt),
                estimate_tokens(build_prompt(task, "baseline", route)),
            )

    def test_practical_tier_spatial_prompt_includes_only_selected_block(self) -> None:
        for task in get_large_contextual_tasks(TASK_TIER_PRACTICAL):
            route = select_relevant_block(task)
            prompt = build_prompt(task, "spatial", route)

            self.assertIn(f"BLOCK {route['selected_block_id']}", prompt)
            for block in task.blocks:
                if block.block_id != route["selected_block_id"]:
                    self.assertNotIn(f"BLOCK {block.block_id}", prompt)

    def test_high_context_tier_spatial_prompt_includes_only_selected_block(self) -> None:
        for task in get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT):
            route = select_relevant_block(task)
            prompt = build_prompt(task, "spatial", route)

            self.assertIn(f"BLOCK {route['selected_block_id']}", prompt)
            for block in task.blocks:
                if block.block_id != route["selected_block_id"]:
                    self.assertNotIn(f"BLOCK {block.block_id}", prompt)

    def test_structural_tier_spatial_prompt_includes_only_selected_block(self) -> None:
        for task in get_large_contextual_tasks(TASK_TIER_STRUCTURAL):
            route = select_relevant_block(task)
            prompt = build_prompt(task, "spatial", route)

            self.assertIn(f"BLOCK {route['selected_block_id']}", prompt)
            for block in task.blocks:
                if block.block_id != route["selected_block_id"]:
                    self.assertNotIn(f"BLOCK {block.block_id}", prompt)

    def test_dry_run_report_is_serializable_and_compares_modes(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
        )

        json.dumps(report, sort_keys=True)
        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["executor"], "lemonade")
        self.assertEqual(report["metadata"]["selection_mode"], "fixture")
        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_STANDARD)
        self.assertEqual(report["metadata"]["provider_call_delay_seconds"], 0.0)
        self.assertEqual(report["metadata"]["task_count"], len(get_large_contextual_tasks()))
        self.assertEqual(report["summary"]["modes"]["baseline"]["run_count"], len(get_large_contextual_tasks()))
        self.assertEqual(
            report["summary"]["modes"]["spatial"]["run_count"],
            len(get_large_contextual_tasks()),
        )
        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial"})
        self.assertTrue(report["summary"]["context_reduction_verified"])
        self.assertGreater(report["summary"]["token_reduction_percent"], 0)
        self.assertIn(FINAL_PHASE_CONCLUSION, report["summary"]["final_phase_conclusion"])
        for run in report["runs"]:
            self.assertEqual(run["benchmark_type"], BENCHMARK_TYPE)
            self.assertEqual(run["executor"], "lemonade")
            self.assertEqual(run["router"], "fixture_relevance_router")
            self.assertIn(run["mode"], {"baseline", "spatial"})
            self.assertIn("input_tokens", run)
            self.assertIn("output_tokens", run)
            self.assertIn("total_tokens", run)

    def test_openai_api_dry_run_uses_same_fixture_modes_and_metadata(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks()[:1],
            repeat=1,
            model="example-openai-executor",
            dry_run=True,
            selection_mode="both",
            executor=OPENAI_API_EXECUTOR,
            router_model="example-openai-router",
        )

        self.assertEqual(report["metadata"]["executor"], "openai-api")
        self.assertEqual(report["metadata"]["router"], "dry_run_fixture_block_selector")
        self.assertEqual(report["metadata"]["executor_model"], "example-openai-executor")
        self.assertEqual(report["metadata"]["router_model"], "example-openai-router")
        self.assertEqual(
            [task["task_label"] for task in report["tasks"]],
            [get_large_contextual_tasks()[0].task_label],
        )
        self.assertEqual(
            set(report["summary"]["modes"]),
            {"baseline", "spatial_fixture", "spatial_router"},
        )
        for run in report["runs"]:
            self.assertEqual(run["executor"], "openai-api")
            self.assertEqual(run["provider"], "openai-api")

    def test_openai_api_cli_uses_openai_env_defaults_and_report_paths(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_OPENAI_EXECUTOR_MODEL": "env-openai-executor",
                "SFE_OPENAI_ROUTER_MODEL": "env-openai-router",
                "OPENAI_BASE_URL": "https://api.example.test/v1",
            },
            clear=True,
        ), patch.object(
            sys,
            "argv",
            ["run_large_contextual_benchmark.py", "--executor", "openai-api", "--dry-run"],
        ):
            args = _parse_args()

        self.assertEqual(args.executor, "openai-api")
        self.assertEqual(args.model, "env-openai-executor")
        self.assertEqual(args.router_model, "env-openai-router")
        self.assertEqual(args.base_url, "https://api.example.test/v1")
        self.assertEqual(args.json, OPENAI_API_JSON_PATH)

    def test_cli_accepts_provider_call_delay_seconds(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "run_large_contextual_benchmark.py",
                "--dry-run",
                "--provider-call-delay-seconds",
                "1.5",
            ],
        ):
            args = _parse_args()

        self.assertEqual(args.provider_call_delay_seconds, 1.5)

    def test_provider_call_delay_sleeps_between_live_provider_calls(self) -> None:
        task = get_large_contextual_tasks()[:1][0]
        fixture_block_id = str(select_relevant_block(task)["selected_block_id"])
        sleep_calls: list[float] = []

        class FakeProvider:
            def __init__(self, base_url: str) -> None:
                self.base_url = base_url
                self.timeout = None

            def chat(self, messages, *_: object, **__: object) -> dict[str, object]:  # type: ignore[no-untyped-def]
                prompt = str(messages[0]["content"])
                if "Return JSON only" in prompt:
                    content = json.dumps(
                        {
                            "selected_block_id": fixture_block_id,
                            "confidence": 1.0,
                            "reason": "contains requested values",
                        }
                    )
                else:
                    content = " ".join(task.expected_answer_hints)
                return {
                    "choices": [{"message": {"content": content}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                }

        with patch(
            "runtime.run_large_contextual_benchmark.LemonadeProvider",
            FakeProvider,
        ):
            report = run_benchmark(
                tasks=[task],
                repeat=1,
                model="fake-lemonade-model",
                base_url="http://localhost:8000/api/v0",
                dry_run=False,
                selection_mode="both",
                provider_call_delay_seconds=1.25,
                sleep_func=sleep_calls.append,
            )

        self.assertEqual(sleep_calls, [1.25, 1.25, 1.25])
        self.assertEqual(report["metadata"]["provider_call_delay_seconds"], 1.25)
        self.assertEqual(
            set(report["summary"]["modes"]),
            {"baseline", "spatial_fixture", "spatial_router"},
        )

    def test_provider_call_delay_does_not_sleep_in_dry_run(self) -> None:
        sleep_calls: list[float] = []

        report = run_benchmark(
            tasks=get_large_contextual_tasks()[:1],
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="both",
            provider_call_delay_seconds=2.0,
            sleep_func=sleep_calls.append,
        )

        self.assertEqual(sleep_calls, [])
        self.assertEqual(report["metadata"]["provider_call_delay_seconds"], 2.0)

    def test_openai_api_provider_path_is_constructed_without_network_in_tests(self) -> None:
        class FakeOpenAIProvider:
            def __init__(self, base_url: str, timeout: float) -> None:
                self.base_url = base_url
                self.timeout = timeout
                self.calls = 0

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                self.calls += 1
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "cache key region code Priya Nair pay-ops"
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                }

        providers: list[FakeOpenAIProvider] = []

        def make_provider(base_url: str, timeout: float) -> FakeOpenAIProvider:
            provider = FakeOpenAIProvider(base_url, timeout)
            providers.append(provider)
            return provider

        with patch(
            "runtime.run_large_contextual_benchmark.OpenAIAPIProvider",
            side_effect=make_provider,
        ):
            report = run_benchmark(
                tasks=get_large_contextual_tasks()[:1],
                repeat=1,
                model="example-openai-executor",
                base_url="https://api.example.test/v1",
                timeout_seconds=7,
                dry_run=False,
                selection_mode="fixture",
                executor=OPENAI_API_EXECUTOR,
            )

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].base_url, "https://api.example.test/v1")
        self.assertEqual(providers[0].timeout, 7)
        self.assertEqual(providers[0].calls, 2)
        self.assertEqual(report["metadata"]["executor"], "openai-api")
        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial"})
        for run in report["runs"]:
            self.assertEqual(run["provider"], "openai-api")

    def test_anthropic_dry_run_uses_same_fixture_modes_and_metadata(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks()[:1],
            repeat=1,
            model="example-anthropic-executor",
            dry_run=True,
            selection_mode="both",
            executor=ANTHROPIC_EXECUTOR,
            router_model="example-anthropic-router",
        )

        self.assertEqual(report["metadata"]["executor"], "anthropic")
        self.assertEqual(report["metadata"]["provider"], "anthropic")
        self.assertEqual(report["metadata"]["api_style"], "anthropic_messages")
        self.assertEqual(report["metadata"]["router"], "dry_run_fixture_block_selector")
        self.assertEqual(report["metadata"]["executor_model"], "example-anthropic-executor")
        self.assertEqual(report["metadata"]["router_model"], "example-anthropic-router")
        self.assertEqual(
            set(report["summary"]["modes"]),
            {"baseline", "spatial_fixture", "spatial_router"},
        )
        for run in report["runs"]:
            self.assertEqual(run["executor"], "anthropic")
            self.assertEqual(run["provider"], "anthropic")

    def test_anthropic_cli_uses_env_defaults_and_report_paths(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_ANTHROPIC_EXECUTOR_MODEL": "env-anthropic-executor",
                "SFE_ANTHROPIC_ROUTER_MODEL": "env-anthropic-router",
                "ANTHROPIC_BASE_URL": "https://api.anthropic.example",
            },
            clear=True,
        ), patch.object(
            sys,
            "argv",
            ["run_large_contextual_benchmark.py", "--executor", "anthropic", "--dry-run"],
        ):
            args = _parse_args()

        self.assertEqual(args.executor, "anthropic")
        self.assertEqual(args.model, "env-anthropic-executor")
        self.assertEqual(args.router_model, "env-anthropic-router")
        self.assertEqual(args.base_url, "https://api.anthropic.example")
        self.assertEqual(args.json, ANTHROPIC_JSON_PATH)

    def test_anthropic_provider_path_is_constructed_without_network_in_tests(self) -> None:
        class FakeAnthropicProvider:
            def __init__(self, base_url: str, timeout: float) -> None:
                self.base_url = base_url
                self.timeout = timeout
                self.calls = 0

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                self.calls += 1
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "cache key region code Priya Nair pay-ops"
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                }

        providers: list[FakeAnthropicProvider] = []

        def make_provider(base_url: str, timeout: float) -> FakeAnthropicProvider:
            provider = FakeAnthropicProvider(base_url, timeout)
            providers.append(provider)
            return provider

        with patch(
            "runtime.run_large_contextual_benchmark.AnthropicProvider",
            side_effect=make_provider,
        ):
            report = run_benchmark(
                tasks=get_large_contextual_tasks()[:1],
                repeat=1,
                model="example-anthropic-executor",
                base_url="https://api.anthropic.example",
                timeout_seconds=7,
                dry_run=False,
                selection_mode="fixture",
                executor=ANTHROPIC_EXECUTOR,
            )

        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].base_url, "https://api.anthropic.example")
        self.assertEqual(providers[0].timeout, 7)
        self.assertEqual(providers[0].calls, 2)
        self.assertEqual(report["metadata"]["executor"], "anthropic")
        self.assertEqual(report["metadata"]["api_style"], "anthropic_messages")
        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial"})
        for run in report["runs"]:
            self.assertEqual(run["provider"], "anthropic")

    def test_alibaba_api_cli_uses_env_defaults_and_report_paths(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_ALIBABA_EXECUTOR_MODEL": "env-alibaba-executor",
                "SFE_ALIBABA_ROUTER_MODEL": "env-alibaba-router",
                "ALIBABA_BASE_URL": "https://dashscope.example.test/compatible-mode/v1",
            },
            clear=True,
        ), patch.object(
            sys,
            "argv",
            ["run_large_contextual_benchmark.py", "--executor", "alibaba-api", "--dry-run"],
        ):
            args = _parse_args()

        self.assertEqual(args.executor, "alibaba-api")
        self.assertEqual(args.model, "env-alibaba-executor")
        self.assertEqual(args.router_model, "env-alibaba-router")
        self.assertEqual(args.base_url, "https://dashscope.example.test/compatible-mode/v1")
        self.assertEqual(args.json, ALIBABA_API_JSON_PATH)

    def test_alibaba_api_provider_path_is_constructed_without_network_in_tests(self) -> None:
        class FakeAlibabaProvider:
            def __init__(self, base_url: str, timeout: float) -> None:
                self.base_url = base_url
                self.timeout = timeout
                self.calls = 0

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                self.calls += 1
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "cache key region code Priya Nair pay-ops"
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 4,
                        "total_tokens": 14,
                    },
                }

        providers: list[FakeAlibabaProvider] = []

        def make_provider(base_url: str, timeout: float) -> FakeAlibabaProvider:
            provider = FakeAlibabaProvider(base_url, timeout)
            providers.append(provider)
            return provider

        with patch(
            "runtime.run_large_contextual_benchmark.AlibabaAPIProvider",
            side_effect=make_provider,
        ):
            report = run_benchmark(
                tasks=get_large_contextual_tasks()[:1],
                repeat=1,
                model="example-alibaba-executor",
                base_url="https://dashscope.example.test/compatible-mode/v1",
                timeout_seconds=7,
                dry_run=False,
                selection_mode="fixture",
                executor=ALIBABA_API_EXECUTOR,
            )

        self.assertEqual(len(providers), 1)
        self.assertEqual(
            providers[0].base_url,
            "https://dashscope.example.test/compatible-mode/v1",
        )
        self.assertEqual(providers[0].timeout, 7)
        self.assertEqual(providers[0].calls, 2)
        self.assertEqual(report["metadata"]["executor"], "alibaba-api")
        self.assertEqual(report["metadata"]["api_style"], "openai_compatible_chat")
        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial"})
        for run in report["runs"]:
            self.assertEqual(run["provider"], "alibaba-api")

    def test_practical_tier_dry_run_fixture_report_is_serializable(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_PRACTICAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            task_tier=TASK_TIER_PRACTICAL,
        )

        json.dumps(report, sort_keys=True)
        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_PRACTICAL)
        self.assertEqual(report["metadata"]["task_count"], len(get_large_contextual_tasks(TASK_TIER_PRACTICAL)))
        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial"})
        self.assertTrue(report["summary"]["context_reduction_verified"])
        self.assertGreater(report["summary"]["token_reduction_percent"], 0)

    def test_practical_tier_dry_run_both_mode_uses_simulated_router(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_PRACTICAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="both",
            task_tier=TASK_TIER_PRACTICAL,
        )

        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_PRACTICAL)
        self.assertEqual(
            set(report["summary"]["modes"]),
            {"baseline", "spatial_fixture", "spatial_router"},
        )
        self.assertEqual(
            report["summary"]["router_selection"]["run_count"],
            len(get_large_contextual_tasks(TASK_TIER_PRACTICAL)),
        )
        self.assertEqual(report["summary"]["router_selection"]["match_rate"], 1.0)
        for run in report["runs"]:
            if run["mode"] == "spatial_router":
                self.assertEqual(run["router"], "dry_run_fixture_block_selector")
                self.assertTrue(run["router_selection_matches_fixture"])
                self.assertIsNone(run["selection_verification_required"])
                self.assertFalse(run["output_validation_required"])
                self.assertIsNone(run["output_validation_status"])

    def test_high_context_tier_dry_run_fixture_report_is_serializable(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            task_tier=TASK_TIER_HIGH_CONTEXT,
        )

        json.dumps(report, sort_keys=True)
        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_HIGH_CONTEXT)
        self.assertEqual(
            report["metadata"]["task_count"],
            len(get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT)),
        )
        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial"})
        self.assertTrue(report["summary"]["context_reduction_verified"])
        self.assertGreater(report["summary"]["token_reduction_percent"], 0)

    def test_high_context_tier_dry_run_both_mode_uses_simulated_router(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="both",
            task_tier=TASK_TIER_HIGH_CONTEXT,
        )

        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_HIGH_CONTEXT)
        self.assertEqual(
            set(report["summary"]["modes"]),
            {"baseline", "spatial_fixture", "spatial_router"},
        )
        self.assertEqual(
            report["summary"]["router_selection"]["run_count"],
            len(get_large_contextual_tasks(TASK_TIER_HIGH_CONTEXT)),
        )
        self.assertEqual(report["summary"]["router_selection"]["match_rate"], 1.0)
        for run in report["runs"]:
            if run["mode"] == "spatial_router":
                self.assertEqual(run["router"], "dry_run_fixture_block_selector")
                self.assertTrue(run["router_selection_matches_fixture"])
                self.assertIsNone(run["selection_verification_required"])
                self.assertFalse(run["output_validation_required"])
                self.assertIsNone(run["output_validation_status"])

    def test_structural_tier_dry_run_fixture_report_is_serializable(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            task_tier=TASK_TIER_STRUCTURAL,
        )

        json.dumps(report, sort_keys=True)
        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_STRUCTURAL)
        self.assertEqual(report["metadata"]["task_count"], 1)
        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial"})
        self.assertTrue(report["summary"]["context_reduction_verified"])
        self.assertGreater(report["summary"]["token_reduction_percent"], 0)

    def test_structural_tier_dry_run_both_mode_uses_simulated_router(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="both",
            task_tier=TASK_TIER_STRUCTURAL,
        )

        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_STRUCTURAL)
        self.assertEqual(
            set(report["summary"]["modes"]),
            {"baseline", "spatial_fixture", "spatial_router"},
        )
        self.assertEqual(report["summary"]["router_selection"]["run_count"], 1)
        self.assertEqual(report["summary"]["router_selection"]["match_rate"], 1.0)
        self.assertEqual(
            report["summary"]["router_selection"]["verification_required_count"],
            1,
        )
        self.assertEqual(
            report["summary"]["router_selection"]["verified_complete_count"],
            1,
        )
        self.assertEqual(
            report["summary"]["router_selection"]["verified_incomplete_count"],
            0,
        )
        self.assertEqual(report["summary"]["output_validation"]["required_count"], 3)
        self.assertEqual(report["summary"]["output_validation"]["complete_count"], 3)
        self.assertEqual(report["summary"]["output_validation"]["incomplete_count"], 0)
        self.assertEqual(report["summary"]["output_validation"]["complete_rate"], 1.0)
        reliability_cost = report["summary"]["structural_reliability_cost"]
        self.assertTrue(reliability_cost["raw_executor_success"])
        self.assertTrue(reliability_cost["repaired_success"])
        self.assertTrue(reliability_cost["router_success"])
        self.assertFalse(reliability_cost["selector_fallback_used"])
        self.assertTrue(reliability_cost["verified_selection_complete"])
        self.assertTrue(reliability_cost["output_validation_complete"])
        self.assertFalse(reliability_cost["output_repair_required"])
        self.assertTrue(reliability_cost["honest_structural_pass"])
        self.assertFalse(reliability_cost["honest_structural_pass_after_repair"])
        self.assertEqual(reliability_cost["publication_gate"], "honest_structural_pass")
        for run in report["runs"]:
            self.assertTrue(run["output_validation_required"])
            self.assertEqual(run["output_validation_status"], "complete")
            self.assertTrue(run["output_contains_all_targets"])
            self.assertEqual(run["output_missing_targets"], [])
            self.assertEqual(run["output"], run["output_original"])
            self.assertEqual(run["output_final"], run["output_original"])
            self.assertEqual(run["output_final_source"], "original")
            self.assertEqual(run["output_repair_status"], "disabled")
            self.assertFalse(run["output_repair_attempted"])
            self.assertEqual(run["success_after_output_repair"], run["success"])
            if run["mode"] == "spatial_router":
                self.assertEqual(run["router"], "dry_run_fixture_block_selector")
                self.assertTrue(run["router_selection_matches_fixture"])
                self.assertTrue(run["selection_verification_required"])
                self.assertEqual(run["selection_verification_status"], "complete")
                self.assertTrue(run["selection_contains_all_targets"])
                self.assertEqual(run["selection_missing_targets"], [])

    def test_structural_executor_prompt_is_schema_first(self) -> None:
        task = get_large_contextual_tasks(TASK_TIER_STRUCTURAL)[0]
        route = select_relevant_block(task)
        prompt = build_prompt(
            task,
            "spatial_router",
            route,
            task_tier=TASK_TIER_STRUCTURAL,
        )

        self.assertIn("Structural answer format", prompt)
        self.assertIn("active_version", prompt)
        self.assertIn("rollback_threshold", prompt)
        self.assertIn("excluded_dataset", prompt)
        self.assertIn("final_approval_owner", prompt)
        self.assertIn("mitigation_label", prompt)
        self.assertIn("evidence_block_id", prompt)
        self.assertNotIn("validation target", prompt.lower())

    def test_non_structural_executor_prompt_does_not_use_structural_schema(self) -> None:
        task = get_large_contextual_tasks(TASK_TIER_STANDARD)[0]
        route = select_relevant_block(task)
        prompt = build_prompt(task, "spatial_router", route, task_tier=TASK_TIER_STANDARD)

        self.assertNotIn("Structural answer format", prompt)
        self.assertNotIn("active_version", prompt)

    def test_selection_verification_is_disabled_for_non_structural_tiers(self) -> None:
        for tier in (TASK_TIER_STANDARD, TASK_TIER_PRACTICAL, TASK_TIER_HIGH_CONTEXT):
            report = run_benchmark(
                tasks=get_large_contextual_tasks(tier)[:1],
                repeat=1,
                model="fake-lemonade-model",
                dry_run=True,
                selection_mode="both",
                task_tier=tier,
            )

            self.assertFalse(report["metadata"]["selection_verification"]["enabled"])
            self.assertFalse(report["metadata"]["output_validation"]["enabled"])
            self.assertEqual(
                report["summary"]["router_selection"]["verification_required_count"],
                0,
            )
            self.assertEqual(report["summary"]["output_validation"]["required_count"], 0)
            self.assertNotIn("structural_reliability_cost", report["summary"])
            router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
            self.assertIsNone(router_run["selection_verification_required"])
            self.assertIsNone(router_run["selection_verification_status"])
            self.assertIsNone(router_run["selection_contains_all_targets"])
            self.assertFalse(router_run["output_validation_required"])
            self.assertIsNone(router_run["output_validation_status"])
            self.assertEqual(router_run["output_repair_status"], "disabled")
            self.assertFalse(router_run["output_repair_attempted"])

    def test_non_structural_tiers_do_not_repair_when_enabled(self) -> None:
        class FixtureSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                return {
                    **fixture_route,
                    "router": "fixture_test_selector",
                    "router_selected_block_id": fixture_route["selected_block_id"],
                    "selection_source": "test",
                    "router_success": True,
                    "router_valid_selection": True,
                    "executor_used_fallback": False,
                    "router_selection_matches_fixture": True,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "",
                    "router_confidence": 1.0,
                    "router_reason": "fixture selection for non-structural repair test",
                }

        class CountingProvider:
            def __init__(self) -> None:
                self.calls = 0

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                self.calls += 1
                return {
                    "choices": [{"message": {"content": "intentionally incomplete"}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }

        for tier in (TASK_TIER_STANDARD, TASK_TIER_PRACTICAL, TASK_TIER_HIGH_CONTEXT):
            provider = CountingProvider()
            report = run_benchmark(
                tasks=get_large_contextual_tasks(tier)[:1],
                repeat=1,
                model="fake-lemonade-model",
                dry_run=False,
                selection_mode="router",
                task_tier=tier,
                provider=provider,  # type: ignore[arg-type]
                selector=FixtureSelector(),
                max_output_repairs=1,
            )

            router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
            self.assertFalse(report["metadata"]["output_repair"]["enabled"])
            self.assertEqual(provider.calls, 2)
            self.assertEqual(router_run["output_repair_status"], "disabled")
            self.assertFalse(router_run["output_repair_attempted"])
            self.assertEqual(router_run["output_final"], router_run["output_original"])
            self.assertEqual(router_run["success_after_output_repair"], router_run["success"])

    def test_structural_verifier_exposes_valid_but_incomplete_selection(self) -> None:
        class PartialStructuralSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                partial_block = next(
                    block for block in task.blocks if block.block_id == "sable-replay-catalog"
                )
                return {
                    **fixture_route,
                    "router": "partial_structural_selector",
                    "selected_block_id": partial_block.block_id,
                    "router_selected_block_id": partial_block.block_id,
                    "selected_block_title": partial_block.title,
                    "selection_source": "test",
                    "router_success": True,
                    "router_valid_selection": True,
                    "executor_used_fallback": False,
                    "router_selection_matches_fixture": False,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "",
                    "router_confidence": 0.7,
                    "router_reason": "contains replay dataset but not every required value",
                    "notes": "test selected partial structural block",
                }

        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="router",
            task_tier=TASK_TIER_STRUCTURAL,
            selector=PartialStructuralSelector(),
        )

        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        summary = report["summary"]["router_selection"]
        self.assertTrue(router_run["router_valid_selection"])
        self.assertFalse(router_run["router_selection_matches_fixture"])
        self.assertFalse(router_run["executor_used_fallback"])
        self.assertTrue(router_run["selection_verification_required"])
        self.assertEqual(router_run["selection_verification_status"], "incomplete")
        self.assertFalse(router_run["selection_contains_all_targets"])
        self.assertIn("SableReplay-144", router_run["selection_present_targets"])
        self.assertIn("42.7", router_run["selection_missing_targets"])
        self.assertIn("ATLAS_OWNER_S9", router_run["selection_missing_targets"])
        self.assertIn("mesh_s9_epoch_pin", router_run["selection_missing_targets"])
        self.assertIn("2026.08-s9", router_run["selection_missing_targets"])
        self.assertEqual(router_run["output_validation_status"], "complete")
        self.assertTrue(router_run["output_contains_all_targets"])
        self.assertEqual(router_run["output_repair_status"], "disabled")
        self.assertFalse(router_run["output_repair_attempted"])
        self.assertEqual(summary["verification_required_count"], 1)
        self.assertEqual(summary["verified_complete_count"], 0)
        self.assertEqual(summary["verified_incomplete_count"], 1)
        self.assertEqual(summary["verified_complete_rate"], 0.0)

    def test_structural_does_not_repair_when_selection_is_incomplete(self) -> None:
        class PartialStructuralSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                partial_block = next(
                    block for block in task.blocks if block.block_id == "sable-replay-catalog"
                )
                return {
                    **fixture_route,
                    "router": "partial_structural_selector",
                    "selected_block_id": partial_block.block_id,
                    "router_selected_block_id": partial_block.block_id,
                    "selected_block_title": partial_block.title,
                    "selection_source": "test",
                    "router_success": True,
                    "router_valid_selection": True,
                    "executor_used_fallback": False,
                    "router_selection_matches_fixture": False,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "",
                    "router_confidence": 0.7,
                    "router_reason": "contains replay dataset but not every required value",
                    "notes": "test selected partial structural block",
                }

        class MissingVersionProvider:
            def __init__(self) -> None:
                self.calls = 0

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                self.calls += 1
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "42.7 SableReplay-144 ATLAS_OWNER_S9 "
                                    "mesh_s9_epoch_pin"
                                )
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 8,
                        "total_tokens": 18,
                    },
                }

        provider = MissingVersionProvider()
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=False,
            selection_mode="router",
            task_tier=TASK_TIER_STRUCTURAL,
            provider=provider,  # type: ignore[arg-type]
            selector=PartialStructuralSelector(),
            max_output_repairs=1,
        )

        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        self.assertEqual(provider.calls, 2)
        self.assertEqual(router_run["selected_block_id"], "sable-replay-catalog")
        self.assertEqual(router_run["selection_verification_status"], "incomplete")
        self.assertEqual(router_run["output_validation_status"], "incomplete")
        self.assertEqual(
            router_run["output_repair_status"],
            "skipped_selection_incomplete",
        )
        self.assertFalse(router_run["output_repair_attempted"])
        self.assertFalse(router_run["executor_used_fallback"])
        self.assertEqual(router_run["output_final"], router_run["output_original"])
        self.assertNotEqual(router_run["selected_block_id"], router_run["fixture_selected_block_id"])

    def test_structural_honest_pass_is_false_when_selector_fallback_is_used(self) -> None:
        class FallbackSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                return {
                    **fixture_route,
                    "router": "fixture_fallback_after_router_error",
                    "router_selected_block_id": None,
                    "selection_source": "fixture_fallback_after_router_error",
                    "router_success": False,
                    "router_valid_selection": False,
                    "executor_used_fallback": True,
                    "router_selection_matches_fixture": False,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "selector failed",
                    "router_confidence": 0.0,
                    "router_reason": "Router failed; fell back to fixture-selected block.",
                    "notes": "test selector fallback",
                }

        class CompleteProvider:
            def chat(self, *_: object, **__: object) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    "active_version: 2026.08-s9\n"
                                    "rollback_threshold: 42.7 credits\n"
                                    "excluded_dataset: SableReplay-144\n"
                                    "final_approval_owner: ATLAS_OWNER_S9\n"
                                    "mitigation_label: mesh_s9_epoch_pin\n"
                                    "evidence_block_id: atlas-mesh-s9-final"
                                )
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                }

        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=False,
            selection_mode="router",
            task_tier=TASK_TIER_STRUCTURAL,
            provider=CompleteProvider(),  # type: ignore[arg-type]
            selector=FallbackSelector(),
        )

        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        reliability_cost = report["summary"]["structural_reliability_cost"]
        self.assertTrue(router_run["success"])
        self.assertTrue(router_run["selection_contains_all_targets"])
        self.assertEqual(router_run["output_validation_status"], "complete")
        self.assertFalse(reliability_cost["router_success"])
        self.assertTrue(reliability_cost["selector_fallback_used"])
        self.assertFalse(reliability_cost["honest_structural_pass"])
        self.assertFalse(reliability_cost["honest_structural_pass_after_repair"])

    def test_structural_honest_pass_is_false_when_router_fails_without_fallback(self) -> None:
        class FailedSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                return {
                    **fixture_route,
                    "router": "failed_test_selector",
                    "router_selected_block_id": fixture_route["selected_block_id"],
                    "selection_source": "test",
                    "router_success": False,
                    "router_valid_selection": False,
                    "executor_used_fallback": False,
                    "router_selection_matches_fixture": False,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "selector failed",
                    "router_confidence": 0.0,
                    "router_reason": "test selector failure",
                    "notes": "test failed selector without fallback",
                }

        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="router",
            task_tier=TASK_TIER_STRUCTURAL,
            selector=FailedSelector(),
        )

        reliability_cost = report["summary"]["structural_reliability_cost"]
        self.assertFalse(reliability_cost["router_success"])
        self.assertFalse(reliability_cost["selector_fallback_used"])
        self.assertTrue(reliability_cost["verified_selection_complete"])
        self.assertTrue(reliability_cost["output_validation_complete"])
        self.assertFalse(reliability_cost["honest_structural_pass"])

    def test_structural_complete_output_passes_output_validation(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="router",
            task_tier=TASK_TIER_STRUCTURAL,
        )

        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        self.assertTrue(report["metadata"]["output_validation"]["enabled"])
        self.assertTrue(router_run["selection_contains_all_targets"])
        self.assertEqual(router_run["output_validation_status"], "complete")
        self.assertTrue(router_run["output_contains_all_targets"])
        self.assertEqual(router_run["output_missing_targets"], [])

    def test_structural_output_missing_version_is_marked_incomplete_without_repair(self) -> None:
        class FixtureSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                return {
                    **fixture_route,
                    "router": "fixture_test_selector",
                    "router_selected_block_id": fixture_route["selected_block_id"],
                    "selection_source": "test",
                    "router_success": True,
                    "router_valid_selection": True,
                    "executor_used_fallback": False,
                    "router_selection_matches_fixture": True,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "",
                    "router_confidence": 1.0,
                    "router_reason": "fixture selection for output validation test",
                }

        class MissingVersionProvider:
            def __init__(self) -> None:
                self.calls = 0
                self.output = (
                    "The threshold is 42.7 credits, the excluded dataset is "
                    "SableReplay-144, final approval is ATLAS_OWNER_S9, and the "
                    "mitigation label is mesh_s9_epoch_pin."
                )

            def chat(self, *_: object, **__: object) -> dict[str, object]:
                self.calls += 1
                return {
                    "choices": [{"message": {"content": self.output}}],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 12,
                        "total_tokens": 22,
                    },
                }

        provider = MissingVersionProvider()
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=False,
            selection_mode="router",
            task_tier=TASK_TIER_STRUCTURAL,
            provider=provider,  # type: ignore[arg-type]
            selector=FixtureSelector(),
        )

        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        self.assertEqual(provider.calls, 2)
        self.assertTrue(router_run["selection_contains_all_targets"])
        self.assertFalse(router_run["executor_used_fallback"])
        self.assertFalse(router_run["success"])
        self.assertEqual(router_run["output"], provider.output)
        self.assertEqual(router_run["output_validation_status"], "incomplete")
        self.assertFalse(router_run["output_contains_all_targets"])
        self.assertIn("2026.08-s9", router_run["output_missing_targets"])
        self.assertNotIn("2026.08-s9", router_run["output"])
        self.assertEqual(router_run["output"], provider.output)
        self.assertEqual(router_run["output_original"], provider.output)
        self.assertEqual(router_run["output_final"], provider.output)
        self.assertEqual(router_run["output_final_source"], "original")
        self.assertEqual(router_run["output_repair_status"], "disabled")
        self.assertFalse(router_run["output_repair_attempted"])
        self.assertFalse(router_run["success_after_output_repair"])
        self.assertEqual(report["summary"]["output_validation"]["required_count"], 2)
        self.assertEqual(report["summary"]["output_validation"]["complete_count"], 0)
        self.assertEqual(report["summary"]["output_validation"]["incomplete_count"], 2)
        self.assertEqual(
            report["summary"]["output_validation"]["missing_target_counts"]["2026.08-s9"],
            2,
        )
        reliability_cost = report["summary"]["structural_reliability_cost"]
        self.assertTrue(reliability_cost["router_success"])
        self.assertFalse(reliability_cost["selector_fallback_used"])
        self.assertTrue(reliability_cost["verified_selection_complete"])
        self.assertFalse(reliability_cost["output_validation_complete"])
        self.assertFalse(reliability_cost["honest_structural_pass"])
        self.assertFalse(reliability_cost["honest_structural_pass_after_repair"])

    def test_structural_repairs_complete_selection_missing_version_once(self) -> None:
        class FixtureSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                return {
                    **fixture_route,
                    "router": "fixture_test_selector",
                    "router_selected_block_id": fixture_route["selected_block_id"],
                    "selection_source": "test",
                    "router_success": True,
                    "router_valid_selection": True,
                    "executor_used_fallback": False,
                    "router_selection_matches_fixture": True,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "",
                    "router_confidence": 1.0,
                    "router_reason": "fixture selection for output repair test",
                }

        class RepairingProvider:
            def __init__(self) -> None:
                self.calls = 0
                self.prompts: list[str] = []
                self.original_output = (
                    "The threshold is 42.7 credits, the excluded dataset is "
                    "SableReplay-144, final approval is ATLAS_OWNER_S9, and the "
                    "mitigation label is mesh_s9_epoch_pin."
                )
                self.repaired_output = (
                    "For active version 2026.08-s9, rollback applies at 42.7 "
                    "credits, SableReplay-144 is excluded, ATLAS_OWNER_S9 owns "
                    "final approval, and mesh_s9_epoch_pin must ship."
                )

            def chat(self, messages, *_: object, **__: object) -> dict[str, object]:  # type: ignore[no-untyped-def]
                self.calls += 1
                self.prompts.append(messages[0]["content"])
                content = self.repaired_output if self.calls == 3 else self.original_output
                return {
                    "choices": [{"message": {"content": content}}],
                    "usage": {
                        "prompt_tokens": 10 + self.calls,
                        "completion_tokens": 12 + self.calls,
                        "total_tokens": 22 + (2 * self.calls),
                    },
                }

        provider = RepairingProvider()
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=False,
            selection_mode="router",
            task_tier=TASK_TIER_STRUCTURAL,
            provider=provider,  # type: ignore[arg-type]
            selector=FixtureSelector(),
            max_output_repairs=1,
        )

        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        repair_prompt = provider.prompts[2]
        self.assertEqual(provider.calls, 3)
        self.assertEqual(router_run["selection_verification_status"], "complete")
        self.assertEqual(router_run["output_validation_status"], "incomplete")
        self.assertFalse(router_run["success"])
        self.assertTrue(router_run["success_after_output_repair"])
        self.assertEqual(router_run["output"], provider.original_output)
        self.assertEqual(router_run["output_original"], provider.original_output)
        self.assertEqual(router_run["output_repaired_text"], provider.repaired_output)
        self.assertEqual(router_run["output_final"], provider.repaired_output)
        self.assertEqual(router_run["output_final_source"], "repaired")
        self.assertEqual(router_run["output_repair_status"], "attempted_complete")
        self.assertTrue(router_run["output_repair_attempted"])
        self.assertEqual(router_run["output_repair_count"], 1)
        self.assertEqual(router_run["output_repair_missing_targets_before"], ["2026.08-s9"])
        self.assertEqual(router_run["output_repair_missing_targets_after"], [])
        self.assertTrue(router_run["output_repair_used_same_context"])
        self.assertEqual(router_run["output_repair_added_tokens"], 28)
        self.assertEqual(router_run["output_repair_prompt_tokens"], 13)
        self.assertEqual(router_run["output_repair_output_tokens"], 15)
        self.assertIsNone(router_run["output_repair_added_estimated_cost"])
        self.assertFalse(router_run["executor_used_fallback"])
        self.assertIn("Missing required targets JSON: [\"2026.08-s9\"]", repair_prompt)
        self.assertIn("Selected context block id: atlas-mesh-s9-final", repair_prompt)
        self.assertIn("2026.08-s9", repair_prompt)
        self.assertNotIn("Candidate blocks", repair_prompt)
        self.assertNotIn("sable-replay-catalog", repair_prompt)
        self.assertEqual(report["summary"]["output_repair"]["required_count"], 1)
        self.assertEqual(report["summary"]["output_repair"]["attempted_count"], 1)
        self.assertEqual(report["summary"]["output_repair"]["completed_count"], 1)
        self.assertEqual(report["summary"]["output_repair"]["incomplete_count"], 0)
        self.assertEqual(report["summary"]["output_repair"]["added_total_tokens"], 28)
        reliability_cost = report["summary"]["structural_reliability_cost"]
        self.assertEqual(reliability_cost["baseline_total_tokens"], 24.0)
        self.assertEqual(reliability_cost["spatial_router_total_tokens"], 29.0)
        self.assertEqual(reliability_cost["spatial_router_router_tokens"], 3.0)
        self.assertEqual(reliability_cost["spatial_router_executor_tokens"], 26.0)
        self.assertEqual(reliability_cost["output_repair_added_tokens"], 28.0)
        self.assertEqual(
            reliability_cost["spatial_router_total_tokens_after_repair"],
            57.0,
        )
        self.assertEqual(
            reliability_cost["tokens_saved_before_repair_vs_baseline"],
            -5.0,
        )
        self.assertEqual(
            reliability_cost["tokens_saved_after_repair_vs_baseline"],
            -33.0,
        )
        self.assertAlmostEqual(
            reliability_cost["token_reduction_before_repair_vs_baseline_pct"],
            -20.8333333333,
        )
        self.assertEqual(
            reliability_cost["token_reduction_after_repair_vs_baseline_pct"],
            -137.5,
        )
        self.assertEqual(reliability_cost["repair_token_tax"], 28.0)
        self.assertAlmostEqual(
            reliability_cost["repair_token_tax_pct_of_router_executor"],
            96.5517241379,
        )
        self.assertFalse(reliability_cost["success"])
        self.assertTrue(reliability_cost["success_after_output_repair"])
        self.assertFalse(reliability_cost["honest_structural_pass"])
        self.assertTrue(reliability_cost["honest_structural_pass_after_repair"])
        self.assertTrue(reliability_cost["output_repair_required"])

    def test_long_alias_dry_run_reports_practical_tier(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_LONG),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="both",
            task_tier=TASK_TIER_LONG,
        )

        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_PRACTICAL)
        self.assertEqual(report["summary"]["router_selection"]["match_rate"], 1.0)

    def test_both_mode_runs_fixture_and_router_spatial_modes(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks()[:1],
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="both",
        )

        self.assertEqual(
            set(report["summary"]["modes"]),
            {"baseline", "spatial_fixture", "spatial_router"},
        )
        self.assertEqual(report["metadata"]["selection_mode"], "both")
        self.assertEqual(report["metadata"]["task_tier"], TASK_TIER_STANDARD)
        self.assertEqual(report["summary"]["router_selection"]["run_count"], 1)
        self.assertEqual(report["summary"]["router_selection"]["match_rate"], 1.0)
        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        self.assertEqual(router_run["router_selected_block_id"], router_run["fixture_selected_block_id"])
        self.assertTrue(router_run["router_selection_matches_fixture"])
        self.assertIn("router_total_tokens", router_run)

    def test_router_mode_runs_baseline_and_router_spatial_modes(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks()[:1],
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="router",
        )

        self.assertEqual(set(report["summary"]["modes"]), {"baseline", "spatial_router"})
        self.assertEqual(report["summary"]["router_selection"]["run_count"], 1)
        self.assertTrue(report["summary"]["context_reduction_verified"])

    def test_selector_prompt_requires_exact_block_id_copying(self) -> None:
        task = get_large_contextual_tasks()[0]
        prompt = build_selector_prompt(task)

        self.assertIn("Copy selected_block_id exactly", prompt)
        self.assertIn("byte-for-byte", prompt)
        self.assertIn("Invalid block IDs count as router failure", prompt)
        self.assertIn("ID string only, without labels or prefixes", prompt)
        self.assertIn('not labels such as "block_id: ..."', prompt)
        for block in task.blocks:
            self.assertIn(f'- "{block.block_id}"', prompt)
            self.assertIn(block.block_id, prompt)

    def test_selector_prompt_emphasizes_answer_sufficiency(self) -> None:
        prompt = build_selector_prompt(get_large_contextual_tasks()[0])

        self.assertIn("answer every requested field", prompt)
        self.assertIn("Prefer answer sufficiency over topical similarity", prompt)
        self.assertIn("Inspect whether the block contains all requested values", prompt)
        self.assertIn("only lists required field names, schemas, checklists", prompt)
        self.assertIn("document completeness rules is not sufficient", prompt)
        self.assertIn("actual values requested by the question", prompt)
        self.assertIn("reason should cite the exact requested values", prompt)
        self.assertIn("Cite at least two exact values when possible", prompt)
        self.assertIn("Keep the reason to one short line", prompt)
        self.assertIn("only identify the incident, timeline, background", prompt)
        self.assertIn("lack the exact answer", prompt)

    def test_selector_prompt_warns_about_shared_distractor_vocabulary(self) -> None:
        prompt = build_selector_prompt(get_large_contextual_tasks()[0])

        self.assertIn("Distractor blocks may share the same keywords", prompt)
        self.assertIn("dates, people, incidents, and domain vocabulary", prompt)
        self.assertIn("Do not normalize, abbreviate, spell-correct, prefix, or invent block IDs", prompt)

    def test_router_match_accuracy_is_computed_from_selector_results(self) -> None:
        class WrongSelector:
            def select(self, task, fixture_route):  # type: ignore[no-untyped-def]
                wrong_block = next(
                    block for block in task.blocks if block.block_id != fixture_route["selected_block_id"]
                )
                return {
                    **fixture_route,
                    "router": "fake_wrong_selector",
                    "selected_block_id": wrong_block.block_id,
                    "router_selected_block_id": wrong_block.block_id,
                    "selected_block_title": wrong_block.title,
                    "selection_source": "test",
                    "router_success": True,
                    "router_valid_selection": True,
                    "executor_used_fallback": False,
                    "router_selection_matches_fixture": False,
                    "router_latency_ms": 1,
                    "router_input_tokens": 2,
                    "router_output_tokens": 1,
                    "router_total_tokens": 3,
                    "router_error": "",
                    "router_confidence": 0.4,
                    "router_reason": "intentional wrong selection",
                }

        report = run_benchmark(
            tasks=get_large_contextual_tasks()[:1],
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="router",
            selector=WrongSelector(),
        )

        self.assertEqual(report["summary"]["router_selection"]["match_rate"], 0.0)
        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        self.assertFalse(router_run["router_selection_matches_fixture"])
        self.assertFalse(router_run["executor_used_fallback"])

    def test_selector_output_parses_json_and_rejects_missing_block_id(self) -> None:
        parsed = parse_selector_output(
            '{"selected_block_id":"pay-ops","confidence":0.8,"reason":"best match"}'
        )

        self.assertEqual(parsed["selected_block_id"], "pay-ops")
        with self.assertRaisesRegex(ValueError, "selected_block_id"):
            parse_selector_output('{"confidence":0.8}')

    def test_invalid_router_block_id_falls_back_safely(self) -> None:
        class InvalidBlockProvider:
            def chat(self, *_: object, **__: object) -> dict[str, object]:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"selected_block_id":"not-a-block",'
                                    '"confidence":0.9,"reason":"bad id"}'
                                )
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13},
                }

        task = get_large_contextual_tasks()[0]
        fixture_route = select_relevant_block(task)
        selector = LemonadeBlockSelector(InvalidBlockProvider(), model="fake-router")  # type: ignore[arg-type]
        route = selector.select(task, fixture_route)

        self.assertFalse(route["router_success"])
        self.assertEqual(route["selected_block_id"], fixture_route["selected_block_id"])
        self.assertEqual(route["router_selected_block_id"], "not-a-block")
        self.assertFalse(route["router_valid_selection"])
        self.assertFalse(route["router_selection_matches_fixture"])
        self.assertTrue(route["executor_used_fallback"])
        self.assertIn("Invalid selected_block_id", route["router_error"])

    def test_invalid_json_router_output_falls_back_and_is_not_valid_match(self) -> None:
        class InvalidJsonProvider:
            def chat(self, *_: object, **__: object) -> dict[str, object]:
                return {
                    "choices": [{"message": {"content": "not json"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                }

        task = get_large_contextual_tasks()[0]
        fixture_route = select_relevant_block(task)
        selector = LemonadeBlockSelector(InvalidJsonProvider(), model="fake-router")  # type: ignore[arg-type]
        route = selector.select(task, fixture_route)

        self.assertFalse(route["router_success"])
        self.assertIsNone(route["router_selected_block_id"])
        self.assertFalse(route["router_valid_selection"])
        self.assertFalse(route["router_selection_matches_fixture"])
        self.assertTrue(route["executor_used_fallback"])

    def test_router_exception_falls_back_and_aggregate_reports_fallback(self) -> None:
        class FailingProvider:
            def chat(self, *_: object, **__: object) -> dict[str, object]:
                raise RuntimeError("router unavailable")

        task = get_large_contextual_tasks()[0]
        selector = LemonadeBlockSelector(FailingProvider(), model="fake-router")  # type: ignore[arg-type]
        report = run_benchmark(
            tasks=[task],
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="router",
            selector=selector,
        )

        router_run = next(run for run in report["runs"] if run["mode"] == "spatial_router")
        summary = report["summary"]["router_selection"]
        self.assertFalse(router_run["router_success"])
        self.assertTrue(router_run["executor_used_fallback"])
        self.assertTrue(router_run["success_with_fallback"])
        self.assertEqual(summary["success_rate"], 0.0)
        self.assertEqual(summary["valid_selection_rate"], 0.0)
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["fallback_rate"], 1.0)
        self.assertEqual(summary["match_rate"], 0.0)
        self.assertIsNone(summary["match_rate_valid_selections"])

    def test_markdown_report_includes_router_fallback_information(self) -> None:
        class FailingProvider:
            def chat(self, *_: object, **__: object) -> dict[str, object]:
                raise RuntimeError("router unavailable")

        report = run_benchmark(
            tasks=get_large_contextual_tasks()[:1],
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="router",
            selector=LemonadeBlockSelector(FailingProvider(), model="fake-router"),  # type: ignore[arg-type]
        )

        from runtime.run_large_contextual_benchmark import write_markdown

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Valid router selection rate: 0.00%", markdown)
        self.assertIn("Task tier: `standard`", markdown)
        self.assertIn("Fallback-assisted executor runs: 1", markdown)
        self.assertIn("## Router Details", markdown)
        self.assertIn(
            "| Task | Fixture block | Router block | Valid | Match | Fallback | Selection verification | Selection missing targets | Output validation | Output missing targets |",
            markdown,
        )
        self.assertIn("| `large_contextual_payments_failover`", markdown)
        self.assertIn("| False | False | True | n/a | n/a | n/a | n/a |", markdown)
        self.assertIn("router unavailable", markdown)
        self.assertIn("Router failed; fell back to fixture-selected block", markdown)
        self.assertNotIn("## Structural Reliability Cost", markdown)

    def test_structural_markdown_report_includes_reliability_cost(self) -> None:
        report = run_benchmark(
            tasks=get_large_contextual_tasks(TASK_TIER_STRUCTURAL),
            repeat=1,
            model="fake-lemonade-model",
            dry_run=True,
            selection_mode="both",
            task_tier=TASK_TIER_STRUCTURAL,
        )

        from runtime.run_large_contextual_benchmark import write_markdown

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "report.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("## Structural Reliability Cost", markdown)
        self.assertIn("| Baseline total tokens |", markdown)
        self.assertIn("| Spatial router total tokens |", markdown)
        self.assertIn("| Spatial router total tokens after repair |", markdown)
        self.assertIn("| Repair token tax pct of router+executor |", markdown)
        self.assertIn("| Honest structural pass | True |", markdown)
        self.assertIn("| Honest structural pass after repair | False |", markdown)
        self.assertIn("| Publication gate | `honest_structural_pass` |", markdown)
        self.assertIn("| Success after output repair |", markdown)

    def test_empty_task_set_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "At least one"):
            run_benchmark(
                tasks=[],
                repeat=1,
                model="fake-lemonade-model",
                dry_run=True,
            )


if __name__ == "__main__":
    unittest.main()
