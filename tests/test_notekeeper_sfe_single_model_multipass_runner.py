from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_notekeeper_sfe_single_model_multipass_openai.py"

spec = importlib.util.spec_from_file_location("notekeeper_sfe_single_model_multipass_runner", RUNNER_PATH)
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
    assert "model: gpt-5.4" in result.stdout
    assert "router_model: gpt-5.4" in result.stdout
    assert "discovery_model: gpt-5.4" in result.stdout
    assert "executor_model: gpt-5.4" in result.stdout
    assert "multipass_planner_model: gpt-5.4" in result.stdout
    assert "multipass_forced_auto: false" in result.stdout
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
    assert config["timeout"] == 12.0


def test_force_sfe_environment_uses_openai_single_model_and_forces_multipass() -> None:
    config = {
        "model": "gpt-5.4",
        "router_model": "gpt-5.4",
        "discovery_model": "gpt-5.4",
        "executor_model": "gpt-5.4",
        "multipass_planner_model": "gpt-5.4",
    }

    environ = runner.force_sfe_environment(config)

    assert environ["SFE_PROVIDER_ROUTER"] == "openai"
    assert environ["SFE_PROVIDER_DISCOVERY"] == "openai"
    assert environ["SFE_PROVIDER_EXECUTOR"] == "openai"
    assert environ["SFE_OPENAI_ROUTER_MODEL"] == "gpt-5.4"
    assert environ["SFE_OPENAI_DISCOVERY_MODEL"] == "gpt-5.4"
    assert environ["SFE_OPENAI_EXECUTOR_MODEL"] == "gpt-5.4"
    assert environ["SFE_WORKSPACE_WRITE_MULTIPASS"] == "true"
    assert os.environ["SFE_WORKSPACE_WRITE_MULTIPASS"] == "true"


def test_build_sfe_pipeline_assigns_one_model_to_all_roles() -> None:
    config = {
        "model": "gpt-5.4-all",
        "router_model": "gpt-5.4-all",
        "discovery_model": "gpt-5.4-all",
        "executor_model": "gpt-5.4-all",
        "multipass_planner_model": "gpt-5.4-all",
        "timeout": 30.0,
    }
    environ = runner.force_sfe_environment(config)
    recorder = runner.ProviderCallRecorder()

    pipeline = runner.build_sfe_pipeline(config=config, environ=environ, recorder=recorder)

    assert pipeline.execution_mode_router.model == "gpt-5.4-all"
    assert pipeline.discovery_router.model == "gpt-5.4-all"
    assert pipeline.multipass_planner.model == "gpt-5.4-all"
    assert pipeline.backend.executor.model == "gpt-5.4-all"


def test_build_controlled_workspace_reuses_shared_helper_with_scenario_40_app(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runner.configure_shared_paths()
    scenario_app = tmp_path / "scenario_app"
    scenario_app.mkdir()
    (scenario_app / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(runner.base, "APP_DIR", scenario_app)

    workspace = tmp_path / "workspace"
    runner.base.build_controlled_workspace(workspace, _context())
    runner.base.validate_controlled_workspace(workspace)

    files = sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file())
    assert files == [
        "app/index.html",
        "brief/acceptance_criteria.md",
        "brief/prompt.md",
        "brief/task_sequence.md",
        "tasks/01_initial_scaffold.md",
    ]


def test_aggregate_provider_calls_by_role_and_model() -> None:
    calls = [
        {
            "role": "router",
            "model": "gpt-5.4",
            "input_tokens": 10,
            "cached_input_tokens": 0,
            "output_tokens": 2,
            "latency_ms": 100,
            "success": True,
        },
        {
            "role": "executor",
            "model": "gpt-5.4",
            "input_tokens": 20,
            "cached_input_tokens": None,
            "output_tokens": 5,
            "latency_ms": 200,
            "success": False,
        },
    ]

    aggregated = runner.aggregate_provider_calls_by_role(calls)

    assert aggregated["router"] == {
        "calls": 1,
        "models": ["gpt-5.4"],
        "input_tokens": 10,
        "cached_input_tokens": 0,
        "output_tokens": 2,
        "latency_ms": 100,
        "success_count": 1,
        "failure_count": 0,
    }
    assert aggregated["executor"]["models"] == ["gpt-5.4"]
    assert aggregated["executor"]["cached_input_tokens"] is None
    assert aggregated["executor"]["failure_count"] == 1
