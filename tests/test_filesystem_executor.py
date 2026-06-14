"""Tests for the core filesystem executor boundary."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sfe.aider_env_bridge import AiderEnvBridgeResult
from sfe.aider_filesystem_executor import AiderFilesystemExecutor
from sfe.aider_preflight import AiderPreflightResult
from sfe.filesystem_executor import (
    FilesystemExecutionDiagnostics,
    FilesystemExecutionRequest,
    FilesystemExecutionResult,
)


class FakeFilesystemExecutor:
    name = "fake-filesystem"

    def execute(
        self,
        request: FilesystemExecutionRequest,
    ) -> FilesystemExecutionResult:
        target = request.cwd / "created.txt"
        target.write_text("created on disk\n", encoding="utf-8")
        diagnostics = FilesystemExecutionDiagnostics(
            executor_name=self.name,
            cwd=str(request.cwd),
            command=("fake-filesystem", "--apply"),
            return_code=0,
            stdout_length=len("created\n"),
            stderr_length=0,
            stdout_preview="created\n",
            stderr_preview="",
            elapsed_ms=7,
        )
        return FilesystemExecutionResult(
            executor_name=self.name,
            status="completed",
            changed_paths=("created.txt",),
            diagnostics=diagnostics,
        )


def test_fake_filesystem_executor_returns_disk_mutation_result(tmp_path: Path) -> None:
    request = FilesystemExecutionRequest(
        cwd=tmp_path,
        task="Create a file",
        expected_paths=("created.txt",),
        context_paths=("README.md",),
        metadata={"phase": "test"},
    )

    result = FakeFilesystemExecutor().execute(request)

    assert result.status == "completed"
    assert result.executor_name == "fake-filesystem"
    assert result.changed_paths == ("created.txt",)
    assert result.error_category is None
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == (
        "created on disk\n"
    )
    assert result.diagnostics.executor_name == "fake-filesystem"
    assert result.diagnostics.cwd == str(tmp_path)
    assert result.diagnostics.command == ("fake-filesystem", "--apply")
    assert result.diagnostics.return_code == 0
    assert result.diagnostics.stdout_length == len("created\n")
    assert result.diagnostics.stderr_length == 0
    assert result.diagnostics.stdout_preview == "created\n"
    assert result.diagnostics.elapsed_ms == 7


def test_aider_filesystem_executor_uses_message_file_and_bounded_command(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []
    env_file_path: Path | None = None

    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal env_file_path
        message_index = command.index("--message-file") + 1
        message_path = Path(command[message_index])
        env_index = command.index("--env-file") + 1
        env_file_path = Path(command[env_index])
        assert message_path.exists()
        assert env_file_path.exists()
        assert not message_path.is_relative_to(tmp_path)
        assert not env_file_path.is_relative_to(tmp_path)
        assert "Create docs" in message_path.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" in env_file_path.read_text(encoding="utf-8")
        assert "OPENAI_API_KEY" not in kwargs["env"]
        assert kwargs["stdin"] is subprocess.DEVNULL
        assert kwargs["timeout"] == 30.0
        calls.append({"command": command, "cwd": kwargs["cwd"]})
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    executor = AiderFilesystemExecutor(
        preflight=lambda: AiderPreflightResult(
            available=True,
            executable_path="/home/patrice/.local/bin/aider",
            version_output="aider 0.86.2",
            install_guidance=(),
            diagnostics={},
        ),
        env_bridge=lambda: AiderEnvBridgeResult(
            provider_name="openai",
            aider_env={"OPENAI_API_KEY": "fixture-openai-key"},
            selected_model="gpt-fixture",
            selected_weak_model="gpt-weak-fixture",
            selected_timeout_seconds=30.0,
            missing_variables=(),
            error_category=None,
            diagnostics={
                "provider_name": "openai",
                "aider_env_variable_names": ("OPENAI_API_KEY",),
                "selected_model": "gpt-fixture",
                "selected_weak_model": "gpt-weak-fixture",
                "selected_timeout_seconds": 30.0,
                "missing_variables": (),
                "error_category": None,
            },
        ),
        runner=runner,
        monotonic=_monotonic_sequence(10.0, 10.25),
    )

    result = executor.execute(
        FilesystemExecutionRequest(
            cwd=tmp_path,
            task="Create docs",
            expected_paths=("docs/README.md",),
            context_paths=("context.txt",),
        )
    )

    assert result.status == "completed"
    assert result.executor_name == "aider"
    assert calls[0]["cwd"] == tmp_path
    command = calls[0]["command"]
    assert isinstance(command, list)
    assert "--message-file" in command
    assert "--env-file" in command
    assert "--model" in command
    assert "gpt-fixture" in command
    assert "--weak-model" in command
    assert "gpt-weak-fixture" in command
    assert "--timeout" in command
    assert "30" in command
    assert "--file" in command
    assert "docs/README.md" in command
    assert "--read" in command
    assert "context.txt" in command
    assert (
        result.diagnostics.command[
            result.diagnostics.command.index("--message-file") + 1
        ]
        == "<message-file>"
    )
    assert (
        result.diagnostics.command[result.diagnostics.command.index("--env-file") + 1]
        == "<aider-env-file>"
    )
    assert result.diagnostics.return_code == 0
    assert result.diagnostics.elapsed_ms == 250
    assert result.diagnostics.metadata["aider_path"] == "/home/patrice/.local/bin/aider"
    assert env_file_path is not None
    assert not env_file_path.exists()


def test_aider_filesystem_executor_missing_aider_returns_install_guidance(
    tmp_path: Path,
) -> None:
    executor = AiderFilesystemExecutor(
        preflight=lambda: AiderPreflightResult(
            available=False,
            executable_path=None,
            version_output=None,
            install_guidance=("pipx install aider-chat",),
            diagnostics={"reason": "aider_executable_not_found"},
        )
    )

    result = executor.execute(
        FilesystemExecutionRequest(cwd=tmp_path, task="Create docs")
    )

    assert result.status == "failed"
    assert result.error_category == "aider_missing"
    assert result.metadata["install_guidance"] == ("pipx install aider-chat",)


def test_aider_filesystem_executor_bridge_failure_does_not_run_aider(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []
    executor = AiderFilesystemExecutor(
        preflight=lambda: AiderPreflightResult(
            available=True,
            executable_path="/home/patrice/.local/bin/aider",
            version_output="aider 0.86.2",
            install_guidance=(),
            diagnostics={},
        ),
        env_bridge=lambda: AiderEnvBridgeResult(
            provider_name="openai",
            aider_env={},
            selected_model="gpt-fixture",
            selected_weak_model=None,
            selected_timeout_seconds=None,
            missing_variables=("OPENAI_API_KEY",),
            error_category="missing_aider_environment",
            diagnostics={
                "provider_name": "openai",
                "aider_env_variable_names": (),
                "selected_model": "gpt-fixture",
                "selected_weak_model": None,
                "selected_timeout_seconds": None,
                "missing_variables": ("OPENAI_API_KEY",),
                "error_category": "missing_aider_environment",
            },
        ),
        runner=lambda command, **_kwargs: calls.append(command) or subprocess.CompletedProcess(
            command,
            0,
            stdout="",
            stderr="",
        ),
    )

    result = executor.execute(
        FilesystemExecutionRequest(cwd=tmp_path, task="Create docs")
    )

    assert result.status == "failed"
    assert result.error_category == "missing_aider_environment"
    assert result.metadata["missing_variables"] == ("OPENAI_API_KEY",)
    assert calls == []


def test_aider_filesystem_executor_timeout_is_structured_and_bounded(
    tmp_path: Path,
) -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            timeout=1.0,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )

    executor = AiderFilesystemExecutor(
        preflight=lambda: AiderPreflightResult(
            available=True,
            executable_path="/home/patrice/.local/bin/aider",
            version_output="aider 0.86.2",
            install_guidance=(),
            diagnostics={},
        ),
        env_bridge=lambda: AiderEnvBridgeResult(
            provider_name="openai",
            aider_env={"OPENAI_API_KEY": "fixture-openai-key"},
            selected_model="gpt-fixture",
            selected_weak_model=None,
            selected_timeout_seconds=1.0,
            missing_variables=(),
            error_category=None,
            diagnostics={
                "provider_name": "openai",
                "aider_env_variable_names": ("OPENAI_API_KEY",),
                "selected_model": "gpt-fixture",
                "selected_weak_model": None,
                "selected_timeout_seconds": 1.0,
                "missing_variables": (),
                "error_category": None,
            },
        ),
        runner=runner,
        monotonic=_monotonic_sequence(20.0, 21.5),
    )

    result = executor.execute(
        FilesystemExecutionRequest(cwd=tmp_path, task="Create docs")
    )

    assert result.status == "failed"
    assert result.error_category == "aider_timeout"
    assert result.diagnostics.command[
        result.diagnostics.command.index("--message-file") + 1
    ] == "<message-file>"
    assert result.diagnostics.command[
        result.diagnostics.command.index("--env-file") + 1
    ] == "<aider-env-file>"
    assert result.diagnostics.stdout_preview == "partial stdout"
    assert result.diagnostics.stderr_preview == "partial stderr"
    assert result.diagnostics.elapsed_ms == 1500
    assert result.diagnostics.metadata["timeout_seconds"] == 1.0


def test_aider_filesystem_executor_rejects_windows_internal_paths(
    tmp_path: Path,
) -> None:
    executor = AiderFilesystemExecutor(
        preflight=lambda: AiderPreflightResult(
            available=True,
            executable_path="/home/patrice/.local/bin/aider",
            version_output="aider 0.86.2",
            install_guidance=(),
            diagnostics={},
        )
    )

    result = executor.execute(
        FilesystemExecutionRequest(
            cwd=tmp_path,
            task="Create docs",
            expected_paths=(".sfe-worktrees\\leak.txt",),
        )
    )

    assert result.status == "failed"
    assert result.error_category == "internal_aider_path"


def _monotonic_sequence(*values: float):
    items = list(values)

    def monotonic() -> float:
        return items.pop(0)

    return monotonic
