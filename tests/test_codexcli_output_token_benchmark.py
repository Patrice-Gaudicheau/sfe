"""Tests for the CodexCLI-only DEV/Patch output-token benchmark."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime.run_codexcli_output_token_benchmark import (  # noqa: E402
    CONDITION_SELECTED,
    TOKEN_SOURCE_ESTIMATED,
    TOKEN_SOURCE_MEASURED,
    TOKEN_SOURCE_MISSING,
    CampaignConfig,
    FakeCodexCLIPatchExecutor,
    classify_token_usage,
    create_playground_fixtures,
    get_dev_patch_tasks,
    guard_codexcli_live_provider,
    reset_playground_fixtures,
    run_campaign,
)


class ExplodingExecutor:
    provider_name = "codexcli"

    def __init__(self) -> None:
        self.calls = 0

    def execute(self, **_: object) -> dict[str, object]:
        self.calls += 1
        raise AssertionError("executor should not be called")


class CodexCLIOutputTokenBenchmarkTests(unittest.TestCase):
    def test_dry_run_does_not_call_codexcli_executor(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = ExplodingExecutor()
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=None,
            )

            self.assertTrue(report["metadata"]["dry_run"])
            self.assertEqual(executor.calls, 0)
            self.assertEqual(report["records"][0]["execution_status"], "planned_dry_run")

    def test_campaign_config_accepts_router_executor_env_combinations(self) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_PROVIDER": "codexcli",
                "SFE_CODEXCLI_ROUTER_MODEL": "router-env",
                "SFE_CODEXCLI_EXECUTOR_MODEL": "executor-env",
            },
            clear=False,
        ):
            config = CampaignConfig.from_env()

        self.assertEqual(config.provider, "codexcli")
        self.assertEqual(config.router_model, "router-env")
        self.assertEqual(config.executor_model, "executor-env")

    def test_codexcli_only_live_provider_guard_rejects_paid_api_provider(self) -> None:
        with self.assertRaisesRegex(ValueError, "CodexCLI-only"):
            guard_codexcli_live_provider("openai")

    def test_output_token_records_distinguish_measured_estimated_and_missing(self) -> None:
        measured = classify_token_usage(
            {
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                }
            },
            "prompt text",
            "output text",
        )
        estimated = classify_token_usage({}, "prompt text", "output text")
        missing = classify_token_usage({}, "prompt text", "")

        self.assertEqual(measured["output_token_source"], TOKEN_SOURCE_MEASURED)
        self.assertEqual(estimated["output_token_source"], TOKEN_SOURCE_ESTIMATED)
        self.assertEqual(missing["output_token_source"], TOKEN_SOURCE_MISSING)

    def test_result_jsonl_csv_markdown_artifacts_are_produced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    fake_provider=True,
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=FakeCodexCLIPatchExecutor(),
            )

            jsonl = Path(report["artifacts"]["jsonl"])
            csv = Path(report["artifacts"]["csv"])
            markdown = Path(report["artifacts"]["markdown"])
            self.assertTrue(jsonl.exists())
            self.assertTrue(csv.exists())
            self.assertTrue(markdown.exists())
            self.assertEqual(len(jsonl.read_text(encoding="utf-8").splitlines()), 1)
            self.assertIn("output_token_source", csv.read_text(encoding="utf-8"))
            self.assertIn("CodexCLI DEV/Patch", markdown.read_text(encoding="utf-8"))

    def test_playground_fixture_creation_and_reset_work(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_playground_fixtures(root)
            target = root / "fixtures" / "tiny-php-blog" / "blog" / "index.php"
            target.write_text("mutated\n", encoding="utf-8")

            reset_playground_fixtures(root)

            self.assertIn("htmlspecialchars", get_dev_patch_tasks()[0].patched_files["blog/index.php"])
            self.assertIn("$posts = require", target.read_text(encoding="utf-8"))
            self.assertNotEqual(target.read_text(encoding="utf-8"), "mutated\n")

    def test_benchmark_runs_with_fake_provider_without_live_codexcli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            executor = FakeCodexCLIPatchExecutor()
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    fake_provider=True,
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=executor,
            )
            record = report["records"][0]

            self.assertEqual(len(executor.calls), 1)
            self.assertTrue(record["patch_accepted"])
            self.assertTrue(record["patch_applied"])
            self.assertEqual(record["output_token_source"], TOKEN_SOURCE_MEASURED)

    def test_invalid_prose_only_patch_output_is_recorded_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    fake_provider=True,
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=FakeCodexCLIPatchExecutor(prose_only=True),
            )
            record = report["records"][0]

            self.assertFalse(record["patch_accepted"])
            self.assertFalse(record["patch_applied"])
            self.assertEqual(record["error_category"], "invalid_patch_proposal")

    def test_no_worktree_mutation_occurs_on_provider_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_playground_fixtures(root)
            source_file = root / "fixtures" / "tiny-php-blog" / "blog" / "index.php"
            before = source_file.read_text(encoding="utf-8")

            report = run_campaign(
                CampaignConfig(
                    playground_dir=root,
                    fake_provider=True,
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=FakeCodexCLIPatchExecutor(raise_error=True),
            )
            record = report["records"][0]
            workspace_file = Path(record["workspace_path"]) / "blog" / "index.php"

            self.assertEqual(source_file.read_text(encoding="utf-8"), before)
            self.assertEqual(workspace_file.read_text(encoding="utf-8"), before)
            self.assertFalse(record["patch_applied"])
            self.assertEqual(record["execution_status"], "provider_error")

    def test_jsonl_records_are_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    fake_provider=True,
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=FakeCodexCLIPatchExecutor(include_usage=False),
            )

            row = json.loads(Path(report["artifacts"]["jsonl"]).read_text(encoding="utf-8"))
            self.assertEqual(row["output_token_source"], TOKEN_SOURCE_ESTIMATED)
            self.assertEqual(row["provider"], "codexcli")


if __name__ == "__main__":
    unittest.main()
