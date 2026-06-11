"""Codex CLI provider for OpenAI-backed benchmark calls."""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from sfe.provider_progress import ProviderCallSupervisor, ProviderProgressSink


PROVIDER_NAME = "openai-codexcli"
# Environment-dependent example defaults retained for compatibility with
# existing benchmark tests. Model identifiers are configurable through
# SFE_CODEXCLI_ROUTER_MODEL and SFE_CODEXCLI_EXECUTOR_MODEL in CodexCLI runtime
# paths.
# These identifiers may depend on the user's account, provider availability, or
# Codex setup, so public users should explicitly configure their own model IDs.
DEFAULT_ROUTER_MODEL = "gpt-5.4"
DEFAULT_EXECUTOR_MODEL = "gpt-5.4"
DEFAULT_TIMEOUT = 300
DEFAULT_SANDBOX = "read-only"
CODEXCLI_EXECUTABLE_ENV = "SFE_CODEXCLI_EXECUTABLE"


class CodexCLITimeoutError(TimeoutError):
    """Raised when the Codex CLI process exceeds the total wall-clock timeout."""


class CodexCLIProvider:
    """Small chat-like adapter around `codex exec --json`."""

    def __init__(
        self,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        idle_timeout: float | None = None,
        sandbox: str | None = None,
        reasoning_effort: str | None = None,
        executable: str | Path | None = None,
    ) -> None:
        self.cwd = Path(cwd or os.getcwd())
        timeout_value = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.timeout = float(timeout_value)
        if self.timeout <= 0:
            raise ValueError("CodexCLI timeout must be greater than 0.")
        idle_timeout_value = idle_timeout if idle_timeout is not None else timeout
        self.idle_timeout = (
            float(idle_timeout_value) if idle_timeout_value is not None else None
        )
        if self.idle_timeout is not None and self.idle_timeout <= 0:
            raise ValueError("CodexCLI idle timeout must be greater than 0.")
        self.sandbox = sandbox or os.getenv("SFE_CODEXCLI_SANDBOX") or DEFAULT_SANDBOX
        self.reasoning_effort = _clean_env_value(reasoning_effort)
        self.executable = _clean_env_value(str(executable)) if executable else None

    def health(self) -> dict[str, Any]:
        """Return whether the codex executable is available."""
        executable, source = resolve_codex_executable(self.executable)
        return {
            "ok": executable is not None,
            "provider": PROVIDER_NAME,
            "executable": executable or "",
            "executable_source": source,
            "reason": None if executable is not None else "codex_executable_not_found",
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
        progress_sink: ProviderProgressSink | None = None,
        system_instruction: str | None = None,
        idle_timeout_seconds: float | None = None,
        provider_role: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        """Run Codex CLI and normalize JSONL events to a chat-completion shape.

        Codex CLI currently receives max_tokens and temperature as request
        metadata only; the adapter does not add unsupported transport flags.
        """
        prompt = _messages_to_prompt(messages, system_instruction=system_instruction)
        started = time.perf_counter()
        command = build_codex_exec_command(
            model=model,
            sandbox=self.sandbox,
            reasoning_effort=self.reasoning_effort,
            executable=resolve_codex_executable(self.executable)[0] or "codex",
        )
        supervisor = ProviderCallSupervisor(
            provider=PROVIDER_NAME,
            model=model,
            role=provider_role,
            progress_sink=progress_sink,
            idle_timeout_seconds=(
                idle_timeout_seconds
                if idle_timeout_seconds is not None
                else self.idle_timeout
            ),
        )
        supervisor.start(
            {
                "command": command,
                "cwd": str(self.cwd),
                "max_tokens_requested": max_tokens,
                "idle_timeout_seconds": supervisor.idle_timeout_seconds,
            }
        )

        try:
            stdout, stderr, returncode = _run_codex_process(
                command=command,
                cwd=self.cwd,
                prompt=prompt,
                supervisor=supervisor,
                timeout_seconds=max(self.timeout, supervisor.idle_timeout_seconds),
            )
        except Exception as exc:
            supervisor.fail({"error_type": type(exc).__name__})
            raise

        latency_ms = int((time.perf_counter() - started) * 1000)
        if returncode != 0:
            supervisor.fail({"returncode": returncode})
            details = stderr.strip() or stdout.strip()
            raise RuntimeError(f"CodexCLI failed with exit {returncode}: {details}")

        parsed = parse_codex_jsonl(stdout)
        content = parsed["content"]
        usage = parsed["usage"]
        parser_diagnostics = parsed["diagnostics"]
        supervisor.complete({"latency_ms": latency_ms, "returncode": returncode})
        return {
            "choices": [{"message": {"content": content}}],
            "usage": usage,
            "codexcli": {
                "provider": PROVIDER_NAME,
                "model": model,
                "latency_ms": latency_ms,
                "thread_id": parsed["thread_id"],
                "command": command,
                "max_tokens_requested": max_tokens,
                "temperature_requested": temperature,
                "returncode": returncode,
                "stdout_length": len(stdout),
                "stderr_length": len(stderr),
                "stderr_present": bool(stderr),
                "parser_diagnostics": parser_diagnostics,
            },
        }


def _run_codex_process(
    *,
    command: list[str],
    cwd: Path,
    prompt: str,
    supervisor: ProviderCallSupervisor,
    timeout_seconds: float,
    clock: Any = time.monotonic,
) -> tuple[str, str, int]:
    if timeout_seconds <= 0:
        raise ValueError("CodexCLI timeout must be greater than 0.")
    supervisor.emit(
        "request_sent",
        source="codexcli",
        real_provider_signal=False,
        resets_idle_timer=False,
        metadata={"command": command},
    )
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    output_queue: queue.Queue[tuple[str, str | None]] = queue.Queue()
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output_queue.put(("stdout", line))
        output_queue.put(("stdout_done", None))

    def read_stderr() -> None:
        assert process.stderr is not None
        stderr = process.stderr.read()
        if stderr:
            output_queue.put(("stderr", stderr))
        output_queue.put(("stderr_done", None))

    threading.Thread(target=read_stdout, daemon=True).start()
    threading.Thread(target=read_stderr, daemon=True).start()
    if process.stdin is not None:
        try:
            process.stdin.write(prompt)
        except (BrokenPipeError, OSError, ValueError):
            pass
        try:
            process.stdin.close()
        except (BrokenPipeError, OSError, ValueError):
            pass

    stdout_done = False
    stderr_done = False
    deadline = clock() + timeout_seconds
    while not (stdout_done and stderr_done and process.poll() is not None):
        if clock() >= deadline:
            _terminate_process(process)
            raise CodexCLITimeoutError(
                f"CodexCLI exceeded total timeout of {timeout_seconds:g} seconds"
            )
        try:
            stream, value = output_queue.get(timeout=supervisor.internal_heartbeat_seconds)
        except queue.Empty:
            supervisor.emit(
                "internal_wait",
                source="sfe_core",
                real_provider_signal=False,
                resets_idle_timer=False,
                metadata={"provider_call": "codexcli_process"},
            )
            try:
                supervisor.check_idle()
            except Exception:
                _terminate_process(process)
                raise
            continue
        if stream == "stdout" and value is not None:
            stdout_parts.append(value)
            supervisor.emit(
                "provider_chunk",
                source="codexcli_jsonl",
                real_provider_signal=True,
                metadata={"bytes": len(value.encode("utf-8"))},
            )
        elif stream == "stderr" and value is not None:
            stderr_parts.append(value)
        elif stream == "stdout_done":
            stdout_done = True
        elif stream == "stderr_done":
            stderr_done = True

    returncode = process.wait()
    return "".join(stdout_parts), "".join(stderr_parts), returncode


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        process.kill()
    except (OSError, ValueError):
        pass
    try:
        process.wait()
    except (OSError, ValueError):
        pass


def build_codex_exec_command(
    model: str,
    sandbox: str = DEFAULT_SANDBOX,
    reasoning_effort: str | None = None,
    executable: str = "codex",
) -> list[str]:
    """Build the non-interactive Codex command used by the benchmark adapter."""
    command = [
        executable,
        "exec",
        "--sandbox",
        sandbox,
        "--json",
        "--model",
        model,
        "--skip-git-repo-check",
    ]
    effort = _resolve_reasoning_effort(reasoning_effort)
    if effort:
        command.extend(["-c", f'model_reasoning_effort="{effort}"'])
    return command


def build_codex_resume_command(model: str, session_id: str) -> list[str]:
    """Build a Codex exec resume command that reads the resumed prompt from stdin."""
    normalized_session_id = session_id.strip()
    if not normalized_session_id:
        raise ValueError("CodexCLI resume session id must not be empty.")
    command = [
        "codex",
        "exec",
        "resume",
        "--json",
        "--model",
        model,
        "--skip-git-repo-check",
    ]
    reasoning_effort = os.getenv("SFE_CODEXCLI_REASONING_EFFORT", "").strip()
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    command.extend([normalized_session_id, "-"])
    return command


def resolve_codex_executable(
    configured_executable: str | None = None,
) -> tuple[str | None, str]:
    explicit = _clean_env_value(configured_executable) or _clean_env_value(
        os.getenv(CODEXCLI_EXECUTABLE_ENV)
    )
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if explicit_path.is_file() and os.access(explicit_path, os.X_OK):
            return str(explicit_path), "configured"
        resolved = shutil.which(explicit)
        if resolved:
            return resolved, "configured"
        return None, "configured_missing"

    path_executable = shutil.which("codex")
    if path_executable:
        return path_executable, "path"

    for candidate in _codex_executable_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate), _safe_candidate_source(candidate)
    return None, "not_found"


