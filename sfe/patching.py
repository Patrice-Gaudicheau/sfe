"""Unified-diff parsing and local patch application for the TUI.

The deterministic layer intentionally stays mechanical: path containment,
Python-only writes, and all-or-nothing application. Task-level patch acceptance
belongs to the configured router reviewer.
"""

from __future__ import annotations

import re
import difflib
import json
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

MECHANICAL_GUARD_REJECTED = "mechanical_safety_guard"
INVALID_PATCH_PROPOSAL = "invalid_patch_proposal"
PHYSICAL_APPLICATION_FAILURE = "physical_application_failure"
PHYSICAL_WRITE_FAILURE = "physical_write_failure"
UNSUPPORTED_PENDING_PATCH_FORMAT = "unsupported_pending_patch_format"
UNSUPPORTED_EDIT_FORMAT = "unsupported_edit_format"
SUPPORTED_REPLACE_ACTION = "replace_existing_file"
SUPPORTED_CREATE_ACTION = "create_file"
SUPPORTED_STRUCTURED_ACTIONS = frozenset(
    {SUPPORTED_REPLACE_ACTION, SUPPORTED_CREATE_ACTION}
)

_DIFF_HEADER_RE = re.compile(r"^diff --git (a/[^ ]+) (b/[^ ]+)$")
_FENCED_BLOCK_RE = re.compile(r"```[^\n`]*\n(?P<body>.*?)\n?```", re.DOTALL)
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<section> .*)?$"
)
_METADATA_PREFIXES = (
    "index ",
    "new file mode ",
    "deleted file mode ",
    "old mode ",
    "new mode ",
    "similarity index ",
    "dissimilarity index ",
    "rename from ",
    "rename to ",
    "copy from ",
    "copy to ",
    "Binary files ",
    "GIT binary patch",
)
PATCH_OPERATION_MODIFY = "modify"
PATCH_OPERATION_CREATE = "create"
_EXCLUDED_WRITE_DIRS = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    "__pycache__",
    "build",
    "cache",
    "dist",
    "logs",
    "node_modules",
    "var",
    "vendor",
}


@dataclass(frozen=True)
class PatchLine:
    kind: str
    text: str


@dataclass(frozen=True)
class ParsedHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: tuple[PatchLine, ...]


@dataclass(frozen=True)
class ParsedFilePatch:
    old_path: str
    new_path: str
    hunks: tuple[ParsedHunk, ...]
    operation: str = PATCH_OPERATION_MODIFY


@dataclass(frozen=True)
class ParsedPatch:
    files: tuple[ParsedFilePatch, ...]


@dataclass(frozen=True)
class PatchIssue:
    category: str
    reason: str
    path: str | None = None
    hunk_accounting: "HunkAccountingDiagnostics | None" = None


@dataclass(frozen=True)
class HunkAccountingDiagnostics:
    path: str | None
    hunk_header: str
    declared_old_start: int
    declared_old_count: int
    declared_new_start: int
    declared_new_count: int
    actual_old_side_count: int
    actual_new_side_count: int
    actual_context_line_count: int
    actual_removed_line_count: int
    actual_added_line_count: int
    looks_like_new_file: bool
    old_file_header_is_dev_null: bool
    hunk_body_only_added_lines: bool
    llm_correctable_in_principle: bool
    message: str


@dataclass(frozen=True)
class HunkCountNormalizationChange:
    path: str
    original_hunk_header: str
    normalized_hunk_header: str
    declared_old_count: int
    declared_new_count: int
    actual_old_side_count: int
    actual_new_side_count: int
    actual_context_line_count: int
    actual_removed_line_count: int
    actual_added_line_count: int


@dataclass(frozen=True)
class HunkCountNormalizationDiagnostics:
    applied: bool
    changes: tuple[HunkCountNormalizationChange, ...] = ()

    @property
    def message(self) -> str:
        if not self.applied or not self.changes:
            return "No hunk count normalization was applied."
        if len(self.changes) == 1:
            change = self.changes[0]
            return (
                "Hunk count normalization applied: declared old/new count was "
                f"{change.declared_old_count}/{change.declared_new_count}, "
                f"but hunk body implies {change.actual_old_side_count}/"
                f"{change.actual_new_side_count}."
            )
        return f"Hunk count normalization applied to {len(self.changes)} hunks."


@dataclass(frozen=True)
class HunkCountNormalizationResult:
    normalized_text: str | None
    diagnostics: HunkCountNormalizationDiagnostics
    issue: PatchIssue | None = None


@dataclass(frozen=True)
class PatchSummary:
    paths: tuple[str, ...]
    file_count: int
    hunk_count: int
    lines_added: int
    lines_removed: int
    modified_paths: tuple[str, ...] = ()
    created_paths: tuple[str, ...] = ()
    refused_paths: tuple[str, ...] = ()
    refused_reasons: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class PatchParseResult:
    patch: ParsedPatch | None
    issue: PatchIssue | None
    summary: PatchSummary | None


@dataclass(frozen=True)
class PatchValidationResult:
    ok: bool
    issue: PatchIssue | None
    summary: PatchSummary | None
    patch: ParsedPatch | None = None


@dataclass(frozen=True)
class PatchApplyResult:
    applied: bool
    issue: PatchIssue | None
    summary: PatchSummary | None
    pending_patch_cleared: bool


