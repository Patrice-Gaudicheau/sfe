"""CodexCLI-only DEV/Patch output-token benchmark protocol.

The benchmark is intentionally narrow: it creates small programming fixtures,
compares full-context and selected-context DEV patch prompts, and records output
token behavior without changing the production patch pipeline.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.codexcli import (  # noqa: E402
    DEFAULT_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL,
    CodexCLIProvider,
)
from runtime.metrics import estimate_text_tokens, estimated_token_usage  # noqa: E402
from runtime.run_experiment import _extract_response_text  # noqa: E402
from sfe.contracts import approximate_token_count  # noqa: E402
from sfe.env import load_repo_env  # noqa: E402
from sfe.patching import (  # noqa: E402
    PatchIssue,
    PatchSummary,
    apply_patch_to_workspace,
    parse_unified_diff,
    validate_patch_paths,
    validate_patch_targets,
)
from sfe_tui.executors import PATCH_SYSTEM_INSTRUCTION  # noqa: E402


BENCHMARK_TYPE = "codexcli_output_tokens/dev_patch"
PUBLIC_CODEXCLI_PROVIDER = "codexcli"
INTERNAL_CODEXCLI_PROVIDER = "openai-codexcli"
CONDITION_SELECTED = "selected_context_dev_patch"
CONDITION_FULL = "full_context_dev_patch"
CONDITIONS = (CONDITION_SELECTED, CONDITION_FULL)
TOKEN_SOURCE_MEASURED = "measured_provider_usage"
TOKEN_SOURCE_ESTIMATED = "estimated_fallback"
TOKEN_SOURCE_MISSING = "missing"
DEFAULT_PLAYGROUND_DIR = (
    Path.home() / "Projets" / "00_Tests" / "SFE-playground"
    / "codexcli-output-token-campaign"
)
DEFAULT_MAX_LIVE_TASKS = 1
DEFAULT_KEEP_LAST_REPORTS = 5
REPORT_TIMESTAMP_RE = re.compile(r"(\d{8}T\d{6}Z)$")
PATCH_FORMAT_INSTRUCTIONS = (
    "Patch format requirements:\n"
    "- Return only a valid Git-style unified diff; do not include prose outside the diff.\n"
    "- Keep hunks as small as possible and use minimal surrounding context.\n"
    "- Prefer one small hunk per localized edit.\n"
    "- Ensure every hunk header exactly matches the old and new line counts in the hunk body.\n"
    "- For each hunk, old_count must equal context lines plus removed lines.\n"
    "- For each hunk, new_count must equal context lines plus added lines.\n"
    "- Recount the hunk body before writing the hunk header.\n"
    "- If uncertain about line counts, reduce surrounding context rather than inventing a larger hunk."
)
CSV_FIELDS = (
    "run_id",
    "task_id",
    "provider",
    "router_model",
    "executor_model",
    "condition",
    "selected_context_file_count",
    "condition_context_file_count",
    "selected_context_token_count",
    "full_context_token_count",
    "condition_context_token_count",
    "input_tokens",
    "input_token_source",
    "output_tokens",
    "output_token_source",
    "total_tokens",
    "total_token_source",
    "patch_accepted",
    "patch_applied",
    "tests_status",
    "files_modified_count",
    "diff_line_count",
    "output_text_length",
    "prompt_artifact_path",
    "patch_issue_category",
    "patch_issue_reason",
    "patch_issue_path",
    "patch_diagnostic_message",
    "hunk_accounting_diagnostics",
    "retry_count",
    "relaunch_count",
    "error_category",
    "execution_status",
)


@dataclass(frozen=True)
class DevPatchTask:
    task_id: str
    project: str
    instruction: str
    files: dict[str, str]
    context_files: tuple[str, ...]
    selected_context_files: tuple[str, ...]
    patched_files: dict[str, str]
    test_commands: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class CampaignConfig:
    playground_dir: Path = DEFAULT_PLAYGROUND_DIR
    reports_base_dir: Path | None = None
    campaign_name: str = "codexcli-output-token-campaign"
    provider: str = PUBLIC_CODEXCLI_PROVIDER
    router_model: str = DEFAULT_ROUTER_MODEL
    executor_model: str = DEFAULT_EXECUTOR_MODEL
    live: bool = False
    fake_provider: bool = False
    max_tasks: int | None = None
    task_ids: tuple[str, ...] = ()
    conditions: tuple[str, ...] = CONDITIONS
    run_tests: bool = False
    timeout_seconds: float = 300

    @property
    def reports_root(self) -> Path:
        return self.reports_base_dir or (self.playground_dir / "reports")

    @property
    def reports_dir(self) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return self.reports_root / f"{self.campaign_name}-{stamp}"

    @classmethod
    def from_env(
        cls,
        *,
        playground_dir: Path = DEFAULT_PLAYGROUND_DIR,
        reports_base_dir: Path | None = None,
        campaign_name: str = "codexcli-output-token-campaign",
        provider: str | None = None,
        router_model: str | None = None,
        executor_model: str | None = None,
        live: bool = False,
        fake_provider: bool = False,
        max_tasks: int | None = None,
        task_ids: tuple[str, ...] = (),
        conditions: tuple[str, ...] = CONDITIONS,
        run_tests: bool = False,
        timeout_seconds: float = 300,
    ) -> "CampaignConfig":
        resolved_provider = (
            provider
            or os.getenv("SFE_PROVIDER")
            or os.getenv("SFE_PROVIDER_EXECUTOR")
            or PUBLIC_CODEXCLI_PROVIDER
        )
        return cls(
            playground_dir=playground_dir,
            reports_base_dir=reports_base_dir,
            campaign_name=campaign_name,
            provider=normalize_provider(resolved_provider),
            router_model=(
                router_model
                or os.getenv("SFE_CODEXCLI_ROUTER_MODEL")
                or DEFAULT_ROUTER_MODEL
            ),
            executor_model=(
                executor_model
                or os.getenv("SFE_CODEXCLI_EXECUTOR_MODEL")
                or DEFAULT_EXECUTOR_MODEL
            ),
            live=live,
            fake_provider=fake_provider,
            max_tasks=max_tasks,
            task_ids=task_ids,
            conditions=conditions,
            run_tests=run_tests,
            timeout_seconds=timeout_seconds,
        )


class PatchExecutor(Protocol):
    provider_name: str

    def execute(
        self,
        *,
        task: DevPatchTask,
        condition: str,
        workspace_root: Path,
        prompt: str,
        model: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class ReportCleanupResult:
    reports_dir: Path
    keep_last_reports: int
    dry_run: bool
    missing_reports_dir: bool
    deleted_dirs: tuple[Path, ...]
    kept_dirs: tuple[Path, ...]


class LiveCodexCLIPatchExecutor:
    provider_name = PUBLIC_CODEXCLI_PROVIDER

    def execute(
        self,
        *,
        task: DevPatchTask,
        condition: str,
        workspace_root: Path,
        prompt: str,
        model: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        del task, condition
        provider = CodexCLIProvider(
            cwd=workspace_root,
            timeout=timeout_seconds,
            reasoning_effort=(
                os.getenv("SFE_CODEXCLI_EXECUTOR_EFFORT", "").strip()
                or os.getenv("SFE_CODEXCLI_REASONING_EFFORT", "").strip()
                or None
            ),
        )
        return provider.chat(
            [{"role": "user", "content": prompt}],
            model=model,
            max_tokens=12000,
            temperature=0.0,
            system_instruction=PATCH_SYSTEM_INSTRUCTION,
        )


class FakeCodexCLIPatchExecutor:
    provider_name = PUBLIC_CODEXCLI_PROVIDER

    def __init__(
        self,
        *,
        include_usage: bool = True,
        prose_only: bool = False,
        raise_error: bool = False,
    ) -> None:
        self.include_usage = include_usage
        self.prose_only = prose_only
        self.raise_error = raise_error
        self.calls: list[dict[str, str]] = []

    def execute(
        self,
        *,
        task: DevPatchTask,
        condition: str,
        workspace_root: Path,
        prompt: str,
        model: str,
        timeout_seconds: float,
    ) -> dict[str, Any]:
        del timeout_seconds
        self.calls.append({"task_id": task.task_id, "condition": condition, "model": model})
        if self.raise_error:
            raise RuntimeError("fake provider error")
        output = (
            "I would update the target file, but this is prose rather than a diff."
            if self.prose_only
            else build_expected_patch(workspace_root, task)
        )
        response: dict[str, Any] = {
            "choices": [{"message": {"content": output}}],
            "codexcli": {"provider": PUBLIC_CODEXCLI_PROVIDER, "model": model},
        }
        if self.include_usage:
            usage = estimated_token_usage(prompt, output)
            response["usage"] = {
                "prompt_tokens": usage["input_tokens"],
                "completion_tokens": usage["output_tokens"],
                "total_tokens": usage["total_tokens"],
            }
        return response


def main(argv: list[str] | None = None) -> None:
    load_repo_env()
    args = parse_args(argv)
    config = config_from_args(args)
    if args.clean_reports:
        cleanup = clean_reports(
            config,
            keep_last_reports=args.keep_last_reports,
            dry_run=args.clean_reports_dry_run or args.dry_run,
        )
        print_cleanup_result(cleanup)
        return
    if args.reset_fixtures:
        reset_playground_fixtures(config.playground_dir)
        print(f"fixtures_reset: {config.playground_dir}")
        if not args.live and not args.fake_provider and not args.dry_run:
            return
    elif args.create_fixtures:
        create_playground_fixtures(config.playground_dir, reset=False)
        print(f"fixtures_ready: {config.playground_dir}")
        if not args.live and not args.fake_provider and not args.dry_run:
            return

    report = run_campaign(config)
    print_report_paths(report)
    if report["metadata"]["dry_run"]:
        for task in report["tasks"]:
            print(f"planned_task: {task['task_id']} project={task['project']}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the CodexCLI-only DEV/Patch output-token benchmark."
    )
    parser.add_argument("--playground-dir", type=Path, default=DEFAULT_PLAYGROUND_DIR)
    parser.add_argument("--reports-dir", type=Path, help="Base directory for reports.")
    parser.add_argument("--campaign-name", default="codexcli-output-token-campaign")
    parser.add_argument("--create-fixtures", action="store_true")
    parser.add_argument("--reset-fixtures", action="store_true")
    parser.add_argument(
        "--clean-reports",
        action="store_true",
        help="Delete old timestamped benchmark report directories explicitly.",
    )
    parser.add_argument(
        "--keep-last-reports",
        type=int,
        default=DEFAULT_KEEP_LAST_REPORTS,
        help="With --clean-reports, keep the newest N report directories.",
    )
    parser.add_argument(
        "--clean-reports-dry-run",
        action="store_true",
        help="With --clean-reports, print old report directories without deleting.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only; no provider calls.")
    parser.add_argument("--live", action="store_true", help="Allow live CodexCLI calls.")
    parser.add_argument(
        "--fake-provider",
        action="store_true",
        help="Use deterministic fake CodexCLI responses for local validation.",
    )
    parser.add_argument("--provider", default=None)
    parser.add_argument("--router-model")
    parser.add_argument("--executor-model")
    parser.add_argument("--max-tasks", type=int)
    parser.add_argument(
        "--task-id",
        action="append",
        default=None,
        help="Run only the requested benchmark task id. May be repeated.",
    )
    parser.add_argument(
        "--condition",
        choices=("both", *CONDITIONS),
        default="both",
    )
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=300)
    args = parser.parse_args(argv)
    if args.live and args.fake_provider:
        parser.error("--live and --fake-provider are mutually exclusive.")
    if args.max_tasks is not None and args.max_tasks < 1:
        parser.error("--max-tasks must be at least 1.")
    if args.keep_last_reports < 0:
        parser.error("--keep-last-reports must be 0 or greater.")
    if args.clean_reports_dry_run:
        args.clean_reports = True
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than 0.")
    return args


def config_from_args(args: argparse.Namespace) -> CampaignConfig:
    conditions = CONDITIONS if args.condition == "both" else (args.condition,)
    live = bool(args.live)
    fake_provider = bool(args.fake_provider)
    return CampaignConfig.from_env(
        playground_dir=args.playground_dir,
        reports_base_dir=args.reports_dir,
        campaign_name=args.campaign_name,
        provider=args.provider,
        router_model=args.router_model,
        executor_model=args.executor_model,
        live=live,
        fake_provider=fake_provider,
        max_tasks=args.max_tasks,
        task_ids=tuple(args.task_id or ()),
        conditions=conditions,
        run_tests=args.run_tests,
        timeout_seconds=args.timeout_seconds,
    )


def run_campaign(
    config: CampaignConfig,
    *,
    executor: PatchExecutor | None = None,
) -> dict[str, Any]:
    config = normalize_config(config)
    tasks = select_tasks(
        get_dev_patch_tasks(),
        max_tasks=config.max_tasks,
        task_ids=config.task_ids,
    )
    create_playground_fixtures(config.playground_dir, reset=False)
    dry_run = not config.live and not config.fake_provider and executor is None
    if config.live:
        guard_codexcli_live_provider(config.provider)
        print_live_warning(config, tasks)
    reports_dir = config.reports_dir
    records: list[dict[str, Any]] = []
    if dry_run:
        for task in tasks:
            for condition in config.conditions:
                records.append(plan_record(config, task, condition))
    else:
        active_executor = executor or (
            LiveCodexCLIPatchExecutor() if config.live else FakeCodexCLIPatchExecutor()
        )
        for task in tasks:
            for condition in config.conditions:
                records.append(run_task_condition(config, task, condition, active_executor, reports_dir))

    report = build_report(config, tasks, records, dry_run=dry_run, reports_dir=reports_dir)
    write_artifacts(report, reports_dir)
    return report


def normalize_config(config: CampaignConfig) -> CampaignConfig:
    conditions = tuple(config.conditions)
    unknown = [condition for condition in conditions if condition not in CONDITIONS]
    if unknown:
        raise ValueError(f"Unknown benchmark condition: {unknown[0]}")
    max_tasks = config.max_tasks
    if config.live and max_tasks is None:
        max_tasks = DEFAULT_MAX_LIVE_TASKS
    return replace(
        config,
        provider=normalize_provider(config.provider),
        max_tasks=max_tasks,
        task_ids=tuple(config.task_ids),
        conditions=conditions,
    )


def normalize_provider(provider: str) -> str:
    normalized = provider.strip().lower()
    if normalized == INTERNAL_CODEXCLI_PROVIDER:
        return PUBLIC_CODEXCLI_PROVIDER
    return normalized


def guard_codexcli_live_provider(provider: str) -> None:
    if normalize_provider(provider) != PUBLIC_CODEXCLI_PROVIDER:
        raise ValueError(
            "This benchmark is CodexCLI-only. Set SFE_PROVIDER=codexcli, set "
            "SFE_PROVIDER_EXECUTOR=codexcli when SFE_PROVIDER is absent, or pass "
            "--provider codexcli. Live OpenAI API, Anthropic, Google, Alibaba, "
            "Qwen API, DeepSeek API, and other paid API providers are rejected."
        )


def print_live_warning(config: CampaignConfig, tasks: list[DevPatchTask]) -> None:
    print(
        "LIVE CODEXCLI RUN: provider=codexcli only; no paid API provider path is "
        f"allowed. tasks={len(tasks)} conditions={len(config.conditions)} "
        f"router_model={config.router_model} executor_model={config.executor_model}"
    )


def select_tasks(
    tasks: list[DevPatchTask],
    *,
    max_tasks: int | None,
    task_ids: tuple[str, ...] = (),
) -> list[DevPatchTask]:
    selected = tasks
    if task_ids:
        requested = set(task_ids)
        by_id = {task.task_id: task for task in tasks}
        unknown = sorted(requested - set(by_id))
        if unknown:
            raise ValueError(f"Unknown benchmark task id: {unknown[0]}")
        selected = [task for task in tasks if task.task_id in requested]
    return selected[:max_tasks] if max_tasks is not None else selected


def clean_reports(
    config: CampaignConfig,
    *,
    keep_last_reports: int = DEFAULT_KEEP_LAST_REPORTS,
    dry_run: bool = False,
) -> ReportCleanupResult:
    if keep_last_reports < 0:
        raise ValueError("keep_last_reports must be 0 or greater.")
    reports_dir = validate_reports_cleanup_root(config)
    if not reports_dir.exists():
        return ReportCleanupResult(
            reports_dir=reports_dir,
            keep_last_reports=keep_last_reports,
            dry_run=dry_run,
            missing_reports_dir=True,
            deleted_dirs=(),
            kept_dirs=(),
        )
    if not reports_dir.is_dir():
        raise ValueError("reports cleanup path is not a directory.")

    report_dirs = sorted(
        (path for path in reports_dir.iterdir() if path.is_dir()),
        key=report_directory_sort_key,
    )
    kept = tuple(report_dirs[-keep_last_reports:]) if keep_last_reports else ()
    kept_set = set(kept)
    delete_candidates = tuple(path for path in report_dirs if path not in kept_set)
    if not dry_run:
        for path in delete_candidates:
            assert_cleanup_child(reports_dir, path)
            shutil.rmtree(path)
    return ReportCleanupResult(
        reports_dir=reports_dir,
        keep_last_reports=keep_last_reports,
        dry_run=dry_run,
        missing_reports_dir=False,
        deleted_dirs=delete_candidates,
        kept_dirs=kept,
    )


def validate_reports_cleanup_root(config: CampaignConfig) -> Path:
    reports_dir = config.reports_root.expanduser().resolve()
    playground_dir = config.playground_dir.expanduser().resolve()
    if reports_dir.name != "reports":
        raise ValueError("refusing cleanup: reports path must be named 'reports'.")
    if reports_dir == playground_dir:
        raise ValueError("refusing cleanup: reports path is the playground root.")
    if reports_dir == playground_dir / "fixtures":
        raise ValueError("refusing cleanup: reports path is the fixtures directory.")
    if config.reports_base_dir is None:
        expected = (playground_dir / "reports").resolve()
        if reports_dir != expected:
            raise ValueError("refusing cleanup: reports path is not the benchmark reports directory.")
    return reports_dir


def assert_cleanup_child(reports_dir: Path, child: Path) -> None:
    resolved_reports = reports_dir.resolve()
    resolved_child = child.resolve()
    if resolved_child.parent != resolved_reports:
        raise ValueError("refusing cleanup: deletion candidate is not an immediate reports child.")
    if not resolved_child.is_dir():
        raise ValueError("refusing cleanup: deletion candidate is not a directory.")


def report_directory_sort_key(path: Path) -> tuple[str, str]:
    match = REPORT_TIMESTAMP_RE.search(path.name)
    if match is not None:
        return (match.group(1), path.name)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError:
        mtime_ns = 0
    return (f"{mtime_ns:020d}", path.name)


def print_cleanup_result(result: ReportCleanupResult) -> None:
    print(f"reports_dir: {result.reports_dir}")
    print(f"keep_last_reports: {result.keep_last_reports}")
    print(f"cleanup_dry_run: {result.dry_run}")
    if result.missing_reports_dir:
        print("cleanup_status: reports_dir_missing")
        return
    action = "would_delete" if result.dry_run else "deleted"
    if not result.deleted_dirs:
        print(f"cleanup_status: no_report_directories_to_{action}")
    for path in result.deleted_dirs:
        print(f"{action}: {path}")
    for path in result.kept_dirs:
        print(f"kept: {path}")


def reset_playground_fixtures(playground_dir: Path) -> None:
    if playground_dir.exists():
        shutil.rmtree(playground_dir)
    create_playground_fixtures(playground_dir, reset=False)


def create_playground_fixtures(playground_dir: Path, *, reset: bool = False) -> None:
    if reset:
        reset_playground_fixtures(playground_dir)
        return
    projects_dir = playground_dir / "fixtures"
    projects_dir.mkdir(parents=True, exist_ok=True)
    (playground_dir / "reports").mkdir(parents=True, exist_ok=True)
    for task in get_dev_patch_tasks():
        project_dir = projects_dir / task.project
        project_dir.mkdir(parents=True, exist_ok=True)
        for relative_path, content in task.files.items():
            path = project_dir / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(content, encoding="utf-8")
    manifest = {
        "benchmark_type": BENCHMARK_TYPE,
        "fixture_count": len(get_dev_patch_tasks()),
        "tasks": [task.task_id for task in get_dev_patch_tasks()],
    }
    (playground_dir / "fixtures" / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_task_condition(
    config: CampaignConfig,
    task: DevPatchTask,
    condition: str,
    executor: PatchExecutor,
    reports_dir: Path,
) -> dict[str, Any]:
    run_id = f"{task.task_id}-{condition}-{datetime.now(timezone.utc).strftime('%H%M%S%f')}"
    source_project = config.playground_dir / "fixtures" / task.project
    workspace_root = reports_dir / "workspaces" / run_id / task.project
    workspace_root.parent.mkdir(parents=True, exist_ok=True)
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    shutil.copytree(source_project, workspace_root)
    prompt = build_patch_prompt(workspace_root, task, condition)
    prompt_artifact_path = write_prompt_artifact(reports_dir, run_id, prompt)
    output = ""
    response: dict[str, Any] = {}
    error_category: str | None = None
    execution_status = "completed"
    try:
        response = executor.execute(
            task=task,
            condition=condition,
            workspace_root=workspace_root,
            prompt=prompt,
            model=config.executor_model,
            timeout_seconds=config.timeout_seconds,
        )
        output = _extract_response_text(response)
    except TimeoutError:
        execution_status = "provider_error"
        error_category = "timeout"
    except Exception as exc:  # noqa: BLE001
        execution_status = "provider_error"
        error_category = type(exc).__name__

    token_record = classify_token_usage(response, prompt, output)
    patch_record = evaluate_and_apply_patch(
        workspace_root,
        output,
        run_tests=config.run_tests,
        test_commands=task.test_commands,
        prior_error_category=error_category,
    )
    if patch_record["error_category"] and not error_category:
        error_category = str(patch_record["error_category"])
    return {
        **base_record(config, task, condition),
        "run_id": run_id,
        "execution_status": execution_status,
        "workspace_path": str(workspace_root),
        "prompt_artifact_path": prompt_artifact_path,
        "prompt_text_length": len(prompt),
        "output_text_length": len(output),
        "output": output,
        **token_record,
        **patch_record,
        "retry_count": 0,
        "relaunch_count": 0,
        "error_category": error_category,
    }


def plan_record(config: CampaignConfig, task: DevPatchTask, condition: str) -> dict[str, Any]:
    return {
        **base_record(config, task, condition),
        "run_id": f"planned-{task.task_id}-{condition}",
        "execution_status": "planned_dry_run",
        "workspace_path": None,
        "prompt_artifact_path": None,
        "prompt_text_length": None,
        "output_text_length": 0,
        "output": "",
        "input_tokens": None,
        "input_token_source": TOKEN_SOURCE_MISSING,
        "output_tokens": None,
        "output_token_source": TOKEN_SOURCE_MISSING,
        "total_tokens": None,
        "total_token_source": TOKEN_SOURCE_MISSING,
        "patch_accepted": False,
        "patch_applied": False,
        "tests_status": "not_run",
        "tests_detail": "dry_run",
        "files_modified_count": 0,
        "diff_line_count": 0,
        "patch_summary": None,
        **empty_patch_issue_fields(),
        "retry_count": 0,
        "relaunch_count": 0,
        "error_category": None,
    }


def base_record(config: CampaignConfig, task: DevPatchTask, condition: str) -> dict[str, Any]:
    selected_tokens = context_token_count(config.playground_dir, task, task.selected_context_files)
    full_tokens = context_token_count(config.playground_dir, task, task.context_files)
    condition_files = files_for_condition(task, condition)
    return {
        "benchmark_type": BENCHMARK_TYPE,
        "task_id": task.task_id,
        "project": task.project,
        "provider": PUBLIC_CODEXCLI_PROVIDER,
        "router_model": config.router_model,
        "executor_model": config.executor_model,
        "condition": condition,
        "selected_context_file_count": len(task.selected_context_files),
        "full_context_file_count": len(task.context_files),
        "condition_context_file_count": len(condition_files),
        "selected_context_token_count": selected_tokens,
        "full_context_token_count": full_tokens,
        "condition_context_token_count": context_token_count(config.playground_dir, task, condition_files),
        "context_files": list(condition_files),
    }


def context_token_count(playground_dir: Path, task: DevPatchTask, files: tuple[str, ...]) -> int:
    root = playground_dir / "fixtures" / task.project
    total = 0
    for relative_path in files:
        path = root / relative_path
        text = path.read_text(encoding="utf-8") if path.exists() else task.files[relative_path]
        total += approximate_token_count(text)
    return total


def files_for_condition(task: DevPatchTask, condition: str) -> tuple[str, ...]:
    if condition == CONDITION_SELECTED:
        return task.selected_context_files
    if condition == CONDITION_FULL:
        return task.context_files
    raise ValueError(f"Unknown condition: {condition}")


def build_patch_prompt(workspace_root: Path, task: DevPatchTask, condition: str) -> str:
    context_parts = []
    for relative_path in files_for_condition(task, condition):
        text = (workspace_root / relative_path).read_text(encoding="utf-8")
        context_parts.append(f"FILE {relative_path}\n{text}")
    return (
        f"Benchmark: {BENCHMARK_TYPE}\n"
        f"Condition: {condition}\n"
        f"Task id: {task.task_id}\n\n"
        "User task:\n"
        f"{task.instruction}\n\n"
        "Selected workspace context for this condition:\n"
        + "\n\n".join(context_parts)
        + f"\n\n{PATCH_FORMAT_INSTRUCTIONS}"
    )


def write_prompt_artifact(reports_dir: Path, run_id: str, prompt: str) -> str:
    prompt_path = reports_dir / "prompts" / f"{run_id}.txt"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt, encoding="utf-8")
    return str(prompt_path)


def classify_token_usage(
    response: dict[str, Any],
    prompt: str,
    output: str,
) -> dict[str, Any]:
    usage = response.get("usage") if isinstance(response, dict) else None
    usage = usage if isinstance(usage, dict) else {}
    prompt_tokens = optional_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion_tokens = optional_int(
        usage.get("completion_tokens") or usage.get("output_tokens")
    )
    total_tokens = optional_int(usage.get("total_tokens"))
    input_source = TOKEN_SOURCE_MEASURED if prompt_tokens is not None else TOKEN_SOURCE_ESTIMATED
    output_source = (
        TOKEN_SOURCE_MEASURED if completion_tokens is not None else TOKEN_SOURCE_ESTIMATED
    )
    if prompt_tokens is None:
        prompt_tokens = estimate_text_tokens(prompt)
    if completion_tokens is None:
        completion_tokens = estimate_text_tokens(output) if output else None
        if completion_tokens is None:
            output_source = TOKEN_SOURCE_MISSING
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens
        total_source = (
            TOKEN_SOURCE_MEASURED
            if input_source == output_source == TOKEN_SOURCE_MEASURED
            else TOKEN_SOURCE_ESTIMATED
        )
    elif total_tokens is not None:
        total_source = TOKEN_SOURCE_MEASURED
    else:
        total_source = TOKEN_SOURCE_MISSING
    return {
        "input_tokens": prompt_tokens,
        "input_token_source": input_source,
        "output_tokens": completion_tokens,
        "output_token_source": output_source,
        "total_tokens": total_tokens,
        "total_token_source": total_source,
    }


def optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def evaluate_and_apply_patch(
    workspace_root: Path,
    output: str,
    *,
    run_tests: bool,
    test_commands: tuple[tuple[str, ...], ...],
    prior_error_category: str | None,
) -> dict[str, Any]:
    if prior_error_category:
        return {
            "patch_accepted": False,
            "patch_applied": False,
            "tests_status": "not_run",
            "tests_detail": "provider_error",
            "files_modified_count": 0,
            "diff_line_count": len(output.splitlines()),
            "patch_summary": None,
            **empty_patch_issue_fields(),
            "error_category": prior_error_category,
        }
    parsed = parse_unified_diff(output)
    if parsed.patch is None or parsed.summary is None:
        return {
            "patch_accepted": False,
            "patch_applied": False,
            "tests_status": "not_run",
            "tests_detail": "invalid_patch",
            "files_modified_count": 0,
            "diff_line_count": len(output.splitlines()),
            "patch_summary": summary_to_dict(parsed.summary),
            **patch_issue_fields(parsed.issue),
            "error_category": "invalid_patch_proposal",
        }
    guard_issue = validate_patch_paths(workspace_root, parsed.summary.paths)
    if guard_issue is not None:
        return rejected_patch_record(output, parsed.summary, guard_issue)
    validation = validate_patch_targets(workspace_root, parsed.patch)
    if not validation.ok:
        return rejected_patch_record(
            output,
            parsed.summary,
            validation.issue,
            fallback_reason="patch_not_applicable",
        )
    apply_result = apply_patch_to_workspace(workspace_root, validation.patch or parsed.patch)
    if not apply_result.applied:
        reason = apply_result.issue.reason if apply_result.issue is not None else "patch_apply_failed"
        return {
            "patch_accepted": True,
            "patch_applied": False,
            "tests_status": "not_run",
            "tests_detail": reason,
            "files_modified_count": 0,
            "diff_line_count": len(output.splitlines()),
            "patch_summary": summary_to_dict(validation.summary or parsed.summary),
            **patch_issue_fields(apply_result.issue, fallback_reason=reason),
            "error_category": reason,
        }
    tests_status, tests_detail = run_task_tests(workspace_root, test_commands) if run_tests else ("not_run", "disabled")
    summary = apply_result.summary or validation.summary or parsed.summary
    return {
        "patch_accepted": True,
        "patch_applied": True,
        "tests_status": tests_status,
        "tests_detail": tests_detail,
        "files_modified_count": summary.file_count,
        "diff_line_count": len(output.splitlines()),
        "patch_summary": summary_to_dict(summary),
        **empty_patch_issue_fields(),
        "error_category": None if tests_status in ("passed", "not_run") else "tests_failed",
    }


def rejected_patch_record(
    output: str,
    summary: PatchSummary,
    issue: PatchIssue | None,
    *,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    reason = issue.reason if issue is not None else (fallback_reason or "patch_rejected")
    return {
        "patch_accepted": False,
        "patch_applied": False,
        "tests_status": "not_run",
        "tests_detail": reason,
        "files_modified_count": 0,
        "diff_line_count": len(output.splitlines()),
        "patch_summary": summary_to_dict(summary),
        **patch_issue_fields(issue, fallback_reason=fallback_reason),
        "error_category": reason,
    }


def empty_patch_issue_fields() -> dict[str, Any]:
    return {
        "patch_issue_category": None,
        "patch_issue_reason": None,
        "patch_issue_path": None,
        "patch_diagnostic_message": None,
        "hunk_accounting_diagnostics": None,
    }


def patch_issue_fields(
    issue: PatchIssue | None,
    *,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    if issue is None:
        fields = empty_patch_issue_fields()
        if fallback_reason:
            fields["patch_issue_reason"] = fallback_reason
            fields["patch_diagnostic_message"] = fallback_reason
        return fields
    return {
        "patch_issue_category": issue.category,
        "patch_issue_reason": issue.reason,
        "patch_issue_path": issue.path,
        "patch_diagnostic_message": patch_diagnostic_message(issue),
        "hunk_accounting_diagnostics": hunk_accounting_to_dict(
            issue.hunk_accounting
        ),
    }


def patch_diagnostic_message(issue: PatchIssue) -> str:
    parts = [f"{issue.category}: {issue.reason}"]
    if issue.path:
        parts.append(f"path={issue.path}")
    diagnostics = issue.hunk_accounting
    if diagnostics is not None:
        parts.extend(
            [
                f"hunk={diagnostics.hunk_header}",
                (
                    "declared_old_new="
                    f"{diagnostics.declared_old_count}/{diagnostics.declared_new_count}"
                ),
                (
                    "actual_old_new="
                    f"{diagnostics.actual_old_side_count}/"
                    f"{diagnostics.actual_new_side_count}"
                ),
                diagnostics.message,
            ]
        )
    return "; ".join(parts)


def hunk_accounting_to_dict(diagnostics: Any) -> dict[str, Any] | None:
    if diagnostics is None:
        return None
    return {
        "path": diagnostics.path,
        "hunk_header": diagnostics.hunk_header,
        "declared_old_start": diagnostics.declared_old_start,
        "declared_old_count": diagnostics.declared_old_count,
        "declared_new_start": diagnostics.declared_new_start,
        "declared_new_count": diagnostics.declared_new_count,
        "actual_old_side_count": diagnostics.actual_old_side_count,
        "actual_new_side_count": diagnostics.actual_new_side_count,
        "actual_context_line_count": diagnostics.actual_context_line_count,
        "actual_removed_line_count": diagnostics.actual_removed_line_count,
        "actual_added_line_count": diagnostics.actual_added_line_count,
        "looks_like_new_file": diagnostics.looks_like_new_file,
        "old_file_header_is_dev_null": diagnostics.old_file_header_is_dev_null,
        "hunk_body_only_added_lines": diagnostics.hunk_body_only_added_lines,
        "llm_correctable_in_principle": diagnostics.llm_correctable_in_principle,
        "message": diagnostics.message,
    }


def run_task_tests(
    workspace_root: Path,
    test_commands: tuple[tuple[str, ...], ...],
) -> tuple[str, str]:
    if not test_commands:
        return "not_run", "no_test_commands"
    for command in test_commands:
        executable = shutil.which(command[0])
        if executable is None:
            return "not_run", f"missing_executable:{command[0]}"
        result = subprocess.run(
            list(command),
            cwd=workspace_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
            check=False,
        )
        if result.returncode != 0:
            return "failed", f"{' '.join(command)} exited {result.returncode}"
    return "passed", "all_commands_passed"


def summary_to_dict(summary: PatchSummary | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {
        "paths": list(summary.paths),
        "file_count": summary.file_count,
        "hunk_count": summary.hunk_count,
        "lines_added": summary.lines_added,
        "lines_removed": summary.lines_removed,
    }


def build_expected_patch(workspace_root: Path, task: DevPatchTask) -> str:
    parts: list[str] = []
    for relative_path, patched in task.patched_files.items():
        current = (workspace_root / relative_path).read_text(encoding="utf-8")
        diff_lines = list(
            difflib.unified_diff(
                current.splitlines(),
                patched.splitlines(),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )
        parts.append(f"diff --git a/{relative_path} b/{relative_path}")
        parts.extend(diff_lines)
    return "\n".join(parts).strip()


def build_report(
    config: CampaignConfig,
    tasks: list[DevPatchTask],
    records: list[dict[str, Any]],
    *,
    dry_run: bool,
    reports_dir: Path,
) -> dict[str, Any]:
    completed = [record for record in records if record["execution_status"] == "completed"]
    measured_outputs = sum(
        1 for record in records if record["output_token_source"] == TOKEN_SOURCE_MEASURED
    )
    estimated_outputs = sum(
        1 for record in records if record["output_token_source"] == TOKEN_SOURCE_ESTIMATED
    )
    missing_outputs = sum(
        1 for record in records if record["output_token_source"] == TOKEN_SOURCE_MISSING
    )
    return {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "benchmark_type": BENCHMARK_TYPE,
            "provider": PUBLIC_CODEXCLI_PROVIDER,
            "router_model": config.router_model,
            "executor_model": config.executor_model,
            "dry_run": dry_run,
            "fake_provider": config.fake_provider,
            "live": config.live,
            "task_count": len(tasks),
            "task_ids": [task.task_id for task in tasks],
            "task_filter": list(config.task_ids),
            "condition_count": len(config.conditions),
            "run_count": len(records),
            "reports_dir": str(reports_dir),
            "financial_guard": "CodexCLI-only; no paid API provider live calls.",
            "baseline_limitations": (
                "full_context_dev_patch is a controlled prompt baseline using all "
                "fixture context files, not a separate non-SFE provider pipeline."
            ),
        },
        "summary": {
            "completed_runs": len(completed),
            "patch_accepted_runs": sum(1 for record in records if record["patch_accepted"]),
            "patch_applied_runs": sum(1 for record in records if record["patch_applied"]),
            "measured_output_token_runs": measured_outputs,
            "estimated_output_token_runs": estimated_outputs,
            "missing_output_token_runs": missing_outputs,
            "error_runs": sum(1 for record in records if record["error_category"]),
        },
        "tasks": [task_to_dict(task) for task in tasks],
        "records": records,
        "artifacts": {
            "jsonl": str(reports_dir / "runs.jsonl"),
            "csv": str(reports_dir / "runs.csv"),
            "markdown": str(reports_dir / "summary.md"),
        },
    }


def task_to_dict(task: DevPatchTask) -> dict[str, Any]:
    return {
        "task_id": task.task_id,
        "project": task.project,
        "instruction": task.instruction,
        "context_files": list(task.context_files),
        "selected_context_files": list(task.selected_context_files),
        "patched_files": list(task.patched_files.keys()),
        "test_commands": [list(command) for command in task.test_commands],
    }


def write_artifacts(report: dict[str, Any], reports_dir: Path) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(Path(report["artifacts"]["jsonl"]), report["records"])
    write_csv(Path(report["artifacts"]["csv"]), report["records"])
    (reports_dir / "summary.md").write_text(render_markdown(report), encoding="utf-8")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(csv_safe_record(record))


def csv_safe_record(record: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, (dict, list, tuple)):
            safe[key] = json.dumps(value, sort_keys=True)
        else:
            safe[key] = value
    return safe


def render_markdown(report: dict[str, Any]) -> str:
    metadata = report["metadata"]
    summary = report["summary"]
    lines = [
        "# CodexCLI DEV/Patch Output-Token Benchmark",
        "",
        f"- Benchmark type: `{metadata['benchmark_type']}`",
        f"- Provider: `{metadata['provider']}`",
        f"- Router model: `{metadata['router_model']}`",
        f"- Executor model: `{metadata['executor_model']}`",
        f"- Live run: `{metadata['live']}`",
        f"- Fake provider: `{metadata['fake_provider']}`",
        f"- Dry run: `{metadata['dry_run']}`",
        f"- Financial guard: {metadata['financial_guard']}",
        f"- Baseline limitation: {metadata['baseline_limitations']}",
        "",
        "## Summary",
        "",
        f"- Runs: {metadata['run_count']}",
        f"- Completed runs: {summary['completed_runs']}",
        f"- Patch accepted runs: {summary['patch_accepted_runs']}",
        f"- Patch applied runs: {summary['patch_applied_runs']}",
        f"- Measured output-token runs: {summary['measured_output_token_runs']}",
        f"- Estimated output-token runs: {summary['estimated_output_token_runs']}",
        f"- Missing output-token runs: {summary['missing_output_token_runs']}",
        f"- Error runs: {summary['error_runs']}",
        "",
        "## Artifacts",
        "",
        f"- JSONL: `{report['artifacts']['jsonl']}`",
        f"- CSV: `{report['artifacts']['csv']}`",
        f"- Markdown: `{report['artifacts']['markdown']}`",
        "",
        "## Runs",
        "",
        (
            "| task | condition | output tokens | source | patch | tests | "
            "error | diagnostic |"
        ),
        "| --- | --- | ---: | --- | --- | --- | --- | --- |",
    ]
    for record in report["records"]:
        patch = "applied" if record["patch_applied"] else "not_applied"
        lines.append(
            (
                "| {task} | {condition} | {tokens} | {source} | {patch} | "
                "{tests} | {error} | {diagnostic} |"
            ).format(
                task=record["task_id"],
                condition=record["condition"],
                tokens=record["output_tokens"],
                source=record["output_token_source"],
                patch=patch,
                tests=record["tests_status"],
                error=record["error_category"] or "",
                diagnostic=record["patch_issue_reason"] or "",
            )
        )
    return "\n".join(lines) + "\n"


def print_report_paths(report: dict[str, Any]) -> None:
    print(f"reports_dir: {report['metadata']['reports_dir']}")
    print(f"jsonl: {report['artifacts']['jsonl']}")
    print(f"csv: {report['artifacts']['csv']}")
    print(f"markdown: {report['artifacts']['markdown']}")


def get_dev_patch_tasks() -> list[DevPatchTask]:
    return [
        DevPatchTask(
            task_id="tiny_php_blog_escape",
            project="tiny-php-blog",
            instruction=(
                "Patch the tiny PHP blog so post titles and bodies are escaped "
                "with htmlspecialchars before rendering. Keep the change minimal."
            ),
            files={
                "README.md": "# Tiny PHP Blog\n\nStatic PHP blog fixture without a database.\n",
                "blog/posts.php": (
                    "<?php\n"
                    "return [\n"
                    "    ['title' => 'Launch notes', 'body' => 'First public build.'],\n"
                    "    ['title' => 'Roadmap', 'body' => 'Next: forms and search.'],\n"
                    "];\n"
                ),
                "blog/index.php": (
                    "<?php $posts = require __DIR__ . '/posts.php'; ?>\n"
                    "<!doctype html>\n"
                    "<html lang=\"en\">\n"
                    "<head><meta charset=\"utf-8\"><title>Tiny Blog</title></head>\n"
                    "<body>\n"
                    "  <main>\n"
                    "    <?php foreach ($posts as $post): ?>\n"
                    "      <article>\n"
                    "        <h2><?= $post['title'] ?></h2>\n"
                    "        <p><?= $post['body'] ?></p>\n"
                    "      </article>\n"
                    "    <?php endforeach; ?>\n"
                    "  </main>\n"
                    "</body>\n"
                    "</html>\n"
                ),
                "assets/styles.css": "body { font-family: system-ui, sans-serif; }\n",
            },
            context_files=("README.md", "blog/posts.php", "blog/index.php", "assets/styles.css"),
            selected_context_files=("blog/posts.php", "blog/index.php"),
            patched_files={
                "blog/index.php": (
                    "<?php $posts = require __DIR__ . '/posts.php'; ?>\n"
                    "<!doctype html>\n"
                    "<html lang=\"en\">\n"
                    "<head><meta charset=\"utf-8\"><title>Tiny Blog</title></head>\n"
                    "<body>\n"
                    "  <main>\n"
                    "    <?php foreach ($posts as $post): ?>\n"
                    "      <article>\n"
                    "        <h2><?= htmlspecialchars($post['title'], ENT_QUOTES, 'UTF-8') ?></h2>\n"
                    "        <p><?= htmlspecialchars($post['body'], ENT_QUOTES, 'UTF-8') ?></p>\n"
                    "      </article>\n"
                    "    <?php endforeach; ?>\n"
                    "  </main>\n"
                    "</body>\n"
                    "</html>\n"
                )
            },
            test_commands=(("php", "-l", "blog/index.php"),),
        ),
        _medium_php_blog_noise_task(),
        DevPatchTask(
            task_id="php_form_email_validation",
            project="php-form-filters",
            instruction=(
                "Patch the contact form validation so name and email are trimmed "
                "and email uses FILTER_VALIDATE_EMAIL before accepting the form."
            ),
            files={
                "contact.php": (
                    "<?php\n"
                    "$errors = [];\n"
                    "$name = $_POST['name'] ?? '';\n"
                    "$email = $_POST['email'] ?? '';\n"
                    "if ($name === '') {\n"
                    "    $errors[] = 'Name is required';\n"
                    "}\n"
                    "if ($email === '') {\n"
                    "    $errors[] = 'Email is required';\n"
                    "}\n"
                    "$ok = count($errors) === 0;\n"
                    "?>\n"
                ),
                "README.md": "# PHP form filters\n\nSmall validation fixture, no database.\n",
                "templates/form.php": "<form method=\"post\"><input name=\"email\"></form>\n",
            },
            context_files=("README.md", "contact.php", "templates/form.php"),
            selected_context_files=("contact.php",),
            patched_files={
                "contact.php": (
                    "<?php\n"
                    "$errors = [];\n"
                    "$name = trim($_POST['name'] ?? '');\n"
                    "$email = trim($_POST['email'] ?? '');\n"
                    "if ($name === '') {\n"
                    "    $errors[] = 'Name is required';\n"
                    "}\n"
                    "if ($email === '') {\n"
                    "    $errors[] = 'Email is required';\n"
                    "} elseif (filter_var($email, FILTER_VALIDATE_EMAIL) === false) {\n"
                    "    $errors[] = 'Email is invalid';\n"
                    "}\n"
                    "$ok = count($errors) === 0;\n"
                    "?>\n"
                )
            },
            test_commands=(("php", "-l", "contact.php"),),
        ),
        DevPatchTask(
            task_id="local_js_search_trim_case",
            project="local-js-search",
            instruction=(
                "Patch the local JavaScript search so it trims the query and "
                "matches titles case-insensitively."
            ),
            files={
                "index.html": "<input id=\"search\"><ul id=\"results\"></ul><script src=\"app.js\"></script>\n",
                "app.js": (
                    "const items = ['Atlas Guide', 'Billing Export', 'Contact Form'];\n"
                    "const input = document.querySelector('#search');\n"
                    "const results = document.querySelector('#results');\n"
                    "function render(query) {\n"
                    "  const matches = items.filter((item) => item.includes(query));\n"
                    "  results.innerHTML = matches.map((item) => `<li>${item}</li>`).join('');\n"
                    "}\n"
                    "input.addEventListener('input', () => render(input.value));\n"
                ),
                "README.md": "# Local JS search\n\nBrowser-only filtering fixture.\n",
            },
            context_files=("README.md", "index.html", "app.js"),
            selected_context_files=("app.js",),
            patched_files={
                "app.js": (
                    "const items = ['Atlas Guide', 'Billing Export', 'Contact Form'];\n"
                    "const input = document.querySelector('#search');\n"
                    "const results = document.querySelector('#results');\n"
                    "function render(query) {\n"
                    "  const normalizedQuery = query.trim().toLowerCase();\n"
                    "  const matches = items.filter((item) => item.toLowerCase().includes(normalizedQuery));\n"
                    "  results.innerHTML = matches.map((item) => `<li>${item}</li>`).join('');\n"
                    "}\n"
                    "input.addEventListener('input', () => render(input.value));\n"
                )
            },
            test_commands=(("node", "--check", "app.js"),),
        ),
        DevPatchTask(
            task_id="css_responsive_cards",
            project="css-layout-fix",
            instruction=(
                "Patch the card grid CSS so cards wrap responsively instead of "
                "forcing three narrow columns on small screens."
            ),
            files={
                "index.html": "<section class=\"cards\"><article>One</article><article>Two</article></section>\n",
                "styles.css": (
                    ".cards {\n"
                    "  display: grid;\n"
                    "  grid-template-columns: repeat(3, 1fr);\n"
                    "  gap: 16px;\n"
                    "}\n"
                    ".cards article {\n"
                    "  min-width: 0;\n"
                    "}\n"
                ),
                "README.md": "# CSS layout fix\n\nResponsive card grid fixture.\n",
            },
            context_files=("README.md", "index.html", "styles.css"),
            selected_context_files=("styles.css",),
            patched_files={
                "styles.css": (
                    ".cards {\n"
                    "  display: grid;\n"
                    "  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));\n"
                    "  gap: 16px;\n"
                    "}\n"
                    ".cards article {\n"
                    "  min-width: 0;\n"
                    "}\n"
                )
            },
        ),
        DevPatchTask(
            task_id="php_csv_export_fputcsv",
            project="php-csv-export",
            instruction=(
                "Patch the CSV export to use fputcsv instead of joining cells "
                "manually, so commas and quotes are escaped correctly."
            ),
            files={
                "export.php": (
                    "<?php\n"
                    "$rows = [\n"
                    "    ['id', 'customer', 'total'],\n"
                    "    [1, 'Ada, Inc.', '12.50'],\n"
                    "];\n"
                    "foreach ($rows as $row) {\n"
                    "    echo implode(',', $row) . \"\\n\";\n"
                    "}\n"
                ),
                "README.md": "# PHP CSV export\n\nCSV export fixture, no database.\n",
                "orders.csv": "id,customer,total\n1,\"Ada, Inc.\",12.50\n",
            },
            context_files=("README.md", "export.php", "orders.csv"),
            selected_context_files=("export.php", "orders.csv"),
            patched_files={
                "export.php": (
                    "<?php\n"
                    "$rows = [\n"
                    "    ['id', 'customer', 'total'],\n"
                    "    [1, 'Ada, Inc.', '12.50'],\n"
                    "];\n"
                    "$handle = fopen('php://output', 'w');\n"
                    "foreach ($rows as $row) {\n"
                    "    fputcsv($handle, $row);\n"
                    "}\n"
                )
            },
            test_commands=(("php", "-l", "export.php"),),
        ),
    ]


def _medium_php_blog_noise_task() -> DevPatchTask:
    files = {
        "README.md": _medium_markdown_doc("Medium PHP Blog", "project orientation", 12),
        "docs/editorial-guidelines.md": _medium_markdown_doc(
            "Editorial Guidelines",
            "publishing workflow and content tone",
            18,
        ),
        "docs/deployment-checklist.md": _medium_markdown_doc(
            "Deployment Checklist",
            "release validation and server operations",
            16,
        ),
        "docs/legacy-migration.md": _medium_markdown_doc(
            "Legacy Migration Notes",
            "old route mapping and archive behavior",
            18,
        ),
        "docs/theme-notes.md": _medium_markdown_doc(
            "Theme Notes",
            "visual tokens and spacing conventions",
            14,
        ),
        "content/posts.php": _medium_posts_php(),
        "public/index.php": _medium_public_index_php(escaped=False),
        "public/archive.php": _medium_simple_php_page("archive", 12),
        "public/about.php": _medium_simple_php_page("about", 10),
        "includes/format.php": _medium_php_helper("format", 12),
        "includes/navigation.php": _medium_php_helper("navigation", 10),
        "includes/legacy_escape.php": _medium_php_helper("legacy_escape", 8),
        "admin/dashboard.php": _medium_simple_php_page("admin_dashboard", 14),
        "admin/import.php": _medium_simple_php_page("admin_import", 14),
        "assets/styles.css": _medium_css("site", 42),
        "assets/admin.css": _medium_css("admin", 34),
        "assets/theme.css": _medium_css("theme", 34),
        "assets/search.js": _medium_js("search", 36),
        "assets/comments.js": _medium_js("comments", 34),
        "assets/archive.js": _medium_js("archive", 34),
        "data/archive.csv": _medium_csv(36),
        "data/tags.json": _medium_json_tags(28),
        "examples/old-index.php": _medium_simple_php_page("old_index_example", 16),
        "examples/static-preview.html": _medium_html_preview(24),
    }
    return DevPatchTask(
        task_id="medium_php_blog_escape",
        project="medium-php-blog-noise",
        instruction=(
            "Patch the public blog index so post titles and bodies are escaped "
            "with htmlspecialchars before rendering. Keep the change localized "
            "to the public index output."
        ),
        files=files,
        context_files=tuple(files.keys()),
        selected_context_files=("content/posts.php", "public/index.php"),
        patched_files={"public/index.php": _medium_public_index_php(escaped=True)},
        test_commands=(("php", "-l", "public/index.php"),),
    )


def _medium_public_index_php(*, escaped: bool) -> str:
    title_expr = "$post['title']"
    body_expr = "$post['body']"
    if escaped:
        title_expr = "htmlspecialchars($post['title'], ENT_QUOTES, 'UTF-8')"
        body_expr = "htmlspecialchars($post['body'], ENT_QUOTES, 'UTF-8')"
    return (
        "<?php $posts = require __DIR__ . '/../content/posts.php'; ?>\n"
        "<!doctype html>\n"
        "<html lang=\"en\">\n"
        "<head><meta charset=\"utf-8\"><title>Medium Blog</title></head>\n"
        "<body>\n"
        "  <main class=\"post-list\">\n"
        "    <?php foreach ($posts as $post): ?>\n"
        "      <article class=\"post-card\">\n"
        f"        <h2><?= {title_expr} ?></h2>\n"
        f"        <p><?= {body_expr} ?></p>\n"
        "      </article>\n"
        "    <?php endforeach; ?>\n"
        "  </main>\n"
        "</body>\n"
        "</html>\n"
    )


def _medium_posts_php() -> str:
    return (
        "<?php\n"
        "return [\n"
        "    ['title' => 'Launch Notes', 'body' => 'First public build with archive pages.'],\n"
        "    ['title' => 'Roadmap', 'body' => 'Next work covers search, feeds, and themes.'],\n"
        "    ['title' => 'Security Review', 'body' => 'Public output must escape titles and bodies.'],\n"
        "];\n"
    )


def _medium_markdown_doc(title: str, subject: str, sections: int) -> str:
    lines = [f"# {title}", ""]
    for index in range(1, sections + 1):
        lines.extend(
            [
                f"## Section {index}",
                (
                    f"This note documents {subject} for the medium PHP blog fixture. "
                    "It is realistic background for full-context pressure, but it is "
                    "not the public index template that renders post output."
                ),
                (
                    "Operators should preserve existing paths, avoid database work, "
                    "and keep edits localized unless the task explicitly names another file."
                ),
                "",
            ]
        )
    return "\n".join(lines)


def _medium_css(prefix: str, blocks: int) -> str:
    lines = [f"/* {prefix} styles for medium PHP blog fixture */"]
    for index in range(1, blocks + 1):
        lines.extend(
            [
                f".{prefix}-block-{index} {{",
                f"  margin: {index % 5}px {index % 7}px;",
                f"  padding: {8 + (index % 4)}px;",
                "  border: 1px solid #d8dde3;",
                "  color: #1f2933;",
                "}",
            ]
        )
    return "\n".join(lines) + "\n"


def _medium_js(name: str, blocks: int) -> str:
    lines = [f"const {name}State = {{ enabled: true, items: [] }};"]
    for index in range(1, blocks + 1):
        lines.extend(
            [
                f"function {name}Helper{index}(value) {{",
                f"  const label = `{name}-{index}-${{value}}`;",
                "  return label.trim().toLowerCase();",
                "}",
            ]
        )
    lines.append(f"export {{ {name}State }};")
    return "\n".join(lines) + "\n"


def _medium_php_helper(name: str, functions: int) -> str:
    lines = ["<?php", f"// Helper functions for {name}; not used by public/index.php."]
    for index in range(1, functions + 1):
        lines.extend(
            [
                f"function {name}_label_{index}(string $value): string",
                "{",
                f"    return trim($value) . '::{name}-{index}';",
                "}",
                "",
            ]
        )
    return "\n".join(lines)


def _medium_simple_php_page(name: str, paragraphs: int) -> str:
    lines = [
        "<?php",
        f"$pageTitle = '{name}';",
        "?>",
        "<!doctype html>",
        "<html lang=\"en\">",
        "<body>",
        f"<h1><?= $pageTitle ?></h1>",
    ]
    for index in range(1, paragraphs + 1):
        lines.append(
            f"<p>Static {name} paragraph {index} with operational background.</p>"
        )
    lines.extend(["</body>", "</html>"])
    return "\n".join(lines) + "\n"


def _medium_html_preview(blocks: int) -> str:
    lines = ["<!doctype html>", "<html lang=\"en\">", "<body>"]
    for index in range(1, blocks + 1):
        lines.append(f"<section><h2>Preview {index}</h2><p>Archived static copy.</p></section>")
    lines.extend(["</body>", "</html>"])
    return "\n".join(lines) + "\n"


def _medium_csv(rows: int) -> str:
    lines = ["id,title,status"]
    for index in range(1, rows + 1):
        lines.append(f"{index},Archive item {index},published")
    return "\n".join(lines) + "\n"


def _medium_json_tags(count: int) -> str:
    payload = [
        {"id": index, "slug": f"tag-{index}", "label": f"Tag {index}"}
        for index in range(1, count + 1)
    ]
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    main()
