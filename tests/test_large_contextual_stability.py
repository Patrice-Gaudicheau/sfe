"""Tests for large/contextual stability aggregation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_large_contextual_stability import (
    DEFAULT_JSON_PATH,
    DEFAULT_MD_PATH,
    _parse_args,
    build_stability_report,
    write_markdown,
)


class LargeContextualStabilityTests(unittest.TestCase):
    def test_cli_defaults_read_loaded_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "SFE_LEMONADE_BASE_URL": "http://127.0.0.1:13305",
                "SFE_EXECUTOR_MODEL": "env-executor-model",
                "SFE_ROUTER_MODEL": "env-router-model",
            },
            clear=True,
        ), patch.object(
            sys,
            "argv",
            [
                "run_large_contextual_stability.py",
                "--iterations",
                "1",
                "--task-tier",
                "high_context",
                "--dry-run",
            ],
        ):
            args = _parse_args()

        self.assertEqual(args.base_url, "http://127.0.0.1:13305")
        self.assertEqual(args.model, "env-executor-model")
        self.assertEqual(args.router_model, "env-router-model")
        self.assertEqual(args.task_tier, "high_context")

    def test_default_report_paths_are_repo_root_based_for_cron(self) -> None:
        self.assertEqual(
            DEFAULT_JSON_PATH,
            PROJECT_ROOT / "logs" / "large_contextual_stability.json",
        )
        self.assertEqual(
            DEFAULT_MD_PATH,
            PROJECT_ROOT / "logs" / "large_contextual_stability.md",
        )

    def test_aggregates_multiple_synthetic_iterations(self) -> None:
        report = build_stability_report(
            iteration_reports=[
                _iteration_report(1, task_b_match=True, task_b_fallback=False),
                _iteration_report(2, task_b_match=False, task_b_fallback=True),
            ],
            selection_mode="both",
            model="fake-lemonade-model",
            dry_run=True,
        )

        summary = report["summary"]
        self.assertEqual(report["metadata"]["task_tier"], "standard")
        self.assertEqual(summary["iteration_count"], 2)
        self.assertEqual(summary["task_count"], 2)
        self.assertEqual(summary["total_runs"], 12)
        self.assertEqual(summary["baseline_success_rate"], 1.0)
        self.assertEqual(summary["spatial_fixture_success_rate"], 1.0)
        self.assertEqual(summary["spatial_router_success_rate"], 1.0)
        self.assertEqual(summary["per_task_router_match_count"]["task_a"], 2)
        self.assertEqual(summary["per_task_router_match_count"]["task_b"], 1)

    def test_router_match_and_fallback_rates_are_calculated_from_router_runs(self) -> None:
        report = build_stability_report(
            iteration_reports=[
                _iteration_report(1, task_b_match=True, task_b_fallback=False),
                _iteration_report(2, task_b_match=False, task_b_fallback=True),
            ],
            selection_mode="both",
            model="fake-lemonade-model",
            dry_run=True,
        )

        summary = report["summary"]
        self.assertEqual(summary["router_valid_selection_rate"], 0.75)
        self.assertEqual(summary["router_match_rate"], 0.75)
        self.assertEqual(summary["router_match_rate_valid_selections"], 1.0)
        self.assertEqual(summary["fallback_count"], 1)
        self.assertEqual(summary["fallback_rate"], 0.25)
        self.assertEqual(summary["average_router_latency_ms"], 25.0)
        self.assertEqual(summary["average_router_total_tokens"], 50.0)
        self.assertEqual(summary["average_router_executor_latency_ms"], 125.0)
        self.assertEqual(summary["average_router_executor_total_tokens"], 170.0)
        self.assertEqual(summary["average_baseline_latency_ms"], 100.0)
        self.assertEqual(summary["average_baseline_total_tokens"], 1010.0)
        self.assertEqual(summary["average_spatial_fixture_latency_ms"], 100.0)
        self.assertEqual(summary["average_spatial_fixture_total_tokens"], 210.0)
        self.assertEqual(summary["average_spatial_router_executor_latency_ms"], 100.0)
        self.assertEqual(summary["average_spatial_router_executor_total_tokens"], 220.0)
        self.assertEqual(
            summary["average_spatial_router_router_executor_latency_ms"],
            125.0,
        )
        self.assertEqual(
            summary["average_spatial_router_router_executor_total_tokens"],
            170.0,
        )
        self.assertAlmostEqual(
            summary["router_inclusive_token_reduction_vs_baseline"],
            83.16831683168317,
        )
        self.assertAlmostEqual(
            summary["router_inclusive_latency_reduction_vs_baseline"],
            -25.0,
        )

    def test_per_task_rows_surface_systematic_instability(self) -> None:
        report = build_stability_report(
            iteration_reports=[
                _iteration_report(1, task_b_match=True, task_b_fallback=False),
                _iteration_report(2, task_b_match=False, task_b_fallback=True),
            ],
            selection_mode="both",
            model="fake-lemonade-model",
            dry_run=True,
        )

        by_task = {row["task_label"]: row for row in report["per_task"]}
        self.assertEqual(by_task["task_a"]["router_match_count"], 2)
        self.assertEqual(by_task["task_a"]["fallback_count"], 0)
        self.assertEqual(by_task["task_b"]["router_match_count"], 1)
        self.assertEqual(by_task["task_b"]["router_mismatch_count"], 1)
        self.assertEqual(by_task["task_b"]["fallback_count"], 1)
        self.assertEqual(
            by_task["task_b"]["router_selected_block_counts"],
            {"fixture_b": 1, "wrong_or_invalid_b": 1},
        )

    def test_markdown_report_contains_key_stability_fields(self) -> None:
        report = build_stability_report(
            iteration_reports=[
                _iteration_report(1, task_b_match=True, task_b_fallback=False),
                _iteration_report(2, task_b_match=False, task_b_fallback=True),
            ],
            selection_mode="both",
            model="fake-lemonade-model",
            dry_run=True,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "stability.md"
            write_markdown(path, report)
            markdown = path.read_text(encoding="utf-8")

        self.assertIn("# Large Contextual Stability Report", markdown)
        self.assertIn("Task tier: `standard`", markdown)
        self.assertIn("Iterations: 2", markdown)
        self.assertIn("Router valid selection rate: 75.00%", markdown)
        self.assertIn("Router match rate among valid selections: 100.00%", markdown)
        self.assertIn("Fallback rate: 25.00%", markdown)
        self.assertIn("Average baseline latency ms: 100.00", markdown)
        self.assertIn("Average baseline total tokens: 1010.00", markdown)
        self.assertIn("Average spatial fixture latency ms: 100.00", markdown)
        self.assertIn("Average spatial_router executor total tokens: 220.00", markdown)
        self.assertIn("Average spatial_router router+executor total tokens: 170.00", markdown)
        self.assertIn("Router-inclusive token reduction vs baseline: 83.17%", markdown)
        self.assertIn("Router-inclusive latency reduction vs baseline: -25.00%", markdown)
        self.assertIn("| `task_b` | 2 | 1 | 1 | 1 | 1 |", markdown)
        self.assertIn("## Per Iteration", markdown)


def _iteration_report(
    iteration: int, task_b_match: bool, task_b_fallback: bool
) -> dict[str, object]:
    runs = [
        _run("task_a", "baseline", iteration, success=True, input_tokens=1000, total_tokens=1010),
        _run(
            "task_a",
            "spatial_fixture",
            iteration,
            success=True,
            input_tokens=200,
            total_tokens=210,
        ),
        _run(
            "task_a",
            "spatial_router",
            iteration,
            success=True,
            input_tokens=210,
            total_tokens=220,
            fixture_block="fixture_a",
            router_block="fixture_a",
            router_valid=True,
            router_match=True,
            fallback=False,
        ),
        _run("task_b", "baseline", iteration, success=True, input_tokens=1000, total_tokens=1010),
        _run(
            "task_b",
            "spatial_fixture",
            iteration,
            success=True,
            input_tokens=200,
            total_tokens=210,
        ),
        _run(
            "task_b",
            "spatial_router",
            iteration,
            success=True,
            input_tokens=210,
            total_tokens=220,
            fixture_block="fixture_b",
            router_block="fixture_b" if task_b_match else "wrong_or_invalid_b",
            router_valid=not task_b_fallback,
            router_match=task_b_match,
            fallback=task_b_fallback,
        ),
    ]
    valid_count = sum(
        1 for run in runs if run["mode"] == "spatial_router" and run["router_valid_selection"]
    )
    match_count = sum(
        1
        for run in runs
        if run["mode"] == "spatial_router" and run["router_selection_matches_fixture"]
    )
    fallback_count = sum(
        1 for run in runs if run["mode"] == "spatial_router" and run["executor_used_fallback"]
    )
    return {
        "metadata": {"run_count": len(runs), "iteration": iteration},
        "summary": {
            "modes": {
                "baseline": {"success_rate": 1.0},
                "spatial_fixture": {"success_rate": 1.0},
                "spatial_router": {"success_rate": 1.0},
            },
            "router_selection": {
                "valid_selection_rate": valid_count / 2,
                "match_rate": match_count / 2,
                "fallback_count": fallback_count,
            },
            "token_reduction_percent": 80.0,
        },
        "per_task": [],
        "runs": runs,
    }


def _run(
    task_label: str,
    mode: str,
    iteration: int,
    success: bool,
    input_tokens: int,
    total_tokens: int,
    fixture_block: str | None = None,
    router_block: str | None = None,
    router_valid: bool | None = None,
    router_match: bool | None = None,
    fallback: bool = False,
) -> dict[str, object]:
    selected_block = fixture_block or f"{task_label}_fixture"
    return {
        "task_label": task_label,
        "mode": mode,
        "repeat_index": 1,
        "success": success,
        "input_tokens": input_tokens,
        "total_tokens": total_tokens,
        "latency_ms": 100,
        "used_block_count": 2 if mode == "baseline" else 1,
        "fixture_selected_block_id": selected_block,
        "selected_block_id": selected_block,
        "router_selected_block_id": router_block if mode == "spatial_router" else None,
        "router_valid_selection": router_valid if mode == "spatial_router" else None,
        "router_selection_matches_fixture": router_match if mode == "spatial_router" else None,
        "router_success": router_valid if mode == "spatial_router" else None,
        "executor_used_fallback": fallback if mode == "spatial_router" else False,
        "router_latency_ms": 25 if mode == "spatial_router" else None,
        "router_total_tokens": 50 if mode == "spatial_router" else None,
        "router_end_to_end_latency_ms": 125 if mode == "spatial_router" else None,
        "router_end_to_end_total_tokens": 170 if mode == "spatial_router" else None,
    }


if __name__ == "__main__":
    unittest.main()