@dataclass(frozen=True)
class StructuredFileEdit:
    path: str
    action: str
    content: str


@dataclass(frozen=True)
class StructuredFilePatch:
    edits: tuple[StructuredFileEdit, ...]
    diff_preview: str | None = None

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(edit.path for edit in self.edits)


@dataclass(frozen=True)
class StructuredFilePatchParseResult:
    proposal: StructuredFilePatch | None
    issue: PatchIssue | None
    summary: PatchSummary | None


def parse_unified_diff(text: str) -> PatchParseResult:
    lines = text.split("\n") if text else []
    if lines and lines[-1] == "":
        lines = lines[:-1]
    if not lines:
        return _parse_error("empty_patch")
    if lines[0].strip() != lines[0] or not lines[0].startswith("diff --git "):
        return _parse_error("missing_diff_header")

    files: list[ParsedFilePatch] = []
    index = 0
    while index < len(lines):
        header = lines[index]
        match = _DIFF_HEADER_RE.match(header)
        if match is None:
            return _parse_error("unexpected_non_diff_text")
        old_path = match.group(1)
        new_path = match.group(2)
        path_issue = _validate_prefixed_pair(old_path, new_path)
        if path_issue is not None:
            return PatchParseResult(None, path_issue, None)
        index += 1

        if index >= len(lines):
            return _parse_error("missing_file_headers", _strip_diff_prefix(new_path))
        for metadata_line in lines[index:]:
            if metadata_line.startswith("--- "):
                break
            if metadata_line.startswith("diff --git "):
                return _parse_error("missing_file_headers", _strip_diff_prefix(new_path))
            if _is_metadata(metadata_line):
                index += 1
                continue
            return _parse_error("unexpected_patch_metadata", _strip_diff_prefix(new_path))

        if index >= len(lines) or not lines[index].startswith("--- "):
            return _parse_error("missing_old_file_header", _strip_diff_prefix(new_path))
        old_file_path = lines[index][4:]
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            return _parse_error("missing_new_file_header", _strip_diff_prefix(new_path))
        new_file_path = lines[index][4:]
        index += 1

        path_issue = _validate_file_headers(
            old_path,
            new_path,
            old_file_path,
            new_file_path,
        )
        if path_issue is not None:
            return PatchParseResult(None, path_issue, _refused_summary(path_issue))
        operation = _classify_file_operation(old_file_path, new_file_path)
        if isinstance(operation, PatchIssue):
            return PatchParseResult(None, operation, _refused_summary(operation))

        hunks: list[ParsedHunk] = []
        while index < len(lines) and not lines[index].startswith("diff --git "):
            if _is_metadata(lines[index]):
                index += 1
                continue
            hunk_header_text = lines[index]
            hunk_header = _HUNK_HEADER_RE.match(hunk_header_text)
            if hunk_header is None:
                return _parse_error("malformed_hunk_header", _strip_diff_prefix(new_path))
            old_start = int(hunk_header.group("old_start"))
            old_count = _range_count(hunk_header.group("old_count"))
            new_start = int(hunk_header.group("new_start"))
            new_count = _range_count(hunk_header.group("new_count"))
            old_range_ok = old_start >= 1 or (old_start == 0 and old_count == 0)
            new_range_ok = new_start >= 1 or (new_start == 0 and new_count == 0)
            if not old_range_ok or not new_range_ok:
                return _parse_error("malformed_hunk_range", _strip_diff_prefix(new_path))
            index += 1
            hunk_lines: list[PatchLine] = []
            old_seen = 0
            new_seen = 0
            while index < len(lines):
                line = lines[index]
                if line.startswith("diff --git ") or _HUNK_HEADER_RE.match(line):
                    break
                if line.startswith("\\"):
                    return _parse_error("unsupported_no_newline_marker", _strip_diff_prefix(new_path))
                if not line:
                    return _parse_error("malformed_hunk_line", _strip_diff_prefix(new_path))
                marker = line[0]
                if marker not in {" ", "-", "+"}:
                    return _parse_error("malformed_hunk_line", _strip_diff_prefix(new_path))
                value = line[1:]
                hunk_lines.append(PatchLine(kind=marker, text=value))
                if marker in {" ", "-"}:
                    old_seen += 1
                if marker in {" ", "+"}:
                    new_seen += 1
                index += 1
            if old_seen != old_count or new_seen != new_count:
                return _hunk_accounting_error(
                    path=_strip_diff_prefix(new_path),
                    hunk_header_text=hunk_header_text,
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    hunk_lines=hunk_lines,
                    old_file_path=old_file_path,
                    operation=operation,
                )
            if not hunk_lines:
                return _parse_error("empty_hunk", _strip_diff_prefix(new_path))
            hunks.append(
                ParsedHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    lines=tuple(hunk_lines),
                )
            )
        if not hunks:
            return _parse_error("missing_hunks", _strip_diff_prefix(new_path))
        files.append(
            ParsedFilePatch(
                old_path=_strip_diff_prefix(old_path),
                new_path=_strip_diff_prefix(new_path),
                hunks=tuple(hunks),
                operation=operation,
            )
        )

    if not files:
        return _parse_error("empty_patch")
    patch = ParsedPatch(files=tuple(files))
    return PatchParseResult(patch=patch, issue=None, summary=summarize_patch(patch))


