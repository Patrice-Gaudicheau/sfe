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

check_aider_config() {
    if [ -z "${PYTHON_FOR_DOCTOR:-}" ]; then
        status "warn" "Aider config" "Python unavailable; skipped"
        return 0
    fi

    output=$(
        SFE_DOCTOR_ENV_PATH="$ENV_PATH" "$PYTHON_FOR_DOCTOR" <<'PY' 2>/dev/null
import os

from sfe.aider_env_bridge import resolve_aider_env_bridge
from sfe.env import load_repo_env


def display(raw):
    return "unknown" if raw is None else str(raw)


load_repo_env(os.environ["SFE_DOCTOR_ENV_PATH"])
result = resolve_aider_env_bridge()
diagnostics = result.diagnostics
state = "ok" if result.ok else "warn"
detail = (
    f"provider {result.provider_name}"
    if result.ok
    else f"{result.error_category or 'aider_env_bridge_failed'}"
)
print(f"STATE\t{state}\t{detail}")
print(
    "DETAIL\tprovider source: "
    f"{display(diagnostics.get('provider_source_env_var'))}="
    f"{display(diagnostics.get('provider_source_value'))}"
)
print(f"DETAIL\tselected model: {display(result.selected_model)}")
model_source = diagnostics.get("model_source_env_var")
model_value = diagnostics.get("model_source_value")
print(f"DETAIL\tmodel source: {display(model_source)}={display(model_value)}")
missing = tuple(result.missing_variables)
if missing:
    print(f"DETAIL\tmissing variables: {', '.join(missing)}")
note = diagnostics.get("codexcli_aider_note")
if note:
    print(f"DETAIL\tnote: {note}")
guidance = diagnostics.get("model_guidance")
if guidance:
    print(f"DETAIL\tmodel guidance: {guidance}")
PY
    ) || {
        status "warn" "Aider config" "unable to inspect Aider provider config"
        return 0
    }

    state=warn
    detail="unable to inspect Aider provider config"
    details=
    while IFS='	' read -r kind first rest; do
        if [ "$kind" = "STATE" ]; then
            state=$first
            detail=$rest
        elif [ "$kind" = "DETAIL" ]; then
            details="${details}${first}
"
        fi
    done <<EOF
$output
EOF

    status "$state" "Aider config" "$detail"
    if [ -n "$details" ]; then
        printf "%s" "$details" | while IFS= read -r line; do
            [ -n "$line" ] || continue
            printf "           %-24s %s\n" "" "$line"
        done
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
check_aider_config

printf "\n%s\n" "Doctor completed. Missing items above are next steps, not installer failures."
