"""Run the deterministic high-overlap policy-exception benchmark.

This runner adds a controlled authority-gap fixture where a general policy is
overridden by a narrower active exception. It is provider-free and does not run
OpenAI selector, executor, fallback-as-success, repair, or full-context
comparison paths.
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


BENCHMARK_TYPE = "multi_zone/high_overlap_policy_exception"
BENCHMARK_NAME = "high_overlap_policy_exception"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_policy_exception_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_policy_exception_benchmark.md"


def main() -> None:
    args = _parse_args()
    report = run_benchmark(repeat=args.repeat)
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic high-overlap policy-exception benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def get_high_overlap_policy_exception_tasks() -> list[PoisonPillTask]:
    authoritative_source_id = "cassini-v31"
    expected_fields = {
        "active_protocol": "Cassini Guard 2028.07-EX",
        "cycle_date": "2028-07-22",
        "owner_id": "CASSINI_OWNER_EXCEPTION",
        "threshold": "risk score <= 0.14 over 3h",
        "required_action": "enable exception quorum before partner cutover",
        "blocking_condition": "rollback if exception drift exceeds 0.03",
    }
    expected_answer = "\n".join(
        [f"{field}: {value}" for field, value in expected_fields.items()]
        + [f"evidence_source_ids: {authoritative_source_id}"]
    )
    return [
        PoisonPillTask(
            fixture_id="high_overlap_cassini_policy_exception_gate",
            question=(
                "For the Cassini Guard deployment gate for the partner-finance "
                "sandbox exception case, select the single controlling source and "
                "answer with the active protocol, cycle date, owner ID, threshold, "
                "required action, blocking condition, and evidence source ID."
            ),
            sources=(
                _source(
                    authoritative_source_id,
                    "governance_note",
                    "Cassini Policy Coordination Note",
                    (
                        "Exception board decision CEX-2028-07 applies to the "
                        "partner-finance sandbox exception case for the 2028-07-22 "
                        "Cassini Guard deployment gate. The exception board signed "
                        "the decision with CASSINI_OWNER_EXCEPTION and states that "
                        "it overrides the general Cassini policy only for this "
                        "partner-finance sandbox case. The decision contains the "
                        "complete controlling values for the exception. The active "
                        "protocol is Cassini Guard 2028.07-EX. The active threshold "
                        "is risk score <= 0.14 over 3h. The required action is "
                        "enable exception quorum before partner cutover. The "
                        "blocking condition is rollback if exception drift exceeds "
                        "0.03."
                    ),
                ),
                _source(
                    "cassini-g04",
                    "governance_note",
                    "Cassini Policy Coordination Note",
                    (
                        "General policy CGP-2028-07 applies to standard Cassini "
                        "Guard deployment gates for the 2028-07-22 cycle. It uses "
                        "the same governance template and states that ordinary "
                        "partner-finance gates use CASSINI_OWNER_GENERAL, Cassini "
                        "Guard 2028.07-GEN, risk score <= 0.26 over 9h, keep "
                        "exception quorum advisory, and rollback if general drift "
                        "exceeds 0.08. The policy says approved exception-board "
                        "decisions may override these general values for named "
                        "exception cases."
                    ),
                ),
                _source(
                    "cassini-p58",
                    "governance_note",
                    "Cassini Policy Addendum",
                    (
                        "Operational addendum for Cassini Guard 2028.07 partner "
                        "finance reviews. It mentions the 2028-07-22 cycle and "
                        "repeats risk score <= 0.14 over 3h from the exception "
                        "tracking dashboard. The addendum is a workflow summary "
                        "for operator visibility. It does not include the exception "
                        "board signature, exception owner, required partner cutover "
                        "action, or rollback condition."
                    ),
                ),
            ),
            authoritative_source_id=authoritative_source_id,
            obsolete_source_ids=(),
            partial_source_ids=("cassini-p58",),
            poison_pill_source_ids=("cassini-g04",),
            expected_fields=expected_fields,
            forbidden_values={
                "general_policy": (
                    "Cassini Guard 2028.07-GEN",
                    "CASSINI_OWNER_GENERAL",
                    "risk score <= 0.26 over 9h",
                    "keep exception quorum advisory",
                    "rollback if general drift exceeds 0.08",
                    "cassini-g04",
                ),
                "partial": (
                    "cassini-p58",
                    "exception tracking dashboard is the evidence source",
                    "workflow summary is sufficient authority",
                    "operator visibility is sufficient authority",
                ),
            },
            poison_instruction_markers=(),
            expected_answer=expected_answer,
        )
    ]


def run_benchmark(repeat: int = 1) -> dict[str, Any]:
    report = run_family_benchmark(tasks=get_high_overlap_policy_exception_tasks(), repeat=repeat)
    report["metadata"].update(
        {
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "fixture_scope": "deterministic policy-exception fixture",
            "authority_gap_type": "policy_exception_vs_active_policy",
            "evidence_level": "controlled fixture; not statistical proof",
            "openai_validation": False,
            "fallback_policy": "fallback visible; fallback is not honest success",
            "repair_policy": "no repair; repair is not supported",
        }
    )
    summary = report["summary"]
    summary["general_policy_rejection_rate"] = summary["poison_pill_rejection_rate"]
    for task in report["tasks"]:
        task["benchmark_type"] = BENCHMARK_TYPE
        task["authority_gap_type"] = "policy_exception_vs_active_policy"
    for run in report["runs"]:
        run["benchmark_type"] = BENCHMARK_TYPE
        run["authority_gap_type"] = "policy_exception_vs_active_policy"
        run["selected_general_policy_source_ids"] = run["selected_poison_pill_source_ids"]
        run["general_policy_sources_omitted"] = run["poison_pill_sources_omitted"]
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# High-Overlap Policy-Exception Benchmark",
        "",
        "This deterministic fixture tests source selection against a general policy "
        "that is overridden by a narrower active exception. The correct answer is "
        "available from one complete authoritative source for the requested "
        "exception case.",
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
        f"General-policy rejection rate: {_format_percent(summary['general_policy_rejection_rate'])}",
        f"Partial-source rejection rate: {_format_percent(summary['partial_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        "Output repair status: not_supported",
        f"Average token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Runs",
        "",
        "| Fixture | Mode | Selector validation | Honest pass | Selected sources | General policy selected | Partial selected |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['fixture_id']}` | `{run['mode']}` | "
            f"{run['selector_validation_result']} | "
            f"{run['honest_high_overlap_poison_pill_pass']} | "
            f"{', '.join(run['selected_source_ids'])} | "
            f"{', '.join(run['selected_general_policy_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_partial_source_ids']) or 'none'} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap policy-exception benchmark")
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
