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
    BENCHMARK_TYPE,
    FINAL_PHASE_CONCLUSION,
    LemonadeBlockSelector,
    OPENAI_API_EXECUTOR,
    OPENAI_API_JSON_PATH,
    TASK_TIER_HIGH_CONTEXT,
    TASK_TIER_LONG,
    TASK_TIER_PRACTICAL,
    TASK_TIER_STANDARD,
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
        self.assertIn("reason should cite the exact requested values", prompt)
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
        self.assertIn("| Task | Fixture block | Router block | Valid | Match | Fallback |", markdown)
        self.assertIn("| `large_contextual_payments_failover`", markdown)
        self.assertIn("| False | False | True |", markdown)
        self.assertIn("router unavailable", markdown)
        self.assertIn("Router failed; fell back to fixture-selected block", markdown)

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
