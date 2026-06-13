"""Core text transport contract for workspace_write executors."""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath


SFE_FILE_END_MARKER = "<<<END_SFE_FILE>>>"
NONCANONICAL_SFE_FILE_END_MARKERS = frozenset(
    {
        "</SFE_FILE>>>",
        "</SFE_FILE>",
    }
)
SFE_FILE_START_RE = re.compile(r'^<<<SFE_FILE path="(?P<path>[^"]+)">[ \t]*$')

WORKSPACE_WRITE_TEXT_TRANSPORT_INSTRUCTION = (
    "You are the SFE workspace_write executor on a text-only provider path. "
    "This provider cannot write files directly into the controlled worktree. "
    "Return every created or modified file as a full-file SFE_FILE block. Use "
    "this exact shape: <<<SFE_FILE path=\"relative/path\">, then the exact file "
    "contents, then <<<END_SFE_FILE>>>. Close every file block with exactly "
    "<<<END_SFE_FILE>>>. Do not use XML tags such as </SFE_FILE>. Use relative "
    "workspace paths only; never use absolute paths or ../ traversal. Do not "
    "claim files were created unless you include their SFE_FILE blocks or a "
    "valid supported Git diff. SFE ignores prose outside file blocks, writes "
    "the recovered blocks into a controlled worktree, then enforce the "
    "destination-directory boundary. A "
    "strict unified diff/git diff remains accepted as a compatibility path; if "
    "you use it, start with diff --git a/<relative-path> b/<relative-path>. Do "
    "not return JSON. Do not return an edits array. Keep changes focused on "
    "the user task."
)


def sfe_file_closing_marker_kind(line: str) -> str | None:
    stripped = line.strip()
    if stripped == SFE_FILE_END_MARKER:
        return "canonical"
    if stripped in NONCANONICAL_SFE_FILE_END_MARKERS:
        return "noncanonical"
    return None


def is_invalid_sfe_file_path(path: str) -> bool:
    if not path or path.strip() != path:
        return True
    parsed = Path(path)
    windows_parsed = PureWindowsPath(path)
    if (
        parsed.is_absolute()
        or windows_parsed.is_absolute()
        or ".." in parsed.parts
        or ".." in windows_parsed.parts
    ):
        return True
    return False
