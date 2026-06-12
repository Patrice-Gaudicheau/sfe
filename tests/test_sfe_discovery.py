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
    create_configured_discovery_router,
    parse_discovery_router_output,
)
from sfe.execution_mode_router import create_configured_execution_mode_router
from sfe.contracts import build_contract
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


class FakeProvider:
    def __init__(self, answer: str = '{"files_to_inspect":[],"reason":"none"}') -> None:
        self.answer = answer
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": True}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        return {"choices": [{"message": {"content": self.answer}}]}


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


def test_configured_discovery_router_uses_discovery_provider_override_only() -> None:
    discovery_provider = FakeProvider()
    execution_provider = FakeProvider(
        '{"execution_mode":"workspace_write","reason":"edit files"}'
    )
    environ = {
        "SFE_PROVIDER": "openai",
        "SFE_PROVIDER_ROUTER": "codexcli",
        "SFE_PROVIDER_DISCOVERY": "openai",
        "SFE_OPENAI_ROUTER_MODEL": "openai-discovery-model",
        "SFE_CODEXCLI_ROUTER_MODEL": "codexcli-execution-router-model",
    }

    discovery_router = create_configured_discovery_router(
        environ=environ,
        provider_factories={"openai": lambda: discovery_provider},
    )
    execution_router = create_configured_execution_mode_router(
        environ=environ,
        provider_factories={"codexcli": lambda: execution_provider},
    )

    assert discovery_router.provider_name == "openai"
    assert discovery_router.model == "openai-discovery-model"
    assert execution_router.provider_name == "codexcli"
    assert execution_router.model == "codexcli-execution-router-model"


def test_discovery_router_does_not_receive_executor_idle_timeout() -> None:
    provider = FakeProvider(
        '{"files_to_inspect":["context.txt"],"reason":"Inspect context."}'
    )
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "codexcli",
            "SFE_CODEXCLI_EXECUTOR_IDLE_TIMEOUT_SECONDS": "900",
            "SFE_PROVIDER_EXECUTOR_IDLE_TIMEOUT_SECONDS": "600",
        },
        provider_factories={"codexcli": lambda: provider},
    )

    selection = router.select_files(
        task="Patch context",
        workspace_map=[{"path": "context.txt"}],
        max_files=1,
    )

    assert selection.files_to_inspect == ("context.txt",)
    assert "idle_timeout_seconds" not in provider.calls[0]
    assert "provider_role" not in provider.calls[0]


def test_openai_discovery_model_overrides_openai_router_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "openai",
            "SFE_OPENAI_DISCOVERY_MODEL": "openai-discovery-model",
            "SFE_OPENAI_ROUTER_MODEL": "openai-router-model",
        },
        provider_factories={"openai": lambda: provider},
    )

    assert router.provider_name == "openai"
    assert router.model == "openai-discovery-model"


def test_openai_discovery_model_falls_back_to_openai_router_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "openai",
            "SFE_OPENAI_DISCOVERY_MODEL": " ",
            "SFE_OPENAI_ROUTER_MODEL": "openai-router-model",
        },
        provider_factories={"openai": lambda: provider},
    )

    assert router.provider_name == "openai"
    assert router.model == "openai-router-model"


def test_configured_discovery_router_blank_discovery_provider_falls_back_to_router_provider() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER": "openai",
            "SFE_PROVIDER_ROUTER": "lemonade",
            "SFE_PROVIDER_DISCOVERY": " ",
            "SFE_ROUTER_MODEL": "lemonade-discovery-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    assert router.provider_name == "lemonade"
    assert router.model == "lemonade-discovery-model"


def test_lemonade_discovery_model_overrides_router_and_shared_models() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "lemonade",
            "SFE_LEMONADE_DISCOVERY_MODEL": "lemonade-discovery-model",
            "SFE_ROUTER_MODEL": "lemonade-router-model",
            "SFE_LEMONADE_MODEL": "lemonade-shared-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    assert router.provider_name == "lemonade"
    assert router.model == "lemonade-discovery-model"


