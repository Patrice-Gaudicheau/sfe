"""Tests for the first-party SFE-aware TUI skeleton."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sfe_tui.app import SfeTuiApp
from sfe_tui.backends import (
    DETERMINISTIC_PREVIEW_MODE,
    DirectBackend,
    ProxyBackend,
    ROUTER_UNAVAILABLE_REASON,
    backend_by_name,
)
from sfe_tui.contracts import (
    ContextSegment,
    MAX_CONTEXT_FILE_BYTES,
    ProtectedText,
    build_contract,
    load_context_file,
    resolve_context_path,
    resolve_workspace,
)
from sfe_tui.renderer import render_dry_run_summary, render_help, render_status


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


def test_files_reads_text_file_and_populates_context_segment_text(tmp_path) -> None:
    source = tmp_path / "notes.md"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")

    loaded = load_context_file(tmp_path, "notes.md")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Summarize the notes.",
        file_paths=[],
        context_files=[loaded],
    )

    assert loaded.loaded is True
    assert contract.context_segments[0].source_ref == "notes.md"
    assert contract.context_segments[0].reducible is True
    assert contract.context_segments[0].text == "SECRET_FILE_CONTENT"
    assert contract.context_segments[0].approx_size == len("SECRET_FILE_CONTENT")
    assert contract.context_segments[0].approx_tokens > 0


def test_files_rejects_traversal_outside_workspace(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ValueError, match="path_outside_workspace"):
        resolve_context_path(tmp_path, "../outside.txt")
    loaded = load_context_file(tmp_path, "../outside.txt")
    assert loaded.loaded is False
    assert loaded.reason == "outside_workspace"


def test_files_rejects_absolute_paths_outside_workspace(tmp_path) -> None:
    outside = tmp_path.parent / "absolute-outside.txt"
    outside.write_text("outside", encoding="utf-8")

    with pytest.raises(ValueError, match="path_outside_workspace"):
        resolve_context_path(tmp_path, str(outside))
    loaded = load_context_file(tmp_path, str(outside))
    assert loaded.loaded is False
    assert loaded.reason == "outside_workspace"


def test_files_rejects_directories(tmp_path) -> None:
    directory = tmp_path / "docs"
    directory.mkdir()

    loaded = load_context_file(tmp_path, "docs")

    assert loaded.loaded is False
    assert loaded.reason == "not_a_file"


def test_files_rejects_file_above_max_size_limit(tmp_path) -> None:
    source = tmp_path / "large.txt"
    source.write_bytes(b"a" * (MAX_CONTEXT_FILE_BYTES + 1))

    loaded = load_context_file(tmp_path, "large.txt")

    assert loaded.loaded is False
    assert loaded.reason == "file_too_large"


def test_files_rejects_binary_file(tmp_path) -> None:
    source = tmp_path / "image.bin"
    source.write_bytes(b"safe-prefix\x00binary")

    loaded = load_context_file(tmp_path, "image.bin")

    assert loaded.loaded is False
    assert loaded.reason == "binary_or_non_text"


def test_files_rejects_secret_like_env_file(tmp_path) -> None:
    source = tmp_path / ".env"
    source.write_text("OPENAI_API_KEY=SECRET", encoding="utf-8")

    loaded = load_context_file(tmp_path, ".env")

    assert loaded.loaded is False
    assert loaded.reason == "secret_like_file"


def test_files_rejects_files_under_ssh_directory(tmp_path) -> None:
    ssh_dir = tmp_path / ".ssh"
    ssh_dir.mkdir()
    source = ssh_dir / "config"
    source.write_text("Host example", encoding="utf-8")

    loaded = load_context_file(tmp_path, ".ssh/config")

    assert loaded.loaded is False
    assert loaded.reason == "secret_like_file"


def test_files_rejects_private_key_marker(tmp_path) -> None:
    source = tmp_path / "key.txt"
    source.write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nSECRET",
        encoding="utf-8",
    )

    loaded = load_context_file(tmp_path, "key.txt")

    assert loaded.loaded is False
    assert loaded.reason == "secret_like_file"


def test_generated_context_source_ref_does_not_expose_absolute_path(tmp_path) -> None:
    nested = tmp_path / "src"
    nested.mkdir()
    source = nested / "alpha.py"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")

    contract = build_contract(
        workspace_root=tmp_path,
        task="Read alpha.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "src/alpha.py")],
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
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
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
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    second = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
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
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_dry_run_summary(contract, result)

    assert "SECRET_FILE_CONTENT" not in rendered
    assert "SECRET_TASK_TEXT" not in rendered
    assert "requested files: 1" in rendered
    assert "loaded files: 1" in rendered
    assert f"selector mode: {DETERMINISTIC_PREVIEW_MODE}" in rendered
    assert "request body" not in rendered.lower()
    assert "Authorization" not in rendered


def test_renderer_can_render_help_and_dry_run_summary(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("content", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
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
    assert "Context sources loaded: 1; skipped: 0" in rendered
    assert "Task stored." in rendered
    assert "SFE dry-run summary" in rendered
    assert f"selector mode: {DETERMINISTIC_PREVIEW_MODE}" in rendered
    assert "selected segment ids: ['ctx_" in rendered
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "Explain the context" not in rendered
    dry_run_block = rendered.split("SFE dry-run summary", 1)[1]
    assert str(tmp_path) not in dry_run_block


def test_app_loop_reports_skipped_reason_counts_without_raw_paths(tmp_path) -> None:
    outside = tmp_path.parent / "outside-app.txt"
    outside.write_text("outside", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", f"/files {outside}", "/dry-run", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Context sources loaded: 0; skipped: 1" in rendered
    assert "outside_workspace" in rendered
    assert str(outside) not in rendered
    assert "outside-app.txt" not in rendered


def test_status_renders_state_without_file_contents(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Explain the context", "/status", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE TUI status" in rendered
    assert "loaded context files: 1" in rendered
    assert "skipped context files: 0" in rendered
    assert "task present: True" in rendered
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "Explain the context" not in rendered


def test_status_reports_direct_backend_and_disabled_capabilities() -> None:
    rendered = render_status(
        workspace_selected=True,
        loaded_context_files=2,
        skipped_context_files=1,
        task_present=True,
        backend_name="direct",
    )

    assert "backend: direct" in rendered
    assert "provider calls made: 0" in rendered
    assert "writes enabled: no" in rendered
    assert "shell enabled: no" in rendered


def test_help_does_not_advertise_backend_switching() -> None:
    rendered = render_help()

    assert "/status" in rendered
    assert "/backend" not in rendered


def test_unknown_backend_command_is_not_exposed(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/backend proxy", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: unknown_command" in rendered
    assert "proxy_not_connected" not in rendered


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
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    assert DirectBackend().dry_run(contract).provider_calls_made == 0
    assert ProxyBackend().dry_run(contract).provider_calls_made == 0


def test_direct_backend_selects_only_reducible_context_segments(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first safe text", encoding="utf-8")
    second.write_text("second safe text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Use both files.",
        file_paths=[],
        context_files=[
            load_context_file(tmp_path, "first.txt"),
            load_context_file(tmp_path, "second.txt"),
        ],
    )
    non_reducible = ContextSegment(
        id="ctx_nonreducible",
        source_ref="internal/nonreducible",
        text="non reducible text",
        reducible=False,
        approx_size=18,
        approx_tokens=5,
    )
    contract = replace(
        contract,
        context_segments=[non_reducible, *contract.context_segments],
    )

    result = DirectBackend().dry_run(contract)

    assert "ctx_nonreducible" not in result.contract.audit["selected_segment_ids"]
    assert "ctx_nonreducible" not in result.contract.audit["router_input_segment_ids"]
    assert result.contract.audit["eligible_segment_count"] == 2
    assert result.contract.audit["selected_segment_count"] == 2


def test_direct_backend_never_selects_instructions_task_or_protected_segments(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="SECRET_TASK_TEXT",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    contract = replace(
        contract,
        protected_segments=[
            ProtectedText(id="protected_segment", text="PROTECTED_TEXT"),
        ],
    )

    result = DirectBackend().dry_run(contract)
    selected_ids = result.contract.audit["selected_segment_ids"]

    assert "instructions_default" not in selected_ids
    assert "task_current" not in selected_ids
    assert "protected_segment" not in selected_ids
    assert result.contract.audit["router_input_segment_ids"] == [
        contract.context_segments[0].id
    ]
    assert selected_ids == [contract.context_segments[0].id]


def test_direct_backend_sets_fallback_when_no_context_loaded(tmp_path) -> None:
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[],
    )

    result = DirectBackend().dry_run(contract)

    assert result.contract.audit["selector_mode"] == DETERMINISTIC_PREVIEW_MODE
    assert result.contract.audit["fallback_reason"] == "no_reducible_context_segments"
    assert result.contract.audit["selected_segment_ids"] == []
    assert result.contract.audit["eligible_segment_count"] == 0
    assert result.contract.audit["router_available"] is False
    assert (
        result.contract.audit["router_unavailable_reason"]
        == ROUTER_UNAVAILABLE_REASON
    )
    assert result.contract.audit["router_provider_calls_made"] == 0


def test_direct_backend_exposes_router_preview_metadata(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = DirectBackend().dry_run(contract)
    router = result.router_preview

    assert router is not None
    assert router.router_mode == DETERMINISTIC_PREVIEW_MODE
    assert router.router_available is False
    assert router.router_unavailable_reason == ROUTER_UNAVAILABLE_REASON
    assert router.router_provider_calls_made == 0
    assert router.input_segment_count == 1
    assert router.eligible_segment_count == 1
    assert router.selected_segment_count == 1
    assert router.selected_segment_ids == [contract.context_segments[0].id]
    assert router.router_input_segment_ids == [contract.context_segments[0].id]


def test_direct_backend_populates_selected_segment_ids_deterministically(
    tmp_path,
) -> None:
    for name in ("a.txt", "b.txt", "c.txt", "d.txt"):
        (tmp_path / name).write_text(name * 10, encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[
            load_context_file(tmp_path, "a.txt"),
            load_context_file(tmp_path, "b.txt"),
            load_context_file(tmp_path, "c.txt"),
            load_context_file(tmp_path, "d.txt"),
        ],
    )

    first = DirectBackend().dry_run(contract)
    second = DirectBackend().dry_run(contract)
    expected = [segment.id for segment in contract.context_segments[:3]]

    assert first.contract.audit["selected_segment_ids"] == expected
    assert second.contract.audit["selected_segment_ids"] == expected
    assert first.contract.audit["selected_segment_count"] == 3
    assert first.contract.audit["eligible_segment_count"] == 4


def test_direct_backend_estimates_tokens_and_reduction_pct(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("a" * 40, encoding="utf-8")
    second.write_text("b" * 40, encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[
            load_context_file(tmp_path, "first.txt"),
            load_context_file(tmp_path, "second.txt"),
        ],
    )

    result = DirectBackend().dry_run(contract)
    audit = result.contract.audit

    assert audit["estimated_input_tokens"] == 20
    assert audit["estimated_selected_tokens"] == 20
    assert audit["estimated_reduction_pct"] == 0.0
    assert audit["provider_calls_made"] == 0


def test_direct_backend_dry_run_returns_execution_preview(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = DirectBackend().dry_run(contract)

    assert result.execution_preview is not None
    assert result.execution_preview.backend_name == "direct"
    assert result.execution_preview.selector_mode == DETERMINISTIC_PREVIEW_MODE


def test_execution_preview_includes_selected_ids_counts_and_estimates(
    tmp_path,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("a" * 40, encoding="utf-8")
    second.write_text("b" * 40, encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[
            load_context_file(tmp_path, "first.txt"),
            load_context_file(tmp_path, "second.txt"),
        ],
    )

    preview = DirectBackend().dry_run(contract).execution_preview

    assert preview is not None
    assert preview.selected_segment_ids == [
        segment.id for segment in contract.context_segments
    ]
    assert preview.selected_segment_count == 2
    assert preview.selected_context_char_count == 80
    assert preview.selected_context_token_estimate == 20
    assert preview.total_context_char_count == 80
    assert preview.total_context_token_estimate == 20
    assert preview.estimated_reduction_pct == 0.0


def test_execution_preview_reports_disabled_capabilities_and_no_provider_calls(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    preview = DirectBackend().dry_run(contract).execution_preview

    assert preview is not None
    assert preview.provider_calls_made == 0
    assert preview.writes_enabled is False
    assert preview.shell_enabled is False


def test_execution_preview_keeps_internal_payload_without_rendering_it(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="SECRET_TASK_TEXT",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = DirectBackend().dry_run(contract)
    preview = result.execution_preview
    rendered = render_dry_run_summary(contract, result)

    assert preview is not None
    assert preview.executor_payload["task"].text == "SECRET_TASK_TEXT"
    assert (
        preview.executor_payload["selected_context_segments"][0].text
        == "SECRET_FILE_CONTENT"
    )
    assert "SECRET_TASK_TEXT" not in rendered
    assert "SECRET_FILE_CONTENT" not in rendered


def test_execution_preview_handles_no_context_with_fallback(tmp_path) -> None:
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[],
    )

    result = DirectBackend().dry_run(contract)
    preview = result.execution_preview

    assert preview is not None
    assert preview.selected_segment_ids == []
    assert preview.selected_segment_count == 0
    assert preview.fallback_reason == "no_reducible_context_segments"
    assert preview.selected_context_token_estimate == 0


def test_dry_run_rendering_omits_content_and_absolute_paths(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_dry_run_summary(contract, result)

    assert f"selector mode: {DETERMINISTIC_PREVIEW_MODE}" in rendered
    assert "DirectBackend execution preview" in rendered
    assert "DirectBackend router preview" in rendered
    assert "router available: False" in rendered
    assert f"router unavailable reason: {ROUTER_UNAVAILABLE_REASON}" in rendered
    assert "router provider calls made: 0" in rendered
    assert "selected segment ids: ['ctx_" in rendered
    assert "SECRET_FILE_CONTENT" not in rendered
    assert str(tmp_path) not in rendered
    assert "request body" not in rendered.lower()
    assert "provider payload" not in rendered.lower()
    assert "Authorization" not in rendered
    assert "API_KEY" not in rendered


def test_dry_run_renders_execution_preview_summary(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_dry_run_summary(contract, result)

    assert "DirectBackend execution preview" in rendered
    assert "DirectBackend router preview" in rendered
    assert "backend name: direct" in rendered
    assert "provider calls made: 0" in rendered
    assert "writes enabled: false" in rendered
    assert "shell enabled: false" in rendered
    assert "not an LLM router result" in rendered


def test_dry_run_renders_router_preview_metadata_safely(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="SECRET_TASK_TEXT",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_dry_run_summary(contract, result)

    assert "DirectBackend router preview" in rendered
    assert f"router mode: {DETERMINISTIC_PREVIEW_MODE}" in rendered
    assert "router available: False" in rendered
    assert f"router unavailable reason: {ROUTER_UNAVAILABLE_REASON}" in rendered
    assert "provider-backed router integration is a later phase" in rendered
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "SECRET_TASK_TEXT" not in rendered
    assert str(tmp_path) not in rendered


def test_proxy_backend_dry_run_remains_safe_and_does_not_call_proxy(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Task.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = ProxyBackend().dry_run(contract)

    assert result.provider_calls_made == 0
    assert result.summary["selector_mode"] == "proxy_not_connected"
    assert result.contract.audit["selected_segment_ids"] == []


def test_docs_mention_direct_backend_as_canonical_tui_path() -> None:
    note = (PROJECT_ROOT / "docs" / "tui_direct_backend_strategy.md").read_text(
        encoding="utf-8"
    )
    index = (PROJECT_ROOT / "docs" / "INDEX.md").read_text(encoding="utf-8")

    assert "DirectBackend is the default and only exposed backend" in note
    assert "No `/backend` command" in note
    assert "CodexCLI path remain compatibility and stress-test" in note
    assert "Router integration comes before executor integration" in note
    assert "`router_unavailable_reason=provider_required`" in note
    assert "tui_direct_backend_strategy.md" in index
