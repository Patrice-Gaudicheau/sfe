"""Tests for the Cognitive Map benchmark Markdown report generator."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.report_cognitive_map_benchmark import (
    aggregate_by_mode,
    combined_comparison_summary,
    comparative_ratios,
    metric_availability,
    read_jsonl,
    reflection_summary,
    render_report,
    task_level_summary,
)


def _rows() -> list[dict[str, object]]:
    return [
        {
            "task_label": "analysis",
            "mode": "explicit_metadata",
            "repeat_index": 1,
            "success": True,
            "provider_reported_prompt_tokens": 100,
            "provider_reported_completion_tokens": 40,
            "provider_reported_total_tokens": 140,
            "latency_ms": 1000,
            "verification_passed": True,
        },
        {
            "task_label": "analysis",
            "mode": "cognitive_map",
            "repeat_index": 1,
            "success": True,
            "provider_reported_prompt_tokens": 60,
            "provider_reported_completion_tokens": 20,
            "provider_reported_total_tokens": 80,
            "latency_ms": 500,
            "reflection_triggered": True,
            "reflection_attempts_used": 1,
            "verification_passed": True,
        },
        {
            "task_label": "coding",
            "mode": "explicit_metadata",
            "repeat_index": 1,
            "success": False,
            "provider_reported_prompt_tokens": 90,
            "provider_reported_completion_tokens": 30,
            "provider_reported_total_tokens": 120,
            "latency_ms": 900,
            "verification_passed": False,
        },
        {
            "task_label": "coding",
            "mode": "cognitive_map",
            "repeat_index": 1,
            "success": True,
            "provider_reported_prompt_tokens": 50,
            "provider_reported_completion_tokens": 10,
            "provider_reported_total_tokens": 60,
            "latency_ms": 300,
            "reflection_triggered": False,
            "reflection_attempts_used": 0,
            "verification_passed": True,
        },
    ]


class CognitiveMapBenchmarkReportTests(unittest.TestCase):
    def test_read_jsonl_parses_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.jsonl"
            path.write_text(
                "\n".join(json.dumps(row, sort_keys=True) for row in _rows()),
                encoding="utf-8",
            )

            rows = read_jsonl(path)

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0]["task_label"], "analysis")

    def test_aggregate_by_mode_summarizes_metrics(self) -> None:
        summary = aggregate_by_mode(_rows())

        self.assertEqual(summary["explicit_metadata"]["runs"], 2)
        self.assertEqual(summary["explicit_metadata"]["success_count"], 1)
        self.assertEqual(summary["explicit_metadata"]["failure_count"], 1)
        self.assertEqual(summary["explicit_metadata"]["verification_passed_count"], 1)
        self.assertEqual(summary["explicit_metadata"]["verification_failed_count"], 1)
        self.assertEqual(summary["explicit_metadata"]["verification_unavailable_count"], 0)
        self.assertEqual(summary["explicit_metadata"]["prompt_token_sum"], 190)
        self.assertEqual(summary["explicit_metadata"]["completion_token_sum"], 70)
        self.assertEqual(summary["explicit_metadata"]["total_token_sum"], 260)
        self.assertEqual(summary["explicit_metadata"]["mean_total_tokens"], 130)
        self.assertEqual(summary["explicit_metadata"]["latency_ms_sum"], 1900)
        self.assertEqual(summary["explicit_metadata"]["mean_latency_ms"], 950)

    def test_aggregate_by_mode_summarizes_verification_counts(self) -> None:
        summary = aggregate_by_mode(_rows())

        self.assertEqual(summary["cognitive_map"]["verification_passed_count"], 2)
        self.assertEqual(summary["cognitive_map"]["verification_failed_count"], 0)
        self.assertEqual(summary["cognitive_map"]["verification_unavailable_count"], 0)
        self.assertEqual(summary["explicit_metadata"]["verification_passed_count"], 1)
        self.assertEqual(summary["explicit_metadata"]["verification_failed_count"], 1)
        self.assertEqual(summary["explicit_metadata"]["verification_unavailable_count"], 0)

    def test_markdown_aggregate_table_includes_verification_counts(self) -> None:
        markdown = render_report(
            rows=_rows(),
            input_path=Path("live_results.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertIn("verif pass", markdown)
        self.assertIn("verif fail", markdown)
        self.assertIn("| explicit_metadata | 2 | 1 | 1 | 1 | 1 | 0 |", markdown)

    def test_comparative_ratio_calculation(self) -> None:
        ratios = comparative_ratios(aggregate_by_mode(_rows()))

        self.assertAlmostEqual(ratios["total_token_reduction_pct"], 46.1538, places=3)
        self.assertAlmostEqual(ratios["prompt_token_reduction_pct"], 42.1052, places=3)
        self.assertAlmostEqual(
            ratios["completion_token_reduction_pct"], 57.1428, places=3
        )
        self.assertAlmostEqual(ratios["latency_reduction_pct"], 57.8947, places=3)
        self.assertEqual(ratios["mean_token_difference"], 60)
        self.assertEqual(ratios["mean_latency_difference_ms"], 550)

    def test_real_rows_with_token_fields_render_computed_ratios(self) -> None:
        markdown = render_report(
            rows=_rows(),
            input_path=Path("live_results.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertIn("total token reduction percentage: 46.15%", markdown)
        self.assertIn("prompt token reduction percentage: 42.11%", markdown)
        self.assertIn("completion token reduction percentage: 57.14%", markdown)
        self.assertIn("latency reduction percentage: 57.89%", markdown)
        self.assertNotIn("appears to be a dry-run or token-free file", markdown)

    def test_reflection_summary_counts_cognitive_map_rows(self) -> None:
        summary = reflection_summary(_rows())

        self.assertTrue(summary["fields_present"])
        self.assertEqual(summary["cognitive_map_rows"], 2)
        self.assertEqual(summary["reflection_triggered_rows"], 1)
        self.assertEqual(summary["triggered_labels"], ["analysis"])
        self.assertEqual(summary["total_reflection_attempts_used"], 1)
        self.assertEqual(summary["verification_passed_count"], 2)
        self.assertEqual(summary["verification_failed_count"], 0)

    def test_task_level_summary_includes_reflection_attempts(self) -> None:
        task_rows = task_level_summary(_rows())
        analysis_cognitive = next(
            row
            for row in task_rows
            if row["task_label"] == "analysis" and row["mode"] == "cognitive_map"
        )

        self.assertEqual(analysis_cognitive["total_tokens"], 80)
        self.assertEqual(analysis_cognitive["latency_ms"], 500)
        self.assertEqual(analysis_cognitive["reflection_attempts"], 1)

    def test_markdown_contains_cautious_wording(self) -> None:
        markdown = render_report(
            rows=_rows(),
            input_path=Path("logs/cognitive_map_real_benchmark.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertIn("# Cognitive Map Real Benchmark Report", markdown)
        self.assertIn("observed in this run", markdown.lower())
        self.assertIn("exploratory benchmark", markdown)
        self.assertIn("not a scientific evaluation", markdown)
        self.assertIn("Quality was not judged semantically", markdown)
        self.assertIn(
            "deterministic verification only checks narrow constraints",
            markdown.lower(),
        )

    def test_missing_token_fields_are_handled_gracefully(self) -> None:
        rows = [
            {
                "task_label": "writing",
                "mode": "cognitive_map",
                "success": True,
                "latency_ms": 0,
            }
        ]

        summary = aggregate_by_mode(rows)
        markdown = render_report(
            rows=rows,
            input_path=Path("missing_tokens.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertEqual(summary["cognitive_map"]["total_token_sum"], 0)
        self.assertEqual(summary["cognitive_map"]["mean_total_tokens"], 0.0)
        self.assertIn("missing_tokens.jsonl", markdown)

    def test_dry_run_null_token_fields_produce_na_with_clear_wording(self) -> None:
        rows = [
            {
                "task_label": "writing",
                "mode": "explicit_metadata",
                "dry_run": True,
                "success": True,
                "provider_reported_prompt_tokens": None,
                "provider_reported_completion_tokens": None,
                "provider_reported_total_tokens": None,
                "latency_ms": 0,
            },
            {
                "task_label": "writing",
                "mode": "cognitive_map",
                "dry_run": True,
                "success": True,
                "provider_reported_prompt_tokens": None,
                "provider_reported_completion_tokens": None,
                "provider_reported_total_tokens": None,
                "latency_ms": 0,
            },
        ]

        markdown = render_report(
            rows=rows,
            input_path=Path("dry_run.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertIn("total token reduction percentage: n/a", markdown)
        self.assertIn("dry-run or token-free file", markdown)
        self.assertIn("provider token fields are missing, null, or zero", markdown)
        self.assertIn("rows with provider token fields: 0", markdown)

    def test_mixed_real_and_dry_run_rows_do_not_crash(self) -> None:
        rows = _rows() + [
            {
                "task_label": "writing",
                "mode": "explicit_metadata",
                "dry_run": True,
                "success": True,
                "provider_reported_total_tokens": None,
                "latency_ms": 0,
            },
            {
                "task_label": "writing",
                "mode": "cognitive_map",
                "dry_run": True,
                "success": True,
                "provider_reported_total_tokens": None,
                "latency_ms": 0,
            },
        ]

        availability = metric_availability(rows)
        markdown = render_report(
            rows=rows,
            input_path=Path("mixed.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertEqual(availability["dry_run_rows"], 2)
        self.assertIn("total token reduction percentage:", markdown)
        self.assertIn("| writing | cognitive_map | 0 | 0 | 1 | 0 | 0 |", markdown)

    def test_missing_reflection_fields_are_handled_gracefully(self) -> None:
        rows = [
            {
                "task_label": "writing",
                "mode": "cognitive_map",
                "success": True,
                "provider_reported_total_tokens": 10,
                "latency_ms": 5,
            }
        ]

        summary = reflection_summary(rows)
        markdown = render_report(
            rows=rows,
            input_path=Path("no_reflection.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertFalse(summary["fields_present"])
        self.assertIn("Reflection fields were not detected", markdown)

    def test_zero_baseline_report_uses_cautious_interpretation(self) -> None:
        rows = [
            {
                "task_label": "writing",
                "mode": "explicit_metadata",
                "success": True,
                "provider_reported_total_tokens": 0,
                "latency_ms": 0,
            },
            {
                "task_label": "writing",
                "mode": "cognitive_map",
                "success": True,
                "provider_reported_total_tokens": 0,
                "latency_ms": 0,
            },
        ]

        markdown = render_report(
            rows=rows,
            input_path=Path("dry_run.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertIn("comparative reduction ratios were not available", markdown)
        self.assertIn("dry-run or token-free file", markdown)

    def test_report_groups_cognitive_map_rows_by_zone_builder_mode(self) -> None:
        rows = [
            {
                "task_label": "analysis",
                "mode": "explicit_metadata",
                "comparison_mode": "explicit_metadata",
                "success": True,
                "provider_reported_prompt_tokens": 100,
                "provider_reported_completion_tokens": 40,
                "provider_reported_total_tokens": 140,
                "latency_ms": 1000,
                "combined_prompt_tokens": 100,
                "combined_completion_tokens": 40,
                "combined_total_tokens": 140,
                "combined_latency_ms": 1000,
                "verification_passed": True,
            },
            {
                "task_label": "analysis",
                "mode": "cognitive_map",
                "comparison_mode": "cognitive_map_deterministic",
                "success": True,
                "provider_reported_prompt_tokens": 60,
                "provider_reported_completion_tokens": 20,
                "provider_reported_total_tokens": 80,
                "latency_ms": 500,
                "zone_builder_total_tokens": 0,
                "zone_builder_latency_ms": 0,
                "zone_builder_mode": "deterministic",
                "zone_builder_success": True,
                "zone_builder_fallback_used": False,
                "combined_prompt_tokens": 60,
                "combined_completion_tokens": 20,
                "combined_total_tokens": 80,
                "combined_latency_ms": 500,
                "reflection_triggered": False,
                "reflection_attempts_used": 0,
                "verification_passed": True,
            },
            {
                "task_label": "analysis",
                "mode": "cognitive_map",
                "comparison_mode": "cognitive_map_llm_intent",
                "success": True,
                "provider_reported_prompt_tokens": 60,
                "provider_reported_completion_tokens": 20,
                "provider_reported_total_tokens": 80,
                "latency_ms": 500,
                "zone_builder_total_tokens": 10,
                "zone_builder_latency_ms": 75,
                "zone_builder_mode": "llm_intent",
                "zone_builder_success": False,
                "zone_builder_fallback_used": True,
                "combined_prompt_tokens": 67,
                "combined_completion_tokens": 23,
                "combined_total_tokens": 90,
                "combined_latency_ms": 575,
                "reflection_triggered": True,
                "reflection_attempts_used": 1,
                "verification_passed": True,
            },
        ]

        summary = aggregate_by_mode(rows)
        markdown = render_report(
            rows=rows,
            input_path=Path("llm_intent.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertIn("cognitive_map_deterministic", summary)
        self.assertIn("cognitive_map_llm_intent", summary)
        self.assertEqual(summary["cognitive_map_llm_intent"]["zone_builder_fallback_count"], 1)
        self.assertEqual(summary["cognitive_map_llm_intent"]["combined_total_token_sum"], 90)
        self.assertIn("Aggregate Zone-Builder Summary by Mode", markdown)
        self.assertIn("Aggregate Combined Summary by Mode", markdown)
        self.assertIn("model-populated zone: `user_intent_zone`", markdown)
        self.assertIn("cognitive_map_llm_intent combined total token reduction", markdown)
        self.assertIn("Combined Comparison Versus Explicit Metadata", markdown)
        self.assertIn("Comparisons use combined metrics", markdown)

    def test_report_does_not_treat_null_combined_tokens_as_zero(self) -> None:
        rows = [
            {
                "task_label": "writing",
                "mode": "explicit_metadata",
                "comparison_mode": "explicit_metadata",
                "success": False,
                "provider_reported_total_tokens": None,
                "latency_ms": 100,
                "combined_total_tokens": None,
                "combined_latency_ms": 100,
            },
            {
                "task_label": "writing",
                "mode": "cognitive_map",
                "comparison_mode": "cognitive_map_llm_intent",
                "success": True,
                "provider_reported_total_tokens": 10,
                "latency_ms": 10,
                "zone_builder_mode": "llm_intent",
                "zone_builder_total_tokens": 5,
                "zone_builder_latency_ms": 5,
                "combined_total_tokens": 15,
                "combined_latency_ms": 15,
            },
        ]

        summary = aggregate_by_mode(rows)

        self.assertEqual(summary["explicit_metadata"]["combined_total_token_sum"], 0)
        self.assertEqual(summary["explicit_metadata"]["combined_mean_total_tokens"], 0.0)
        self.assertEqual(summary["cognitive_map_llm_intent"]["combined_total_token_sum"], 15)

    def test_combined_comparison_summary_labels_lower_and_higher_variants(self) -> None:
        rows = [
            {
                "task_label": "analysis",
                "mode": "explicit_metadata",
                "comparison_mode": "explicit_metadata",
                "success": True,
                "combined_total_tokens": 568,
                "combined_latency_ms": 13433,
            },
            {
                "task_label": "analysis",
                "mode": "cognitive_map",
                "comparison_mode": "cognitive_map_deterministic",
                "success": True,
                "combined_total_tokens": 331,
                "combined_latency_ms": 5263,
            },
            {
                "task_label": "analysis",
                "mode": "cognitive_map",
                "comparison_mode": "cognitive_map_llm_intent",
                "success": True,
                "combined_total_tokens": 668,
                "combined_latency_ms": 62366,
            },
        ]

        comparison = combined_comparison_summary(rows)
        markdown = render_report(
            rows=rows,
            input_path=Path("combined.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertEqual(comparison[0]["variant"], "cognitive_map_deterministic")
        self.assertEqual(comparison[0]["token_delta"], -237)
        self.assertAlmostEqual(comparison[0]["token_change_pct"], -41.7253, places=3)
        self.assertEqual(comparison[1]["variant"], "cognitive_map_llm_intent")
        self.assertEqual(comparison[1]["latency_delta_ms"], 48933)
        self.assertIn(
            "| cognitive_map_deterministic | 331 | -237 | -41.73% lower | 5263 | -8170 | -60.82% lower |",
            markdown,
        )
        self.assertIn(
            "| cognitive_map_llm_intent | 668 | +100 | +17.61% higher | 62366 | +48933 | +364.27% higher |",
            markdown,
        )

    def test_combined_comparison_skips_gracefully_without_explicit_metadata(self) -> None:
        rows = [
            {
                "task_label": "analysis",
                "mode": "cognitive_map",
                "comparison_mode": "cognitive_map_deterministic",
                "success": True,
                "combined_total_tokens": 331,
                "combined_latency_ms": 5263,
            }
        ]

        markdown = render_report(
            rows=rows,
            input_path=Path("missing_explicit.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertEqual(combined_comparison_summary(rows), [])
        self.assertIn("Combined comparison requires `explicit_metadata`", markdown)

    def test_combined_comparison_renders_unknown_metrics_as_na(self) -> None:
        rows = [
            {
                "task_label": "writing",
                "mode": "explicit_metadata",
                "comparison_mode": "explicit_metadata",
                "success": False,
                "combined_total_tokens": None,
                "combined_latency_ms": 100,
            },
            {
                "task_label": "writing",
                "mode": "cognitive_map",
                "comparison_mode": "cognitive_map_llm_intent",
                "success": True,
                "combined_total_tokens": 15,
                "combined_latency_ms": 125,
            },
        ]

        markdown = render_report(
            rows=rows,
            input_path=Path("unknown_tokens.jsonl"),
            generated_at="2026-05-04T00:00:00+00:00",
        )

        self.assertIn(
            "| cognitive_map_llm_intent | 15 | n/a | n/a | 125 | +25 | +25.00% higher |",
            markdown,
        )


if __name__ == "__main__":
    unittest.main()
