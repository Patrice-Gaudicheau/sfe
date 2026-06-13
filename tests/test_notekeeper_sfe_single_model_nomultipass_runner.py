from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_notekeeper_sfe_single_model_nomultipass_openai.py"

spec = importlib.util.spec_from_file_location("notekeeper_sfe_single_model_runner", RUNNER_PATH)
assert spec is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
assert spec.loader is not None
spec.loader.exec_module(runner)


def _context() -> runner.BenchmarkContext:
    tasks = (
        runner.TaskInstruction(
            task_id="01_initial_scaffold",
            title="Initial static scaffold",
            heading="## 1. Initial static scaffold",
            body="Create the initial static files.",
        ),
    )
    return runner.BenchmarkContext(
        product_prompt="Product brief",
        acceptance_criteria="Acceptance criteria",
        task_sequence="Task sequence",
        tasks=tasks,
    )


def test_dry_run_validate_inputs_does_not_require_openai_api_key() -> None:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)

    result = subprocess.run(
        [
            sys.executable,
            str(RUNNER_PATH),
            "--dry-run-validate-inputs",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "success: true" in result.stdout
    assert "sfe_runpipeline_called: false" in result.stdout
    assert "multipass_forced_off: true" in result.stdout
    assert "api_called: false" in result.stdout


def test_build_controlled_workspace_contains_only_brief_tasks_and_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario_app = tmp_path / "scenario_app"
    scenario_app.mkdir()
    (scenario_app / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(runner, "APP_DIR", scenario_app)

    workspace = tmp_path / "workspace"
    runner.build_controlled_workspace(workspace, _context())
    runner.validate_controlled_workspace(workspace)

    files = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file())
    assert files == [
        "app/index.html",
        "brief/acceptance_criteria.md",
        "brief/prompt.md",
        "brief/task_sequence.md",
        "tasks/01_initial_scaffold.md",
    ]


def test_validate_benchmark_layout_creates_missing_task_run_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scenario_dir = tmp_path / "scenario"
    app_dir = scenario_dir / "app"
    runs_dir = scenario_dir / "runs"
    app_dir.mkdir(parents=True)
    runs_dir.mkdir()
    token_usage_path = scenario_dir / "token_usage.json"
    report_path = scenario_dir / "report.md"
    token_usage_path.write_text("{}\n", encoding="utf-8")
    report_path.write_text("# Report\n", encoding="utf-8")

    monkeypatch.setattr(runner, "SCENARIO_DIR", scenario_dir)
    monkeypatch.setattr(runner, "APP_DIR", app_dir)
    monkeypatch.setattr(runner, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(runner, "TOKEN_USAGE_PATH", token_usage_path)
    monkeypatch.setattr(runner, "REPORT_PATH", report_path)

    runner.validate_benchmark_layout(_context().tasks)

    assert (runs_dir / "01_initial_scaffold").is_dir()


def test_validate_controlled_workspace_rejects_extra_app_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    runner.build_controlled_workspace(workspace, _context())
    (workspace / "app" / "package.json").write_text("{}", encoding="utf-8")

    try:
        runner.validate_controlled_workspace(workspace)
    except runner.NoteKeeperSFERunnerError as exc:
        assert "Unexpected controlled app file" in str(exc)
    else:
        raise AssertionError("expected controlled workspace validation to fail")


def test_validate_successful_task_output_rejects_unexpected_promoted_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "app").mkdir(parents=True)
    for filename in runner.REQUIRED_APP_FILES:
        (workspace / "app" / filename).write_text(filename, encoding="utf-8")

    class Result:
        promoted_files = ("app/index.html", "package.json")
        changed_files = ()

    error = runner.validate_successful_task_output(workspace, Result())

    assert error is not None
    assert "Unexpected SFE-promoted files" in error


def test_provider_call_aggregation_uses_real_values_only() -> None:
    calls = [
        {"input_tokens": 10, "cached_input_tokens": 2, "output_tokens": 5, "latency_ms": 100},
        {"input_tokens": None, "cached_input_tokens": None, "output_tokens": 7, "latency_ms": 200},
    ]

    assert runner._sum_optional(call.get("input_tokens") for call in calls) == 10
    assert runner._sum_optional(call.get("cached_input_tokens") for call in calls) == 2
    assert runner._sum_optional(call.get("output_tokens") for call in calls) == 12
    assert runner._sum_optional(call.get("latency_ms") for call in calls) == 300
