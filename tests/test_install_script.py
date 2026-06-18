from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install.sh"
DOCTOR_SCRIPT = ROOT / "scripts" / "doctor.sh"


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
    env_path = tmp_path / ".env"
    result = run_install(
        extra_env={
            "SFE_INSTALL_DRY_RUN": "1",
            "SFE_INSTALL_SKIP_AIDER": "1",
            "SFE_INSTALL_VENV_DIR": str(venv_dir),
            "SFE_INSTALL_ENV_PATH": str(env_path),
        }
    )

    assert result.returncode == 0, result.stderr
    assert "Using Python interpreter:" in result.stdout
    assert "Checking Python version against pyproject.toml (>= 3.10)." in result.stdout
    assert "+ " in result.stdout
    assert f" -m venv {venv_dir}" in result.stdout
    assert f"{venv_dir}/bin/python -m pip install --disable-pip-version-check -e ." in result.stdout
    assert f"+ cp .env.example {env_path}" in result.stdout
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


def test_install_script_creates_env_from_example_only_when_absent(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    venv_dir = tmp_path / ".venv-install-test"
    env_path = tmp_path / ".env"
    env_example_path = tmp_path / ".env.example"
    env_example_path.write_text("SFE_PROVIDER=openai\n", encoding="utf-8")

    write_executable(
        bin_dir / "fakepython",
        """#!/bin/sh
set -eu
REAL_PYTHON=${SFE_TEST_REAL_PYTHON:?}
if [ "${1:-}" = "-" ] || [ "${1:-}" = "-c" ]; then
    exec "$REAL_PYTHON" "$@"
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "venv" ]; then
    target=${3:?}
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
exec "$REAL_PYTHON" "$@"
""",
    )

    common_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SFE_INSTALL_SKIP_AIDER": "1",
        "SFE_INSTALL_PYTHON_BIN": "fakepython",
        "SFE_INSTALL_VENV_DIR": str(venv_dir),
        "SFE_INSTALL_ENV_PATH": str(env_path),
        "SFE_INSTALL_ENV_EXAMPLE_PATH": str(env_example_path),
        "SFE_TEST_REAL_PYTHON": shutil.which("python3") or shutil.which("python") or "",
    }

    first = run_install(extra_env=common_env)
    assert first.returncode == 0, first.stderr
    assert env_path.read_text(encoding="utf-8") == "SFE_PROVIDER=openai\n"

    env_path.write_text("SFE_PROVIDER=anthropic\n", encoding="utf-8")
    env_example_path.write_text("SFE_PROVIDER=google\n", encoding="utf-8")
    second = run_install(extra_env=common_env)
    assert second.returncode == 0, second.stderr
    assert "Keeping existing" in second.stdout
    assert env_path.read_text(encoding="utf-8") == "SFE_PROVIDER=anthropic\n"


