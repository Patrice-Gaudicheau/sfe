"""Zone data structures for the minimal cognitive map prototype."""

from __future__ import annotations

from dataclasses import dataclass, field


REQUIRED_ZONE_NAMES = (
    "user_intent_zone",
    "task_constraints_zone",
    "domain_knowledge_zone",
    "execution_zone",
    "verification_zone",
    "output_zone",
)

DEFAULT_INPUT_ACTIVATION = 0.5
DEFAULT_HANDOFF_ACTIVATION = 0.75


@dataclass
class CognitiveZone:
    """Structured workspace zone with deterministic activation behavior."""

    name: str
    activation_level: float = 0.0
    allowed_operations: list[str] = field(default_factory=list)
    suppressed_operations: list[str] = field(default_factory=list)
    input_fragments: list[str] = field(default_factory=list)
    output_fragments: list[str] = field(default_factory=list)
    handoff_rules: dict[str, list[str]] = field(default_factory=dict)

    def __setattr__(self, name: str, value: object) -> None:
        if name == "activation_level":
            value = _clamp_activation(value)
        super().__setattr__(name, value)

    def __post_init__(self) -> None:
        self.activation_level = _clamp_activation(self.activation_level)

    def set_activation(self, activation_level: float) -> None:
        self.activation_level = _clamp_activation(activation_level)

    def activate_at_least(self, activation_level: float) -> None:
        self.set_activation(max(self.activation_level, activation_level))

    def add_input_fragment(self, fragment: str) -> None:
        if not fragment:
            raise ValueError(f"{self.name} cannot receive an empty fragment")

        self.input_fragments.append(fragment)
        self.activate_at_least(DEFAULT_INPUT_ACTIVATION)

    def add_output_fragment(self, fragment: str) -> None:
        if not fragment:
            raise ValueError(f"{self.name} cannot emit an empty fragment")

        self.output_fragments.append(fragment)
        self.activate_at_least(DEFAULT_INPUT_ACTIVATION)

    def receive_handoff(self, fragments: list[str], source_zone: str, operation: str) -> None:
        for fragment in fragments:
            self.add_input_fragment(fragment)

        self.activate_at_least(DEFAULT_HANDOFF_ACTIVATION)
        self.add_output_fragment(
            f"{self.name} received {operation} handoff from {source_zone}"
        )

    def can_handoff_to(self, target_zone: str, operation: str) -> bool:
        return target_zone in self.handoff_rules.get(operation, [])

    def snapshot(self) -> dict[str, object]:
        return {
            "name": self.name,
            "activation_level": self.activation_level,
            "allowed_operations": list(self.allowed_operations),
            "suppressed_operations": list(self.suppressed_operations),
            "input_fragments": list(self.input_fragments),
            "output_fragments": list(self.output_fragments),
            "handoff_rules": {
                operation: list(targets)
                for operation, targets in self.handoff_rules.items()
            },
        }


def create_default_zones() -> dict[str, CognitiveZone]:
    """Create the six default cognitive zones in flow order."""

    zones = [
        CognitiveZone(
            name="user_intent_zone",
            allowed_operations=["extract_intent", "handoff_intent"],
            suppressed_operations=["execute_task", "finalize_output"],
            handoff_rules={"handoff_intent": ["task_constraints_zone"]},
        ),
        CognitiveZone(
            name="task_constraints_zone",
            allowed_operations=["extract_constraints", "handoff_constraints"],
            suppressed_operations=["invent_requirements", "finalize_output"],
            handoff_rules={"handoff_constraints": ["domain_knowledge_zone"]},
        ),
        CognitiveZone(
            name="domain_knowledge_zone",
            allowed_operations=["retrieve_context", "handoff_context"],
            suppressed_operations=["execute_task", "ignore_constraints"],
            handoff_rules={"handoff_context": ["execution_zone"]},
        ),
        CognitiveZone(
            name="execution_zone",
            allowed_operations=["execute_task", "handoff_execution"],
            suppressed_operations=["bypass_verification"],
            handoff_rules={"handoff_execution": ["verification_zone"]},
        ),
        CognitiveZone(
            name="verification_zone",
            allowed_operations=["verify_output", "handoff_verified_output"],
            suppressed_operations=["invent_evidence", "skip_checks"],
            handoff_rules={"handoff_verified_output": ["output_zone"]},
        ),
        CognitiveZone(
            name="output_zone",
            allowed_operations=["finalize_output"],
            suppressed_operations=["alter_verified_claims"],
            handoff_rules={},
        ),
    ]
    return {zone.name: zone for zone in zones}


def _clamp_activation(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
