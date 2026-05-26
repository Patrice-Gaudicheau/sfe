"""Core patch JSON repair primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


PATCH_JSON_REPAIR_MAX_INPUT_CHARS = 120_000


@dataclass(frozen=True)
class PatchJsonRepairResult:
    repaired_text: str | None
    error_category: str | None = None
    provider_name: str | None = None
    model: str | None = None


class PatchJsonRepairer(Protocol):
    provider_name: str | None
    model: str | None

    def repair(
        self,
        *,
        raw_response: str,
        parse_error: str,
    ) -> PatchJsonRepairResult:
        ...
