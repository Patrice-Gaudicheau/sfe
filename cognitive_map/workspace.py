"""Workspace owner for the minimal cognitive map prototype."""

from __future__ import annotations

import hashlib
import json

from cognitive_map.zones import CognitiveZone, create_default_zones


class CognitiveWorkspace:
    """Container for cognitive zones and explicit handoffs between them."""

    def __init__(self, zones: dict[str, CognitiveZone] | None = None) -> None:
        self.zones = zones if zones is not None else create_default_zones()
        self.handoff_trace: list[dict[str, object]] = []

    def add_fragment(self, zone_name: str, fragment: str) -> None:
        zone = self._zone(zone_name)
        zone.add_input_fragment(fragment)
        zone.add_output_fragment(f"{zone_name} captured input: {fragment}")

    def handoff(self, source_zone: str, target_zone: str, operation: str) -> None:
        source = self._zone(source_zone)
        target = self._zone(target_zone)

        if operation in source.suppressed_operations:
            raise ValueError(
                f"{source_zone} cannot perform '{operation}'; operation is suppressed"
            )
        if operation not in source.allowed_operations:
            raise ValueError(
                f"{source_zone} cannot perform '{operation}'; operation is not allowed"
            )
        if not source.can_handoff_to(target_zone, operation):
            raise ValueError(
                f"{source_zone} cannot hand off to {target_zone} using '{operation}'"
            )

        fragments = list(source.output_fragments)
        if not fragments:
            raise ValueError(f"{source_zone} has no output fragments to hand off")

        target.receive_handoff(fragments, source_zone=source_zone, operation=operation)
        self.handoff_trace.append(
            {
                "source_zone": source_zone,
                "target_zone": target_zone,
                "operation": operation,
                "fragment_count": len(fragments),
                "fragment_hash": _fragment_hash(fragments),
            }
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "zones": {
                zone_name: zone.snapshot()
                for zone_name, zone in self.zones.items()
            },
            "handoff_trace": [dict(entry) for entry in self.handoff_trace],
        }

    def run_minimal_flow(
        self, user_prompt: str, constraints: list[str] | None = None
    ) -> dict[str, object]:
        from cognitive_map.flow import run_minimal_flow

        return run_minimal_flow(
            user_prompt=user_prompt,
            constraints=constraints,
            workspace=self,
        )

    def _zone(self, zone_name: str) -> CognitiveZone:
        try:
            return self.zones[zone_name]
        except KeyError as exc:
            known_zones = ", ".join(self.zones)
            raise ValueError(f"Unknown zone '{zone_name}'. Known zones: {known_zones}") from exc


def _fragment_hash(fragments: list[str]) -> str:
    payload = json.dumps(fragments, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
