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
    DirectBackend,
    MISSING_TASK,
    ProxyBackend,
    backend_by_name,
)
from sfe_tui.contracts import (
    ContextSegment,
    MAX_CONTEXT_FILE_BYTES,
    PRIVATE_KEY_MARKERS,
    ProtectedText,
    build_contract,
    load_context_file,
    resolve_context_path,
    resolve_workspace,
)
from sfe_tui.executors import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_PATCH_OUTPUT_TOKENS,
    ExecutorResponse,
    OpenAIReadOnlyExecutor,
    PATCH_SYSTEM_INSTRUCTION,
    READ_ONLY_SYSTEM_INSTRUCTION,
)
from sfe_tui.renderer import (
    render_context_summary,
    render_dry_run_summary,
    render_help,
    render_status,
    render_workspace_selected,
    safe_workspace_label,
)
from sfe_tui.routers import (
    LOCAL_LEXICAL_PREVIEW_MODE,
    NO_MATCHING_CONTEXT_TERMS,
    NO_REDUCIBLE_CONTEXT_SEGMENTS,
    LocalSegmentRouter,
)


class FakeInput:
    def __init__(self, values: list[str]) -> None:
        self.values = list(values)
        self.prompts: list[str] = []

    def prompt(self, message: str, default: str = "") -> str:
        self.prompts.append(message)
        if not self.values:
            return default
        value = self.values.pop(0)
        return value if value else default


