"""Reusable output validation for visible executor answers."""

from __future__ import annotations

from dataclasses import asdict, dataclass


OUTPUT_VALIDATION_STATUS_COMPLETE = "complete"
OUTPUT_VALIDATION_STATUS_INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class OutputValidationResult:
    """Deterministic check that visible output contains required target values."""

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


class OutputValidator:
    """Validate executor-visible output without retrying or repairing it."""

    def validate(
        self,
        *,
        output: str,
        required_targets: tuple[str, ...],
    ) -> OutputValidationResult:
        normalized_output = output.lower()
        present = tuple(
            target
            for target in required_targets
            if str(target).lower() in normalized_output
        )
        missing = tuple(
            target
            for target in required_targets
            if str(target).lower() not in normalized_output
        )
        contains_all_targets = bool(output.strip()) and not missing
        return OutputValidationResult(
            status=(
                OUTPUT_VALIDATION_STATUS_COMPLETE
                if contains_all_targets
                else OUTPUT_VALIDATION_STATUS_INCOMPLETE
            ),
            contains_all_targets=contains_all_targets,
            present_targets=present,
            missing_targets=missing,
            target_count=len(required_targets),
            missing_target_count=len(missing),
        )
