"""Workspace-write executor selection."""

from __future__ import annotations

import os
from collections.abc import Mapping


SFE_WORKSPACE_WRITE_EXECUTOR_ENV = "SFE_WORKSPACE_WRITE_EXECUTOR"
WORKSPACE_WRITE_EXECUTOR_AIDER = "aider"
WORKSPACE_WRITE_EXECUTOR_TEXT = "text"
DEFAULT_WORKSPACE_WRITE_EXECUTOR = WORKSPACE_WRITE_EXECUTOR_AIDER
SUPPORTED_WORKSPACE_WRITE_EXECUTORS = (
    WORKSPACE_WRITE_EXECUTOR_AIDER,
    WORKSPACE_WRITE_EXECUTOR_TEXT,
)


class WorkspaceWriteExecutorConfigError(ValueError):
    def __init__(self, value: str) -> None:
        self.value = value
        supported = ", ".join(SUPPORTED_WORKSPACE_WRITE_EXECUTORS)
        super().__init__(
            f"Unsupported workspace_write executor {value!r}; supported values: {supported}."
        )


def resolve_workspace_write_executor(
    environ: Mapping[str, str] | None = None,
) -> str:
    env = os.environ if environ is None else environ
    raw = env.get(SFE_WORKSPACE_WRITE_EXECUTOR_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_WORKSPACE_WRITE_EXECUTOR
    normalized = raw.strip().lower()
    if normalized not in SUPPORTED_WORKSPACE_WRITE_EXECUTORS:
        raise WorkspaceWriteExecutorConfigError(raw)
    return normalized