def test_lemonade_discovery_model_falls_back_to_router_then_shared_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "lemonade",
            "SFE_LEMONADE_DISCOVERY_MODEL": " ",
            "SFE_ROUTER_MODEL": "lemonade-router-model",
            "SFE_LEMONADE_MODEL": "lemonade-shared-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )
    shared = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "lemonade",
            "SFE_ROUTER_MODEL": " ",
            "SFE_LEMONADE_MODEL": "lemonade-shared-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    assert router.model == "lemonade-router-model"
    assert shared.model == "lemonade-shared-model"


def test_configured_discovery_router_legacy_shared_provider_fallback_still_works() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER": "alibaba",
            "SFE_ALIBABA_ROUTER_MODEL": "alibaba-discovery-model",
        },
        provider_factories={"alibaba": lambda: provider},
    )

    assert router.provider_name == "alibaba"
    assert router.model == "alibaba-discovery-model"


def test_alibaba_discovery_model_overrides_alibaba_router_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "alibaba",
            "SFE_ALIBABA_DISCOVERY_MODEL": "alibaba-discovery-model",
            "SFE_ALIBABA_ROUTER_MODEL": "alibaba-router-model",
        },
        provider_factories={"alibaba": lambda: provider},
    )

    assert router.provider_name == "alibaba"
    assert router.model == "alibaba-discovery-model"


def test_anthropic_discovery_model_overrides_anthropic_router_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "anthropic",
            "SFE_ANTHROPIC_DISCOVERY_MODEL": "anthropic-discovery-model",
            "SFE_ANTHROPIC_ROUTER_MODEL": "anthropic-router-model",
        },
        provider_factories={"anthropic": lambda: provider},
    )

    assert router.provider_name == "anthropic"
    assert router.model == "anthropic-discovery-model"


def test_google_discovery_selects_files_with_fake_response(tmp_path) -> None:
    _write(tmp_path / "public" / "index.php", "<?php echo 'raw';\n")
    _write(tmp_path / "content" / "posts.php", "<?php return [];\n")
    provider = FakeProvider(
        '{"files_to_inspect":["public/index.php","content/posts.php"],'
        '"reason":"rendered output and source data"}'
    )

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="escape PHP blog output",
        router=create_configured_discovery_router(
            environ={
                "SFE_PROVIDER_DISCOVERY": "google",
                "SFE_GOOGLE_DISCOVERY_MODEL": "google-discovery-model",
                "SFE_GOOGLE_MODEL": "google-shared-model",
            },
            provider_factories={"google": lambda: provider},
        ),
    )

    assert _refs(result) == ["public/index.php", "content/posts.php"]
    assert result.router_provider_name == "google"
    assert result.router_model == "google-discovery-model"
    assert result.router_error_category is None
    assert provider.calls[0]["model"] == "google-discovery-model"
    assert provider.calls[0]["messages"][0]["role"] == "system"


def test_google_discovery_model_overrides_google_shared_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "google",
            "SFE_GOOGLE_DISCOVERY_MODEL": "google-discovery-model",
            "SFE_GOOGLE_MODEL": "google-shared-model",
        },
        provider_factories={"google": lambda: provider},
    )

    assert router.provider_name == "google"
    assert router.model == "google-discovery-model"


def test_google_discovery_model_falls_back_to_google_shared_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "google",
            "SFE_GOOGLE_DISCOVERY_MODEL": " ",
            "SFE_GOOGLE_MODEL": "google-shared-model",
        },
        provider_factories={"google": lambda: provider},
    )

    assert router.provider_name == "google"
    assert router.model == "google-shared-model"


