"""Tests for the minimal cognitive map prototype."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cognitive_map import CognitiveWorkspace, CognitiveZone
from cognitive_map.zones import REQUIRED_ZONE_NAMES


class CognitiveMapTests(unittest.TestCase):
    def test_all_six_zones_exist(self) -> None:
        workspace = CognitiveWorkspace()

        self.assertEqual(tuple(workspace.zones), REQUIRED_ZONE_NAMES)

    def test_adding_fragment_activates_target_zone(self) -> None:
        workspace = CognitiveWorkspace()

        workspace.add_fragment("user_intent_zone", "Explain the architecture.")

        self.assertGreater(workspace.zones["user_intent_zone"].activation_level, 0.0)

    def test_activation_updates_are_clamped(self) -> None:
        zone = CognitiveZone(name="test_zone")

        zone.set_activation(2.0)
        self.assertEqual(zone.activation_level, 1.0)

        zone.set_activation(-1.0)
        self.assertEqual(zone.activation_level, 0.0)

        zone.activate_at_least(2.0)
        self.assertEqual(zone.activation_level, 1.0)

        zone.activation_level = -0.25
        self.assertEqual(zone.activation_level, 0.0)

    def test_allowed_handoff_succeeds(self) -> None:
        workspace = CognitiveWorkspace()
        workspace.add_fragment("user_intent_zone", "Explain the architecture.")

        workspace.handoff(
            "user_intent_zone", "task_constraints_zone", "handoff_intent"
        )

        target_zone = workspace.zones["task_constraints_zone"]
        self.assertGreater(target_zone.activation_level, 0.0)
        self.assertTrue(target_zone.input_fragments)
        self.assertEqual(len(workspace.handoff_trace), 1)
        self.assertEqual(len(workspace.handoff_trace[0]["fragment_hash"]), 64)
        self.assertNotIn("Explain the architecture.", workspace.handoff_trace[0].values())

    def test_fragment_hash_is_deterministic(self) -> None:
        first_workspace = CognitiveWorkspace()
        second_workspace = CognitiveWorkspace()

        for workspace in (first_workspace, second_workspace):
            workspace.add_fragment("user_intent_zone", "Explain the architecture.")
            workspace.handoff(
                "user_intent_zone", "task_constraints_zone", "handoff_intent"
            )

        self.assertEqual(
            first_workspace.handoff_trace[0]["fragment_hash"],
            second_workspace.handoff_trace[0]["fragment_hash"],
        )

    def test_suppressed_operation_fails(self) -> None:
        workspace = CognitiveWorkspace()
        workspace.add_fragment("execution_zone", "Draft output.")

        with self.assertRaisesRegex(ValueError, "suppressed"):
            workspace.handoff(
                "execution_zone", "verification_zone", "bypass_verification"
            )

    def test_invalid_target_handoff_fails(self) -> None:
        workspace = CognitiveWorkspace()
        workspace.add_fragment("user_intent_zone", "Explain the architecture.")

        with self.assertRaisesRegex(ValueError, "cannot hand off"):
            workspace.handoff(
                "user_intent_zone", "execution_zone", "handoff_intent"
            )

    def test_snapshot_returns_serializable_dict(self) -> None:
        workspace = CognitiveWorkspace()
        snapshot = workspace.run_minimal_flow("Explain SFE.")

        self.assertIsInstance(snapshot, dict)
        json.dumps(snapshot)


if __name__ == "__main__":
    unittest.main()