def extract_single_fenced_git_diff(text: str) -> str | None:
    """Extract one fenced Git diff when there is no surrounding prose."""
    stripped = text.strip()
    if not stripped:
        return None
    matches = list(_FENCED_BLOCK_RE.finditer(stripped))
    if len(matches) != 1:
        return None
    match = matches[0]
    if stripped[: match.start()].strip() or stripped[match.end() :].strip():
        return None
    body = match.group("body").strip()
    if not body.startswith("diff --git "):
        return None
    return body


def normalize_unified_diff_hunk_counts(text: str) -> HunkCountNormalizationResult:
    """Normalize only hunk old/new counts derived from hunk bodies.

    This does not change paths, hunk starts, or any hunk body line. Callers must
    re-run the strict parser and normal validation before applying the result.
    """

    lines = text.split("\n") if text else []
    had_trailing_newline = bool(lines and lines[-1] == "")
    if had_trailing_newline:
        lines = lines[:-1]
    if not lines:
        return _hunk_count_normalization_error("empty_patch")
    if lines[0].strip() != lines[0] or not lines[0].startswith("diff --git "):
        return _hunk_count_normalization_error("missing_diff_header")

    normalized_lines = list(lines)
    changes: list[HunkCountNormalizationChange] = []
    index = 0
    while index < len(lines):
        header = lines[index]
        match = _DIFF_HEADER_RE.match(header)
        if match is None:
            return _hunk_count_normalization_error("unexpected_non_diff_text")
        old_path = match.group(1)
        new_path = match.group(2)
        path_issue = _validate_prefixed_pair(old_path, new_path)
        if path_issue is not None:
            return HunkCountNormalizationResult(
                None,
                HunkCountNormalizationDiagnostics(applied=False),
                path_issue,
            )
        path = _strip_diff_prefix(new_path)
        index += 1

        if index >= len(lines):
            return _hunk_count_normalization_error("missing_file_headers", path)
        for metadata_line in lines[index:]:
            if metadata_line.startswith("--- "):
                break
            if metadata_line.startswith("diff --git "):
                return _hunk_count_normalization_error("missing_file_headers", path)
            if _is_metadata(metadata_line):
                index += 1
                continue
            return _hunk_count_normalization_error("unexpected_patch_metadata", path)

        if index >= len(lines) or not lines[index].startswith("--- "):
            return _hunk_count_normalization_error("missing_old_file_header", path)
        old_file_path = lines[index][4:]
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            return _hunk_count_normalization_error("missing_new_file_header", path)
        new_file_path = lines[index][4:]
        index += 1

        path_issue = _validate_file_headers(
            old_path,
            new_path,
            old_file_path,
            new_file_path,
        )
        if path_issue is not None:
            return HunkCountNormalizationResult(
                None,
                HunkCountNormalizationDiagnostics(applied=False),
                path_issue,
            )
        operation = _classify_file_operation(old_file_path, new_file_path)
        if isinstance(operation, PatchIssue):
            return HunkCountNormalizationResult(
                None,
                HunkCountNormalizationDiagnostics(applied=False),
                operation,
            )

        file_hunk_count = 0
        while index < len(lines) and not lines[index].startswith("diff --git "):
            if _is_metadata(lines[index]):
                index += 1
                continue
            hunk_header_text = lines[index]
            hunk_header = _HUNK_HEADER_RE.match(hunk_header_text)
            if hunk_header is None:
                return _hunk_count_normalization_error("malformed_hunk_header", path)
            old_start = int(hunk_header.group("old_start"))
            old_count = _range_count(hunk_header.group("old_count"))
            new_start = int(hunk_header.group("new_start"))
            new_count = _range_count(hunk_header.group("new_count"))
            old_range_ok = old_start >= 1 or (old_start == 0 and old_count == 0)
            new_range_ok = new_start >= 1 or (new_start == 0 and new_count == 0)
            if not old_range_ok or not new_range_ok:
                return _hunk_count_normalization_error("malformed_hunk_range", path)
            hunk_index = index
            index += 1
            hunk_lines: list[PatchLine] = []
            while index < len(lines):
                line = lines[index]
                if line.startswith("diff --git ") or _HUNK_HEADER_RE.match(line):
                    break
                if line.startswith("\\"):
                    return _hunk_count_normalization_error(
                        "unsupported_no_newline_marker",
                        path,
                    )
                if not line:
                    return _hunk_count_normalization_error("malformed_hunk_line", path)
                marker = line[0]
                if marker not in {" ", "-", "+"}:
                    return _hunk_count_normalization_error("malformed_hunk_line", path)
                hunk_lines.append(PatchLine(kind=marker, text=line[1:]))
                index += 1
            if not hunk_lines:
                return _hunk_count_normalization_error("empty_hunk", path)
            file_hunk_count += 1

            context_count = sum(1 for line in hunk_lines if line.kind == " ")
            removed_count = sum(1 for line in hunk_lines if line.kind == "-")
            added_count = sum(1 for line in hunk_lines if line.kind == "+")
            actual_old_count = context_count + removed_count
            actual_new_count = context_count + added_count
            if actual_old_count == old_count and actual_new_count == new_count:
                continue

            section = hunk_header.group("section") or ""
            normalized_header = (
                f"@@ -{old_start},{actual_old_count} "
                f"+{new_start},{actual_new_count} @@{section}"
            )
            normalized_lines[hunk_index] = normalized_header
            changes.append(
                HunkCountNormalizationChange(
                    path=path,
                    original_hunk_header=hunk_header_text,
                    normalized_hunk_header=normalized_header,
                    declared_old_count=old_count,
                    declared_new_count=new_count,
                    actual_old_side_count=actual_old_count,
                    actual_new_side_count=actual_new_count,
                    actual_context_line_count=context_count,
                    actual_removed_line_count=removed_count,
                    actual_added_line_count=added_count,
                )
            )

        if file_hunk_count == 0:
            return _hunk_count_normalization_error("missing_hunks", path)

    normalized_text = "\n".join(normalized_lines)
    if had_trailing_newline:
        normalized_text += "\n"
    return HunkCountNormalizationResult(
        normalized_text,
        HunkCountNormalizationDiagnostics(
            applied=bool(changes),
            changes=tuple(changes),
        ),
    )


