from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.sh"


def run_install(*, extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env)
    return subprocess.run(
        ["/bin/sh", str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_install_script_is_shell_syntax_safe() -> None:
    result = subprocess.run(
        ["/bin/sh", "-n", str(SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_install_script_dry_run_uses_editable_install(tmp_path: Path) -> None:
    venv_dir = tmp_path / ".venv-install-test"
    result = run_install(
        extra_env={
            "SFE_INSTALL_DRY_RUN": "1",
            "SFE_INSTALL_SKIP_AIDER": "1",
            "SFE_INSTALL_VENV_DIR": str(venv_dir),
        }
    )

    assert result.returncode == 0, result.stderr
    assert "Using Python interpreter:" in result.stdout
    assert "Checking Python version against pyproject.toml (>= 3.10)." in result.stdout
    assert "+ " in result.stdout
    assert f" -m venv {venv_dir}" in result.stdout
    assert f"{venv_dir}/bin/python -m pip install --disable-pip-version-check -e ." in result.stdout
    assert "Skipping Aider checks because SFE_INSTALL_SKIP_AIDER=1." in result.stdout


def test_install_script_missing_python_reports_help() -> None:
    result = run_install(
        extra_env={
            "SFE_INSTALL_DRY_RUN": "1",
            "SFE_INSTALL_PYTHON_BIN": "python-does-not-exist",
            "SFE_INSTALL_SKIP_AIDER": "1",
        }
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Python 3.10+ is required for SFE" in combined
    assert "sudo apt install python3 python3-venv python3-pip" in combined
    assert "python-does-not-exist" in combined


def test_install_script_noninteractive_missing_aider_fails_safely(tmp_path: Path) -> None:
    if shutil.which("pipx") is None:
        pytest.skip("pipx is not available in this environment")

    venv_dir = tmp_path / ".venv-install-test"
    result = run_install(
        extra_env={
            "SFE_INSTALL_DRY_RUN": "1",
            "SFE_INSTALL_VENV_DIR": str(venv_dir),
            "SFE_INSTALL_AIDER_BIN": "aider-does-not-exist",
        }
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 1
    assert "Aider is not currently available on PATH." in combined
    assert "pipx install aider-chat" in combined
    assert "non-interactive" in combined


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_makefile_declares_install_target() -> None:
    result = subprocess.run(
        ["make", "-n", "install"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert result.returncode == 0, result.stderr
    assert "./scripts/install.sh" in result.stdout
