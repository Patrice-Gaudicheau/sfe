"""Compact diagnostics for invalid patch proposal responses."""

from __future__ import annotations

import json
from dataclasses import dataclass

from sfe.patching import (
    _FENCED_BLOCK_RE,
    _safe_trailing_text_after_diff,
    extract_first_parseable_git_diff_segment,
    extract_single_fenced_git_diff,
    parse_unified_diff,
)


PATCH_PROPOSAL_FIRST_LINE_MAX_CHARS = 160
PATCH_PROPOSAL_CONTEXT_BEFORE_LINES = 3
PATCH_PROPOSAL_CONTEXT_AFTER_LINES = 10
PATCH_PROPOSAL_CONTEXT_MAX_LINES = (
    PATCH_PROPOSAL_CONTEXT_BEFORE_LINES + 1 + PATCH_PROPOSAL_CONTEXT_AFTER_LINES
)
PATCH_PROPOSAL_CONTEXT_LINE_MAX_CHARS = 160
PATCH_PROPOSAL_CONTEXT_MAX_CHARS = 2400


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
    first_diff_git_header_offset: int | None
    first_diff_git_header_line_index: int | None
    diff_git_header_context_preview: tuple[str, ...]
    has_preamble_before_diff: bool
    preamble_line_count: int
    has_trailing_text_after_diff: bool | None
    contains_old_file_header: bool
    contains_new_file_header: bool
    contains_hunk_header: bool
    looks_like_json: bool
    mentions_selected_paths: tuple[str, ...]
    looks_like_plain_text_or_markdown: bool
    strict_parse_succeeded: bool = False
    strict_parse_issue_reason: str | None = None
    fenced_extraction_attempted: bool = False
    fenced_extraction_succeeded: bool = False
    fenced_extraction_failure_reason: str | None = None
    raw_segment_extraction_attempted: bool = False
    raw_segment_extraction_succeeded: bool = False
    raw_segment_candidate_started: bool = False
    raw_segment_candidate_line_count: int | None = None
    raw_segment_parse_issue_reason: str | None = None
    raw_segment_extraction_failure_reason: str | None = None
    final_extraction_succeeded: bool = False
    final_parse_issue_reason: str | None = None


def build_patch_proposal_diagnostics(
    raw_output: str,
    *,
    selected_source_refs: tuple[str, ...] = (),
) -> PatchProposalDiagnostics:
    stripped = raw_output.strip()
    first_line = _first_non_empty_line(raw_output)
    contains_diff_git_header = _contains_line_prefix(raw_output, "diff --git ")
    diff_git_header_offset = _line_prefix_offset(raw_output, "diff --git ")
    diff_git_header_line_index = _line_prefix_index(raw_output, "diff --git ")
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
    extraction = _patch_extraction_diagnostics(raw_output)
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
        first_diff_git_header_offset=diff_git_header_offset,
        first_diff_git_header_line_index=diff_git_header_line_index,
        diff_git_header_context_preview=_diff_git_header_context_preview(
            raw_output,
            diff_git_header_line_index,
        ),
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
        strict_parse_succeeded=extraction["strict_parse_succeeded"],
        strict_parse_issue_reason=extraction["strict_parse_issue_reason"],
        fenced_extraction_attempted=extraction["fenced_extraction_attempted"],
        fenced_extraction_succeeded=extraction["fenced_extraction_succeeded"],
        fenced_extraction_failure_reason=extraction["fenced_extraction_failure_reason"],
        raw_segment_extraction_attempted=extraction["raw_segment_extraction_attempted"],
        raw_segment_extraction_succeeded=extraction["raw_segment_extraction_succeeded"],
        raw_segment_candidate_started=extraction["raw_segment_candidate_started"],
        raw_segment_candidate_line_count=extraction["raw_segment_candidate_line_count"],
        raw_segment_parse_issue_reason=extraction["raw_segment_parse_issue_reason"],
        raw_segment_extraction_failure_reason=extraction[
            "raw_segment_extraction_failure_reason"
        ],
        final_extraction_succeeded=extraction["final_extraction_succeeded"],
        final_parse_issue_reason=extraction["final_parse_issue_reason"],
    )


def _patch_extraction_diagnostics(raw_output: str) -> dict[str, bool | int | str | None]:
    strict_parse = parse_unified_diff(raw_output)
    strict_succeeded = strict_parse.patch is not None and strict_parse.summary is not None
    strict_reason = strict_parse.issue.reason if strict_parse.issue is not None else None
    diagnostics: dict[str, bool | str | None] = {
        "strict_parse_succeeded": strict_succeeded,
        "strict_parse_issue_reason": strict_reason,
        "fenced_extraction_attempted": False,
        "fenced_extraction_succeeded": False,
        "fenced_extraction_failure_reason": None,
        "raw_segment_extraction_attempted": False,
        "raw_segment_extraction_succeeded": False,
        "raw_segment_candidate_started": False,
        "raw_segment_candidate_line_count": None,
        "raw_segment_parse_issue_reason": None,
        "raw_segment_extraction_failure_reason": None,
        "final_extraction_succeeded": strict_succeeded,
        "final_parse_issue_reason": None if strict_succeeded else strict_reason,
    }
    if strict_succeeded or strict_reason != "missing_diff_header":
        return diagnostics

    diagnostics["fenced_extraction_attempted"] = True
    diagnostics["fenced_extraction_failure_reason"] = _fenced_extraction_failure_reason(
        raw_output
    )
    fenced_diff = extract_single_fenced_git_diff(raw_output)
    if fenced_diff is not None:
        diagnostics["fenced_extraction_succeeded"] = True
        diagnostics["fenced_extraction_failure_reason"] = None
        diagnostics["final_extraction_succeeded"] = True
        diagnostics["final_parse_issue_reason"] = None
        return diagnostics

    diagnostics["raw_segment_extraction_attempted"] = True
    raw_diagnostics = _raw_segment_extraction_diagnostics(raw_output)
    diagnostics.update(raw_diagnostics)
    extracted_diff = extract_first_parseable_git_diff_segment(raw_output)
    if extracted_diff is not None:
        diagnostics["raw_segment_extraction_succeeded"] = True
        diagnostics["raw_segment_extraction_failure_reason"] = None
        diagnostics["final_extraction_succeeded"] = True
        diagnostics["final_parse_issue_reason"] = None
    elif diagnostics["raw_segment_parse_issue_reason"] is not None:
        diagnostics["final_parse_issue_reason"] = diagnostics[
            "raw_segment_parse_issue_reason"
        ]
    return diagnostics


