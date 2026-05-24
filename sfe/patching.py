"""Unified-diff parsing and local patch application for the TUI.

The deterministic layer intentionally stays mechanical: path containment,
Python-only writes, and all-or-nothing application. Task-level patch acceptance
belongs to the configured router reviewer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MECHANICAL_GUARD_REJECTED = "mechanical_safety_guard"
INVALID_PATCH_PROPOSAL = "invalid_patch_proposal"
PHYSICAL_APPLICATION_FAILURE = "physical_application_failure"

_DIFF_HEADER_RE = re.compile(r"^diff --git (a/[^ ]+) (b/[^ ]+)$")
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?: .*)?$"
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


@dataclass(frozen=True)
class ParsedPatch:
    files: tuple[ParsedFilePatch, ...]


@dataclass(frozen=True)
class PatchIssue:
    category: str
    reason: str
    path: str | None = None


@dataclass(frozen=True)
class PatchSummary:
    paths: tuple[str, ...]
    file_count: int
    hunk_count: int
    lines_added: int
    lines_removed: int


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


@dataclass(frozen=True)
class PatchApplyResult:
    applied: bool
    issue: PatchIssue | None
    summary: PatchSummary | None
    pending_patch_cleared: bool


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
            return PatchParseResult(None, path_issue, None)

        hunks: list[ParsedHunk] = []
        while index < len(lines) and not lines[index].startswith("diff --git "):
            if _is_metadata(lines[index]):
                index += 1
                continue
            hunk_header = _HUNK_HEADER_RE.match(lines[index])
            if hunk_header is None:
                return _parse_error("malformed_hunk_header", _strip_diff_prefix(new_path))
            old_start = int(hunk_header.group("old_start"))
            old_count = _range_count(hunk_header.group("old_count"))
            new_start = int(hunk_header.group("new_start"))
            new_count = _range_count(hunk_header.group("new_count"))
            if old_start < 1 or new_start < 1:
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
                if old_seen > old_count or new_seen > new_count:
                    return _parse_error("impossible_hunk_accounting", _strip_diff_prefix(new_path))
                index += 1
            if old_seen != old_count or new_seen != new_count:
                return _parse_error("impossible_hunk_accounting", _strip_diff_prefix(new_path))
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
            )
        )

    if not files:
        return _parse_error("empty_patch")
    patch = ParsedPatch(files=tuple(files))
    return PatchParseResult(patch=patch, issue=None, summary=summarize_patch(patch))


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
        return PatchValidationResult(False, path_result, None)
    return PatchValidationResult(True, None, summarize_patch(patch))


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

    computed: list[tuple[Path, bytes, bytes]] = []
    for file_patch in patch.files:
        target = _resolve_safe_target(workspace_root, file_patch.new_path)
        if isinstance(target, PatchIssue):
            return PatchApplyResult(False, target, None, True)
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

    written: list[tuple[Path, bytes]] = []
    for target, original_bytes, new_bytes in computed:
        try:
            target.write_bytes(new_bytes)
            written.append((target, original_bytes))
        except OSError:
            for written_target, previous_bytes in reversed(written):
                try:
                    written_target.write_bytes(previous_bytes)
                except OSError:
                    pass
            return PatchApplyResult(
                False,
                PatchIssue(PHYSICAL_APPLICATION_FAILURE, "write_error", None),
                None,
                False,
            )
    return PatchApplyResult(
        applied=True,
        issue=None,
        summary=summarize_patch(patch),
        pending_patch_cleared=True,
    )


def summarize_patch(patch: ParsedPatch) -> PatchSummary:
    paths = tuple(file_patch.new_path for file_patch in patch.files)
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
    )


def _apply_file_patch(text: str, file_patch: ParsedFilePatch) -> str | PatchIssue:
    original_lines = text.split("\n")
    had_final_newline = bool(original_lines and original_lines[-1] == "")
    if had_final_newline:
        original_lines = original_lines[:-1]
    result_lines: list[str] = []
    cursor = 0
    for hunk in file_patch.hunks:
        start = hunk.old_start - 1
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
    return None


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
