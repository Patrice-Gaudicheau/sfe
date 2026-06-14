"""Tests for the core filesystem executor boundary."""

from __future__ import annotations

from pathlib import Path

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
