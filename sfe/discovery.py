"""LLM-driven workspace discovery for reusable SFE context selection."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from sfe.discovery_router import (
    DISCOVERY_ROUTER_MODE,
    DiscoveryRouter,
    DiscoveryRouterError,
    create_configured_discovery_router,
)
from sfe.contracts import (
    ContextLoadResult,
    PRIVATE_KEY_MARKERS,
    SECRET_FILE_NAMES,
    approximate_token_count,
    load_context_file,
    text_length_bucket,
    workspace_relative_ref,
)


_TEXT_PREFIX_BYTES = 4096
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
    ".git",
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
    discovery_mode: str = DISCOVERY_ROUTER_MODE
    router_reason: str | None = None
    router_provider_name: str | None = None
    router_model: str | None = None
    router_error_category: str | None = None
    router_provider_calls_made: int = 0
    workspace_map_count: int = 0


@dataclass(frozen=True)
class _ScannedFile:
    path: Path
    source_ref: str
    approx_bytes: int


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
    router: DiscoveryRouter | None = None,
) -> DiscoveryResult:
    """Discover a router-selected candidate pool from a workspace.

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
    workspace_map = _build_workspace_map(scanned)
    stop_reason = scan_stop_reason
    if not workspace_map:
        return DiscoveryResult(
            workspace_root_present=True,
            task_present=True,
            scanned_file_count=scanned_file_count,
            candidate_count=0,
            loaded_candidate_count=0,
            skipped_candidate_count=0,
            stop_reason=stop_reason or "empty_workspace",
            candidates=(),
            load_results=(),
            skipped_reason_counts=dict(sorted(skipped_reason_counts.items())),
            warning_reason_counts={},
            router_reason="empty workspace; no existing context to inspect",
            workspace_map_count=0,
        )
    discovery_router = router or create_configured_discovery_router()
    try:
        router_selection = discovery_router.select_files(
            task=task,
            workspace_map=workspace_map,
            max_files=normalized_policy.max_candidates,
        )
    except DiscoveryRouterError as exc:
        return DiscoveryResult(
            workspace_root_present=True,
            task_present=True,
            scanned_file_count=scanned_file_count,
            candidate_count=0,
            loaded_candidate_count=0,
            skipped_candidate_count=0,
            stop_reason=exc.category,
            candidates=(),
            load_results=(),
            skipped_reason_counts=dict(sorted(skipped_reason_counts.items())),
            warning_reason_counts={},
            router_provider_name=getattr(discovery_router, "provider_name", None),
            router_model=getattr(discovery_router, "model", None),
            router_error_category=exc.category,
            router_reason=exc.reason,
            workspace_map_count=len(workspace_map),
        )
    candidates = _validate_router_selection(
        root,
        scanned,
        selected_refs=router_selection.files_to_inspect,
        policy=normalized_policy,
        skipped_reason_counts=skipped_reason_counts,
    )
    if stop_reason is None and "max_candidates" in skipped_reason_counts:
        stop_reason = "max_candidates"
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
        router_reason=router_selection.reason,
        router_provider_name=router_selection.provider_name,
        router_model=router_selection.model,
        router_provider_calls_made=router_selection.provider_calls_made,
        workspace_map_count=len(workspace_map),
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
    return _ScannedFile(
        path=path,
        source_ref=source_ref,
        approx_bytes=size,
    )


def _build_workspace_map(scanned: list[_ScannedFile]) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for item in scanned:
        path = PurePosixPath(item.source_ref)
        entries.append(
            {
                "path": item.source_ref,
                "type": "file",
                "approx_bytes": item.approx_bytes,
                "depth": max(0, len(path.parts) - 1),
                "extension": path.suffix,
                "suffix": "".join(path.suffixes),
            }
        )
    return entries


def _validate_router_selection(
    root: Path,
    scanned: list[_ScannedFile],
    *,
    selected_refs: tuple[str, ...],
    policy: DiscoveryPolicy,
    skipped_reason_counts: dict[str, int],
) -> tuple[DiscoveryCandidate, ...]:
    scanned_by_ref = {item.source_ref: item for item in scanned}
    accepted: list[DiscoveryCandidate] = []
    seen: set[str] = set()
    for selected_ref in selected_refs:
        source_ref = str(selected_ref)
        if len(accepted) >= policy.max_candidates:
            _increment(skipped_reason_counts, "max_candidates")
            continue
        reason = _router_selected_ref_rejection_reason(
            root,
            source_ref,
            scanned_by_ref,
            policy=policy,
        )
        if reason is not None:
            _increment(skipped_reason_counts, reason)
            continue
        if source_ref in seen:
            _increment(skipped_reason_counts, "duplicate_router_path")
            continue
        seen.add(source_ref)
        item = scanned_by_ref[source_ref]
        accepted.append(
            DiscoveryCandidate(
                source_ref=source_ref,
                approx_bytes=item.approx_bytes,
                score=max(0, policy.max_candidates - len(accepted)),
                reasons=("llm_router_selected",),
            )
        )
    return tuple(accepted)


def _router_selected_ref_rejection_reason(
    root: Path,
    source_ref: str,
    scanned_by_ref: dict[str, _ScannedFile],
    *,
    policy: DiscoveryPolicy,
) -> str | None:
    if not source_ref.strip():
        return "empty_router_path"
    selected = PurePosixPath(source_ref)
    if selected.is_absolute():
        return "absolute_path"
    if ".." in selected.parts:
        return "path_traversal"
    path = root / source_ref
    try:
        resolved = path.resolve()
        resolved.relative_to(root)
    except ValueError:
        return "outside_workspace"
    except OSError:
        return "read_error"
    if not resolved.exists():
        return "path_not_found"
    if not resolved.is_file():
        return "not_a_file"
    try:
        size = resolved.stat().st_size
    except OSError:
        return "read_error"
    if size > policy.max_file_bytes:
        return "file_too_large"
    if source_ref not in scanned_by_ref:
        return "not_in_workspace_map"
    return None


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
