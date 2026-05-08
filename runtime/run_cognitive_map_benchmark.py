"""Compare explicit spatial metadata with the Cognitive Map workspace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cognitive_map import CognitiveWorkspace
from router.mock_router import route
from runtime.metrics import estimate_char_count_tokens
from runtime.run_experiment import _build_execution_prompt


DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "logs" / "cognitive_map_benchmark.jsonl"

BENCHMARK_TASKS: list[dict[str, str]] = [
    {
        "task_label": "writing",
        "task": (
            "Write a concise project update about the Spatial Field Engine "
            "prototype and mention one next step."
        ),
    },
    {
        "task_label": "analysis",
        "task": (
            "Compare explicit spatial prompt metadata and a structured cognitive "
            "workspace for traceability."
        ),
    },
    {
        "task_label": "coding",
        "task": (
            "Write a Python function that checks whether a workspace snapshot "
            "contains all required zones."
        ),
    },
    {
        "task_label": "review",
        "task": (
            "Review a small benchmark design for missing validation checks and "
            "report the top risks."
        ),
    },
    {
        "task_label": "multi_context",
        "task": (
            "Explain how routing decisions, constraints, domain context, "
            "execution, verification, and final output relate in SFE."
        ),
    },
]


def main() -> None:
    args = _parse_args()
    results = run_benchmark(BENCHMARK_TASKS)
    write_jsonl(args.output, results)
    print_report(results, args.output)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Path for JSONL benchmark results.",
    )
    return parser.parse_args()


def run_benchmark(tasks: list[dict[str, str]]) -> list[dict[str, Any]]:
    results = []
    for task in tasks:
        results.append(run_explicit_metadata_mode(task))
        results.append(run_cognitive_map_mode(task))
    return results


def run_explicit_metadata_mode(task: dict[str, str]) -> dict[str, Any]:
    try:
        routing_decision = route(task["task"])
        prompt = _build_execution_prompt(task["task"], routing_decision, "spatial")
        prompt_fragments = _prompt_fragments(prompt)
        return _base_result(
            task_label=task["task_label"],
            mode="explicit_metadata",
            audit_size_chars=len(prompt),
            llm_payload_size_chars=len(prompt),
            number_of_fragments=len(prompt_fragments),
            number_of_active_zones=1,
            handoff_count=0,
            trace_available=False,
            success=True,
            error=None,
            extra={
                "routing_task_type": routing_decision["task_type"],
                "routing_role": routing_decision["role"],
                "constructed_prompt": prompt,
            },
        )
    except Exception as exc:
        return _error_result(task["task_label"], "explicit_metadata", exc)


def run_cognitive_map_mode(task: dict[str, str]) -> dict[str, Any]:
    try:
        workspace = CognitiveWorkspace()
        snapshot = workspace.run_minimal_flow(
            task["task"], constraints=_default_constraints(task)
        )
        zones = snapshot["zones"]
        active_zone_names = [
            zone_name
            for zone_name, zone in zones.items()
            if float(zone["activation_level"]) > 0.0
        ]
        input_count, output_count = _workspace_fragment_counts(snapshot)
        workspace_json = json.dumps(snapshot, sort_keys=True)
        llm_payload = _cognitive_map_llm_payload(snapshot)
        fragment_hashes = [
            str(entry["fragment_hash"])
            for entry in snapshot["handoff_trace"]
            if "fragment_hash" in entry
        ]

        return _base_result(
            task_label=task["task_label"],
            mode="cognitive_map",
            audit_size_chars=len(workspace_json),
            llm_payload_size_chars=len(llm_payload),
            number_of_fragments=input_count + output_count,
            number_of_active_zones=len(active_zone_names),
            handoff_count=len(snapshot["handoff_trace"]),
            trace_available=bool(snapshot["handoff_trace"]),
            success=True,
            error=None,
            extra={
                "active_zone_names": active_zone_names,
                "final_output_fragments_count": len(
                    zones["output_zone"]["output_fragments"]
                ),
                "fragment_hashes": fragment_hashes,
                "handoff_trace": snapshot["handoff_trace"],
                "llm_payload": llm_payload,
            },
        )
    except Exception as exc:
        return _error_result(task["task_label"], "cognitive_map", exc)


def write_jsonl(path: Path, results: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(json.dumps(result, sort_keys=True) + "\n")


def print_report(results: list[dict[str, Any]], output_path: Path) -> None:
    print("Cognitive Map Micro-Benchmark")
    print("=============================")
    print(f"results_jsonl: {output_path}")
    print()
    print(
        f"{'task_label':<14} {'mode':<18} {'audit':>7} {'payload':>8} "
        f"{'audit_tok':>9} {'pay_tok':>7} {'frags':>7} {'zones':>6} "
        f"{'handoffs':>8} {'trace':>7} {'ok':>4}"
    )
    print("-" * 112)
    for result in results:
        print(
            f"{result['task_label']:<14} "
            f"{result['mode']:<18} "
            f"{result['audit_size_chars']:>7} "
            f"{result['llm_payload_size_chars']:>8} "
            f"{result['approximate_token_estimate_audit']:>9} "
            f"{result['approximate_token_estimate_llm_payload']:>7} "
            f"{result['number_of_fragments']:>7} "
            f"{result['number_of_active_zones']:>6} "
            f"{result['handoff_count']:>8} "
            f"{str(result['trace_available']):>7} "
            f"{str(result['success']):>4}"
        )


def _base_result(
    task_label: str,
    mode: str,
    audit_size_chars: int,
    llm_payload_size_chars: int,
    number_of_fragments: int,
    number_of_active_zones: int,
    handoff_count: int,
    trace_available: bool,
    success: bool,
    error: str | None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "task_label": task_label,
        "mode": mode,
        "audit_size_chars": audit_size_chars,
        "llm_payload_size_chars": llm_payload_size_chars,
        "approximate_token_estimate_audit": _estimate_tokens(audit_size_chars),
        "approximate_token_estimate_llm_payload": _estimate_tokens(
            llm_payload_size_chars
        ),
        "number_of_fragments": number_of_fragments,
        "number_of_active_zones": number_of_active_zones,
        "handoff_count": handoff_count,
        "trace_available": trace_available,
        "success": success,
        "error": error,
    }
    if extra:
        result.update(extra)
    return result


def _error_result(task_label: str, mode: str, exc: Exception) -> dict[str, Any]:
    return _base_result(
        task_label=task_label,
        mode=mode,
        audit_size_chars=0,
        llm_payload_size_chars=0,
        number_of_fragments=0,
        number_of_active_zones=0,
        handoff_count=0,
        trace_available=False,
        success=False,
        error=str(exc),
    )


def _estimate_tokens(size_chars: int) -> int:
    """Rough deterministic chars/4 heuristic, not a tokenizer."""

    return estimate_char_count_tokens(size_chars)


def _prompt_fragments(prompt: str) -> list[str]:
    return [fragment.strip() for fragment in prompt.splitlines() if fragment.strip()]


def _workspace_fragment_counts(snapshot: dict[str, Any]) -> tuple[int, int]:
    input_count = 0
    output_count = 0
    for zone in snapshot["zones"].values():
        input_count += len(zone["input_fragments"])
        output_count += len(zone["output_fragments"])
    return input_count, output_count


def _cognitive_map_llm_payload(snapshot: dict[str, Any]) -> str:
    output_fragments = snapshot["zones"]["output_zone"]["output_fragments"]
    return "\n".join(str(fragment) for fragment in output_fragments)


def _default_constraints(task: dict[str, str]) -> list[str]:
    return [
        f"Preserve task label: {task['task_label']}.",
        "Keep the benchmark flow deterministic.",
        "Do not call external APIs.",
    ]


if __name__ == "__main__":
    main()
