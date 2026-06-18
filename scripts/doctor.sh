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

render_status_details() {
    output=$1
    state=warn
    detail="unable to inspect provider config"
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

    status "$state" "$2" "$detail"
    if [ -n "$details" ]; then
        printf "%s" "$details" | while IFS= read -r line; do
            [ -n "$line" ] || continue
            printf "           %-24s %s\n" "" "$line"
        done
    fi
}

check_sfe_models() {
    if [ -z "${PYTHON_FOR_DOCTOR:-}" ]; then
        status "warn" "SFE models" "Python unavailable; skipped"
        return 0
    fi

    output=$(
        SFE_DOCTOR_ENV_PATH="$ENV_PATH" "$PYTHON_FOR_DOCTOR" <<'PY' 2>/dev/null
import os

from providers.alibaba import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_ALIBABA_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_ALIBABA_ROUTER_MODEL,
)
from providers.anthropic import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_ANTHROPIC_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_ANTHROPIC_ROUTER_MODEL,
)
from providers.codexcli import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_CODEXCLI_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_CODEXCLI_ROUTER_MODEL,
)
from providers.google import DEFAULT_MODEL as DEFAULT_GOOGLE_MODEL
from providers.ollama import DEFAULT_MODEL as DEFAULT_OLLAMA_MODEL
from providers.openai_api import (
    DEFAULT_EXECUTOR_MODEL as DEFAULT_OPENAI_EXECUTOR_MODEL,
    DEFAULT_ROUTER_MODEL as DEFAULT_OPENAI_ROUTER_MODEL,
)
from sfe.discovery_router import DEFAULT_LEMONADE_DISCOVERY_MODEL
from sfe.env import load_repo_env
from sfe.execution_mode_router import DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL
from sfe.provider_config import (
    CODEXCLI_SFE_PROVIDER,
    OLLAMA_SFE_PROVIDER,
    SFE_PROVIDER_ENV,
    SFE_PROVIDER_DISCOVERY_ENV,
    SFE_PROVIDER_EXECUTOR_ENV,
    SFE_PROVIDER_ROUTER_ENV,
    normalize_provider_name,
    resolve_sfe_discovery_provider,
    resolve_sfe_executor_provider,
    resolve_sfe_provider,
    resolve_sfe_router_provider,
)
from sfe_tui.executors import DEFAULT_LEMONADE_EXECUTOR_MODEL


def env_value(name):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    return raw.strip()


def display(raw):
    return "unknown" if raw is None else str(raw)


def first_env(names):
    for name in names:
        value = env_value(name)
        if value is not None:
            return value, name
    return None, None


def provider_source(role_env_name):
    role_value = env_value(role_env_name)
    if role_value is not None:
        return role_env_name, role_value
    shared_value = env_value(SFE_PROVIDER_ENV)
    if shared_value is not None:
        return SFE_PROVIDER_ENV, shared_value
    return "default", "openai"


def discovery_provider_source():
    discovery_value = env_value(SFE_PROVIDER_DISCOVERY_ENV)
    if discovery_value is not None:
        return SFE_PROVIDER_DISCOVERY_ENV, discovery_value
    return provider_source(SFE_PROVIDER_ROUTER_ENV)