class FakeExecutor:
    def __init__(
        self,
        response: ExecutorResponse | None = None,
        patch_response: ExecutorResponse | None = None,
    ) -> None:
        self.response = response or ExecutorResponse(
            answer="mock answer",
            error_category=None,
            provider_calls_made=1,
        )
        self.patch_response = patch_response or ExecutorResponse(
            answer="diff --git a/context.txt b/context.txt\n--- a/context.txt\n+++ b/context.txt",
            error_category=None,
            provider_calls_made=1,
        )
        self.calls: list[dict[str, object]] = []
        self.patch_calls: list[dict[str, object]] = []

    def execute(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.calls.append(executor_payload)
        return self.response

    def propose_patch(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.patch_calls.append(executor_payload)
        return self.patch_response


class FakeProvider:
    def __init__(
        self,
        *,
        ok: bool = True,
        response: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.ok = ok
        self.response = response or {
            "choices": [{"message": {"content": "provider answer"}}]
        }
        self.error = error
        self.calls: list[dict[str, object]] = []

    def health(self) -> dict[str, object]:
        return {"ok": self.ok, "error": "sk-SECRET_SHOULD_NOT_RENDER_123456"}

    def chat(self, messages: list[dict[str, str]], **kwargs: object) -> dict[str, object]:
        self.calls.append({"messages": messages, **kwargs})
        if self.error is not None:
            raise self.error
        return self.response


def test_startup_accepts_empty_workspace_input_and_uses_cwd(tmp_path) -> None:
    assert resolve_workspace("", tmp_path) == tmp_path.resolve()


def test_startup_prompt_uses_current_without_absolute_path(tmp_path) -> None:
    input_provider = FakeInput(["", "/quit"])
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=input_provider,
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    assert input_provider.prompts[0] == "Workspace [current]: "
    assert "Workspace: ." in output
    assert str(tmp_path.resolve()) not in input_provider.prompts[0]
    assert str(tmp_path.resolve()) not in "\n".join(output)
    assert app.workspace_root == tmp_path.resolve()


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
    assert pwd_outputs[-1] == "Workspace: ."
    assert str(tmp_path.resolve()) not in "\n".join(output)
    assert "Authorization" not in "\n".join(output)


def test_workspace_root_remains_absolute_resolved_internally(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    assert app.workspace_root == tmp_path.resolve()
    assert app.workspace_root.is_absolute()
    assert str(tmp_path.resolve()) not in "\n".join(output)


def test_workspace_label_uses_relative_or_basename_without_absolute_path(
    tmp_path,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    outside = tmp_path.parent / "outside-workspace-label"
    outside.mkdir(exist_ok=True)

    assert safe_workspace_label(tmp_path, tmp_path) == "."
    assert safe_workspace_label(child, tmp_path) == "child"
    assert safe_workspace_label(outside, tmp_path) == "outside-workspace-label"
    assert str(tmp_path) not in render_workspace_selected(child, tmp_path)


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


def test_files_rejects_private_key_marker_in_non_source_file(tmp_path) -> None:
    source = tmp_path / "key.pem"
    source.write_text(
        f"{PRIVATE_KEY_MARKERS[0]}\nSECRET",
        encoding="utf-8",
    )

    loaded = load_context_file(tmp_path, "key.pem")

    assert loaded.loaded is False
    assert loaded.reason == "secret_like_file"


def test_files_loads_source_file_with_secret_marker_literal(tmp_path) -> None:
    source = tmp_path / "scanner.py"
    source.write_text(
        f"MARKER = {PRIVATE_KEY_MARKERS[0]!r}\n",
        encoding="utf-8",
    )

    loaded = load_context_file(tmp_path, "scanner.py")

    assert loaded.loaded is True
    assert loaded.reason is None
    assert loaded.warning_reason == "secret_marker_literal_in_source"
    assert loaded.source_ref == "scanner.py"


def test_files_loads_real_contracts_source_with_secret_marker_literals() -> None:
    loaded = load_context_file(PROJECT_ROOT, "sfe_tui/contracts.py")

    assert loaded.loaded is True
    assert loaded.reason is None
    assert loaded.warning_reason == "secret_marker_literal_in_source"
    assert loaded.source_ref == "sfe_tui/contracts.py"


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
    assert "warning reasons: {}" in rendered
    assert f"selector mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
    assert "request body" not in rendered.lower()
    assert "Authorization" not in rendered


def test_dry_run_summary_reports_source_marker_warning_safely(tmp_path) -> None:
    source = tmp_path / "scanner.py"
    source.write_text(
        f"MARKER = {PRIVATE_KEY_MARKERS[0]!r}\nSECRET_FILE_CONTENT",
        encoding="utf-8",
    )
    loaded = load_context_file(tmp_path, "scanner.py")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Explain scanner source.",
        file_paths=[],
        context_files=[loaded],
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_dry_run_summary(contract, result)

    assert loaded.loaded is True
    assert contract.metadata["warning_reason_counts"] == {
        "secret_marker_literal_in_source": 1
    }
    assert "warning reasons: {'secret_marker_literal_in_source': 1}" in rendered
    assert PRIVATE_KEY_MARKERS[0] not in rendered
    assert "SECRET_FILE_CONTENT" not in rendered
    assert str(tmp_path) not in rendered


def test_dry_run_with_context_but_missing_task_does_not_fake_reduction(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files context.txt", "/dry-run", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    dry_run_block = rendered.split("SFE dry-run summary", 1)[1]
    assert "task present: False" in dry_run_block
    assert "selected segments: 0" in dry_run_block
    assert f"fallback reason: {MISSING_TASK}" in dry_run_block
    assert "estimated selected tokens: 0" in dry_run_block
    assert "estimated reduction pct: None" in dry_run_block
    assert "estimated reduction pct: 100.0" not in dry_run_block
    assert "provider calls made: 0" in dry_run_block
    assert "SECRET_FILE_CONTENT" not in dry_run_block
    assert str(tmp_path.resolve()) not in rendered


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
    assert f"selector mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
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
    assert str(tmp_path.resolve()) not in rendered


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
    assert "/context" in rendered
    assert "/ask" in rendered
    assert "/patch" in rendered
    assert "/reset" in rendered
    assert "Clear task, context, and routing; preserve workspace" in rendered
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


def test_context_empty_state_is_safe(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/context", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE context" in rendered
    assert "loaded context segments: 0" in rendered
    assert "empty: no context loaded" in rendered
    assert str(tmp_path) not in rendered.split("SFE context", 1)[1]


def test_context_after_files_shows_ids_and_relative_refs_only(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files context.txt", "/context", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    context_block = rendered.split("SFE context", 1)[1]
    assert "id=ctx_" in context_block
    assert "ref=context.txt" in context_block
    assert "selected=no" in context_block
    assert "score=unrouted" in context_block
    assert "SECRET_FILE_CONTENT" not in context_block
    assert str(tmp_path) not in context_block


def test_context_after_dry_run_marks_selected_segments(tmp_path) -> None:
    first = tmp_path / "alpha.txt"
    second = tmp_path / "beta.txt"
    first.write_text("alpha routing", encoding="utf-8")
    second.write_text("unrelated", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files alpha.txt beta.txt",
                "/task Explain alpha routing",
                "/dry-run",
                "/context",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    context_block = rendered.split("SFE context", 1)[1]
    assert "ref=alpha.txt" in context_block
    assert "ref=beta.txt" in context_block
    assert "selected=yes" in context_block
    assert "selected=no" in context_block
    assert "score=high" in context_block
    assert "score=zero" in context_block


def test_reset_clears_task_context_skips_and_latest_state(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    outside = tmp_path.parent / "outside-reset.txt"
    outside.write_text("outside", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                f"/files context.txt {outside}",
                "/task Explain selected context",
                "/dry-run",
                "/reset",
                "/dry-run",
                "/status",
                "/context",
                "/pwd",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    dry_run_block = rendered.rsplit("SFE dry-run summary", 1)[1].split(
        "SFE TUI status",
        1,
    )[0]
    status_block = rendered.split("SFE TUI status", 1)[1].split("SFE context", 1)[0]
    context_block = rendered.split("SFE context", 1)[1]
    assert "Session reset. Workspace is preserved." in rendered
    assert app.workspace_root == tmp_path.resolve()
    assert app.context_files == []
    assert app.task == ""
    assert "loaded context files: 0" in status_block
    assert "skipped context files: 0" in status_block
    assert "task present: False" in status_block
    assert "task present: False" in dry_run_block
    assert "context segments: 0" in dry_run_block
    assert "loaded context segments: 0" in context_block
    assert "empty: no context loaded" in context_block
    assert "selected=yes" not in context_block
    assert "Workspace: ." in rendered
    assert str(tmp_path.resolve()) not in rendered
    assert str(outside) not in rendered


def test_reset_clears_latest_result_internally(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Explain selected context",
                "/dry-run",
                "/reset",
                "/quit",
            ]
        ),
        output=lambda _message: None,
        cwd=tmp_path,
    )

    assert app.run() == 0
    assert app.workspace_root == tmp_path.resolve()
    assert app.context_files == []
    assert app.task == ""
    assert app.latest_result is None


def test_ask_and_patch_fail_safely_after_reset(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Explain selected context",
                "/dry-run",
                "/reset",
                "/ask",
                "/patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert rendered.count("Error: missing_task") == 2
    assert not executor.calls
    assert not executor.patch_calls
    assert "calling provider" not in rendered
    assert str(tmp_path.resolve()) not in rendered


def test_context_after_ask_marks_selected_segments(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Explain selected context",
                "/ask",
                "/context",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=FakeExecutor()),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    context_block = rendered.split("SFE context", 1)[1]
    assert "selected=yes" in context_block
    assert "score=high" in context_block
    assert "mock answer" not in context_block
    assert "selected context text" not in context_block


def test_context_shows_warning_category_without_marker_or_content(tmp_path) -> None:
    source = tmp_path / "scanner.py"
    source.write_text(
        f"MARKER = {PRIVATE_KEY_MARKERS[0]!r}\nSECRET_FILE_CONTENT",
        encoding="utf-8",
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files scanner.py", "/context", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    context_block = rendered.split("SFE context", 1)[1]
    assert "warning=secret_marker_literal_in_source" in context_block
    assert PRIVATE_KEY_MARKERS[0] not in context_block
    assert "SECRET_FILE_CONTENT" not in context_block
    assert str(tmp_path) not in context_block
    assert "request body" not in context_block.lower()
    assert "provider payload" not in context_block.lower()
    assert "Authorization" not in context_block
    assert "API_KEY" not in context_block


def test_app_loop_quit_exits_cleanly(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0


def test_render_context_summary_uses_latest_result_selection(tmp_path) -> None:
    first = tmp_path / "alpha.txt"
    second = tmp_path / "beta.txt"
    first.write_text("alpha routing", encoding="utf-8")
    second.write_text("unrelated", encoding="utf-8")
    context_files = [
        load_context_file(tmp_path, "alpha.txt"),
        load_context_file(tmp_path, "beta.txt"),
    ]
    contract = build_contract(
        workspace_root=tmp_path,
        task="Explain alpha routing.",
        file_paths=[],
        context_files=context_files,
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_context_summary(
        contract=contract,
        context_files=context_files,
        latest_result=result,
    )

    assert "selected=yes" in rendered
    assert "selected=no" in rendered
    assert "score=high" in rendered
    assert "score=zero" in rendered
    assert str(tmp_path) not in rendered


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


def test_ask_requires_task(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("context", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files context.txt", "/ask", "/quit"]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "building contract" in rendered
    assert "Error: missing_task" in rendered
    assert not executor.calls


def test_ask_requires_loaded_context(tmp_path) -> None:
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Explain context", "/ask", "/quit"]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: no_context_loaded" in rendered
    assert not executor.calls


def test_ask_refuses_when_router_selects_no_context(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("unrelated material", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task database migrations", "/ask", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "routing context" in rendered
    assert "SFE ask failed" in rendered
    assert "reason: no_selected_context" in rendered
    assert "calling provider" not in rendered
    assert not executor.calls


def test_direct_backend_run_uses_selected_context_only(tmp_path) -> None:
    alpha = tmp_path / "alpha.txt"
    beta = tmp_path / "beta.txt"
    alpha.write_text("ALPHA_SECRET_CONTENT alpha routing", encoding="utf-8")
    beta.write_text("BETA_SECRET_CONTENT unrelated", encoding="utf-8")
    executor = FakeExecutor()
    contract = build_contract(
        workspace_root=tmp_path,
        task="Explain alpha routing.",
        file_paths=[],
        context_files=[
            load_context_file(tmp_path, "alpha.txt"),
            load_context_file(tmp_path, "beta.txt"),
        ],
    )

    result = DirectBackend(executor=executor).run(contract)

    assert result.answer == "mock answer"
    assert result.provider_calls_made == 1
    assert len(executor.calls) == 1
    selected = executor.calls[0]["selected_context_segments"]
    assert [segment.id for segment in selected] == [contract.context_segments[0].id]
    assert selected[0].text == "ALPHA_SECRET_CONTENT alpha routing"
    assert all("BETA_SECRET_CONTENT" not in segment.text for segment in selected)


def test_direct_backend_run_does_not_send_protected_segments_as_context(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    executor = FakeExecutor()
    contract = build_contract(
        workspace_root=tmp_path,
        task="Explain selected context.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    contract = replace(
        contract,
        protected_segments=[
            ProtectedText(id="protected_segment", text="PROTECTED_SEGMENT_SECRET"),
        ],
    )

    DirectBackend(executor=executor).run(contract)

    payload = executor.calls[0]
    assert "protected_segments" not in payload
    assert payload["instructions"]
    assert payload["task"] is contract.task
    assert payload["selected_context_segments"] == contract.context_segments


def test_ask_renders_answer_and_sanitized_summary(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT context", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Explain context", "/ask", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=FakeExecutor()),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    summary = rendered.split("SFE ask summary", 1)[1]
    assert "calling provider" in rendered
    assert "answer received" in rendered
    assert "SFE answer\nmock answer" in rendered
    assert "router mode: local_lexical_preview" in summary
    assert "selected segment ids: ['ctx_" in summary
    assert "provider calls made: 1" in summary
    assert "writes enabled: no" in summary
    assert "shell enabled: no" in summary
    assert "SECRET_FILE_CONTENT" not in summary
    assert "Explain context" not in summary
    assert str(tmp_path) not in summary
    assert str(tmp_path.resolve()) not in rendered


def test_ask_provider_failure_is_category_only(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("context", encoding="utf-8")
    api_key = "sk-SECRET_SHOULD_NOT_RENDER_123456"
    executor = FakeExecutor(
        ExecutorResponse(
            answer=None,
            error_category="provider_error",
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Explain context", "/ask", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE ask failed" in rendered
    assert "reason: provider_error" in rendered
    assert api_key not in rendered
    assert "Authorization" not in rendered
    assert "request body" not in rendered.lower()
    assert "provider payload" not in rendered.lower()


def test_patch_requires_task(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("context", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files context.txt", "/patch", "/quit"]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "building contract" in rendered
    assert "Error: missing_task" in rendered
    assert not executor.patch_calls


def test_patch_requires_loaded_context(tmp_path) -> None:
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Update context", "/patch", "/quit"]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: no_context_loaded" in rendered
    assert not executor.patch_calls


def test_patch_refuses_when_router_selects_no_context(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("unrelated material", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task database migrations", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "routing context" in rendered
    assert "SFE patch failed" in rendered
    assert "reason: no_selected_context" in rendered
    assert "calling provider" not in rendered
    assert not executor.patch_calls


def test_direct_backend_patch_uses_selected_context_only(tmp_path) -> None:
    alpha = tmp_path / "alpha.txt"
    beta = tmp_path / "beta.txt"
    alpha.write_text("ALPHA_SECRET_CONTENT alpha routing", encoding="utf-8")
    beta.write_text("BETA_SECRET_CONTENT unrelated", encoding="utf-8")
    executor = FakeExecutor()
    contract = build_contract(
        workspace_root=tmp_path,
        task="Patch alpha routing.",
        file_paths=[],
        context_files=[
            load_context_file(tmp_path, "alpha.txt"),
            load_context_file(tmp_path, "beta.txt"),
        ],
    )

    result = DirectBackend(executor=executor).patch(contract)

    assert result.status == "patch_proposed"
    assert result.answer is not None
    assert result.provider_calls_made == 1
    assert result.summary["patch_applied"] is False
    assert not executor.calls
    assert len(executor.patch_calls) == 1
    selected = executor.patch_calls[0]["selected_context_segments"]
    assert [segment.id for segment in selected] == [contract.context_segments[0].id]
    assert selected[0].text == "ALPHA_SECRET_CONTENT alpha routing"
    assert all("BETA_SECRET_CONTENT" not in segment.text for segment in selected)


def test_direct_backend_patch_does_not_send_protected_segments_as_context(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    executor = FakeExecutor()
    contract = build_contract(
        workspace_root=tmp_path,
        task="Patch selected context.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    contract = replace(
        contract,
        protected_segments=[
            ProtectedText(id="protected_segment", text="PROTECTED_SEGMENT_SECRET"),
        ],
    )

    DirectBackend(executor=executor).patch(contract)

    payload = executor.patch_calls[0]
    assert "protected_segments" not in payload
    assert payload["instructions"]
    assert payload["task"] is contract.task
    assert payload["selected_context_segments"] == contract.context_segments


def test_patch_renders_proposal_and_sanitized_summary(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT context", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=FakeExecutor()),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    summary = rendered.split("SFE patch summary", 1)[1]
    assert "calling provider" in rendered
    assert "Patch proposal only, not applied" in rendered
    assert "diff --git a/context.txt b/context.txt" in rendered
    assert "router mode: local_lexical_preview" in summary
    assert "selected segment ids: ['ctx_" in summary
    assert "provider calls made: 1" in summary
    assert "writes enabled: no" in summary
    assert "shell enabled: no" in summary
    assert "patch applied: no" in summary
    assert "SECRET_FILE_CONTENT" not in summary
    assert "Patch context" not in summary
    assert str(tmp_path) not in summary
    assert str(tmp_path.resolve()) not in rendered
    assert "request body" not in summary.lower()
    assert "provider payload" not in summary.lower()
    assert "Authorization" not in summary
    assert "API_KEY" not in summary


def test_patch_provider_failure_is_category_only(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("context", encoding="utf-8")
    api_key = "sk-SECRET_SHOULD_NOT_RENDER_123456"
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=None,
            error_category="provider_error",
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE patch failed" in rendered
    assert "reason: provider_error" in rendered
    assert "patch applied: no" in rendered
    assert api_key not in rendered
    assert "Authorization" not in rendered
    assert "request body" not in rendered.lower()
    assert "provider payload" not in rendered.lower()


def test_openai_executor_reports_provider_not_configured_without_key_leak() -> None:
    provider = FakeProvider(ok=False)
    executor = OpenAIReadOnlyExecutor(provider=provider, model="test-model")

    result = executor.execute(
        {
            "instructions": [],
            "task": None,
            "selected_context_segments": [],
        }
    )

    assert result.answer is None
    assert result.error_category == "provider_not_configured"
    assert result.provider_calls_made == 0
    assert not provider.calls


def test_openai_executor_returns_invalid_response_category() -> None:
    provider = FakeProvider(response={"choices": [{"message": {"content": ""}}]})
    executor = OpenAIReadOnlyExecutor(provider=provider, model="test-model")

    result = executor.execute(
        {
            "instructions": [],
            "task": None,
            "selected_context_segments": [],
        }
    )

    assert result.answer is None
    assert result.error_category == "invalid_response"
    assert result.provider_calls_made == 1


def test_openai_executor_uses_tui_default_output_token_budget() -> None:
    provider = FakeProvider()
    executor = OpenAIReadOnlyExecutor(provider=provider, model="test-model")

    result = executor.execute(
        {
            "instructions": [],
            "task": None,
            "selected_context_segments": [],
        }
    )

    assert result.answer == "provider answer"
    assert DEFAULT_MAX_OUTPUT_TOKENS == 1500
    assert provider.calls[0]["max_tokens"] == 1500


def test_openai_executor_patch_uses_patch_instruction_and_output_budget() -> None:
    provider = FakeProvider()
    executor = OpenAIReadOnlyExecutor(provider=provider, model="test-model")

    result = executor.propose_patch(
        {
            "instructions": [],
            "task": None,
            "selected_context_segments": [],
        }
    )

    assert result.answer == "provider answer"
    assert DEFAULT_PATCH_OUTPUT_TOKENS == 4000
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
    assert provider.calls[0]["system_instruction"] != READ_ONLY_SYSTEM_INSTRUCTION
    assert provider.calls[0]["max_tokens"] == 4000


def test_local_segment_router_selects_matching_segment() -> None:
    alpha = ContextSegment(
        id="ctx_alpha",
        source_ref="alpha.txt",
        text="routing context alpha",
        approx_size=21,
        approx_tokens=6,
    )
    beta = ContextSegment(
        id="ctx_beta",
        source_ref="beta.txt",
        text="unrelated material",
        approx_size=18,
        approx_tokens=5,
    )

    result = LocalSegmentRouter().route("Explain alpha routing", [beta, alpha])

    assert result.router_mode == LOCAL_LEXICAL_PREVIEW_MODE
    assert result.router_available is True
    assert result.provider_calls_made == 0
    assert result.selected_segment_ids == ["ctx_alpha"]
    assert result.selected_segment_count == 1
    assert result.fallback_reason is None


def test_local_segment_router_boosts_source_ref_relevance() -> None:
    source_named = ContextSegment(
        id="ctx_router",
        source_ref="sfe_tui/routers.py",
        text="small implementation file",
        approx_size=25,
        approx_tokens=7,
    )
    content_named = ContextSegment(
        id="ctx_notes",
        source_ref="docs/notes.md",
        text="router concepts appear here",
        approx_size=27,
        approx_tokens=7,
    )

    result = LocalSegmentRouter().route(
        "Explain router selection.",
        [content_named, source_named],
    )

    assert result.selected_segment_ids[0] == "ctx_router"
    assert result.score_categories_by_segment_id["ctx_router"] == "medium"
    assert result.score_categories_by_segment_id["ctx_notes"] == "low"


def test_local_segment_router_source_ref_match_requires_non_empty_context() -> None:
    empty_named = ContextSegment(
        id="ctx_router",
        source_ref="sfe_tui/routers.py",
        text="",
        approx_size=0,
        approx_tokens=0,
    )

    result = LocalSegmentRouter().route("Explain router selection.", [empty_named])

    assert result.selected_segment_ids == []
    assert result.eligible_segment_count == 0
    assert result.fallback_reason == NO_REDUCIBLE_CONTEXT_SEGMENTS


def test_local_segment_router_only_considers_reducible_segments() -> None:
    protected_like = ContextSegment(
        id="ctx_protected_like",
        source_ref="protected.txt",
        text="alpha routing",
        reducible=False,
        approx_size=13,
        approx_tokens=4,
    )
    reducible = ContextSegment(
        id="ctx_reducible",
        source_ref="context.txt",
        text="alpha routing",
        approx_size=13,
        approx_tokens=4,
    )

    result = LocalSegmentRouter().route("alpha routing", [protected_like, reducible])

    assert result.router_input_segment_ids == ["ctx_reducible"]
    assert result.selected_segment_ids == ["ctx_reducible"]


def test_local_segment_router_returns_safe_no_match_fallback() -> None:
    segment = ContextSegment(
        id="ctx_beta",
        source_ref="beta.txt",
        text="unrelated material",
        approx_size=18,
        approx_tokens=5,
    )

    result = LocalSegmentRouter().route("alpha routing", [segment])

    assert result.selected_segment_ids == []
    assert result.selected_segment_count == 0
    assert result.fallback_reason == NO_MATCHING_CONTEXT_TERMS
    assert result.score_category_counts == {
        "high": 0,
        "medium": 0,
        "low": 0,
        "zero": 1,
    }


def test_local_segment_router_selects_router_source_for_router_task() -> None:
    routers = ContextSegment(
        id="ctx_routers",
        source_ref="sfe_tui/routers.py",
        text="route local segments",
        approx_size=20,
        approx_tokens=5,
    )
    tests = ContextSegment(
        id="ctx_tests",
        source_ref="tests/test_sfe_tui.py",
        text="local lexical router selects context segments before executor",
        approx_size=62,
        approx_tokens=16,
    )
    docs = ContextSegment(
        id="ctx_docs",
        source_ref="docs/tui_direct_backend_strategy.md",
        text="context routing before executor integration",
        approx_size=44,
        approx_tokens=11,
    )
    renderer = ContextSegment(
        id="ctx_renderer",
        source_ref="sfe_tui/renderer.py",
        text="render selected context diagnostics",
        approx_size=35,
        approx_tokens=9,
    )

    result = LocalSegmentRouter().route(
        "Explain how the local lexical router selects context segments before the read-only executor call.",
        [tests, docs, renderer, routers],
    )

    assert "ctx_routers" in result.selected_segment_ids
    assert result.score_categories_by_segment_id["ctx_routers"] == "high"


def test_direct_backend_selects_only_reducible_context_segments(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("first safe text", encoding="utf-8")
    second.write_text("second safe text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Find first and second text.",
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
        task="Find context text.",
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

    assert result.contract.audit["selector_mode"] == LOCAL_LEXICAL_PREVIEW_MODE
    assert result.contract.audit["fallback_reason"] == NO_REDUCIBLE_CONTEXT_SEGMENTS
    assert result.contract.audit["selected_segment_ids"] == []
    assert result.contract.audit["eligible_segment_count"] == 0
    assert result.contract.audit["router_available"] is True
    assert result.contract.audit["router_unavailable_reason"] is None
    assert result.contract.audit["router_provider_calls_made"] == 0


def test_direct_backend_exposes_router_preview_metadata(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Find safe context.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = DirectBackend().dry_run(contract)
    router = result.router_preview

    assert router is not None
    assert router.router_mode == LOCAL_LEXICAL_PREVIEW_MODE
    assert router.router_available is True
    assert router.router_unavailable_reason is None
    assert router.router_provider_calls_made == 0
    assert router.input_segment_count == 1
    assert router.eligible_segment_count == 1
    assert router.selected_segment_count == 1
    assert router.selected_segment_ids == [contract.context_segments[0].id]
    assert router.router_input_segment_ids == [contract.context_segments[0].id]
    assert router.score_category_counts["high"] == 1


def test_direct_backend_populates_selected_segment_ids_by_lexical_score(
    tmp_path,
) -> None:
    (tmp_path / "alpha.txt").write_text("alpha beta gamma", encoding="utf-8")
    (tmp_path / "beta.txt").write_text("beta gamma", encoding="utf-8")
    (tmp_path / "gamma.txt").write_text("gamma", encoding="utf-8")
    (tmp_path / "delta.txt").write_text("unmatched", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="alpha beta gamma",
        file_paths=[],
        context_files=[
            load_context_file(tmp_path, "alpha.txt"),
            load_context_file(tmp_path, "beta.txt"),
            load_context_file(tmp_path, "gamma.txt"),
            load_context_file(tmp_path, "delta.txt"),
        ],
    )

    first = DirectBackend().dry_run(contract)
    second = DirectBackend().dry_run(contract)
    expected = [segment.id for segment in contract.context_segments[:3]]

    assert first.contract.audit["selected_segment_ids"] == expected
    assert second.contract.audit["selected_segment_ids"] == expected
    assert first.contract.audit["selected_segment_count"] == 3
    assert first.contract.audit["eligible_segment_count"] == 4
    assert first.contract.audit["router_score_category_counts"] == {
        "high": 2,
        "medium": 1,
        "low": 0,
        "zero": 1,
    }


def test_direct_backend_estimates_tokens_and_reduction_pct(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("a" * 40, encoding="utf-8")
    second.write_text("b" * 40, encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="first second.",
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


def test_direct_backend_dry_run_missing_task_has_no_reduction_pct(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = DirectBackend().dry_run(contract)
    audit = result.contract.audit

    assert audit["fallback_reason"] == MISSING_TASK
    assert audit["selected_segment_ids"] == []
    assert audit["selected_segment_count"] == 0
    assert audit["eligible_segment_count"] == 1
    assert audit["estimated_input_tokens"] == contract.context_segments[0].approx_tokens
    assert audit["estimated_selected_tokens"] == 0
    assert audit["estimated_reduction_pct"] is None
    assert audit["provider_calls_made"] == 0
    assert result.router_preview is not None
    assert result.router_preview.fallback_reason == MISSING_TASK
    assert result.execution_preview is not None
    assert result.execution_preview.estimated_reduction_pct is None


def test_direct_backend_dry_run_returns_execution_preview(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("safe context text", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Find context.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = DirectBackend().dry_run(contract)

    assert result.execution_preview is not None
    assert result.execution_preview.backend_name == "direct"
    assert result.execution_preview.selector_mode == LOCAL_LEXICAL_PREVIEW_MODE


def test_execution_preview_includes_selected_ids_counts_and_estimates(
    tmp_path,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("a" * 40, encoding="utf-8")
    second.write_text("b" * 40, encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="first second.",
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
        task="Find context.",
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
        task="SECRET_TASK_TEXT context",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )

    result = DirectBackend().dry_run(contract)
    preview = result.execution_preview
    rendered = render_dry_run_summary(contract, result)

    assert preview is not None
    assert preview.executor_payload["task"].text == "SECRET_TASK_TEXT context"
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
    assert preview.fallback_reason == NO_REDUCIBLE_CONTEXT_SEGMENTS
    assert preview.selected_context_token_estimate == 0


def test_dry_run_rendering_omits_content_and_absolute_paths(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    contract = build_contract(
        workspace_root=tmp_path,
        task="Find context.",
        file_paths=[],
        context_files=[load_context_file(tmp_path, "context.txt")],
    )
    result = DirectBackend().dry_run(contract)

    rendered = render_dry_run_summary(contract, result)

    assert f"selector mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
    assert "DirectBackend execution preview" in rendered
    assert "DirectBackend router preview" in rendered
    assert "router available: True" in rendered
    assert "router unavailable reason: None" in rendered
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
        task="Find context.",
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
    assert f"router mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
    assert "router available: True" in rendered
    assert "router unavailable reason: None" in rendered
    assert "provider-free lexical preview only" in rendered
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
    assert "`local_lexical_preview`" in note
    assert "`/ask` is the first read-only executor phase" in note
    assert "does not use" in note
    assert "the proxy, write files, execute shell commands" in note
    assert "not an LLM router result" in note
    assert "tui_direct_backend_strategy.md" in index
    milestone = (
        PROJECT_ROOT / "docs" / "tui_readonly_ask_milestone.md"
    ).read_text(encoding="utf-8")
    assert "selected 3 of 7 context segments" in milestone
    assert "38.92%" in milestone
    assert "36.58%" in milestone
    assert "40.83%" in milestone
    assert "raised from 800 to 1500 tokens" in milestone
    assert "source/path-aware lexical ranking" in milestone
    assert "`/patch` is the next proposal-only phase" in milestone
    assert "Patch proposal only, not applied" in milestone
    assert "does not write files, apply patches, execute shell commands" in milestone
    assert "larger local output budget than" in milestone
    assert "`/reset` exists as a session comfort command" in milestone
    assert "preserves the selected workspace" in milestone
    assert "not a benchmark" in milestone
    assert "tui_readonly_ask_milestone.md" in index
