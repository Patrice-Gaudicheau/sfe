"""Run the deterministic high-overlap scope-authority benchmark.

This runner adds a controlled regional/scope authority fixture to the
high-overlap benchmark family. It is provider-free and does not run OpenAI
selector, executor, fallback-as-success, repair, or full-context comparison
paths.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.metrics import write_json_report, write_text_report
from runtime.run_high_overlap_poison_pill_benchmark import (
    PoisonPillTask,
    _format_optional_percent,
    _format_percent,
    _source,
    run_benchmark as run_family_benchmark,
)


BENCHMARK_TYPE = "multi_zone/high_overlap_scope_authority"
BENCHMARK_NAME = "high_overlap_scope_authority"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_scope_authority_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_scope_authority_benchmark.md"


def main() -> None:
    args = _parse_args()
    report = run_benchmark(repeat=args.repeat)
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic high-overlap scope-authority benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def get_high_overlap_scope_authority_tasks() -> list[PoisonPillTask]:
    authoritative_source_id = "aurelia-r19"
    expected_fields = {
        "active_protocol": "Aurelia Guard 2028.02-NR",
        "cycle_date": "2028-02-14",
        "owner_id": "AURELIA_OWNER_NORTH",
        "threshold": "risk score <= 0.21 over 4h",
        "required_action": "enable north-lane dual approval before rollout",
        "blocking_condition": "rollback if north drift exceeds 0.04",
    }
    expected_answer = "\n".join(
        [f"{field}: {value}" for field, value in expected_fields.items()]
        + [f"evidence_source_ids: {authoritative_source_id}"]
    )
    return [
        PoisonPillTask(
            fixture_id="high_overlap_aurelia_scope_authority_gate",
            question=(
                "For the Aurelia Guard deployment gate for the North Ridge "
                "payment-risk lane, select the single source whose authority "
                "matches that scope and answer with the active protocol, cycle "
                "date, owner ID, threshold, required action, blocking condition, "
                "and evidence source ID."
            ),
            sources=(
                _source(
                    authoritative_source_id,
                    "deployment_note",
                    "Aurelia Deployment Coordination Note",
                    (
                        "Regional Deployment Council decision ARC-2028-02-NR "
                        "applies to the North Ridge payment-risk deployment lane "
                        "for the 2028-02-14 cycle. The decision is signed by "
                        "AURELIA_OWNER_NORTH and states that neighboring regions "
                        "and product lanes use separate decision records for their "
                        "own rollout gates. For this North Ridge payment-risk "
                        "scope, the active protocol is Aurelia Guard 2028.02-NR. "
                        "The active threshold is risk score <= 0.21 over 4h. The "
                        "required action is enable north-lane dual approval before "
                        "rollout. The blocking condition is rollback if north "
                        "drift exceeds 0.04."
                    ),
                ),
                _source(
                    "aurelia-q44",
                    "deployment_note",
                    "Aurelia Deployment Coordination Note",
                    (
                        "Regional Deployment Council decision ARC-2028-02-SR "
                        "applies to the South Ridge payment-risk deployment lane "
                        "for the 2028-02-14 cycle. It is signed by "
                        "AURELIA_OWNER_SOUTH and uses the same rollout gate "
                        "template as the North Ridge decision. For South Ridge, "
                        "the active protocol is Aurelia Guard 2028.02-SR, the "
                        "threshold is risk score <= 0.29 over 10h, the required "
                        "action is keep north-lane dual approval advisory, and "
                        "the blocking condition is rollback if south drift exceeds "
                        "0.09. The note says South Ridge and North Ridge use "
                        "separate regional decision records."
                    ),
                ),
                _source(
                    "aurelia-s08",
                    "deployment_note",
                    "Aurelia Deployment Coordination Note",
                    (
                        "Product Deployment Council decision APC-2028-02-CAT "
                        "applies to the North Ridge catalog-risk deployment lane "
                        "for the 2028-02-14 cycle. It is signed by "
                        "AURELIA_OWNER_CATALOG and shares the Aurelia Guard "
                        "rollout vocabulary. For the catalog-risk lane, the active "
                        "protocol is Aurelia Guard 2028.02-CAT, the threshold is "
                        "risk score <= 0.33 over 6h, the required action is enable "
                        "catalog review only, and the blocking condition is hold "
                        "rollout if catalog backlog exceeds 12. The note says "
                        "payment-risk and catalog-risk lanes use separate product "
                        "decision records."
                    ),
                ),
                _source(
                    "aurelia-n27",
                    "deployment_note",
                    "Aurelia Monitoring Addendum",
                    (
                        "Monitoring addendum for Aurelia Guard 2028.02 across the "
                        "North Ridge payment-risk and catalog-risk lanes. It "
                        "repeats the 2028-02-14 cycle and risk score <= 0.21 over "
                        "4h from the consolidated dashboard. The addendum is a "
                        "summary-only cross-scope view for operator visibility. It "
                        "does not include the Regional Deployment Council signature, "
                        "scope owner, required rollout action, or rollback "
                        "condition for the North Ridge payment-risk lane."
                    ),
                ),
            ),
            authoritative_source_id=authoritative_source_id,
            obsolete_source_ids=(),
            partial_source_ids=("aurelia-n27",),
            poison_pill_source_ids=("aurelia-q44", "aurelia-s08"),
            expected_fields=expected_fields,
            forbidden_values={
                "scope_mismatch": (
                    "Aurelia Guard 2028.02-SR",
                    "AURELIA_OWNER_SOUTH",
                    "risk score <= 0.29 over 10h",
                    "keep north-lane dual approval advisory",
                    "rollback if south drift exceeds 0.09",
                    "aurelia-q44",
                    "Aurelia Guard 2028.02-CAT",
                    "AURELIA_OWNER_CATALOG",
                    "risk score <= 0.33 over 6h",
                    "enable catalog review only",
                    "hold rollout if catalog backlog exceeds 12",
                    "aurelia-s08",
                ),
                "partial": (
                    "aurelia-n27",
                    "consolidated dashboard is the evidence source",
                    "summary-only cross-scope view is sufficient authority",
                    "operator visibility is sufficient authority",
                ),
            },
            poison_instruction_markers=(),
            expected_answer=expected_answer,
        )
    ]


def run_benchmark(repeat: int = 1) -> dict[str, Any]:
    report = run_family_benchmark(tasks=get_high_overlap_scope_authority_tasks(), repeat=repeat)
    report["metadata"].update(
        {
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "fixture_scope": "deterministic scope-authority fixture",
            "authority_gap_type": "regional_or_scope_authority_conflict",
            "evidence_level": "controlled fixture; not statistical proof",
            "openai_validation": False,
            "fallback_policy": "fallback visible; fallback is not honest success",
            "repair_policy": "no repair; repair is not supported",
        }
    )
    summary = report["summary"]
    summary["scope_mismatch_rejection_rate"] = summary["poison_pill_rejection_rate"]
    for task in report["tasks"]:
        task["benchmark_type"] = BENCHMARK_TYPE
        task["authority_gap_type"] = "regional_or_scope_authority_conflict"
    for run in report["runs"]:
        run["benchmark_type"] = BENCHMARK_TYPE
        run["authority_gap_type"] = "regional_or_scope_authority_conflict"
        run["selected_scope_mismatch_source_ids"] = run["selected_poison_pill_source_ids"]
        run["scope_mismatch_sources_omitted"] = run["poison_pill_sources_omitted"]
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# High-Overlap Scope-Authority Benchmark",
        "",
        "This deterministic fixture tests source selection against official-looking "
        "sources that are valid only for different deployment scopes. The correct "
        "answer is available from one complete authoritative source for the "
        "requested scope.",
        "",
        "This is a controlled fixture. It is not statistical proof, not OpenAI "
        "validation, and not general robustness proof.",
        "",
        f"Benchmark type: `{report['metadata']['benchmark_type']}`",
        f"Selector provider: `{report['metadata']['selector_provider']}`",
        f"Executor provider: `{report['metadata']['executor_provider']}`",
        f"Runs: {summary['run_count']}",
        "",
        "## Summary",
        "",
        f"Honest deterministic pass rate: {_format_percent(summary['honest_high_overlap_poison_pill_pass_rate'])}",
        f"Authoritative selection rate: {_format_percent(summary['authoritative_selection_rate'])}",
        f"Scope-mismatch rejection rate: {_format_percent(summary['scope_mismatch_rejection_rate'])}",
        f"Partial-source rejection rate: {_format_percent(summary['partial_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        "Output repair status: not_supported",
        f"Average token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Runs",
        "",
        "| Fixture | Mode | Selector validation | Honest pass | Selected sources | Scope-mismatch selected | Partial selected |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['fixture_id']}` | `{run['mode']}` | "
            f"{run['selector_validation_result']} | "
            f"{run['honest_high_overlap_poison_pill_pass']} | "
            f"{', '.join(run['selected_source_ids'])} | "
            f"{', '.join(run['selected_scope_mismatch_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_partial_source_ids']) or 'none'} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap scope-authority benchmark")
    print(f"selector provider: {report['metadata']['selector_provider']}")
    print(f"executor provider: {report['metadata']['executor_provider']}")
    print(f"runs: {summary['run_count']}")
    print(
        "honest deterministic pass rate: "
        f"{_format_percent(summary['honest_high_overlap_poison_pill_pass_rate'])}"
    )
    print(f"fallback count: {summary['fallback_count']}")
    print(f"json: {json_path}")
    print(f"markdown: {md_path}")


if __name__ == "__main__":
    main()
