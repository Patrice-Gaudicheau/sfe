"""Report baseline vs spatial token usage for logged sfe runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.logger import list_runs
from runtime.metrics import average, percentage, success_rate


def main() -> None:
    args = _parse_args()
    runs = _filter_by_executor(list_runs(), args.executor)
    baseline_runs = [run for run in runs if run["mode"] == "baseline"]
    spatial_runs = [run for run in runs if run["mode"] == "spatial"]

    print("Token Savings Report")
    print("====================")
    print(f"Executor: {args.executor}")

    if not baseline_runs or not spatial_runs:
        print()
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

    baseline_success_rate = success_rate(baseline_runs)
    spatial_success_rate = success_rate(spatial_runs)
    success_rate_difference = spatial_success_rate - baseline_success_rate

    print()
    print(f"Baseline run count: {len(baseline_runs)}")
    print(f"Spatial run count: {len(spatial_runs)}")
    print(f"Average baseline total_tokens: {baseline_tokens:.2f}")
    print(f"Average spatial total_tokens: {spatial_tokens:.2f}")
    print(f"Absolute token difference: {token_savings:.2f}")
    print(f"Percentage token savings: {token_savings_percent:.2f}%")
    print(f"Average latency difference: {latency_difference:.2f} ms")
    print(f"Success rate difference: {success_rate_difference:.2%}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Report baseline vs spatial token savings.")
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


if __name__ == "__main__":
    main()
