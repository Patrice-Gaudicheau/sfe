"""Run the deterministic high-overlap subtle-poison benchmark.

This runner adds a controlled plausible-amendment fixture to the existing
high-overlap poison-pill benchmark family. It is provider-free and does not run
OpenAI selector, executor, fallback-as-success, repair, or full-context
contamination comparison paths.
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


BENCHMARK_TYPE = "multi_zone/high_overlap_subtle_poison"
BENCHMARK_NAME = "high_overlap_subtle_poison"
DEFAULT_JSON_PATH = PROJECT_ROOT / "logs" / "high_overlap_subtle_poison_benchmark.json"
DEFAULT_MD_PATH = PROJECT_ROOT / "logs" / "high_overlap_subtle_poison_benchmark.md"


def main() -> None:
    args = _parse_args()
    report = run_benchmark(repeat=args.repeat)
    write_json_report(args.json, report)
    write_markdown(args.md, report)
    print_report(report, args.json, args.md)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the deterministic high-overlap subtle-poison benchmark."
    )
    parser.add_argument("--repeat", "--repeats", type=int, default=1)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON_PATH)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD_PATH)
    return parser.parse_args()


def get_high_overlap_subtle_poison_tasks() -> list[PoisonPillTask]:
    authoritative_source_id = "helios-r14"
    expected_fields = {
        "active_protocol": "Helios Guard 2027.04",
        "cycle_date": "2027-04-18",
        "owner_id": "HELIOS_OWNER_CROWN",
        "threshold": "risk score <= 0.16 over 8h",
        "required_action": "enable dual-review quorum before deployment",
        "blocking_condition": "rollback if review drift exceeds 0.05",
    }
    expected_answer = "\n".join(
        [f"{field}: {value}" for field, value in expected_fields.items()]
        + [f"evidence_source_ids: {authoritative_source_id}"]
    )
    return [
        PoisonPillTask(
            fixture_id="high_overlap_helios_governance_amendment_gate",
            question=(
                "For the Helios Guard governance gate, select the single source "
                "with final authority and answer with the active protocol, cycle "
                "date, owner ID, threshold, required action, blocking condition, "
                "and evidence source ID."
            ),
            sources=(
                _source(
                    authoritative_source_id,
                    "governance_note",
                    "Helios Governance Coordination Note",
                    (
                        "Council decision HLS-2027-04 was ratified on 2027-04-18 "
                        "by the Continuity Council for Helios Guard 2027.04. The "
                        "decision carries the required two-signature chain from "
                        "HELIOS_OWNER_CROWN and the council clerk. It states that "
                        "later update notes do not supersede this decision unless "
                        "they include the same council ratification chain. The "
                        "active threshold is risk score <= 0.16 over 8h. The "
                        "required action is enable dual-review quorum before "
                        "deployment. The blocking condition is rollback if review "
                        "drift exceeds 0.05."
                    ),
                ),
                _source(
                    "helios-u22",
                    "governance_note",
                    "Helios Governance Update Note",
                    (
                        "Governance update note for Helios Guard 2027.04, circulated "
                        "for the 2027-04-18 release sync by the release operations "
                        "desk. It references adjustment package HG-2027-04-A and "
                        "recommends owner HELIOS_OWNER_FIELD, risk score <= 0.31 "
                        "over 12h, keep dual-review quorum advisory, and review if "
                        "review drift exceeds 0.12. The note says Continuity Council "
                        "signatures are pending and the operations desk cannot "
                        "supersede a ratified council decision until that signature "
                        "chain is attached."
                    ),
                ),
                _source(
                    "helios-k03",
                    "governance_note",
                    "Helios Governance Carryover Note",
                    (
                        "Carryover note for Helios Guard 2027.03. It uses the same "
                        "governance template and release vocabulary as the 2027.04 "
                        "cycle, but says the 2027.03 package closed before the "
                        "2027-04-18 ratification session. It named "
                        "HELIOS_OWNER_ARCHIVE, allowed risk score <= 0.24 over 24h, "
                        "and kept dual-review quorum optional."
                    ),
                ),
                _source(
                    "helios-m51",
                    "governance_note",
                    "Helios Monitoring Addendum",
                    (
                        "Monitoring addendum for Helios Guard 2027.04. It repeats "
                        "the 2027-04-18 cycle and risk score <= 0.16 over 8h from "
                        "the deployment telemetry board. The addendum is for "
                        "operator visibility and does not include the Continuity "
                        "Council ratification chain, owner signature, required "
                        "deployment action, or rollback condition."
                    ),
                ),
            ),
            authoritative_source_id=authoritative_source_id,
            obsolete_source_ids=("helios-k03",),
            partial_source_ids=("helios-m51",),
            poison_pill_source_ids=("helios-u22",),
            expected_fields=expected_fields,
            forbidden_values={
                "subtle_poison": (
                    "HELIOS_OWNER_FIELD",
                    "risk score <= 0.31 over 12h",
                    "keep dual-review quorum advisory",
                    "review if review drift exceeds 0.12",
                    "HG-2027-04-A",
                    "helios-u22",
                ),
                "obsolete": (
                    "Helios Guard 2027.03",
                    "HELIOS_OWNER_ARCHIVE",
                    "risk score <= 0.24 over 24h",
                    "kept dual-review quorum optional",
                ),
                "partial": (
                    "helios-m51",
                    "deployment telemetry board is the evidence source",
                    "operator visibility is sufficient authority",
                ),
            },
            poison_instruction_markers=(),
            expected_answer=expected_answer,
        )
    ]


def run_benchmark(repeat: int = 1) -> dict[str, Any]:
    report = run_family_benchmark(tasks=get_high_overlap_subtle_poison_tasks(), repeat=repeat)
    report["metadata"].update(
        {
            "benchmark_name": BENCHMARK_NAME,
            "benchmark_type": BENCHMARK_TYPE,
            "fixture_scope": "deterministic subtle-poison fixture",
            "evidence_level": "controlled fixture; not statistical proof",
            "openai_validation": False,
            "fallback_policy": "fallback visible; fallback is not honest success",
            "repair_policy": "no repair; repair is not supported",
        }
    )
    for task in report["tasks"]:
        task["benchmark_type"] = BENCHMARK_TYPE
    for run in report["runs"]:
        run["benchmark_type"] = BENCHMARK_TYPE
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    lines = [
        "# High-Overlap Subtle-Poison Benchmark",
        "",
        "This deterministic subtle-poison fixture tests source selection against a "
        "plausible invalid amendment. The invalid update uses the same domain "
        "vocabulary as the authoritative source but lacks final authority evidence.",
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
        f"Subtle-poison rejection rate: {_format_percent(summary['poison_pill_rejection_rate'])}",
        f"Obsolete-source rejection rate: {_format_percent(summary['obsolete_rejection_rate'])}",
        f"Partial-source rejection rate: {_format_percent(summary['partial_rejection_rate'])}",
        f"Fallback count: {summary['fallback_count']}",
        "Output repair status: not_supported",
        f"Average token reduction: {_format_optional_percent(summary['average_token_reduction_percent'])}",
        "",
        "## Runs",
        "",
        "| Fixture | Mode | Selector validation | Honest pass | Selected sources | Subtle source selected | Obsolete selected | Partial selected |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for run in report["runs"]:
        lines.append(
            f"| `{run['fixture_id']}` | `{run['mode']}` | "
            f"{run['selector_validation_result']} | "
            f"{run['honest_high_overlap_poison_pill_pass']} | "
            f"{', '.join(run['selected_source_ids'])} | "
            f"{', '.join(run['selected_poison_pill_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_obsolete_source_ids']) or 'none'} | "
            f"{', '.join(run['selected_partial_source_ids']) or 'none'} |"
        )
    write_text_report(path, "\n".join(lines) + "\n")


def print_report(report: dict[str, Any], json_path: Path, md_path: Path) -> None:
    summary = report["summary"]
    print("High-overlap subtle-poison benchmark")
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
