"""Tests for the first-party SFE-aware TUI skeleton."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.error
from dataclasses import replace
from pathlib import Path

import pytest
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.lemonade import LemonadeProvider, LemonadeProviderError
from sfe.contracts import (
    ContextSegment,
    MAX_CONTEXT_FILE_BYTES,
    PRIVATE_KEY_MARKERS,
    ProtectedText,
    build_contract,
    load_context_file,
    resolve_context_path,
    resolve_workspace,
)
from sfe.discovery_router import DiscoveryRouterSelection
from sfe.execution_mode_router import (
    EXECUTION_MODE_CONSOLE_OUTPUT,
    EXECUTION_MODE_EXTERNAL_ACTION,
    EXECUTION_MODE_WORKSPACE_WRITE,
    ExecutionModeDecision,
)
from sfe.patch_json_repair import (
    PATCH_JSON_REPAIR_MAX_INPUT_CHARS,
    PatchJsonRepairResult,
)
from sfe_tui.app import SfeTuiApp
from sfe_tui.backends import (
    DirectBackend,
    MISSING_TASK,
    ProxyBackend,
    backend_by_name,
)
from sfe_tui.executors import (
    CONSOLE_SYSTEM_INSTRUCTION,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_PATCH_OUTPUT_TOKENS,
    ExecutorResponse,
    OpenAIReadOnlyExecutor,
    PATCH_SYSTEM_INSTRUCTION,
    READ_ONLY_SYSTEM_INSTRUCTION,
    create_tui_executor,
)
from sfe_tui.input import (
    SLASH_COMMANDS,
    SlashCommandCompleter,
    should_accept_autosuggestion_on_tab,
    slash_command_completion_available,
)
from sfe_tui.patch_review import (
    PATCH_REVIEW_SYSTEM_INSTRUCTION,
    DirectProviderPatchReviewer,
    PatchReviewDecision,
    _build_review_prompt,
)
from sfe.workspace_review import WorkspaceReviewDecision
from sfe_tui.renderer import (
    color_sfe_output,
    render_advanced_help,
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


def slash_command_completions(text: str) -> list[str]:
    completer = SlashCommandCompleter()
    document = Document(text=text, cursor_position=len(text))
    event = CompleteEvent(completion_requested=True)
    return [completion.text for completion in completer.get_completions(document, event)]


def test_slash_command_completer_matches_command_prefixes() -> None:
    assert slash_command_completions("/he") == ["/help", "/help-advanced"]
    assert slash_command_completions("/help-a") == ["/help-advanced"]
    assert slash_command_completions("/run-d") == ["/run-debug"]
    assert slash_command_completions("/run-r") == ["/run-report"]
    assert slash_command_completions("/worktree-d") == ["/worktree-diff"]
    assert slash_command_completions("/workspace-s") == ["/workspace-status"]


def test_slash_command_completer_prefers_hyphenated_run_debug() -> None:
    completions = slash_command_completions("/run")

    assert "/run" in completions
    assert "/run-debug" in completions
    assert "/run-report" in completions
    assert "/run_debug" not in completions
    assert "/run_debug" not in SLASH_COMMANDS


def test_slash_command_completer_ignores_arguments_and_non_commands() -> None:
    assert slash_command_completions("/task free text") == []
    assert slash_command_completions("help") == []


def test_tab_autosuggestion_acceptance_preserves_slash_completion_priority() -> None:
    assert slash_command_completion_available("/run-d")
    assert not should_accept_autosuggestion_on_tab(
        "/run-d",
        completion_active=False,
        suggestion_available=True,
    )


def test_tab_autosuggestion_acceptance_waits_for_completion_menu() -> None:
    assert not should_accept_autosuggestion_on_tab(
        "/run",
        completion_active=True,
        suggestion_available=True,
    )


def test_tab_autosuggestion_acceptance_works_for_non_command_text() -> None:
    assert should_accept_autosuggestion_on_tab(
        "/task free text",
        completion_active=False,
        suggestion_available=True,
    )
    assert should_accept_autosuggestion_on_tab(
        "free text",
        completion_active=False,
        suggestion_available=True,
    )


def test_tab_autosuggestion_acceptance_requires_visible_suggestion() -> None:
    assert not should_accept_autosuggestion_on_tab(
        "free text",
        completion_active=False,
        suggestion_available=False,
    )


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
            answer=replacement_proposal(),
            error_category=None,
            provider_calls_made=1,
        )
        self.calls: list[dict[str, object]] = []
        self.patch_calls: list[dict[str, object]] = []
        self.console_calls: list[dict[str, object]] = []

    def answer_console(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.console_calls.append(executor_payload)
        return self.response

    def execute(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.calls.append(executor_payload)
        return self.response

    def propose_patch(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.patch_calls.append(executor_payload)
        return self.patch_response


class RecordingActivityIndicator:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.running = False

    def start(self) -> None:
        self.running = True
        self.events.append("activity:start")

    def stop(self) -> None:
        self.events.append("activity:stop")
        self.running = False


class RecordingActivityFactory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.instances: list[RecordingActivityIndicator] = []

    def __call__(self) -> RecordingActivityIndicator:
        indicator = RecordingActivityIndicator(self.events)
        self.instances.append(indicator)
        return indicator


class EventRecordingExecutor(FakeExecutor):
    def __init__(
        self,
        events: list[str],
        response: ExecutorResponse | None = None,
    ) -> None:
        super().__init__(response=response)
        self.events = events

    def answer_console(self, executor_payload: dict[str, object]) -> ExecutorResponse:
        self.events.append("backend:start")
        result = super().answer_console(executor_payload)
        self.events.append("backend:complete")
        return result


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


class FakeExecutionModeRouter:
    provider_name = "fake-execution-mode-router"
    model = "fake-execution-mode-model"

    def __init__(self, execution_mode: str = EXECUTION_MODE_WORKSPACE_WRITE) -> None:
        self.execution_mode = execution_mode
        self.calls: list[dict[str, object]] = []

    def decide(self, *, task: str) -> ExecutionModeDecision:
        self.calls.append({"task": task})
        return ExecutionModeDecision(
            execution_mode=self.execution_mode,
            reason=f"fake selected {self.execution_mode}",
            confidence=0.88,
            provider_name=self.provider_name,
            model=self.model,
            provider_calls_made=1,
        )


class FakePatchJsonRepairer:
    provider_name = "fake-json-repairer"
    model = "fake-json-repair-model"

    def __init__(self, repaired_text: str | None) -> None:
        self.repaired_text = repaired_text
        self.calls: list[dict[str, object]] = []

    def repair(
        self,
        *,
        raw_response: str,
        parse_error: str,
    ) -> PatchJsonRepairResult:
        self.calls.append(
            {
                "raw_response": raw_response,
                "parse_error": parse_error,
            }
        )
        return PatchJsonRepairResult(
            self.repaired_text,
            error_category=None if self.repaired_text is not None else "failed",
            provider_name=self.provider_name,
            model=self.model,
        )


@pytest.fixture(autouse=True)
def fake_discovery_router(monkeypatch: pytest.MonkeyPatch) -> None:
    import sfe.discovery as discovery

    monkeypatch.setattr(
        discovery,
        "create_configured_discovery_router",
        lambda: FakeDiscoveryRouter(),
    )


class FakePatchReviewer:
    def __init__(
        self,
        decision: PatchReviewDecision | None = None,
    ) -> None:
        self.provider_name = "fake-router"
        self.model = "fake-router-model"
        self.decision = decision or PatchReviewDecision(
            decision="OK_APPLY",
            reason="patch matches the requested task",
            files_reviewed=("context.txt",),
            risk_level="low",
            provider_name=self.provider_name,
            model=self.model,
        )
        self.calls: list[dict[str, object]] = []

    def review(self, payload: dict[str, object]) -> PatchReviewDecision:
        self.calls.append(payload)
        return self.decision


class FakeWorkspaceReviewer:
    def __init__(
        self,
        decision: WorkspaceReviewDecision | None = None,
    ) -> None:
        self.provider_name = "fake-workspace-router"
        self.model = "fake-workspace-router-model"
        self.decision = decision or WorkspaceReviewDecision(
            decision="OK_PROMOTE",
            reason="worktree changes match the requested task",
            files_reviewed=("context.txt",),
            risk_level="low",
            provider_name=self.provider_name,
            model=self.model,
        )
        self.calls: list[dict[str, object]] = []

    def review(self, payload: dict[str, object]) -> WorkspaceReviewDecision:
        self.calls.append(payload)
        return self.decision


class DeltaAwareFakePatchReviewer:
    provider_name = "fake-router"
    model = "fake-router-model"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def review(self, payload: dict[str, object]) -> PatchReviewDecision:
        self.calls.append(payload)
        current_by_path = {
            str(item["path"]): str(item.get("content") or "")
            for item in payload.get("current_files", [])
            if isinstance(item, dict) and item.get("available")
        }
        unrelated_paths: list[str] = []
        for item in payload.get("proposed_full_replacements", []):
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "")
            proposed = str(item.get("content") or "")
            current = current_by_path.get(path, "")
            if current and not proposed.startswith(current):
                unrelated_paths.append(path)
        if unrelated_paths:
            return PatchReviewDecision(
                decision="KO_BLOCK",
                reason="effective delta replaces unrelated content",
                files_reviewed=tuple(unrelated_paths),
                risk_level="high",
                provider_name=self.provider_name,
                model=self.model,
            )
        return PatchReviewDecision(
            decision="OK_APPLY",
            reason="effective delta is a small task-aligned addition",
            files_reviewed=tuple(current_by_path),
            risk_level="low",
            provider_name=self.provider_name,
            model=self.model,
        )


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


def valid_create_diff(path: str = "composer.json", content: str = "{}") -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "index 0000000..1111111",
            "--- /dev/null",
            f"+++ b/{path}",
            "@@ -0,0 +1,1 @@",
            f"+{content}",
        ]
    )


def valid_implicit_create_diff(path: str = "README.md", content: str = "# Demo") -> str:
    return "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -0,0 +1,1 @@",
            f"+{content}",
        ]
    )


def valid_multi_create_diff(files: dict[str, str]) -> str:
    return "\n".join(valid_create_diff(path, content) for path, content in files.items())


def valid_multi_implicit_create_diff(files: dict[str, str]) -> str:
    return "\n".join(
        valid_implicit_create_diff(path, content) for path, content in files.items()
    )


def markdown_fenced_diff(
    path: str = "context.txt",
    *,
    old: str = "old context",
    new: str = "new context",
) -> str:
    return "\n".join(
        [
            "```diff",
            f"diff --git a/{path} b/{path}",
            f"--- a/{path}",
            f"+++ b/{path}",
            "@@ -1,1 +1,1 @@",
            f"-{old}",
            f"+{new}",
            "```",
        ]
    )


def replacement_proposal(
    path: str = "context.txt",
    *,
    old: str = "old context",
    new: str = "new context\n",
    content: str | None = None,
    diff_preview: str | None = None,
) -> str:
    replacement = content if content is not None else new
    preview_new = replacement.rstrip("\n")
    return json.dumps(
        {
            "edits": [
                {
                    "path": path,
                    "action": "replace_existing_file",
                    "content": replacement,
                }
            ],
            "diff_preview": diff_preview or valid_text_diff(path, old=old, new=preview_new),
        }
    )


def multi_replacement_proposal(files: dict[str, str]) -> str:
    return json.dumps(
        {
            "edits": [
                {
                    "path": path,
                    "action": "replace_existing_file",
                    "content": content,
                }
                for path, content in files.items()
            ],
            "diff_preview": "\n".join(
                valid_text_diff(path, old="old context", new=content.rstrip("\n"))
                for path, content in files.items()
            ),
        }
    )


def create_file_proposal(
    path: str = "README.md",
    *,
    content: str = "# Demo\n",
    diff_preview: str | None = None,
) -> str:
    preview_content = content.rstrip("\n")
    return json.dumps(
        {
            "edits": [
                {
                    "path": path,
                    "action": "create_file",
                    "content": content,
                }
            ],
            "diff_preview": diff_preview or valid_create_diff(path, preview_content),
        }
    )


def init_git_repo(path: Path) -> Path:
    path.mkdir()
    run_git(path, "init")
    run_git(path, "config", "user.email", "sfe@example.invalid")
    run_git(path, "config", "user.name", "SFE Test")
    (path / "context.txt").write_text("old context\n", encoding="utf-8")
    run_git(path, "add", "context.txt")
    run_git(path, "commit", "-m", "initial")
    run_git(path, "branch", "-M", "main")
    return path


def run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    return completed


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
    assert f"Workspace: {safe_workspace_label(tmp_path, tmp_path)}" in output
    assert str(tmp_path.resolve()) not in input_provider.prompts[0]
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
    assert directory_outputs[-1] == f"Workspace: {safe_workspace_label(tmp_path, tmp_path)}"
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
    assert f"Workspace: {safe_workspace_label(tmp_path, tmp_path)}" in rendered
    assert "/pwd" not in render_help()


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


def test_workspace_label_uses_full_path_with_home_shortening(
    tmp_path,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    outside = tmp_path.parent / "outside-workspace-label"
    outside.mkdir(exist_ok=True)

    assert safe_workspace_label(tmp_path, tmp_path) == tmp_path.resolve().as_posix()
    assert safe_workspace_label(child, tmp_path) == child.resolve().as_posix()
    assert safe_workspace_label(outside, tmp_path) == outside.resolve().as_posix()
    assert str(child.resolve()) in render_workspace_selected(child, tmp_path)


def test_tui_color_mode_wraps_prompts_and_output(tmp_path) -> None:
    input_provider = FakeInput(["", "/quit"])
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=input_provider,
        output=output.append,
        cwd=tmp_path,
        color_enabled=True,
    )

    assert app.run() == 0
    assert input_provider.prompts[0] == "Workspace [current]: "
    assert input_provider.prompts[1] == "sfe> "
    assert "\033[" not in "".join(input_provider.prompts)
    assert output[0] == color_sfe_output(
        render_workspace_selected(tmp_path, tmp_path),
        enabled=True,
    )


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
    loaded = load_context_file(PROJECT_ROOT, "sfe/contracts.py")

    assert loaded.loaded is True
    assert loaded.reason is None
    assert loaded.warning_reason == "secret_marker_literal_in_source"
    assert loaded.source_ref == "sfe/contracts.py"


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
    assert "automatic writes disabled" in dry_run_block
    assert "shell disabled" in dry_run_block
    assert "patch application available through explicit /apply-patch" in dry_run_block
    assert "SECRET_FILE_CONTENT" not in dry_run_block
    assert str(tmp_path.resolve()) not in dry_run_block


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

    assert "/dry-run" in render_advanced_help()
    assert "/run" in render_help()
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
    assert f"workspace: {safe_workspace_label(tmp_path, tmp_path)}" in status_block
    assert "latest result present: no" in status_block
    assert "latest result kind: none" in status_block
    assert "latest provider calls made: 0" in status_block
    assert "SECRET_FILE_CONTENT" not in rendered
    assert "Explain the context" not in rendered


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
    assert f"workspace: {safe_workspace_label(tmp_path, tmp_path)}" in status_block
    assert "loaded context files: 0" in status_block
    assert "skipped context files: 0" in status_block
    assert "loaded context segments: 0" in status_block
    assert "task present: False" in status_block
    assert "latest result present: no" in status_block
    assert "latest result kind: none" in status_block
    assert "latest provider calls made: 0" in status_block
    assert "writes: routed /run workspace_write or explicit /apply-patch only" in status_block
    assert "shell enabled: no" in status_block
    assert "patch application: routed /run workspace_write or explicit /apply-patch" in status_block
    assert "/backend" not in status_block
    assert "ProxyBackend" not in status_block


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
    assert "writes: routed /run workspace_write or explicit /apply-patch only" in status_block
    assert "shell enabled: no" in status_block
    assert "patch application: routed /run workspace_write or explicit /apply-patch" in status_block


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
    assert "writes: routed /run workspace_write or explicit /apply-patch only" in status_block
    assert "shell enabled: no" in status_block
    assert "patch application: routed /run workspace_write or explicit /apply-patch" in status_block


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
    assert "writes: routed /run workspace_write or explicit /apply-patch only" in rendered
    assert "shell enabled: no" in rendered
    assert "patch application: routed /run workspace_write or explicit /apply-patch" in rendered
    assert "ProxyBackend" not in rendered
    assert "/backend" not in rendered


def test_help_does_not_advertise_backend_switching() -> None:
    rendered = render_help()
    advanced = render_advanced_help()
    help_lines = rendered.splitlines()

    assert "/help-advanced" in rendered
    assert "/help advanced" not in rendered
    assert "/directory" in rendered
    assert "/pwd" not in rendered
    assert "/status" in rendered
    assert "/context" in rendered
    assert "/run" in rendered
    assert "/run-debug" not in rendered
    assert "/run-report" in rendered
    assert "/run_debug" not in rendered
    assert "Resolve the task and show concise output" in rendered
    assert "Show diagnostics for the previous run without re-running" in rendered
    assert not any(line.strip().startswith("/discover") for line in help_lines)
    assert not any(line.strip().startswith("/dry-run") for line in help_lines)
    assert not any(line.strip().startswith("/patch") for line in help_lines)
    assert not any(line.strip().startswith("/apply-patch") for line in help_lines)
    assert not any(line.strip().startswith("/isolate") for line in help_lines)
    assert not any(line.strip().startswith("/worktree-diff") for line in help_lines)
    assert not any(line.strip().startswith("/review-worktree") for line in help_lines)
    assert not any(line.strip().startswith("/auto-patch") for line in help_lines)
    assert not any(line.strip().startswith("/auto-worktree") for line in help_lines)
    assert not any(line.strip().startswith("/files") for line in help_lines)
    assert "/ask" in rendered
    assert "/reset" in rendered
    assert "files or directories" not in rendered
    assert "Add context" not in rendered
    assert "ProxyBackend" not in rendered
    assert "Clear task, context, discovery, and routing; preserve workspace" in rendered
    assert "/backend" not in rendered
    assert rendered.index("/directory") < rendered.index("/status")
    assert rendered.index("/task <text>") < rendered.index("/run")
    assert rendered.index("/run") < rendered.index("/context")
    assert rendered.index("/context") < rendered.index("/ask")

    assert "SFE TUI advanced/debug commands:" in advanced
    assert "/run-debug" in advanced
    assert "/run-report" in advanced
    assert "/run_debug" not in advanced
    assert "Run the task and show full diagnostics" in advanced
    assert "Show diagnostics for the previous run without re-running" in advanced
    assert "/discover" in advanced
    assert "/dry-run" in advanced
    assert "/patch" in advanced
    assert "/apply-patch" in advanced
    assert "/isolate" in advanced
    assert "/worktree-diff" in advanced
    assert "/review-worktree" in advanced
    assert "/cleanup-worktree" in advanced
    assert "/gc-worktrees" in advanced
    assert "Legacy: run discover, patch, and router-reviewed apply" in advanced
    assert "Legacy: isolate, patch, apply, diff, and router-review" in advanced
    assert "/files <paths...>  Replace context manually for debug/design" in advanced


def test_help_advanced_command_renders_debug_help(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/help-advanced", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE TUI advanced/debug commands:" in rendered
    assert "/discover" in rendered
    assert "/auto-worktree" in rendered


def test_help_advanced_argument_remains_discreet_alias(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/help advanced", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE TUI advanced/debug commands:" in rendered
    assert "/discover" in rendered


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
    assert str(tmp_path.resolve()) not in dry_run_block


def test_discover_with_no_candidates_allows_dry_run_and_patch_provider_call(
    tmp_path,
) -> None:
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=create_file_proposal("README.md"),
            error_category=None,
            provider_calls_made=1,
        )
    )
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
    assert rendered.count("Error: no_context_loaded") == 1
    assert "calling provider" in rendered
    assert "pending patch created files: 1" in rendered
    assert "diff --git a/README.md b/README.md" in rendered
    assert (
        "note: empty workspace is valid in DEV patch mode; no existing context to inspect"
        in rendered
    )
    assert executor.calls == []
    assert len(executor.patch_calls) == 1
    assert executor.patch_calls[0]["selected_context_segments"] == []
    assert not (tmp_path / "README.md").exists()


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
        discovery_router=FakeDiscoveryRouter(("safe.md", "data.txt")),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    discovery_block = rendered.split("SFE discovery", 1)[1]
    assert "top candidate source refs: safe.md, data.txt" in discovery_block
    assert ".env" not in discovery_block
    assert "hidden.md" not in discovery_block
    assert "app.log" not in discovery_block
    assert "cache.md" not in discovery_block
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
    assert f"Workspace: {safe_workspace_label(tmp_path, tmp_path)}" in rendered
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
    diagnostics = rendered.split("building contract", 1)[1].split("SFE answer", 1)[0]
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
    assert "automatic writes disabled" in rendered
    assert "shell disabled" in rendered
    assert "patch application available through explicit /apply-patch" in rendered
    assert "SECRET_FILE_CONTENT" not in diagnostics
    assert "Explain context" not in diagnostics
    assert str(tmp_path) not in diagnostics
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
    diagnostics = rendered.split("building contract", 1)[1].split(
        "Patch proposal only, not applied",
        1,
    )[0]
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
    assert "automatic writes disabled" in rendered
    assert "shell disabled" in rendered
    assert "patch application available through explicit /apply-patch" in rendered
    assert "patch applied: no" in rendered
    assert "SECRET_FILE_CONTENT" not in diagnostics
    assert "Patch context" not in diagnostics
    assert str(tmp_path) not in diagnostics
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
    assert "patch application available through explicit /apply-patch" in rendered
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
    rendered = render_advanced_help()

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


def test_patch_stores_pending_file_replacement_proposal(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal(),
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
    assert app.pending_patch.proposal.edits[0].content == "new context\n"
    assert "pending patch stored: yes" in rendered
    patch_block = rendered.split("SFE patch", 1)[1].split("SFE TUI status", 1)[0]
    assert "diff --git a/context.txt b/context.txt" in patch_block
    assert '"edits"' not in patch_block
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "pending patch: yes" in status_block
    assert "pending patch files: 1" in status_block
    assert "pending patch hunks: 1" in status_block


def test_patch_stores_pending_multi_file_json_without_repair(tmp_path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old context\n", encoding="utf-8")
    second.write_text("old context\n", encoding="utf-8")
    repairer = FakePatchJsonRepairer(replacement_proposal())
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=multi_replacement_proposal(
                {
                    "first.txt": "new first\n",
                    "second.txt": "new second\n",
                }
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
                "/files first.txt second.txt",
                "/task Patch old context in both files",
                "/patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_json_repairer=repairer,
    )

    assert app.run() == 0

    rendered = "\n".join(output)
    assert app.pending_patch is not None
    assert repairer.calls == []
    assert "pending patch stored: yes" in rendered
    assert "pending patch files: 2" in rendered
    assert "pending patch repair attempted: no" in rendered
    assert "pending patch repair result: not_needed" in rendered


def test_patch_repairs_invalid_structured_json_once_and_stores_pending_patch(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    repaired = replacement_proposal(content="new context\n")
    repairer = FakePatchJsonRepairer(repaired)
    raw = 'Here is the JSON:\n{"edits":[{"path":"context.txt","action":"replace_existing_file","content":"new context\n"}]}\nThanks'
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw,
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_json_repairer=repairer,
    )

    assert app.run() == 0

    rendered = "\n".join(output)
    assert app.pending_patch is not None
    assert len(repairer.calls) == 1
    assert repairer.calls[0]["parse_error"] == "invalid_json"
    assert app.pending_patch.text == repaired
    assert "pending patch stored: yes" in rendered
    assert "pending patch repair attempted: yes" in rendered
    assert "pending patch repair result: success" in rendered
    assert "pending patch detail: invalid_json_repaired" in rendered


def test_apply_patch_after_json_repair_still_uses_router_review(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    repairer = FakePatchJsonRepairer(replacement_proposal(content="new context\n"))
    reviewer = FakePatchReviewer()
    raw = '{"edits":[{"path":"context.txt","action":"replace_existing_file","content":"new context\n"}]}'
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw,
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
        patch_json_repairer=repairer,
        patch_reviewer=reviewer,
    )

    assert app.run() == 0

    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "new context\n"
    assert len(repairer.calls) == 1
    assert len(reviewer.calls) == 1
    assert reviewer.calls[0]["patch_summary"]["paths"] == ["context.txt"]
    assert "pending patch repair result: success" in rendered
    assert "router decision: OK_APPLY" in rendered


def test_patch_failed_json_repair_does_not_store_pending_patch(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    repairer = FakePatchJsonRepairer(None)
    raw = '{"edits":[{"path":"context.txt","action":"replace_existing_file","content":"new context\n"}]}'
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw,
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_json_repairer=repairer,
    )

    assert app.run() == 0

    rendered = "\n".join(output)
    assert app.pending_patch is None
    assert len(repairer.calls) == 1
    assert "pending patch stored: no" in rendered
    assert "pending patch reason: unsupported_pending_patch_format" in rendered
    assert "pending patch repair attempted: yes" in rendered
    assert "pending patch repair result: failed" in rendered
    assert "pending patch detail: invalid_json_repair_failed" in rendered


def test_patch_repair_invalid_schema_does_not_store_pending_patch(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    repairer = FakePatchJsonRepairer(
        json.dumps(
            {
                "edits": [
                    {
                        "path": "context.txt",
                        "action": "delete_file",
                        "content": "new context\n",
                    }
                ]
            }
        )
    )
    raw = '{"edits":[{"path":"context.txt","action":"replace_existing_file","content":"new context\n"}]}'
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw,
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_json_repairer=repairer,
    )

    assert app.run() == 0

    rendered = "\n".join(output)
    assert app.pending_patch is None
    assert len(repairer.calls) == 1
    assert "pending patch stored: no" in rendered
    assert "pending patch detail: invalid_json_repair_failed" in rendered


def test_patch_skips_json_repair_for_too_large_response(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    repairer = FakePatchJsonRepairer(replacement_proposal())
    raw = (
        '{"edits":[{"path":"context.txt","action":"replace_existing_file",'
        '"content":"'
        + ("x" * PATCH_JSON_REPAIR_MAX_INPUT_CHARS)
    )
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw,
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_json_repairer=repairer,
    )

    assert app.run() == 0

    rendered = "\n".join(output)
    assert app.pending_patch is None
    assert repairer.calls == []
    assert "pending patch stored: no" in rendered
    assert "pending patch repair attempted: no" in rendered
    assert "pending patch repair result: skipped" in rendered
    assert "pending patch detail: invalid_json_too_large_for_repair" in rendered


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


def test_patch_legacy_diff_only_output_is_unsupported_pending_format(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=markdown_fenced_diff(),
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
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert app.pending_patch is None
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert "pending patch stored: no" in rendered
    assert "pending patch reason: unsupported_pending_patch_format" in rendered


def test_patch_stores_pending_unified_diff_file_creation(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Symfony skeleton composer json", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_create_diff("composer.json", '{"type":"project"}'),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Create Symfony skeleton composer json",
                "/discover",
                "/patch",
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
    assert app.pending_patch is not None
    assert not (tmp_path / "composer.json").exists()
    assert "pending patch stored: yes" in rendered
    assert "pending patch created files: 1" in rendered
    assert "diff --git a/composer.json b/composer.json" in rendered


def test_tui_pipeline_applies_provider_mocked_readme_creation_diff(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Create README documentation", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_create_diff("README.md", "# Demo"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    reviewer = FakePatchReviewer()
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Create README documentation",
                "/discover",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Demo\n"
    assert app.pending_patch is None
    assert "pending patch stored: yes" in rendered
    assert "pending patch reason: unsupported_pending_patch_format" not in rendered
    assert reviewer.calls[0]["patch_summary"]["created_paths"] == ["README.md"]
    assert "created relative paths: README.md" in rendered


def test_tui_pipeline_applies_provider_mocked_multiple_file_creation_diff(
    tmp_path,
) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text(
        "Create Symfony composer public index controller",
        encoding="utf-8",
    )
    files = {
        "composer.json": '{"type":"project"}',
        "public/index.php": "<?php echo 'home';",
        "src/Controller/HomeController.php": "<?php final class HomeController {}",
    }
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_multi_create_diff(files),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    reviewer = FakePatchReviewer()
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Create Symfony composer public index controller",
                "/discover",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    for path, content in files.items():
        assert (tmp_path / path).read_text(encoding="utf-8") == f"{content}\n"
    assert (tmp_path / "public").is_dir()
    assert (tmp_path / "src" / "Controller").is_dir()
    assert app.pending_patch is None
    assert "pending patch stored: yes" in rendered
    assert "pending patch created files: 3" in rendered
    assert reviewer.calls[0]["patch_summary"]["created_paths"] == list(files)
    assert "created relative paths: composer.json, public/index.php, src/Controller/HomeController.php" in rendered


def test_tui_pipeline_reclassifies_provider_mocked_implicit_creation_diff(
    tmp_path,
) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text(
        "Create Symfony composer public index controller",
        encoding="utf-8",
    )
    files = {
        "composer.json": '{"type":"project"}',
        "public/index.php": "<?php echo 'home';",
        "src/Controller/HomeController.php": "<?php final class HomeController {}",
    }
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_multi_implicit_create_diff(files),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    reviewer = FakePatchReviewer()
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Create Symfony composer public index controller",
                "/discover",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    for path, content in files.items():
        assert (tmp_path / path).read_text(encoding="utf-8") == f"{content}\n"
    assert app.pending_patch is None
    assert "pending patch stored: yes" in rendered
    assert "pending patch created files: 3" in rendered
    assert "modified relative paths: none" in rendered
    assert "created relative paths: composer.json, public/index.php, src/Controller/HomeController.php" in rendered
    assert reviewer.calls[0]["patch_summary"]["created_paths"] == list(files)
    assert reviewer.calls[0]["patch_summary"]["modified_paths"] == []
    assert reviewer.calls[0]["current_files"] == [
        {
            "path": path,
            "available": True,
            "content": "",
            "state": "new_file",
        }
        for path in files
    ]
    assert reviewer.calls[0]["proposed_full_replacements"] == [
        {
            "path": path,
            "action": "create_file",
            "content": f"{content}\n",
        }
        for path, content in files.items()
    ]


def test_tui_pipeline_still_applies_provider_mocked_existing_file_diff(
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
    reviewer = FakePatchReviewer()
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "new context\n"
    assert "pending patch stored: yes" in rendered
    assert "pending patch created files: 0" in rendered
    assert "modified relative paths: context.txt" in rendered
    assert "created relative paths: none" in rendered
    assert reviewer.calls[0]["patch_summary"]["modified_paths"] == ["context.txt"]
    assert reviewer.calls[0]["patch_summary"]["created_paths"] == []


def test_apply_patch_creates_file_from_core_validated_unified_diff(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Symfony skeleton composer json", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_create_diff("composer.json", '{"type":"project"}'),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    reviewer = FakePatchReviewer()
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Create Symfony skeleton composer json",
                "/discover",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert (tmp_path / "composer.json").read_text(encoding="utf-8") == '{"type":"project"}\n'
    assert app.pending_patch is None
    assert "status: applied" in rendered
    assert "created relative paths: composer.json" in rendered
    assert reviewer.calls[0]["patch_summary"]["created_paths"] == ["composer.json"]
    assert reviewer.calls[0]["proposed_full_replacements"] == [
        {
            "path": "composer.json",
            "action": "create_file",
            "content": '{"type":"project"}\n',
        }
    ]


def test_patch_rejects_dangerous_unified_diff_creation_from_core(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Symfony skeleton vendor file", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=valid_create_diff("vendor/autoload.php", "<?php"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Create Symfony skeleton vendor file",
                "/discover",
                "/patch",
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
    assert app.pending_patch is None
    assert not (tmp_path / "vendor" / "autoload.php").exists()
    assert "pending patch stored: no" in rendered
    assert "pending patch reason: mechanical_safety_guard" in rendered
    assert "pending patch: no" in rendered


def test_patch_hidden_or_secret_like_path_stores_pending_patch(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal(".env", old="SECRET=old", new="SECRET=new\n"),
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
    assert "pending patch: yes" in rendered


def test_patch_json_create_file_stores_pending_with_created_metadata(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Create README", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=create_file_proposal("README.md", content="# Demo\n"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Create README", "/discover", "/patch", "/status", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert app.pending_patch is not None
    assert app.pending_patch.summary.created_paths == ("README.md",)
    assert app.pending_patch.summary.modified_paths == ()
    assert not (tmp_path / "README.md").exists()
    assert "pending patch stored: yes" in rendered
    assert "pending patch created files: 1" in rendered


def test_apply_patch_json_create_file_creates_file_after_router_review(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Create README", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=create_file_proposal("README.md", content="# Demo\n"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    reviewer = FakePatchReviewer()
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Create README", "/discover", "/patch", "/apply-patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "# Demo\n"
    assert "created relative paths: README.md" in rendered
    assert reviewer.calls[0]["current_files"] == [
        {
            "path": "README.md",
            "available": True,
            "content": "",
            "state": "new_file",
        }
    ]
    assert reviewer.calls[0]["proposed_full_replacements"] == [
        {
            "path": "README.md",
            "action": "create_file",
            "content": "# Demo\n",
        }
    ]


def test_apply_patch_json_create_file_existing_target_is_refused(tmp_path) -> None:
    source = tmp_path / "README.md"
    source.write_text("existing\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=create_file_proposal("README.md", content="# Demo\n"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files README.md", "/task Create README", "/patch", "/apply-patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "existing\n"
    assert "error category: physical_write_failure" in rendered
    assert "reason category: target_already_exists" in rendered


def test_apply_patch_json_create_file_dangerous_path_is_refused(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Create outside", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=create_file_proposal("../outside.md", content="# Demo\n"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Create outside", "/discover", "/patch", "/apply-patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "pending patch stored: yes" in rendered
    assert "failure kind: mechanical_safety_guard" in rendered
    assert "reason category: path_outside_workspace" in rendered


def test_apply_patch_json_create_file_generated_directories_are_refused(tmp_path) -> None:
    for path in (
        ".git/hooks/post-checkout",
        "vendor/autoload.php",
        "var/cache.php",
        "cache/item.txt",
        "node_modules/pkg/index.js",
    ):
        source = tmp_path / path.replace("/", "-") / "PROJECT_REQUEST.md"
        source.parent.mkdir()
        source.write_text("Create generated path", encoding="utf-8")
        executor = FakeExecutor(
            patch_response=ExecutorResponse(
                answer=create_file_proposal(path, content="nope\n"),
                error_category=None,
                provider_calls_made=1,
            )
        )
        output: list[str] = []
        app = SfeTuiApp(
            input_provider=FakeInput(
                ["", "/task Create generated path", "/discover", "/patch", "/apply-patch", "/quit"]
            ),
            output=output.append,
            cwd=source.parent,
            backend=DirectBackend(executor=executor),
            patch_reviewer=FakePatchReviewer(),
        )

        assert app.run() == 0
        rendered = "\n".join(output)
        assert "failure kind: mechanical_safety_guard" in rendered
        assert "reason category: excluded_directory" in rendered


def test_apply_patch_success_modifies_existing_file_and_clears_pending_patch(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal(),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    reviewer = FakePatchReviewer()
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "new context\n"
    assert app.pending_patch is None
    assert "SFE apply-patch" in rendered
    assert "status: applied" in rendered
    assert "router decision: OK_APPLY" in rendered
    assert "router provider: fake-router" in rendered
    assert "router reason: patch matches the requested task" in rendered
    assert "modified relative paths: context.txt" in rendered
    assert "file count: 1" in rendered
    assert "hunk count: 1" in rendered
    assert "lines added: 1" in rendered
    assert "lines removed: 1" in rendered
    assert "pending patch cleared: yes" in rendered
    assert reviewer.calls[0]["proposal_format"] == "file_replacements"
    guidance = reviewer.calls[0]["review_guidance"]
    assert guidance["full_file_replacements_are_expected"] is True
    assert guidance["do_not_reject_solely_because_full_file_replacement"] is True
    assert guidance["judge_effective_delta_between_current_and_proposed_content"] is True
    assert reviewer.calls[0]["proposed_full_replacements"] == [
        {
            "path": "context.txt",
            "action": "replace_existing_file",
            "content": "new context\n",
        }
    ]
    assert "pending_patch" not in reviewer.calls[0]
    status_block = rendered.split("SFE TUI status", 1)[1]
    assert "pending patch: no" in status_block


def test_patch_preview_is_computed_from_replacement_not_provider_preview(
    tmp_path,
) -> None:
    source = tmp_path / "README.rst"
    original = "| |sponsor| |bluesky-nedbat| |mastodon-nedbat|\n\nOld docs\n"
    replacement = "|sponsor| |bluesky-nedbat| |mastodon-nedbat|\n\nOld docs\n\n>>> greet(\"Ada\")\n'Hello, Ada!'\n"
    source.write_text(original, encoding="utf-8")
    provider_preview = "\n".join(
        [
            "diff --git a/README.rst b/README.rst",
            "--- a/README.rst",
            "+++ b/README.rst",
            "@@ -3,1 +3,4 @@",
            " Old docs",
            "+",
            "+>>> greet(\"Ada\")",
            "+'Hello, Ada!'",
        ]
    )
    proposal = json.dumps(
        {
            "edits": [
                {
                    "path": "README.rst",
                    "action": "replace_existing_file",
                    "content": replacement,
                }
            ],
            "diff_preview": provider_preview,
        }
    )

    class DiffAwareReviewer:
        provider_name = "diff-aware-router"
        model = "diff-aware-model"

        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def review(self, payload: dict[str, object]) -> PatchReviewDecision:
            self.calls.append(payload)
            diff = str(payload.get("diff_preview") or "")
            if "-| |sponsor| |bluesky-nedbat| |mastodon-nedbat|" in diff:
                return PatchReviewDecision(
                    decision="KO_BLOCK",
                    reason="computed effective diff includes unrelated README badge edit",
                    files_reviewed=("README.rst",),
                    risk_level="medium",
                    provider_name=self.provider_name,
                    model=self.model,
                )
            return PatchReviewDecision(
                decision="OK_APPLY",
                reason="no unrelated computed diff found",
                files_reviewed=("README.rst",),
                risk_level="low",
                provider_name=self.provider_name,
                model=self.model,
            )

    reviewer = DiffAwareReviewer()
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=proposal,
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files README.rst",
                "/task Update README greeting docs",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "-| |sponsor| |bluesky-nedbat| |mastodon-nedbat|" in rendered
    assert "+|sponsor| |bluesky-nedbat| |mastodon-nedbat|" in rendered
    assert reviewer.calls
    reviewed_diff = str(reviewer.calls[0]["diff_preview"])
    assert "-| |sponsor| |bluesky-nedbat| |mastodon-nedbat|" in reviewed_diff
    assert "+|sponsor| |bluesky-nedbat| |mastodon-nedbat|" in reviewed_diff
    assert reviewed_diff != provider_preview
    assert "router decision: KO_BLOCK" in rendered
    assert "computed effective diff includes unrelated README badge edit" in rendered
    assert source.read_text(encoding="utf-8") == original


def test_isolate_on_non_git_workspace_reports_unsupported(tmp_path) -> None:
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/isolate", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE isolate" in rendered
    assert "status: failed" in rendered
    assert "error category: unsupported_workspace" in rendered
    assert "reason: not_inside_git_repository" in rendered
    assert app.workspace_session is None


def test_isolate_on_clean_git_repo_creates_worktree_and_switches_active_workspace(
    tmp_path,
) -> None:
    repo = init_git_repo(tmp_path / "repo")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/isolate", "/workspace-status", "/quit"]),
        output=output.append,
        cwd=repo,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert app.workspace_session is not None
    session = app.workspace_session
    assert app.workspace_root == session.worktree_path
    assert session.worktree_path.exists()
    assert session.worktree_branch.startswith("sfe/worktree/")
    assert "SFE isolate" in rendered
    assert "status: created" in rendered
    assert "SFE workspace-status" in rendered
    assert "mode: isolated" in rendered
    assert "status available: yes" in rendered

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_patch_apply_after_isolate_writes_only_to_worktree(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal(),
            error_category=None,
            provider_calls_made=1,
        )
    )
    reviewer = FakePatchReviewer()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/isolate",
                "/files context.txt",
                "/task Patch old context",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    assert (session.worktree_path / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert run_git(repo, "status", "--porcelain").stdout.strip() == ""
    rendered = "\n".join(output)
    assert "router decision: OK_APPLY" in rendered

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_tui_run_starts_activity_indicator_before_backend_completion(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[str] = []
    activity_factory = RecordingActivityFactory(events)
    executor = EventRecordingExecutor(
        events,
        response=ExecutorResponse(
            answer="done",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        ),
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Answer directly", "/run", "/quit"]),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
        activity_indicator_factory=activity_factory,
    )

    assert app.run() == 0
    assert events.index("activity:start") < events.index("backend:complete")


def test_tui_run_stops_activity_indicator_after_success(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[str] = []
    activity_factory = RecordingActivityFactory(events)
    executor = EventRecordingExecutor(
        events,
        response=ExecutorResponse(
            answer="done",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        ),
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Answer directly", "/run", "/quit"]),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
        activity_indicator_factory=activity_factory,
    )

    assert app.run() == 0
    assert events.index("backend:complete") < events.index("activity:stop")
    assert activity_factory.instances[0].running is False
    assert output[-1] == "done"


def test_tui_run_stops_activity_indicator_after_backend_failure(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[str] = []
    activity_factory = RecordingActivityFactory(events)
    executor = EventRecordingExecutor(
        events,
        response=ExecutorResponse(
            answer=None,
            error_category="provider_failed",
            provider_calls_made=1,
            provider_name="fake-executor",
        ),
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Answer directly", "/run", "/quit"]),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
        activity_indicator_factory=activity_factory,
    )

    assert app.run() == 0
    assert events.index("backend:complete") < events.index("activity:stop")
    assert activity_factory.instances[0].running is False
    assert "status: failed" in output[-1]
    assert "issue reason: provider_failed" in output[-1]


def test_tui_run_stops_activity_indicator_after_backend_exception(tmp_path) -> None:
    class RaisingExecutor(FakeExecutor):
        def answer_console(
            self,
            executor_payload: dict[str, object],
        ) -> ExecutorResponse:
            del executor_payload
            raise RuntimeError("provider exploded")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    events: list[str] = []
    activity_factory = RecordingActivityFactory(events)
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Answer directly", "/run", "/quit"]),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=RaisingExecutor()),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
        activity_indicator_factory=activity_factory,
    )

    with pytest.raises(RuntimeError, match="provider exploded"):
        app.run()
    assert events == ["activity:start", "activity:stop"]
    assert activity_factory.instances[0].running is False


def test_tui_run_noninteractive_default_does_not_render_activity_output(
    tmp_path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor(
        response=ExecutorResponse(
            answer="Symfony is a PHP framework.",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Connais le Framework PHP intitulé Symfony ?", "/run", "/quit"]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE is working" not in rendered
    assert output[-1] == "Symfony is a PHP framework."


def test_tui_run_console_output_renders_only_answer(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor(
        response=ExecutorResponse(
            answer="Symfony is a PHP framework.",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Connais le Framework PHP intitulé Symfony ?", "/run", "/quit"]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert run_output == "Symfony is a PHP framework."
    assert "SFE run" not in run_output
    assert "SFE console output" not in run_output
    assert len(executor.console_calls) == 1
    assert executor.patch_calls == []


def test_tui_run_debug_console_output_renders_full_report(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor(
        response=ExecutorResponse(
            answer="Symfony is a PHP framework.",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Connais le Framework PHP intitulé Symfony ?", "/run-debug", "/quit"]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "execution mode: console_output" in run_output
    assert "execution-mode router provider: fake-execution-mode-router" in run_output
    assert "SFE console output" in run_output
    assert "Symfony is a PHP framework." in run_output
    assert len(executor.console_calls) == 1
    assert executor.patch_calls == []


def test_tui_run_debug_underscore_alias_renders_full_report(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor(
        response=ExecutorResponse(
            answer="Symfony is a PHP framework.",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Connais le Framework PHP intitulé Symfony ?", "/run_debug", "/quit"]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "execution mode: console_output" in run_output
    assert "SFE console output" in run_output
    assert "Symfony is a PHP framework." in run_output
    assert len(executor.console_calls) == 1
    assert executor.patch_calls == []


def test_tui_run_report_before_any_run_renders_clear_message(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor()
    router = FakeExecutionModeRouter()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/run-report", "/quit"]),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=router,
    )

    assert app.run() == 0
    assert output[-1] == "No previous run result available."
    assert app.last_run_result is None
    assert router.calls == []
    assert executor.console_calls == []
    assert executor.patch_calls == []


def test_tui_run_report_after_console_run_does_not_execute_again(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor(
        response=ExecutorResponse(
            answer="Symfony is a PHP framework.",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    router = FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT)
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Connais le Framework PHP intitulé Symfony ?",
                "/run",
                "/run-report",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=router,
    )

    assert app.run() == 0
    assert app.last_run_result is not None
    assert app.last_run_result.status == "completed"
    assert len(router.calls) == 1
    assert len(executor.console_calls) == 1
    report_output = output[-1]
    assert "SFE run" in report_output
    assert "execution mode: console_output" in report_output
    assert "SFE console output" in report_output
    assert "Symfony is a PHP framework." in report_output


def test_tui_run_debug_still_executes_fresh_after_run(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor(
        response=ExecutorResponse(
            answer="Symfony is a PHP framework.",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    router = FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT)
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Connais le Framework PHP intitulé Symfony ?",
                "/run",
                "/run-debug",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=router,
    )

    assert app.run() == 0
    assert len(router.calls) == 2
    assert len(executor.console_calls) == 2
    assert app.last_run_result is not None
    assert app.last_run_result.status == "completed"
    assert "SFE run" in output[-1]
    assert "execution mode: console_output" in output[-1]


def test_tui_run_report_after_run_debug_reports_debug_run_result(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    executor = FakeExecutor(
        response=ExecutorResponse(
            answer="Symfony is a PHP framework.",
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    router = FakeExecutionModeRouter(EXECUTION_MODE_CONSOLE_OUTPUT)
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/task Connais le Framework PHP intitulé Symfony ?",
                "/run-debug",
                "/run-report",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=executor),
        execution_mode_router=router,
    )

    assert app.run() == 0
    assert len(router.calls) == 1
    assert len(executor.console_calls) == 1
    debug_output = output[-2]
    report_output = output[-1]
    assert "SFE run" in debug_output
    assert report_output == debug_output


def test_tui_run_workspace_write_renders_compact_summary(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/run", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=FakeExecutionModeRouter(),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "status: completed" in run_output
    assert "execution mode: workspace_write" in run_output
    assert "promoted files: context.txt" in run_output
    assert "modified relative paths: context.txt" in run_output
    assert "created relative paths: none" in run_output
    assert "execution-mode router provider:" not in run_output
    assert "worktree path:" not in run_output
    assert "discovery candidates:" not in run_output
    assert "warnings:" not in run_output
    assert "router review: not run" not in run_output
    assert (repo / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert executor.patch_calls
    assert app.last_run_result is not None
    assert app.last_run_result.status == "completed"
    assert app.last_run_result.patch_generated is True
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_report_after_workspace_write_run_does_not_execute_again(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor()
    router = FakeExecutionModeRouter()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Patch old context", "/run", "/run-report", "/quit"]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=router,
    )

    assert app.run() == 0
    assert len(router.calls) == 1
    assert len(executor.patch_calls) == 1
    report_output = output[-1]
    assert "SFE run" in report_output
    assert "status: completed" in report_output
    assert "execution-mode router provider: fake-execution-mode-router" in report_output
    assert "patch generated: yes" in report_output
    assert "promotion: applied" in report_output
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_debug_workspace_write_renders_full_report(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/run-debug", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=FakeExecutionModeRouter(),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "status: completed" in run_output
    assert "execution mode: workspace_write" in run_output
    assert "execution-mode router provider: fake-execution-mode-router" in run_output
    assert "worktree path:" in run_output
    assert "discovery candidates:" in run_output
    assert "patch generated: yes" in run_output
    assert "promotion: applied" in run_output
    assert "router review: not run" in run_output
    assert (repo / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert executor.patch_calls
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_external_action_renders_compact_message(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Create a calendar event", "/run", "/quit"]),
        output=output.append,
        cwd=workspace,
        backend=DirectBackend(executor=FakeExecutor()),
        execution_mode_router=FakeExecutionModeRouter(EXECUTION_MODE_EXTERNAL_ACTION),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "status: failed" in run_output
    assert "execution mode: external_action" in run_output
    assert "external action: not implemented" in run_output
    assert "issue category: unsupported_execution_mode" in run_output
    assert "issue reason: external_action_not_implemented" in run_output
    assert "execution-mode router provider:" not in run_output
    assert "worktree path:" not in run_output


def test_tui_run_invalid_response_failure_stores_last_result_and_hints(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=None,
            error_category="invalid_response",
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/run", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=FakeExecutionModeRouter(),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "status: failed" in run_output
    assert "issue category: patch_generation" in run_output
    assert "issue reason: invalid_response" in run_output
    assert (
        "hint: executor returned an invalid or empty response; "
        "use /run-report for diagnostics or retry /run"
    ) in run_output
    assert app.last_run_result is not None
    assert app.last_run_result.status == "failed"
    assert app.last_run_result.issue is not None
    assert app.last_run_result.issue.category == "patch_generation"
    assert app.last_run_result.issue.reason == "invalid_response"
    assert len(executor.patch_calls) == 1
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_report_after_failed_run_does_not_execute_again(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=None,
            error_category="invalid_response",
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    router = FakeExecutionModeRouter()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Patch old context", "/run", "/run-report", "/quit"]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=router,
    )

    assert app.run() == 0
    assert len(router.calls) == 1
    assert len(executor.patch_calls) == 1
    report_output = output[-1]
    assert "SFE run" in report_output
    assert "status: failed" in report_output
    assert "issue category: patch_generation" in report_output
    assert "issue reason: invalid_response" in report_output
    assert "executor provider: fake-executor" in report_output
    assert "patch generated: no" in report_output
    assert "patch proposal output length: 0" in report_output
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_report_displays_safe_invalid_response_shape_diagnostics(
    tmp_path,
) -> None:
    repo = init_git_repo(tmp_path / "repo")
    provider = FakeProvider(
        response={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"content": ""},
                }
            ],
            "error": {
                "message": "sk-SECRET_SHOULD_NOT_RENDER_123456",
                "type": "empty_content",
            },
            "output_text": "",
            "status": "failed",
        }
    )
    executor = OpenAIReadOnlyExecutor(
        provider=provider,
        model="test-model",
        provider_name="fake-provider",
    )
    router = FakeExecutionModeRouter()
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Patch old context", "/run", "/run-report", "/quit"]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=router,
    )

    assert app.run() == 0
    assert len(router.calls) == 1
    assert len(provider.calls) == 1
    report_output = output[-1]
    assert "SFE executor response diagnostics" in report_output
    assert "executor response provider: fake-provider" in report_output
    assert "executor response object type: dict" in report_output
    assert "executor response top-level keys: choices, error, output_text, status" in report_output
    assert "executor response choices exists: yes" in report_output
    assert "executor response choices count: 1" in report_output
    assert "executor response first choice keys: finish_reason, message" in report_output
    assert "executor response finish reason: stop" in report_output
    assert "executor response message keys: content" in report_output
    assert "executor response message content exists: yes" in report_output
    assert "executor response message content type: str" in report_output
    assert "executor response message content length: 0" in report_output
    assert "executor response output_text exists: yes" in report_output
    assert "executor response output_text type: str" in report_output
    assert "executor response output_text length: 0" in report_output
    assert "executor response error exists: yes" in report_output
    assert "executor response error type: dict" in report_output
    assert "executor response error keys: message, type" in report_output
    assert "executor response status exists: yes" in report_output
    assert "executor response status type: str" in report_output
    assert "sk-SECRET" not in report_output
    assert "empty_content" not in report_output
    assert "Protected instructions:" not in report_output
    assert "User task:" not in report_output
    assert "Selected context:" not in report_output
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_invalid_patch_proposal_omits_debug_diagnostics(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    (repo / "README.md").write_text("old readme\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "add readme")
    raw_output = (
        "# SFE Test 01\n\n"
        "Short README sentence.\n\n"
        "## Checks\n\n"
        "- README.md selected.\n"
    )
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw_output,
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Replace README.md with short content", "/run", "/quit"]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("README.md",)),
        execution_mode_router=FakeExecutionModeRouter(),
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "status: failed" in run_output
    assert "issue category: invalid_patch_proposal" in run_output
    assert "issue reason: missing_diff_header" in run_output
    assert "patch proposal output length:" not in run_output
    assert "patch proposal first line:" not in run_output
    assert "patch proposal looks like plain text:" not in run_output
    assert raw_output not in run_output
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_json_patch_proposal_missing_diff_header_hints_unified_diff(
    tmp_path,
) -> None:
    repo = init_git_repo(tmp_path / "repo")
    raw_output = (
        '{"edits":[{"path":"index.html","action":"create_file",'
        '"content":"<!doctype html>"}'
    )
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw_output,
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/run", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=FakeExecutionModeRouter(),
        patch_json_repairer=FakePatchJsonRepairer(None),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "status: failed" in run_output
    assert "issue category: invalid_patch_proposal" in run_output
    assert "issue reason: missing_diff_header" in run_output
    assert (
        "hint: executor returned JSON edit instructions instead of a unified diff; "
        "use /run-report for details or retry /run"
    ) in run_output
    assert "patch proposal looks like JSON:" not in run_output
    assert raw_output not in run_output
    assert app.last_run_result is not None
    assert app.last_run_result.patch_proposal_diagnostics is not None
    assert app.last_run_result.patch_proposal_diagnostics.looks_like_json is True
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_report_renders_hunk_accounting_diagnostics(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    raw_output = "\n".join(
        [
            "diff --git a/index.html b/index.html",
            "new file mode 100644",
            "--- /dev/null",
            "+++ b/index.html",
            "@@ -0,0 +1,5 @@",
            "+one",
            "+two",
            "+three",
        ]
    )
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw_output,
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Patch old context", "/run", "/run-report", "/quit"]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("context.txt",)),
        execution_mode_router=FakeExecutionModeRouter(),
    )

    assert app.run() == 0
    report_output = output[-1]
    assert "SFE hunk accounting diagnostics" in report_output
    assert "hunk path: index.html" in report_output
    assert "hunk header: @@ -0,0 +1,5 @@" in report_output
    assert "declared old start: 0" in report_output
    assert "declared old count: 0" in report_output
    assert "declared new start: 1" in report_output
    assert "declared new count: 5" in report_output
    assert "actual old-side count: 0" in report_output
    assert "actual new-side count: 3" in report_output
    assert "actual context line count: 0" in report_output
    assert "actual removed line count: 0" in report_output
    assert "actual added line count: 3" in report_output
    assert "looks like new-file hunk: yes" in report_output
    assert "old file header is /dev/null: yes" in report_output
    assert "hunk body only added lines: yes" in report_output
    assert "LLM-correctable in principle: yes" in report_output
    assert "+one" not in report_output
    assert "+two" not in report_output
    assert "+three" not in report_output
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_tui_run_debug_renders_invalid_patch_proposal_diagnostics(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    (repo / "README.md").write_text("old readme\n", encoding="utf-8")
    run_git(repo, "add", "README.md")
    run_git(repo, "commit", "-m", "add readme")
    raw_output = (
        "# SFE Test 01\n\n"
        "Short README sentence.\n\n"
        "## Checks\n\n"
        "- README.md selected.\n"
    )
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=raw_output,
            error_category=None,
            provider_calls_made=1,
            provider_name="fake-executor",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Replace README.md with short content", "/run-debug", "/quit"]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        discovery_router=FakeDiscoveryRouter(files_to_inspect=("README.md",)),
        execution_mode_router=FakeExecutionModeRouter(),
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    run_output = output[-1]
    assert "SFE run" in run_output
    assert "status: failed" in run_output
    assert "issue category: invalid_patch_proposal" in run_output
    assert "issue reason: missing_diff_header" in run_output
    assert "patch proposal output length:" in run_output
    assert "patch proposal first line: # SFE Test 01" in run_output
    assert "patch proposal looks like plain text: yes" in run_output
    assert "patch proposal mentions selected paths: README.md" in run_output
    assert raw_output not in run_output
    assert app.workspace_session is not None
    cleanup = app.workspace_manager.cleanup(app.workspace_session)
    assert cleanup.cleaned is True


def test_worktree_diff_shows_changed_files(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    app = SfeTuiApp(
        input_provider=FakeInput([""]),
        output=lambda text: None,
        cwd=repo,
    )
    assert app._select_workspace() is True
    app._handle_command("/isolate")
    assert app.workspace_session is not None
    session = app.workspace_session
    (session.worktree_path / "context.txt").write_text("changed in worktree\n", encoding="utf-8")
    output: list[str] = []
    app.output = output.append

    app._handle_command("/worktree-diff")

    rendered = "\n".join(output)
    assert "SFE worktree-diff" in rendered
    assert "changed files: context.txt" in rendered
    assert "changed in worktree" in rendered
    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_review_worktree_renders_ok_promote(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    reviewer = FakeWorkspaceReviewer()
    app = SfeTuiApp(
        input_provider=FakeInput([""]),
        output=lambda text: None,
        cwd=repo,
        workspace_reviewer=reviewer,
    )
    assert app._select_workspace() is True
    app._handle_command("/task Patch old context")
    app._handle_command("/isolate")
    assert app.workspace_session is not None
    session = app.workspace_session
    (session.worktree_path / "context.txt").write_text("changed in worktree\n", encoding="utf-8")
    output: list[str] = []
    app.output = output.append

    app._handle_command("/review-worktree")

    rendered = "\n".join(output)
    assert "SFE review-worktree" in rendered
    assert "router decision: OK_PROMOTE" in rendered
    assert "router provider: fake-workspace-router" in rendered
    assert "router reason: worktree changes match the requested task" in rendered
    assert "merge: not performed" in rendered
    assert reviewer.calls[0]["original_user_task"] == "Patch old context"
    assert reviewer.calls[0]["changed_files"] == ["context.txt"]
    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_review_worktree_renders_ko_block(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    reviewer = FakeWorkspaceReviewer(
        WorkspaceReviewDecision(
            decision="KO_BLOCK",
            reason="worktree changes are unrelated",
            files_reviewed=("context.txt",),
            risk_level="high",
            provider_name="fake-workspace-router",
            model="fake-workspace-router-model",
        )
    )
    app = SfeTuiApp(
        input_provider=FakeInput([""]),
        output=lambda text: None,
        cwd=repo,
        workspace_reviewer=reviewer,
    )
    assert app._select_workspace() is True
    app._handle_command("/task Patch old context")
    app._handle_command("/isolate")
    assert app.workspace_session is not None
    session = app.workspace_session
    (session.worktree_path / "context.txt").write_text("unrelated\n", encoding="utf-8")
    output: list[str] = []
    app.output = output.append

    app._handle_command("/review-worktree")

    rendered = "\n".join(output)
    assert "router decision: KO_BLOCK" in rendered
    assert "router risk level: high" in rendered
    assert "router reason: worktree changes are unrelated" in rendered
    assert "promotion: not performed" in rendered
    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_cleanup_worktree_removes_sfe_worktree_and_restores_source_workspace(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput([""]),
        output=output.append,
        cwd=repo,
    )
    assert app._select_workspace() is True
    app._handle_command("/isolate")
    assert app.workspace_session is not None
    session = app.workspace_session
    assert session.worktree_path.exists()

    app._handle_command("/cleanup-worktree")

    rendered = "\n".join(output)
    assert "SFE cleanup-worktree" in rendered
    assert "status: cleaned" in rendered
    assert app.workspace_session is None
    assert app.workspace_root == repo.resolve()
    assert not session.worktree_path.exists()
    assert session.metadata_path is not None
    assert not session.metadata_path.exists()


def test_reset_does_not_delete_active_worktree(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/isolate", "/task Patch old context", "/reset", "/quit"]),
        output=output.append,
        cwd=repo,
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    assert session.worktree_path.exists()
    assert app.workspace_root == session.worktree_path
    assert app.task == ""
    rendered = "\n".join(output)
    assert "Session reset. Workspace is preserved." in rendered

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_gc_worktrees_dry_run_reports_sfe_worktree_without_removing(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/isolate", "/gc-worktrees", "/quit"]),
        output=output.append,
        cwd=repo,
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    rendered = "\n".join(output)
    assert "SFE gc-worktrees" in rendered
    assert "mode: dry-run" in rendered
    assert "SFE worktrees found: 1" in rendered
    assert "status=protected_skipped" in rendered
    assert session.worktree_path.exists()

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_gc_worktrees_clean_keeps_active_worktree_protected(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/isolate", "/gc-worktrees --clean", "/quit"]),
        output=output.append,
        cwd=repo,
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    rendered = "\n".join(output)
    assert "mode: clean" in rendered
    assert "worktrees removed: 0" in rendered
    assert "status=protected_skipped" in rendered
    assert session.worktree_path.exists()

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_auto_patch_stops_if_no_task_is_present(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/files context.txt", "/auto-patch", "/quit"]),
        output=output.append,
        cwd=tmp_path,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert "SFE auto-patch" in rendered
    assert "status: stopped" in rendered
    assert "reason: missing_task" in rendered
    assert source.read_text(encoding="utf-8") == "old context\n"


def test_auto_patch_runs_patch_apply_with_router_ok(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/auto-patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "new context\n"
    assert "SFE auto-patch step: patch" in rendered
    assert "router decision: OK_APPLY" in rendered
    assert "status: completed" in rendered


def test_auto_patch_stops_and_reports_router_ko_block(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
    )
    reviewer = FakePatchReviewer(
        PatchReviewDecision(
            decision="KO_BLOCK",
            reason="auto patch blocked by router",
            files_reviewed=("context.txt",),
            risk_level="medium",
            provider_name="fake-router",
            model="fake-router-model",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/auto-patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert "router decision: KO_BLOCK" in rendered
    assert "router reason: auto patch blocked by router" in rendered
    assert "reason: apply_patch_failed" in rendered


def test_auto_worktree_creates_isolation_and_leaves_source_unchanged(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/auto-worktree", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
        workspace_reviewer=FakeWorkspaceReviewer(),
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    rendered = "\n".join(output)
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    assert (session.worktree_path / "context.txt").read_text(encoding="utf-8") == "new context\n"
    assert run_git(repo, "status", "--porcelain").stdout.strip() == ""
    assert "router decision: OK_PROMOTE" in rendered
    assert "cleanup: not performed" in rendered
    assert session.worktree_path.exists()

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_auto_worktree_preserves_manual_files_after_isolate(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files context.txt",
                "/task Patch old context",
                "/auto-worktree",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
        workspace_reviewer=FakeWorkspaceReviewer(),
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    selected_segments = executor.patch_calls[0]["selected_context_segments"]
    selected_refs = [segment.source_ref for segment in selected_segments]
    rendered = "\n".join(output)
    assert selected_refs == ["context.txt"]
    assert "Context files replaced: loaded 1; skipped 0" in rendered
    assert "SFE auto-worktree step: discover" not in rendered
    assert (session.worktree_path / "context.txt").read_text(encoding="utf-8") == "new context\n"

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_auto_worktree_stops_on_patch_failure(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(None, "provider_error", 1)
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/auto-worktree", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    rendered = "\n".join(output)
    assert "reason: patch_failed" in rendered
    assert "SFE review-worktree" not in rendered
    assert session.worktree_path.exists()

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_auto_worktree_stops_on_apply_ko_block(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
    )
    reviewer = FakePatchReviewer(
        PatchReviewDecision(
            decision="KO_BLOCK",
            reason="auto worktree apply blocked",
            files_reviewed=("context.txt",),
            risk_level="medium",
            provider_name="fake-router",
            model="fake-router-model",
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/auto-worktree", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    rendered = "\n".join(output)
    assert "router decision: KO_BLOCK" in rendered
    assert "router reason: auto worktree apply blocked" in rendered
    assert "reason: apply_patch_failed" in rendered
    assert (repo / "context.txt").read_text(encoding="utf-8") == "old context\n"
    assert (session.worktree_path / "context.txt").read_text(encoding="utf-8") == "old context\n"

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_auto_worktree_reaches_review_and_does_not_cleanup(tmp_path) -> None:
    repo = init_git_repo(tmp_path / "repo")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(["", "/task Patch old context", "/auto-worktree", "/quit"]),
        output=output.append,
        cwd=repo,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
        workspace_reviewer=FakeWorkspaceReviewer(),
    )

    assert app.run() == 0
    assert app.workspace_session is not None
    session = app.workspace_session
    rendered = "\n".join(output)
    assert "SFE review-worktree" in rendered
    assert "router decision: OK_PROMOTE" in rendered
    assert "merge: not performed" in rendered
    assert "push: not performed" in rendered
    assert "cleanup: not performed" in rendered
    assert session.worktree_path.exists()
    assert run_git(repo, "status", "--porcelain").stdout.strip() == ""

    cleanup = app.workspace_manager.cleanup(session)
    assert cleanup.cleaned is True


def test_patch_review_prompt_describes_full_replacement_as_expected_transport() -> None:
    payload = {
        "proposal_format": "file_replacements",
        "current_files": [{"path": "context.txt", "content": "old context\n"}],
        "proposed_full_replacements": [
            {
                "path": "context.txt",
                "action": "replace_existing_file",
                "content": "old context\nnew line\n",
            }
        ],
        "diff_preview": "@@ -1 +1,2 @@\n old context\n+new line",
    }

    prompt = _build_review_prompt(payload)

    assert "full-file replacements" in PATCH_REVIEW_SYSTEM_INSTRUCTION
    assert "Do not reject a proposal merely because it uses full-file replacement format" in (
        PATCH_REVIEW_SYSTEM_INSTRUCTION
    )
    assert "Judge the effective semantic and textual delta" in (
        PATCH_REVIEW_SYSTEM_INSTRUCTION
    )
    assert "decision must be OK_APPLY or KO_BLOCK" in PATCH_REVIEW_SYSTEM_INSTRUCTION
    assert "risk_level must be low, medium, or high" in PATCH_REVIEW_SYSTEM_INSTRUCTION
    assert "files_reviewed must be a JSON array of strings" in (
        PATCH_REVIEW_SYSTEM_INSTRUCTION
    )
    assert "Do not return a string, object, count, or comma-separated text" in (
        PATCH_REVIEW_SYSTEM_INSTRUCTION
    )
    assert "expected internal application format" in prompt
    assert "not evidence that the user-visible edit is large or non-minimal" in prompt
    assert "Compare current_files with proposed_full_replacements" in prompt
    assert "diff_preview field was computed locally by SFE" in prompt
    assert "Allow OK_APPLY when the effective diff is small" in prompt
    assert "Patch review payload JSON:" in prompt


def test_direct_patch_reviewer_sends_full_replacement_guidance_to_provider() -> None:
    provider = FakeProvider(
        response={
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "decision": "OK_APPLY",
                                "reason": "effective delta is small",
                                "files_reviewed": ["context.txt"],
                                "risk_level": "low",
                            }
                        )
                    }
                }
            ]
        }
    )
    reviewer = DirectProviderPatchReviewer(
        provider=provider,
        provider_name="fake-router",
        model="fake-router-model",
        call_style="system_instruction",
    )

    decision = reviewer.review(
        {
            "proposal_format": "file_replacements",
            "current_files": [{"path": "context.txt", "content": "old context\n"}],
            "proposed_full_replacements": [
                {"path": "context.txt", "content": "old context\nnew line\n"}
            ],
        }
    )

    assert decision.decision == "OK_APPLY"
    assert "full-file replacements" in provider.calls[0]["system_instruction"]
    assert "Do not reject a proposal merely because it uses full-file replacement format" in (
        provider.calls[0]["system_instruction"]
    )
    prompt = provider.calls[0]["messages"][0]["content"]
    assert "expected internal application format" in prompt
    assert "not evidence that the user-visible edit is large or non-minimal" in prompt


def test_delta_aware_reviewer_allows_small_delta_full_replacement(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            replacement_proposal(content="old context\nnew line\n"),
            None,
            1,
        )
    )
    reviewer = DeltaAwareFakePatchReviewer()
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\nnew line\n"
    assert "router decision: OK_APPLY" in rendered
    assert "router reason: effective delta is a small task-aligned addition" in rendered


def test_delta_aware_reviewer_blocks_unrelated_full_replacement(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            replacement_proposal(content="totally unrelated rewrite\n"),
            None,
            1,
        )
    )
    reviewer = DeltaAwareFakePatchReviewer()
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert app.pending_patch is not None
    assert "router decision: KO_BLOCK" in rendered
    assert "router reason: effective delta replaces unrelated content" in rendered


def test_apply_patch_router_ko_blocks_and_keeps_pending_patch(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
    )
    reviewer = FakePatchReviewer(
        PatchReviewDecision(
            decision="KO_BLOCK",
            reason="patch changes the wrong behavior",
            files_reviewed=("context.txt",),
            risk_level="medium",
            provider_name="fake-router",
            model="fake-router-model",
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert app.pending_patch is not None
    assert len(reviewer.calls) == 1
    assert "error category: router_rejected_patch" in rendered
    assert "failure kind: router_rejected" in rendered
    assert "router decision: KO_BLOCK" in rendered
    assert "router reason: patch changes the wrong behavior" in rendered
    assert "pending patch cleared: no" in rendered


def test_apply_patch_absolute_path_rejected_before_router_review(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal("/tmp/outside.txt"), None, 1)
    )
    reviewer = FakePatchReviewer()
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert len(reviewer.calls) == 0
    assert "failure kind: mechanical_safety_guard" in rendered
    assert "reason category: absolute_path" in rendered


def test_apply_patch_workspace_escape_rejected_before_router_review(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal("../outside.txt"), None, 1)
    )
    reviewer = FakePatchReviewer()
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert len(reviewer.calls) == 0
    assert "failure kind: mechanical_safety_guard" in rendered
    assert "reason category: path_outside_workspace" in rendered


def test_apply_patch_physical_write_failure_keeps_pending_patch(
    tmp_path,
) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal("missing.txt"),
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
        patch_reviewer=FakePatchReviewer(),
    )
    assert app._select_workspace() is True
    app._handle_files("context.txt")
    app._handle_command("/task Patch old context")
    app._handle_patch()

    app._handle_apply_patch()

    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert app.pending_patch is not None
    assert "error category: physical_write_failure" in rendered
    assert "failure kind: physical_write_failure" in rendered
    assert "reason category: target_not_existing_file" in rendered
    assert "hunk_preimage_mismatch" not in rendered
    assert "router decision: OK_APPLY" in rendered
    assert "pending patch cleared: no" in rendered


def test_apply_patch_physical_write_failure_rolls_back_prior_writes(
    tmp_path,
    monkeypatch,
) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_text("old first\n", encoding="utf-8")
    second.write_text("old second\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            json.dumps(
                {
                    "edits": [
                        {
                            "path": "first.txt",
                            "action": "replace_existing_file",
                            "content": "new first\n",
                        },
                        {
                            "path": "second.txt",
                            "action": "replace_existing_file",
                            "content": "new second\n",
                        },
                    ],
                    "diff_preview": "\n".join(
                        [
                            valid_text_diff("first.txt", old="old first", new="new first"),
                            valid_text_diff("second.txt", old="old second", new="new second"),
                        ]
                    ),
                }
            ),
            None,
            1,
        )
    )
    import sfe.patching as patching

    real_replace = patching.os.replace
    replace_calls = 0

    def fail_second_replace(src: object, dst: object) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise OSError("simulated replace failure")
        real_replace(src, dst)

    monkeypatch.setattr(patching.os, "replace", fail_second_replace)
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            [
                "",
                "/files first.txt second.txt",
                "/task Patch old first and old second",
                "/patch",
                "/apply-patch",
                "/quit",
            ]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert first.read_text(encoding="utf-8") == "old first\n"
    assert second.read_text(encoding="utf-8") == "old second\n"
    assert app.pending_patch is not None
    assert "error category: physical_write_failure" in rendered
    assert "pending patch cleared: no" in rendered


def test_apply_patch_calls_router_reviewer_but_not_ask_executor(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal(),
            error_category=None,
            provider_calls_made=1,
        )
    )
    reviewer = FakePatchReviewer()
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
        patch_reviewer=reviewer,
    )

    assert app.run() == 0
    assert len(executor.patch_calls) == 1
    assert len(executor.calls) == 0
    assert len(reviewer.calls) == 1


def test_apply_patch_does_not_use_shell_commands(tmp_path, monkeypatch) -> None:
    import os
    import subprocess

    def fail_shell(*_: object, **__: object) -> None:
        raise AssertionError("shell command should not be used")

    monkeypatch.setattr(os, "system", fail_shell)
    monkeypatch.setattr(subprocess, "run", fail_shell)
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
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
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    assert source.read_text(encoding="utf-8") == "new context\n"


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
            patch_response=ExecutorResponse(replacement_proposal(), None, 1),
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
        patch_response=ExecutorResponse(replacement_proposal(), None, 1)
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


def test_patch_unsupported_edit_format_does_not_store_pending_proposal(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            json.dumps(
                {
                    "edits": [
                        {
                            "path": "context.txt",
                            "action": "delete_file",
                            "content": "new context\n",
                        }
                    ]
                }
            ),
            None,
            1,
        )
    )
    output: list[str] = []
    repairer = FakePatchJsonRepairer(replacement_proposal())
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/files context.txt", "/task Patch old context", "/patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_json_repairer=repairer,
    )

    assert app.run() == 0

    rendered = "\n".join(output)
    assert source.read_text(encoding="utf-8") == "old context\n"
    assert app.pending_patch is None
    assert repairer.calls == []
    assert "pending patch stored: no" in rendered
    assert "pending patch reason: unsupported_edit_format" in rendered
    assert "pending patch repair attempted: no" in rendered


def test_apply_patch_json_replace_existing_file_absent_target_is_refused(tmp_path) -> None:
    source = tmp_path / "PROJECT_REQUEST.md"
    source.write_text("Update missing file", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal("missing.txt", content="new context\n"),
            error_category=None,
            provider_calls_made=1,
        )
    )
    output: list[str] = []
    app = SfeTuiApp(
        input_provider=FakeInput(
            ["", "/task Update missing file", "/discover", "/patch", "/apply-patch", "/quit"]
        ),
        output=output.append,
        cwd=tmp_path,
        backend=DirectBackend(executor=executor),
        patch_reviewer=FakePatchReviewer(),
    )

    assert app.run() == 0
    rendered = "\n".join(output)
    assert app.pending_patch is not None
    assert not (tmp_path / "missing.txt").exists()
    assert "error category: physical_write_failure" in rendered
    assert "reason category: target_not_existing_file" in rendered


def test_status_and_context_show_safe_pending_patch_metadata(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context SECRET_FILE_CONTENT\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal(
                old="old context SECRET_FILE_CONTENT",
                new="new context\n",
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
    assert f"workspace: {safe_workspace_label(tmp_path, tmp_path)}" in status_block
    for block in (status_block, context_block):
        assert "pending patch: yes" in block
        assert "pending patch files: 1" in block
        assert "pending patch hunks: 1" in block
        assert "SECRET_FILE_CONTENT" not in block
        assert "SECRET_TASK_TEXT" not in block
    assert str(tmp_path.resolve()) not in context_block


def test_apply_diagnostics_omit_raw_sensitive_material(tmp_path) -> None:
    source = tmp_path / "context.txt"
    source.write_text("old context SECRET_FILE_CONTENT\n", encoding="utf-8")
    executor = FakeExecutor(
        patch_response=ExecutorResponse(
            answer=replacement_proposal(
                old="old context SECRET_FILE_CONTENT",
                new="new context SECRET_FILE_CONTENT\n",
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
        patch_reviewer=FakePatchReviewer(),
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
    assert result.response_diagnostics is not None
    assert result.response_diagnostics["message_content_length"] == 0


def test_openai_executor_records_empty_choices_response_shape_diagnostics() -> None:
    provider = FakeProvider(
        response={
            "sk-SECRET_KEY_SHOULD_NOT_RENDER": "value",
            "choices": [],
            "error": {
                "message": "sk-SECRET_SHOULD_NOT_RENDER_123456",
                "type": "empty_choices",
            },
            "status": "failed",
        }
    )
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
    assert result.response_diagnostics == {
        "provider_name": "openai",
        "response_object_type": "dict",
        "top_level_keys": ("[redacted]", "choices", "error", "status"),
        "choices_exists": True,
        "choices_count": 0,
        "first_choice_keys": (),
        "finish_reason": None,
        "message_keys": (),
        "message_content_exists": False,
        "message_content_type": None,
        "message_content_length": None,
        "output_text_exists": False,
        "output_text_type": None,
        "output_text_length": None,
        "error_exists": True,
        "error_type": "dict",
        "error_keys": ("message", "type"),
        "status_exists": True,
        "status_type": "str",
    }
    assert "sk-SECRET" not in str(result.response_diagnostics)


def test_openai_executor_records_missing_content_response_shape_diagnostics() -> None:
    provider = FakeProvider(
        response={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant"},
                }
            ],
            "output_text": None,
        }
    )
    executor = OpenAIReadOnlyExecutor(provider=provider, model="test-model")

    result = executor.execute(
        {
            "instructions": [],
            "task": None,
            "selected_context_segments": [],
        }
    )

    diagnostics = result.response_diagnostics
    assert result.answer is None
    assert result.error_category == "invalid_response"
    assert diagnostics is not None
    assert diagnostics["choices_count"] == 1
    assert diagnostics["first_choice_keys"] == ("finish_reason", "message")
    assert diagnostics["finish_reason"] == "stop"
    assert diagnostics["message_keys"] == ("role",)
    assert diagnostics["message_content_exists"] is False
    assert diagnostics["message_content_type"] is None
    assert diagnostics["message_content_length"] is None
    assert diagnostics["output_text_exists"] is True
    assert diagnostics["output_text_type"] == "NoneType"
    assert diagnostics["output_text_length"] is None


def test_openai_executor_records_output_text_shape_diagnostics() -> None:
    provider = FakeProvider(
        response={
            "choices": [{"message": {"content": ""}}],
            "output_text": "",
        }
    )
    executor = OpenAIReadOnlyExecutor(provider=provider, model="test-model")

    result = executor.execute(
        {
            "instructions": [],
            "task": None,
            "selected_context_segments": [],
        }
    )

    diagnostics = result.response_diagnostics
    assert result.answer is None
    assert result.error_category == "invalid_response"
    assert diagnostics is not None
    assert diagnostics["message_content_exists"] is True
    assert diagnostics["message_content_type"] == "str"
    assert diagnostics["message_content_length"] == 0
    assert diagnostics["output_text_exists"] is True
    assert diagnostics["output_text_type"] == "str"
    assert diagnostics["output_text_length"] == 0


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
    assert DEFAULT_PATCH_OUTPUT_TOKENS == 12000
    assert provider.calls[0]["system_instruction"] == PATCH_SYSTEM_INSTRUCTION
    assert provider.calls[0]["system_instruction"] != READ_ONLY_SYSTEM_INSTRUCTION
    assert provider.calls[0]["max_tokens"] == 12000


def test_openai_executor_console_uses_console_instruction_and_output_budget() -> None:
    provider = FakeProvider()
    executor = OpenAIReadOnlyExecutor(provider=provider, model="test-model")

    result = executor.answer_console(
        {
            "instructions": [],
            "task": None,
            "selected_context_segments": [],
        }
    )

    assert result.answer == "provider answer"
    assert provider.calls[0]["system_instruction"] == CONSOLE_SYSTEM_INSTRUCTION
    assert provider.calls[0]["system_instruction"] != PATCH_SYSTEM_INSTRUCTION
    assert provider.calls[0]["max_tokens"] == DEFAULT_MAX_OUTPUT_TOKENS


def test_console_system_instruction_forbids_diffs_and_file_edits() -> None:
    instruction = CONSOLE_SYSTEM_INSTRUCTION

    assert "Answer the user's task directly" in instruction
    assert "general questions without selected workspace context" in instruction
    assert "Do not modify files" in instruction
    assert "Do not produce a patch, diff, or file replacement JSON" in instruction


def test_patch_system_instruction_requires_unified_diff_only() -> None:
    instruction = PATCH_SYSTEM_INSTRUCTION

    assert "Return only a strict unified diff/git diff" in instruction
    assert "diff --git a/<relative-path> b/<relative-path>" in instruction
    assert "The response must start with a diff header" in instruction
    assert "Do not return JSON" in instruction
    assert "Do not return an edits array" in instruction
    assert "Do not return Markdown" in instruction
    assert "Do not wrap the patch in a code fence" in instruction
    assert "Do not explain the patch" in instruction
    assert "Do not include a file manifest" in instruction
    assert "All paths must be relative to the workspace" in instruction
    assert "--- /dev/null" in instruction
    assert "+++ b/<relative-path>" in instruction
    assert "normal unified diff hunks" in instruction
    assert "Hunk header counts must exactly match the hunk body" in instruction
    assert "@@ -0,0 +1,N @@" in instruction
    assert "N exactly equals the number of added + lines" in instruction
    assert "Every added content line must start with +" in instruction
    assert "Do not guess hunk counts" in instruction
    assert "keep files smaller and hunks simpler" in instruction
    assert ".git, vendor, var, cache" in instruction
    assert "deletes" in instruction
    assert "renames" in instruction
    assert "mode-only changes" in instruction
    assert "binary patches" in instruction
    assert "symlink changes" in instruction
    assert "If no safe unified diff can be proposed, return no text" in instruction
    assert "Return only one strict JSON object" not in instruction
    assert '"edits"' not in instruction


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
    assert "Local dry-run context preview" in rendered
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
    assert "Local dry-run context preview" in rendered
    assert "Selected context" in rendered
    assert "Skipped/rejected context" in rendered
    assert "Safety guarantees" in rendered
    assert "backend: direct" in rendered
    assert "provider calls made: 0" in rendered
    assert "executor/provider called: no" in rendered
    assert "automatic writes disabled" in rendered
    assert "shell disabled" in rendered
    assert "patch application available through explicit /apply-patch" in rendered
    assert "/discover reports its own discovery mode" in rendered


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

    assert "Local dry-run context preview" in rendered
    assert f"selector mode: {LOCAL_LEXICAL_PREVIEW_MODE}" in rendered
    assert "this dry-run context preview is local" in rendered
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
    normalized_note = " ".join(note.split())
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
    assert "the proxy, write files, execute shell commands" in normalized_note
    assert "dry-run" in normalized_note
    assert "tui_direct_backend_strategy.md" in index
    milestone = (
        PROJECT_ROOT / "docs" / "tui_readonly_ask_milestone.md"
    ).read_text(encoding="utf-8")
    normalized_milestone = " ".join(milestone.split())
    assert "selected 3 of 7 context segments" in milestone
    assert "38.92%" in milestone
    assert "36.58%" in milestone
    assert "40.83%" in milestone
    assert "raised from 800 to 1500 tokens" in milestone
    assert "source/path-aware lexical ranking" in milestone
    assert "`/patch` is the next proposal-only phase" in milestone
    assert "Patch proposal only, not applied" in normalized_milestone
    assert "does not write files, apply patches, execute shell commands" in normalized_milestone
    assert "larger local output budget than" in normalized_milestone
    assert "`/reset` exists as a session comfort command" in milestone
    assert "preserves the selected workspace" in milestone
    assert "not a benchmark" in milestone
    assert "tui_readonly_ask_milestone.md" in index
