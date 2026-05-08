"""Codex CLI provider for OpenAI-backed benchmark calls."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any


PROVIDER_NAME = "openai-codexcli"
# Environment-dependent example defaults retained for compatibility with the
# existing benchmark tests. Public docs prefer explicit SFE_OPENAI_*_MODEL
# configuration because model availability varies by account and Codex setup.
DEFAULT_ROUTER_MODEL = "gpt-5.4-mini"
DEFAULT_EXECUTOR_MODEL = "gpt-5.5"
DEFAULT_TIMEOUT = 300
DEFAULT_SANDBOX = "read-only"


class CodexCLIProvider:
    """Small chat-like adapter around `codex exec --json`."""

    def __init__(
        self,
        cwd: str | Path | None = None,
        timeout: float | None = None,
        sandbox: str | None = None,
    ) -> None:
        self.cwd = Path(cwd or os.getcwd())
        timeout_value = (
            timeout
            if timeout is not None
            else os.getenv("SFE_CODEXCLI_TIMEOUT") or DEFAULT_TIMEOUT
        )
        self.timeout = float(timeout_value)
        if self.timeout <= 0:
            raise ValueError("CodexCLI timeout must be greater than 0.")
        self.sandbox = sandbox or os.getenv("SFE_CODEXCLI_SANDBOX") or DEFAULT_SANDBOX

    def health(self) -> dict[str, Any]:
        """Return whether the codex executable is available."""
        from shutil import which

        executable = which("codex")
        return {
            "ok": executable is not None,
            "provider": PROVIDER_NAME,
            "executable": executable or "",
        }

    def chat(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
        **_: Any,
    ) -> dict[str, Any]:
        """Run Codex CLI and normalize JSONL events to a chat-completion shape."""
        prompt = _messages_to_prompt(messages)
        started = time.perf_counter()
        command = build_codex_exec_command(model=model, sandbox=self.sandbox)

        try:
            result = subprocess.run(
                command,
                cwd=str(self.cwd),
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"CodexCLI timed out after {self.timeout:g} seconds"
            ) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"CodexCLI failed with exit {result.returncode}: {details}")

        parsed = parse_codex_jsonl(result.stdout)
        content = parsed["content"]
        usage = parsed["usage"]
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
            },
        }


def build_codex_exec_command(model: str, sandbox: str = DEFAULT_SANDBOX) -> list[str]:
    """Build the non-interactive Codex command used by the benchmark adapter."""
    command = [
        "codex",
        "exec",
        "--sandbox",
        sandbox,
        "--json",
        "--model",
        model,
        "--skip-git-repo-check",
    ]
    reasoning_effort = os.getenv("SFE_CODEXCLI_REASONING_EFFORT", "").strip()
    if reasoning_effort:
        command.extend(["-c", f'model_reasoning_effort="{reasoning_effort}"'])
    return command


def parse_codex_jsonl(stdout: str) -> dict[str, Any]:
    """Extract final visible answer, thread id, and token usage from Codex JSONL."""
    thread_id = None
    content_parts: list[str] = []
    usage: dict[str, int | None] = {
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
    }

    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = event.get("thread_id", thread_id)
        elif event_type == "item.completed":
            item = event.get("item", {})
            if isinstance(item, dict) and item.get("type") == "agent_message":
                text = str(item.get("text") or "").strip()
                if text:
                    content_parts.append(text)
        elif event_type == "turn.completed":
            usage = _normalize_usage(event.get("usage"))

    return {
        "content": "\n".join(content_parts).strip(),
        "thread_id": thread_id,
        "usage": usage,
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


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    parts = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = str(message.get("content") or "")
        parts.append(f"{role.upper()}:\n{content}")
    return "\n\n".join(parts).strip()
