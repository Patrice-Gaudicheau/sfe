"""Structured file patch proposals for TUI patch application.

The parsing, validation, summary, preview, and application mechanics live in
``sfe.patching`` so future SFE surfaces inherit the same safety behavior.
"""

from __future__ import annotations

from sfe.patching import (
    PHYSICAL_WRITE_FAILURE,
    SUPPORTED_CREATE_ACTION,
    SUPPORTED_REPLACE_ACTION,
    UNSUPPORTED_EDIT_FORMAT,
    UNSUPPORTED_PENDING_PATCH_FORMAT,
    StructuredFileEdit as FileReplacementEdit,
    StructuredFilePatch as FileReplacementProposal,
    StructuredFilePatchParseResult as FileReplacementParseResult,
    apply_structured_file_patch as apply_file_replacements,
    generate_structured_file_patch_diff_preview as generate_replacement_diff_preview,
    parse_structured_file_patch_json as parse_file_replacement_proposal,
    summarize_structured_file_patch as summarize_file_replacements,
)


SUPPORTED_ACTIONS = frozenset({SUPPORTED_REPLACE_ACTION, SUPPORTED_CREATE_ACTION})
