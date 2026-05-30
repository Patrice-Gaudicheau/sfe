"""Tests for the CodexCLI OpenAI provider adapter."""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.codexcli import (
    CodexCLIProvider,
    build_codex_exec_command,
    parse_codex_jsonl,
)
from sfe.provider_progress import collect_progress_events


class FakeStdin:
    def __init__(self) -> None:
        self.written = ""
        self.closed = False

    def write(self, text: str) -> None:
        self.written += text

    def close(self) -> None:
        self.closed = True


class BrokenPipeStdin(FakeStdin):
    def write(self, text: str) -> None:
        del text
        raise BrokenPipeError("stdin closed")


class FakeStderr:
    def __init__(self, text: str) -> None:
        self.text = text
        self.read_called = False

    def read(self) -> str:
        self.read_called = True
        return self.text


class FakeProcess:
    def __init__(
        self,
        *,
        stdout_lines: list[str],
        stderr_text: str = "",
        returncode: int = 0,
        stdin: FakeStdin | None = None,
    ) -> None:
        self.stdin = stdin or FakeStdin()
        self.stdout = iter(stdout_lines)
        self.stderr = FakeStderr(stderr_text)
        self.returncode = returncode
        self.killed = False
        self.wait_called = False

    def poll(self) -> int:
        return self.returncode

    def wait(self) -> int:
        self.wait_called = True
        return self.returncode

    def kill(self) -> None:
        self.killed = True


class CodexCLIProviderTests(unittest.TestCase):
    def test_build_command_uses_json_model_and_read_only_sandbox(self) -> None:
        command = build_codex_exec_command("gpt-5.5")

        self.assertEqual(
            command,
            [
                "codex",
                "exec",
                "--sandbox",
                "read-only",
                "--json",
                "--model",
                "gpt-5.5",
                "--skip-git-repo-check",
            ],
        )

    def test_parse_jsonl_extracts_visible_answer_thread_and_usage(self) -> None:
        parsed = parse_codex_jsonl(
            "\n".join(
                [
                    '{"type":"thread.started","thread_id":"thread-1"}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}',
                    '{"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":3}}',
                ]
            )
        )

        self.assertEqual(parsed["content"], "Done.")
        self.assertEqual(parsed["thread_id"], "thread-1")
        self.assertEqual(
            parsed["usage"],
            {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
        )

    def test_chat_raises_runtime_error_on_failed_command(self) -> None:
        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=1)
        fake_process = FakeProcess(
            stdout_lines=[],
            stderr_text="missing credentials",
            returncode=2,
        )

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            with self.assertRaisesRegex(RuntimeError, "missing credentials"):
                provider.chat(
                    [{"role": "user", "content": "hello"}],
                    model="gpt-5.5",
                )

    def test_chat_preserves_stderr_when_stdin_pipe_is_closed_early(self) -> None:
        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=1)
        fake_process = FakeProcess(
            stdout_lines=[],
            stderr_text="missing credentials",
            returncode=2,
            stdin=BrokenPipeStdin(),
        )
        events, sink = collect_progress_events()

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            with self.assertRaisesRegex(RuntimeError, "missing credentials"):
                provider.chat(
                    [{"role": "user", "content": "hello"}],
                    model="gpt-5.5",
                    progress_sink=sink,
                )

        self.assertTrue(fake_process.stderr.read_called)
        self.assertTrue(fake_process.wait_called)
        self.assertIn("call_failed", [event.kind for event in events])
        self.assertNotIn("provider_chunk", [event.kind for event in events])

    def test_chat_emits_progress_for_codex_jsonl_stdout(self) -> None:
        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=1)
        fake_process = FakeProcess(
            stdout_lines=[
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n',
                '{"type":"turn.completed","usage":{"input_tokens":7,"output_tokens":3}}\n',
            ],
        )
        events, sink = collect_progress_events()

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            response = provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
                progress_sink=sink,
            )

        self.assertEqual(response["choices"][0]["message"]["content"], "Done.")
        self.assertIn("provider_chunk", [event.kind for event in events])
        chunk_events = [event for event in events if event.kind == "provider_chunk"]
        self.assertTrue(all(event.real_provider_signal for event in chunk_events))


if __name__ == "__main__":
    unittest.main()
