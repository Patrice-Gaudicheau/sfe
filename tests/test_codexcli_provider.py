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
        completed = subprocess.CompletedProcess(
            args=["codex"],
            returncode=2,
            stdout="",
            stderr="missing credentials",
        )

        with patch("providers.codexcli.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "missing credentials"):
                provider.chat(
                    [{"role": "user", "content": "hello"}],
                    model="gpt-5.5",
                )


if __name__ == "__main__":
    unittest.main()
