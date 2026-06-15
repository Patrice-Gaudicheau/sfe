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


def write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


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


def test_install_script_retries_after_missing_venv_package(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    venv_dir = tmp_path / ".venv-install-test"

    write_executable(
        bin_dir / "fakepython",
        """#!/bin/sh
set -eu
STATE_DIR=${SFE_TEST_STATE_DIR:?}
REAL_PYTHON=${SFE_TEST_REAL_PYTHON:?}
if [ "${1:-}" = "-" ] || [ "${1:-}" = "-c" ]; then
    exec "$REAL_PYTHON" "$@"
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
    target=${3:?}
    if [ ! -f "$STATE_DIR/venv_ready" ]; then
        printf "ensurepip is not available\\n" >&2
        exit 1
    fi
    mkdir -p "$target/bin"
    cat > "$target/bin/python" <<'EOF'
#!/bin/sh
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
    exit 0
fi
exit 0
EOF
    chmod +x "$target/bin/python"
    exit 0
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "pip" ]; then
    exit 0
fi
exec "$REAL_PYTHON" "$@"
""",
    )
    write_executable(
        bin_dir / "sudo",
        """#!/bin/sh
exec "$@"
""",
    )
    write_executable(
        bin_dir / "apt",
        f"""#!/bin/sh
set -eu
printf "%s\\n" "$*" >> "{state_dir / 'apt.log'}"
if [ "${{1:-}}" = "install" ]; then
    : > "{state_dir / 'venv_ready'}"
fi
exit 0
""",
    )

    result = run_install(
        extra_env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SFE_INSTALL_ASSUME_YES": "1",
            "SFE_INSTALL_SKIP_AIDER": "1",
            "SFE_INSTALL_PYTHON_BIN": "fakepython",
            "SFE_INSTALL_VENV_DIR": str(venv_dir),
            "SFE_INSTALL_OS_ID": "ubuntu",
            "SFE_INSTALL_OS_LIKE": "debian",
            "SFE_TEST_REAL_PYTHON": shutil.which("python3") or shutil.which("python") or "",
            "SFE_TEST_STATE_DIR": str(state_dir),
        }
    )

    assert result.returncode == 0, result.stderr
    assert "usually means `python3-venv` is missing" in result.stdout
    assert "Run `sudo apt install python3-venv python3-pip` now and retry virtual environment creation? [auto-yes]" in result.stdout
    assert "+ sudo apt install python3-venv python3-pip" in result.stdout
    assert result.stdout.count("-m venv") >= 2
    assert (state_dir / "apt.log").read_text(encoding="utf-8").strip() == "install python3-venv python3-pip"


def test_install_script_assume_yes_does_not_auto_update_aider(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    venv_dir = tmp_path / ".venv-install-test"

    write_executable(
        bin_dir / "aider",
        """#!/bin/sh
printf "aider 1.0.0\\n"
""",
    )
    write_executable(
        bin_dir / "pipx",
        f"""#!/bin/sh
set -eu
printf "%s\\n" "$*" >> "{state_dir / 'pipx.log'}"
if [ "${{1:-}}" = "list" ]; then
    printf "package aider-chat 1.0.0\\n"
fi
exit 0
""",
    )

    result = run_install(
        extra_env={
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "SFE_INSTALL_ASSUME_YES": "1",
            "SFE_INSTALL_DRY_RUN": "1",
            "SFE_INSTALL_VENV_DIR": str(venv_dir),
            "SFE_INSTALL_AIDER_LATEST_VERSION": "9.9.9",
        }
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "Updates require an interactive confirmation or SFE_INSTALL_ALLOW_UPDATES=1." in combined
    assert "upgrade aider-chat [auto-yes]" not in combined
    assert "upgrade aider-chat" not in result.stdout
    assert (state_dir / "pipx.log").read_text(encoding="utf-8").strip() == "list"


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