def summarize_patch_text(text: str) -> PatchParseResult:
    """Return best-effort patch metadata without making policy decisions."""
    parsed = parse_unified_diff(text)
    if parsed.patch is not None and parsed.summary is not None:
        return parsed

    paths = extract_touched_paths(text)
    if not paths:
        return parsed
    summary = PatchSummary(
        paths=tuple(paths),
        file_count=len(paths),
        hunk_count=sum(1 for line in text.splitlines() if line.startswith("@@ ")),
        lines_added=sum(
            1
            for line in text.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ),
        lines_removed=sum(
            1
            for line in text.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ),
    )
    return PatchParseResult(patch=None, issue=None, summary=summary)


def extract_touched_paths(text: str) -> tuple[str, ...]:
    paths: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = _DIFF_HEADER_RE.match(line)
        if match is None:
            continue
        candidate = _strip_diff_prefix(match.group(2))
        if candidate not in seen:
            seen.add(candidate)
            paths.append(candidate)
    return tuple(paths)


def parse_structured_file_patch_json(text: str) -> StructuredFilePatchParseResult:
    try:
        payload = json.loads(strip_json_fence(text))
    except json.JSONDecodeError:
        return _structured_parse_error("invalid_json")
    if not isinstance(payload, dict):
        return _structured_parse_error("json_not_object")
    edits_value = payload.get("edits")
    if not isinstance(edits_value, list) or not edits_value:
        return _structured_parse_error("missing_edits")

    edits: list[StructuredFileEdit] = []
    for item in edits_value:
        if not isinstance(item, dict):
            return _structured_parse_error("edit_not_object")
        path = item.get("path")
        action = item.get("action")
        content = item.get("content")
        if not isinstance(path, str) or not path.strip():
            return _structured_parse_error("invalid_path")
        if action not in SUPPORTED_STRUCTURED_ACTIONS:
            return StructuredFilePatchParseResult(
                None,
                PatchIssue(UNSUPPORTED_EDIT_FORMAT, "unsupported_action", path),
                None,
            )
        if not isinstance(content, str):
            return StructuredFilePatchParseResult(
                None,
                PatchIssue(UNSUPPORTED_EDIT_FORMAT, "content_not_text", path),
                None,
            )
        edits.append(StructuredFileEdit(path=path, action=str(action), content=content))

    diff_preview = payload.get("diff_preview")
    if diff_preview is not None and not isinstance(diff_preview, str):
        return _structured_parse_error("invalid_diff_preview")
    proposal = StructuredFilePatch(edits=tuple(edits), diff_preview=diff_preview)
    return StructuredFilePatchParseResult(
        proposal=proposal,
        issue=None,
        summary=summarize_structured_file_patch(proposal),
    )


def validate_structured_file_patch_targets(
    workspace_root: Path,
    proposal: StructuredFilePatch,
) -> PatchValidationResult:
    guard_issue = validate_patch_paths(workspace_root, proposal.paths)
    if guard_issue is not None:
        return PatchValidationResult(False, guard_issue, _structured_summary_with_issue(proposal, guard_issue))
    root = workspace_root.resolve()
    for edit in proposal.edits:
        target = (root / edit.path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            issue = PatchIssue(MECHANICAL_GUARD_REJECTED, "path_outside_workspace", edit.path)
            return PatchValidationResult(False, issue, _structured_summary_with_issue(proposal, issue))
        if edit.action == SUPPORTED_REPLACE_ACTION:
            if not target.is_file():
                issue = PatchIssue(PHYSICAL_WRITE_FAILURE, "target_not_existing_file", edit.path)
                return PatchValidationResult(False, issue, _structured_summary_with_issue(proposal, issue))
        elif edit.action == SUPPORTED_CREATE_ACTION:
            if target.exists() or target.is_symlink():
                issue = PatchIssue(PHYSICAL_WRITE_FAILURE, "target_already_exists", edit.path)
                return PatchValidationResult(False, issue, _structured_summary_with_issue(proposal, issue))
        else:
            issue = PatchIssue(UNSUPPORTED_EDIT_FORMAT, "unsupported_action", edit.path)
            return PatchValidationResult(False, issue, _structured_summary_with_issue(proposal, issue))
    return PatchValidationResult(True, None, summarize_structured_file_patch(proposal))


def summarize_structured_file_patch(proposal: StructuredFilePatch) -> PatchSummary:
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
    modified_paths = tuple(
        edit.path for edit in proposal.edits if edit.action == SUPPORTED_REPLACE_ACTION
    )
    created_paths = tuple(
        edit.path for edit in proposal.edits if edit.action == SUPPORTED_CREATE_ACTION
    )
    return PatchSummary(
        paths=proposal.paths,
        file_count=len(proposal.edits),
        hunk_count=hunk_count or len(proposal.edits),
        lines_added=lines_added,
        lines_removed=lines_removed,
        modified_paths=modified_paths,
        created_paths=created_paths,
    )


def generate_structured_file_patch_diff_preview(
    workspace_root: Path,
    proposal: StructuredFilePatch,
) -> str:
    root = workspace_root.resolve()
    parts: list[str] = []
    for edit in proposal.edits:
        target = root / edit.path
        if edit.action == SUPPORTED_CREATE_ACTION:
            old_lines: list[str] = []
            fromfile = "/dev/null"
        else:
            try:
                old_text = target.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            old_lines = old_text.splitlines(keepends=True)
            fromfile = f"a/{edit.path}"
        new_lines = edit.content.splitlines(keepends=True)
        if edit.content and not edit.content.endswith("\n"):
            new_lines = edit.content.splitlines()
        diff = difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=fromfile,
            tofile=f"b/{edit.path}",
            lineterm="",
        )
        body = "\n".join(diff).rstrip()
        if body:
            parts.append(f"diff --git a/{edit.path} b/{edit.path}\n{body}")
    return "\n".join(parts)


