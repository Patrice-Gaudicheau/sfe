"""Tests for the CodexCLI OpenAI provider adapter."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.codexcli import (
    CodexCLITimeoutError,
    CodexCLIProvider,
    _run_codex_process,
    build_codex_resume_command,
    build_codex_exec_command,
    parse_codex_jsonl,
    resolve_codex_executable,
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


class FakeNeverExitsProcess(FakeProcess):
    def poll(self) -> int | None:
        return self.returncode if self.killed else None


class TimeoutSupervisor:
    internal_heartbeat_seconds = 0.001

    def __init__(self) -> None:
        self.events: list[str] = []

    def emit(
        self,
        kind: str,
        *,
        source: str,
        real_provider_signal: bool,
        resets_idle_timer: bool | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        del source, real_provider_signal, resets_idle_timer, metadata
        self.events.append(kind)

    def check_idle(self) -> None:
        raise TimeoutError("CodexCLI process stalled")


class NonIdleSupervisor:
    internal_heartbeat_seconds = 0.001

    def __init__(self) -> None:
        self.events: list[str] = []
        self.idle_checks = 0

    def emit(
        self,
        kind: str,
        *,
        source: str,
        real_provider_signal: bool,
        resets_idle_timer: bool | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        del source, real_provider_signal, resets_idle_timer, metadata
        self.events.append(kind)

    def check_idle(self) -> None:
        self.idle_checks += 1


class AdvancingClock:
    def __init__(self, step: float = 0.01) -> None:
        self.current = 0.0
        self.step = step

    def __call__(self) -> float:
        self.current += self.step
        return self.current


class CodexCLIProviderTests(unittest.TestCase):
    def test_build_command_uses_json_model_and_read_only_sandbox(self) -> None:
        with patch.dict(
            "providers.codexcli.os.environ",
            {"SFE_CODEXCLI_REASONING_EFFORT": ""},
        ):
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

    def test_build_command_uses_custom_sandbox_and_reasoning_effort(self) -> None:
        with patch.dict(
            "providers.codexcli.os.environ",
            {"SFE_CODEXCLI_REASONING_EFFORT": "medium"},
        ):
            command = build_codex_exec_command("gpt-5.5", sandbox="workspace-write")

        self.assertEqual(
            command,
            [
                "codex",
                "exec",
                "--sandbox",
                "workspace-write",
                "--json",
                "--model",
                "gpt-5.5",
                "--skip-git-repo-check",
                "-c",
                'model_reasoning_effort="medium"',
            ],
        )

    def test_build_command_explicit_reasoning_effort_overrides_legacy_env(self) -> None:
        with patch.dict(
            "providers.codexcli.os.environ",
            {"SFE_CODEXCLI_REASONING_EFFORT": "high"},
        ):
            command = build_codex_exec_command(
                "gpt-5.5",
                reasoning_effort="low",
            )

        self.assertIn('model_reasoning_effort="low"', command)
        self.assertNotIn('model_reasoning_effort="high"', command)

    def test_build_command_blank_explicit_reasoning_effort_uses_legacy_env(self) -> None:
        with patch.dict(
            "providers.codexcli.os.environ",
            {"SFE_CODEXCLI_REASONING_EFFORT": "medium"},
        ):
            command = build_codex_exec_command(
                "gpt-5.5",
                reasoning_effort=" ",
            )

        self.assertIn('model_reasoning_effort="medium"', command)

    def test_resolve_codex_executable_accepts_configured_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)

            resolved, source = resolve_codex_executable(str(executable))

        self.assertEqual(resolved, str(executable))
        self.assertEqual(source, "configured")

    def test_health_falls_back_to_known_wsl_codex_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            with patch("providers.codexcli.shutil.which", return_value=None), patch(
                "providers.codexcli._codex_executable_candidates",
                return_value=(executable,),
            ):
                health = CodexCLIProvider().health()

        self.assertTrue(health["ok"])
        self.assertEqual(health["executable"], str(executable))
        self.assertEqual(health["reason"], None)

    def test_chat_uses_resolved_codex_executable_for_process_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executable = Path(tmpdir) / "codex"
            executable.write_text("#!/bin/sh\n", encoding="utf-8")
            executable.chmod(0o755)
            provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=1)
            fake_process = FakeProcess(
                stdout_lines=[
                    '{"type":"thread.started","thread_id":"thread-1"}\n',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n',
                ],
            )

            with patch("providers.codexcli.shutil.which", return_value=None), patch(
                "providers.codexcli._codex_executable_candidates",
                return_value=(executable,),
            ), patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
                response = provider.chat(
                    [{"role": "user", "content": "hello"}],
                    model="gpt-5.5",
                )

        self.assertEqual(response["codexcli"]["command"][0], str(executable))

    def test_build_resume_command_reads_prompt_from_stdin(self) -> None:
        with patch.dict(
            "providers.codexcli.os.environ",
            {"SFE_CODEXCLI_REASONING_EFFORT": ""},
        ):
            command = build_codex_resume_command("gpt-5.5", "thread-1")

        self.assertEqual(
            command,
            [
                "codex",
                "exec",
                "resume",
                "--json",
                "--model",
                "gpt-5.5",
                "--skip-git-repo-check",
                "thread-1",
                "-",
            ],
        )

    def test_build_resume_command_uses_reasoning_effort_without_changing_exec_command(
        self,
    ) -> None:
        with patch.dict(
            "providers.codexcli.os.environ",
            {"SFE_CODEXCLI_REASONING_EFFORT": "high"},
        ):
            resume_command = build_codex_resume_command("gpt-5.5", " thread-1 ")
            exec_command = build_codex_exec_command("gpt-5.5")

        self.assertEqual(
            resume_command,
            [
                "codex",
                "exec",
                "resume",
                "--json",
                "--model",
                "gpt-5.5",
                "--skip-git-repo-check",
                "-c",
                'model_reasoning_effort="high"',
                "thread-1",
                "-",
            ],
        )
        self.assertEqual(exec_command[0:3], ["codex", "exec", "--sandbox"])
        self.assertNotIn("resume", exec_command)

    def test_build_resume_command_rejects_empty_session_id(self) -> None:
        with self.assertRaisesRegex(ValueError, "session id"):
            build_codex_resume_command("gpt-5.5", " ")

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

    def test_parse_jsonl_accepts_openai_style_usage_keys(self) -> None:
        parsed = parse_codex_jsonl(
            "\n".join(
                [
                    '{"type":"thread.started","thread_id":"thread-1"}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"First."}}',
                    '{"type":"item.completed","item":{"type":"tool_call","text":"ignored"}}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"Second."}}',
                    '{"type":"turn.completed","usage":{"prompt_tokens":11,"completion_tokens":5,"total_tokens":16}}',
                ]
            )
        )

        self.assertEqual(parsed["content"], "First.\nSecond.")
        self.assertEqual(
            parsed["usage"],
            {"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
        )

    def test_chat_sends_prompt_via_stdin_and_includes_system_instruction(self) -> None:
        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=1)
        fake_stdin = FakeStdin()
        fake_process = FakeProcess(
            stdout_lines=[
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n',
            ],
            stdin=fake_stdin,
        )

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            response = provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
                system_instruction="Follow the SFE contract.",
            )

        self.assertEqual(response["choices"][0]["message"]["content"], "Done.")
        self.assertEqual(
            fake_stdin.written,
            "SYSTEM:\nFollow the SFE contract.\n\nUSER:\nhello",
        )
        self.assertTrue(fake_stdin.closed)

    def test_chat_records_max_tokens_and_temperature_as_metadata_only(self) -> None:
        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=1)
        fake_process = FakeProcess(
            stdout_lines=[
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n',
            ],
        )

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            response = provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
                max_tokens=42,
                temperature=0.7,
            )

        metadata = response["codexcli"]
        self.assertEqual(metadata["max_tokens_requested"], 42)
        self.assertEqual(metadata["temperature_requested"], 0.7)
        self.assertNotIn("42", metadata["command"])
        self.assertNotIn("0.7", metadata["command"])

    def test_chat_emits_provider_reasoning_effort_in_command(self) -> None:
        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=1, reasoning_effort="high")
        fake_process = FakeProcess(
            stdout_lines=[
                '{"type":"thread.started","thread_id":"thread-1"}\n',
                '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n',
            ],
        )

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            response = provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
            )

        self.assertIn(
            'model_reasoning_effort="high"',
            response["codexcli"]["command"],
        )

    def test_chat_wires_timeout_into_supervisor_and_start_metadata(self) -> None:
        created: dict[str, object] = {}

        class SpySupervisor:
            def __init__(self, **kwargs: object) -> None:
                self.idle_timeout_seconds = kwargs["idle_timeout_seconds"]
                created["idle_timeout_seconds"] = self.idle_timeout_seconds

            def start(self, metadata: dict[str, object]) -> None:
                created["start_metadata"] = metadata

            def fail(self, metadata: dict[str, object] | None = None) -> None:
                created["fail_metadata"] = metadata

            def complete(self, metadata: dict[str, object] | None = None) -> None:
                created["complete_metadata"] = metadata

        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=12)
        stdout = (
            '{"type":"thread.started","thread_id":"thread-1"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n'
        )

        with patch("providers.codexcli.ProviderCallSupervisor", SpySupervisor), patch(
            "providers.codexcli._run_codex_process",
            return_value=(stdout, "", 0),
        ):
            response = provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
            )

        self.assertEqual(response["choices"][0]["message"]["content"], "Done.")
        self.assertEqual(created["idle_timeout_seconds"], 12.0)
        self.assertEqual(created["start_metadata"]["idle_timeout_seconds"], 12.0)

    def test_chat_accepts_explicit_idle_timeout_for_supervisor(self) -> None:
        created: dict[str, object] = {}

        class SpySupervisor:
            def __init__(self, **kwargs: object) -> None:
                self.idle_timeout_seconds = kwargs["idle_timeout_seconds"]
                created["idle_timeout_seconds"] = self.idle_timeout_seconds

            def start(self, metadata: dict[str, object]) -> None:
                created["start_metadata"] = metadata

            def fail(self, metadata: dict[str, object] | None = None) -> None:
                created["fail_metadata"] = metadata

            def complete(self, metadata: dict[str, object] | None = None) -> None:
                created["complete_metadata"] = metadata

        provider = CodexCLIProvider(cwd=PROJECT_ROOT, idle_timeout=7)
        stdout = (
            '{"type":"thread.started","thread_id":"thread-1"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n'
        )

        with patch("providers.codexcli.ProviderCallSupervisor", SpySupervisor), patch(
            "providers.codexcli._run_codex_process",
            return_value=(stdout, "", 0),
        ):
            provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
            )

        self.assertEqual(created["idle_timeout_seconds"], 7.0)
        self.assertEqual(created["start_metadata"]["idle_timeout_seconds"], 7.0)

    def test_chat_uses_shared_idle_timeout_when_not_explicit(self) -> None:
        created: dict[str, object] = {}

        class SpySupervisor:
            def __init__(self, **kwargs: object) -> None:
                self.idle_timeout_seconds = 300.0
                created["idle_timeout_seconds_argument"] = kwargs["idle_timeout_seconds"]

            def start(self, metadata: dict[str, object]) -> None:
                created["start_metadata"] = metadata

            def fail(self, metadata: dict[str, object] | None = None) -> None:
                created["fail_metadata"] = metadata

            def complete(self, metadata: dict[str, object] | None = None) -> None:
                created["complete_metadata"] = metadata

        provider = CodexCLIProvider(cwd=PROJECT_ROOT)
        stdout = (
            '{"type":"thread.started","thread_id":"thread-1"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"Done."}}\n'
        )

        with patch("providers.codexcli.ProviderCallSupervisor", SpySupervisor), patch(
            "providers.codexcli._run_codex_process",
            return_value=(stdout, "", 0),
        ):
            provider.chat(
                [{"role": "user", "content": "hello"}],
                model="gpt-5.5",
            )

        self.assertIsNone(created["idle_timeout_seconds_argument"])
        self.assertEqual(created["start_metadata"]["idle_timeout_seconds"], 300.0)

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

    def test_run_codex_process_kills_process_when_idle_supervision_fires(self) -> None:
        fake_process = FakeNeverExitsProcess(stdout_lines=[], returncode=0)
        supervisor = TimeoutSupervisor()

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            with self.assertRaisesRegex(TimeoutError, "stalled"):
                _run_codex_process(
                    command=["codex", "exec", "--json"],
                    cwd=PROJECT_ROOT,
                    prompt="hello",
                    supervisor=supervisor,
                    timeout_seconds=30,
                )

        self.assertTrue(fake_process.killed)
        self.assertIn("internal_wait", supervisor.events)

    def test_run_codex_process_kills_process_when_total_timeout_expires(self) -> None:
        fake_process = FakeNeverExitsProcess(stdout_lines=[], returncode=0)
        supervisor = NonIdleSupervisor()

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process):
            with self.assertRaisesRegex(CodexCLITimeoutError, "total timeout"):
                _run_codex_process(
                    command=["codex", "exec", "--json"],
                    cwd=PROJECT_ROOT,
                    prompt="hello",
                    supervisor=supervisor,
                    timeout_seconds=0.015,
                    clock=AdvancingClock(step=0.01),
                )

        self.assertTrue(fake_process.killed)
        self.assertEqual(supervisor.idle_checks, 0)

    def test_chat_reports_total_timeout_as_clear_provider_error(self) -> None:
        provider = CodexCLIProvider(cwd=PROJECT_ROOT, timeout=0.015, idle_timeout=30)
        fake_process = FakeNeverExitsProcess(stdout_lines=[], returncode=0)
        events, sink = collect_progress_events()

        with patch("providers.codexcli.subprocess.Popen", return_value=fake_process), patch(
            "providers.codexcli.time.monotonic",
            AdvancingClock(step=0.01),
        ):
            with self.assertRaisesRegex(CodexCLITimeoutError, "CodexCLI exceeded total timeout"):
                provider.chat(
                    [{"role": "user", "content": "hello"}],
                    model="gpt-5.5",
                    progress_sink=sink,
                )

        self.assertTrue(fake_process.killed)
        self.assertIn("call_failed", [event.kind for event in events])


if __name__ == "__main__":
    unittest.main()
