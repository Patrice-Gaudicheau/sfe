from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = PROJECT_ROOT / "scripts" / "run_notekeeper_baseline_openai.py"

spec = importlib.util.spec_from_file_location("notekeeper_baseline_runner", RUNNER_PATH)
assert spec is not None
runner = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runner
assert spec.loader is not None
spec.loader.exec_module(runner)


def _valid_snapshot_json() -> str:
    return (
        "{"
        '"files": ['
        '{"path": "index.html", "content": "<!doctype html>"},'
        '{"path": "styles.css", "content": "body {}"},'
        '{"path": "app.js", "content": "console.log(1);"},'
        '{"path": "README.md", "content": "# NoteKeeper"}'
        '], "notes": "ok"}'
    )


def test_parse_model_snapshot_accepts_exact_required_files() -> None:
    snapshot = runner.parse_model_snapshot(_valid_snapshot_json())

    assert tuple(snapshot.files) == runner.REQUIRED_APP_FILES
    assert snapshot.files["index.html"] == "<!doctype html>"
    assert snapshot.notes == "ok"


@pytest.mark.parametrize(
    "path",
    [
        "/tmp/index.html",
        "../index.html",
        "nested/index.html",
        "nested\\index.html",
        "package.json",
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

    with pytest.raises(runner.NoteKeeperBaselineError):
        runner.parse_model_snapshot(payload)


def test_parse_model_snapshot_rejects_missing_file() -> None:
    payload = (
        "{"
        '"files": ['
        '{"path": "index.html", "content": ""},'
        '{"path": "styles.css", "content": ""},'
        '{"path": "app.js", "content": ""}'
        "]}"
    )

    with pytest.raises(runner.NoteKeeperBaselineError, match="missing files"):
        runner.parse_model_snapshot(payload)


def test_parse_model_snapshot_rejects_malformed_json() -> None:
    with pytest.raises(runner.NoteKeeperBaselineError, match="strict JSON"):
        runner.parse_model_snapshot("```json\n{}\n```")


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
    assert "api_called: false" in result.stdout
