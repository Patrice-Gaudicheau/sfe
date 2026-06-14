"""Core filesystem executor boundary for disk-mutating execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class FilesystemExecutionRequest:
    cwd: Path
    task: str
    expected_paths: tuple[str, ...] = ()
    context_paths: tuple[str, ...] = ()
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class FilesystemExecutionDiagnostics:
    executor_name: str
    cwd: str
    command: tuple[str, ...]
    return_code: int | None
    stdout_length: int
    stderr_length: int
    stdout_preview: str | None
    stderr_preview: str | None
    elapsed_ms: int


@dataclass(frozen=True)
class FilesystemExecutionResult:
    executor_name: str
    status: str
    changed_paths: tuple[str, ...]
    diagnostics: FilesystemExecutionDiagnostics
    error_category: str | None = None


class FilesystemExecutor(Protocol):
    name: str

    def execute(
        self,
        request: FilesystemExecutionRequest,
    ) -> FilesystemExecutionResult:
        ...