def apply_structured_file_patch(
    workspace_root: Path,
    proposal: StructuredFilePatch,
) -> PatchApplyResult:
    validation = validate_structured_file_patch_targets(workspace_root, proposal)
    if not validation.ok:
        return PatchApplyResult(False, validation.issue, validation.summary, True)

    root = workspace_root.resolve()
    computed: list[tuple[Path, bytes | None, bytes, str]] = []
    for edit in proposal.edits:
        target = (root / edit.path).resolve()
        if edit.action == SUPPORTED_CREATE_ACTION:
            computed.append((target, None, edit.content.encode("utf-8"), edit.path))
            continue
        try:
            original_bytes = target.read_bytes()
        except OSError:
            return PatchApplyResult(
                False,
                PatchIssue(PHYSICAL_WRITE_FAILURE, "read_error", edit.path),
                None,
                False,
            )
        computed.append((target, original_bytes, edit.content.encode("utf-8"), edit.path))

    temp_paths: list[Path] = []
    created_dirs: list[Path] = []
    try:
        for target, original_bytes, replacement_bytes, source_ref in computed:
            if original_bytes is None:
                created_dirs.extend(_ensure_parent_dirs(target.parent))
                with target.open("xb") as handle:
                    handle.write(replacement_bytes)
                temp_paths.append(target)
                continue
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
        _cleanup_structured_created_files(computed)
        _cleanup_temp_files(temp_paths)
        _cleanup_created_dirs(created_dirs)
        return PatchApplyResult(
            False,
            PatchIssue(PHYSICAL_WRITE_FAILURE, "write_error", source_ref if "source_ref" in locals() else None),
            None,
            False,
        )

    written: list[tuple[Path, bytes | None]] = [
        (target, None) for target, original_bytes, _new_bytes, _source_ref in computed if original_bytes is None
    ]
    replace_temp_paths = [
        path
        for path, (_target, original_bytes, _new_bytes, _source_ref) in zip(temp_paths, computed)
        if original_bytes is not None
    ]
    replace_targets = [
        (target, original_bytes)
        for target, original_bytes, _new_bytes, _source_ref in computed
        if original_bytes is not None
    ]
    for temp_path, (target, original_bytes) in zip(replace_temp_paths, replace_targets):
        try:
            os.replace(temp_path, target)
            written.append((target, original_bytes))
        except OSError:
            _cleanup_temp_files([temp_path, *replace_temp_paths])
            _rollback_patch_writes(written)
            _cleanup_created_dirs(created_dirs)
            return PatchApplyResult(
                False,
                PatchIssue(PHYSICAL_WRITE_FAILURE, "write_error", None),
                None,
                False,
            )
    return PatchApplyResult(True, None, summarize_structured_file_patch(proposal), True)


def validate_patch_targets(
    workspace_root: Path,
    patch: ParsedPatch,
    *,
    max_bytes: int | None = None,
) -> PatchValidationResult:
    del max_bytes
    path_result = validate_patch_paths(
        workspace_root,
        tuple(file_patch.new_path for file_patch in patch.files),
    )
    if path_result is not None:
        return PatchValidationResult(False, path_result, _summary_with_issue(patch, path_result))
    normalized_files: list[ParsedFilePatch] = []
    for file_patch in patch.files:
        if file_patch.operation not in {PATCH_OPERATION_MODIFY, PATCH_OPERATION_CREATE}:
            issue = PatchIssue(
                INVALID_PATCH_PROPOSAL,
                "unsupported_file_operation",
                file_patch.new_path,
            )
            return PatchValidationResult(False, issue, _summary_with_issue(patch, issue))
        target = _resolve_safe_target(workspace_root, file_patch.new_path)
        if isinstance(target, PatchIssue):
            return PatchValidationResult(False, target, _summary_with_issue(patch, target))
        if file_patch.operation == PATCH_OPERATION_CREATE:
            if target.exists() or target.is_symlink():
                issue = PatchIssue(
                    PHYSICAL_APPLICATION_FAILURE,
                    "target_already_exists",
                    file_patch.new_path,
                )
                return PatchValidationResult(False, issue, _summary_with_issue(patch, issue))
            normalized_files.append(file_patch)
            continue
        if target.exists() or target.is_symlink():
            normalized_files.append(file_patch)
            continue
        if not _is_safe_implicit_create_patch(file_patch):
            issue = PatchIssue(
                INVALID_PATCH_PROPOSAL,
                "missing_target_not_safe_create",
                file_patch.new_path,
            )
            return PatchValidationResult(False, issue, _summary_with_issue(patch, issue))
        normalized_files.append(replace(file_patch, operation=PATCH_OPERATION_CREATE))
    normalized_patch = ParsedPatch(files=tuple(normalized_files))
    return PatchValidationResult(True, None, summarize_patch(normalized_patch), normalized_patch)


