"""Tests for LLM-driven core workspace discovery."""

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
from sfe.discovery_router import (
    DISCOVERY_ROUTER_MODE,
    DiscoveryRouterError,
    DiscoveryRouterSelection,
    parse_discovery_router_output,
)
from sfe_tui.contracts import build_contract
from sfe_tui.routers import LocalSegmentRouter


def _write(path: Path, text: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _refs(result) -> list[str]:
    return [candidate.source_ref for candidate in result.candidates]


class FakeDiscoveryRouter:
    provider_name = "fake-discovery-router"
    model = "fake-discovery-model"

    def __init__(self, files_to_inspect: tuple[str, ...] = ()) -> None:
        self.files_to_inspect = files_to_inspect
        self.calls: list[dict[str, object]] = []

    def select_files(
        self,
        *,
        task: str,
        workspace_map: list[dict[str, object]],
        max_files: int,
    ) -> DiscoveryRouterSelection:
        self.calls.append(
            {
                "task": task,
                "workspace_map": workspace_map,
                "max_files": max_files,
            }
        )
        files = self.files_to_inspect or tuple(
            str(entry["path"]) for entry in workspace_map[:max_files]
        )
        return DiscoveryRouterSelection(
            files_to_inspect=files,
            reason="fake semantic file selection",
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


def test_discovery_rejects_missing_workspace_or_missing_task_safely(tmp_path) -> None:
    missing = discover_workspace_context(
        workspace_root=tmp_path / "missing",
        task="find context",
        router=FakeDiscoveryRouter(),
    )

    assert missing.workspace_root_present is False
    assert missing.task_present is True
    assert missing.stop_reason == "workspace_missing"
    assert missing.candidates == ()
    assert missing.load_results == ()

    no_task = discover_workspace_context(
        workspace_root=tmp_path,
        task="  ",
        router=FakeDiscoveryRouter(),
    )

    assert no_task.workspace_root_present is True
    assert no_task.task_present is False
    assert no_task.stop_reason == "missing_task"
    assert no_task.scanned_file_count == 0


def test_discovery_router_output_parser_requires_strict_json_shape() -> None:
    parsed = parse_discovery_router_output(
        '{"files_to_inspect":["templates/home/index.html.twig"],"reason":"homepage"}'
    )

    assert parsed.files_to_inspect == ("templates/home/index.html.twig",)
    assert parsed.reason == "homepage"

    try:
        parse_discovery_router_output(
            '{"files_to_inspect":["valid.txt", 3],"reason":"bad"}'
        )
    except DiscoveryRouterError as exc:
        assert exc.category == "invalid_discovery_router_response"
    else:
        raise AssertionError("expected strict parser failure")


def test_discovery_finds_relevant_project_files_from_task_terms(tmp_path) -> None:
    _write(tmp_path / "sfe" / "discovery.py", "def discover_workspace_context(): pass")
    _write(tmp_path / "sfe_tui" / "contracts.py", "class ContextLoadResult: pass")
    _write(tmp_path / "docs" / "notes.md", "architecture notes")
    _write(tmp_path / "unrelated.txt", "nothing important")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="Implement core workspace discovery context loading",
        router=FakeDiscoveryRouter(("sfe/discovery.py", "sfe_tui/contracts.py")),
    )

    refs = _refs(result)
    assert "sfe/discovery.py" in refs
    assert "sfe_tui/contracts.py" in refs
    assert "unrelated.txt" not in refs
    assert result.loaded_candidate_count > 0
    assert result.discovery_mode == DISCOVERY_ROUTER_MODE


def test_discovery_returns_only_workspace_relative_refs(tmp_path) -> None:
    _write(tmp_path / "pkg" / "module.py", "module content")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="module",
        router=FakeDiscoveryRouter(("pkg/module.py",)),
    )

    assert _refs(result) == ["pkg/module.py"]
    assert result.load_results[0].source_ref == "pkg/module.py"


