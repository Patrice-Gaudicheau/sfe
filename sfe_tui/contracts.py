"""Explicit SFE-aware request contracts for the first-party TUI."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_INSTRUCTIONS = (
    "Use only explicitly selected SFE context. Keep protected instructions and "
    "the user task separate from reducible context."
)


@dataclass(frozen=True)
class ProtectedText:
    id: str
    text: str
    protected: bool = True
    reducible: bool = False


@dataclass(frozen=True)
class ContextSegment:
    id: str
    source_ref: str
    text: str = ""
    protected: bool = False
    reducible: bool = True
    approx_size: int = 0


@dataclass(frozen=True)
class SFEContract:
    instructions: list[ProtectedText]
    task: ProtectedText | None
    context_segments: list[ContextSegment]
    protected_segments: list[ProtectedText]
    metadata: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)


def resolve_workspace(raw_value: str, cwd: Path | None = None) -> Path:
    base = (cwd or Path.cwd()).resolve()
    value = raw_value.strip()
    path = base if not value else Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve()
    if not resolved.exists():
        raise ValueError("workspace_not_found")
    if not resolved.is_dir():
        raise ValueError("workspace_not_directory")
    return resolved


def resolve_context_path(workspace_root: Path, raw_value: str) -> Path:
    value = raw_value.strip()
    if not value:
        raise ValueError("empty_path")
    root = workspace_root.resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("path_outside_workspace") from exc
    if not resolved.exists():
        raise ValueError("path_not_found")
    return resolved


def workspace_relative_ref(workspace_root: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace_root.resolve()).as_posix()


def context_segment_id(source_ref: str) -> str:
    digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]
    return f"ctx_{digest}"


def build_contract(
    *,
    workspace_root: Path | None,
    task: str,
    file_paths: list[Path],
    instructions: str = DEFAULT_INSTRUCTIONS,
) -> SFEContract:
    context_segments: list[ContextSegment] = []
    for path in file_paths:
        if workspace_root is None:
            source_ref = path.name
        else:
            source_ref = workspace_relative_ref(workspace_root, path)
        context_segments.append(
            ContextSegment(
                id=context_segment_id(source_ref),
                source_ref=source_ref,
                text="",
                approx_size=0,
            )
        )

    instruction_items = [
        ProtectedText(id="instructions_default", text=instructions),
    ]
    task_item = (
        ProtectedText(id="task_current", text=task)
        if task.strip()
        else None
    )
    protected_segments: list[ProtectedText] = []
    metadata = {
        "workspace_root_present": workspace_root is not None,
        "context_segment_count": len(context_segments),
        "protected_segment_count": len(protected_segments),
        "protected_instruction_count": len(instruction_items),
        "reducible_segment_count": sum(1 for item in context_segments if item.reducible),
        "context_segment_ids": [item.id for item in context_segments],
        "approx_context_sizes": [item.approx_size for item in context_segments],
    }
    audit = {
        "selected_segment_ids": [],
        "router_token_estimate": None,
        "executor_token_estimate": None,
        "fallback_reason": None,
    }
    return SFEContract(
        instructions=instruction_items,
        task=task_item,
        context_segments=context_segments,
        protected_segments=protected_segments,
        metadata=metadata,
        audit=audit,
    )