def _fenced_extraction_failure_reason(raw_output: str) -> str | None:
    stripped = raw_output.strip()
    if not stripped:
        return "empty_output"
    matches = list(_FENCED_BLOCK_RE.finditer(stripped))
    if not matches:
        return "no_fenced_block"
    if len(matches) > 1:
        return "multiple_fenced_blocks"
    body = matches[0].group("body").strip()
    if not body.startswith("diff --git "):
        return "fenced_body_missing_diff_header"
    parsed = parse_unified_diff(body)
    if parsed.patch is None or parsed.summary is None:
        return (
            parsed.issue.reason
            if parsed.issue is not None
            else "fenced_body_not_parseable"
        )
    return None


def _raw_segment_extraction_diagnostics(
    raw_output: str,
) -> dict[str, bool | int | str | None]:
    lines = raw_output.splitlines()
    start_index = _first_git_diff_line_index(lines)
    diagnostics: dict[str, bool | int | str | None] = {
        "raw_segment_candidate_started": start_index is not None,
        "raw_segment_candidate_line_count": None,
        "raw_segment_parse_issue_reason": None,
        "raw_segment_extraction_failure_reason": None,
    }
    if start_index is None:
        diagnostics["raw_segment_extraction_failure_reason"] = "no_diff_git_header"
        return diagnostics

    suffix_lines = lines[start_index:]
    suffix = "\n".join(suffix_lines)
    diagnostics["raw_segment_candidate_line_count"] = len(suffix_lines)
    suffix_parse = parse_unified_diff(suffix)
    if suffix_parse.patch is not None and suffix_parse.summary is not None:
        return diagnostics
    diagnostics["raw_segment_parse_issue_reason"] = (
        suffix_parse.issue.reason if suffix_parse.issue is not None else None
    )

    for end_index in range(len(suffix_lines) - 1, 0, -1):
        candidate = "\n".join(suffix_lines[:end_index])
        parsed = parse_unified_diff(candidate)
        if parsed.patch is None or parsed.summary is None:
            continue
        trailing_lines = suffix_lines[end_index:]
        if _safe_trailing_text_after_diff(trailing_lines):
            return diagnostics
        diagnostics[
            "raw_segment_extraction_failure_reason"
        ] = "unsafe_trailing_text_after_parseable_segment"
        return diagnostics

    diagnostics["raw_segment_extraction_failure_reason"] = "no_parseable_raw_segment"
    return diagnostics


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


def _line_prefix_index(raw_output: str, prefix: str) -> int | None:
    for index, line in enumerate(raw_output.splitlines()):
        if line.startswith(prefix):
            return index
    return None


def _first_git_diff_line_index(lines: list[str]) -> int | None:
    for index, line in enumerate(lines):
        if line.startswith("diff --git "):
            return index
    return None


def _diff_git_header_context_preview(
    raw_output: str,
    line_index: int | None,
) -> tuple[str, ...]:
    if line_index is None:
        return ()
    lines = raw_output.splitlines()
    start = max(0, line_index - PATCH_PROPOSAL_CONTEXT_BEFORE_LINES)
    end = min(
        len(lines),
        line_index + PATCH_PROPOSAL_CONTEXT_AFTER_LINES + 1,
    )
    preview: list[str] = []
    total_chars = 0
    for index, line in enumerate(lines[start:end], start=start):
        rendered = f"{index + 1}: {_safe_preview_line(line)}"
        if total_chars + len(rendered) > PATCH_PROPOSAL_CONTEXT_MAX_CHARS:
            break
        preview.append(rendered)
        total_chars += len(rendered)
        if len(preview) >= PATCH_PROPOSAL_CONTEXT_MAX_LINES:
            break
    return tuple(preview)


def _safe_preview_line(line: str) -> str:
    rendered = repr(line)
    lowered = rendered.lower()
    if "sk-" in lowered or "api_key" in lowered or "authorization" in lowered:
        return "'[redacted]'"
    if len(rendered) <= PATCH_PROPOSAL_CONTEXT_LINE_MAX_CHARS:
        return rendered
    return rendered[: PATCH_PROPOSAL_CONTEXT_LINE_MAX_CHARS - 4].rstrip() + "...'"


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
