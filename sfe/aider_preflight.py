"""Aider executable preflight checks for future filesystem execution."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass


AIDER_INSTALL_GUIDANCE = (
    "sudo apt update",
    "sudo apt install pipx",
    "pipx ensurepath",
    "exec $SHELL -l",
    "pipx install aider-chat",
    "aider --version",
    "which aider",
    "Alternative: python -m pip install aider-install",
    "Alternative: aider-install",
)
DEFAULT_AIDER_EXECUTABLE = "aider"
DEFAULT_VERSION_TIMEOUT_SECONDS = 5.0
MAX_PREVIEW_CHARS = 500


@dataclass(frozen=True)
class AiderPreflightResult:
    available: bool
    executable_path: str | None
    version_output: str | None
    install_guidance: tuple[str, ...]
    diagnostics: dict[str, object]


Runner = Callable[..., subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]


def check_aider_preflight(
    *,
    executable_name: str = DEFAULT_AIDER_EXECUTABLE,
    which: Which | None = None,
    runner: Runner | None = None,
    version_timeout_seconds: float = DEFAULT_VERSION_TIMEOUT_SECONDS,
) -> AiderPreflightResult:
    """Return bounded diagnostics for the external Aider executable."""

    which_func = which or shutil.which
    resolved = which_func(executable_name)
    if not resolved:
        return AiderPreflightResult(
            available=False,
            executable_path=None,
            version_output=None,
            install_guidance=AIDER_INSTALL_GUIDANCE,
            diagnostics={
                "executable_name": executable_name,
                "reason": "aider_executable_not_found",
            },
        )

    command = (resolved, "--version")
    runner_func = runner or subprocess.run
    try:
        completed = runner_func(
            list(command),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=version_timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        return AiderPreflightResult(
            available=True,
            executable_path=resolved,
            version_output=None,
            install_guidance=(),
            diagnostics={
                "executable_name": executable_name,
                "command": list(command),
                "version_check_status": "timeout",
                "timeout_seconds": version_timeout_seconds,
                "stdout_preview": _bounded_preview(exc.stdout),
                "stderr_preview": _bounded_preview(exc.stderr),
            },
        )
    except OSError as exc:
        return AiderPreflightResult(
            available=True,
            executable_path=resolved,
            version_output=None,
            install_guidance=(),
            diagnostics={
                "executable_name": executable_name,
                "command": list(command),
                "version_check_status": "error",
                "error_type": type(exc).__name__,
            },
        )

    version_output = _extract_version_output(completed.stdout, completed.stderr)
    return AiderPreflightResult(
        available=True,
        executable_path=resolved,
        version_output=version_output,
        install_guidance=(),
        diagnostics={
            "executable_name": executable_name,
            "command": list(command),
            "version_check_status": (
                "ok" if completed.returncode == 0 else "nonzero_exit"
            ),
            "return_code": completed.returncode,
            "stdout_length": _safe_len(completed.stdout),
            "stderr_length": _safe_len(completed.stderr),
            "stdout_preview": _bounded_preview(completed.stdout),
            "stderr_preview": _bounded_preview(completed.stderr),
        },
    )


def _extract_version_output(stdout: str | None, stderr: str | None) -> str | None:
    combined = "\n".join(
        part.strip() for part in (stdout, stderr) if isinstance(part, str) and part.strip()
    )
    return _bounded_preview(combined) if combined else None


def _bounded_preview(value: object) -> str | None:
    if value is None:
        return None
    text = _string_from_output(value)
    if not text:
        return ""
    return text if len(text) <= MAX_PREVIEW_CHARS else text[:MAX_PREVIEW_CHARS]


def _string_from_output(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    if isinstance(value, Sequence):
        return "".join(str(item) for item in value)
    return str(value)


def _safe_len(value: object) -> int:
    if value is None:
        return 0
    return len(_string_from_output(value))
