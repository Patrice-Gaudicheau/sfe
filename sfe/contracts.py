"""Neutral SFE request contracts and workspace context loading helpers."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MAX_CONTEXT_FILE_BYTES = 1_000_000
SECRET_FILE_NAMES = {"id_rsa", "id_dsa", "id_ed25519", "known_hosts"}
SOURCE_OR_DOCUMENTATION_EXTENSIONS = {
    ".bash",
    ".c",
    ".cfg",
    ".cpp",
    ".cs",
    ".go",
    ".h",
    ".hpp",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".php",
    ".ps1",
    ".py",
    ".pyi",
    ".rb",
    ".rs",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
    ".zsh",
}
PRIVATE_KEY_MARKERS = (
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
)
DEFAULT_INSTRUCTIONS = (
    "Use only explicitly selected SFE context. Keep protected instructions and "
    "the user task separate from reducible context."
)


@dataclass(frozen=True)
class ProtectedText:
    id: str
    text: str
    protected: bool = True
    reducible: bool = False


@dataclass(frozen=True)
class ContextSegment:
    id: str
    source_ref: str
    text: str = ""
    protected: bool = False
    reducible: bool = True
    approx_size: int = 0
    approx_tokens: int = 0


@dataclass(frozen=True)
class ContextLoadResult:
    loaded: bool
    reason: str | None
    source_ref: str | None = None
    text: str = ""
    approx_chars: int = 0
    approx_tokens: int = 0
    size_bucket: str = "0"
    warning_reason: str | None = None


@dataclass(frozen=True)
class SFEContract:
    instructions: list[ProtectedText]
    task: ProtectedText | None
    context_segments: list[ContextSegment]
    protected_segments: list[ProtectedText]
    metadata: dict[str, Any] = field(default_factory=dict)
    audit: dict[str, Any] = field(default_factory=dict)


def resolve_workspace(raw_value: str, cwd: Path | None = None) -> Path:
    base = (cwd or Path.cwd()).resolve()
    value = raw_value.strip()
    path = base if not value else Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    resolved = path.resolve()
    if not resolved.exists():
        raise ValueError("workspace_not_found")
    if not resolved.is_dir():
        raise ValueError("workspace_not_directory")
    return resolved


def resolve_context_path(workspace_root: Path, raw_value: str) -> Path:
    value = raw_value.strip()
    if not value:
        raise ValueError("empty_path")
    root = workspace_root.resolve()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("path_outside_workspace") from exc
    if not resolved.exists():
        raise ValueError("path_not_found")
    return resolved


def load_context_file(
    workspace_root: Path,
    raw_value: str,
    *,
    max_bytes: int = MAX_CONTEXT_FILE_BYTES,
) -> ContextLoadResult:
    try:
        path = resolve_context_path(workspace_root, raw_value)
    except ValueError as exc:
        return ContextLoadResult(loaded=False, reason=_load_reason_from_error(exc))

    source_ref = workspace_relative_ref(workspace_root, path)
    if _is_secret_like_path(source_ref):
        return ContextLoadResult(
            loaded=False,
            reason="secret_like_file",
            source_ref=source_ref,
        )
    try:
        if not path.is_file():
            return ContextLoadResult(
                loaded=False,
                reason="not_a_file",
                source_ref=source_ref,
            )
        size = path.stat().st_size
        if size > max_bytes:
            return ContextLoadResult(
                loaded=False,
                reason="file_too_large",
                source_ref=source_ref,
            )
        raw = path.read_bytes()
    except OSError:
        return ContextLoadResult(
            loaded=False,
            reason="read_error",
            source_ref=source_ref,
        )

    prefix = raw[:4096]
    if b"\x00" in prefix:
        return ContextLoadResult(
            loaded=False,
            reason="binary_or_non_text",
            source_ref=source_ref,
        )
    try:
        prefix_text = prefix.decode("utf-8")
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ContextLoadResult(
            loaded=False,
            reason="binary_or_non_text",
            source_ref=source_ref,
        )
    marker_found = _contains_private_key_marker(prefix_text) or (
        _contains_private_key_marker(text)
    )
    if marker_found and not _is_source_or_documentation_path(source_ref):
        return ContextLoadResult(
            loaded=False,
            reason="secret_like_file",
            source_ref=source_ref,
        )
    warning_reason = "secret_marker_literal_in_source" if marker_found else None
    approx_chars = len(text)
    return ContextLoadResult(
        loaded=True,
        reason=None,
        source_ref=source_ref,
        text=text,
        approx_chars=approx_chars,
        approx_tokens=approximate_token_count(text),
        size_bucket=text_length_bucket(approx_chars),
        warning_reason=warning_reason,
    )


def workspace_relative_ref(workspace_root: Path, path: Path) -> str:
    return path.resolve().relative_to(workspace_root.resolve()).as_posix()


def context_segment_id(source_ref: str) -> str:
    digest = hashlib.sha256(source_ref.encode("utf-8")).hexdigest()[:16]
    return f"ctx_{digest}"


def approximate_token_count(text: str) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / 4)


def text_length_bucket(text_chars: int) -> str:
    if text_chars <= 0:
        return "0"
    if text_chars <= 128:
        return "1-128"
    if text_chars <= 512:
        return "129-512"
    if text_chars <= 2_048:
        return "513-2048"
    if text_chars <= 8_192:
        return "2049-8192"
    return "8193+"


def build_contract(
    *,
    workspace_root: Path | None,
    task: str,
    file_paths: list[Path],
    context_files: list[ContextLoadResult] | None = None,
    instructions: str = DEFAULT_INSTRUCTIONS,
) -> SFEContract:
    context_segments: list[ContextSegment] = []
    load_results = (
        context_files
        if context_files is not None
        else [_loaded_context_from_path(workspace_root, path) for path in file_paths]
    )
    for result in load_results:
        if not result.loaded or result.source_ref is None:
            continue
        source_ref = result.source_ref
        context_segments.append(
            ContextSegment(
                id=context_segment_id(source_ref),
                source_ref=source_ref,
                text=result.text,
                approx_size=result.approx_chars,
                approx_tokens=result.approx_tokens,
            )
        )

    instruction_items = [
        ProtectedText(id="instructions_default", text=instructions),
    ]
    task_item = (
        ProtectedText(id="task_current", text=task)
        if task.strip()
        else None
    )
    protected_segments: list[ProtectedText] = []
    metadata = {
        "workspace_root_present": workspace_root is not None,
        "context_segment_count": len(context_segments),
        "protected_segment_count": len(protected_segments),
        "protected_instruction_count": len(instruction_items),
        "reducible_segment_count": sum(1 for item in context_segments if item.reducible),
        "context_segment_ids": [item.id for item in context_segments],
        "approx_context_sizes": [item.approx_size for item in context_segments],
        "approx_context_tokens": [item.approx_tokens for item in context_segments],
        "total_approx_context_chars": sum(item.approx_size for item in context_segments),
        "total_approx_context_tokens": sum(
            item.approx_tokens for item in context_segments
        ),
        "requested_file_count": len(load_results),
        "loaded_context_file_count": sum(1 for item in load_results if item.loaded),
        "skipped_file_count": sum(1 for item in load_results if not item.loaded),
        "skipped_reason_counts": _skipped_reason_counts(load_results),
        "warning_reason_counts": _warning_reason_counts(load_results),
        "context_size_buckets": _size_bucket_counts(context_segments),
    }
    audit = {
        "selected_segment_ids": [],
        "router_token_estimate": None,
        "executor_token_estimate": None,
        "fallback_reason": None,
    }
    return SFEContract(
        instructions=instruction_items,
        task=task_item,
        context_segments=context_segments,
        protected_segments=protected_segments,
        metadata=metadata,
        audit=audit,
    )


def _loaded_context_from_path(
    workspace_root: Path | None,
    path: Path,
) -> ContextLoadResult:
    if workspace_root is not None:
        return load_context_file(workspace_root, str(path))
    source_ref = path.name
    return ContextLoadResult(
        loaded=True,
        reason=None,
        source_ref=source_ref,
        text="",
        approx_chars=0,
        approx_tokens=0,
        size_bucket="0",
    )


def _load_reason_from_error(exc: ValueError) -> str:
    value = str(exc)
    if value == "path_outside_workspace":
        return "outside_workspace"
    if value == "path_not_found":
        return "read_error"
    if value == "empty_path":
        return "read_error"
    return "read_error"


def _is_secret_like_path(source_ref: str) -> bool:
    parts = Path(source_ref).parts
    name = parts[-1] if parts else source_ref
    return (
        ".ssh" in parts
        or name == ".env"
        or name.startswith(".env.")
        or name in SECRET_FILE_NAMES
    )


def _is_source_or_documentation_path(source_ref: str) -> bool:
    return Path(source_ref).suffix.lower() in SOURCE_OR_DOCUMENTATION_EXTENSIONS


def _contains_private_key_marker(text: str) -> bool:
    return any(marker in text for marker in PRIVATE_KEY_MARKERS)


def _skipped_reason_counts(results: list[ContextLoadResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if result.loaded:
            continue
        reason = result.reason or "read_error"
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def _warning_reason_counts(results: list[ContextLoadResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if not result.loaded or result.warning_reason is None:
            continue
        counts[result.warning_reason] = counts.get(result.warning_reason, 0) + 1
    return dict(sorted(counts.items()))


def _size_bucket_counts(segments: list[ContextSegment]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for segment in segments:
        bucket = text_length_bucket(segment.approx_size)
        counts[bucket] = counts.get(bucket, 0) + 1
    return dict(sorted(counts.items()))
