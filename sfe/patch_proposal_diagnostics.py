"""Compact diagnostics for invalid patch proposal responses."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sfe.patching import extract_first_parseable_git_diff_segment


PATCH_PROPOSAL_FIRST_LINE_MAX_CHARS = 160


@dataclass(frozen=True)
class PatchProposalDiagnostics:
    raw_output_length: int
    is_empty: bool
    first_non_empty_line: str | None
    starts_with_markdown_fence: bool
    contains_fenced_diff: bool
    contains_diff_git_header: bool
    starts_with_diff_git: bool
    diff_git_header_offset: int | None
    has_preamble_before_diff: bool
    preamble_line_count: int
    has_trailing_text_after_diff: bool | None
    contains_old_file_header: bool
    contains_new_file_header: bool
    contains_hunk_header: bool
    looks_like_json: bool
    mentions_selected_paths: tuple[str, ...]
    looks_like_plain_text_or_markdown: bool


def build_patch_proposal_diagnostics(
    raw_output: str,
    *,
    selected_source_refs: tuple[str, ...] = (),
) -> PatchProposalDiagnostics:
    stripped = raw_output.strip()
    first_line = _first_non_empty_line(raw_output)
    contains_diff_git_header = _contains_line_prefix(raw_output, "diff --git ")
    diff_git_header_offset = _line_prefix_offset(raw_output, "diff --git ")
    contains_old_file_header = _contains_line_prefix(raw_output, "--- ")
    contains_new_file_header = _contains_line_prefix(raw_output, "+++ ")
    contains_hunk_header = _contains_line_prefix(raw_output, "@@")
    looks_like_json = _looks_like_json(stripped)
    starts_with_markdown_fence = stripped.startswith("```")
    starts_with_diff_git = stripped.startswith("diff --git ")
    preamble_line_count = _preamble_line_count(raw_output, diff_git_header_offset)
    has_preamble_before_diff = preamble_line_count > 0
    has_trailing_text_after_diff = _has_trailing_text_after_diff(raw_output)
    contains_fenced_diff = "```diff" in raw_output.lower()
    mentions_selected_paths = tuple(
        ref for ref in selected_source_refs if ref and ref in raw_output
    )
    return PatchProposalDiagnostics(
        raw_output_length=len(raw_output),
        is_empty=not bool(stripped),
        first_non_empty_line=first_line,
        starts_with_markdown_fence=starts_with_markdown_fence,
        contains_fenced_diff=contains_fenced_diff,
        contains_diff_git_header=contains_diff_git_header,
        starts_with_diff_git=starts_with_diff_git,
        diff_git_header_offset=diff_git_header_offset,
        has_preamble_before_diff=has_preamble_before_diff,
        preamble_line_count=preamble_line_count,
        has_trailing_text_after_diff=has_trailing_text_after_diff,
        contains_old_file_header=contains_old_file_header,
        contains_new_file_header=contains_new_file_header,
        contains_hunk_header=contains_hunk_header,
        looks_like_json=looks_like_json,
        mentions_selected_paths=mentions_selected_paths,
        looks_like_plain_text_or_markdown=(
            bool(stripped)
            and not looks_like_json
            and not contains_diff_git_header
            and not contains_hunk_header
        ),
    )


def _first_non_empty_line(raw_output: str) -> str | None:
    for line in raw_output.splitlines():
        stripped = line.strip()
        if stripped:
            return _truncate_line(stripped)
    return None


def _truncate_line(line: str) -> str:
    if len(line) <= PATCH_PROPOSAL_FIRST_LINE_MAX_CHARS:
        return line
    return line[:PATCH_PROPOSAL_FIRST_LINE_MAX_CHARS].rstrip() + "..."


def _contains_line_prefix(raw_output: str, prefix: str) -> bool:
    return any(line.startswith(prefix) for line in raw_output.splitlines())


def _line_prefix_offset(raw_output: str, prefix: str) -> int | None:
    offset = 0
    for line in raw_output.splitlines(keepends=True):
        line_without_ending = line.rstrip("\r\n")
        if line_without_ending.startswith(prefix):
            return offset
        offset += len(line)
    return None


def _preamble_line_count(raw_output: str, diff_offset: int | None) -> int:
    if diff_offset is None:
        return 0
    preamble = raw_output[:diff_offset]
    return sum(1 for line in preamble.splitlines() if line.strip())


def _has_trailing_text_after_diff(raw_output: str) -> bool | None:
    segment = extract_first_parseable_git_diff_segment(raw_output)
    if segment is None:
        return None
    diff_offset = _line_prefix_offset(raw_output, "diff --git ")
    if diff_offset is None:
        return None
    suffix = raw_output[diff_offset:].strip()
    return suffix != segment.strip()


def _looks_like_json(stripped: str) -> bool:
    if not stripped or stripped[0] not in "[{":
        return False
    try:
        json.loads(stripped)
    except json.JSONDecodeError:
        return True
    return True