def test_discovery_augments_existing_symfony_completion_with_anchor_files(tmp_path) -> None:
    _write(tmp_path / "composer.json", '{"require":{"symfony/framework-bundle":"^7.0"}}\n')
    _write(tmp_path / "README.md", "# Todo List\n")
    _write(tmp_path / ".env.example", "APP_ENV=dev\n")
    _write(tmp_path / "bin" / "console", "#!/usr/bin/env php\n")
    _write(tmp_path / "config" / "packages" / "framework.yaml", "framework: {}\n")
    _write(tmp_path / "src" / "Controller" / "TodoController.php", "<?php\n")
    _write(tmp_path / "src" / "Entity" / "Todo.php", "<?php\n")
    _write(tmp_path / "src" / "Form" / "TodoType.php", "<?php\n")
    _write(tmp_path / "src" / "Repository" / "TodoRepository.php", "<?php\n")
    _write(tmp_path / "templates" / "todo" / "index.html.twig", "{{ todos }}\n")
    _write(tmp_path / "migrations" / "Version20260101000000.php", "<?php\n")
    _write(tmp_path / "tests" / "TodoTest.php", "<?php\n")
    router = FakeDiscoveryRouter(files_to_inspect=("templates/todo/index.html.twig",))

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task=(
            "Continue and complete the existing Symfony Todo List application. "
            "Inspect existing files first and reuse the current Symfony project structure."
        ),
        router=router,
    )

    refs = _refs(result)
    assert refs[0] == "composer.json"
    assert "templates/todo/index.html.twig" in refs
    for expected in (
        "composer.json",
        "README.md",
        ".env.example",
        "bin/console",
        "config/packages/framework.yaml",
        "src/Controller/TodoController.php",
        "src/Entity/Todo.php",
        "src/Form/TodoType.php",
        "src/Repository/TodoRepository.php",
        "migrations/Version20260101000000.php",
        "tests/TodoTest.php",
    ):
        assert expected in refs
    assert len(refs) <= DiscoveryPolicy().max_candidates
    assert result.candidates[0].reasons == ("existing_symfony_anchor",)


def test_codexcli_discovery_selects_files_with_fake_response(
    tmp_path,
) -> None:
    _write(tmp_path / "content" / "posts.php", "<?php return [];\n")
    _write(tmp_path / "public" / "index.php", "<?php echo $post['title'];\n")
    _write(tmp_path / "tests" / "render_smoke.php", "<?php\n")
    provider = FakeProvider(
        '{"files_to_inspect":["public/index.php","content/posts.php"],'
        '"reason":"rendered output and source data"}'
    )

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="escape PHP blog output",
        router=create_configured_discovery_router(
            environ={
                "SFE_PROVIDER_DISCOVERY": "codexcli",
                "SFE_CODEXCLI_DISCOVERY_MODEL": "codexcli-discovery-model",
                "SFE_CODEXCLI_ROUTER_MODEL": "codexcli-router-model",
            },
            provider_factories={"codexcli": lambda: provider},
        ),
    )

    assert result.scanned_file_count == 3
    assert result.workspace_map_count == 3
    assert _refs(result) == ["public/index.php", "content/posts.php"]
    assert result.loaded_candidate_count == 2
    assert result.router_provider_name == "codexcli"
    assert result.router_model == "codexcli-discovery-model"
    assert result.router_error_category is None
    assert provider.calls[0]["model"] == "codexcli-discovery-model"
    assert provider.calls[0]["system_instruction"]


def test_codexcli_discovery_malformed_output_returns_router_error(tmp_path) -> None:
    _write(tmp_path / "public" / "index.php", "<?php echo 'raw';\n")
    provider = FakeProvider("not json")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="escape PHP blog output",
        router=create_configured_discovery_router(
            environ={"SFE_PROVIDER_DISCOVERY": "codexcli"},
            provider_factories={"codexcli": lambda: provider},
        ),
    )

    assert result.candidate_count == 0
    assert result.router_provider_name == "codexcli"
    assert result.router_error_category == "invalid_discovery_router_response"
    assert result.stop_reason == "invalid_discovery_router_response"


