from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_solarsystem3d_baseline_full_context_openai.py"

spec = importlib.util.spec_from_file_location("solarsystem3d_baseline_runner", RUNNER_PATH)
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


def _valid_snapshot_json() -> str:
    return (
        "{"
        '"files": ['
        '{"path": "index.html", "content": "<!doctype html>"},'
        '{"path": "styles.css", "content": "body {}"},'
        '{"path": "app.js", "content": "console.log(1);"},'
        '{"path": "README.md", "content": "# SolarSystem3D"}'
        '], "notes": "ok"}'
    )


def test_expected_app_file_targets_are_static_four_file_app() -> None:
    assert runner.REQUIRED_APP_FILES == ("index.html", "styles.css", "app.js", "README.md")


def test_load_benchmark_context_uses_solarsystem3d_task_mapping() -> None:
    context = runner.load_benchmark_context()

    assert tuple(task.task_id for task in context.tasks) == EXPECTED_TASK_IDS
    assert len(context.tasks) == 8
    assert "SolarSystem3D" in context.product_prompt


def test_validate_benchmark_layout_creates_empty_app_runs_and_task_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario_dir = tmp_path / "10_baseline_full_context_gpt54"
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


def test_parse_model_snapshot_accepts_exact_required_files() -> None:
    snapshot = runner.parse_model_snapshot(_valid_snapshot_json())

    assert tuple(snapshot.files) == runner.REQUIRED_APP_FILES
    assert snapshot.files["README.md"] == "# SolarSystem3D"
    assert snapshot.notes == "ok"


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/index.html",
        "../index.html",
        "nested/index.html",
        "nested\\index.html",
        "package.json",
        "vendor/three.module.js",
    ],
)
def test_parse_model_snapshot_rejects_unsafe_or_extra_paths(path: str) -> None:
    payload = (
        "{"
        '"files": ['
        f'{{"path": "{path}", "content": "bad"}},'
        '{"path": "styles.css", "content": ""},'
        '{"path": "app.js", "content": ""},'
        '{"path": "README.md", "content": ""}'
        "]}"
    )

    with pytest.raises(runner.SolarSystem3DBaselineError):
        runner.parse_model_snapshot(payload)


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
    assert "scenario: baseline_full_context_gpt54" in result.stdout
    assert "task_count: 8" in result.stdout
    assert "required_app_files: index.html, styles.css, app.js, README.md" in result.stdout
    assert "api_called: false" in result.stdout

