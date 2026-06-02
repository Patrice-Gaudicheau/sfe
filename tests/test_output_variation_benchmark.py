"""Tests for the controlled output-variation benchmark."""

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

from runtime.run_output_variation_benchmark import (
    BENCHMARK_TYPE,
    DRY_RUN_NOTE,
    EXECUTOR_FIXTURE,
    FixtureOutputVariationExecutor,
    _parse_args,
    block_ids_for_mode,
    build_prompt,
    compare_pair,
    get_output_variation_tasks,
    output_unchanged_or_near_equal,
    run_benchmark,
    task_families,
    validate_output,
    write_markdown,
)


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

    def test_compare_pair_flags_output_increase_near_equal_total_reduction_and_offset(self) -> None:
        increased = compare_pair(
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

        self.assertTrue(increased["output_tokens_increased"])
        self.assertTrue(increased["total_tokens_reduced"])
        self.assertTrue(increased["output_expansion_offsets_input_reduction"])
        self.assertTrue(near_equal["output_unchanged_or_near_equal"])
        self.assertFalse(near_equal["output_tokens_reduced"])
        self.assertFalse(near_equal["output_tokens_increased"])
        self.assertFalse(fully_offset["total_tokens_reduced"])
        self.assertTrue(fully_offset["output_expansion_offsets_input_reduction"])
        self.assertTrue(output_unchanged_or_near_equal(100, 103))

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
        self.assertEqual(args.task_family, "patch_planning")
        self.assertEqual(args.limit, 1)
        self.assertEqual(args.json, Path("/tmp/out.json"))
        self.assertEqual(args.md, Path("/tmp/out.md"))

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


if __name__ == "__main__":
    unittest.main()
