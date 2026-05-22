"""Tests for the first-party SFE-aware TUI skeleton."""

from __future__ import annotations

import io
import sys
import urllib.error
from dataclasses import replace
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.lemonade import LemonadeProvider, LemonadeProviderError
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
    create_tui_executor,
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


class FakeHTTPResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def valid_text_diff(
    path: str = "context.txt",
    *,
    old: str = "old context",
    new: str = "new context",
) -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -1,1 +1,1 @@",
            f"-{old}",
            f"+{new}",
        ]
    )


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


def test_directory_reports_selected_workspace_safely(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/directory", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    directory_outputs = [line for line in output if line.startswith("Workspace:")]
    assert directory_outputs
    assert directory_outputs[-1] == "Workspace: ."
    assert str(tmp_path.resolve()) not in "\n".join(output)
    assert "Authorization" not in "\n".join(output)


def test_pwd_remains_undocumented_workspace_alias(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/pwd", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Workspace: ." in rendered
    assert "/pwd" not in render_help()
    assert str(tmp_path.resolve()) not in rendered


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


def test_files_directory_input_reports_clear_safe_rejection(tmp_path) -> None:
    directory = tmp_path / "docs"
    directory.mkdir()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files docs", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Context files replaced: loaded 0; skipped 1" in rendered
    assert "not_a_file" in rendered
    assert "unsupported file input; provide a file path, not a directory" in rendered
    assert str(directory.resolve()) not in rendered


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
    assert "warning reasons: none" in rendered
    assert f"selector mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
    assert "executor/provider called: no" in rendered
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
    assert "warning reasons: secret_marker_literal_in_source: 1" in rendered
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
    assert "task present: no" in dry_run_block
    assert "selected segments: 0" in dry_run_block
    assert f"fallback reason: {MISSING_TASK}" in dry_run_block
    assert "action: missing task; set one with /task <text>" in dry_run_block
    assert "estimated selected tokens: 0" in dry_run_block
    assert "estimated reduction pct: unknown" in dry_run_block
    assert "None" not in dry_run_block
    assert "estimated reduction pct: 100.0" not in dry_run_block
    assert "provider calls made: 0" in dry_run_block
    assert "executor/provider called: no" in dry_run_block
    assert "writes disabled" in dry_run_block
    assert "shell disabled" in dry_run_block
    assert "patch application disabled" in dry_run_block
    assert "SECRET_FILE_CONTENT" not in dry_run_block
    assert str(tmp_path.resolve()) not in rendered


def test_dry_run_after_task_requires_discovery_without_manual_context(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Explain context", "/dry-run", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert (
        "Error: discovery_not_run - run /discover after /task before this command"
        in rendered
    )
    assert "SFE dry-run summary" not in rendered
    assert "calling provider" not in rendered
    assert "ProxyBackend" not in rendered
    assert "/backend" not in rendered


def test_dry_run_with_no_selected_context_is_actionable(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("unrelated material", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task database migrations", "/dry-run", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    dry_run_block = rendered.split("SFE dry-run summary", 1)[1]
    assert "context loaded: yes" in dry_run_block
    assert "selected segments: 0" in dry_run_block
    assert f"fallback reason: {NO_MATCHING_CONTEXT_TERMS}" in dry_run_block
    assert "routing found no relevant context segments" in dry_run_block
    assert "selected segment ids: none" in dry_run_block
    assert "selected source refs: none" in dry_run_block


def test_dry_run_with_skipped_inputs_reports_rejections_safely(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context", encoding="utf-8")
    outside = tmp_path.parent / "outside-dry-run.txt"
    outside.write_text("OUTSIDE_SECRET", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                f"/files context.txt {outside}",
                "/task Explain selected context",
                "/dry-run",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    dry_run_block = rendered.split("SFE dry-run summary", 1)[1]
    assert "Skipped/rejected context" in dry_run_block
    assert "skipped files: 1" in dry_run_block
    assert "skipped reasons: outside_workspace: 1" in dry_run_block
    assert "selected source refs: context.txt" in dry_run_block
    assert "OUTSIDE_SECRET" not in dry_run_block
    assert "outside-dry-run.txt" not in dry_run_block
    assert str(outside) not in dry_run_block
    assert str(tmp_path.resolve()) not in dry_run_block
    assert "{}" not in dry_run_block


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
    assert "loaded context segments: 1" in summary


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
    assert "Context files replaced: loaded 1; skipped 0" in rendered
    assert "Task stored." in rendered
    assert "SFE dry-run summary" in rendered
    assert f"selector mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
    assert "selected segment ids: ctx_" in rendered
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
    assert "Context files replaced: loaded 0; skipped 1" in rendered
    assert "outside_workspace" in rendered
    assert "path is outside the selected workspace" in rendered
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
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "loaded context files: 1" in rendered
    assert "skipped context files: 0" in rendered
    assert "loaded context segments: 1" in rendered
    assert "task present: True" in rendered
    assert "workspace: ." in status_block
    assert "latest result present: no" in status_block
    assert "latest result kind: none" in status_block
    assert "latest provider calls made: 0" in status_block
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "Explain the context" not in rendered
    assert str(tmp_path.resolve()) not in rendered


def test_status_before_any_task_or_context_is_coherent(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/status", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "workspace selected: True" in status_block
    assert "workspace: ." in status_block
    assert "loaded context files: 0" in status_block
    assert "skipped context files: 0" in status_block
    assert "loaded context segments: 0" in status_block
    assert "task present: False" in status_block
    assert "latest result present: no" in status_block
    assert "latest result kind: none" in status_block
    assert "latest provider calls made: 0" in status_block
    assert "writes enabled: no" in status_block
    assert "shell enabled: no" in status_block
    assert "patch application enabled: no" in status_block
    assert "/backend" not in status_block
    assert "ProxyBackend" not in status_block
    assert str(tmp_path.resolve()) not in status_block


def test_status_after_task_reports_task_without_content(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task SECRET_TASK_TEXT", "/status", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "task present: True" in status_block
    assert "loaded context segments: 0" in status_block
    assert "latest result present: no" in status_block
    assert "SECRET_TASK_TEXT" not in status_block


def test_status_after_files_reports_context_counts_without_content(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files context.txt", "/status", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "loaded context files: 1" in status_block
    assert "skipped context files: 0" in status_block
    assert "loaded context segments: 1" in status_block
    assert "task present: False" in status_block
    assert "latest result present: no" in status_block
    assert "SECRET_FILE_CONTENT" not in status_block
    assert str(tmp_path.resolve()) not in status_block


def test_status_after_dry_run_reports_latest_result_and_no_provider_calls(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Explain selected context",
                "/dry-run",
                "/status",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "latest result present: yes" in status_block
    assert "latest result kind: dry_run_only" in status_block
    assert "latest provider calls made: 0" in status_block
    assert "writes enabled: no" in status_block
    assert "shell enabled: no" in status_block
    assert "patch application enabled: no" in status_block


def test_status_after_ask_reports_latest_provider_calls(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Explain selected context",
                "/ask",
                "/status",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=FakeExecutor()),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "latest result present: yes" in status_block
    assert "latest result kind: ask_completed" in status_block
    assert "latest provider calls made: 1" in status_block
    assert "writes enabled: no" in status_block
    assert "shell enabled: no" in status_block
    assert "patch application enabled: no" in status_block


def test_status_reports_discovery_state_without_content(tmp_path) -> None:
    source = tmp_path / "context.md"
    source.write_text("SECRET_FILE_CONTENT", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Explain context", "/discover", "/status", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "discovery result present: yes" in status_block
    assert "discovered candidates: 1" in status_block
    assert "discovered loaded candidates: 1" in status_block
    assert "SECRET_FILE_CONTENT" not in status_block
    assert "Explain context" not in status_block
    assert str(tmp_path.resolve()) not in status_block


def test_status_reports_direct_backend_and_disabled_capabilities() -> None:
    rendered = render_status(
        workspace_selected=True,
        workspace_label=".",
        loaded_context_files=2,
        skipped_context_files=1,
        loaded_context_segments=2,
        task_present=True,
        backend_name="direct",
        latest_result=None,
    )

    assert "backend: direct" in rendered
    assert "workspace: ." in rendered
    assert "latest provider calls made: 0" in rendered
    assert "writes enabled: no" in rendered
    assert "shell enabled: no" in rendered
    assert "patch application enabled: no" in rendered
    assert "ProxyBackend" not in rendered
    assert "/backend" not in rendered


def test_help_does_not_advertise_backend_switching() -> None:
    rendered = render_help()

    assert "/directory" in rendered
    assert "/pwd" not in rendered
    assert "/status" in rendered
    assert "/context" in rendered
    assert "/discover" in rendered
    assert "/ask" in rendered
    assert "/patch" in rendered
    assert "/reset" in rendered
    assert "/files <paths...>  Replace context manually for debug/design" in rendered
    assert "files or directories" not in rendered
    assert "Add context" not in rendered
    assert "ProxyBackend" not in rendered
    assert "Clear task, context, discovery, and routing; preserve workspace" in rendered
    assert "/backend" not in rendered
    assert rendered.index("/directory") < rendered.index("/status")
    assert rendered.index("/task <text>") < rendered.index("/discover")
    assert rendered.index("/discover") < rendered.index("/dry-run")
    assert rendered.index("/dry-run") < rendered.index("/context")
    assert rendered.index("/context") < rendered.index("/ask")
    assert rendered.index("/patch") < rendered.index("/files <paths...>")


def test_task_without_text_is_actionable_error_and_preserves_existing_task(
    tmp_path,
) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Keep this task", "/task", "/status", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Task stored." in rendered
    assert "Error: missing_task - missing task; set one with /task <text>" in rendered
    assert rendered.count("Task stored.") == 1
    assert "task present: True" in rendered


def test_unknown_command_suggests_help(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/wat", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: unknown_command" in rendered
    assert "use /help to list commands" in rendered


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
    assert "use /help to list commands" in rendered
    assert "proxy_not_connected" not in rendered


def test_discover_without_task_reports_missing_task(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/discover", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: missing_task - missing task; set one with /task <text>" in rendered
    assert "SFE discovery" not in rendered


def test_discover_after_task_reports_safe_summary(tmp_path) -> None:
    source = tmp_path / "context.md"
    source.write_text("SECRET_FILE_CONTENT alpha routing", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task SECRET_TASK_TEXT alpha", "/discover", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    discovery_block = rendered.split("SFE discovery", 1)[1]
    assert "discovery ran: yes" in discovery_block
    assert "workspace selected: yes" in discovery_block
    assert "task present: yes" in discovery_block
    assert "scanned files: 1" in discovery_block
    assert "candidates: 1" in discovery_block
    assert "loaded candidate count: 1" in discovery_block
    assert "top candidate source refs: context.md" in discovery_block
    assert "SECRET_FILE_CONTENT" not in discovery_block
    assert "SECRET_TASK_TEXT" not in discovery_block
    assert str(tmp_path.resolve()) not in discovery_block
    assert "Authorization" not in discovery_block
    assert "API_KEY" not in discovery_block


def test_ask_before_discover_reports_error_and_makes_zero_provider_calls(
    tmp_path,
) -> None:
    source = tmp_path / "context.md"
    source.write_text("alpha routing content", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task alpha routing", "/ask", "/quit"]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: discovery_not_run" in rendered
    assert "calling provider" not in rendered
    assert executor.calls == []


def test_patch_before_discover_reports_error_and_makes_zero_provider_calls(
    tmp_path,
) -> None:
    source = tmp_path / "context.md"
    source.write_text("alpha routing content", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task alpha routing", "/patch", "/quit"]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: discovery_not_run" in rendered
    assert "calling provider" not in rendered
    assert executor.patch_calls == []


def test_discover_then_dry_run_reloads_full_text_for_routing(tmp_path) -> None:
    source = tmp_path / "context.md"
    source.write_text("alpha routing content", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task alpha routing", "/discover", "/dry-run", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    dry_run_block = rendered.split("SFE dry-run summary", 1)[1]
    assert "context loaded: yes" in dry_run_block
    assert "selected segments: 1" in dry_run_block
    assert "selected source refs: context.md" in dry_run_block
    assert "alpha routing content" not in rendered
    assert str(tmp_path.resolve()) not in rendered


def test_discover_with_no_candidates_allows_dry_run_but_not_provider_call(
    tmp_path,
) -> None:
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task missing context",
                "/discover",
                "/dry-run",
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
    assert "candidates: 0" in rendered
    assert "SFE dry-run summary" in rendered
    assert "context loaded: no" in rendered
    assert f"fallback reason: {NO_REDUCIBLE_CONTEXT_SEGMENTS}" in rendered
    assert rendered.count("Error: no_context_loaded") == 2
    assert "calling provider" not in rendered
    assert executor.calls == []
    assert executor.patch_calls == []


def test_discover_then_ask_can_call_executor_when_context_is_selected(
    tmp_path,
) -> None:
    source = tmp_path / "context.md"
    source.write_text("alpha routing content", encoding="utf-8")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task alpha routing", "/discover", "/ask", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "calling provider" in rendered
    assert "answer received" in rendered
    assert len(executor.calls) == 1
    selected_segments = executor.calls[0]["selected_context_segments"]
    assert selected_segments[0].text == "alpha routing content"
    assert "alpha routing content" not in rendered


def test_task_after_discover_invalidates_discovery_until_rerun(tmp_path) -> None:
    source = tmp_path / "context.md"
    source.write_text("alpha routing content", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task alpha routing",
                "/discover",
                "/task beta routing",
                "/dry-run",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert rendered.count("Task stored.") == 2
    assert "Error: discovery_not_run" in rendered


def test_manual_files_context_still_works_without_discover(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("manual alpha routing", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task manual alpha", "/dry-run", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE dry-run summary" in rendered
    assert "selected source refs: context.txt" in rendered
    assert "Error: discovery_not_run" not in rendered


def test_manual_files_context_takes_precedence_over_discovered_context(
    tmp_path,
) -> None:
    manual = tmp_path / "manual.txt"
    discovered = tmp_path / "auto.md"
    manual.write_text("manual-only context", encoding="utf-8")
    discovered.write_text("auto unique context", encoding="utf-8")
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files manual.txt",
                "/task auto unique",
                "/discover",
                "/dry-run",
                "/quit",
            ]
        ),
        output=lambda _message: None,
        cwd=tmp_path,
    )

    assert app.run() == 0
    assert app.latest_result is not None
    refs = [segment.source_ref for segment in app.latest_result.contract.context_segments]
    assert refs == ["manual.txt"]


def test_reset_clears_discovery_state(tmp_path) -> None:
    source = tmp_path / "context.md"
    source.write_text("alpha routing content", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task alpha routing",
                "/discover",
                "/reset",
                "/status",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert app.discovery_result is None
    assert "discovery result present: no" in status_block
    assert "discovered candidates: 0" in status_block


def test_discovery_excludes_sensitive_generated_and_non_text_files_in_tui(
    tmp_path,
) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=SECRET", encoding="utf-8")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "hidden.md").write_text("hidden content", encoding="utf-8")
    logs = tmp_path / "logs"
    logs.mkdir()
    (logs / "app.log").write_text("log content", encoding="utf-8")
    cache = tmp_path / ".pytest_cache"
    cache.mkdir()
    (cache / "cache.md").write_text("cache content", encoding="utf-8")
    (tmp_path / "data.txt").write_bytes(b"safe\x00binary")
    (tmp_path / "safe.md").write_text("safe alpha context", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task safe alpha", "/discover", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    discovery_block = rendered.split("SFE discovery", 1)[1]
    assert "top candidate source refs: safe.md" in discovery_block
    assert ".env" not in discovery_block
    assert "hidden.md" not in discovery_block
    assert "app.log" not in discovery_block
    assert "cache.md" not in discovery_block
    assert "data.txt" not in discovery_block
    assert "secret_like_file" in discovery_block
    assert "binary_or_non_text" in discovery_block
    assert "safe alpha context" not in discovery_block


def test_discovered_context_summary_is_content_safe(tmp_path) -> None:
    source = tmp_path / "context.md"
    source.write_text("SECRET_FILE_CONTENT alpha routing", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task SECRET_TASK_TEXT alpha",
                "/discover",
                "/dry-run",
                "/context",
                "/status",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "discovery result present: yes" in rendered
    assert "discovered source refs: context.md" in rendered
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "SECRET_TASK_TEXT" not in rendered
    assert str(tmp_path.resolve()) not in rendered
    assert "Authorization" not in rendered
    assert "request body" not in rendered.lower()


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
    assert "skipped context files: 0" in rendered
    assert "skipped reasons: none" in rendered
    assert "latest selected segment ids: []" in rendered
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
    assert "loaded context segments: 1" in context_block
    assert "skipped context files: 0" in context_block
    assert "skipped reasons: none" in context_block
    assert "latest selected segment ids: []" in context_block
    assert "id=ctx_" in context_block
    assert "ref=context.txt" in context_block
    assert "chars=19" in context_block
    assert "tokens=" in context_block
    assert "selected=no" in context_block
    assert "score=unrouted" in context_block
    assert "SECRET_FILE_CONTENT" not in context_block
    assert str(tmp_path) not in context_block


def test_context_after_files_reports_skipped_reasons_safely(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("SAFE_CONTEXT", encoding="utf-8")
    outside = tmp_path.parent / "outside-context.txt"
    outside.write_text("OUTSIDE_SECRET", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", f"/files context.txt {outside}", "/context", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    context_block = rendered.split("SFE context", 1)[1]
    assert "loaded context segments: 1" in context_block
    assert "skipped context files: 1" in context_block
    assert "skipped reasons: outside_workspace: 1" in context_block
    assert "ref=context.txt" in context_block
    assert "SAFE_CONTEXT" not in context_block
    assert "OUTSIDE_SECRET" not in context_block
    assert "outside-context.txt" not in context_block
    assert str(outside) not in context_block
    assert str(tmp_path.resolve()) not in context_block


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
    assert "latest selected segment ids: ['ctx_" in context_block
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
                "/status",
                "/context",
                "/directory",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1].split("SFE context", 1)[0]
    context_block = rendered.split("SFE context", 1)[1]
    assert "Session reset. Workspace is preserved." in rendered
    assert app.workspace_root == tmp_path.resolve()
    assert app.context_files == []
    assert app.task == ""
    assert "loaded context files: 0" in status_block
    assert "skipped context files: 0" in status_block
    assert "loaded context segments: 0" in status_block
    assert "task present: False" in status_block
    assert "latest result present: no" in status_block
    assert "latest result kind: none" in status_block
    assert "latest provider calls made: 0" in status_block
    assert "loaded context segments: 0" in context_block
    assert "skipped context files: 0" in context_block
    assert "skipped reasons: none" in context_block
    assert "latest selected segment ids: []" in context_block
    assert "empty: no context loaded" in context_block
    assert "selected=yes" not in context_block
    assert "latest selected segment ids: ['ctx_" not in context_block
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
    assert "set one with /task <text>" in rendered
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
    assert "Error: discovery_not_run" in rendered
    assert "run /discover after /task before this command" in rendered
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
    assert "routing found no relevant context segments" in rendered
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
    diagnostics = rendered.split("SFE answer", 1)[0]
    assert "calling provider" in rendered
    assert "answer received" in rendered
    assert "SFE answer\nmock answer" in rendered
    assert "Preflight state" in diagnostics
    assert "Local routing" in diagnostics
    assert "Provider call" in diagnostics
    assert "selected segment ids: ctx_" in diagnostics
    assert "selected source refs: context.txt" in diagnostics
    assert "provider calls made: 1" in diagnostics
    assert "Safety state" in rendered
    assert "writes disabled" in rendered
    assert "shell disabled" in rendered
    assert "patch application disabled" in rendered
    assert "SECRET_FILE_CONTENT" not in diagnostics
    assert "Explain context" not in diagnostics
    assert str(tmp_path) not in diagnostics
    assert str(tmp_path.resolve()) not in rendered
    assert "ProxyBackend" not in rendered
    assert "backend switching" not in rendered


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
    assert "provider call failed; check provider configuration and retry" in rendered
    assert api_key not in rendered
    assert "Authorization" not in rendered
    assert "request body" not in rendered.lower()
    assert "provider payload" not in rendered.lower()


def test_ask_provider_not_configured_is_actionable(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("context", encoding="utf-8")
    executor = FakeExecutor(
        ExecutorResponse(
            answer=None,
            error_category="provider_not_configured",
            provider_calls_made=0,
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
    assert "reason: provider_not_configured" in rendered
    assert "needs a configured executor/provider" in rendered
    assert "provider calls made: 0" in rendered


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
    assert "set one with /task <text>" in rendered
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
    assert "Error: discovery_not_run" in rendered
    assert "run /discover after /task before this command" in rendered
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
    assert "routing found no relevant context segments" in rendered
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
    diagnostics = rendered.split("Patch proposal only, not applied", 1)[0]
    assert "calling provider" in rendered
    assert "Patch proposal only, not applied" in rendered
    assert "not applied" in rendered
    assert "no files were modified" in rendered
    assert "diff --git a/context.txt b/context.txt" in rendered
    assert "Preflight state" in diagnostics
    assert "Local routing" in diagnostics
    assert "Provider call" in diagnostics
    assert "selected segment ids: ctx_" in diagnostics
    assert "selected source refs: context.txt" in diagnostics
    assert "provider calls made: 1" in diagnostics
    assert "writes disabled" in rendered
    assert "shell disabled" in rendered
    assert "patch application disabled" in rendered
    assert "patch applied: no" in rendered
    assert "SECRET_FILE_CONTENT" not in diagnostics
    assert "Patch context" not in diagnostics
    assert str(tmp_path) not in diagnostics
    assert str(tmp_path.resolve()) not in rendered
    assert "request body" not in diagnostics.lower()
    assert "provider payload" not in diagnostics.lower()
    assert "Authorization" not in diagnostics
    assert "API_KEY" not in diagnostics
    assert "ProxyBackend" not in rendered
    assert "backend switching" not in rendered


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
    assert "provider call failed; check provider configuration and retry" in rendered
    assert "no files were modified" in rendered
    assert "patch application disabled" in rendered
    assert "patch applied: no" in rendered
    assert api_key not in rendered
    assert "Authorization" not in rendered
    assert "request body" not in rendered.lower()
    assert "provider payload" not in rendered.lower()


def test_patch_provider_not_configured_is_actionable(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("context", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=None,
            error_category="provider_not_configured",
            provider_calls_made=0,
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
    assert "reason: provider_not_configured" in rendered
    assert "needs a configured executor/provider" in rendered
    assert "provider calls made: 0" in rendered
    assert "no files were modified" in rendered


def test_patch_does_not_modify_files(tmp_path) -> None:
    source = tmp_path / "context.txt"
    original = "context before patch proposal"
    source.write_text(original, encoding="utf-8")
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
    assert source.read_text(encoding="utf-8") == original
    rendered = "\n".join(output)
    assert "Patch proposal only, not applied" in rendered
    assert "no files were modified" in rendered


def test_help_includes_apply_patch_command() -> None:
    rendered = render_help()

    assert "/apply-patch" in rendered
    assert "Apply latest pending patch proposal" in rendered


def test_apply_patch_without_pending_patch_reports_actionable_error(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/apply-patch", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "Error: no_pending_patch" in rendered
    assert "run /patch first" in rendered


def test_patch_stores_pending_patch_only_for_valid_diff(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_text_diff(),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/status", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert app.pending_patch is not None
    assert "pending patch stored: yes" in rendered
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "pending patch: yes" in status_block
    assert "pending patch files: 1" in status_block
    assert "pending patch hunks: 1" in status_block


def test_patch_non_diff_output_does_not_store_pending_patch(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer="No safe patch can be proposed.",
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/status", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert app.pending_patch is None
    assert "pending patch stored: no" in rendered
    assert "pending patch: no" in rendered


def test_patch_dangerous_diff_does_not_store_pending_patch(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_text_diff(".env", old="SECRET=old", new="SECRET=new"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/status", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert app.pending_patch is None
    assert "pending patch stored: no" in rendered
    assert "pending patch reason: unsafe_patch" in rendered


def test_apply_patch_success_modifies_existing_file_and_clears_pending_patch(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_text_diff(),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Patch old context",
                "/patch",
                "/apply-patch",
                "/status",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "new context\n"
    assert app.pending_patch is None
    assert "SFE apply-patch" in rendered
    assert "status: applied" in rendered
    assert "modified relative paths: context.txt" in rendered
    assert "file count: 1" in rendered
    assert "hunk count: 1" in rendered
    assert "lines added: 1" in rendered
    assert "lines removed: 1" in rendered
    assert "pending patch cleared: yes" in rendered
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "pending patch: no" in status_block


def test_apply_patch_preimage_mismatch_writes_nothing_and_keeps_pending_patch(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_text_diff(),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput([""]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )
    assert app._select_workspace() is True
    app._handle_files("context.txt")
    app._handle_command("/task Patch old context")
    app._handle_patch()
    source.write_text("changed context\n", encoding="utf-8")

    app._handle_apply_patch()

    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "changed context\n"
    assert app.pending_patch is not None
    assert "error category: patch_preimage_mismatch" in rendered
    assert "pending patch cleared: no" in rendered


def test_apply_patch_makes_zero_provider_calls(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_text_diff(),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Patch old context",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    assert len(executor.patch_calls) == 1
    assert len(executor.calls) == 0


def test_pending_patch_clear_lifecycle_commands(tmp_path) -> None:
    clearing_commands = [
        "/task New old context task",
        "/discover",
        "/ask",
        "/files other.txt",
        "/reset",
    ]
    for command in clearing_commands:
        source = tmp_path / command.strip("/").split()[0] / "context.txt"
        source.parent.mkdir()
        source.write_text("old context\n", encoding="utf-8")
        other = source.parent / "other.txt"
        other.write_text("other context\n", encoding="utf-8")
        executor = FakeExecutor(
            response=ExecutorResponse("mock answer", None, 1),
            patch_response=ExecutorResponse(valid_text_diff(), None, 1),
        )
        output: list[str] = []
        app = SfeTuiApp(
            input_provider=FakeInput([""]),
            output=output.append,
            cwd=source.parent,
            backend=DirectBackend(executor=executor),
        )
        assert app._select_workspace() is True
        app._handle_files("context.txt")
        app._handle_command("/task Patch old context")
        app._handle_patch()
        assert app.pending_patch is not None

        app._handle_command(command)

        assert app.pending_patch is None


def test_pending_patch_preserved_by_observation_commands(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(valid_text_diff(), None, 1)
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput([""]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )
    assert app._select_workspace() is True
    app._handle_files("context.txt")
    app._handle_command("/task Patch old context")
    app._handle_patch()

    for command in ["/dry-run", "/context", "/status", "/directory", "/pwd", "/help"]:
        app._handle_command(command)
        assert app.pending_patch is not None


def test_apply_patch_invalid_pending_state_clears_without_writing(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(valid_text_diff(), None, 1)
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput([""]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )
    assert app._select_workspace() is True
    app._handle_files("context.txt")
    app._handle_command("/task Patch old context")
    app._handle_patch()
    assert app.pending_patch is not None
    app.pending_patch = replace(app.pending_patch, text="not a diff")

    app._handle_apply_patch()

    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert app.pending_patch is None
    assert "error category: invalid_patch_proposal" in rendered
    assert "pending patch cleared: yes" in rendered


def test_status_and_context_show_safe_pending_patch_metadata(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context SECRET_FILE_CONTENT\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_text_diff(old="old context SECRET_FILE_CONTENT", new="new context"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Patch old context SECRET_TASK_TEXT",
                "/patch",
                "/status",
                "/context",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1].split("SFE context", 1)[0]
    context_block = rendered.split("SFE context", 1)[1]
    for block in (status_block, context_block):
        assert "pending patch: yes" in block
        assert "pending patch files: 1" in block
        assert "pending patch hunks: 1" in block
        assert "SECRET_FILE_CONTENT" not in block
        assert "SECRET_TASK_TEXT" not in block
        assert str(tmp_path.resolve()) not in block


def test_apply_diagnostics_omit_raw_sensitive_material(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context SECRET_FILE_CONTENT\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_text_diff(
                old="old context SECRET_FILE_CONTENT",
                new="new context SECRET_FILE_CONTENT",
            ),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Patch SECRET_TASK_TEXT old context",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    apply_block = "\n".join(output).split("SFE apply-patch", 1)[1]
    assert "status: applied" in apply_block
    assert "context.txt" in apply_block
    assert "SECRET_FILE_CONTENT" not in apply_block
    assert "SECRET_TASK_TEXT" not in apply_block
    assert str(tmp_path.resolve()) not in apply_block
    assert "Authorization" not in apply_block
    assert "API_KEY" not in apply_block
    assert "request body" not in apply_block.lower()
    assert "provider payload" not in apply_block.lower()
    assert "diff --git" not in apply_block


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


def test_tui_executor_factory_defaults_to_openai_when_sfe_provider_unset() -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={},
        provider_factories={"openai": lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert executor.provider_name == "openai"
    assert result.provider_name == "openai"
    assert result.answer == "provider answer"
    assert provider.calls[0]["system_instruction"] == READ_ONLY_SYSTEM_INSTRUCTION


def test_tui_executor_factory_selects_openai_from_sfe_provider() -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={"SFE_PROVIDER": "openai"},
        provider_factories={"openai": lambda: provider},
    )

    assert executor.provider_name == "openai"


def test_tui_executor_factory_selects_lemonade_from_sfe_provider() -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={
            "SFE_PROVIDER": "lemonade",
            "SFE_EXECUTOR_MODEL": "local-executor",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert executor.provider_name == "lemonade"
    assert result.provider_name == "lemonade"
    assert result.answer == "provider answer"
    assert provider.calls[0]["model"] == "local-executor"
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert provider.calls[0]["messages"][0]["content"] == READ_ONLY_SYSTEM_INSTRUCTION
    assert "system_instruction" not in provider.calls[0]


def test_tui_lemonade_executor_uses_lemonade_model_fallback() -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={
            "SFE_PROVIDER": "lemonade",
            "SFE_LEMONADE_MODEL": "lemonade-fallback-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert result.answer == "provider answer"
    assert provider.calls[0]["model"] == "lemonade-fallback-model"


def test_tui_lemonade_executor_prefers_specific_executor_model() -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={
            "SFE_PROVIDER": "lemonade",
            "SFE_LEMONADE_EXECUTOR_MODEL": "lemonade-executor-model",
            "SFE_LEMONADE_MODEL": "lemonade-shared-model",
            "SFE_EXECUTOR_MODEL": "generic-executor-model",
        },
        provider_factories={"lemonade": lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert result.answer == "provider answer"
    assert provider.calls[0]["model"] == "lemonade-executor-model"


@pytest.mark.parametrize(
    ("provider_error", "expected_category"),
    (
        (LemonadeProviderError("timeout"), "timeout"),
        (LemonadeProviderError("http_error"), "http_error"),
        (LemonadeProviderError("invalid_json"), "invalid_json"),
        (LemonadeProviderError("network_error"), "network_error"),
    ),
)
def test_tui_lemonade_executor_maps_safe_error_categories(
    provider_error: LemonadeProviderError,
    expected_category: str,
) -> None:
    provider = FakeProvider(error=provider_error)
    executor = create_tui_executor(
        environ={"SFE_PROVIDER": "lemonade"},
        provider_factories={"lemonade": lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert result.error_category == expected_category
    assert result.provider_calls_made == 1
    assert result.provider_name == "lemonade"


@pytest.mark.parametrize(
    ("raised_error", "expected_category"),
    (
        (TimeoutError("timed out with raw detail"), "timeout"),
        (urllib.error.URLError(TimeoutError("timed out with raw detail")), "timeout"),
        (urllib.error.URLError("connection refused with raw detail"), "network_error"),
        (
            urllib.error.HTTPError(
                "redacted",
                500,
                "server error",
                {},
                io.BytesIO(b"raw body should not be rendered"),
            ),
            "http_error",
        ),
    ),
)
def test_lemonade_provider_raises_safe_error_categories(
    monkeypatch,
    raised_error: Exception,
    expected_category: str,
) -> None:
    def fake_urlopen(*_: object, **__: object) -> object:
        raise raised_error

    monkeypatch.setattr("providers.lemonade.urllib.request.urlopen", fake_urlopen)
    provider = LemonadeProvider(base_url="http://local.invalid", timeout=1)

    with pytest.raises(LemonadeProviderError) as exc_info:
        provider.list_models()

    assert exc_info.value.error_category == expected_category
    assert str(exc_info.value) == expected_category
    assert "raw detail" not in str(exc_info.value)
    assert "raw body" not in str(exc_info.value)


def test_lemonade_provider_invalid_json_raises_safe_category(monkeypatch) -> None:
    def fake_urlopen(*_: object, **__: object) -> FakeHTTPResponse:
        return FakeHTTPResponse(b"not json")

    monkeypatch.setattr("providers.lemonade.urllib.request.urlopen", fake_urlopen)
    provider = LemonadeProvider(base_url="http://local.invalid", timeout=1)

    with pytest.raises(LemonadeProviderError) as exc_info:
        provider.list_models()

    assert exc_info.value.error_category == "invalid_json"
    assert str(exc_info.value) == "invalid_json"
    assert "not json" not in str(exc_info.value)


def test_lemonade_provider_uses_timeout_env(monkeypatch) -> None:
    monkeypatch.setenv("SFE_LEMONADE_TIMEOUT_SECONDS", "45")

    provider = LemonadeProvider(base_url="redacted")

    assert provider.timeout == 45


def test_tui_executor_factory_selects_openai_compatible_from_sfe_provider() -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={"SFE_PROVIDER": "openai-compatible"},
        provider_factories={"openai-compatible": lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert executor.provider_name == "openai-compatible"
    assert result.provider_name == "openai-compatible"
    assert provider.calls[0]["system_instruction"] == READ_ONLY_SYSTEM_INSTRUCTION


@pytest.mark.parametrize(
    ("provider_name", "model_env", "model_value"),
    (
        ("alibaba", "SFE_ALIBABA_EXECUTOR_MODEL", "qwen-test"),
        ("anthropic", "SFE_ANTHROPIC_EXECUTOR_MODEL", "claude-test"),
    ),
)
def test_tui_executor_factory_selects_other_direct_providers(
    provider_name: str,
    model_env: str,
    model_value: str,
) -> None:
    provider = FakeProvider()
    executor = create_tui_executor(
        environ={"SFE_PROVIDER": provider_name, model_env: model_value},
        provider_factories={provider_name: lambda: provider},
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert executor.provider_name == provider_name
    assert result.provider_name == provider_name
    assert provider.calls[0]["model"] == model_value


def test_tui_executor_factory_reports_invalid_sfe_provider_safely() -> None:
    executor = create_tui_executor(environ={"SFE_PROVIDER": "bad-provider"})

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert executor.provider_name == "invalid"
    assert result.error_category == "provider_configuration_error"
    assert result.provider_calls_made == 0


def test_tui_executor_factory_ignores_proxy_provider_legacy_variable() -> None:
    openai_provider = FakeProvider()
    lemonade_provider = FakeProvider()
    executor = create_tui_executor(
        environ={"SFE_PROXY_PROVIDER": "lemonade"},
        provider_factories={
            "openai": lambda: openai_provider,
            "lemonade": lambda: lemonade_provider,
        },
    )

    result = executor.execute(
        {"instructions": [], "task": None, "selected_context_segments": []}
    )

    assert executor.provider_name == "openai"
    assert result.provider_name == "openai"
    assert openai_provider.calls
    assert not lemonade_provider.calls


def test_tui_dry_run_makes_no_provider_call_with_sfe_provider(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context", encoding="utf-8")
    provider = FakeProvider()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Explain selected context",
                "/dry-run",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(
            executor=create_tui_executor(
                environ={"SFE_PROVIDER": "lemonade"},
                provider_factories={"lemonade": lambda: provider},
            )
        ),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "executor/provider called: no" in rendered
    assert "provider calls made: 0" in rendered
    assert not provider.calls


def test_tui_ask_uses_resolved_provider_without_proxy(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context", encoding="utf-8")
    provider = FakeProvider()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Explain selected context", "/ask", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(
            executor=create_tui_executor(
                environ={"SFE_PROVIDER": "lemonade"},
                provider_factories={"lemonade": lambda: provider},
            )
        ),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "provider: lemonade" in rendered
    assert "SFE answer\nprovider answer" in rendered
    assert provider.calls
    assert "ProxyBackend" not in rendered
    assert "/backend" not in rendered


def test_tui_ask_renders_safe_lemonade_failure_category(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text(
        "selected context PROMPT_CONTENT_SHOULD_NOT_RENDER",
        encoding="utf-8",
    )
    provider = FakeProvider(error=LemonadeProviderError("timeout"))
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Explain selected context SECRET_TASK_SHOULD_NOT_RENDER",
                "/ask",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(
            executor=create_tui_executor(
                environ={"SFE_PROVIDER": "lemonade"},
                provider_factories={"lemonade": lambda: provider},
            )
        ),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "provider: lemonade" in rendered
    assert "status: failed (timeout)" in rendered
    assert "reason: timeout" in rendered
    assert "PROMPT_CONTENT_SHOULD_NOT_RENDER" not in rendered
    assert "SECRET_TASK_SHOULD_NOT_RENDER" not in rendered
    assert "sk-SECRET" not in rendered
    assert "Authorization" not in rendered
    assert "http://" not in rendered


def test_tui_patch_uses_resolved_provider_without_proxy(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context", encoding="utf-8")
    provider = FakeProvider()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch selected context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(
            executor=create_tui_executor(
                environ={"SFE_PROVIDER": "lemonade"},
                provider_factories={"lemonade": lambda: provider},
            )
        ),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "provider: lemonade" in rendered
    assert "Patch proposal only, not applied" in rendered
    assert provider.calls[0]["messages"][0]["role"] == "system"
    assert provider.calls[0]["messages"][0]["content"] == PATCH_SYSTEM_INSTRUCTION
    assert "system_instruction" not in provider.calls[0]
    assert "ProxyBackend" not in rendered
    assert "/backend" not in rendered


def test_tui_patch_renders_safe_lemonade_failure_category(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text(
        "selected context PATCH_PROMPT_CONTENT_SHOULD_NOT_RENDER",
        encoding="utf-8",
    )
    provider = FakeProvider(error=LemonadeProviderError("http_error"))
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Patch selected context PATCH_SECRET_TASK_SHOULD_NOT_RENDER",
                "/patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(
            executor=create_tui_executor(
                environ={"SFE_PROVIDER": "lemonade"},
                provider_factories={"lemonade": lambda: provider},
            )
        ),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "provider: lemonade" in rendered
    assert "status: failed (http_error)" in rendered
    assert "reason: http_error" in rendered
    assert "PATCH_PROMPT_CONTENT_SHOULD_NOT_RENDER" not in rendered
    assert "PATCH_SECRET_TASK_SHOULD_NOT_RENDER" not in rendered
    assert "sk-SECRET" not in rendered
    assert "Authorization" not in rendered
    assert "http://" not in rendered


def test_tui_status_displays_executor_provider_safely(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/status", "/quit"]),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(
            executor=create_tui_executor(
                environ={"SFE_PROVIDER": "lemonade"},
                provider_factories={"lemonade": lambda: FakeProvider()},
            )
        ),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "executor provider: lemonade" in status_block
    assert "API_KEY" not in status_block
    assert "Authorization" not in status_block
    assert "http://" not in status_block


def test_tui_invalid_provider_renders_configuration_guidance(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("selected context", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Explain selected context", "/ask", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(
            executor=create_tui_executor(environ={"SFE_PROVIDER": "bad-provider"})
        ),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "reason: provider_configuration_error" in rendered
    assert "set SFE_PROVIDER to openai-compatible, openai, lemonade, alibaba, or anthropic" in rendered
    assert "bad-provider" not in rendered


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
    assert "Local routing preview" in rendered
    assert "Selected context" in rendered
    assert "Safety guarantees" in rendered
    assert "selected segment ids: ctx_" in rendered
    assert "selected source refs: context.txt" in rendered
    assert "None" not in rendered
    assert "{}" not in rendered
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

    assert "Preflight state" in rendered
    assert "Local routing preview" in rendered
    assert "Selected context" in rendered
    assert "Skipped/rejected context" in rendered
    assert "Safety guarantees" in rendered
    assert "backend: direct" in rendered
    assert "provider calls made: 0" in rendered
    assert "executor/provider called: no" in rendered
    assert "writes disabled" in rendered
    assert "shell disabled" in rendered
    assert "patch application disabled" in rendered
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

    assert "Local routing preview" in rendered
    assert f"selector mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
    assert "local preview only, not an LLM router result" in rendered
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
    assert "CodexCLI path are standby compatibility" in note
    assert "stress-test infrastructure" in note
    assert "The project should not keep reverse-engineering those payloads" in note
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
