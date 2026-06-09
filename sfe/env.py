"""Small dependency-free .env loader for SFE runtime entrypoints."""

from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


def load_repo_env(path: str | Path | None = None) -> dict[str, str]:
    """Load KEY=value pairs from .env without overriding existing environment.

    When no explicit path is supplied, SFE first checks the launch working
    directory and then falls back to the installed project root.
    """
    env_path = _resolve_env_path(path)
    loaded: dict[str, str] = {}
    if env_path is None or not env_path.exists():
        return loaded

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        if key in os.environ:
            continue
        os.environ[key] = value
        loaded[key] = value
    return loaded


def _resolve_env_path(path: str | Path | None = None) -> Path | None:
    if path is not None:
        return Path(path)

    cwd_env_path = Path.cwd() / ".env"
    if cwd_env_path.exists():
        return cwd_env_path
    if DEFAULT_ENV_PATH.exists():
        return DEFAULT_ENV_PATH
    return cwd_env_path


def _parse_env_line(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or "=" not in stripped:
        return None

    key, value = stripped.split("=", 1)
    key = key.strip()
    if not key:
        return None

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return key, value
