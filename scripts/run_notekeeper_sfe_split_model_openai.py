"""Run the NoteKeeper SFE split-model OpenAI benchmark scenario.

This runner reuses the NoteKeeper SFE benchmark helpers from the single-model
scenario while configuring split OpenAI models and multipass auto mode for the
scenario 30 benchmark.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import MissingOpenAIAPIKeyError, PROVIDER_NAME  # noqa: E402
from runtime.metrics import write_json_report, write_text_report  # noqa: E402
from sfe.discovery_router import create_configured_discovery_router  # noqa: E402
from sfe.env import load_repo_env  # noqa: E402
from sfe.execution_mode_router import create_configured_execution_mode_router  # noqa: E402
from sfe.multipass_planner import create_configured_multipass_planner  # noqa: E402
from sfe.run_pipeline import RUN_STATUS_COMPLETED, RunPipeline, RunRequest  # noqa: E402
from sfe.workspace_isolation import WorkspaceIsolationPolicy  # noqa: E402
from sfe_tui.backends import DirectBackend  # noqa: E402
from sfe_tui.executors import OpenAIReadOnlyExecutor  # noqa: E402


_SINGLE_RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_notekeeper_sfe_single_model_openai.py"
_single_spec = importlib.util.spec_from_file_location(
    "notekeeper_sfe_single_model_runner_shared",
    _SINGLE_RUNNER_PATH,
)
if _single_spec is None or _single_spec.loader is None:
    raise RuntimeError("Unable to load NoteKeeper SFE single-model runner helpers.")
base = importlib.util.module_from_spec(_single_spec)
sys.modules[_single_spec.name] = base
_single_spec.loader.exec_module(base)


DEFAULT_ROUTER_MODEL = "gpt-5.4"
DEFAULT_DISCOVERY_MODEL = "gpt-5.4"
DEFAULT_EXECUTOR_MODEL = "gpt-5.4-mini"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_PATCH_OUTPUT_TOKENS = 30_000
SCENARIO_NAME = "sfe_split_gpt54_router_gpt54mini_executor"
SCENARIO_DESCRIPTION = (
    "SFE split-model run with gpt-5.4 for routing/discovery/planning and "
    "gpt-5.4-mini for execution."
)

NOTEKEEPER_ROOT = PROJECT_ROOT / "examples" / "NoteKeeper"
BRIEF_DIR = NOTEKEEPER_ROOT / "00_project_brief"
SCENARIO_DIR = NOTEKEEPER_ROOT / "30_sfe_split_gpt54_router_gpt54mini_executor"
APP_DIR = SCENARIO_DIR / "app"
RUNS_DIR = SCENARIO_DIR / "runs"
TOKEN_USAGE_PATH = SCENARIO_DIR / "token_usage.json"
REPORT_PATH = SCENARIO_DIR / "report.md"

REQUIRED_APP_FILES = base.REQUIRED_APP_FILES
ALLOWED_WORKSPACE_APP_FILES = base.ALLOWED_WORKSPACE_APP_FILES
EXPECTED_TASKS = base.EXPECTED_TASKS
NoteKeeperSFERunnerError = base.NoteKeeperSFERunnerError
BenchmarkContext = base.BenchmarkContext
TaskInstruction = base.TaskInstruction
ProviderCallRecorder = base.ProviderCallRecorder
RecordingOpenAIProvider = base.RecordingOpenAIProvider


def main() -> int:
    load_repo_env()
    configure_shared_paths()
    args = _parse_args()
    try:
        config = _validate_args(args)
        context = base.load_benchmark_context()
        base.validate_benchmark_layout(context.tasks)
        with tempfile.TemporaryDirectory(prefix="notekeeper-sfe-split-model-") as tmp:
            workspace_root = Path(tmp) / "workspace"
            base.build_controlled_workspace(workspace_root, context)
            base.validate_controlled_workspace(workspace_root)
            if config["dry_run_validate_inputs"]:
                _print_dry_run_success(config, context, workspace_root)
                return 0

            if not os.getenv("OPENAI_API_KEY"):
                raise MissingOpenAIAPIKeyError(
                    "OPENAI_API_KEY is required for the NoteKeeper SFE split-model run."
                )
            run_sfe_scenario(context=context, config=config, workspace_root=workspace_root)
        return 0
    except NoteKeeperSFERunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except MissingOpenAIAPIKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def configure_shared_paths() -> None:
    base.SCENARIO_NAME = SCENARIO_NAME
    base.SCENARIO_DESCRIPTION = SCENARIO_DESCRIPTION
    base.SCENARIO_DIR = SCENARIO_DIR
    base.APP_DIR = APP_DIR
    base.RUNS_DIR = RUNS_DIR
    base.TOKEN_USAGE_PATH = TOKEN_USAGE_PATH
    base.REPORT_PATH = REPORT_PATH


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the NoteKeeper SFE split-model OpenAI benchmark with gpt-5.4 "
            "for router/discovery/planning and gpt-5.4-mini for execution."
        )
    )
    parser.add_argument("--router-model", default=DEFAULT_ROUTER_MODEL)
    parser.add_argument("--discovery-model", default=DEFAULT_DISCOVERY_MODEL)
    parser.add_argument("--executor-model", default=DEFAULT_EXECUTOR_MODEL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--dry-run-validate-inputs",
        action="store_true",
        help="Validate local inputs and controlled workspace construction without API calls.",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> dict[str, Any]:
    router_model = str(args.router_model or "").strip()
    discovery_model = str(args.discovery_model or "").strip()
    executor_model = str(args.executor_model or "").strip()
    if not router_model:
        raise NoteKeeperSFERunnerError("--router-model must not be empty.")
    if not discovery_model:
        raise NoteKeeperSFERunnerError("--discovery-model must not be empty.")
    if not executor_model:
        raise NoteKeeperSFERunnerError("--executor-model must not be empty.")
    if args.timeout <= 0:
        raise NoteKeeperSFERunnerError("--timeout must be greater than 0.")
    return {
        "router_model": router_model,
        "discovery_model": discovery_model,
        "executor_model": executor_model,
        "multipass_planner_model": router_model,
        "timeout": float(args.timeout),
        "dry_run_validate_inputs": bool(args.dry_run_validate_inputs),
    }


def run_sfe_scenario(
    *,
    context: BenchmarkContext,
    config: dict[str, Any],
    workspace_root: Path,
) -> None:
    forced_environ = force_sfe_environment(config)
    recorder = ProviderCallRecorder()
    pipeline = build_sfe_pipeline(config=config, environ=forced_environ, recorder=recorder)
    run_results: list[dict[str, Any]] = []
    failed = False

    for task in context.tasks:
        recorder.current_task_id = task.task_id
        result = execute_sfe_task(
            pipeline=pipeline,
            context=context,
            task=task,
            config=config,
            workspace_root=workspace_root,
            recorder=recorder,
        )
        run_results.append(result)
        if not result["success"]:
            failed = True
            break
        base.commit_controlled_workspace_snapshot(workspace_root, task)

    write_token_usage(run_results, config)
    write_report(run_results, config)
    if failed:
        raise NoteKeeperSFERunnerError(
            "SFE split-model run failed; see task artifacts for diagnostics."
        )
    print("success: true")
    print(f"scenario: {SCENARIO_NAME}")
    print(f"router_model: {config['router_model']}")
    print(f"discovery_model: {config['discovery_model']}")
    print(f"executor_model: {config['executor_model']}")
    print(f"multipass_planner_model: {config['multipass_planner_model']}")
    print("multipass: auto")
    print("generated_files:")
    for path in base._final_generated_file_list():
        print(f"- {path}")


def force_sfe_environment(config: dict[str, Any]) -> dict[str, str]:
    environ = dict(os.environ)
    forced = {
        "SFE_PROVIDER": "openai",
        "SFE_PROVIDER_ROUTER": "openai",
        "SFE_PROVIDER_DISCOVERY": "openai",
        "SFE_PROVIDER_EXECUTOR": "openai",
        "SFE_OPENAI_ROUTER_MODEL": config["router_model"],
        "SFE_OPENAI_DISCOVERY_MODEL": config["discovery_model"],
        "SFE_OPENAI_EXECUTOR_MODEL": config["executor_model"],
        "SFE_WORKSPACE_WRITE_MULTIPASS": "auto",
    }
    os.environ.update(forced)
    environ.update(forced)
    return environ


def build_sfe_pipeline(
    *,
    config: dict[str, Any],
    environ: dict[str, str],
    recorder: ProviderCallRecorder,
) -> RunPipeline:
    timeout = float(config["timeout"])

    def router_provider() -> RecordingOpenAIProvider:
        return RecordingOpenAIProvider(role="router", recorder=recorder, timeout=timeout)

    def discovery_provider() -> RecordingOpenAIProvider:
        return RecordingOpenAIProvider(role="discovery", recorder=recorder, timeout=timeout)

    def executor_provider() -> RecordingOpenAIProvider:
        return RecordingOpenAIProvider(role="executor", recorder=recorder, timeout=timeout)

    def multipass_planner_provider() -> RecordingOpenAIProvider:
        return RecordingOpenAIProvider(
            role="multipass_planner",
            recorder=recorder,
            timeout=timeout,
        )

    executor = OpenAIReadOnlyExecutor(
        provider=executor_provider(),
        model=config["executor_model"],
        provider_name="openai",
        environ=environ,
        max_patch_output_tokens=DEFAULT_MAX_PATCH_OUTPUT_TOKENS,
    )
    return RunPipeline(
        backend=DirectBackend(executor=executor),
        execution_mode_router=create_configured_execution_mode_router(
            environ=environ,
            provider_factories={"openai": router_provider},
        ),
        discovery_router=create_configured_discovery_router(
            environ=environ,
            provider_factories={"openai": discovery_provider},
        ),
        multipass_planner=create_configured_multipass_planner(
            environ=environ,
            provider_factories={"openai": multipass_planner_provider},
        ),
        progress_callback=None,
    )


def execute_sfe_task(
    *,
    pipeline: RunPipeline,
    context: BenchmarkContext,
    task: TaskInstruction,
    config: dict[str, Any],
    workspace_root: Path,
    recorder: ProviderCallRecorder,
) -> dict[str, Any]:
    run_dir = RUNS_DIR / task.task_id
    run_dir.mkdir(parents=True, exist_ok=True)
    task_prompt = build_sfe_task_prompt(context=context, task=task)
    (run_dir / "task.md").write_text(task_prompt, encoding="utf-8")

    progress_events: list[dict[str, Any]] = []

    def progress_callback(event: Any) -> None:
        progress_events.append(base._to_jsonable(event))

    pipeline.progress_callback = progress_callback
    started = time.perf_counter()
    result = pipeline.run(
        RunRequest(
            workspace_root=workspace_root,
            task=task_prompt,
            workspace_policy=WorkspaceIsolationPolicy(allow_dirty_source=False),
        )
    )
    wall_clock_ms = int((time.perf_counter() - started) * 1000)
    provider_calls = recorder.calls_for_task(task.task_id)
    validation_error = base.validate_successful_task_output(workspace_root, result)
    success = result.status == RUN_STATUS_COMPLETED and validation_error is None
    generated_files: list[str] = []
    if success:
        base.copy_workspace_app_to_scenario(workspace_root)
        generated_files = [base._rel(APP_DIR / filename) for filename in REQUIRED_APP_FILES]

    if result.discovery_result is not None:
        write_json_report(run_dir / "discovery_result.json", base.discovery_result_summary(result.discovery_result))
    if result.dry_run_result is not None:
        write_json_report(run_dir / "selected_context.json", base.selected_context_summary(result.dry_run_result))
    if result.patch_result is not None and result.patch_result.answer is not None:
        (run_dir / "patch_response.txt").write_text(result.patch_result.answer, encoding="utf-8")
    else:
        (run_dir / "patch_response.txt").write_text("", encoding="utf-8")
    if result.multi_pass_summary is not None:
        write_json_report(run_dir / "multipass_summary.json", base._to_jsonable(result.multi_pass_summary))
    (run_dir / "changed_files.txt").write_text(
        "\n".join(result.changed_files or result.promoted_files)
        + ("\n" if result.changed_files or result.promoted_files else ""),
        encoding="utf-8",
    )
    write_json_report(run_dir / "progress_events.json", progress_events)
    write_json_report(run_dir / "provider_calls.json", {"calls": provider_calls})

    role_usage = aggregate_provider_calls_by_role(provider_calls)
    run_record = {
        "task_id": task.task_id,
        "task_title": task.title,
        "provider": PROVIDER_NAME,
        "models": model_record(config),
        "input_tokens": base._sum_optional(call.get("input_tokens") for call in provider_calls),
        "cached_input_tokens": base._sum_optional(call.get("cached_input_tokens") for call in provider_calls),
        "output_tokens": base._sum_optional(call.get("output_tokens") for call in provider_calls),
        "total_estimated_cost": None,
        "currency": None,
        "latency_or_wall_clock_duration": base._sum_optional(call.get("latency_ms") for call in provider_calls),
        "wall_clock_duration_ms": wall_clock_ms,
        "success": success,
        "generated_or_modified_files": generated_files,
        "manual_verification_notes": None,
        "validation_error": validation_error,
        "sfe_status": result.status,
        "sfe_issue": base._issue_summary(result.issue),
        "multipass_mode": "auto",
        "multipass_forced_auto": True,
        "provider_call_count": len(provider_calls),
        "provider_calls_by_role": role_usage,
    }
    write_json_report(run_dir / "run_result.json", base.run_result_summary(result, run_record))
    return run_record


def build_sfe_task_prompt(*, context: BenchmarkContext, task: TaskInstruction) -> str:
    del context
    return (
        "# NoteKeeper SFE split-model benchmark task\n\n"
        "Use the SFE-selected workspace context. The controlled workspace contains "
        "only the benchmark brief under `brief/`, task metadata under `tasks/`, "
        "and the current generated app under `app/`.\n\n"
        "This scenario uses split OpenAI models: router/discovery/multipass planning "
        "use the stronger router model, while patch generation uses the executor model. "
        "Multipass is intentionally set to auto.\n\n"
        "You are implementing the NoteKeeper static browser app. Edit only these "
        "workspace files:\n\n"
        "- `app/index.html`\n"
        "- `app/styles.css`\n"
        "- `app/app.js`\n"
        "- `app/README.md`\n\n"
        "Do not create package files, server code, dependency manifests, external "
        "assets, screenshots, logs, or files outside `app/`. The final app must "
        "run by opening `index.html` directly after the runner copies the app "
        "files out of `app/`.\n\n"
        "Consult these benchmark documents from selected context when available:\n\n"
        "- `brief/prompt.md`\n"
        "- `brief/acceptance_criteria.md`\n"
        "- `brief/task_sequence.md`\n"
        f"- `tasks/{task.task_id}.md`\n\n"
        "## Current task\n\n"
        f"{task.heading}\n\n{task.body}\n"
    )


def model_record(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "primary": config["router_model"],
        "router": config["router_model"],
        "discovery": config["discovery_model"],
        "executor": config["executor_model"],
        "multipass_planner": config["multipass_planner_model"],
        "reviewer": None,
    }


def aggregate_provider_calls_by_role(calls: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for call in calls:
        role = str(call.get("role") or "unknown")
        bucket = aggregated.setdefault(
            role,
            {
                "calls": 0,
                "models": [],
                "input_tokens": None,
                "cached_input_tokens": None,
                "output_tokens": None,
                "latency_ms": None,
                "success_count": 0,
                "failure_count": 0,
            },
        )
        bucket["calls"] += 1
        model = call.get("model")
        if model is not None and model not in bucket["models"]:
            bucket["models"].append(model)
        for source_key, target_key in (
            ("input_tokens", "input_tokens"),
            ("cached_input_tokens", "cached_input_tokens"),
            ("output_tokens", "output_tokens"),
            ("latency_ms", "latency_ms"),
        ):
            value = call.get(source_key)
            if value is not None:
                bucket[target_key] = int(value) + int(bucket[target_key] or 0)
        if call.get("success"):
            bucket["success_count"] += 1
        else:
            bucket["failure_count"] += 1
    return aggregated


def write_token_usage(run_results: list[dict[str, Any]], config: dict[str, Any]) -> None:
    runs = []
    for result in run_results:
        runs.append(
            {
                "task_id": result["task_id"],
                "provider": result["provider"],
                "models": result["models"],
                "input_tokens": result["input_tokens"],
                "cached_input_tokens": result["cached_input_tokens"],
                "output_tokens": result["output_tokens"],
                "total_estimated_cost": None,
                "currency": None,
                "latency_or_wall_clock_duration": result["latency_or_wall_clock_duration"],
                "success": result["success"],
                "generated_or_modified_files": result["generated_or_modified_files"],
                "manual_verification_notes": result["manual_verification_notes"],
                "validation_error": result["validation_error"],
                "sfe_status": result["sfe_status"],
                "provider_call_count": result["provider_call_count"],
                "provider_calls_by_role": result["provider_calls_by_role"],
            }
        )
    write_json_report(
        TOKEN_USAGE_PATH,
        {
            "scenario": SCENARIO_NAME,
            "description": SCENARIO_DESCRIPTION,
            "runs": runs,
            "totals": {
                "input_tokens": base._sum_optional(result["input_tokens"] for result in run_results),
                "cached_input_tokens": base._sum_optional(
                    result["cached_input_tokens"] for result in run_results
                ),
                "output_tokens": base._sum_optional(result["output_tokens"] for result in run_results),
                "total_estimated_cost": None,
                "currency": None,
                "latency_or_wall_clock_duration": base._sum_optional(
                    result["latency_or_wall_clock_duration"] for result in run_results
                ),
            },
            "configuration": {
                "router_model": config["router_model"],
                "discovery_model": config["discovery_model"],
                "executor_model": config["executor_model"],
                "multipass_planner_model": config["multipass_planner_model"],
                "multipass": "auto",
            },
        },
    )


def write_report(run_results: list[dict[str, Any]], config: dict[str, Any]) -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_success = all(result["success"] for result in run_results)
    lines = [
        "# SFE split-model gpt-5.4 router / gpt-5.4-mini executor report",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "## Scenario",
        "",
        "- Workflow: SFE split-model run.",
        f"- Provider: `{PROVIDER_NAME}`.",
        f"- Router model: `{config['router_model']}`.",
        f"- Discovery model: `{config['discovery_model']}`.",
        f"- Multipass planner model: `{config['multipass_planner_model']}`.",
        f"- Executor model: `{config['executor_model']}`.",
        "- Multipass: `auto`.",
        "- Workspace: temporary controlled workspace containing only benchmark brief, task metadata, and current scenario app files.",
        "- Project brief: `../00_project_brief/prompt.md`.",
        "- Task sequence: `../00_project_brief/task_sequence.md`.",
        "",
        "## Result",
        "",
        f"- Success: `{str(all_success).lower()}`.",
        "- Total estimated cost: `null`.",
        "- Manual verification: not performed by this runner.",
        "",
        "## Task Runs",
        "",
        "| Task | Success | Provider calls | Input tokens | Cached input tokens | Output tokens | Latency ms | Error |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for result in run_results:
        error = result["validation_error"] or (result["sfe_issue"] or {}).get("reason") or ""
        lines.append(
            f"| `{result['task_id']}` | `{str(result['success']).lower()}` | "
            f"{result['provider_call_count']} | "
            f"{base._format_optional(result['input_tokens'])} | "
            f"{base._format_optional(result['cached_input_tokens'])} | "
            f"{base._format_optional(result['output_tokens'])} | "
            f"{base._format_optional(result['latency_or_wall_clock_duration'])} | "
            f"{base._markdown_cell(str(error))} |"
        )
    lines.extend(
        [
            "",
            "## Model Routing",
            "",
            "Multipass planning is created through `create_configured_multipass_planner()` with the OpenAI router provider factory and `SFE_OPENAI_ROUTER_MODEL`, so planner calls use the router model unless the SFE internals change.",
            "",
            "## Generated Files",
            "",
            *(f"- `{path}`" for path in base._final_generated_file_list()),
            "",
            "## Notes",
            "",
            "Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, optional multipass summaries, and run metadata are stored under `runs/<task>/`.",
        ]
    )
    write_text_report(REPORT_PATH, "\n".join(lines) + "\n")


def _print_dry_run_success(
    config: dict[str, Any],
    context: BenchmarkContext,
    workspace_root: Path,
) -> None:
    print("success: true")
    print("mode: dry-run-validate-inputs")
    print(f"scenario: {SCENARIO_NAME}")
    print(f"router_model: {config['router_model']}")
    print(f"discovery_model: {config['discovery_model']}")
    print(f"executor_model: {config['executor_model']}")
    print(f"multipass_planner_model: {config['multipass_planner_model']}")
    print(f"task_count: {len(context.tasks)}")
    print(f"required_app_files: {', '.join(REQUIRED_APP_FILES)}")
    print(f"controlled_workspace_files: {len([path for path in workspace_root.rglob('*') if path.is_file()])}")
    print("sfe_runpipeline_called: false")
    print("multipass_forced_auto: true")
    print("api_called: false")


if __name__ == "__main__":
    raise SystemExit(main())