def _codex_executable_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = [
        Path.home() / ".codex" / "bin" / "wsl" / "codex",
    ]
    users_root = Path("/mnt/c/Users")
    if users_root.exists():
        candidates.extend(users_root.glob("*/.codex/bin/wsl/codex"))
    return tuple(candidates)


def _safe_candidate_source(candidate: Path) -> str:
    if _is_relative_to(candidate, Path.home()):
        return "home_codex_wsl"
    if _is_relative_to(candidate, Path("/mnt/c/Users")):
        return "windows_codex_wsl"
    return "candidate"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _resolve_reasoning_effort(reasoning_effort: str | None = None) -> str | None:
    return _clean_env_value(reasoning_effort) or _clean_env_value(
        os.getenv("SFE_CODEXCLI_REASONING_EFFORT")
    )


def _clean_env_value(value: str | None) -> str | None:
    if value is None or value.strip() == "":
        return None
    return value.strip()


def parse_codex_jsonl(stdout: str) -> dict[str, Any]:
    """Extract final visible answer, thread id, and token usage from Codex JSONL."""
    thread_id = None
    content_parts: list[str] = []
    stdout_lines = stdout.splitlines()
    parsed_event_count = 0
    invalid_json_line_count = 0
    event_type_counts: dict[str, int] = {}
    agent_message_count = 0
    usage_present = False
    usage: dict[str, int | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }

    for line in stdout_lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_json_line_count += 1
            continue
        if not isinstance(event, dict):
            parsed_event_count += 1
            event_type_counts["<non_object>"] = (
                event_type_counts.get("<non_object>", 0) + 1
            )
            continue

        parsed_event_count += 1
        event_type = event.get("type")
        event_type_label = str(event_type or "<missing>")
        event_type_counts[event_type_label] = (
            event_type_counts.get(event_type_label, 0) + 1
        )
        if event_type == "thread.started":
            thread_id = event.get("thread_id", thread_id)
        elif event_type == "item.completed":
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agent_message":
                agent_message_count += 1
                text = str(item.get("text") or "").strip()
                if text:
                    content_parts.append(text)
        elif event_type == "turn.completed":
            usage_present = isinstance(event.get("usage"), dict)
            usage = _normalize_usage(event.get("usage"))

    content = "\n".join(content_parts).strip()
    return {
        "content": content,
        "thread_id": thread_id,
        "usage": usage,
        "diagnostics": {
            "stdout_length": len(stdout),
            "jsonl_line_count": len(stdout_lines),
            "parsed_event_count": parsed_event_count,
            "invalid_json_line_count": invalid_json_line_count,
            "event_type_counts": event_type_counts,
            "agent_message_count": agent_message_count,
            "final_content_present": bool(content),
            "thread_id_present": thread_id is not None,
            "usage_present": usage_present,
        },
    }


def _normalize_usage(raw_usage: Any) -> dict[str, int | None]:
    if not isinstance(raw_usage, dict):
        return {"prompt_tokens": None, "completion_tokens": None, "total_tokens": None}

    prompt_tokens = _first_int(raw_usage, ("prompt_tokens", "input_tokens"))
    completion_tokens = _first_int(raw_usage, ("completion_tokens", "output_tokens"))
    total_tokens = _first_int(raw_usage, ("total_tokens",))
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _first_int(data: dict[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return int(value)
    return None


def _messages_to_prompt(
    messages: list[dict[str, str]],
    *,
    system_instruction: str | None = None,
) -> str:
    parts = []
    if system_instruction:
        parts.append(f"SYSTEM:\n{system_instruction}")
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        parts.append(f"{role.upper()}:\n{content}")
    return "\n\n".join(parts).strip()
