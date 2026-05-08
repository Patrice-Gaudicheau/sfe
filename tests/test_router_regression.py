"""Regression tests for benchmark-task routing classifications."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from router import llm_router


TASKS_PATH = PROJECT_ROOT / "benchmarks" / "tasks.json"

EXPECTED_TASK_TYPES = {
    "writing_update": {"writing"},
    "writing_edit": {"writing"},
    "coding_validator": {"coding"},
    "coding_zero_division": {"coding", "multi_context"},
    "analysis_methods": {"analysis"},
    "planning_roadmap": {"planning"},
    "architecture_router": {"analysis"},
    "review_report": {"review"},
    "json_metrics": {"writing", "coding"},
    "multi_context_eval": {"multi_context"},
}

ROLE_BY_TASK_TYPE = {
    "writing": "writer",
    "coding": "executor",
    "review": "reviewer",
    "analysis": "reviewer",
    "planning": "architect",
    "multi_context": "architect",
}


class CollapsedPlanningProvider:
    """Provider stub that reproduces the observed all-planning LLM collapse."""

    timeout = None

    def chat(self, *args, **kwargs):
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "task_type": "planning",
                                "role": "architect",
                                "provider": "local",
                                "model": llm_router.DEFAULT_EXECUTION_MODEL,
                                "memory_zones": [],
                                "execution_mode": "direct",
                                "max_input_tokens": 4000,
                                "max_output_tokens": 1000,
                                "requires_review": False,
                                "confidence": 0.5,
                                "rationale": "collapsed planning response",
                            }
                        )
                    }
                }
            ]
        }


class RouterRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_provider = llm_router.LemonadeProvider
        llm_router.LemonadeProvider = CollapsedPlanningProvider

    def tearDown(self) -> None:
        llm_router.LemonadeProvider = self.original_provider

    def test_benchmark_tasks_do_not_collapse_to_planning(self) -> None:
        tasks = {task["id"]: task for task in json.loads(TASKS_PATH.read_text(encoding="utf-8"))}

        for task_id, expected_task_types in EXPECTED_TASK_TYPES.items():
            with self.subTest(task_id=task_id):
                decision, diagnostics = llm_router.route_with_llm_diagnostics(
                    tasks[task_id]["prompt"]
                )

                self.assertIn(decision["task_type"], expected_task_types)
                self.assertEqual(decision["role"], ROLE_BY_TASK_TYPE[decision["task_type"]])
                self.assertTrue(diagnostics["json_valid"])
                self.assertFalse(diagnostics["used_fallback"])


if __name__ == "__main__":
    unittest.main()