def validate_patch_paths(
    workspace_root: Path,
    paths: tuple[str, ...] | list[str],
) -> PatchIssue | None:
    for source_ref in paths:
        issue = _validate_relative_path(source_ref)
        if issue is not None:
            return issue
        resolved = _resolve_safe_target(workspace_root, source_ref)
        if isinstance(resolved, PatchIssue):
            return resolved
    return None


def apply_patch_to_workspace(
    workspace_root: Path,
    patch: ParsedPatch,
    *,
    max_bytes: int | None = None,
) -> PatchApplyResult:
    del max_bytes
    validation = validate_patch_targets(
        workspace_root,
        patch,
    )
    if not validation.ok:
        return PatchApplyResult(
            applied=False,
            issue=validation.issue,
            summary=None,
            pending_patch_cleared=True,
        )

    effective_patch = validation.patch or patch

    computed: list[tuple[Path, bytes | None, bytes]] = []
    for file_patch in effective_patch.files:
        target = _resolve_safe_target(workspace_root, file_patch.new_path)
        if isinstance(target, PatchIssue):
            return PatchApplyResult(False, target, None, True)
        if file_patch.operation == PATCH_OPERATION_CREATE:
            current_bytes = None
            current_text = ""
        else:
            try:
                current_bytes = target.read_bytes()
                current_text = current_bytes.decode("utf-8")
            except OSError:
                return PatchApplyResult(
                    False,
                    PatchIssue(PHYSICAL_APPLICATION_FAILURE, "read_error", file_patch.new_path),
                    None,
                    False,
                )
            except UnicodeDecodeError:
                return PatchApplyResult(
                    False,
                    PatchIssue(PHYSICAL_APPLICATION_FAILURE, "decode_error", file_patch.new_path),
                    None,
                    False,
                )
        applied = _apply_file_patch(current_text, file_patch)
        if isinstance(applied, PatchIssue):
            return PatchApplyResult(
                applied=False,
                issue=applied,
                summary=None,
                pending_patch_cleared=False,
            )
        computed.append((target, current_bytes, applied.encode("utf-8")))

    written: list[tuple[Path, bytes | None]] = []
    created_dirs: list[Path] = []
    for target, original_bytes, new_bytes in computed:
        try:
            if original_bytes is None:
                created_dirs.extend(_ensure_parent_dirs(target.parent))
            target.write_bytes(new_bytes)
            written.append((target, original_bytes))
        except OSError:
            _rollback_patch_writes(written)
            _cleanup_created_dirs(created_dirs)
            return PatchApplyResult(
                False,
                PatchIssue(PHYSICAL_APPLICATION_FAILURE, "write_error", None),
                None,
                False,
            )
    return PatchApplyResult(
        applied=True,
        issue=None,
        summary=summarize_patch(effective_patch),
        pending_patch_cleared=True,
    )


def summarize_patch(patch: ParsedPatch) -> PatchSummary:
    paths = tuple(file_patch.new_path for file_patch in patch.files)
    modified_paths = tuple(
        file_patch.new_path
        for file_patch in patch.files
        if file_patch.operation == PATCH_OPERATION_MODIFY
    )
    created_paths = tuple(
        file_patch.new_path
        for file_patch in patch.files
        if file_patch.operation == PATCH_OPERATION_CREATE
    )
    hunk_count = sum(len(file_patch.hunks) for file_patch in patch.files)
    lines_added = 0
    lines_removed = 0
    for file_patch in patch.files:
        for hunk in file_patch.hunks:
            for line in hunk.lines:
                if line.kind == "+":
                    lines_added += 1
                elif line.kind == "-":
                    lines_removed += 1
    return PatchSummary(
        paths=paths,
        file_count=len(paths),
        hunk_count=hunk_count,
        lines_added=lines_added,
        lines_removed=lines_removed,
        modified_paths=modified_paths,
        created_paths=created_paths,
    )


def preview_file_patch_text(text: str, file_patch: ParsedFilePatch) -> str | PatchIssue:
    return _apply_file_patch(text, file_patch)


