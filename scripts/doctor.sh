#!/bin/sh

set -u

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT" || exit 1

VENV_DIR=${SFE_DOCTOR_VENV_DIR:-${SFE_INSTALL_VENV_DIR:-.venv}}
ENV_PATH=${SFE_DOCTOR_ENV_PATH:-.env}
AIDER_BIN=${SFE_DOCTOR_AIDER_BIN:-aider}
GIT_BIN=${SFE_DOCTOR_GIT_BIN:-git}
PYTHON_BIN_OVERRIDE=${SFE_DOCTOR_PYTHON_BIN:-}

find_command() {
    command -v "$1" 2>/dev/null || true
}

status() {
    state=$1
    label=$2
    detail=${3:-}
    if [ -n "$detail" ]; then
        printf "%-10s %-24s %s\n" "[$state]" "$label" "$detail"
    else
        printf "%-10s %s\n" "[$state]" "$label"
    fi
}

detect_python_bin() {
    if [ -n "$PYTHON_BIN_OVERRIDE" ]; then
        find_command "$PYTHON_BIN_OVERRIDE"
        return 0
    fi
    if [ -x "$VENV_DIR/bin/python" ]; then
        printf "%s\n" "$VENV_DIR/bin/python"
        return 0
    fi
    if [ -x "$VENV_DIR/Scripts/python.exe" ]; then
        printf "%s\n" "$VENV_DIR/Scripts/python.exe"
        return 0
    fi
    for candidate in python3 python; do
        resolved=$(find_command "$candidate")
        if [ -n "$resolved" ]; then
            printf "%s\n" "$resolved"
            return 0
        fi
    done
    return 0
}

resolve_minimum_python() {
    sed -n 's/^requires-python = ">=\([0-9][0-9.]*\)".*$/\1/p' pyproject.toml | head -n 1
}

check_python() {
    python_bin=$(detect_python_bin)
    minimum=$(resolve_minimum_python)
    if [ -z "$python_bin" ]; then
        status "missing" "Python" "Python $minimum+ is required"
        PYTHON_FOR_DOCTOR=
        return 0
    fi

    version=$("$python_bin" -c 'import sys; print(".".join(str(part) for part in sys.version_info[:3]))' 2>/dev/null || true)
    if [ -z "$version" ]; then
        status "warn" "Python" "$python_bin did not report a version"
        PYTHON_FOR_DOCTOR=$python_bin
        return 0
    fi

    if "$python_bin" - "$minimum" <<'PY' >/dev/null 2>&1
import sys

minimum = tuple(int(part) for part in sys.argv[1].split("."))
current = sys.version_info[: len(minimum)]
raise SystemExit(0 if current >= minimum else 1)
PY
    then
        status "ok" "Python" "$version at $python_bin"
    else
        status "missing" "Python" "$version at $python_bin; need $minimum+"
    fi
    PYTHON_FOR_DOCTOR=$python_bin
}

check_venv() {
    if [ -d "$VENV_DIR" ]; then
        status "ok" "Virtualenv" "$VENV_DIR"
    else
        status "missing" "Virtualenv" "run make install"
    fi
}

check_sfe_package() {
    if [ -z "${PYTHON_FOR_DOCTOR:-}" ]; then
        status "missing" "SFE package" "Python unavailable"
        return 0
    fi
    if "$PYTHON_FOR_DOCTOR" -c 'import sfe' >/dev/null 2>&1; then
        status "ok" "SFE package" "importable"
        return 0
    fi
    sfe_mcp_path=$(find_command sfe-mcp)
    if [ -n "$sfe_mcp_path" ]; then
        status "ok" "SFE CLI" "$sfe_mcp_path"
        return 0
    fi
    status "missing" "SFE package" "run make install"
}

check_command() {
    label=$1
    bin_name=$2
    missing_detail=$3
    resolved=$(find_command "$bin_name")
    if [ -n "$resolved" ]; then
        status "ok" "$label" "$resolved"
    else
        status "missing" "$label" "$missing_detail"
    fi
}

check_env_file() {
    if [ -f "$ENV_PATH" ]; then
        status "ok" ".env" "$ENV_PATH"
    else
        status "missing" ".env" "make install can create it from .env.example"
    fi
}

has_provider_in_process_env() {
    for name in \
        SFE_PROVIDER SFE_PROVIDER_ROUTER SFE_PROVIDER_DISCOVERY SFE_PROVIDER_EXECUTOR \
        OPENAI_API_KEY ANTHROPIC_API_KEY GOOGLE_API_KEY ALIBABA_API_KEY \
        SFE_LEMONADE_API_KEY SFE_LEMONADE_BASE_URL SFE_OLLAMA_BASE_URL
    do
        eval "value=\${$name:-}"
        if [ -n "$value" ]; then
            return 0
        fi
    done
    return 1
}

has_provider_in_env_file() {
    [ -f "$ENV_PATH" ] || return 1
    grep -Eq '^[[:space:]]*(SFE_PROVIDER|SFE_PROVIDER_ROUTER|SFE_PROVIDER_DISCOVERY|SFE_PROVIDER_EXECUTOR)[[:space:]]*=[[:space:]]*[^[:space:]#]+' "$ENV_PATH" && return 0
    grep -Eq '^[[:space:]]*(OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY|ALIBABA_API_KEY|SFE_LEMONADE_API_KEY)[[:space:]]*=[[:space:]]*[^[:space:]#]+' "$ENV_PATH" && return 0
    return 1
}

check_provider() {
    if has_provider_in_process_env || has_provider_in_env_file; then
        status "ok" "Provider config" "at least one provider appears configured"
    else
        status "missing" "Provider config" "edit .env and set one provider"
    fi
}

log_header() {
    printf "%s\n" "SFE doctor"
    printf "%s\n" "----------"
}

log_header
check_python
check_venv
check_sfe_package
check_command "Git" "$GIT_BIN" "install Git for repository workflows"
check_command "Aider" "$AIDER_BIN" "pipx install aider-chat"
check_env_file
check_provider

printf "\n%s\n" "Doctor completed. Missing items above are next steps, not installer failures."
