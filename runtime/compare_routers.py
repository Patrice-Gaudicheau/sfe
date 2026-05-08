"""Compare deterministic and LLM routing decisions on sample tasks."""

from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from router.llm_router import route_with_llm
from router.mock_router import route


SAMPLE_TASKS = [
    ("writing", "Write a short article about spatial cognition."),
    ("coding", "Code a small Python bug fix for experiment logging."),
    (
        "multi-context",
        "Plan a research prototype that combines writing, code changes, evaluation metrics, and prior design decisions.",
    ),
]


def main() -> None:
    for label, task in SAMPLE_TASKS:
        mock_decision = route(task)
        llm_decision = _call_llm_router(task)

        print("=" * 72)
        print(f"Task type: {label}")
        print(f"Task: {task}")
        print()
        print("mock_router.route:")
        print(json.dumps(mock_decision, indent=2, sort_keys=True))
        print()
        print("llm_router.route_with_llm:")
        print(json.dumps(llm_decision, indent=2, sort_keys=True))


def _call_llm_router(task: str) -> dict:
    try:
        return route_with_llm(task)
    except Exception as exc:
        return {"error": str(exc)}


if __name__ == "__main__":
    main()
