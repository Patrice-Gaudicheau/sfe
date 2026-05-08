"""Reusable selection verification for routed context execution."""

from __future__ import annotations

from dataclasses import asdict, dataclass


VERIFICATION_STATUS_COMPLETE = "complete"
VERIFICATION_STATUS_INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class SelectionVerificationResult:
    """Deterministic check that selected context contains required target values."""

    status: str
    contains_all_targets: bool
    present_targets: tuple[str, ...]
    missing_targets: tuple[str, ...]
    target_count: int
    missing_target_count: int

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["present_targets"] = list(self.present_targets)
        data["missing_targets"] = list(self.missing_targets)
        return data


class SelectionVerifier:
    """Verify selected context sufficiency without changing the selected route."""

    def verify(
        self,
        *,
        selected_context: str,
        required_targets: tuple[str, ...],
    ) -> SelectionVerificationResult:
        normalized_context = selected_context.lower()
        present = tuple(
            target
            for target in required_targets
            if str(target).lower() in normalized_context
        )
        missing = tuple(
            target
            for target in required_targets
            if str(target).lower() not in normalized_context
        )
        contains_all_targets = not missing
        return SelectionVerificationResult(
            status=(
                VERIFICATION_STATUS_COMPLETE
                if contains_all_targets
                else VERIFICATION_STATUS_INCOMPLETE
            ),
            contains_all_targets=contains_all_targets,
            present_targets=present,
            missing_targets=missing,
            target_count=len(required_targets),
            missing_target_count=len(missing),
        )