def test_install_script_noninteractive_missing_aider_continues(tmp_path: Path) -> None:
    venv_dir = tmp_path / ".venv-install-test"
    result = run_install(
        extra_env={
            "SFE_INSTALL_DRY_RUN": "1",
            "SFE_INSTALL_VENV_DIR": str(venv_dir),
            "SFE_INSTALL_AIDER_BIN": "aider-does-not-exist",
            "SFE_INSTALL_ENV_PATH": str(tmp_path / ".env"),
        }
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0
    assert "Aider is not currently available on PATH." in combined
    assert "Aider is required for normal SFE workspace_write runs." in combined
    assert "pipx install aider-chat" in combined
    assert "Continuing without Aider." in combined


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


def test_install_script_aider_install_requires_specific_opt_in(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    venv_dir = tmp_path / ".venv-install-test"

    write_executable(
        bin_dir / "pipx",
        f"""#!/bin/sh
set -eu
printf "%s\\n" "$*" >> "{state_dir / 'pipx.log'}"
exit 0
""",
    )

    base_env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SFE_INSTALL_DRY_RUN": "1",
        "SFE_INSTALL_ASSUME_YES": "1",
        "SFE_INSTALL_VENV_DIR": str(venv_dir),
        "SFE_INSTALL_AIDER_BIN": "aider-does-not-exist",
        "SFE_INSTALL_ENV_PATH": str(tmp_path / ".env"),
    }

    no_opt_in = run_install(extra_env=base_env)
    assert no_opt_in.returncode == 0, no_opt_in.stderr
    if (state_dir / "pipx.log").exists():
        assert "install aider-chat" not in (state_dir / "pipx.log").read_text(
            encoding="utf-8"
        )
    assert "Continuing without Aider." in no_opt_in.stdout

    with_opt_in = run_install(extra_env={**base_env, "SFE_INSTALL_AIDER": "1"})
    assert with_opt_in.returncode == 0, with_opt_in.stderr
    assert "+ " in with_opt_in.stdout
    assert " install aider-chat" in with_opt_in.stdout


def test_install_script_pipx_install_requires_specific_opt_in(tmp_path: Path) -> None:
    venv_dir = tmp_path / ".venv-install-test"
    env_path = tmp_path / ".env"
    result = run_install(
        extra_env={
            "SFE_INSTALL_DRY_RUN": "1",
            "SFE_INSTALL_ASSUME_YES": "1",
            "SFE_INSTALL_PIPX": "1",
            "SFE_INSTALL_AIDER": "1",
            "SFE_INSTALL_PIPX_BIN": "pipx-does-not-exist",
            "SFE_INSTALL_AIDER_BIN": "aider-does-not-exist",
            "SFE_INSTALL_VENV_DIR": str(venv_dir),
            "SFE_INSTALL_ENV_PATH": str(env_path),
        }
    )

    assert result.returncode == 0, result.stderr
    assert "Install pipx now with" in result.stdout
    assert "auto-yes via SFE_INSTALL_PIPX=1" in result.stdout
    assert " -m pip install --user pipx" in result.stdout
    assert "sudo apt install pipx" not in result.stdout


def test_doctor_reports_missing_components_without_crashing(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/bin/sh", str(DOCTOR_SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ.copy(),
            "SFE_DOCTOR_ENV_PATH": str(tmp_path / "missing.env"),
            "SFE_DOCTOR_VENV_DIR": str(tmp_path / "missing-venv"),
            "SFE_DOCTOR_AIDER_BIN": "aider-does-not-exist",
            "SFE_DOCTOR_GIT_BIN": "git-does-not-exist",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "SFE doctor" in result.stdout
    assert "[missing]  Virtualenv" in result.stdout
    assert "[missing]  Git" in result.stdout
    assert "[missing]  Aider" in result.stdout
    assert "[missing]  .env" in result.stdout


def test_doctor_warns_when_codexcli_lacks_aider_provider(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "SFE_PROVIDER=codexcli",
                "OPENAI_API_KEY=SECRET_VALUE_THAT_MUST_NOT_LEAK",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SFE_")
        and key
        not in {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "ALIBABA_API_KEY",
        }
    }
    env.update(
        {
            "SFE_DOCTOR_ENV_PATH": str(env_path),
            "SFE_DOCTOR_VENV_DIR": str(tmp_path / "missing-venv"),
            "SFE_DOCTOR_AIDER_BIN": "aider-does-not-exist",
        }
    )

    result = subprocess.run(
        ["/bin/sh", str(DOCTOR_SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "[warn]" in result.stdout
    assert "Aider config" in result.stdout
    assert "unsupported_aider_provider" in result.stdout
    assert "provider source: SFE_PROVIDER=codexcli" in result.stdout
    assert "Aider cannot use CodexCLI as its LLM backend." in result.stdout
    assert "SECRET_VALUE_THAT_MUST_NOT_LEAK" not in result.stdout
    assert "OPENAI_API_KEY=" not in result.stdout


def test_doctor_reports_missing_aider_env_names_only(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "SFE_PROVIDER=lemonade",
                "SFE_AIDER_PROVIDER=lemonade",
                "SFE_LEMONADE_BASE_URL=http://secret-local-host.invalid",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("SFE_")
        and key
        not in {
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GOOGLE_API_KEY",
            "ALIBABA_API_KEY",
        }
    }
    env.update(
        {
            "SFE_DOCTOR_ENV_PATH": str(env_path),
            "SFE_DOCTOR_VENV_DIR": str(tmp_path / "missing-venv"),
        }
    )

    result = subprocess.run(
        ["/bin/sh", str(DOCTOR_SCRIPT)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "[warn]" in result.stdout
    assert "Aider config" in result.stdout
    assert "missing variables: SFE_AIDER_MODEL" in result.stdout
    assert "openai/Gemma-4-E4B-it-GGUF" in result.stdout
    assert "http://secret-local-host.invalid" not in result.stdout


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


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_makefile_declares_doctor_target() -> None:
    result = subprocess.run(
        ["make", "-n", "doctor"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert result.returncode == 0, result.stderr
    assert "./scripts/doctor.sh" in result.stdout