def test_discovery_never_includes_absolute_workspace_paths_in_result_metadata(
    tmp_path,
) -> None:
    _write(tmp_path / "notes.md", "SECRET_FILE_CONTENT")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="notes",
        router=FakeDiscoveryRouter(("notes.md",)),
    )

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
        router=FakeDiscoveryRouter((".env.example",)),
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

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="safe context",
        router=FakeDiscoveryRouter(("safe.py",)),
    )

    assert _refs(result) == ["safe.py"]
    assert "secret_like_file" in result.skipped_reason_counts
    assert "excluded_directory" in result.skipped_reason_counts
    assert "jsonl_stream" in result.skipped_reason_counts
    assert "local_database" in result.skipped_reason_counts


def test_discovery_rejects_binary_and_non_utf8_files(tmp_path) -> None:
    (tmp_path / "image.txt").write_bytes(b"safe-prefix\x00binary")
    (tmp_path / "latin.txt").write_bytes("caf\xe9".encode("latin-1"))
    _write(tmp_path / "valid.txt", "valid text")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="valid text",
        router=FakeDiscoveryRouter(("image.txt", "latin.txt", "valid.txt")),
    )

    assert _refs(result) == ["image.txt", "latin.txt", "valid.txt"]
    assert [item.source_ref for item in result.load_results if item.loaded] == [
        "valid.txt"
    ]
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
        router=FakeDiscoveryRouter(),
    )
    assert scanned.scanned_file_count == 1
    assert scanned.stop_reason == "max_files_scanned"

    candidates = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        policy=DiscoveryPolicy(max_candidates=1),
        router=FakeDiscoveryRouter(("a.py", "b.py", "c.py")),
    )
    assert candidates.candidate_count == 1
    assert candidates.stop_reason == "max_candidates"

    loaded = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        policy=DiscoveryPolicy(max_loaded_candidates=1),
        router=FakeDiscoveryRouter(),
    )
    assert loaded.candidate_count == 3
    assert loaded.loaded_candidate_count == 1
    assert loaded.skipped_candidate_count == 2
    assert loaded.stop_reason == "max_loaded_candidates"

    total_bytes = discover_workspace_context(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        policy=DiscoveryPolicy(max_total_loaded_bytes=5),
        router=FakeDiscoveryRouter(),
    )
    assert total_bytes.loaded_candidate_count == 0
    assert total_bytes.stop_reason == "max_total_loaded_bytes"


def test_discovery_uses_injected_router_without_configured_provider_calls(
    tmp_path,
    monkeypatch,
) -> None:
    import sfe.provider_config as provider_config

    calls = {"count": 0}

    def fake_resolver(*_args, **_kwargs) -> str:
        calls["count"] += 1
        return "openai"

    monkeypatch.setattr(provider_config, "resolve_sfe_provider", fake_resolver)
    _write(tmp_path / "context.py", "provider-free discovery")

    router = FakeDiscoveryRouter(("context.py",))
    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="provider discovery",
        router=router,
    )

    assert calls["count"] == 0
    assert router.calls
    assert result.router_provider_calls_made == 1


def test_discovery_and_execution_time_loading_perform_no_writes(tmp_path) -> None:
    _write(tmp_path / "context.md", "original")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="context",
        router=FakeDiscoveryRouter(("context.md",)),
    )
    load_discovered_context(workspace_root=tmp_path, discovery_result=result)

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_discovery_output_does_not_contain_raw_file_contents(tmp_path) -> None:
    _write(tmp_path / "context.md", "SECRET_FILE_CONTENT")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="context",
        router=FakeDiscoveryRouter(("context.md",)),
    )

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
        router=FakeDiscoveryRouter(("context.md",)),
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
        router=FakeDiscoveryRouter(("selected.py",)),
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
        router=FakeDiscoveryRouter(),
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