def _apply_file_patch(text: str, file_patch: ParsedFilePatch) -> str | PatchIssue:
    if file_patch.operation == PATCH_OPERATION_CREATE:
        original_lines: list[str] = []
        had_final_newline = True
    else:
        original_lines = text.split("\n")
        had_final_newline = bool(original_lines and original_lines[-1] == "")
        if had_final_newline:
            original_lines = original_lines[:-1]
    result_lines: list[str] = []
    cursor = 0
    for hunk in file_patch.hunks:
        start = 0 if hunk.old_start == 0 and hunk.old_count == 0 else hunk.old_start - 1
        if start < cursor or start > len(original_lines):
            return PatchIssue(PHYSICAL_APPLICATION_FAILURE, "hunk_location_mismatch", file_patch.new_path)
        result_lines.extend(original_lines[cursor:start])
        preimage = [line.text for line in hunk.lines if line.kind in {" ", "-"}]
        if original_lines[start : start + len(preimage)] != preimage:
            return PatchIssue(PHYSICAL_APPLICATION_FAILURE, "hunk_preimage_mismatch", file_patch.new_path)
        for line in hunk.lines:
            if line.kind in {" ", "+"}:
                result_lines.append(line.text)
        cursor = start + len(preimage)
    result_lines.extend(original_lines[cursor:])
    new_text = "\n".join(result_lines)
    if had_final_newline:
        new_text += "\n"
    return new_text


def _parse_error(reason: str, path: str | None = None) -> PatchParseResult:
    return PatchParseResult(
        patch=None,
        issue=PatchIssue(INVALID_PATCH_PROPOSAL, reason, path),
        summary=None,
    )


def _hunk_accounting_error(
    *,
    path: str,
    hunk_header_text: str,
    old_start: int,
    old_count: int,
    new_start: int,
    new_count: int,
    hunk_lines: list[PatchLine],
    old_file_path: str,
    operation: str,
) -> PatchParseResult:
    context_count = sum(1 for line in hunk_lines if line.kind == " ")
    removed_count = sum(1 for line in hunk_lines if line.kind == "-")
    added_count = sum(1 for line in hunk_lines if line.kind == "+")
    actual_old_count = context_count + removed_count
    actual_new_count = context_count + added_count
    diagnostics = HunkAccountingDiagnostics(
        path=path,
        hunk_header=_truncate_diagnostic_text(hunk_header_text),
        declared_old_start=old_start,
        declared_old_count=old_count,
        declared_new_start=new_start,
        declared_new_count=new_count,
        actual_old_side_count=actual_old_count,
        actual_new_side_count=actual_new_count,
        actual_context_line_count=context_count,
        actual_removed_line_count=removed_count,
        actual_added_line_count=added_count,
        looks_like_new_file=operation == PATCH_OPERATION_CREATE,
        old_file_header_is_dev_null=old_file_path == "/dev/null",
        hunk_body_only_added_lines=bool(hunk_lines)
        and all(line.kind == "+" for line in hunk_lines),
        llm_correctable_in_principle=bool(hunk_lines),
        message=(
            "Hunk accounting mismatch only: declared old/new count is "
            f"{old_count}/{new_count}, but hunk body implies "
            f"{actual_old_count}/{actual_new_count}."
        ),
    )
    return PatchParseResult(
        patch=None,
        issue=PatchIssue(
            INVALID_PATCH_PROPOSAL,
            "impossible_hunk_accounting",
            path,
            diagnostics,
        ),
        summary=None,
    )


def _truncate_diagnostic_text(text: str, limit: int = 160) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[: limit - 3].rstrip() + "..."


def _hunk_count_normalization_error(
    reason: str,
    path: str | None = None,
) -> HunkCountNormalizationResult:
    return HunkCountNormalizationResult(
        None,
        HunkCountNormalizationDiagnostics(applied=False),
        PatchIssue(INVALID_PATCH_PROPOSAL, reason, path),
    )


def _structured_parse_error(reason: str) -> StructuredFilePatchParseResult:
    return StructuredFilePatchParseResult(
        None,
        PatchIssue(UNSUPPORTED_PENDING_PATCH_FORMAT, reason, None),
        None,
    )


def _range_count(value: str | None) -> int:
    if value is None:
        return 1
    return int(value)


def _is_metadata(line: str) -> bool:
    return line.startswith(_METADATA_PREFIXES)


def _validate_prefixed_pair(old_path: str, new_path: str) -> PatchIssue | None:
    if not old_path.startswith("a/") or not new_path.startswith("b/"):
        return PatchIssue(INVALID_PATCH_PROPOSAL, "missing_path_prefix", None)
    old_ref = _strip_diff_prefix(old_path)
    new_ref = _strip_diff_prefix(new_path)
    if old_ref != new_ref:
        return PatchIssue(INVALID_PATCH_PROPOSAL, "rename_or_copy_not_supported", new_ref)
    return _validate_relative_path(new_ref)


def _validate_file_headers(
    diff_old_path: str,
    diff_new_path: str,
    old_file_path: str,
    new_file_path: str,
) -> PatchIssue | None:
    if old_file_path != "/dev/null" and old_file_path != diff_old_path:
        path = _strip_diff_prefix(diff_new_path)
        return PatchIssue(INVALID_PATCH_PROPOSAL, "path_header_mismatch", path)
    if new_file_path != "/dev/null" and new_file_path != diff_new_path:
        path = _strip_diff_prefix(diff_new_path)
        return PatchIssue(INVALID_PATCH_PROPOSAL, "path_header_mismatch", path)
    if old_file_path == "/dev/null" and new_file_path == "/dev/null":
        path = _strip_diff_prefix(diff_new_path)
        return PatchIssue(INVALID_PATCH_PROPOSAL, "empty_file_operation", path)
    return None