def test_codexcli_discovery_unknown_paths_are_rejected_locally(tmp_path) -> None:
    _write(tmp_path / "public" / "index.php", "<?php echo 'raw';\n")
    provider = FakeProvider(
        '{"files_to_inspect":["missing.php","public/index.php"],'
        '"reason":"one bad and one good path"}'
    )

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="escape PHP blog output",
        router=create_configured_discovery_router(
            environ={"SFE_PROVIDER_DISCOVERY": "codexcli"},
            provider_factories={"codexcli": lambda: provider},
        ),
    )

    assert _refs(result) == ["public/index.php"]
    assert result.router_error_category is None
    assert result.skipped_reason_counts["path_not_found"] == 1


def test_codexcli_discovery_model_overrides_codexcli_router_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "codexcli",
            "SFE_CODEXCLI_DISCOVERY_MODEL": "codexcli-discovery-model",
            "SFE_CODEXCLI_ROUTER_MODEL": "codexcli-router-model",
        },
        provider_factories={"codexcli": lambda: provider},
    )

    assert router.provider_name == "codexcli"
    assert router.model == "codexcli-discovery-model"


def test_codexcli_discovery_model_falls_back_to_codexcli_router_model() -> None:
    provider = FakeProvider()
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "codexcli",
            "SFE_CODEXCLI_DISCOVERY_MODEL": " ",
            "SFE_CODEXCLI_ROUTER_MODEL": "codexcli-router-model",
        },
        provider_factories={"codexcli": lambda: provider},
    )

    assert router.provider_name == "codexcli"
    assert router.model == "codexcli-router-model"


def test_codexcli_discovery_uses_role_specific_effort() -> None:
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "codexcli",
            "SFE_CODEXCLI_DISCOVERY_EFFORT": "low",
            "SFE_CODEXCLI_ROUTER_EFFORT": "high",
            "SFE_CODEXCLI_REASONING_EFFORT": "medium",
        },
    )

    assert router.provider_name == "codexcli"
    assert getattr(router, "provider").reasoning_effort == "low"


def test_codexcli_discovery_effort_falls_back_to_router_effort() -> None:
    router = create_configured_discovery_router(
        environ={
            "SFE_PROVIDER_DISCOVERY": "codexcli",
            "SFE_CODEXCLI_DISCOVERY_EFFORT": " ",
            "SFE_CODEXCLI_ROUTER_EFFORT": "high",
            "SFE_CODEXCLI_REASONING_EFFORT": "medium",
        },
    )

    assert router.provider_name == "codexcli"
    assert getattr(router, "provider").reasoning_effort == "high"


def test_non_git_php_workspace_scans_files_with_supported_discovery_router(
    tmp_path,
) -> None:
    _write(tmp_path / "content" / "posts.php", "<?php return [];\n")
    _write(tmp_path / "public" / "index.php", "<?php echo $post['title'];\n")
    _write(tmp_path / "tests" / "render_smoke.php", "<?php\n")

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="escape PHP blog output",
        router=FakeDiscoveryRouter(
            ("content/posts.php", "public/index.php", "tests/render_smoke.php")
        ),
    )

    assert result.scanned_file_count == 3
    assert result.workspace_map_count == 3
    assert _refs(result) == [
        "content/posts.php",
        "public/index.php",
        "tests/render_smoke.php",
    ]
    assert result.loaded_candidate_count == 3


def test_discovery_empty_workspace_returns_valid_empty_context(tmp_path) -> None:
    router = FakeDiscoveryRouter(("README.md",))

    result = discover_workspace_context(
        workspace_root=tmp_path,
        task="Create a README for this empty project",
        router=router,
    )

    assert result.workspace_root_present is True
    assert result.task_present is True
    assert result.stop_reason == "empty_workspace"
    assert result.workspace_map_count == 0
    assert result.candidate_count == 0
    assert result.loaded_candidate_count == 0
    assert result.candidates == ()
    assert result.load_results == ()
    assert result.router_provider_calls_made == 0
    assert router.calls == []


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