def test_discovery_router_can_select_symfony_home_template_without_content_or_twig_rule(
    tmp_path,
) -> None:
    _write(tmp_path / "composer.json", '{"require":{"symfony/framework-bundle":"*"}}')
    _write(tmp_path / "config" / "routes.yaml", "controllers:\n  resource: ../src/Controller/\n")
    _write(tmp_path / "src" / "Controller" / "HomeController.php", "<?php\nclass HomeController {}\n")
    _write(tmp_path / "templates" / "base.html.twig", "<html>{% block body %}{% endblock %}</html>")
    _write(
        tmp_path / "templates" / "home" / "index.html.twig",
        "<h1>SECRET_TEMPLATE_CONTENT</h1>",
    )
    _write(tmp_path / "README.md", "Symfony test project")
    _write(tmp_path / "PROJECT_REQUEST.md", "Add a homepage form")
    router = FakeDiscoveryRouter(("templates/home/index.html.twig",))

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task=(
            "Modifier la page d'accueil pour y ajouter un formulaire HTML avec "
            "nom, prénom, bouton Envoyer"
        ),
        router=router,
    )

    workspace_map = router.calls[0]["workspace_map"]
    assert "templates/home/index.html.twig" in {
        entry["path"] for entry in workspace_map
    }
    assert "SECRET_TEMPLATE_CONTENT" not in repr(workspace_map)
    template_entry = next(
        entry
        for entry in workspace_map
        if entry["path"] == "templates/home/index.html.twig"
    )
    assert template_entry["suffix"] == ".html.twig"
    assert _refs(result) == ["templates/home/index.html.twig"]
    assert result.load_results[0].loaded is True
    assert result.load_results[0].text == ""
    loaded = load_discovered_context(workspace_root=tmp_path, discovery_result=result)
    assert loaded[0].source_ref == "templates/home/index.html.twig"
    assert "SECRET_TEMPLATE_CONTENT" in loaded[0].text
    assert "unsupported_extension" not in result.skipped_reason_counts


def test_discovery_revalidates_router_selected_paths_locally(tmp_path) -> None:
    _write(tmp_path / "valid.txt", "valid context")
    _write(tmp_path / "large.txt", "x" * 20)
    outside = tmp_path.parent / "outside-discovery.txt"
    outside.write_text("outside", encoding="utf-8")
    symlink_created = False
    try:
        (tmp_path / "outside-link.txt").symlink_to(outside)
        symlink_created = True
    except OSError:
        pass
    selected = [
        str(tmp_path / "valid.txt"),
        "../outside-discovery.txt",
        "missing.txt",
        "large.txt",
        "valid.txt",
        "extra.txt",
    ]
    _write(tmp_path / "extra.txt", "extra context")
    if symlink_created:
        selected.append("outside-link.txt")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="validate router paths",
        policy=DiscoveryPolicy(max_file_bytes=15, max_candidates=10),
        router=FakeDiscoveryRouter(tuple(selected)),
    )

    assert _refs(result) == ["valid.txt", "extra.txt"]
    assert result.skipped_reason_counts["absolute_path"] == 1
    assert result.skipped_reason_counts["path_traversal"] == 1
    assert result.skipped_reason_counts["path_not_found"] == 1
    assert result.skipped_reason_counts["file_too_large"] >= 1
    if symlink_created:
        assert result.skipped_reason_counts["outside_workspace"] >= 1

    limited = discover_workspace_context(
        workspace_root=tmp_path,
        task="validate router path count limit",
        router=FakeDiscoveryRouter(("valid.txt", "extra.txt")),
        policy=DiscoveryPolicy(max_candidates=1),
    )

    assert _refs(limited) == ["valid.txt"]
    assert limited.skipped_reason_counts["max_candidates"] == 1


def test_candidate_ordering_is_deterministic(tmp_path) -> None:
    _write(tmp_path / "zeta.py", "shared content")
    _write(tmp_path / "alpha.py", "shared content")
    _write(tmp_path / "docs" / "guide.md", "shared content")

    first = discover_workspace_context(
        workspace_root=tmp_path,
        task="shared",
        router=FakeDiscoveryRouter(),
    )
    second = discover_workspace_context(
        workspace_root=tmp_path,
        task="shared",
        router=FakeDiscoveryRouter(),
    )

    assert _refs(first) == _refs(second)
    assert _refs(first) == sorted(_refs(first), key=lambda ref: (-_score(first, ref), ref))


def _score(result, source_ref: str) -> int:
    for candidate in result.candidates:
        if candidate.source_ref == source_ref:
            return candidate.score
    raise AssertionError(source_ref)
