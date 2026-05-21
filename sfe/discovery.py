"""Provider-free workspace discovery for reusable SFE context selection."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, replace
from pathlib import Path

from sfe_tui.contracts import (
    ContextLoadResult,
    PRIVATE_KEY_MARKERS,
    SECRET_FILE_NAMES,
    approximate_token_count,
    load_context_file,
    text_length_bucket,
    workspace_relative_ref,
)


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
_TEXT_PREFIX_BYTES = 4096
_CANDIDATE_EXTENSIONS = {
    ".cfg",
    ".ini",
    ".json",
    ".md",
    ".py",
    ".rst",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
_DIRECTORY_EXCLUSIONS = {
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
_FILE_NAME_EXCLUSIONS = {
    ".coverage",
    ".ds_store",
    "coverage.xml",
    "thumbs.db",
}
_FILE_SUFFIX_EXCLUSIONS = {
    ".db",
    ".jsonl",
    ".log",
    ".out",
    ".p12",
    ".pem",
    ".pfx",
    ".pyc",
    ".sqlite",
    ".sqlite3",
}
_PRIVATE_KEY_SUFFIXES = {".key"}
_SPECIAL_CANDIDATE_NAMES = {"Makefile", ".env.example"}


@dataclass(frozen=True)
class DiscoveryPolicy:
    max_files_scanned: int = 300
    max_candidates: int = 40
    max_loaded_candidates: int = 20
    max_file_bytes: int = 1_000_000
    max_total_loaded_bytes: int = 2_000_000
    include_hidden: bool = False
    respect_gitignore: bool = True


@dataclass(frozen=True)
class DiscoveryCandidate:
    source_ref: str
    approx_bytes: int
    score: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryResult:
    workspace_root_present: bool
    task_present: bool
    scanned_file_count: int
    candidate_count: int
    loaded_candidate_count: int
    skipped_candidate_count: int
    stop_reason: str | None
    candidates: tuple[DiscoveryCandidate, ...]
    load_results: tuple[ContextLoadResult, ...]
    skipped_reason_counts: dict[str, int]
    warning_reason_counts: dict[str, int]


@dataclass(frozen=True)
class _ScannedFile:
    path: Path
    source_ref: str
    approx_bytes: int
    text_prefix: str


@dataclass(frozen=True)
class _GitignoreRule:
    pattern: str
    negated: bool
    directory_only: bool


def discover_workspace_context(
    *,
    workspace_root: Path | None,
    task: str,
    policy: DiscoveryPolicy = DiscoveryPolicy(),
) -> DiscoveryResult:
    """Discover a deterministic candidate pool from a workspace.

    The returned object is safe to render: source refs are workspace-relative and
    loaded context results have their text fields scrubbed.
    """

    task_present = bool(task.strip())
    workspace_root_present = _workspace_root_present(workspace_root)
    if not workspace_root_present or workspace_root is None:
        return _empty_result(
            workspace_root_present=False,
            task_present=task_present,
            stop_reason="workspace_missing",
        )
    if not task_present:
        return _empty_result(
            workspace_root_present=True,
            task_present=False,
            stop_reason="missing_task",
        )

    root = workspace_root.resolve()
    normalized_policy = _normalize_policy(policy)
    rules = (
        _load_gitignore_rules(root)
        if normalized_policy.respect_gitignore
        else tuple()
    )
    skipped_reason_counts: dict[str, int] = {}
    scanned, scanned_file_count, scan_stop_reason = _scan_workspace(
        root,
        rules=rules,
        policy=normalized_policy,
        skipped_reason_counts=skipped_reason_counts,
    )
    task_terms = _tokenize(task)
    scored = [
        _score_scanned_file(item, task_terms)
        for item in scanned
    ]
    scored.sort(key=lambda item: (-item.score, item.source_ref))

    stop_reason = scan_stop_reason
    if len(scored) > normalized_policy.max_candidates:
        _increment(
            skipped_reason_counts,
            "max_candidates",
            len(scored) - normalized_policy.max_candidates,
        )
        if stop_reason is None:
            stop_reason = "max_candidates"
    candidates = tuple(scored[: normalized_policy.max_candidates])
    load_results, load_stop_reason = _load_candidates(
        root,
        candidates,
        policy=normalized_policy,
    )
    if stop_reason is None:
        stop_reason = load_stop_reason

    for result in load_results:
        if not result.loaded:
            _increment(skipped_reason_counts, result.reason or "read_error")
    warning_reason_counts = _warning_reason_counts(load_results)
    loaded_candidate_count = sum(1 for item in load_results if item.loaded)
    return DiscoveryResult(
        workspace_root_present=True,
        task_present=True,
        scanned_file_count=scanned_file_count,
        candidate_count=len(candidates),
        loaded_candidate_count=loaded_candidate_count,
        skipped_candidate_count=len(candidates) - loaded_candidate_count,
        stop_reason=stop_reason,
        candidates=candidates,
        load_results=load_results,
        skipped_reason_counts=dict(sorted(skipped_reason_counts.items())),
        warning_reason_counts=warning_reason_counts,
    )


def load_discovered_context(
    *,
    workspace_root: Path | None,
    discovery_result: DiscoveryResult,
    policy: DiscoveryPolicy = DiscoveryPolicy(),
) -> tuple[ContextLoadResult, ...]:
    """Reload discovered candidates with full text for internal contract building."""

    if workspace_root is None or not _workspace_root_present(workspace_root):
        return tuple()
    root = workspace_root.resolve()
    normalized_policy = _normalize_policy(policy)
    load_results: list[ContextLoadResult] = []
    loaded_count = 0
    loaded_bytes = 0
    for candidate in discovery_result.candidates:
        if loaded_count >= normalized_policy.max_loaded_candidates:
            load_results.append(
                _skipped_load_result(candidate.source_ref, "max_loaded_candidates")
            )
            continue
        if loaded_bytes + candidate.approx_bytes > normalized_policy.max_total_loaded_bytes:
            load_results.append(
                _skipped_load_result(candidate.source_ref, "max_total_loaded_bytes")
            )
            continue
        loaded = load_context_file(
            root,
            candidate.source_ref,
            max_bytes=normalized_policy.max_file_bytes,
        )
        load_results.append(loaded)
        if loaded.loaded:
            loaded_count += 1
            loaded_bytes += candidate.approx_bytes
    return tuple(load_results)


def _empty_result(
    *,
    workspace_root_present: bool,
    task_present: bool,
    stop_reason: str,
) -> DiscoveryResult:
    return DiscoveryResult(
        workspace_root_present=workspace_root_present,
        task_present=task_present,
        scanned_file_count=0,
        candidate_count=0,
        loaded_candidate_count=0,
        skipped_candidate_count=0,
        stop_reason=stop_reason,
        candidates=(),
        load_results=(),
        skipped_reason_counts={},
        warning_reason_counts={},
    )


def _workspace_root_present(workspace_root: Path | None) -> bool:
    if workspace_root is None:
        return False
    try:
        return workspace_root.resolve().is_dir()
    except OSError:
        return False


def _normalize_policy(policy: DiscoveryPolicy) -> DiscoveryPolicy:
    return DiscoveryPolicy(
        max_files_scanned=max(0, policy.max_files_scanned),
        max_candidates=max(0, policy.max_candidates),
        max_loaded_candidates=max(0, policy.max_loaded_candidates),
        max_file_bytes=max(0, policy.max_file_bytes),
        max_total_loaded_bytes=max(0, policy.max_total_loaded_bytes),
        include_hidden=policy.include_hidden,
        respect_gitignore=policy.respect_gitignore,
    )


def _scan_workspace(
    root: Path,
    *,
    rules: tuple[_GitignoreRule, ...],
    policy: DiscoveryPolicy,
    skipped_reason_counts: dict[str, int],
) -> tuple[list[_ScannedFile], int, str | None]:
    discovered: list[_ScannedFile] = []
    scanned_file_count = 0
    directories = [root]
    while directories:
        current = directories.pop(0)
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            _increment(skipped_reason_counts, "read_error")
            continue
        pending_dirs: list[Path] = []
        for child in children:
            try:
                source_ref = workspace_relative_ref(root, child)
            except ValueError:
                _increment(skipped_reason_counts, "outside_workspace")
                continue
            if child.is_dir() and not child.is_symlink():
                reason = _directory_skip_reason(source_ref, child.name, rules, policy)
                if reason is not None:
                    _increment(skipped_reason_counts, reason)
                    continue
                pending_dirs.append(child)
                continue
            if not child.is_file():
                continue
            if scanned_file_count >= policy.max_files_scanned:
                return discovered, scanned_file_count, "max_files_scanned"
            scanned_file_count += 1
            scanned = _scan_file(root, child, source_ref, rules, policy)
            if isinstance(scanned, str):
                _increment(skipped_reason_counts, scanned)
                continue
            discovered.append(scanned)
        directories.extend(sorted(pending_dirs, key=lambda item: _safe_rel(root, item)))
    return discovered, scanned_file_count, None


def _scan_file(
    root: Path,
    path: Path,
    source_ref: str,
    rules: tuple[_GitignoreRule, ...],
    policy: DiscoveryPolicy,
) -> _ScannedFile | str:
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return "outside_workspace"
    reason = _file_skip_reason(source_ref, path.name, rules, policy)
    if reason is not None:
        return reason
    try:
        size = path.stat().st_size
    except OSError:
        return "read_error"
    if size > policy.max_file_bytes:
        return "file_too_large"
    try:
        raw_prefix = path.read_bytes()[:_TEXT_PREFIX_BYTES]
    except OSError:
        return "read_error"
    if b"\x00" in raw_prefix:
        return "binary_or_non_text"
    try:
        text_prefix = raw_prefix.decode("utf-8")
    except UnicodeDecodeError:
        return "binary_or_non_text"
    if _contains_private_key_marker(text_prefix) and not _is_source_or_doc_ref(
        source_ref
    ):
        return "secret_like_file"
    return _ScannedFile(
        path=path,
        source_ref=source_ref,
        approx_bytes=size,
        text_prefix=text_prefix,
    )


def _directory_skip_reason(
    source_ref: str,
    name: str,
    rules: tuple[_GitignoreRule, ...],
    policy: DiscoveryPolicy,
) -> str | None:
    normalized_name = name.lower()
    if normalized_name in _DIRECTORY_EXCLUSIONS:
        return "excluded_directory"
    if not policy.include_hidden and name.startswith("."):
        return "hidden_directory"
    if policy.respect_gitignore and _gitignore_ignored(source_ref, is_dir=True, rules=rules):
        return "gitignored"
    return None


def _file_skip_reason(
    source_ref: str,
    name: str,
    rules: tuple[_GitignoreRule, ...],
    policy: DiscoveryPolicy,
) -> str | None:
    path = Path(source_ref)
    lower_name = name.lower()
    suffix = path.suffix.lower()
    if name != ".env.example" and (name == ".env" or name.startswith(".env.")):
        return "secret_like_file"
    if _is_private_key_like_ref(source_ref):
        return "secret_like_file"
    if lower_name in _FILE_NAME_EXCLUSIONS:
        return "generated_artifact"
    if suffix in _FILE_SUFFIX_EXCLUSIONS:
        if suffix in {".db", ".sqlite", ".sqlite3"}:
            return "local_database"
        if suffix in {".log", ".out"}:
            return "log_file"
        if suffix == ".jsonl":
            return "jsonl_stream"
        return "generated_artifact"
    if policy.respect_gitignore and _gitignore_ignored(source_ref, is_dir=False, rules=rules):
        return "gitignored"
    if name not in _SPECIAL_CANDIDATE_NAMES and suffix not in _CANDIDATE_EXTENSIONS:
        return "unsupported_extension"
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


def _is_source_or_doc_ref(source_ref: str) -> bool:
    path = Path(source_ref)
    return path.name in _SPECIAL_CANDIDATE_NAMES or path.suffix.lower() in _CANDIDATE_EXTENSIONS


def _score_scanned_file(
    item: _ScannedFile,
    task_terms: set[str],
) -> DiscoveryCandidate:
    source_ref = item.source_ref
    path = Path(source_ref)
    path_terms = _tokenize(source_ref)
    name_terms = _tokenize(path.name)
    prefix_terms = _tokenize(item.text_prefix)
    score = 0
    reasons: list[str] = []

    path_matches = len(task_terms.intersection(path_terms))
    if path_matches:
        score += path_matches * 8
        reasons.append("task_path_match")
    name_matches = len(task_terms.intersection(name_terms))
    if name_matches:
        score += name_matches * 4
        reasons.append("task_name_match")
    extension = path.suffix.lower().lstrip(".")
    if extension and extension in task_terms:
        score += 3
        reasons.append("task_extension_match")
    prefix_matches = len(task_terms.intersection(prefix_terms))
    if prefix_matches:
        score += prefix_matches
        reasons.append("task_prefix_match")

    priority_score, priority_reason = _priority_score(source_ref)
    if priority_score:
        score += priority_score
        reasons.append(priority_reason)
    if not reasons:
        reasons.append("eligible")
    return DiscoveryCandidate(
        source_ref=source_ref,
        approx_bytes=item.approx_bytes,
        score=score,
        reasons=tuple(reasons),
    )


def _priority_score(source_ref: str) -> tuple[int, str]:
    if source_ref == "README.md":
        return 7, "priority_readme"
    if source_ref == "Makefile":
        return 5, "priority_makefile"
    if source_ref == ".env.example":
        return 3, "priority_env_example"
    if source_ref.startswith("sfe_tui/"):
        return 6, "priority_tui"
    if source_ref.startswith("sfe/"):
        return 6, "priority_core"
    if source_ref.startswith("tests/"):
        return 5, "priority_tests"
    if source_ref.startswith("docs/"):
        return 4, "priority_docs"
    return 0, ""


def _load_candidates(
    root: Path,
    candidates: tuple[DiscoveryCandidate, ...],
    *,
    policy: DiscoveryPolicy,
) -> tuple[tuple[ContextLoadResult, ...], str | None]:
    load_results: list[ContextLoadResult] = []
    loaded_count = 0
    loaded_bytes = 0
    stop_reason: str | None = None
    for candidate in candidates:
        if loaded_count >= policy.max_loaded_candidates:
            stop_reason = stop_reason or "max_loaded_candidates"
            load_results.append(_skipped_load_result(candidate.source_ref, "max_loaded_candidates"))
            continue
        if loaded_bytes + candidate.approx_bytes > policy.max_total_loaded_bytes:
            stop_reason = stop_reason or "max_total_loaded_bytes"
            load_results.append(_skipped_load_result(candidate.source_ref, "max_total_loaded_bytes"))
            continue
        if Path(candidate.source_ref).name == ".env.example":
            loaded = _load_env_example(
                root,
                candidate.source_ref,
                max_bytes=policy.max_file_bytes,
            )
        else:
            loaded = load_context_file(
                root,
                candidate.source_ref,
                max_bytes=policy.max_file_bytes,
            )
        safe_loaded = _safe_load_result(loaded)
        load_results.append(safe_loaded)
        if loaded.loaded:
            loaded_count += 1
            loaded_bytes += candidate.approx_bytes
    return tuple(load_results), stop_reason


def _safe_load_result(result: ContextLoadResult) -> ContextLoadResult:
    if not result.text:
        return result
    return replace(result, text="")


def _skipped_load_result(source_ref: str, reason: str) -> ContextLoadResult:
    return ContextLoadResult(
        loaded=False,
        reason=reason,
        source_ref=source_ref,
        text="",
        approx_chars=0,
        approx_tokens=0,
        size_bucket="0",
    )


def _load_env_example(
    root: Path,
    source_ref: str,
    *,
    max_bytes: int,
) -> ContextLoadResult:
    path = root / source_ref
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
        if not resolved.is_file():
            return _skipped_load_result(source_ref, "not_a_file")
        size = resolved.stat().st_size
        if size > max_bytes:
            return _skipped_load_result(source_ref, "file_too_large")
        raw = resolved.read_bytes()
    except OSError:
        return _skipped_load_result(source_ref, "read_error")
    except ValueError:
        return _skipped_load_result(source_ref, "outside_workspace")

    prefix = raw[:_TEXT_PREFIX_BYTES]
    if b"\x00" in prefix:
        return _skipped_load_result(source_ref, "binary_or_non_text")
    try:
        prefix_text = prefix.decode("utf-8")
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return _skipped_load_result(source_ref, "binary_or_non_text")
    if _contains_private_key_marker(prefix_text) or _contains_private_key_marker(text):
        return _skipped_load_result(source_ref, "secret_like_file")
    approx_chars = len(text)
    return ContextLoadResult(
        loaded=True,
        reason=None,
        source_ref=source_ref,
        text=text,
        approx_chars=approx_chars,
        approx_tokens=approximate_token_count(text),
        size_bucket=text_length_bucket(approx_chars),
    )


def _load_gitignore_rules(root: Path) -> tuple[_GitignoreRule, ...]:
    gitignore = root / ".gitignore"
    try:
        lines = gitignore.read_text(encoding="utf-8").splitlines()
    except OSError:
        return tuple()
    rules: list[_GitignoreRule] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:].strip()
        if not line:
            continue
        directory_only = line.endswith("/")
        if directory_only:
            line = line.rstrip("/")
        rules.append(
            _GitignoreRule(
                pattern=line.lstrip("/"),
                negated=negated,
                directory_only=directory_only,
            )
        )
    return tuple(rules)


def _gitignore_ignored(
    source_ref: str,
    *,
    is_dir: bool,
    rules: tuple[_GitignoreRule, ...],
) -> bool:
    ignored = False
    for rule in rules:
        if _gitignore_rule_matches(rule, source_ref, is_dir=is_dir):
            ignored = not rule.negated
    return ignored


def _gitignore_rule_matches(
    rule: _GitignoreRule,
    source_ref: str,
    *,
    is_dir: bool,
) -> bool:
    if rule.directory_only and not is_dir:
        return False
    pattern = rule.pattern
    if "/" in pattern:
        if fnmatch.fnmatchcase(source_ref, pattern):
            return True
        if rule.directory_only and source_ref.startswith(f"{pattern}/"):
            return True
        return False
    parts = source_ref.split("/")
    basename = parts[-1]
    if rule.directory_only:
        return any(fnmatch.fnmatchcase(part, pattern) for part in parts)
    return fnmatch.fnmatchcase(basename, pattern) or fnmatch.fnmatchcase(
        source_ref,
        pattern,
    )


def _tokenize(text: str) -> set[str]:
    return {
        normalized
        for token in (match.group(0).lower() for match in _TOKEN_RE.finditer(text))
        if len(token) >= 3
        for normalized in (_normalize_token(token),)
        if normalized
    }


def _normalize_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _contains_private_key_marker(text: str) -> bool:
    return any(marker in text for marker in PRIVATE_KEY_MARKERS)


def _warning_reason_counts(
    results: tuple[ContextLoadResult, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        if result.loaded and result.warning_reason is not None:
            _increment(counts, result.warning_reason)
    return dict(sorted(counts.items()))


def _increment(counts: dict[str, int], reason: str, amount: int = 1) -> None:
    counts[reason] = counts.get(reason, 0) + amount


def _safe_rel(root: Path, path: Path) -> str:
    try:
        return workspace_relative_ref(root, path)
    except ValueError:
        return path.name
