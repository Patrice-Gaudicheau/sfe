"""Tests for the CodexCLI-only DEV/Patch output-token benchmark."""

from __future__ import annotations

import contextlib
import csv
import io
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
    CONDITION_FULL,
    CONDITION_SELECTED,
    PATCH_FORMAT_INSTRUCTIONS,
    TOKEN_SOURCE_ESTIMATED,
    TOKEN_SOURCE_MEASURED,
    TOKEN_SOURCE_MISSING,
    CampaignConfig,
    FakeCodexCLIPatchExecutor,
    build_patch_prompt,
    clean_reports,
    classify_token_usage,
    context_token_count,
    create_playground_fixtures,
    get_dev_patch_tasks,
    guard_codexcli_live_provider,
    main,
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

    def test_campaign_config_accepts_executor_provider_when_shared_provider_absent(
        self,
    ) -> None:
        with patch.dict(os.environ, {"SFE_PROVIDER_EXECUTOR": "codexcli"}, clear=True):
            config = CampaignConfig.from_env()

        self.assertEqual(config.provider, "codexcli")

    def test_campaign_config_shared_provider_takes_precedence_over_executor_provider(
        self,
    ) -> None:
        with patch.dict(
            os.environ,
            {
                "SFE_PROVIDER": "openai",
                "SFE_PROVIDER_EXECUTOR": "codexcli",
            },
            clear=True,
        ):
            config = CampaignConfig.from_env()

        self.assertEqual(config.provider, "openai")

    def test_codexcli_only_live_provider_guard_rejects_paid_api_provider(self) -> None:
        with self.assertRaisesRegex(ValueError, "CodexCLI-only"):
            guard_codexcli_live_provider("openai")

    def test_selected_context_prompt_includes_small_hunk_accounting_instruction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_playground_fixtures(root)
            task = get_dev_patch_tasks()[0]
            workspace_root = root / "fixtures" / task.project

            prompt = build_patch_prompt(workspace_root, task, CONDITION_SELECTED)

            self.assertIn("Condition: selected_context_dev_patch", prompt)
            self.assertIn(PATCH_FORMAT_INSTRUCTIONS, prompt)
            self.assertIn("Keep hunks as small as possible", prompt)
            self.assertIn("minimal surrounding context", prompt)
            self.assertIn("one small hunk per localized edit", prompt)
            self.assertIn("hunk header exactly matches", prompt)
            self.assertIn("reduce surrounding context", prompt)
            self.assertIn("do not include prose outside the diff", prompt)

    def test_full_context_prompt_uses_same_safe_patch_format_clarification(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_playground_fixtures(root)
            task = get_dev_patch_tasks()[0]
            workspace_root = root / "fixtures" / task.project

            selected_prompt = build_patch_prompt(workspace_root, task, CONDITION_SELECTED)
            full_prompt = build_patch_prompt(workspace_root, task, CONDITION_FULL)

            self.assertIn("Condition: full_context_dev_patch", full_prompt)
            self.assertIn(PATCH_FORMAT_INSTRUCTIONS, full_prompt)
            self.assertIn(PATCH_FORMAT_INSTRUCTIONS, selected_prompt)
            self.assertEqual(
                selected_prompt.split("Patch format requirements:\n", 1)[1],
                full_prompt.split("Patch format requirements:\n", 1)[1],
            )

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

    def test_medium_fixture_is_created_and_reset_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_playground_fixtures(root)
            target = (
                root / "fixtures" / "medium-php-blog-noise" / "public" / "index.php"
            )
            docs = (
                root / "fixtures" / "medium-php-blog-noise" / "docs"
                / "deployment-checklist.md"
            )
            target.write_text("mutated\n", encoding="utf-8")

            reset_playground_fixtures(root)

            self.assertTrue(target.exists())
            self.assertTrue(docs.exists())
            self.assertIn("$posts = require", target.read_text(encoding="utf-8"))
            self.assertNotEqual(target.read_text(encoding="utf-8"), "mutated\n")

    def test_medium_task_is_included_and_has_meaningful_context_gap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_playground_fixtures(root)
            task = _task_by_id("medium_php_blog_escape")

            selected_tokens = context_token_count(
                root,
                task,
                task.selected_context_files,
            )
            full_tokens = context_token_count(root, task, task.context_files)

            self.assertIn(task.task_id, [item.task_id for item in get_dev_patch_tasks()])
            self.assertEqual(task.project, "medium-php-blog-noise")
            self.assertEqual(
                task.selected_context_files,
                ("content/posts.php", "public/index.php"),
            )
            self.assertGreater(full_tokens - selected_tokens, 3000)
            self.assertGreater(full_tokens, selected_tokens * 5)

    def test_medium_selected_and_full_prompts_can_be_generated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            create_playground_fixtures(root)
            task = _task_by_id("medium_php_blog_escape")
            workspace_root = root / "fixtures" / task.project

            selected_prompt = build_patch_prompt(workspace_root, task, CONDITION_SELECTED)
            full_prompt = build_patch_prompt(workspace_root, task, CONDITION_FULL)

            self.assertIn("FILE content/posts.php", selected_prompt)
            self.assertIn("FILE public/index.php", selected_prompt)
            self.assertNotIn("FILE docs/deployment-checklist.md", selected_prompt)
            self.assertIn("FILE docs/deployment-checklist.md", full_prompt)
            self.assertIn("FILE assets/search.js", full_prompt)
            self.assertGreater(len(full_prompt) - len(selected_prompt), 12000)

    def test_dry_run_can_target_medium_task_without_live_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                main(
                    [
                        "--playground-dir",
                        str(root),
                        "--dry-run",
                        "--task-id",
                        "medium_php_blog_escape",
                    ]
                )

            rendered = output.getvalue()
            self.assertIn("planned_task: medium_php_blog_escape", rendered)
            self.assertNotIn("planned_task: tiny_php_blog_escape", rendered)

    def test_run_campaign_task_id_filter_selects_only_medium_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            report = run_campaign(
                CampaignConfig(
                    playground_dir=Path(tmpdir),
                    task_ids=("medium_php_blog_escape",),
                )
            )

            self.assertTrue(report["metadata"]["dry_run"])
            self.assertEqual(report["metadata"]["task_ids"], ["medium_php_blog_escape"])
            self.assertEqual(report["metadata"]["task_filter"], ["medium_php_blog_escape"])
            self.assertEqual(len(report["tasks"]), 1)
            self.assertEqual(
                {record["task_id"] for record in report["records"]},
                {"medium_php_blog_escape"},
            )

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

    def test_clean_reports_keeps_last_n_report_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = root / "reports"
            old = _make_report_dir(reports, "smoke-20260101T000000Z")
            kept_one = _make_report_dir(reports, "smoke-20260102T000000Z")
            kept_two = _make_report_dir(reports, "smoke-20260103T000000Z")

            result = clean_reports(
                CampaignConfig(playground_dir=root),
                keep_last_reports=2,
            )

            self.assertFalse(old.exists())
            self.assertTrue(kept_one.exists())
            self.assertTrue(kept_two.exists())
            self.assertEqual([path.name for path in result.deleted_dirs], [old.name])
            self.assertEqual(
                [path.name for path in result.kept_dirs],
                [kept_one.name, kept_two.name],
            )

    def test_clean_reports_keep_zero_deletes_all_report_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = root / "reports"
            first = _make_report_dir(reports, "smoke-20260101T000000Z")
            second = _make_report_dir(reports, "smoke-20260102T000000Z")

            result = clean_reports(
                CampaignConfig(playground_dir=root),
                keep_last_reports=0,
            )

            self.assertFalse(first.exists())
            self.assertFalse(second.exists())
            self.assertTrue(reports.exists())
            self.assertEqual(len(result.deleted_dirs), 2)
            self.assertEqual(result.kept_dirs, ())

    def test_no_report_cleanup_occurs_without_explicit_clean_reports_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old = _make_report_dir(root / "reports", "smoke-20260101T000000Z")

            main(["--playground-dir", str(root), "--dry-run", "--max-tasks", "1"])

            self.assertTrue(old.exists())

    def test_clean_reports_dry_run_deletes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = root / "reports"
            old = _make_report_dir(reports, "smoke-20260101T000000Z")
            new = _make_report_dir(reports, "smoke-20260102T000000Z")

            result = clean_reports(
                CampaignConfig(playground_dir=root),
                keep_last_reports=1,
                dry_run=True,
            )

            self.assertTrue(old.exists())
            self.assertTrue(new.exists())
            self.assertEqual([path.name for path in result.deleted_dirs], [old.name])
            self.assertEqual([path.name for path in result.kept_dirs], [new.name])

    def test_clean_reports_missing_reports_directory_exits_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            result = clean_reports(CampaignConfig(playground_dir=root))

            self.assertTrue(result.missing_reports_dir)
            self.assertEqual(result.deleted_dirs, ())
            self.assertFalse((root / "reports").exists())

    def test_clean_reports_rejects_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            with self.assertRaisesRegex(ValueError, "reports path"):
                clean_reports(
                    CampaignConfig(
                        playground_dir=root,
                        reports_base_dir=root / "fixtures",
                    )
                )

    def test_clean_reports_does_not_touch_non_report_files_outside_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            reports = root / "reports"
            old = _make_report_dir(reports, "smoke-20260101T000000Z")
            sentinel = root / "do-not-delete.txt"
            sentinel.write_text("keep\n", encoding="utf-8")
            fixture_file = root / "fixtures" / "fixture.txt"
            fixture_file.parent.mkdir(parents=True)
            fixture_file.write_text("keep fixture\n", encoding="utf-8")
            reports_file = reports / "README.txt"
            reports_file.write_text("not a report dir\n", encoding="utf-8")

            clean_reports(CampaignConfig(playground_dir=root), keep_last_reports=0)

            self.assertFalse(old.exists())
            self.assertTrue(sentinel.exists())
            self.assertTrue(fixture_file.exists())
            self.assertTrue(reports_file.exists())


def _make_report_dir(reports_dir: Path, name: str) -> Path:
    path = reports_dir / name
    path.mkdir(parents=True)
    (path / "summary.md").write_text("# summary\n", encoding="utf-8")
    return path


def _task_by_id(task_id: str):
    return next(task for task in get_dev_patch_tasks() if task.task_id == task_id)


if __name__ == "__main__":
    unittest.main()
