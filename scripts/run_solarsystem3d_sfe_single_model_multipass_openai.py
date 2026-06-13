"""Run the SolarSystem3D SFE single-model OpenAI benchmark scenario.

This runner intentionally uses the real SFE RunPipeline path while keeping the
workspace small and benchmark-specific. It does not use the full-context
baseline runner and does not expose unrelated repository files to discovery.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, is_dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from providers.openai_api import (  # noqa: E402
    MissingOpenAIAPIKeyError,
    OpenAIAPIProvider,
    PROVIDER_NAME,
)
from runtime.metrics import write_json_report, write_text_report  # noqa: E402
from sfe.discovery_router import create_configured_discovery_router  # noqa: E402
from sfe.env import load_repo_env  # noqa: E402
from sfe.execution_mode_router import create_configured_execution_mode_router  # noqa: E402
from sfe.multipass_planner import create_configured_multipass_planner  # noqa: E402
from sfe.run_pipeline import RUN_STATUS_COMPLETED, RunPipeline, RunRequest  # noqa: E402
from sfe.workspace_isolation import WorkspaceIsolationPolicy  # noqa: E402
from sfe_tui.backends import DirectBackend  # noqa: E402
from sfe_tui.executors import OpenAIReadOnlyExecutor  # noqa: E402


DEFAULT_MODEL = "gpt-5.4"
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_PATCH_OUTPUT_TOKENS = 30_000
SCENARIO_NAME = "sfe_single_model_gpt54_multipass"
SCENARIO_DESCRIPTION = (
    "SFE single-model run with gpt-5.4 used for routing, discovery, multipass "
    "planning, and execution, with multipass forced on."
)

SOLARSYSTEM3D_ROOT = PROJECT_ROOT / "examples" / "SolarSystem3D"
BRIEF_DIR = SOLARSYSTEM3D_ROOT / "00_project_brief"
SCENARIO_DIR = SOLARSYSTEM3D_ROOT / "20_sfe_single_model_gpt54_multipass"
APP_DIR = SCENARIO_DIR / "app"
RUNS_DIR = SCENARIO_DIR / "runs"
TOKEN_USAGE_PATH = SCENARIO_DIR / "token_usage.json"
REPORT_PATH = SCENARIO_DIR / "report.md"

PRODUCT_PROMPT_PATH = BRIEF_DIR / "prompt.md"
ACCEPTANCE_CRITERIA_PATH = BRIEF_DIR / "acceptance_criteria.md"
TASK_SEQUENCE_PATH = BRIEF_DIR / "task_sequence.md"

REQUIRED_APP_FILES = ("index.html", "styles.css", "app.js", "README.md")
ALLOWED_WORKSPACE_APP_FILES = tuple(f"app/{filename}" for filename in REQUIRED_APP_FILES)
EXPECTED_TASKS = (
    ("01_static_scaffold", "Static scaffold and Three.js scene shell"),
    ("02_data_and_textures", "Solar system data model and procedural texture pipeline"),
    ("03_bodies_scale_orbits", "Bodies, educational scale, rings, and orbit paths"),
    ("04_animation_time_scale", "Animation, time controls, and realistic scale mode"),
    ("05_earth_seasons", "Earth seasons, axial tilt, and date or season presets"),
    ("06_camera_labels_focus", "Camera navigation, presets, labels, and click focus"),
    ("07_info_accessibility", "Info panel, toggles, keyboard support, and accessibility pass"),
    ("08_responsive_performance_readme", "Responsive polish, performance review, and README"),
)


class SolarSystem3DSFERunnerError(RuntimeError):
    """Raised for runner validation and execution failures."""


@dataclass(frozen=True)
class TaskInstruction:
    task_id: str
    title: str
    heading: str
    body: str


@dataclass(frozen=True)
class BenchmarkContext:
    product_prompt: str
    acceptance_criteria: str
    task_sequence: str
    tasks: tuple[TaskInstruction, ...]


@dataclass
class ProviderCallRecorder:
    current_task_id: str | None = None
    calls: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.calls is None:
            self.calls = []

    def append(self, call: dict[str, Any]) -> None:
        assert self.calls is not None
        self.calls.append(call)

    def calls_for_task(self, task_id: str) -> list[dict[str, Any]]:
        assert self.calls is not None
        return [call for call in self.calls if call.get("task_id") == task_id]


class RecordingOpenAIProvider:
    """OpenAI provider wrapper that records normalized usage for each SFE role."""

    def __init__(
        self,
        *,
        role: str,
        recorder: ProviderCallRecorder,
        timeout: float,
    ) -> None:
        self.role = role
        self.recorder = recorder
        self.provider = OpenAIAPIProvider(timeout=timeout)

    def health(self) -> dict[str, Any]:
        return self.provider.health()

    def chat(self, messages: list[dict[str, str]], model: str, **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        call: dict[str, Any] = {
            "task_id": self.recorder.current_task_id,
            "role": self.role,
            "provider": PROVIDER_NAME,
            "model": model,
            "input_tokens": None,
            "cached_input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "latency": None,
            "latency_ms": None,
            "retry_count": None,
            "success": False,
            "error": None,
        }
        try:
            response = self.provider.chat(messages, model=model, **kwargs)
        except Exception as exc:
            call["latency_ms"] = int((time.perf_counter() - started) * 1000)
            call["latency"] = call["latency_ms"]
            call["error"] = _safe_error_message(exc)
            self.recorder.append(call)
            raise

        usage = extract_usage(response)
        metadata = response.get("openai_api") if isinstance(response, dict) else None
        if not isinstance(metadata, dict):
            metadata = {}
        latency_ms = _optional_int(metadata.get("latency_ms"))
        if latency_ms is None:
            latency_ms = int((time.perf_counter() - started) * 1000)
        call.update(
            {
                "provider": str(metadata.get("provider") or PROVIDER_NAME),
                "input_tokens": usage["input_tokens"],
                "cached_input_tokens": usage["cached_input_tokens"],
                "output_tokens": usage["output_tokens"],
                "total_tokens": usage["total_tokens"],
                "latency": latency_ms,
                "latency_ms": latency_ms,
                "retry_count": _optional_int(metadata.get("api_error_retry_count")),
                "success": True,
                "error": None,
            }
        )
        self.recorder.append(call)
        return response


def main() -> int:
    load_repo_env()
    args = _parse_args()
    try:
        config = _validate_args(args)
        context = load_benchmark_context()
        validate_benchmark_layout(context.tasks)
        with tempfile.TemporaryDirectory(prefix="solarsystem3d-sfe-single-model-") as tmp:
            workspace_root = Path(tmp) / "workspace"
            build_controlled_workspace(workspace_root, context)
            validate_controlled_workspace(workspace_root)
            if config["dry_run_validate_inputs"]:
                _print_dry_run_success(config, context, workspace_root)
                return 0

            if not os.getenv("OPENAI_API_KEY"):
                raise MissingOpenAIAPIKeyError(
                    "OPENAI_API_KEY is required for the SolarSystem3D SFE single-model run."
                )
            run_sfe_scenario(context=context, config=config, workspace_root=workspace_root)
        return 0
    except SolarSystem3DSFERunnerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except MissingOpenAIAPIKeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the SolarSystem3D SFE single-model OpenAI benchmark with router, "
            "discovery, and executor all using the same model."
        )
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument(
        "--dry-run-validate-inputs",
        action="store_true",
        help="Validate local inputs and controlled workspace construction without API calls.",
    )
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> dict[str, Any]:
    model = str(args.model or "").strip()
    if not model:
        raise SolarSystem3DSFERunnerError("--model must not be empty.")
    if args.timeout <= 0:
        raise SolarSystem3DSFERunnerError("--timeout must be greater than 0.")
    return {
        "model": model,
        "router_model": model,
        "discovery_model": model,
        "executor_model": model,
        "multipass_planner_model": model,
        "timeout": float(args.timeout),
        "dry_run_validate_inputs": bool(args.dry_run_validate_inputs),
    }


def load_benchmark_context() -> BenchmarkContext:
    product_prompt = _read_required_text(PRODUCT_PROMPT_PATH)
    acceptance_criteria = _read_required_text(ACCEPTANCE_CRITERIA_PATH)
    task_sequence = _read_required_text(TASK_SEQUENCE_PATH)
    tasks = parse_task_sequence(task_sequence)
    return BenchmarkContext(
        product_prompt=product_prompt,
        acceptance_criteria=acceptance_criteria,
        task_sequence=task_sequence,
        tasks=tasks,
    )


def parse_task_sequence(task_sequence: str) -> tuple[TaskInstruction, ...]:
    import re

    matches = list(re.finditer(r"^##\s+(\d+)\.\s+(.+?)\s*$", task_sequence, flags=re.MULTILINE))
    tasks: list[TaskInstruction] = []
    for index, match in enumerate(matches):
        number = int(match.group(1))
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(task_sequence)
        body = task_sequence[start:end].strip()
        if not body:
            raise SolarSystem3DSFERunnerError(f"Task {number} has no body in task_sequence.md.")
        expected_id, expected_title = EXPECTED_TASKS[number - 1] if 1 <= number <= len(EXPECTED_TASKS) else ("", "")
        if not expected_id or title != expected_title:
            raise SolarSystem3DSFERunnerError(
                f"Unexpected task heading {number}: {title!r}; expected {expected_title!r}."
            )
        tasks.append(
            TaskInstruction(
                task_id=expected_id,
                title=title,
                heading=match.group(0).strip(),
                body=body,
            )
        )
    if len(tasks) != len(EXPECTED_TASKS):
        raise SolarSystem3DSFERunnerError(
            f"Expected {len(EXPECTED_TASKS)} tasks in task_sequence.md, found {len(tasks)}."
        )
    return tuple(tasks)


def validate_benchmark_layout(tasks: tuple[TaskInstruction, ...]) -> None:
    for path in (APP_DIR, RUNS_DIR):
        path.mkdir(parents=True, exist_ok=True)
    for path in (BRIEF_DIR, SCENARIO_DIR, APP_DIR, RUNS_DIR):
        if not path.is_dir():
            raise SolarSystem3DSFERunnerError(f"Required directory is missing: {_rel(path)}")
    for task in tasks:
        (RUNS_DIR / task.task_id).mkdir(parents=True, exist_ok=True)
    validate_scenario_app_dir()


def validate_scenario_app_dir() -> None:
    unexpected = [
        path.name
        for path in APP_DIR.iterdir()
        if path.is_file() and path.name not in REQUIRED_APP_FILES and path.name != ".gitkeep"
    ]
    if unexpected:
        raise SolarSystem3DSFERunnerError(
            "Unexpected files already exist in app directory: " + ", ".join(sorted(unexpected))
        )


def build_controlled_workspace(workspace_root: Path, context: BenchmarkContext) -> None:
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    (workspace_root / "brief").mkdir(parents=True)
    (workspace_root / "tasks").mkdir()
    (workspace_root / "app").mkdir()
    (workspace_root / "brief" / "prompt.md").write_text(context.product_prompt, encoding="utf-8")
    (workspace_root / "brief" / "acceptance_criteria.md").write_text(
        context.acceptance_criteria,
        encoding="utf-8",
    )
    (workspace_root / "brief" / "task_sequence.md").write_text(
        context.task_sequence,
        encoding="utf-8",
    )
    for task in context.tasks:
        (workspace_root / "tasks" / f"{task.task_id}.md").write_text(
            build_task_metadata(task),
            encoding="utf-8",
        )
    for filename in REQUIRED_APP_FILES:
        source = APP_DIR / filename
        if source.is_file():
            shutil.copy2(source, workspace_root / "app" / filename)


def validate_controlled_workspace(workspace_root: Path) -> None:
    required = (
        workspace_root / "brief" / "prompt.md",
        workspace_root / "brief" / "acceptance_criteria.md",
        workspace_root / "brief" / "task_sequence.md",
    )
    for path in required:
        if not path.is_file() or not path.read_text(encoding="utf-8").strip():
            raise SolarSystem3DSFERunnerError(f"Controlled workspace missing required file: {path}")
    for path in workspace_root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace_root).as_posix()
        if relative.startswith("app/") and relative not in ALLOWED_WORKSPACE_APP_FILES:
            raise SolarSystem3DSFERunnerError(f"Unexpected controlled app file: {relative}")


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
        commit_controlled_workspace_snapshot(workspace_root, task)

    write_token_usage(run_results, config)
    write_report(run_results, config)
    if failed:
        raise SolarSystem3DSFERunnerError(
            "SFE single-model run failed; see task artifacts for diagnostics."
        )
    print("success: true")
    print(f"scenario: {SCENARIO_NAME}")
    print(f"model: {config['model']}")
    print(f"router_model: {config['router_model']}")
    print(f"discovery_model: {config['discovery_model']}")
    print(f"executor_model: {config['executor_model']}")
    print(f"multipass_planner_model: {config['multipass_planner_model']}")
    print("multipass: true")
    print("generated_files:")
    for path in _final_generated_file_list():
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
        "SFE_WORKSPACE_WRITE_MULTIPASS": "true",
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
        progress_events.append(_to_jsonable(event))

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
    validation_error = validate_successful_task_output(workspace_root, result)
    success = result.status == RUN_STATUS_COMPLETED and validation_error is None
    generated_files: list[str] = []
    if success:
        copy_workspace_app_to_scenario(workspace_root)
        generated_files = [_rel(APP_DIR / filename) for filename in REQUIRED_APP_FILES]

    if result.discovery_result is not None:
        write_json_report(run_dir / "discovery_result.json", discovery_result_summary(result.discovery_result))
    if result.dry_run_result is not None:
        write_json_report(run_dir / "selected_context.json", selected_context_summary(result.dry_run_result))
    if result.patch_result is not None and result.patch_result.answer is not None:
        (run_dir / "patch_response.txt").write_text(result.patch_result.answer, encoding="utf-8")
    else:
        (run_dir / "patch_response.txt").write_text("", encoding="utf-8")
    if result.multi_pass_summary is not None:
        write_json_report(run_dir / "multipass_summary.json", _to_jsonable(result.multi_pass_summary))
    (run_dir / "changed_files.txt").write_text(
        "\n".join(result.changed_files or result.promoted_files) + ("\n" if result.changed_files or result.promoted_files else ""),
        encoding="utf-8",
    )
    write_json_report(run_dir / "progress_events.json", progress_events)
    write_json_report(run_dir / "provider_calls.json", {"calls": provider_calls})

    run_record = {
        "task_id": task.task_id,
        "task_title": task.title,
        "provider": PROVIDER_NAME,
        "models": {
            "primary": config["model"],
            "router": config["router_model"],
            "discovery": config["discovery_model"],
            "executor": config["executor_model"],
            "multipass_planner": config["multipass_planner_model"],
            "reviewer": None,
        },
        "input_tokens": _sum_optional(call.get("input_tokens") for call in provider_calls),
        "cached_input_tokens": _sum_optional(call.get("cached_input_tokens") for call in provider_calls),
        "output_tokens": _sum_optional(call.get("output_tokens") for call in provider_calls),
        "total_estimated_cost": None,
        "currency": None,
        "latency_or_wall_clock_duration": _sum_optional(call.get("latency_ms") for call in provider_calls),
        "wall_clock_duration_ms": wall_clock_ms,
        "success": success,
        "generated_or_modified_files": generated_files,
        "manual_verification_notes": None,
        "validation_error": validation_error,
        "sfe_status": result.status,
        "sfe_issue": _issue_summary(result.issue),
        "multipass_mode": "true",
        "multipass_forced_on": True,
        "multipass_forced_auto": False,
        "provider_call_count": len(provider_calls),
    }
    write_json_report(run_dir / "run_result.json", run_result_summary(result, run_record))
    return run_record


def build_sfe_task_prompt(*, context: BenchmarkContext, task: TaskInstruction) -> str:
    del context
    return (
        "# SolarSystem3D SFE single-model multipass benchmark task\n\n"
        "Use the SFE-selected workspace context. The controlled workspace contains "
        "only the benchmark brief under `brief/`, task metadata under `tasks/`, "
        "and the current generated app under `app/`.\n\n"
        "This scenario uses one OpenAI model for router, discovery, multipass planning, and patch generation. Multipass is intentionally forced on.\n\n"
        "You are implementing the SolarSystem3D static Three.js browser app. Edit only these "
        "workspace files:\n\n"
        "- `app/index.html`\n"
        "- `app/styles.css`\n"
        "- `app/app.js`\n"
        "- `app/README.md`\n\n"
        "Do not create package files, server code, backend code, screenshots, logs, "
        "or files outside `app/`. Do not add external texture images or audio. "
        "A pinned browser Three.js CDN import is allowed, and a documented simple "
        "static-server fallback is allowed if browser module restrictions require it.\n\n"
        "Consult these benchmark documents from selected context when available:\n\n"
        "- `brief/prompt.md`\n"
        "- `brief/acceptance_criteria.md`\n"
        "- `brief/task_sequence.md`\n"
        f"- `tasks/{task.task_id}.md`\n\n"
        "## Current task\n\n"
        f"{task.heading}\n\n{task.body}\n"
    )


def build_task_metadata(task: TaskInstruction) -> str:
    return f"# {task.task_id}: {task.title}\n\n{task.heading}\n\n{task.body}\n"


def validate_successful_task_output(workspace_root: Path, result: Any) -> str | None:
    promoted_files = tuple(getattr(result, "promoted_files", ()) or ())
    changed_files = tuple(getattr(result, "changed_files", ()) or ())
    touched = set(promoted_files or changed_files)
    unexpected = sorted(path for path in touched if path not in ALLOWED_WORKSPACE_APP_FILES)
    if unexpected:
        return "Unexpected SFE-promoted files: " + ", ".join(unexpected)
    app_dir = workspace_root / "app"
    missing = [filename for filename in REQUIRED_APP_FILES if not (app_dir / filename).is_file()]
    if missing:
        return "Missing required app files in controlled workspace: " + ", ".join(missing)
    unexpected_app_files = [
        path.name
        for path in app_dir.iterdir()
        if path.is_file() and path.name not in REQUIRED_APP_FILES
    ]
    if unexpected_app_files:
        return "Unexpected files in controlled app directory: " + ", ".join(sorted(unexpected_app_files))
    return None


def copy_workspace_app_to_scenario(workspace_root: Path) -> None:
    validate_scenario_app_dir()
    APP_DIR.mkdir(parents=True, exist_ok=True)
    gitkeep = APP_DIR / ".gitkeep"
    if gitkeep.exists():
        gitkeep.unlink()
    for filename in REQUIRED_APP_FILES:
        shutil.copy2(workspace_root / "app" / filename, APP_DIR / filename)


def commit_controlled_workspace_snapshot(workspace_root: Path, task: TaskInstruction) -> None:
    add = _git(workspace_root, "add", "--", "app")
    if add.returncode != 0:
        raise SolarSystem3DSFERunnerError(f"Failed to stage controlled workspace app after {task.task_id}.")
    commit = _git(
        workspace_root,
        "-c",
        "user.name=SFE",
        "-c",
        "user.email=sfe@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        f"SolarSystem3D {task.task_id}",
    )
    if commit.returncode != 0:
        raise SolarSystem3DSFERunnerError(f"Failed to commit controlled workspace app after {task.task_id}.")


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
            }
        )
    write_json_report(
        TOKEN_USAGE_PATH,
        {
            "scenario": SCENARIO_NAME,
            "description": SCENARIO_DESCRIPTION,
            "runs": runs,
            "totals": {
                "input_tokens": _sum_optional(result["input_tokens"] for result in run_results),
                "cached_input_tokens": _sum_optional(
                    result["cached_input_tokens"] for result in run_results
                ),
                "output_tokens": _sum_optional(result["output_tokens"] for result in run_results),
                "total_estimated_cost": None,
                "currency": None,
                "latency_or_wall_clock_duration": _sum_optional(
                    result["latency_or_wall_clock_duration"] for result in run_results
                ),
            },
            "configuration": {
                "model": config["model"],
                "router_model": config["router_model"],
                "discovery_model": config["discovery_model"],
                "executor_model": config["executor_model"],
                "multipass_planner_model": config["multipass_planner_model"],
                "multipass": "true",
            },
        },
    )


def write_report(run_results: list[dict[str, Any]], config: dict[str, Any]) -> None:
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    all_success = all(result["success"] for result in run_results)
    lines = [
        "# SFE single-model gpt-5.4 multipass report",
        "",
        f"Generated at: `{generated_at}`",
        "",
        "## Scenario",
        "",
        "- Workflow: SFE single-model run with multipass forced on.",
        f"- Provider: `{PROVIDER_NAME}`.",
        f"- Router model: `{config['router_model']}`.",
        f"- Discovery model: `{config['discovery_model']}`.",
        f"- Multipass planner model: `{config['multipass_planner_model']}`.",
        f"- Executor model: `{config['executor_model']}`.",
        "- Multipass: `true`.",
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
            f"{_format_optional(result['input_tokens'])} | "
            f"{_format_optional(result['cached_input_tokens'])} | "
            f"{_format_optional(result['output_tokens'])} | "
            f"{_format_optional(result['latency_or_wall_clock_duration'])} | "
            f"{_markdown_cell(str(error))} |"
        )
    lines.extend(
        [
            "",
            "## Generated Files",
            "",
            *(f"- `{path}`" for path in _final_generated_file_list()),
            "",
            "## Notes",
            "",
            "Task-level SFE prompts, progress events, provider call records, discovery summaries, selected context summaries, patch responses, and run metadata are stored under `runs/<task>/`.",
        ]
    )
    write_text_report(REPORT_PATH, "\n".join(lines) + "\n")


def discovery_result_summary(discovery_result: Any) -> dict[str, Any]:
    payload = _to_jsonable(discovery_result)
    if isinstance(payload, dict):
        for item in payload.get("load_results", []) or []:
            if isinstance(item, dict) and "text" in item:
                item["text"] = f"[omitted {len(str(item['text']))} chars]"
    return payload if isinstance(payload, dict) else {"value": payload}


def selected_context_summary(dry_run_result: Any) -> dict[str, Any]:
    contract = getattr(dry_run_result, "contract", None)
    audit = getattr(contract, "audit", {}) if contract is not None else {}
    selected_ids = set(audit.get("selected_segment_ids") or [])
    segments = []
    for segment in getattr(contract, "context_segments", []) if contract is not None else []:
        if segment.id in selected_ids:
            segments.append(
                {
                    "id": segment.id,
                    "source_ref": segment.source_ref,
                    "approx_size": segment.approx_size,
                    "approx_tokens": segment.approx_tokens,
                }
            )
    return {
        "selected_segment_ids": sorted(selected_ids),
        "selected_segments": segments,
        "audit": _to_jsonable(audit),
        "router_preview": _to_jsonable(getattr(dry_run_result, "router_preview", None)),
    }


def run_result_summary(result: Any, run_record: dict[str, Any]) -> dict[str, Any]:
    patch_summary = getattr(result, "patch_summary", None)
    execution_mode_decision = getattr(result, "execution_mode_decision", None)
    return {
        "run": run_record,
        "sfe": {
            "status": result.status,
            "issue": _issue_summary(result.issue),
            "execution_mode_decision": _to_jsonable(execution_mode_decision),
            "executor_provider": result.executor_provider,
            "patch_generated": result.patch_generated,
            "patch_applied": result.patch_applied,
            "promotion_status": result.promotion_status,
            "promotion_applied": result.promotion_applied,
            "changed_files": list(result.changed_files),
            "promoted_files": list(result.promoted_files),
            "selected_source_refs": list(result.selected_source_refs),
            "warnings": list(result.warnings),
            "git_auto_init": result.git_auto_init,
            "git_initial_commit_hash": result.git_initial_commit_hash,
            "patch_summary": _to_jsonable(patch_summary),
            "multi_pass_summary": _to_jsonable(result.multi_pass_summary),
        },
    }


def extract_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    return {
        "input_tokens": _optional_int(usage.get("prompt_tokens")),
        "cached_input_tokens": _optional_int(usage.get("cached_input_tokens")),
        "output_tokens": _optional_int(usage.get("completion_tokens")),
        "total_tokens": _optional_int(usage.get("total_tokens")),
    }


def _read_required_text(path: Path) -> str:
    if not path.is_file():
        raise SolarSystem3DSFERunnerError(f"Required file is missing: {_rel(path)}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise SolarSystem3DSFERunnerError(f"Required file is empty: {_rel(path)}")
    return text


def _issue_summary(issue: Any) -> dict[str, Any] | None:
    if issue is None:
        return None
    return _to_jsonable(issue)


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if is_dataclass(value):
        return {field.name: _to_jsonable(getattr(value, field.name)) for field in fields(value)}
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sum_optional(values: Any) -> int | None:
    numbers = [int(value) for value in values if value is not None]
    if not numbers:
        return None
    return sum(numbers)


def _format_optional(value: Any) -> str:
    if value is None:
        return "`null`"
    return str(value)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _safe_error_message(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        message = message.replace(api_key, "[REDACTED]")
    return message


def _final_generated_file_list() -> list[str]:
    return [_rel(APP_DIR / filename) for filename in REQUIRED_APP_FILES if (APP_DIR / filename).is_file()]


def _print_dry_run_success(
    config: dict[str, Any],
    context: BenchmarkContext,
    workspace_root: Path,
) -> None:
    print("success: true")
    print("mode: dry-run-validate-inputs")
    print(f"scenario: {SCENARIO_NAME}")
    print(f"model: {config['model']}")
    print(f"router_model: {config['router_model']}")
    print(f"discovery_model: {config['discovery_model']}")
    print(f"executor_model: {config['executor_model']}")
    print(f"multipass_planner_model: {config['multipass_planner_model']}")
    print(f"task_count: {len(context.tasks)}")
    print(f"required_app_files: {', '.join(REQUIRED_APP_FILES)}")
    print(f"controlled_workspace_files: {len([path for path in workspace_root.rglob('*') if path.is_file()])}")
    print("sfe_runpipeline_called: false")
    print("multipass_forced_auto: false")
    print("multipass_forced_on: true")
    print("api_called: false")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def _rel(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
