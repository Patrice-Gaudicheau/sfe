"""Tests for Aider executable preflight diagnostics."""

from __future__ import annotations

import subprocess

from sfe.aider_preflight import AIDER_INSTALL_GUIDANCE, check_aider_preflight


def test_aider_preflight_missing_executable_returns_install_guidance() -> None:
    result = check_aider_preflight(which=lambda _name: None)

    assert result.available is False
    assert result.executable_path is None
    assert result.version_output is None
    assert result.install_guidance == AIDER_INSTALL_GUIDANCE
    assert result.install_guidance[:7] == (
        "sudo apt update",
        "sudo apt install pipx",
        "pipx ensurepath",
        "exec $SHELL -l",
        "pipx install aider-chat",
        "aider --version",
        "which aider",
    )
    assert "Alternative: aider-install" in result.install_guidance
    assert result.diagnostics["reason"] == "aider_executable_not_found"


def test_aider_preflight_available_executable_captures_version_output() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command == ["/usr/bin/aider", "--version"]
        assert kwargs["timeout"] == 5.0
        return subprocess.CompletedProcess(
            command,
            0,
            stdout="aider 1.2.3\n",
            stderr="",
        )

    result = check_aider_preflight(
        which=lambda _name: "/usr/bin/aider",
        runner=runner,
    )

    assert result.available is True
    assert result.executable_path == "/usr/bin/aider"
    assert result.version_output == "aider 1.2.3"
    assert result.install_guidance == ()
    assert result.diagnostics["version_check_status"] == "ok"
    assert result.diagnostics["stdout_length"] == len("aider 1.2.3\n")


def test_aider_preflight_version_failure_keeps_executable_available() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            2,
            stdout="",
            stderr="usage error\n",
        )

    result = check_aider_preflight(
        which=lambda _name: "/usr/bin/aider",
        runner=runner,
    )

    assert result.available is True
    assert result.executable_path == "/usr/bin/aider"
    assert result.version_output == "usage error"
    assert result.diagnostics["version_check_status"] == "nonzero_exit"
    assert result.diagnostics["return_code"] == 2


def test_aider_preflight_version_timeout_keeps_executable_available() -> None:
    def runner(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=1.0, output="partial")

    result = check_aider_preflight(
        which=lambda _name: "/usr/bin/aider",
        runner=runner,
        version_timeout_seconds=1.0,
    )

    assert result.available is True
    assert result.executable_path == "/usr/bin/aider"
    assert result.version_output is None
    assert result.diagnostics["version_check_status"] == "timeout"
    assert result.diagnostics["stdout_preview"] == "partial"
