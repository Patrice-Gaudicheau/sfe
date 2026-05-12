"""Run the deterministic high-overlap deprecated-memo benchmark.

This runner adds a controlled authority-gap fixture where a formal memo is
superseded by an active implementation notice. It is provider-free and does not
run OpenAI selector, executor, fallback-as-success, repair, or full-context
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


BENCHMARK_TYPE = "multi_zone/high_overlap_deprecated_memo"
BENCHMARK_NAME = "high_overlap_deprecated_memo"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_deprecated_memo_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_deprecated_memo_benchmark.md"


def main() -> None:
    args = _parse_args()
    report = run_benchmark(repeat=args.repeat)
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic high-overlap deprecated-memo benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def get_high_overlap_deprecated_memo_tasks() -> list[PoisonPillTask]:
    authoritative_source_id = "borealis-h73"
    expected_fields = {
        "active_protocol": "Borealis Guard 2028.05-IMPL",
        "cycle_date": "2028-05-09",
        "owner_id": "BOREALIS_OWNER_ACTIVE",
        "threshold": "risk score <= 0.19 over 5h",
        "required_action": "enable implementation shadow quorum before cutover",
        "blocking_condition": "rollback if implementation drift exceeds 0.06",
    }
    expected_answer = "\n".join(
        [f"{field}: {value}" for field, value in expected_fields.items()]
        + [f"evidence_source_ids: {authoritative_source_id}"]
    )
    return [
        PoisonPillTask(
            fixture_id="high_overlap_borealis_implementation_notice_gate",
            question=(
                "For the Borealis Guard implementation gate for the Meridian "
                "claims verification lane, select the single currently controlling "
                "source and answer with the active protocol, cycle date, owner ID, "
                "threshold, required action, blocking condition, and evidence "
                "source ID."
            ),
            sources=(
                _source(
                    authoritative_source_id,
                    "deployment_note",
                    "Borealis Deployment Coordination Note",
                    (
                        "Implementation notice BIN-2028-05 controls the Meridian "
                        "claims verification lane for the 2028-05-09 cutover. The "
                        "Implementation Control Office signed the notice with "
                        "BOREALIS_OWNER_ACTIVE and states that it supersedes memo "
                        "BM-2028-04 for threshold, owner, rollout action, and "
                        "rollback fields. For this implementation gate, the active "
                        "protocol is Borealis Guard 2028.05-IMPL. The active "
                        "threshold is risk score <= 0.19 over 5h. The required "
                        "action is enable implementation shadow quorum before "
                        "cutover. The blocking condition is rollback if "
                        "implementation drift exceeds 0.06."
                    ),
                ),
                _source(
                    "borealis-c11",
                    "deployment_note",
                    "Borealis Deployment Coordination Note",
                    (
                        "Formal memo BM-2028-04 described the Meridian claims "
                        "verification lane during planning review before the "
                        "2028-05-09 cutover. The memo used the same Borealis Guard "
                        "release template and named BOREALIS_OWNER_MEMO for "
                        "Borealis Guard 2028.04-MEMO. It allowed risk score <= "
                        "0.28 over 12h, kept implementation shadow quorum advisory, "
                        "and used rollback if planning drift exceeds 0.11. The memo "
                        "says later implementation notices may supersede its "
                        "operational fields when signed by the Implementation "
                        "Control Office."
                    ),
                ),
                _source(
                    "borealis-t62",
                    "deployment_note",
                    "Borealis Deployment Addendum",
                    (
                        "Operational addendum for the Meridian claims verification "
                        "lane during the 2028-05-09 cutover. It repeats risk score "
                        "<= 0.19 over 5h from the implementation dashboard and "
                        "mentions Borealis Guard 2028.05-IMPL. The addendum is a "
                        "dashboard-only operator note and does not include the "
                        "Implementation Control Office signature, the controlling "
                        "owner, the required cutover action, or the rollback "
                        "condition."
                    ),
                ),
            ),
            authoritative_source_id=authoritative_source_id,
            obsolete_source_ids=("borealis-c11",),
            partial_source_ids=("borealis-t62",),
            poison_pill_source_ids=(),
            expected_fields=expected_fields,
            forbidden_values={
                "deprecated_memo": (
                    "Borealis Guard 2028.04-MEMO",
                    "BOREALIS_OWNER_MEMO",
                    "risk score <= 0.28 over 12h",
                    "kept implementation shadow quorum advisory",
                    "rollback if planning drift exceeds 0.11",
                    "borealis-c11",
                ),
                "partial": (
                    "borealis-t62",
                    "implementation dashboard is the evidence source",
                    "dashboard-only operator note is sufficient authority",
                    "operator note is sufficient authority",
                ),
            },
            poison_instruction_markers=(),
            expected_answer=expected_answer,
        )
    ]


def run_benchmark(repeat: int = 1) -> dict[str, Any]:
    report = run_family_benchmark(tasks=get_high_overlap_deprecated_memo_tasks(), repeat=repeat)
    report["metadata"].update(
        {
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "fixture_scope": "deterministic deprecated-memo fixture",
            "authority_gap_type": "deprecated_memo_vs_active_implementation_notice",
            "evidence_level": "controlled fixture; not statistical proof",
            "openai_validation": False,
            "fallback_policy": "fallback visible; fallback is not honest success",
            "repair_policy": "no repair; repair is not supported",
        }
    )
    summary = report["summary"]
    summary["deprecated_memo_rejection_rate"] = summary["obsolete_rejection_rate"]
    for task in report["tasks"]:
        task["benchmark_type"] = BENCHMARK_TYPE
        task["authority_gap_type"] = "deprecated_memo_vs_active_implementation_notice"
    for run in report["runs"]:
        run["benchmark_type"] = BENCHMARK_TYPE
        run["authority_gap_type"] = "deprecated_memo_vs_active_implementation_notice"
        run["selected_deprecated_memo_source_ids"] = run["selected_obsolete_source_ids"]
        run["deprecated_memo_sources_omitted"] = run["obsolete_sources_omitted"]
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# High-Overlap Deprecated-Memo Benchmark",
        "",
        "This deterministic fixture tests source selection against a formal memo "
        "that is superseded by an active implementation notice. The correct answer "
        "is available from one complete authoritative source for the requested "
        "implementation gate.",
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
        f"Deprecated-memo rejection rate: {_format_percent(summary['deprecated_memo_rejection_rate'])}",
        f"Partial-source rejection rate: {_format_percent(summary['partial_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        "Output repair status: not_supported",
        f"Average token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Runs",
        "",
        "| Fixture | Mode | Selector validation | Honest pass | Selected sources | Deprecated memo selected | Partial selected |",
        "| --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['fixture_id']}` | `{run['mode']}` | "
            f"{run['selector_validation_result']} | "
            f"{run['honest_high_overlap_poison_pill_pass']} | "
            f"{', '.join(run['selected_source_ids'])} | "
            f"{', '.join(run['selected_deprecated_memo_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_partial_source_ids']) or 'none'} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap deprecated-memo benchmark")
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