MODEL_RULES = {
    "router": {
        "openai": (("SFE_OPENAI_ROUTER_MODEL",), DEFAULT_OPENAI_ROUTER_MODEL),
        "openai-compatible": (("SFE_OPENAI_ROUTER_MODEL",), DEFAULT_OPENAI_ROUTER_MODEL),
        CODEXCLI_SFE_PROVIDER: (
            ("SFE_CODEXCLI_ROUTER_MODEL",),
            DEFAULT_CODEXCLI_ROUTER_MODEL,
        ),
        "lemonade": (
            ("SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"),
            DEFAULT_LEMONADE_EXECUTION_MODE_ROUTER_MODEL,
        ),
        "alibaba": (("SFE_ALIBABA_ROUTER_MODEL",), DEFAULT_ALIBABA_ROUTER_MODEL),
        "anthropic": (
            ("SFE_ANTHROPIC_ROUTER_MODEL",),
            DEFAULT_ANTHROPIC_ROUTER_MODEL,
        ),
        OLLAMA_SFE_PROVIDER: (
            ("SFE_OLLAMA_ROUTER_MODEL", "SFE_OLLAMA_MODEL"),
            DEFAULT_OLLAMA_MODEL,
        ),
    },
    "discovery": {
        "openai": (
            ("SFE_OPENAI_DISCOVERY_MODEL", "SFE_OPENAI_ROUTER_MODEL"),
            DEFAULT_OPENAI_ROUTER_MODEL,
        ),
        "openai-compatible": (
            ("SFE_OPENAI_DISCOVERY_MODEL", "SFE_OPENAI_ROUTER_MODEL"),
            DEFAULT_OPENAI_ROUTER_MODEL,
        ),
        CODEXCLI_SFE_PROVIDER: (
            ("SFE_CODEXCLI_DISCOVERY_MODEL", "SFE_CODEXCLI_ROUTER_MODEL"),
            DEFAULT_CODEXCLI_ROUTER_MODEL,
        ),
        "lemonade": (
            ("SFE_LEMONADE_DISCOVERY_MODEL", "SFE_ROUTER_MODEL", "SFE_LEMONADE_MODEL"),
            DEFAULT_LEMONADE_DISCOVERY_MODEL,
        ),
        "alibaba": (
            ("SFE_ALIBABA_DISCOVERY_MODEL", "SFE_ALIBABA_ROUTER_MODEL"),
            DEFAULT_ALIBABA_ROUTER_MODEL,
        ),
        "anthropic": (
            ("SFE_ANTHROPIC_DISCOVERY_MODEL", "SFE_ANTHROPIC_ROUTER_MODEL"),
            DEFAULT_ANTHROPIC_ROUTER_MODEL,
        ),
        "google": (
            ("SFE_GOOGLE_DISCOVERY_MODEL", "SFE_GOOGLE_MODEL"),
            DEFAULT_GOOGLE_MODEL,
        ),
        OLLAMA_SFE_PROVIDER: (
            (
                "SFE_OLLAMA_DISCOVERY_MODEL",
                "SFE_OLLAMA_ROUTER_MODEL",
                "SFE_OLLAMA_MODEL",
            ),
            DEFAULT_OLLAMA_MODEL,
        ),
    },
    "executor": {
        "openai": (("SFE_OPENAI_EXECUTOR_MODEL",), DEFAULT_OPENAI_EXECUTOR_MODEL),
        "openai-compatible": (
            ("SFE_OPENAI_EXECUTOR_MODEL",),
            DEFAULT_OPENAI_EXECUTOR_MODEL,
        ),
        CODEXCLI_SFE_PROVIDER: (
            ("SFE_CODEXCLI_EXECUTOR_MODEL",),
            DEFAULT_CODEXCLI_EXECUTOR_MODEL,
        ),
        "lemonade": (
            ("SFE_LEMONADE_EXECUTOR_MODEL", "SFE_LEMONADE_MODEL", "SFE_EXECUTOR_MODEL"),
            DEFAULT_LEMONADE_EXECUTOR_MODEL,
        ),
        "alibaba": (("SFE_ALIBABA_EXECUTOR_MODEL",), DEFAULT_ALIBABA_EXECUTOR_MODEL),
        "anthropic": (
            ("SFE_ANTHROPIC_EXECUTOR_MODEL",),
            DEFAULT_ANTHROPIC_EXECUTOR_MODEL,
        ),
        "google": (("SFE_GOOGLE_MODEL",), DEFAULT_GOOGLE_MODEL),
        OLLAMA_SFE_PROVIDER: (
            ("SFE_OLLAMA_EXECUTOR_MODEL", "SFE_OLLAMA_MODEL"),
            DEFAULT_OLLAMA_MODEL,
        ),
    },
}


def model_summary(role, provider):
    rules = MODEL_RULES[role].get(provider)
    if rules is None:
        return None, None
    names, default = rules
    value, source = first_env(names)
    if value is not None:
        return value, source
    return default, "default"


load_repo_env(os.environ["SFE_DOCTOR_ENV_PATH"])
try:
    shared_provider = resolve_sfe_provider(default="openai")
    roles = (
        ("router", resolve_sfe_router_provider(default="openai"), provider_source(SFE_PROVIDER_ROUTER_ENV)),
        (
            "discovery",
            resolve_sfe_discovery_provider(default="openai"),
            discovery_provider_source(),
        ),
        (
            "executor",
            resolve_sfe_executor_provider(default="openai"),
            provider_source(SFE_PROVIDER_EXECUTOR_ENV),
        ),
    )
except ValueError as exc:
    print(f"STATE\twarn\t{exc}")
    raise SystemExit(0)

shared_source = provider_source(SFE_PROVIDER_ENV)
print(f"STATE\tok\tprovider {shared_provider}")
print(f"DETAIL\tprovider source: {shared_source[0]}={normalize_provider_name(shared_source[1])}")
for role, provider, source in roles:
    print(f"DETAIL\t{role} provider: {provider}")
    print(f"DETAIL\t{role} provider source: {source[0]}={normalize_provider_name(source[1])}")
    model, model_source = model_summary(role, provider)
    if model is not None:
        print(f"DETAIL\t{role} model: {display(model)}")
        print(f"DETAIL\t{role} model source: {display(model_source)}")
PY
    ) || {
        status "warn" "SFE models" "unable to inspect SFE provider config"
        return 0
    }

    render_status_details "$output" "SFE models"
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

    render_status_details "$output" "Aider config"
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
check_sfe_models
check_aider_config

printf "\n%s\n" "Doctor completed. Missing items above are next steps, not installer failures."
