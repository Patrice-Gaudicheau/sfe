"""Tests for the CodexCLI-only DEV/Patch output-token benchmark."""

from __future__ import annotations

import json
import os
import csv
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


class InvalidHunkExecutor:
    provider_name = "codexcli"

    def execute(self, **_: object) -> dict[str, object]:
        return {
            "choices": [{"message": {"content": INVALID_HUNK_DIFF}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
            },
        }


INVALID_HUNK_DIFF = "\n".join(
    [
        "diff --git a/blog/index.php b/blog/index.php",
        "--- a/blog/index.php",
        "+++ b/blog/index.php",
        "@@ -6,8 +6,8 @@",
        " <body>",
        "  <main>",
        "    <?php foreach ($posts as $post): ?>",
        "      <article>",
        "-        <h2><?= $post['title'] ?></h2>",
        "-        <p><?= $post['body'] ?></p>",
        "+        <h2><?= htmlspecialchars($post['title'], ENT_QUOTES, 'UTF-8') ?></h2>",
        "+        <p><?= htmlspecialchars($post['body'], ENT_QUOTES, 'UTF-8') ?></p>",
        "      </article>",
        "    <?php endforeach; ?>",
        "  </main>",
    ]
)


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
            self.assertIn("patch_issue_reason", csv.read_text(encoding="utf-8"))
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
            self.assertIsNone(record["patch_issue_category"])
            self.assertIsNone(record["patch_issue_reason"])
            self.assertIsNone(record["hunk_accounting_diagnostics"])
            self.assertTrue(Path(record["prompt_artifact_path"]).exists())

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
            self.assertEqual(record["patch_issue_category"], "invalid_patch_proposal")
            self.assertEqual(record["patch_issue_reason"], "missing_diff_header")

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

    def test_impossible_hunk_accounting_is_recorded_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    fake_provider=True,
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=InvalidHunkExecutor(),
            )
            record = report["records"][0]

            self.assertEqual(record["error_category"], "invalid_patch_proposal")
            self.assertEqual(record["patch_issue_category"], "invalid_patch_proposal")
            self.assertEqual(record["patch_issue_reason"], "impossible_hunk_accounting")
            self.assertIn("actual_old_new=9/9", record["patch_diagnostic_message"])
            diagnostics = record["hunk_accounting_diagnostics"]
            self.assertEqual(diagnostics["declared_old_count"], 8)
            self.assertEqual(diagnostics["declared_new_count"], 8)
            self.assertEqual(diagnostics["actual_old_side_count"], 9)
            self.assertEqual(diagnostics["actual_new_side_count"], 9)

    def test_jsonl_csv_and_markdown_include_patch_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    fake_provider=True,
                    max_tasks=1,
                    conditions=(CONDITION_SELECTED,),
                ),
                executor=InvalidHunkExecutor(),
            )

            jsonl_path = Path(report["artifacts"]["jsonl"])
            csv_path = Path(report["artifacts"]["csv"])
            md_path = Path(report["artifacts"]["markdown"])
            row = json.loads(jsonl_path.read_text(encoding="utf-8"))
            self.assertEqual(row["patch_issue_reason"], "impossible_hunk_accounting")
            self.assertEqual(
                row["hunk_accounting_diagnostics"]["actual_old_side_count"],
                9,
            )

            with csv_path.open(newline="", encoding="utf-8") as handle:
                csv_row = next(csv.DictReader(handle))
            self.assertEqual(
                csv_row["patch_issue_reason"],
                "impossible_hunk_accounting",
            )
            self.assertIn("actual_old_side_count", csv_row["hunk_accounting_diagnostics"])
            self.assertTrue(Path(csv_row["prompt_artifact_path"]).exists())

            markdown = md_path.read_text(encoding="utf-8")
            self.assertIn("diagnostic", markdown)
            self.assertIn("impossible_hunk_accounting", markdown)


if __name__ == "__main__":
    unittest.main()
