"""Tests for the first-party SFE-aware TUI skeleton."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe_tui.app import SfeTuiApp
from sfe_tui.backends import DirectBackend, ProxyBackend, backend_by_name
from sfe_tui.contracts import (
    build_contract,
    resolve_context_path,
    resolve_workspace,
)
from sfe_tui.renderer import render_dry_run_summary, render_help


class FakeInput:
    def __init__(self, values: list[str]) -> None:
        self.values = list(values)

    def prompt(self, message: str, default: str = "") -> str:
        if not self.values:
            return default
        value = self.values.pop(0)
        return value if value else default


def test_startup_accepts_empty_workspace_input_and_uses_cwd(tmp_path) -> None:
    assert resolve_workspace("", tmp_path) == tmp_path.resolve()


def test_startup_accepts_valid_explicit_workspace_directory(tmp_path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()

    assert resolve_workspace(str(workspace), tmp_path) == workspace.resolve()


def test_startup_rejects_non_existing_workspace_directory(tmp_path) -> None:
    with pytest.raises(ValueError, match="workspace_not_found"):
        resolve_workspace("missing", tmp_path)


def test_startup_rejects_file_path_as_workspace(tmp_path) -> None:
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("not a workspace", encoding="utf-8")

    with pytest.raises(ValueError, match="workspace_not_directory"):
        resolve_workspace(str(file_path), tmp_path)


def test_pwd_reports_selected_workspace_safely(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/pwd", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    pwd_outputs = [line for line in output if line.startswith("Workspace:")]
    assert pwd_outputs
    assert str(tmp_path.resolve()) in pwd_outputs[-1]
    assert "Authorization" not in "\n".join(output)


def test_files_stores_paths_relative_to_workspace_root(tmp_path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")

    resolved = resolve_context_path(tmp_path, "notes.md")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Summarize the notes.",
        file_paths=[resolved],
    )

    assert contract.context_segments[0].source_ref == "notes.md"
    assert contract.context_segments[0].reducible is True
    assert contract.context_segments[0].text == ""


def test_files_rejects_traversal_outside_workspace(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ValueError, match="path_outside_workspace"):
        resolve_context_path(tmp_path, "../outside.txt")


def test_files_rejects_absolute_paths_outside_workspace(tmp_path) -> None:
    outside = tmp_path.parent / "absolute-outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ValueError, match="path_outside_workspace"):
        resolve_context_path(tmp_path, str(outside))


def test_generated_context_source_ref_does_not_expose_absolute_path(tmp_path) -> None:
    nested = tmp_path / "src"
    nested.mkdir()
    source = nested / "alpha.py"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")

    contract = build_contract(
        workspace_root=tmp_path,
        task="Read alpha.",
        file_paths=[source],
    )

    segment = contract.context_segments[0]
    assert segment.source_ref == "src/alpha.py"
    assert str(tmp_path) not in segment.source_ref


def test_contract_builder_separates_protected_task_from_reducible_context(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")

    contract = build_contract(
        workspace_root=tmp_path,
        task="Use the context.",
        file_paths=[source],
    )

    assert contract.instructions[0].protected is True
    assert contract.instructions[0].reducible is False
    assert contract.task is not None
    assert contract.task.protected is True
    assert contract.task.reducible is False
    assert contract.context_segments[0].protected is False
    assert contract.context_segments[0].reducible is True


def test_context_segment_ids_are_stable_opaque_and_do_not_expose_paths(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("content", encoding="utf-8")

    first = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[source],
    )
    second = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[source],
    )

    first_id = first.context_segments[0].id
    assert first_id == second.context_segments[0].id
    assert first_id.startswith("ctx_")
    assert "context.txt" not in first_id
    assert str(tmp_path) not in first_id


def test_dry_run_summary_does_not_include_file_contents(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task containing SECRET_TASK_TEXT",
        file_paths=[source],
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_dry_run_summary(contract, result)

    assert "SECRET_FILE_CONTENT" not in rendered
    assert "SECRET_TASK_TEXT" not in rendered
    assert "request body" not in rendered.lower()
    assert "Authorization" not in rendered


def test_renderer_can_render_help_and_dry_run_summary(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("content", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[source],
    )
    result = DirectBackend().dry_run(contract)

    assert "/dry-run" in render_help()
    summary = render_dry_run_summary(contract, result)
    assert "SFE dry-run summary" in summary
    assert "context segments: 1" in summary


def test_app_loop_handles_mocked_commands_and_quit(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Explain the context", "/dry-run", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Context sources selected: 1" in rendered
    assert "Task stored." in rendered
    assert "SFE dry-run summary" in rendered
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "Explain the context" not in rendered


def test_app_loop_quit_exits_cleanly(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0


def test_backend_adapters_can_be_selected_or_instantiated() -> None:
    direct = backend_by_name("direct")
    proxy = backend_by_name("proxy")

    assert isinstance(direct, DirectBackend)
    assert isinstance(proxy, ProxyBackend)
    assert DirectBackend().name == "direct"
    assert ProxyBackend().name == "proxy"


def test_backend_dry_run_makes_no_provider_calls(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("content", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[source],
    )

    assert DirectBackend().dry_run(contract).provider_calls_made == 0
    assert ProxyBackend().dry_run(contract).provider_calls_made == 0
