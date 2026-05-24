"""Structured file replacement proposals for TUI patch application."""

from __future__ import annotations

import difflib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sfe.patching import (
    MECHANICAL_GUARD_REJECTED,
    PatchApplyResult,
    PatchIssue,
    PatchSummary,
    validate_patch_paths,
)


UNSUPPORTED_PENDING_PATCH_FORMAT = "unsupported_pending_patch_format"
UNSUPPORTED_EDIT_FORMAT = "unsupported_edit_format"
PHYSICAL_WRITE_FAILURE = "physical_write_failure"
SUPPORTED_REPLACE_ACTION = "replace_existing_file"


@dataclass(frozen=True)
class FileReplacementEdit:
    path: str
    action: str
    content: str


@dataclass(frozen=True)
class FileReplacementProposal:
    edits: tuple[FileReplacementEdit, ...]
    diff_preview: str | None = None

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(edit.path for edit in self.edits)


@dataclass(frozen=True)
class FileReplacementParseResult:
    proposal: FileReplacementProposal | None
    issue: PatchIssue | None
    summary: PatchSummary | None


def parse_file_replacement_proposal(text: str) -> FileReplacementParseResult:
    try:
        payload = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError:
        return _parse_error("invalid_json")
    if not isinstance(payload, dict):
        return _parse_error("json_not_object")
    edits_value = payload.get("edits")
    if not isinstance(edits_value, list) or not edits_value:
        return _parse_error("missing_edits")

    edits: list[FileReplacementEdit] = []
    for item in edits_value:
        if not isinstance(item, dict):
            return _parse_error("edit_not_object")
        path = item.get("path")
        action = item.get("action")
        content = item.get("content")
        if not isinstance(path, str) or not path.strip():
            return _parse_error("invalid_path")
        if action != SUPPORTED_REPLACE_ACTION:
            return FileReplacementParseResult(
                None,
                PatchIssue(UNSUPPORTED_EDIT_FORMAT, "unsupported_action", path),
                None,
            )
        if not isinstance(content, str):
            return FileReplacementParseResult(
                None,
                PatchIssue(UNSUPPORTED_EDIT_FORMAT, "content_not_text", path),
                None,
            )
        edits.append(
            FileReplacementEdit(
                path=path,
                action=SUPPORTED_REPLACE_ACTION,
                content=content,
            )
        )

    diff_preview = payload.get("diff_preview")
    if diff_preview is not None and not isinstance(diff_preview, str):
        return _parse_error("invalid_diff_preview")
    proposal = FileReplacementProposal(edits=tuple(edits), diff_preview=diff_preview)
    return FileReplacementParseResult(
        proposal=proposal,
        issue=None,
        summary=summarize_file_replacements(proposal),
    )


def summarize_file_replacements(proposal: FileReplacementProposal) -> PatchSummary:
    preview = proposal.diff_preview or ""
    hunk_count = sum(1 for line in preview.splitlines() if line.startswith("@@ "))
    lines_added = sum(
        1
        for line in preview.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    lines_removed = sum(
        1
        for line in preview.splitlines()
        if line.startswith("-") and not line.startswith("---")
    )
    return PatchSummary(
        paths=proposal.paths,
        file_count=len(proposal.edits),
        hunk_count=hunk_count or len(proposal.edits),
        lines_added=lines_added,
        lines_removed=lines_removed,
    )


def generate_replacement_diff_preview(
    workspace_root: Path,
    proposal: FileReplacementProposal,
) -> str:
    root = workspace_root.resolve()
    parts: list[str] = []
    for edit in proposal.edits:
        target = root / edit.path
        try:
            old_text = target.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        old_lines = old_text.splitlines(keepends=True)
        new_lines = edit.content.splitlines(keepends=True)
        if edit.content and not edit.content.endswith("\n"):
            new_lines = edit.content.splitlines()
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{edit.path}",
            tofile=f"b/{edit.path}",
            lineterm="",
        )
        body = "\n".join(diff).rstrip()
        if body:
            parts.append(f"diff --git a/{edit.path} b/{edit.path}\n{body}")
    return "\n".join(parts)


def apply_file_replacements(
    workspace_root: Path,
    proposal: FileReplacementProposal,
) -> PatchApplyResult:
    guard_issue = validate_patch_paths(workspace_root, proposal.paths)
    if guard_issue is not None:
        return PatchApplyResult(False, guard_issue, None, True)

    root = workspace_root.resolve()
    computed: list[tuple[Path, bytes, bytes]] = []
    for edit in proposal.edits:
        target = (root / edit.path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return PatchApplyResult(
                False,
                PatchIssue(MECHANICAL_GUARD_REJECTED, "path_outside_workspace", edit.path),
                None,
                True,
            )
        try:
            if not target.is_file():
                return PatchApplyResult(
                    False,
                    PatchIssue(PHYSICAL_WRITE_FAILURE, "target_not_existing_file", edit.path),
                    None,
                    False,
                )
            original_bytes = target.read_bytes()
        except OSError:
            return PatchApplyResult(
                False,
                PatchIssue(PHYSICAL_WRITE_FAILURE, "read_error", edit.path),
                None,
                False,
            )
        computed.append((target, original_bytes, edit.content.encode("utf-8")))

    temp_paths: list[Path] = []
    try:
        for target, _original_bytes, replacement_bytes in computed:
            temp_file = tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".sfe-tmp",
            )
            with temp_file:
                temp_file.write(replacement_bytes)
            temp_paths.append(Path(temp_file.name))
    except OSError:
        _cleanup_temp_files(temp_paths)
        return PatchApplyResult(
            False,
            PatchIssue(PHYSICAL_WRITE_FAILURE, "write_error", None),
            None,
            False,
        )

    written: list[tuple[Path, bytes]] = []
    for target, original_bytes, _replacement_bytes in computed:
        temp_path = temp_paths.pop(0)
        try:
            os.replace(temp_path, target)
            written.append((target, original_bytes))
        except OSError:
            _cleanup_temp_files([temp_path, *temp_paths])
            _rollback_written_files(written)
            return PatchApplyResult(
                False,
                PatchIssue(PHYSICAL_WRITE_FAILURE, "write_error", None),
                None,
                False,
            )
    return PatchApplyResult(
        True,
        None,
        summarize_file_replacements(proposal),
        True,
    )


def _cleanup_temp_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except OSError:
            pass


def _rollback_written_files(written: list[tuple[Path, bytes]]) -> None:
    for target, original_bytes in reversed(written):
        try:
            target.write_bytes(original_bytes)
        except OSError:
            pass


def _parse_error(reason: str) -> FileReplacementParseResult:
    return FileReplacementParseResult(
        None,
        PatchIssue(UNSUPPORTED_PENDING_PATCH_FORMAT, reason, None),
        None,
    )


def _strip_json_fence(output: str) -> str:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text
