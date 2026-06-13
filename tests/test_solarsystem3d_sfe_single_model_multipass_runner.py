from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_solarsystem3d_sfe_single_model_multipass_openai.py"

spec = importlib.util.spec_from_file_location("solarsystem3d_sfe_single_model_multipass_runner", RUNNER_PATH)
assert spec is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
assert spec.loader is not None
spec.loader.exec_module(runner)


EXPECTED_TASK_IDS = (
    "01_static_scaffold",
    "02_data_and_textures",
    "03_bodies_scale_orbits",
    "04_animation_time_scale",
    "05_earth_seasons",
    "06_camera_labels_focus",
    "07_info_accessibility",
    "08_responsive_performance_readme",
)


def test_scenario_mapping_and_expected_app_targets() -> None:
    assert runner.SCENARIO_DIR == PROJECT_ROOT / "examples" / "SolarSystem3D" / "20_sfe_single_model_gpt54_multipass"
    assert runner.REQUIRED_APP_FILES == ("index.html", "styles.css", "app.js", "README.md")
    assert runner.ALLOWED_WORKSPACE_APP_FILES == (
        "app/index.html",
        "app/styles.css",
        "app/app.js",
        "app/README.md",
    )


def test_load_benchmark_context_uses_eight_solarsystem3d_tasks() -> None:
    context = runner.load_benchmark_context()

    assert tuple(task.task_id for task in context.tasks) == EXPECTED_TASK_IDS
    assert len(context.tasks) == 8


def test_validate_benchmark_layout_creates_empty_app_runs_and_task_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario_dir = tmp_path / "20_sfe_single_model_gpt54_multipass"
    scenario_dir.mkdir()
    app_dir = scenario_dir / "app"
    runs_dir = scenario_dir / "runs"

    monkeypatch.setattr(runner, "SCENARIO_DIR", scenario_dir)
    monkeypatch.setattr(runner, "APP_DIR", app_dir)
    monkeypatch.setattr(runner, "RUNS_DIR", runs_dir)
    monkeypatch.setattr(runner, "TOKEN_USAGE_PATH", scenario_dir / "token_usage.json")
    monkeypatch.setattr(runner, "REPORT_PATH", scenario_dir / "report.md")

    context = runner.load_benchmark_context()
    runner.validate_benchmark_layout(context.tasks)

    assert app_dir.is_dir()
    assert runs_dir.is_dir()
    assert sorted(path.name for path in runs_dir.iterdir()) == list(EXPECTED_TASK_IDS)


def test_build_controlled_workspace_supports_empty_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario_app = tmp_path / "app"
    scenario_app.mkdir()
    monkeypatch.setattr(runner, "APP_DIR", scenario_app)

    context = runner.load_benchmark_context()
    workspace = tmp_path / "workspace"
    runner.build_controlled_workspace(workspace, context)
    runner.validate_controlled_workspace(workspace)

    files = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file())
    assert "brief/prompt.md" in files
    assert "brief/acceptance_criteria.md" in files
    assert "brief/task_sequence.md" in files
    assert "tasks/08_responsive_performance_readme.md" in files
    assert not any(path.startswith("app/") for path in files)


def test_dry_run_validate_inputs_does_not_require_openai_api_key() -> None:
    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)

    result = subprocess.run(
        [sys.executable, str(RUNNER_PATH), "--dry-run-validate-inputs"],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "success: true" in result.stdout
    assert "scenario: sfe_single_model_gpt54_multipass" in result.stdout
    assert "router_model: gpt-5.4" in result.stdout
    assert "executor_model: gpt-5.4" in result.stdout
    assert "task_count: 8" in result.stdout
    assert "sfe_runpipeline_called: false" in result.stdout
    assert "multipass_forced_on: true" in result.stdout
    assert "api_called: false" in result.stdout


def test_validate_args_uses_one_model_for_all_roles() -> None:
    class Args:
        model = "gpt-test"
        timeout = 12
        dry_run_validate_inputs = True

    config = runner._validate_args(Args())

    assert config["model"] == "gpt-test"
    assert config["router_model"] == "gpt-test"
    assert config["discovery_model"] == "gpt-test"
    assert config["executor_model"] == "gpt-test"
    assert config["multipass_planner_model"] == "gpt-test"


def test_force_sfe_environment_uses_openai_single_model_and_forces_multipass() -> None:
    config = {
        "model": "gpt-5.4",
        "router_model": "gpt-5.4",
        "discovery_model": "gpt-5.4",
        "executor_model": "gpt-5.4",
        "multipass_planner_model": "gpt-5.4",
    }

    environ = runner.force_sfe_environment(config)

    assert environ["SFE_OPENAI_ROUTER_MODEL"] == "gpt-5.4"
    assert environ["SFE_OPENAI_DISCOVERY_MODEL"] == "gpt-5.4"
    assert environ["SFE_OPENAI_EXECUTOR_MODEL"] == "gpt-5.4"
    assert environ["SFE_WORKSPACE_WRITE_MULTIPASS"] == "true"

