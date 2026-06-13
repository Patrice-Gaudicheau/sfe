from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_solarsystem3d_sfe_split_model_multipass_openai.py"

spec = importlib.util.spec_from_file_location("solarsystem3d_sfe_split_model_multipass_runner", RUNNER_PATH)
assert spec is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
assert spec.loader is not None
spec.loader.exec_module(runner)


def test_scenario_mapping_and_expected_app_targets() -> None:
    assert runner.SCENARIO_DIR == (
        PROJECT_ROOT
        / "examples"
        / "SolarSystem3D"
        / "30_sfe_split_gpt54_router_gpt54mini_executor_multipass"
    )
    assert runner.REQUIRED_APP_FILES == ("index.html", "styles.css", "app.js", "README.md")
    assert runner.ALLOWED_WORKSPACE_APP_FILES == (
        "app/index.html",
        "app/styles.css",
        "app/app.js",
        "app/README.md",
    )


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
    assert "scenario: sfe_split_gpt54_router_gpt54mini_executor_multipass" in result.stdout
    assert "router_model: gpt-5.4" in result.stdout
    assert "discovery_model: gpt-5.4" in result.stdout
    assert "executor_model: gpt-5.4-mini" in result.stdout
    assert "multipass_planner_model: gpt-5.4" in result.stdout
    assert "task_count: 8" in result.stdout
    assert "multipass_forced_auto: true" in result.stdout
    assert "api_called: false" in result.stdout


def test_validate_args_accepts_split_model_overrides() -> None:
    class Args:
        router_model = "router-x"
        discovery_model = "discovery-y"
        executor_model = "executor-z"
        timeout = 12
        dry_run_validate_inputs = True

    config = runner._validate_args(Args())

    assert config["router_model"] == "router-x"
    assert config["discovery_model"] == "discovery-y"
    assert config["executor_model"] == "executor-z"
    assert config["multipass_planner_model"] == "router-x"
    assert config["timeout"] == 12.0


def test_force_sfe_environment_uses_openai_split_models_and_multipass_auto() -> None:
    config = {
        "router_model": "gpt-5.4",
        "discovery_model": "gpt-5.4-discovery",
        "executor_model": "gpt-5.4-mini",
    }

    environ = runner.force_sfe_environment(config)

    assert environ["SFE_PROVIDER_ROUTER"] == "openai"
    assert environ["SFE_PROVIDER_DISCOVERY"] == "openai"
    assert environ["SFE_PROVIDER_EXECUTOR"] == "openai"
    assert environ["SFE_OPENAI_ROUTER_MODEL"] == "gpt-5.4"
    assert environ["SFE_OPENAI_DISCOVERY_MODEL"] == "gpt-5.4-discovery"
    assert environ["SFE_OPENAI_EXECUTOR_MODEL"] == "gpt-5.4-mini"
    assert environ["SFE_WORKSPACE_WRITE_MULTIPASS"] == "auto"


def test_configure_shared_paths_maps_base_helper_to_split_scenario() -> None:
    runner.configure_shared_paths()

    assert runner.base.SCENARIO_DIR == runner.SCENARIO_DIR
    assert runner.base.APP_DIR == runner.APP_DIR
    assert runner.base.RUNS_DIR == runner.RUNS_DIR
    assert runner.base.TOKEN_USAGE_PATH == runner.TOKEN_USAGE_PATH
    assert runner.base.REPORT_PATH == runner.REPORT_PATH

