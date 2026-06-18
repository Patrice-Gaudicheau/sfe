"""Tests for dependency-free .env configuration handling."""

from __future__ import annotations

import fnmatch
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import sfe.env as env_module
from sfe.env import load_repo_env


class EnvConfigTests(unittest.TestCase):
    def test_env_loader_loads_simple_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("OPENAI_API_KEY=test-key\nSFE_PROVIDER=openai\n", encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_repo_env(env_path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "test-key")
                self.assertEqual(os.environ["SFE_PROVIDER"], "openai")

        self.assertEqual(
            loaded,
            {"OPENAI_API_KEY": "test-key", "SFE_PROVIDER": "openai"},
        )

    def test_env_loader_does_not_overwrite_existing_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text("OPENAI_API_KEY=file-key\n", encoding="utf-8")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "existing-key"}, clear=True):
                loaded = load_repo_env(env_path)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "existing-key")

        self.assertEqual(loaded, {})

    def test_env_loader_uses_current_working_directory_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            env_path = cwd / ".env"
            env_path.write_text("SFE_PROVIDER=ollama\n", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                with patch.dict(os.environ, {}, clear=True), patch.object(
                    env_module,
                    "DEFAULT_ENV_PATH",
                    cwd / "missing.env",
                ):
                    loaded = load_repo_env()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(loaded, {"SFE_PROVIDER": "ollama"})

    def test_env_loader_falls_back_to_project_env_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fallback_path = Path(tmpdir) / "project.env"
            fallback_path.write_text("SFE_PROVIDER=codexcli\n", encoding="utf-8")
            cwd = Path(tmpdir) / "cwd"
            cwd.mkdir()
            old_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                with patch.dict(os.environ, {}, clear=True), patch.object(
                    env_module,
                    "DEFAULT_ENV_PATH",
                    fallback_path,
                ):
                    loaded = load_repo_env()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(loaded, {"SFE_PROVIDER": "codexcli"})

    def test_env_loader_does_not_print_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            cwd = Path(tmpdir)
            env_path = cwd / ".env"
            env_path.write_text("OPENAI_API_KEY=super-secret-value\n", encoding="utf-8")
            stdout = io.StringIO()
            stderr = io.StringIO()
            old_cwd = Path.cwd()
            try:
                os.chdir(cwd)
                with patch.dict(os.environ, {}, clear=True), redirect_stdout(
                    stdout
                ), redirect_stderr(stderr):
                    loaded = load_repo_env()
            finally:
                os.chdir(old_cwd)

        self.assertEqual(loaded, {"OPENAI_API_KEY": "super-secret-value"})
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_env_loader_ignores_comments_blank_lines_and_invalid_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                "\n# comment\nNOT_A_PAIR\nSFE_OPENAI_ROUTER_MODEL=example-router-model\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_repo_env(env_path)

        self.assertEqual(loaded, {"SFE_OPENAI_ROUTER_MODEL": "example-router-model"})

    def test_env_loader_strips_simple_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"
            env_path.write_text(
                'OPENAI_BASE_URL="https://example.test/v1"\nSFE_EXECUTOR_MODEL=\'model-name\'\n',
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                loaded = load_repo_env(env_path)

        self.assertEqual(loaded["OPENAI_BASE_URL"], "https://example.test/v1")
        self.assertEqual(loaded["SFE_EXECUTOR_MODEL"], "model-name")

    def test_env_example_contains_placeholders_not_obvious_real_secrets(self) -> None:
        env_example = PROJECT_ROOT / ".env.example"
        text = env_example.read_text(encoding="utf-8")

        self.assertIn("Spatial Field Engine - Example configuration", text)
        self.assertIn("choose one LLM provider below", text)
        self.assertIn("Only one SFE_PROVIDER should be active at a time.", text)
        for provider in (
            "openai",
            "anthropic",
            "google",
            "alibaba",
            "codexcli",
            "lemonade",
            "ollama",
        ):
            self.assertIn(f"#SFE_PROVIDER={provider}", text)

        self.assertIn("OPENAI_API_KEY=", text)
        self.assertIn("OPENAI_BASE_URL=https://api.openai.com/v1", text)
        self.assertIn("SFE_OPENAI_ROUTER_MODEL=gpt-5.5", text)
        self.assertIn("SFE_OPENAI_DISCOVERY_MODEL=", text)
        self.assertIn("SFE_OPENAI_EXECUTOR_MODEL=gpt-5.4", text)
        self.assertIn("Aider cannot use CodexCLI as its LLM backend.", text)
        self.assertIn("#SFE_AIDER_PROVIDER=openai", text)
        self.assertIn("#SFE_AIDER_MODEL=gpt-5.4", text)
        self.assertIn("SFE_CODEXCLI_ROUTER_MODEL=gpt-5.5", text)
        self.assertIn("SFE_CODEXCLI_DISCOVERY_MODEL=", text)
        self.assertIn("SFE_CODEXCLI_EXECUTOR_MODEL=gpt-5.4", text)
        self.assertIn("SFE_CODEXCLI_DISCOVERY_EFFORT=", text)
        self.assertIn("ALIBABA_API_KEY=", text)
        self.assertIn(
            "ALIBABA_BASE_URL=https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            text,
        )
        self.assertIn("SFE_ALIBABA_ROUTER_MODEL=qwen3.6-plus", text)
        self.assertIn("SFE_ALIBABA_DISCOVERY_MODEL=", text)
        self.assertIn("SFE_ALIBABA_EXECUTOR_MODEL=qwen3.6-plus", text)
        self.assertIn("SFE_ALIBABA_DISABLE_THINKING=true", text)
        self.assertIn("GOOGLE_API_KEY=", text)
        self.assertIn("SFE_GOOGLE_MODEL=gemini-2.5", text)
        self.assertIn("SFE_GOOGLE_DISCOVERY_MODEL=", text)
        self.assertIn(
            "SFE_GOOGLE_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai",
            text,
        )
        self.assertIn("ANTHROPIC_API_KEY=", text)
        self.assertIn("ANTHROPIC_BASE_URL=https://api.anthropic.com", text)
        self.assertIn("ANTHROPIC_VERSION=2023-06-01", text)
        self.assertIn("SFE_ANTHROPIC_ROUTER_MODEL=claude-sonnet-4-6", text)
        self.assertIn("SFE_ANTHROPIC_DISCOVERY_MODEL=", text)
        self.assertIn("SFE_ANTHROPIC_EXECUTOR_MODEL=claude-haiku-4-5-20251001", text)
        self.assertIn("SFE_ROUTER_MODEL=Qwen3-0.6B-GGUF", text)
        self.assertIn("SFE_LEMONADE_DISCOVERY_MODEL=", text)
        self.assertIn("SFE_EXECUTOR_MODEL=Qwen3.5-35B-A3B-GGUF", text)
        self.assertIn("SFE_OLLAMA_BASE_URL=http://localhost:11434", text)
        self.assertIn("SFE_OLLAMA_MODEL=qwen3.5:4b", text)
        self.assertIn("SFE_OLLAMA_ROUTER_MODEL=", text)
        self.assertIn("SFE_OLLAMA_DISCOVERY_MODEL=", text)
        self.assertIn("SFE_OLLAMA_EXECUTOR_MODEL=", text)
        self.assertIn("SFE_OLLAMA_TIMEOUT_SECONDS=120", text)
        self.assertIn("SFE_OLLAMA_THINK=false", text)
        self.assertIn("SFE_PROVIDER_ROUTER=", text)
        self.assertIn("SFE_PROVIDER_DISCOVERY=", text)
        self.assertIn("SFE_PROVIDER_EXECUTOR=", text)
        self.assertIn("SFE_PATCH_JSON_REPAIR_ENABLED=true", text)
        self.assertIn("SFE_ZONE_ROUTER_MODEL=", text)
        self.assertIn("SFE_PROVIDER_IDLE_TIMEOUT_SECONDS=", text)
        self.assertIn("SFE_PROVIDER_INTERNAL_HEARTBEAT_SECONDS=", text)
        self.assertIn("SFE_PATCH_NORMALIZE_HUNK_COUNTS=", text)
        self.assertIn("SFE_LEMONADE_ROUTER_MODEL=", text)
        self.assertIn("SFE_LEMONADE_EXECUTOR_MODEL=", text)
        self.assertNotIn("SFE_MULTIPASS_PLANNER_MODEL", text)
        self.assertNotRegex(text, r"sk-[A-Za-z0-9_-]{12,}")
        for line in text.splitlines():
            if line.startswith("OPENAI_API_KEY="):
                self.assertEqual(line, "OPENAI_API_KEY=")
            if line.startswith("SFE_OPENAI_DISCOVERY_MODEL="):
                self.assertEqual(line, "SFE_OPENAI_DISCOVERY_MODEL=")
            if line.startswith("SFE_CODEXCLI_DISCOVERY_MODEL="):
                self.assertEqual(line, "SFE_CODEXCLI_DISCOVERY_MODEL=")
            if line.startswith("SFE_CODEXCLI_DISCOVERY_EFFORT="):
                self.assertEqual(line, "SFE_CODEXCLI_DISCOVERY_EFFORT=")
            if line.startswith("ALIBABA_API_KEY="):
                self.assertEqual(line, "ALIBABA_API_KEY=")
            if line.startswith("SFE_ALIBABA_DISCOVERY_MODEL="):
                self.assertEqual(line, "SFE_ALIBABA_DISCOVERY_MODEL=")
            if line.startswith("GOOGLE_API_KEY="):
                self.assertEqual(line, "GOOGLE_API_KEY=")
            if line.startswith("SFE_GOOGLE_DISCOVERY_MODEL="):
                self.assertEqual(line, "SFE_GOOGLE_DISCOVERY_MODEL=")
            if line.startswith("ANTHROPIC_API_KEY="):
                self.assertEqual(line, "ANTHROPIC_API_KEY=")
            if line.startswith("SFE_ANTHROPIC_DISCOVERY_MODEL="):
                self.assertEqual(line, "SFE_ANTHROPIC_DISCOVERY_MODEL=")
            if line.startswith("SFE_LEMONADE_DISCOVERY_MODEL="):
                self.assertEqual(line, "SFE_LEMONADE_DISCOVERY_MODEL=")
            if line.startswith("SFE_OLLAMA_ROUTER_MODEL="):
                self.assertEqual(line, "SFE_OLLAMA_ROUTER_MODEL=")
            if line.startswith("SFE_OLLAMA_DISCOVERY_MODEL="):
                self.assertEqual(line, "SFE_OLLAMA_DISCOVERY_MODEL=")
            if line.startswith("SFE_OLLAMA_EXECUTOR_MODEL="):
                self.assertEqual(line, "SFE_OLLAMA_EXECUTOR_MODEL=")

    def test_gitignore_ignores_env_but_allows_env_example(self) -> None:
        gitignore = PROJECT_ROOT / ".gitignore"
        patterns = [
            line.strip()
            for line in gitignore.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        self.assertTrue(_ignored_by_patterns(".env", patterns))
        self.assertTrue(_ignored_by_patterns(".env.local", patterns))
        self.assertFalse(_ignored_by_patterns(".env.example", patterns))


def _ignored_by_patterns(path: str, patterns: list[str]) -> bool:
    ignored = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        normalized = pattern[1:] if negated else pattern
        if fnmatch.fnmatch(path, normalized):
            ignored = not negated
    return ignored


if __name__ == "__main__":
    unittest.main()
