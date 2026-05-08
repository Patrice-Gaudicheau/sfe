"""Simple text report for sfe experiment runs."""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.logger import list_runs
from runtime.metrics import average, success_rate


def main() -> None:
    runs = list_runs()
    grouped_runs = _group_by_mode(runs)

    print("Experiment Run Report")
    print("=====================")
    print(f"Total runs: {len(runs)}")

    if not runs:
        return

    print()
    for mode in sorted(grouped_runs):
        mode_runs = grouped_runs[mode]
        count = len(mode_runs)
        average_total_tokens = average(run["total_tokens"] for run in mode_runs)
        average_latency_ms = average(run["latency_ms"] for run in mode_runs)
        mode_success_rate = success_rate(mode_runs)

        print(f"Mode: {mode}")
        print(f"  Runs: {count}")
        print(f"  Average total_tokens: {average_total_tokens:.2f}")
        print(f"  Average latency_ms: {average_latency_ms:.2f}")
        print(f"  Success rate: {mode_success_rate:.2%}")


def _group_by_mode(runs: list[dict]) -> dict[str, list[dict]]:
    grouped_runs: dict[str, list[dict]] = defaultdict(list)
    for run in runs:
        grouped_runs[str(run["mode"])].append(run)
    return dict(grouped_runs)


if __name__ == "__main__":
    main()
