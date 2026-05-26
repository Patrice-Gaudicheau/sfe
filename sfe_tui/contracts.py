"""Compatibility re-exports for SFE contract primitives.

Neutral contract and context-loading definitions now live in ``sfe.contracts``.
This module keeps existing TUI imports stable during the core/TUI decoupling.
"""

from sfe.contracts import (
    DEFAULT_INSTRUCTIONS,
    MAX_CONTEXT_FILE_BYTES,
    PRIVATE_KEY_MARKERS,
    SECRET_FILE_NAMES,
    SOURCE_OR_DOCUMENTATION_EXTENSIONS,
    ContextLoadResult,
    ContextSegment,
    ProtectedText,
    SFEContract,
    approximate_token_count,
    build_contract,
    context_segment_id,
    load_context_file,
    resolve_context_path,
    resolve_workspace,
    text_length_bucket,
    workspace_relative_ref,
)


__all__ = [
    "DEFAULT_INSTRUCTIONS",
    "MAX_CONTEXT_FILE_BYTES",
    "PRIVATE_KEY_MARKERS",
    "SECRET_FILE_NAMES",
    "SOURCE_OR_DOCUMENTATION_EXTENSIONS",
    "ContextLoadResult",
    "ContextSegment",
    "ProtectedText",
    "SFEContract",
    "approximate_token_count",
    "build_contract",
    "context_segment_id",
    "load_context_file",
    "resolve_context_path",
    "resolve_workspace",
    "text_length_bucket",
    "workspace_relative_ref",
]