def _classify_file_operation(
    old_file_path: str,
    new_file_path: str,
) -> str | PatchIssue:
    if old_file_path == "/dev/null":
        return PATCH_OPERATION_CREATE
    if new_file_path == "/dev/null":
        return PatchIssue(
            INVALID_PATCH_PROPOSAL,
            "delete_not_supported",
            _strip_diff_prefix(old_file_path),
        )
    return PATCH_OPERATION_MODIFY


def _is_safe_implicit_create_patch(file_patch: ParsedFilePatch) -> bool:
    if not file_patch.hunks:
        return False
    for hunk in file_patch.hunks:
        if hunk.old_start != 0 or hunk.old_count != 0:
            return False
        if any(line.kind != "+" for line in hunk.lines):
            return False
    return True


def _strip_diff_prefix(path: str) -> str:
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _validate_relative_path(source_ref: str) -> PatchIssue | None:
    path = Path(source_ref)
    parts = path.parts
    if not source_ref or source_ref.strip() != source_ref:
        return PatchIssue(MECHANICAL_GUARD_REJECTED, "empty_or_ambiguous_path", source_ref or None)
    if "\t" in source_ref or "\r" in source_ref:
        return PatchIssue(MECHANICAL_GUARD_REJECTED, "empty_or_ambiguous_path", source_ref)
    if path.is_absolute() or re.match(r"^[A-Za-z]:[\\/]", source_ref):
        return PatchIssue(MECHANICAL_GUARD_REJECTED, "absolute_path", source_ref)
    if ".." in parts:
        return PatchIssue(MECHANICAL_GUARD_REJECTED, "path_outside_workspace", source_ref)
    lowered_parts = {part.lower() for part in parts}
    blocked = lowered_parts & _EXCLUDED_WRITE_DIRS
    if blocked:
        return PatchIssue(MECHANICAL_GUARD_REJECTED, "excluded_directory", source_ref)
    return None


def _resolve_safe_target(workspace_root: Path, source_ref: str) -> Path | PatchIssue:
    root = workspace_root.resolve()
    target = root / source_ref
    try:
        resolved = target.resolve()
        resolved.relative_to(root)
    except ValueError:
        return PatchIssue(MECHANICAL_GUARD_REJECTED, "path_outside_workspace", source_ref)
    except OSError:
        return PatchIssue(PHYSICAL_APPLICATION_FAILURE, "read_error", source_ref)
    return resolved


def strip_json_fence(output: str) -> str:
    text = output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def _summary_with_issue(patch: ParsedPatch, issue: PatchIssue) -> PatchSummary:
    summary = summarize_patch(patch)
    refused_path = issue.path or ""
    refused_paths = (refused_path,) if refused_path else ()
    refused_reasons = ((refused_path, issue.reason),) if refused_path else ()
    return PatchSummary(
        paths=summary.paths,
        file_count=summary.file_count,
        hunk_count=summary.hunk_count,
        lines_added=summary.lines_added,
        lines_removed=summary.lines_removed,
        modified_paths=summary.modified_paths,
        created_paths=summary.created_paths,
        refused_paths=refused_paths,
        refused_reasons=refused_reasons,
    )


def _structured_summary_with_issue(
    proposal: StructuredFilePatch,
    issue: PatchIssue,
) -> PatchSummary:
    summary = summarize_structured_file_patch(proposal)
    refused_path = issue.path or ""
    refused_paths = (refused_path,) if refused_path else ()
    refused_reasons = ((refused_path, issue.reason),) if refused_path else ()
    return PatchSummary(
        paths=summary.paths,
        file_count=summary.file_count,
        hunk_count=summary.hunk_count,
        lines_added=summary.lines_added,
        lines_removed=summary.lines_removed,
        modified_paths=summary.modified_paths,
        created_paths=summary.created_paths,
        refused_paths=refused_paths,
        refused_reasons=refused_reasons,
    )


def _refused_summary(issue: PatchIssue) -> PatchSummary:
    refused_path = issue.path or ""
    refused_paths = (refused_path,) if refused_path else ()
    refused_reasons = ((refused_path, issue.reason),) if refused_path else ()
    return PatchSummary(
        paths=(),
        file_count=0,
        hunk_count=0,
        lines_added=0,
        lines_removed=0,
        refused_paths=refused_paths,
        refused_reasons=refused_reasons,
    )


def _ensure_parent_dirs(parent: Path) -> list[Path]:
    missing: list[Path] = []
    current = parent
    while not current.exists():
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir()
    return missing


def _rollback_patch_writes(written: list[tuple[Path, bytes | None]]) -> None:
    for target, previous_bytes in reversed(written):
        try:
            if previous_bytes is None:
                target.unlink()
            else:
                target.write_bytes(previous_bytes)
        except OSError:
            pass


def _cleanup_temp_files(paths: list[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except OSError:
            pass


def _cleanup_structured_created_files(
    computed: list[tuple[Path, bytes | None, bytes, str]],
) -> None:
    for target, original_bytes, _new_bytes, _source_ref in computed:
        if original_bytes is None:
            try:
                target.unlink()
            except OSError:
                pass


def _cleanup_created_dirs(created_dirs: list[Path]) -> None:
    for directory in created_dirs:
        try:
            directory.rmdir()
        except OSError:
            pass
