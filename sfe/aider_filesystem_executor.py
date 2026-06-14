"""Aider-backed filesystem executor for SFE-controlled worktrees."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path, PureWindowsPath

from sfe.aider_env_bridge import (
    AiderEnvBridgeResult,
    AiderEnvFileError,
    resolve_aider_env_bridge,
    write_temporary_aider_env_file,
)
from sfe.aider_preflight import AiderPreflightResult, check_aider_preflight
from sfe.filesystem_executor import (
    FilesystemExecutionDiagnostics,
    FilesystemExecutionRequest,
    FilesystemExecutionResult,
)


AIDER_EXECUTOR_NAME = "aider"
MAX_OUTPUT_PREVIEW_CHARS = 500
SUBPROCESS_ENV_ALLOWLIST = (
    "HOME",
    "PATH",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "TEMP",
    "TMP",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)


class AiderFilesystemExecutor:
    name = AIDER_EXECUTOR_NAME

    def __init__(
        self,
        *,
        preflight: Callable[[], AiderPreflightResult] | None = None,
        env_bridge: Callable[[], AiderEnvBridgeResult] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.preflight = preflight or check_aider_preflight
        self.env_bridge = env_bridge or resolve_aider_env_bridge
        self.runner = runner or subprocess.run
        self.monotonic = monotonic or time.monotonic

    def execute(
        self,
        request: FilesystemExecutionRequest,
    ) -> FilesystemExecutionResult:
        preflight = self.preflight()
        if not preflight.available or preflight.executable_path is None:
            return _failed_result(
                cwd=request.cwd,
                error_category="aider_missing",
                metadata={
                    "install_guidance": preflight.install_guidance,
                    "preflight_diagnostics": preflight.diagnostics,
                },
            )

        path_issue = _validate_relative_paths(
            (*request.expected_paths, *request.context_paths)
        )
        if path_issue is not None:
            return _failed_result(
                cwd=request.cwd,
                error_category=path_issue,
                metadata={"aider_path": preflight.executable_path},
            )

        bridge = self.env_bridge()
        if not bridge.ok:
            return _failed_result(
                cwd=request.cwd,
                error_category=bridge.error_category or "aider_env_bridge_failed",
                metadata={
                    "aider_path": preflight.executable_path,
                    "bridge_diagnostics": bridge.diagnostics,
                    "missing_variables": bridge.missing_variables,
                },
            )

        prompt = _build_aider_prompt(request)
        try:
            with tempfile.TemporaryDirectory(prefix="sfe-aider-") as temp_dir:
                message_path = Path(temp_dir) / "message.txt"
                message_path.write_text(prompt, encoding="utf-8")
                with write_temporary_aider_env_file(
                    bridge.aider_env,
                    forbidden_roots=_forbidden_env_file_roots(request),
                ) as env_file_path:
                    command = _build_aider_command(
                        aider_path=preflight.executable_path,
                        message_path=message_path,
                        env_file_path=env_file_path,
                        selected_model=bridge.selected_model,
                        selected_weak_model=bridge.selected_weak_model,
                        selected_timeout_seconds=bridge.selected_timeout_seconds,
                        expected_paths=request.expected_paths,
                        context_paths=request.context_paths,
                    )
                    start = self.monotonic()
                    try:
                        completed = self.runner(
                            command,
                            cwd=request.cwd,
                            check=False,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL,
                            text=True,
                            timeout=bridge.selected_timeout_seconds,
                            env=_aider_subprocess_environment(),
                        )
                    except subprocess.TimeoutExpired as exc:
                        elapsed_ms = int((self.monotonic() - start) * 1000)
                        return FilesystemExecutionResult(
                            executor_name=self.name,
                            status="failed",
                            changed_paths=(),
                            diagnostics=FilesystemExecutionDiagnostics(
                                executor_name=self.name,
                                cwd=str(request.cwd),
                                command=_sanitize_command(command),
                                return_code=None,
                                stdout_length=_safe_len(exc.stdout),
                                stderr_length=_safe_len(exc.stderr),
                                stdout_preview=_bounded_preview(exc.stdout),
                                stderr_preview=_bounded_preview(exc.stderr),
                                elapsed_ms=elapsed_ms,
                                metadata={
                                    "aider_path": preflight.executable_path,
                                    "error_type": type(exc).__name__,
                                    "timeout_seconds": bridge.selected_timeout_seconds,
                                    "bridge_diagnostics": bridge.diagnostics,
                                },
                            ),
                            error_category="aider_timeout",
                        )
                    except OSError as exc:
                        elapsed_ms = int((self.monotonic() - start) * 1000)
                        return FilesystemExecutionResult(
                            executor_name=self.name,
                            status="failed",
                            changed_paths=(),
                            diagnostics=FilesystemExecutionDiagnostics(
                                executor_name=self.name,
                                cwd=str(request.cwd),
                                command=_sanitize_command(command),
                                return_code=None,
                                stdout_length=0,
                                stderr_length=0,
                                stdout_preview=None,
                                stderr_preview=None,
                                elapsed_ms=elapsed_ms,
                                metadata={
                                    "aider_path": preflight.executable_path,
                                    "error_type": type(exc).__name__,
                                    "bridge_diagnostics": bridge.diagnostics,
                                },
                            ),
                            error_category="aider_execution_error",
                        )
                    elapsed_ms = int((self.monotonic() - start) * 1000)
        except AiderEnvFileError as exc:
            return _failed_result(
                cwd=request.cwd,
                error_category=exc.error_category,
                metadata={
                    "aider_path": preflight.executable_path,
                    "bridge_diagnostics": bridge.diagnostics,
                },
            )
        except OSError as exc:
            return FilesystemExecutionResult(
                executor_name=self.name,
                status="failed",
                changed_paths=(),
                diagnostics=FilesystemExecutionDiagnostics(
                    executor_name=self.name,
                    cwd=str(request.cwd),
                    command=(),
                    return_code=None,
                    stdout_length=0,
                    stderr_length=0,
                    stdout_preview=None,
                    stderr_preview=None,
                    elapsed_ms=0,
                    metadata={
                        "aider_path": preflight.executable_path,
                        "error_type": type(exc).__name__,
                        "bridge_diagnostics": bridge.diagnostics,
                    },
                ),
                error_category="aider_tempfile_error",
            )

        diagnostics = FilesystemExecutionDiagnostics(
            executor_name=self.name,
            cwd=str(request.cwd),
            command=_sanitize_command(command),
            return_code=completed.returncode,
            stdout_length=_safe_len(completed.stdout),
            stderr_length=_safe_len(completed.stderr),
            stdout_preview=_bounded_preview(completed.stdout),
            stderr_preview=_bounded_preview(completed.stderr),
            elapsed_ms=elapsed_ms,
            metadata={
                "aider_path": preflight.executable_path,
                "version_output": preflight.version_output,
                "bridge_diagnostics": bridge.diagnostics,
            },
        )
        return FilesystemExecutionResult(
            executor_name=self.name,
            status="completed" if completed.returncode == 0 else "failed",
            changed_paths=(),
            diagnostics=diagnostics,
            error_category=None if completed.returncode == 0 else "aider_failed",
            metadata={"aider_path": preflight.executable_path},
        )


def _build_aider_prompt(request: FilesystemExecutionRequest) -> str:
    context_lines = "\n".join(f"- {path}" for path in request.context_paths) or "- none"
    expected_lines = "\n".join(f"- {path}" for path in request.expected_paths) or "- none"
    return "\n".join(
        [
            "You are executing an SFE workspace_write task inside an SFE-controlled Git worktree.",
            "Modify files on disk only inside the current working directory subtree.",
            "Do not write outside the selected destination. Do not edit .git, .sfe, or .sfe-worktrees.",
            "Keep the change focused on the user task.",
            "",
            "User task:",
            request.task,
            "",
            "Expected edit paths:",
            expected_lines,
            "",
            "Selected read-only context paths:",
            context_lines,
            "",
        ]
    )


def _build_aider_command(
    *,
    aider_path: str,
    message_path: Path,
    env_file_path: Path,
    selected_model: str | None,
    selected_weak_model: str | None,
    selected_timeout_seconds: float | None,
    expected_paths: tuple[str, ...],
    context_paths: tuple[str, ...],
) -> list[str]:
    command = [
        aider_path,
        "--message-file",
        str(message_path),
        "--env-file",
        str(env_file_path),
        "--yes-always",
        "--no-pretty",
        "--no-stream",
        "--no-gui",
        "--no-browser",
        "--git",
        "--auto-commits",
        "--no-auto-lint",
        "--no-auto-test",
        "--subtree-only",
    ]
    if selected_model is not None:
        command.extend(("--model", selected_model))
    if selected_weak_model is not None:
        command.extend(("--weak-model", selected_weak_model))
    if selected_timeout_seconds is not None:
        command.extend(("--timeout", _format_timeout(selected_timeout_seconds)))
    for path in expected_paths:
        command.extend(("--file", path))
    expected_path_set = set(expected_paths)
    for path in context_paths:
        if path not in expected_path_set:
            command.extend(("--read", path))
    return command


def _sanitize_command(command: list[str]) -> tuple[str, ...]:
    sanitized: list[str] = []
    redacted_next = None
    skip_next = False
    for item in command:
        if skip_next:
            sanitized.append(redacted_next or "<redacted>")
            skip_next = False
            redacted_next = None
            continue
        sanitized.append(item)
        if item == "--message-file":
            skip_next = True
            redacted_next = "<message-file>"
        elif item == "--env-file":
            skip_next = True
            redacted_next = "<aider-env-file>"
    return tuple(sanitized)


def _validate_relative_paths(paths: tuple[str, ...]) -> str | None:
    for path in paths:
        if not path or path.strip() != path:
            return "invalid_aider_path"
        parsed = Path(path)
        windows = PureWindowsPath(path)
        if (
            parsed.is_absolute()
            or windows.is_absolute()
            or ".." in parsed.parts
            or ".." in windows.parts
        ):
            return "unsafe_aider_path"
        lowered = {part.lower() for part in (*parsed.parts, *windows.parts)}
        if lowered & {".git", ".sfe", ".sfe-worktrees"}:
            return "internal_aider_path"
    return None


def _failed_result(
    *,
    cwd: Path,
    error_category: str,
    metadata: dict[str, object] | None = None,
) -> FilesystemExecutionResult:
    return FilesystemExecutionResult(
        executor_name=AIDER_EXECUTOR_NAME,
        status="failed",
        changed_paths=(),
        diagnostics=FilesystemExecutionDiagnostics(
            executor_name=AIDER_EXECUTOR_NAME,
            cwd=str(cwd),
            command=(),
            return_code=None,
            stdout_length=0,
            stderr_length=0,
            stdout_preview=None,
            stderr_preview=None,
            elapsed_ms=0,
            metadata=metadata or {},
        ),
        error_category=error_category,
        metadata=metadata or {},
    )


def _bounded_preview(value: object) -> str | None:
    if value is None:
        return None
    text = _string_from_output(value)
    return text if len(text) <= MAX_OUTPUT_PREVIEW_CHARS else text[:MAX_OUTPUT_PREVIEW_CHARS]


def _safe_len(value: object) -> int:
    return len(_string_from_output(value)) if value is not None else 0


def _string_from_output(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _format_timeout(value: float) -> str:
    return str(int(value)) if value.is_integer() else str(value)


def _forbidden_env_file_roots(request: FilesystemExecutionRequest) -> tuple[Path, ...]:
    roots = [request.cwd]
    for key in ("source_path", "worktree_path"):
        value = request.metadata.get(key)
        if isinstance(value, str) and value.strip():
            roots.append(Path(value))
    return tuple(roots)


def _aider_subprocess_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key in SUBPROCESS_ENV_ALLOWLIST
    }
