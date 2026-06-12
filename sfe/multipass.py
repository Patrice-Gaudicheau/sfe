"""Multi-pass planning primitives for large workspace_write runs."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


DEFAULT_MULTIPASS_MODE = "auto"
DEFAULT_MULTIPASS_MAX_PASSES = 10
DEFAULT_MULTIPASS_MAX_FILES_PER_PASS = 10


@dataclass(frozen=True)
class MultiPassConfig:
    mode: str = DEFAULT_MULTIPASS_MODE
    max_passes: int = DEFAULT_MULTIPASS_MAX_PASSES
    max_files_per_pass: int = DEFAULT_MULTIPASS_MAX_FILES_PER_PASS

    @property
    def forced(self) -> bool:
        return self.mode == "true"

    @property
    def disabled(self) -> bool:
        return self.mode == "false"


@dataclass(frozen=True)
class MultiPassBatch:
    id: str
    title: str
    goal: str
    allowed_files: tuple[str, ...]
    depends_on: tuple[str, ...] = ()
    validation_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class MultiPassPlan:
    project_summary: str
    batches: tuple[MultiPassBatch, ...]


@dataclass(frozen=True)
class MultiPassIssue:
    category: str
    reason: str
    path: str | None = None
    pass_id: str | None = None


@dataclass(frozen=True)
class MultiPassBatchResult:
    pass_id: str
    title: str
    status: str
    allowed_files: tuple[str, ...]
    created_files: tuple[str, ...] = ()
    promoted_files: tuple[str, ...] = ()
    patch_paths: tuple[str, ...] = ()
    provider_diagnostics: dict[str, object] | None = None
    issue: MultiPassIssue | None = None


@dataclass(frozen=True)
class MultiPassRunSummary:
    enabled: bool
    status: str
    project_summary: str | None = None
    passes_total: int = 0
    passes_completed: int = 0
    failed_pass_id: str | None = None
    failed_pass_issue: MultiPassIssue | None = None
    created_files_by_pass: dict[str, tuple[str, ...]] | None = None
    promoted_files_by_pass: dict[str, tuple[str, ...]] | None = None
    all_promoted_files: tuple[str, ...] = ()
    safe_resume_possible: bool = False
    pass_results: tuple[MultiPassBatchResult, ...] = ()


def resolve_multipass_config(
    environ: Mapping[str, str] | None = None,
) -> MultiPassConfig:
    env = os.environ if environ is None else environ
    return MultiPassConfig(
        mode=_resolve_mode(env.get("SFE_WORKSPACE_WRITE_MULTIPASS")),
        max_passes=_resolve_positive_int(
            env.get("SFE_MULTIPASS_MAX_PASSES"),
            DEFAULT_MULTIPASS_MAX_PASSES,
        ),
        max_files_per_pass=_resolve_positive_int(
            env.get("SFE_MULTIPASS_MAX_FILES_PER_PASS"),
            DEFAULT_MULTIPASS_MAX_FILES_PER_PASS,
        ),
    )


def should_use_multipass(task: str, config: MultiPassConfig) -> bool:
    if config.disabled:
        return False
    if config.forced:
        return True
    return _looks_like_large_workspace_write(task)


def parse_multipass_plan_json(text: str) -> MultiPassPlan | MultiPassIssue:
    if text.strip() != text or not text.strip().startswith("{"):
        return MultiPassIssue("multi_pass_planning", "invalid_plan_json")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return MultiPassIssue("multi_pass_planning", "invalid_plan_json")
    if not isinstance(payload, dict):
        return MultiPassIssue("multi_pass_planning", "plan_json_not_object")
    summary = payload.get("project_summary")
    if not isinstance(summary, str) or not summary.strip():
        return MultiPassIssue("multi_pass_planning", "missing_project_summary")
    batches_value = payload.get("batches")
    if not isinstance(batches_value, list) or not batches_value:
        return MultiPassIssue("multi_pass_planning", "missing_batches")
    batches: list[MultiPassBatch] = []
    for item in batches_value:
        if not isinstance(item, dict):
            return MultiPassIssue("multi_pass_planning", "batch_not_object")
        batch_id = item.get("id")
        title = item.get("title")
        goal = item.get("goal")
        allowed_files = _string_tuple(item.get("allowed_files"))
        depends_on = _string_tuple(item.get("depends_on"))
        validation_notes = _string_tuple(item.get("validation_notes"))
        if not isinstance(batch_id, str) or not batch_id.strip():
            return MultiPassIssue("multi_pass_planning", "missing_batch_id")
        if not isinstance(title, str) or not title.strip():
            return MultiPassIssue("multi_pass_planning", "missing_batch_title")
        if not isinstance(goal, str) or not goal.strip():
            return MultiPassIssue("multi_pass_planning", "missing_batch_goal")
        if allowed_files is None:
            return MultiPassIssue(
                "multi_pass_planning",
                "invalid_allowed_files",
                pass_id=batch_id.strip(),
            )
        if depends_on is None:
            return MultiPassIssue(
                "multi_pass_planning",
                "invalid_depends_on",
                pass_id=batch_id.strip(),
            )
        if validation_notes is None:
            return MultiPassIssue(
                "multi_pass_planning",
                "invalid_validation_notes",
                pass_id=batch_id.strip(),
            )
        batches.append(
            MultiPassBatch(
                id=batch_id.strip(),
                title=title.strip(),
                goal=goal.strip(),
                allowed_files=allowed_files,
                depends_on=depends_on,
                validation_notes=validation_notes,
            )
        )
    return MultiPassPlan(project_summary=summary.strip(), batches=tuple(batches))


def validate_multipass_plan(
    plan: MultiPassPlan,
    config: MultiPassConfig,
) -> MultiPassIssue | None:
    if len(plan.batches) > config.max_passes:
        return MultiPassIssue("multi_pass_planning", "too_many_passes")
    seen_ids: set[str] = set()
    for batch in plan.batches:
        if batch.id in seen_ids:
            return MultiPassIssue(
                "multi_pass_planning",
                "duplicate_batch_id",
                pass_id=batch.id,
            )
        if not batch.allowed_files:
            return MultiPassIssue(
                "multi_pass_planning",
                "empty_allowed_files",
                pass_id=batch.id,
            )
        if len(batch.allowed_files) > config.max_files_per_pass:
            return MultiPassIssue(
                "multi_pass_planning",
                "too_many_files_per_pass",
                pass_id=batch.id,
            )
        for dependency in batch.depends_on:
            if dependency not in seen_ids:
                return MultiPassIssue(
                    "multi_pass_planning",
                    "invalid_dependency",
                    pass_id=batch.id,
                )
        for path in batch.allowed_files:
            path_issue = validate_multipass_path(path, pass_id=batch.id)
            if path_issue is not None:
                return path_issue
        seen_ids.add(batch.id)
    return None


def validate_multipass_path(
    path: str,
    *,
    pass_id: str | None = None,
) -> MultiPassIssue | None:
    normalized = path.strip()
    if not normalized:
        return MultiPassIssue(
            "multi_pass_planning",
            "invalid_allowed_path",
            path=path,
            pass_id=pass_id,
        )
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        return MultiPassIssue(
            "multi_pass_planning",
            "unsafe_allowed_path",
            path=path,
            pass_id=pass_id,
        )
    lowered_parts = {part.lower() for part in pure.parts}
    if lowered_parts & {".git", ".sfe-worktrees"}:
        return MultiPassIssue(
            "multi_pass_planning",
            "internal_allowed_path",
            path=path,
            pass_id=pass_id,
        )
    return None


def validate_patch_paths_in_batch(
    paths: tuple[str, ...],
    batch: MultiPassBatch,
) -> MultiPassIssue | None:
    allowed = set(batch.allowed_files)
    for path in paths:
        if path not in allowed:
            return MultiPassIssue(
                "multi_pass_patch_scope",
                "path_outside_batch_allowed_files",
                path=path,
                pass_id=batch.id,
            )
    return None


def provider_diagnostics_from_execution_summary(
    summary: Mapping[str, object],
) -> dict[str, object] | None:
    diagnostics = summary.get("executor_response_diagnostics")
    if isinstance(diagnostics, dict):
        return dict(diagnostics)
    return None


def _resolve_mode(value: str | None) -> str:
    normalized = (value or DEFAULT_MULTIPASS_MODE).strip().lower()
    if normalized in {"1", "true", "yes", "on", "force", "forced"}:
        return "true"
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return "false"
    return "auto"


def _resolve_positive_int(value: str | None, default: int) -> int:
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _string_tuple(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return None
        items.append(item.strip())
    return tuple(items)


def _looks_like_large_workspace_write(task: str) -> bool:
    lowered = task.casefold()
    scaffold_terms = (
        "scaffold",
        "app complète",
        "application complète",
        "project structure",
        "structure projet",
        "multi-fichiers",
        "multi fichiers",
        "multi-file",
        "gros projet",
        "volumineux",
    )
    if any(term in lowered for term in scaffold_terms):
        return True
    framework_terms = ("symfony", "laravel", "react app", "next.js app", "vue app")
    large_terms = ("scaffold", "app complète", "application complète", "project")
    if any(term in lowered for term in framework_terms) and any(
        term in lowered for term in large_terms
    ):
        return True
    for match in re.finditer(r"(\d+)\s*(?:\+|à|-)?\s*(?:files?|fichiers?)", lowered):
        try:
            if int(match.group(1)) >= 15:
                return True
        except ValueError:
            continue
    return False
