"""ASCII token usage graph for sfe experiment runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.logger import list_runs
from runtime.metrics import average, percentage


BAR_WIDTH = 30


def main() -> None:
    args = _parse_args()
    runs = _filter_by_executor(list_runs(), args.executor)
    baseline_runs = [run for run in runs if run["mode"] == "baseline"]
    spatial_runs = [run for run in runs if run["mode"] == "spatial"]

    print("Token Usage Graph")
    print("=================")
    print(f"Executor: {args.executor}")
    print()

    if not baseline_runs or not spatial_runs:
        print("Not enough runs to compare baseline and spatial modes.")
        print(f"Baseline runs: {len(baseline_runs)}")
        print(f"Spatial runs: {len(spatial_runs)}")
        return

    baseline_tokens = average(run["total_tokens"] for run in baseline_runs)
    spatial_tokens = average(run["total_tokens"] for run in spatial_runs)
    token_savings = baseline_tokens - spatial_tokens
    token_savings_percent = percentage(token_savings, baseline_tokens)

    baseline_latency = average(run["latency_ms"] for run in baseline_runs)
    spatial_latency = average(run["latency_ms"] for run in spatial_runs)
    latency_difference = baseline_latency - spatial_latency

    scale = max(baseline_tokens, spatial_tokens)

    print(_bar_line("baseline", baseline_tokens, scale))
    print(_bar_line("spatial", spatial_tokens, scale))
    print()
    print(f"Savings: {token_savings:.2f} tokens ({token_savings_percent:.2f}%)")
    print(f"Latency difference: {latency_difference:.2f} ms")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print an ASCII token usage graph.")
    parser.add_argument("--executor", choices=("mock", "lemonade"), default="lemonade")
    return parser.parse_args()


def _filter_by_executor(runs: list[dict], executor: str) -> list[dict]:
    return [run for run in runs if _metadata_value(run, "executor") == executor]


def _metadata_value(run: dict, key: str) -> str | None:
    value = run.get(key)
    if value:
        return str(value)

    return _parse_notes(run.get("notes")).get(key)


def _parse_notes(notes: str | None) -> dict[str, str]:
    metadata = {}

    for part in str(notes or "").split(";"):
        if "=" not in part:
            continue

        key, value = part.split("=", 1)
        metadata[key.strip()] = value.strip()

    return metadata


def _bar_line(label: str, value: float, scale: float) -> str:
    filled = _bar_length(value, scale)
    bar = "█" * filled
    return f"{label:<8} | {bar:<{BAR_WIDTH}} {value:.2f}"


def _bar_length(value: float, scale: float) -> int:
    if scale <= 0:
        return 0
    return max(1, round(value / scale * BAR_WIDTH))


if __name__ == "__main__":
    main()
