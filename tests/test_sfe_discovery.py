"""Tests for provider-free core workspace discovery."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe.discovery import (
    DiscoveryPolicy,
    discover_workspace_context,
    load_discovered_context,
)
from sfe_tui.contracts import build_contract
from sfe_tui.routers import LocalSegmentRouter


def _write(path: Path, text: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _refs(result) -> list[str]:
    return [candidate.source_ref for candidate in result.candidates]


def test_discovery_rejects_missing_workspace_or_missing_task_safely(tmp_path) -> None:
    missing = discover_workspace_context(
        workspace_root=tmp_path / "missing",
        task="find context",
    )

    assert missing.workspace_root_present is False
    assert missing.task_present is True
    assert missing.stop_reason == "workspace_missing"
    assert missing.candidates == ()
    assert missing.load_results == ()

    no_task = discover_workspace_context(workspace_root=tmp_path, task="  ")

    assert no_task.workspace_root_present is True
    assert no_task.task_present is False
    assert no_task.stop_reason == "missing_task"
    assert no_task.scanned_file_count == 0


def test_discovery_finds_relevant_project_files_from_task_terms(tmp_path) -> None:
    _write(tmp_path / "sfe" / "discovery.py", "def discover_workspace_context(): pass")
    _write(tmp_path / "sfe_tui" / "contracts.py", "class ContextLoadResult: pass")
    _write(tmp_path / "docs" / "notes.md", "architecture notes")
    _write(tmp_path / "unrelated.txt", "nothing important")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="Implement core workspace discovery context loading",
    )

    refs = _refs(result)
    assert "sfe/discovery.py" in refs
    assert "sfe_tui/contracts.py" in refs
    assert refs.index("sfe/discovery.py") < refs.index("unrelated.txt")
    assert result.loaded_candidate_count > 0


def test_discovery_returns_only_workspace_relative_refs(tmp_path) -> None:
    _write(tmp_path / "pkg" / "module.py", "module content")

    result = discover_workspace_context(workspace_root=tmp_path, task="module")

    assert _refs(result) == ["pkg/module.py"]
    assert result.load_results[0].source_ref == "pkg/module.py"


def test_discovery_never_includes_absolute_workspace_paths_in_result_metadata(
    tmp_path,
) -> None:
    _write(tmp_path / "notes.md", "SECRET_FILE_CONTENT")

    result = discover_workspace_context(workspace_root=tmp_path, task="notes")

    rendered = repr(result)
    assert str(tmp_path.resolve()) not in rendered
    assert "SECRET_FILE_CONTENT" not in rendered


def test_discovery_excludes_env_files_but_allows_env_example(tmp_path) -> None:
    _write(tmp_path / ".gitignore", ".env\n.env.*\n!.env.example\n")
    _write(tmp_path / ".env", "OPENAI_API_KEY=SECRET")
    _write(tmp_path / ".env.local", "OPENAI_API_KEY=SECRET")
    _write(tmp_path / ".env.example", "SFE_PROVIDER=openai")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="environment example provider",
    )

    refs = _refs(result)
    assert ".env.example" in refs
    assert ".env" not in refs
    assert ".env.local" not in refs
    assert result.skipped_reason_counts["secret_like_file"] == 2


def test_discovery_excludes_sensitive_generated_and_cache_paths(tmp_path) -> None:
    _write(tmp_path / ".ssh" / "config", "Host example")
    _write(tmp_path / "id_rsa", "private")
    _write(tmp_path / "service.key", "private")
    _write(tmp_path / "logs" / "app.log", "log")
    _write(tmp_path / "events.jsonl", "{}\n")
    _write(tmp_path / "state.sqlite", "sqlite")
    _write(tmp_path / "local.db", "db")
    _write(tmp_path / ".pytest_cache" / "data.txt", "cache")
    _write(tmp_path / ".hidden" / "notes.md", "hidden")
    _write(tmp_path / "build" / "artifact.py", "generated")
    _write(tmp_path / "dist" / "package.py", "generated")
    _write(tmp_path / "safe.py", "safe context")

    result = discover_workspace_context(workspace_root=tmp_path, task="safe context")

    assert _refs(result) == ["safe.py"]
    assert "secret_like_file" in result.skipped_reason_counts
    assert "excluded_directory" in result.skipped_reason_counts
    assert "jsonl_stream" in result.skipped_reason_counts
    assert "local_database" in result.skipped_reason_counts


def test_discovery_rejects_binary_and_non_utf8_files(tmp_path) -> None:
    (tmp_path / "image.txt").write_bytes(b"safe-prefix\x00binary")
    (tmp_path / "latin.txt").write_bytes("caf\xe9".encode("latin-1"))
    _write(tmp_path / "valid.txt", "valid text")

    result = discover_workspace_context(workspace_root=tmp_path, task="valid text")

    assert _refs(result) == ["valid.txt"]
    assert result.skipped_reason_counts["binary_or_non_text"] == 2


def test_discovery_respects_scan_candidate_load_and_total_byte_limits(
    tmp_path,
) -> None:
    _write(tmp_path / "a.py", "alpha context")
    _write(tmp_path / "b.py", "beta context")
    _write(tmp_path / "c.py", "gamma context")

    scanned = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        policy=DiscoveryPolicy(max_files_scanned=1),
    )
    assert scanned.scanned_file_count == 1
    assert scanned.stop_reason == "max_files_scanned"

    candidates = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        policy=DiscoveryPolicy(max_candidates=1),
    )
    assert candidates.candidate_count == 1
    assert candidates.stop_reason == "max_candidates"

    loaded = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        policy=DiscoveryPolicy(max_loaded_candidates=1),
    )
    assert loaded.candidate_count == 3
    assert loaded.loaded_candidate_count == 1
    assert loaded.skipped_candidate_count == 2
    assert loaded.stop_reason == "max_loaded_candidates"

    total_bytes = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        policy=DiscoveryPolicy(max_total_loaded_bytes=5),
    )
    assert total_bytes.loaded_candidate_count == 0
    assert total_bytes.stop_reason == "max_total_loaded_bytes"


def test_discovery_makes_zero_provider_calls(tmp_path, monkeypatch) -> None:
    import sfe.provider_config as provider_config

    calls = {"count": 0}

    def fake_resolver(*_args, **_kwargs) -> str:
        calls["count"] += 1
        return "openai"

    monkeypatch.setattr(provider_config, "resolve_sfe_provider", fake_resolver)
    _write(tmp_path / "context.py", "provider-free discovery")

    discover_workspace_context(workspace_root=tmp_path, task="provider discovery")

    assert calls["count"] == 0


def test_discovery_and_execution_time_loading_perform_no_writes(tmp_path) -> None:
    _write(tmp_path / "context.md", "original")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = discover_workspace_context(workspace_root=tmp_path, task="context")
    load_discovered_context(workspace_root=tmp_path, discovery_result=result)

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_discovery_output_does_not_contain_raw_file_contents(tmp_path) -> None:
    _write(tmp_path / "context.md", "SECRET_FILE_CONTENT")

    result = discover_workspace_context(workspace_root=tmp_path, task="context")

    assert result.load_results[0].loaded is True
    assert result.load_results[0].text == ""
    assert "SECRET_FILE_CONTENT" not in repr(result)


def test_load_discovered_context_returns_full_text_for_contract_building(
    tmp_path,
) -> None:
    _write(tmp_path / "context.md", "alpha routing content")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha routing",
    )
    loaded = load_discovered_context(
        workspace_root=tmp_path,
        discovery_result=result,
    )
    contract = build_contract(
        workspace_root=tmp_path,
        task="alpha routing",
        file_paths=[],
        context_files=list(loaded),
    )
    routed = LocalSegmentRouter().route("alpha routing", contract.context_segments)

    assert result.load_results[0].text == ""
    assert loaded[0].loaded is True
    assert loaded[0].text == "alpha routing content"
    assert contract.context_segments[0].text == "alpha routing content"
    assert routed.selected_segment_count == 1
    assert routed.selected_segment_ids == [contract.context_segments[0].id]


def test_load_discovered_context_only_reloads_discovered_candidates(tmp_path) -> None:
    _write(tmp_path / "selected.py", "selected alpha context")
    _write(tmp_path / "unselected.py", "unselected beta context")
    discovery = discover_workspace_context(
        workspace_root=tmp_path,
        task="selected alpha",
        policy=DiscoveryPolicy(max_candidates=1),
    )

    loaded = load_discovered_context(
        workspace_root=tmp_path,
        discovery_result=discovery,
    )

    assert _refs(discovery) == ["selected.py"]
    assert [result.source_ref for result in loaded] == ["selected.py"]


def test_load_discovered_context_respects_load_and_total_byte_limits(
    tmp_path,
) -> None:
    _write(tmp_path / "a.py", "alpha context")
    _write(tmp_path / "b.py", "beta context")
    _write(tmp_path / "c.py", "gamma context")
    discovery = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
    )

    limited_count = load_discovered_context(
        workspace_root=tmp_path,
        discovery_result=discovery,
        policy=DiscoveryPolicy(max_loaded_candidates=1),
    )
    limited_bytes = load_discovered_context(
        workspace_root=tmp_path,
        discovery_result=discovery,
        policy=DiscoveryPolicy(max_total_loaded_bytes=5),
    )

    assert sum(1 for result in limited_count if result.loaded) == 1
    assert [result.reason for result in limited_count if not result.loaded] == [
        "max_loaded_candidates",
        "max_loaded_candidates",
    ]
    assert all(not result.loaded for result in limited_bytes)
    assert {result.reason for result in limited_bytes} == {"max_total_loaded_bytes"}


def test_candidate_ordering_is_deterministic(tmp_path) -> None:
    _write(tmp_path / "zeta.py", "shared content")
    _write(tmp_path / "alpha.py", "shared content")
    _write(tmp_path / "docs" / "guide.md", "shared content")

    first = discover_workspace_context(workspace_root=tmp_path, task="shared")
    second = discover_workspace_context(workspace_root=tmp_path, task="shared")

    assert _refs(first) == _refs(second)
    assert _refs(first) == sorted(_refs(first), key=lambda ref: (-_score(first, ref), ref))


def _score(result, source_ref: str) -> int:
    for candidate in result.candidates:
        if candidate.source_ref == source_ref:
            return candidate.score
    raise AssertionError(source_ref)
