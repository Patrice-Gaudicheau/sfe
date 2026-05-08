"""Regression tests for the planning-specific spatial prompt."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from router.mock_router import route
from runtime.run_experiment import _build_execution_prompt


TASKS_PATH = PROJECT_ROOT / "benchmarks" / "tasks.json"


class PlanningPromptTests(unittest.TestCase):
    def test_planning_roadmap_uses_compact_numbered_list_prompt(self) -> None:
        tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
        task = next(task for task in tasks if task["id"] == "planning_roadmap")
        decision = route(task["prompt"])

        baseline_prompt = _build_execution_prompt(task["prompt"], decision, "baseline")
        spatial_prompt = _build_execution_prompt(task["prompt"], decision, "spatial")

        self.assertEqual(decision["task_type"], "planning")
        self.assertLess(len(spatial_prompt.split()), len(baseline_prompt.split()))
        self.assertIn("Return only a numbered list with exactly 3 items.", spatial_prompt)
        self.assertNotIn("Preserve and address these planning dimensions", spatial_prompt)
        self.assertNotIn("- Dependencies:", spatial_prompt)
        self.assertNotIn("- Risks:", spatial_prompt)
        self.assertNotIn("- Sequence:", spatial_prompt)


if __name__ == "__main__":
    unittest.main()
