"""Conservative unified-diff parsing and local text patch application."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from sfe_tui.contracts import (
    MAX_CONTEXT_FILE_BYTES,
    PRIVATE_KEY_MARKERS,
    SECRET_FILE_NAMES,
    workspace_relative_ref,
)


UNSAFE_PATCH = "unsafe_patch"
INVALID_PATCH_PROPOSAL = "invalid_patch_proposal"
PATCH_PREIMAGE_MISMATCH = "patch_preimage_mismatch"
APPLY_IO_ERROR = "apply_io_error"

_DIFF_HEADER_RE = re.compile(r"^diff --git (a/[^ ]+) (b/[^ ]+)$")
_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?: .*)?$"
)
_UNSUPPORTED_METADATA_PREFIXES = (
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
_UNSAFE_DIRECTORY_NAMES = {
    ".cache",
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".ssh",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "venv",
}
_UNSAFE_FILE_NAMES = {
    ".coverage",
    ".ds_store",
    "coverage.xml",
    "thumbs.db",
}
_UNSAFE_SUFFIXES = {
    ".7z",
    ".a",
    ".bin",
    ".class",
    ".db",
    ".dll",
    ".dylib",
    ".egg",
    ".exe",
    ".gz",
    ".jar",
    ".jsonl",
    ".log",
    ".o",
    ".out",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".rar",
    ".so",
    ".sqlite",
    ".sqlite3",
    ".tar",
    ".tgz",
    ".whl",
    ".zip",
}
_PRIVATE_KEY_SUFFIXES = {".key"}
_TEXT_PREFIX_BYTES = 4096


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
            if _is_unsupported_metadata(metadata_line):
                return PatchParseResult(
                    None,
                    PatchIssue(
                        category=UNSAFE_PATCH,
                        reason="unsupported_patch_metadata",
                        path=_strip_diff_prefix(new_path),
                    ),
                    None,
                )
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
            if _is_unsupported_metadata(lines[index]):
                return PatchParseResult(
                    None,
                    PatchIssue(
                        category=UNSAFE_PATCH,
                        reason="unsupported_patch_metadata",
                        path=_strip_diff_prefix(new_path),
                    ),
                    None,
                )
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


def validate_patch_targets(
    workspace_root: Path,
    patch: ParsedPatch,
    *,
    max_bytes: int = MAX_CONTEXT_FILE_BYTES,
) -> PatchValidationResult:
    seen_paths: set[str] = set()
    for file_patch in patch.files:
        issue = _validate_relative_path(file_patch.new_path)
        if issue is not None:
            return PatchValidationResult(False, issue, None)
        if file_patch.new_path in seen_paths:
            return PatchValidationResult(
                False,
                PatchIssue(UNSAFE_PATCH, "duplicate_target_path", file_patch.new_path),
                None,
            )
        seen_paths.add(file_patch.new_path)
        if file_patch.old_path != file_patch.new_path:
            return PatchValidationResult(
                False,
                PatchIssue(UNSAFE_PATCH, "rename_or_copy_not_supported", file_patch.new_path),
                None,
            )
        path_result = _resolve_safe_target(workspace_root, file_patch.new_path)
        if isinstance(path_result, PatchIssue):
            return PatchValidationResult(False, path_result, None)
        target = path_result
        file_issue = _validate_existing_text_file(
            workspace_root,
            target,
            file_patch.new_path,
            max_bytes=max_bytes,
        )
        if file_issue is not None:
            return PatchValidationResult(False, file_issue, None)
    return PatchValidationResult(True, None, summarize_patch(patch))


def apply_patch_to_workspace(
    workspace_root: Path,
    patch: ParsedPatch,
    *,
    max_bytes: int = MAX_CONTEXT_FILE_BYTES,
) -> PatchApplyResult:
    validation = validate_patch_targets(
        workspace_root,
        patch,
        max_bytes=max_bytes,
    )
    if not validation.ok:
        return PatchApplyResult(
            applied=False,
            issue=validation.issue,
            summary=None,
            pending_patch_cleared=True,
        )

    computed: list[tuple[Path, str]] = []
    for file_patch in patch.files:
        target = _resolve_safe_target(workspace_root, file_patch.new_path)
        if isinstance(target, PatchIssue):
            return PatchApplyResult(False, target, None, True)
        try:
            current_text = target.read_bytes().decode("utf-8")
        except OSError:
            return PatchApplyResult(
                False,
                PatchIssue(UNSAFE_PATCH, "read_error", file_patch.new_path),
                None,
                True,
            )
        except UnicodeDecodeError:
            return PatchApplyResult(
                False,
                PatchIssue(UNSAFE_PATCH, "binary_or_non_text", file_patch.new_path),
                None,
                True,
            )
        applied = _apply_file_patch(current_text, file_patch)
        if isinstance(applied, PatchIssue):
            return PatchApplyResult(
                applied=False,
                issue=applied,
                summary=None,
                pending_patch_cleared=False,
            )
        computed.append((target, applied))

    for target, new_text in computed:
        try:
            target.write_bytes(new_text.encode("utf-8"))
        except OSError:
            return PatchApplyResult(
                False,
                PatchIssue(APPLY_IO_ERROR, "write_error", None),
                None,
                True,
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
            return PatchIssue(PATCH_PREIMAGE_MISMATCH, "hunk_location_mismatch", file_patch.new_path)
        result_lines.extend(original_lines[cursor:start])
        preimage = [line.text for line in hunk.lines if line.kind in {" ", "-"}]
        if original_lines[start : start + len(preimage)] != preimage:
            return PatchIssue(PATCH_PREIMAGE_MISMATCH, "hunk_preimage_mismatch", file_patch.new_path)
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


def _is_unsupported_metadata(line: str) -> bool:
    return line.startswith(_UNSUPPORTED_METADATA_PREFIXES)


def _validate_prefixed_pair(old_path: str, new_path: str) -> PatchIssue | None:
    if old_path == "/dev/null" or new_path == "/dev/null":
        return PatchIssue(UNSAFE_PATCH, "new_or_deleted_file_not_supported", None)
    if not old_path.startswith("a/") or not new_path.startswith("b/"):
        return PatchIssue(INVALID_PATCH_PROPOSAL, "missing_path_prefix", None)
    old_ref = _strip_diff_prefix(old_path)
    new_ref = _strip_diff_prefix(new_path)
    if old_ref != new_ref:
        return PatchIssue(UNSAFE_PATCH, "rename_or_copy_not_supported", new_ref)
    return _validate_relative_path(new_ref)


def _validate_file_headers(
    diff_old_path: str,
    diff_new_path: str,
    old_file_path: str,
    new_file_path: str,
) -> PatchIssue | None:
    if old_file_path == "/dev/null" or new_file_path == "/dev/null":
        return PatchIssue(UNSAFE_PATCH, "new_or_deleted_file_not_supported", None)
    if old_file_path != diff_old_path or new_file_path != diff_new_path:
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
    name = path.name
    lower_name = name.lower()
    suffix = path.suffix.lower()
    if not source_ref or source_ref.strip() != source_ref:
        return PatchIssue(UNSAFE_PATCH, "empty_or_ambiguous_path", source_ref or None)
    if "\\" in source_ref or "\t" in source_ref or "\r" in source_ref:
        return PatchIssue(UNSAFE_PATCH, "empty_or_ambiguous_path", source_ref)
    if path.is_absolute() or re.match(r"^[A-Za-z]:/", source_ref):
        return PatchIssue(UNSAFE_PATCH, "absolute_path", None)
    if ".." in parts:
        return PatchIssue(UNSAFE_PATCH, "path_traversal", None)
    if any(part.startswith(".") for part in parts):
        if name == ".env" or name.startswith(".env."):
            return PatchIssue(UNSAFE_PATCH, "secret_like_path", source_ref)
        return PatchIssue(UNSAFE_PATCH, "hidden_path", source_ref)
    if any(part.lower() in _UNSAFE_DIRECTORY_NAMES for part in parts):
        return PatchIssue(UNSAFE_PATCH, "unsafe_directory", source_ref)
    if name == ".env" or name.startswith(".env."):
        return PatchIssue(UNSAFE_PATCH, "secret_like_path", source_ref)
    if _is_private_key_like_ref(source_ref):
        return PatchIssue(UNSAFE_PATCH, "secret_like_path", source_ref)
    if lower_name in _UNSAFE_FILE_NAMES:
        return PatchIssue(UNSAFE_PATCH, "generated_artifact", source_ref)
    if suffix in _UNSAFE_SUFFIXES:
        if suffix in {".db", ".sqlite", ".sqlite3"}:
            reason = "local_database"
        elif suffix in {".log", ".out"}:
            reason = "log_file"
        elif suffix == ".jsonl":
            reason = "jsonl_stream"
        else:
            reason = "generated_artifact"
        return PatchIssue(UNSAFE_PATCH, reason, source_ref)
    return None


def _is_private_key_like_ref(source_ref: str) -> bool:
    path = Path(source_ref)
    name = path.name
    lower_name = name.lower()
    return (
        ".ssh" in path.parts
        or name in SECRET_FILE_NAMES
        or lower_name.endswith("_rsa")
        or lower_name.endswith("_dsa")
        or lower_name.endswith("_ed25519")
        or path.suffix.lower() in _PRIVATE_KEY_SUFFIXES
    )


def _resolve_safe_target(workspace_root: Path, source_ref: str) -> Path | PatchIssue:
    root = workspace_root.resolve()
    target = root / source_ref
    if target.is_symlink():
        return PatchIssue(UNSAFE_PATCH, "symlink_target", source_ref)
    try:
        resolved = target.resolve()
        resolved.relative_to(root)
    except ValueError:
        return PatchIssue(UNSAFE_PATCH, "path_outside_workspace", None)
    except OSError:
        return PatchIssue(UNSAFE_PATCH, "read_error", source_ref)
    return resolved


def _validate_existing_text_file(
    workspace_root: Path,
    path: Path,
    source_ref: str,
    *,
    max_bytes: int,
) -> PatchIssue | None:
    try:
        if path.is_symlink():
            return PatchIssue(UNSAFE_PATCH, "symlink_target", source_ref)
        if not path.is_file():
            return PatchIssue(UNSAFE_PATCH, "target_not_existing_file", source_ref)
        if workspace_relative_ref(workspace_root, path) != source_ref:
            return PatchIssue(UNSAFE_PATCH, "path_outside_workspace", None)
        size = path.stat().st_size
        if size > max_bytes:
            return PatchIssue(UNSAFE_PATCH, "file_too_large", source_ref)
        raw = path.read_bytes()
    except OSError:
        return PatchIssue(UNSAFE_PATCH, "read_error", source_ref)
    prefix = raw[:_TEXT_PREFIX_BYTES]
    if b"\x00" in prefix:
        return PatchIssue(UNSAFE_PATCH, "binary_or_non_text", source_ref)
    try:
        prefix_text = prefix.decode("utf-8")
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return PatchIssue(UNSAFE_PATCH, "binary_or_non_text", source_ref)
    if _contains_private_key_marker(prefix_text) or _contains_private_key_marker(text):
        return PatchIssue(UNSAFE_PATCH, "secret_like_file", source_ref)
    return None


def _contains_private_key_marker(text: str) -> bool:
    return any(marker in text for marker in PRIVATE_KEY_MARKERS)
