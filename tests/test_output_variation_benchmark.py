"""Tests for the controlled output-variation benchmark."""

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

from runtime.run_output_variation_benchmark import (
    BENCHMARK_TYPE,
    DRY_RUN_NOTE,
    EXECUTOR_FIXTURE,
    EXECUTOR_ANTHROPIC,
    EXECUTOR_ALIBABA_API,
    EXECUTOR_GOOGLE,
    ROUTER_SELECTION_NOTE,
    FixtureOutputVariationExecutor,
    SegmentSelectorOutputVariationSelector,
    SELECTION_SOURCE_FIXTURE,
    SELECTION_SOURCE_ROUTER,
    _parse_args,
    block_ids_for_mode,
    build_prompt,
    build_segment_selection_input,
    compare_pair,
    comparison_flags,
    get_output_variation_tasks,
    output_unchanged_or_near_equal,
    run_benchmark,
    task_families,
    validate_output,
    write_markdown,
)
from sfe.segment_selector import SegmentSelectionResult


class OutputVariationBenchmarkTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = get_output_variation_tasks()

    def test_fixture_integrity_covers_all_task_families(self) -> None:
        families = {task.family for task in self.tasks}

        self.assertEqual(families, set(task_families()))
        self.assertEqual(len(self.tasks), 5)
        for task in self.tasks:
            block_ids = [block.block_id for block in task.context_blocks]
            self.assertEqual(len(block_ids), len(set(block_ids)))
            self.assertTrue(task.selected_block_ids)
            self.assertTrue(set(task.selected_block_ids) <= set(block_ids))
            self.assertEqual(
                {block.block_id for block in task.context_blocks if block.selected},
                set(task.selected_block_ids),
            )
            self.assertIn("baseline", task.dry_run_outputs)
            self.assertIn("selected", task.dry_run_outputs)
            self.assertTrue(task.required_facts)
            self.assertTrue(task.format_markers)

    def test_baseline_prompt_includes_all_blocks_and_selected_prompt_only_selected_blocks(self) -> None:
        task = self.tasks[0]
        baseline_prompt = build_prompt(task, "baseline")
        selected_prompt = build_prompt(task, "selected")

        for block in task.context_blocks:
            self.assertIn(f"BLOCK {block.block_id}", baseline_prompt)
        for block_id in task.selected_block_ids:
            self.assertIn(f"BLOCK {block_id}", selected_prompt)
        for block in task.context_blocks:
            if block.block_id not in task.selected_block_ids:
                self.assertNotIn(f"BLOCK {block.block_id}", selected_prompt)
        self.assertEqual(block_ids_for_mode(task, "selected"), list(task.selected_block_ids))

    def test_prompt_includes_exact_required_labels_from_task_format_markers(self) -> None:
        task = self.tasks[0]
        prompt = build_prompt(task, "selected")

        self.assertIn("Required answer labels, copy exactly:", prompt)
        for marker in task.format_markers:
            self.assertIn(f"\n{marker}\n", prompt)

    def test_prompt_labels_are_derived_from_each_task_format_markers(self) -> None:
        for task in self.tasks:
            with self.subTest(family=task.family):
                prompt = build_prompt(task, "selected")
                marker_block = prompt.split("Required answer labels, copy exactly:\n", 1)[1]
                marker_block = marker_block.split("\n\nContext:", 1)[0]

                self.assertEqual(marker_block.splitlines(), list(task.format_markers))

    def test_dry_run_report_is_serializable_and_includes_metadata_caveat(self) -> None:
        report = run_benchmark(
            tasks=self.tasks,
            repeat=1,
            executor=FixtureOutputVariationExecutor(),
        )

        json.dumps(report, sort_keys=True)
        self.assertEqual(report["metadata"]["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(report["metadata"]["executor"], EXECUTOR_FIXTURE)
        self.assertTrue(report["metadata"]["dry_run"])
        self.assertTrue(report["metadata"]["dry_run_fixture_outputs"])
        self.assertEqual(report["metadata"]["dry_run_note"], DRY_RUN_NOTE)
        self.assertIn(DRY_RUN_NOTE, report["summary"]["notes"])
        self.assertFalse(report["metadata"]["router_used"])
        self.assertEqual(report["metadata"]["selection_source"], SELECTION_SOURCE_FIXTURE)
        self.assertEqual(report["metadata"]["comparison_count"], 5)
        self.assertEqual(len(report["runs"]), 10)
        self.assertEqual(len(report["comparisons"]), 5)

    def test_compare_pair_calculates_output_delta_ratio_and_reduction_flags(self) -> None:
        comparison = compare_pair(
            {
                "task_label": "task",
                "family": "ambiguous_diagnostic",
                "repeat_index": 1,
                "input_tokens": 100,
                "output_tokens": 20,
                "total_tokens": 120,
                "success": True,
                "compactness_score": 0.1,
            },
            {
                "task_label": "task",
                "family": "ambiguous_diagnostic",
                "repeat_index": 1,
                "input_tokens": 40,
                "output_tokens": 10,
                "total_tokens": 50,
                "success": True,
                "compactness_score": 0.2,
            },
        )

        self.assertEqual(comparison["input_delta"], -60)
        self.assertEqual(comparison["output_delta"], -10)
        self.assertEqual(comparison["output_ratio"], 0.5)
        self.assertEqual(comparison["total_delta"], -70)
        self.assertAlmostEqual(comparison["input_reduction_percent"], 60.0)
        self.assertAlmostEqual(comparison["total_reduction_percent"], 58.333333333)
        self.assertTrue(comparison["output_tokens_reduced"])
        self.assertFalse(comparison["output_tokens_increased"])
        self.assertFalse(comparison["output_unchanged_or_near_equal"])
        self.assertTrue(comparison["total_tokens_reduced"])
        self.assertFalse(comparison["output_expansion_offsets_input_reduction"])
        self.assertFalse(
            comparison["output_expansion_partially_offsets_input_reduction"]
        )
        self.assertFalse(comparison["output_expansion_fully_offsets_input_reduction"])

    def test_compare_pair_flags_output_increase_near_equal_total_reduction_and_offset(self) -> None:
        partial_offset = compare_pair(
            _run_tokens(output_tokens=10, total_tokens=110),
            _run_tokens(input_tokens=40, output_tokens=30, total_tokens=70),
        )
        near_equal = compare_pair(
            _run_tokens(output_tokens=100, total_tokens=200),
            _run_tokens(input_tokens=70, output_tokens=103, total_tokens=173),
        )
        fully_offset = compare_pair(
            _run_tokens(output_tokens=10, total_tokens=110),
            _run_tokens(input_tokens=40, output_tokens=120, total_tokens=160),
        )

        self.assertTrue(partial_offset["output_tokens_increased"])
        self.assertTrue(partial_offset["total_tokens_reduced"])
        self.assertTrue(partial_offset["output_expansion_offsets_input_reduction"])
        self.assertTrue(
            partial_offset["output_expansion_partially_offsets_input_reduction"]
        )
        self.assertFalse(partial_offset["output_expansion_fully_offsets_input_reduction"])
        self.assertTrue(near_equal["output_unchanged_or_near_equal"])
        self.assertFalse(near_equal["output_tokens_reduced"])
        self.assertFalse(near_equal["output_tokens_increased"])
        self.assertTrue(near_equal["output_expansion_offsets_input_reduction"])
        self.assertTrue(
            near_equal["output_expansion_partially_offsets_input_reduction"]
        )
        self.assertFalse(near_equal["output_expansion_fully_offsets_input_reduction"])
        self.assertFalse(fully_offset["total_tokens_reduced"])
        self.assertTrue(fully_offset["output_expansion_offsets_input_reduction"])
        self.assertFalse(
            fully_offset["output_expansion_partially_offsets_input_reduction"]
        )
        self.assertTrue(fully_offset["output_expansion_fully_offsets_input_reduction"])
        self.assertTrue(output_unchanged_or_near_equal(100, 103))

    def test_comparison_flags_distinguish_partial_and_full_output_offset(self) -> None:
        partial_offset = compare_pair(
            _run_tokens(output_tokens=10, total_tokens=110),
            _run_tokens(input_tokens=40, output_tokens=30, total_tokens=70),
        )
        full_offset = compare_pair(
            _run_tokens(output_tokens=10, total_tokens=110),
            _run_tokens(input_tokens=40, output_tokens=120, total_tokens=160),
        )
        no_offset = compare_pair(
            _run_tokens(output_tokens=30, total_tokens=130),
            _run_tokens(input_tokens=40, output_tokens=20, total_tokens=60),
        )

        self.assertIn("output_partially_offsets_input", comparison_flags(partial_offset))
        self.assertNotIn("output_fully_offsets_input", comparison_flags(partial_offset))
        self.assertIn("output_fully_offsets_input", comparison_flags(full_offset))
        self.assertNotIn("output_partially_offsets_input", comparison_flags(full_offset))
        self.assertFalse(no_offset["output_expansion_offsets_input_reduction"])
        self.assertFalse(
            no_offset["output_expansion_partially_offsets_input_reduction"]
        )
        self.assertFalse(no_offset["output_expansion_fully_offsets_input_reduction"])

    def test_quality_checks_required_facts_forbidden_mentions_and_format(self) -> None:
        task = self.tasks[0]
        valid = validate_output(task, task.dry_run_outputs["selected"])
        missing_fact = validate_output(task, "Cause: cache. Owner: Priya Nair. Next action: flush.")
        forbidden = validate_output(task, task.dry_run_outputs["baseline"])
        bad_format = validate_output(
            task,
            "stale PSP routing cache Priya Nair pay-cache-17",
        )

        self.assertTrue(valid["success"])
        self.assertFalse(missing_fact["required_facts_present"])
        self.assertIn("pay-cache-17", missing_fact["missing_required_facts"])
        self.assertFalse(forbidden["forbidden_mentions_absent"])
        self.assertIn("Mason Vale", forbidden["present_forbidden_mentions"])
        self.assertFalse(bad_format["format_respected"])
        self.assertIn("Cause:", bad_format["missing_format_markers"])

    def test_quality_check_remains_strict_for_equivalent_cause_prose(self) -> None:
        task = self.tasks[0]
        equivalent_prose = (
            "Diagnostic Note: The checkout incident was caused by stale PSP routing "
            "cache entries. Owner: Priya Nair. Next Action: Flush the PSP routing "
            "cache and pin cache epoch pay-cache-17."
        )

        quality = validate_output(task, equivalent_prose)

        self.assertTrue(quality["required_facts_present"])
        self.assertTrue(quality["forbidden_mentions_absent"])
        self.assertFalse(quality["format_respected"])
        self.assertFalse(quality["success"])
        self.assertEqual(quality["missing_format_markers"], ["Cause:"])

    def test_markdown_report_includes_summary_quality_flags_and_dry_run_caveat(self) -> None:
        report = run_benchmark(
            tasks=self.tasks,
            repeat=1,
            executor=FixtureOutputVariationExecutor(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output_variation.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("# Output Variation Benchmark", markdown)
        self.assertIn("## Dry-Run Note", markdown)
        self.assertIn(DRY_RUN_NOTE, markdown)
        self.assertIn("## Summary By Task Family", markdown)
        self.assertIn("Selection source: `fixture`", markdown)
        self.assertIn("Router used: `False`", markdown)
        self.assertIn("Base in", markdown)
        self.assertIn("Selected out", markdown)
        self.assertIn("Output delta", markdown)
        self.assertIn("Quality base/selected", markdown)
        self.assertIn("## Interpretation", markdown)
        self.assertIn("bounded output control", markdown.lower())
        self.assertIn("not evidence that SFE reduces or increases output tokens", markdown)

    def test_cli_parses_dry_run_executor_task_family_limit_and_paths(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "run_output_variation_benchmark.py",
                "--dry-run",
                "--executor",
                "openai-api",
                "--selection-source",
                "fixture",
                "--task-family",
                "patch_planning",
                "--limit",
                "1",
                "--json",
                "/tmp/out.json",
                "--md",
                "/tmp/out.md",
            ],
        ):
            args = _parse_args()

        self.assertEqual(args.executor, EXECUTOR_FIXTURE)
        self.assertTrue(args.dry_run)
        self.assertEqual(args.selection_source, SELECTION_SOURCE_FIXTURE)
        self.assertEqual(args.task_family, "patch_planning")
        self.assertEqual(args.limit, 1)
        self.assertEqual(args.json, Path("/tmp/out.json"))
        self.assertEqual(args.md, Path("/tmp/out.md"))

    def test_cli_parses_anthropic_router_and_executor_env_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_ANTHROPIC_EXECUTOR_MODEL": "env-anthropic-executor",
                "SFE_ANTHROPIC_ROUTER_MODEL": "env-anthropic-router",
            },
            clear=True,
        ), patch.object(
            sys,
            "argv",
            [
                "run_output_variation_benchmark.py",
                "--executor",
                "anthropic",
                "--selection-source",
                "router",
            ],
        ):
            args = _parse_args()

        self.assertEqual(args.executor, EXECUTOR_ANTHROPIC)
        self.assertEqual(args.router_provider, "anthropic")
        self.assertEqual(args.model, "env-anthropic-executor")
        self.assertEqual(args.router_model, "env-anthropic-router")

    def test_cli_parses_alibaba_router_and_executor_env_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_ALIBABA_EXECUTOR_MODEL": "env-alibaba-executor",
                "SFE_ALIBABA_ROUTER_MODEL": "env-alibaba-router",
            },
            clear=True,
        ), patch.object(
            sys,
            "argv",
            [
                "run_output_variation_benchmark.py",
                "--executor",
                "alibaba-api",
                "--selection-source",
                "router",
            ],
        ):
            args = _parse_args()

        self.assertEqual(args.executor, EXECUTOR_ALIBABA_API)
        self.assertEqual(args.router_provider, "alibaba")
        self.assertEqual(args.model, "env-alibaba-executor")
        self.assertEqual(args.router_model, "env-alibaba-router")

    def test_cli_parses_google_router_and_executor_env_defaults(self) -> None:
        with patch.dict(
            os.environ,
            {"SFE_GOOGLE_MODEL": "env-google-model"},
            clear=True,
        ), patch.object(
            sys,
            "argv",
            [
                "run_output_variation_benchmark.py",
                "--executor",
                "google",
                "--selection-source",
                "router",
            ],
        ):
            args = _parse_args()

        self.assertEqual(args.executor, EXECUTOR_GOOGLE)
        self.assertEqual(args.router_provider, "google")
        self.assertEqual(args.model, "env-google-model")
        self.assertEqual(args.router_model, "env-google-model")

    def test_task_family_filter_can_run_single_family(self) -> None:
        selected = [task for task in self.tasks if task.family == "bounded_output_control"]
        report = run_benchmark(
            tasks=selected,
            repeat=1,
            executor=FixtureOutputVariationExecutor(),
        )

        self.assertEqual(report["metadata"]["task_count"], 1)
        self.assertEqual(set(report["summary"]["by_family"]), {"bounded_output_control"})
        comparison = report["comparisons"][0]
        self.assertTrue(comparison["output_unchanged_or_near_equal"])

    def test_cli_rejects_dry_run_with_router_selection_source(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "run_output_variation_benchmark.py",
                "--dry-run",
                "--selection-source",
                "router",
            ],
        ):
            with self.assertRaises(SystemExit):
                _parse_args()

    def test_cli_rejects_router_selection_with_fixture_executor(self) -> None:
        with patch.object(
            sys,
            "argv",
            [
                "run_output_variation_benchmark.py",
                "--selection-source",
                "router",
            ],
        ):
            with self.assertRaises(SystemExit):
                _parse_args()

    def test_segment_selection_input_uses_block_ids_as_candidate_segment_ids(self) -> None:
        task = self.tasks[0]
        selection_input = build_segment_selection_input(
            task,
            repeat_index=1,
            router_model="router-model",
        )

        self.assertEqual(selection_input.request_id, f"{task.task_label}:1")
        self.assertEqual(selection_input.model, "router-model")
        self.assertEqual(selection_input.metadata["benchmark_type"], BENCHMARK_TYPE)
        self.assertEqual(
            [segment.id for segment in selection_input.candidate_segments],
            [block.block_id for block in task.context_blocks],
        )
        self.assertIn("BLOCK payments-cache", selection_input.candidate_segments[0].text)

    def test_router_selection_source_uses_neutral_selector_selected_block_ids(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="candidate_selected",
            reason="fake_selected_context",
        )

        self.assertTrue(report["metadata"]["router_used"])
        self.assertEqual(report["metadata"]["selection_source"], SELECTION_SOURCE_ROUTER)
        self.assertIn(ROUTER_SELECTION_NOTE, report["summary"]["notes"])
        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_selected_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "candidate_selected")
        comparison = report["comparisons"][0]
        self.assertTrue(comparison["comparison_valid"])
        self.assertTrue(comparison["router_selection_usable"])
        self.assertEqual(comparison["router_provider"], "openai")

    def test_router_status_selected_with_valid_ids_is_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="selected",
            reason="live_router_selected_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_selected_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "selected")
        self.assertTrue(selected_run["router_selection_usable"])
        comparison = report["comparisons"][0]
        self.assertTrue(comparison["comparison_valid"])
        self.assertTrue(comparison["router_selection_usable"])

    def test_router_status_success_with_valid_ids_is_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="success",
            reason="live_router_success_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "success")
        self.assertTrue(selected_run["router_selection_usable"])
        self.assertTrue(report["comparisons"][0]["comparison_valid"])

    def test_router_status_eligible_with_valid_ids_is_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="eligible",
            reason="live_router_eligible_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "eligible")
        self.assertTrue(selected_run["router_selection_usable"])
        self.assertTrue(report["comparisons"][0]["comparison_valid"])

    def test_router_status_ok_with_valid_ids_is_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="ok",
            reason="live_router_ok_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "ok")
        self.assertTrue(selected_run["router_selection_usable"])
        self.assertTrue(report["comparisons"][0]["comparison_valid"])

    def test_router_status_approved_with_valid_ids_is_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="approved",
            reason="live_router_approved_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "approved")
        self.assertTrue(selected_run["router_selection_usable"])
        self.assertTrue(report["comparisons"][0]["comparison_valid"])

    def test_router_status_ready_with_valid_ids_is_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="ready",
            reason="live_router_ready_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "ready")
        self.assertTrue(selected_run["router_status_known"])
        self.assertTrue(selected_run["router_selection_usable"])
        self.assertTrue(report["comparisons"][0]["comparison_valid"])

    def test_arbitrary_unknown_router_status_with_valid_ids_is_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="arbitrary_unknown_status",
            reason="unknown_live_router_status",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(selected_run["execution_status"], "completed")
        self.assertEqual(selected_run["used_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_status"], "arbitrary_unknown_status")
        self.assertFalse(selected_run["router_status_known"])
        self.assertTrue(selected_run["router_selection_usable"])
        self.assertTrue(report["comparisons"][0]["comparison_valid"])

    def test_router_status_selected_with_unknown_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=["unknown-block"],
            status="selected",
            reason="live_router_selected_unknown_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], ["unknown-block"])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_status_success_with_unknown_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=["unknown-block"],
            status="success",
            reason="live_router_success_unknown_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], ["unknown-block"])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_status_ok_with_unknown_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=["unknown-block"],
            status="ok",
            reason="live_router_ok_unknown_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], ["unknown-block"])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_arbitrary_unknown_router_status_with_unknown_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=["unknown-block"],
            status="arbitrary_unknown_status",
            reason="unknown_live_router_status_unknown_context",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], ["unknown-block"])
        self.assertFalse(selected_run["router_status_known"])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_error_with_selected_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=["payments-cache"],
            status="selected",
            reason="router_provider_error",
            error_type="ProviderError",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], ["payments-cache"])
        self.assertEqual(selected_run["router_error_type"], "ProviderError")
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_error_with_success_or_eligible_is_not_usable(self) -> None:
        for status in ("success", "eligible"):
            with self.subTest(status=status):
                report = self._router_report(
                    selected_ids=["payments-cache"],
                    status=status,
                    reason="router_provider_error",
                    error_type="ProviderError",
                )

                selected_run = next(
                    run for run in report["runs"] if run["mode"] == "selected"
                )
                self.assertEqual(
                    selected_run["execution_status"],
                    "skipped_router_selection_unusable",
                )
                self.assertEqual(
                    selected_run["router_selected_block_ids"],
                    ["payments-cache"],
                )
                self.assertEqual(selected_run["router_status"], status)
                self.assertEqual(selected_run["router_error_type"], "ProviderError")
                self.assertFalse(selected_run["router_selection_usable"])
                self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_error_with_ok_or_approved_is_not_usable(self) -> None:
        for status in ("ok", "approved"):
            with self.subTest(status=status):
                report = self._router_report(
                    selected_ids=["payments-cache"],
                    status=status,
                    reason="router_provider_error",
                    error_type="ProviderError",
                )

                selected_run = next(
                    run for run in report["runs"] if run["mode"] == "selected"
                )
                self.assertEqual(
                    selected_run["execution_status"],
                    "skipped_router_selection_unusable",
                )
                self.assertEqual(
                    selected_run["router_selected_block_ids"],
                    ["payments-cache"],
                )
                self.assertEqual(selected_run["router_status"], status)
                self.assertEqual(selected_run["router_error_type"], "ProviderError")
                self.assertFalse(selected_run["router_selection_usable"])
                self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_error_with_any_status_is_not_usable(self) -> None:
        for status in ("ready", "arbitrary_unknown_status"):
            with self.subTest(status=status):
                report = self._router_report(
                    selected_ids=["payments-cache"],
                    status=status,
                    reason="router_provider_error",
                    error_type="ProviderError",
                )

                selected_run = next(
                    run for run in report["runs"] if run["mode"] == "selected"
                )
                self.assertEqual(
                    selected_run["execution_status"],
                    "skipped_router_selection_unusable",
                )
                self.assertEqual(
                    selected_run["router_selected_block_ids"],
                    ["payments-cache"],
                )
                self.assertEqual(selected_run["router_status"], status)
                self.assertEqual(selected_run["router_error_type"], "ProviderError")
                self.assertFalse(selected_run["router_selection_usable"])
                self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_empty_router_selected_ids_are_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=[],
            status="selected",
            reason="router_selection_empty",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], [])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_status_approved_with_empty_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=[],
            status="approved",
            reason="router_selection_empty",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], [])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_arbitrary_unknown_router_status_with_empty_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=[],
            status="arbitrary_unknown_status",
            reason="router_selection_empty",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], [])
        self.assertFalse(selected_run["router_status_known"])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_status_eligible_with_empty_ids_is_not_usable(self) -> None:
        report = self._router_report(
            selected_ids=[],
            status="eligible",
            reason="router_selection_empty",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertEqual(selected_run["router_selected_block_ids"], [])
        self.assertFalse(selected_run["router_selection_usable"])
        self.assertFalse(report["comparisons"][0]["comparison_valid"])

    def test_router_selection_failure_skips_selected_executor_and_invalidates_comparison(self) -> None:
        report = self._router_report(
            selected_ids=[],
            status="no_selection",
            reason="router_selection_empty",
        )

        selected_run = next(run for run in report["runs"] if run["mode"] == "selected")
        self.assertEqual(
            selected_run["execution_status"],
            "skipped_router_selection_unusable",
        )
        self.assertIsNone(selected_run["input_tokens"])
        self.assertFalse(selected_run["router_selection_usable"])
        comparison = report["comparisons"][0]
        self.assertFalse(comparison["comparison_valid"])
        self.assertEqual(comparison["comparison_invalid_reason"], "router_selection_empty")
        self.assertIsNone(comparison["output_delta"])
        self.assertEqual(report["summary"]["overall"]["invalid_comparison_count"], 1)
        self.assertEqual(report["summary"]["overall"]["valid_comparison_count"], 0)

    def test_markdown_report_includes_router_selection_note_and_router_summary(self) -> None:
        selector = SegmentSelectorOutputVariationSelector(
            provider="openai",
            selector=FakeSegmentSelector(
                selected_ids=["payments-cache"],
                provider="openai",
            ),
        )
        report = run_benchmark(
            tasks=[self.tasks[0]],
            repeat=1,
            executor=FixtureOutputVariationExecutor(),
            selector=selector,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "output_variation_router.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("Selection source: `router`", markdown)
        self.assertIn("Router used: `True`", markdown)
        self.assertIn("## Router Selection Note", markdown)
        self.assertIn(ROUTER_SELECTION_NOTE, markdown)
        self.assertIn("neutral SFE segment selector", markdown)
        self.assertNotIn("proxy shadow-router", markdown)
        self.assertIn(
            "candidate_selected; known=True; usable=True; selected=payments-cache",
            markdown,
        )

    def _router_report(
        self,
        *,
        selected_ids: list[str],
        status: str,
        reason: str,
        error_type: str | None = None,
    ) -> dict[str, object]:
        selector = SegmentSelectorOutputVariationSelector(
            provider="openai",
            selector=FakeSegmentSelector(
                selected_ids=selected_ids,
                provider="openai",
                status=status,
                reason=reason,
                error_type=error_type,
            ),
        )
        return run_benchmark(
            tasks=[self.tasks[0]],
            repeat=1,
            executor=FixtureOutputVariationExecutor(),
            selector=selector,
        )


def _run_tokens(
    *,
    input_tokens: int = 100,
    output_tokens: int = 10,
    total_tokens: int = 110,
) -> dict[str, object]:
    return {
        "task_label": "task",
        "family": "test_family",
        "repeat_index": 1,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "success": True,
        "compactness_score": 0.1,
    }


class FakeSegmentSelector:

    def __init__(
        self,
        *,
        selected_ids: list[str],
        provider: str,
        status: str = "candidate_selected",
        reason: str = "fake_selected_context",
        error_type: str | None = None,
    ) -> None:
        self.selected_ids = selected_ids
        self.provider_name = provider
        self.model = "fake-router-model"
        self.status = status
        self.reason = reason
        self.error_type = error_type
        self.calls: list[object] = []

    def select(self, selection_input: object) -> SegmentSelectionResult:
        self.calls.append(selection_input)
        return SegmentSelectionResult(
            selected_segment_ids=tuple(self.selected_ids),
            router_status=self.status,
            router_status_known=(
                self.status
                in {
                    "approved",
                    "candidate_selected",
                    "eligible",
                    "ok",
                    "ready",
                    "selected",
                    "select_segments",
                    "success",
                }
            ),
            reason=self.reason,
            provider_name=self.provider_name,
            model=self.model,
            confidence=0.91,
            error_type=self.error_type,
            latency_ms=7,
            estimated_selected_input_tokens=12 if self.selected_ids else None,
            estimated_token_reduction_pct=75.0 if self.selected_ids else None,
        )


if __name__ == "__main__":
    unittest.main()
