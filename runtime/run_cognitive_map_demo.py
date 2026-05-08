"""Run the minimal cognitive map prototype flow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cognitive_map.flow import DEFAULT_PROMPT, run_minimal_flow


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prompt", nargs="?", default=DEFAULT_PROMPT)
    args = parser.parse_args()

    snapshot = run_minimal_flow(args.prompt)
    zones = snapshot["zones"]

    print("Cognitive Map Snapshot")
    print("======================")
    for zone_name, zone in zones.items():
        print(f"\n{zone_name}")
        print(f"  activation_level: {zone['activation_level']}")
        print("  input_fragments:")
        for fragment in zone["input_fragments"]:
            print(f"    - {fragment}")
        print("  output_fragments:")
        for fragment in zone["output_fragments"]:
            print(f"    - {fragment}")

    print("\nHandoff Trace")
    print("=============")
    for entry in snapshot["handoff_trace"]:
        print(
            "  - "
            f"{entry['source_zone']} -> {entry['target_zone']} "
            f"via {entry['operation']} ({entry['fragment_count']} fragments, "
            f"hash {entry['fragment_hash']})"
        )


if __name__ == "__main__":
    main()
