#!/bin/sh

set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

ASSUME_YES=${SFE_INSTALL_ASSUME_YES:-0}
ALLOW_UPDATES=${SFE_INSTALL_ALLOW_UPDATES:-0}
DRY_RUN=${SFE_INSTALL_DRY_RUN:-0}
SKIP_AIDER=${SFE_INSTALL_SKIP_AIDER:-0}
VENV_DIR=${SFE_INSTALL_VENV_DIR:-.venv}
PYTHON_BIN_OVERRIDE=${SFE_INSTALL_PYTHON_BIN:-}
AIDER_BIN=${SFE_INSTALL_AIDER_BIN:-aider}
PIPX_BIN=${SFE_INSTALL_PIPX_BIN:-pipx}
AIDER_LATEST_VERSION_OVERRIDE=${SFE_INSTALL_AIDER_LATEST_VERSION:-}
OS_ID_OVERRIDE=${SFE_INSTALL_OS_ID:-}
OS_LIKE_OVERRIDE=${SFE_INSTALL_OS_LIKE:-}
PROC_VERSION_OVERRIDE=${SFE_INSTALL_PROC_VERSION:-}
PYTHON_BIN_RESOLVED=

log() {
    printf "%s\n" "$*"
}

warn() {
    printf "warning: %s\n" "$*" >&2
}

die() {
    printf "error: %s\n" "$*" >&2
    exit 1
}

is_enabled() {
    case "${1:-0}" in
        1|true|TRUE|yes|YES|on|ON)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

can_prompt() {
    if is_enabled "$ASSUME_YES"; then
        return 0
    fi
    [ -t 0 ] && [ -t 1 ]
}

can_interactively_prompt() {
    [ -t 0 ] && [ -t 1 ]
}

confirm() {
    prompt=$1
    if is_enabled "$ASSUME_YES"; then
        log "$prompt [auto-yes]"
        return 0
    fi
    if ! can_prompt; then
        return 1
    fi
    printf "%s [y/N] " "$prompt"
    read -r answer || return 1
    case "$answer" in
        y|Y|yes|YES)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

confirm_update() {
    prompt=$1
    if is_enabled "$ALLOW_UPDATES"; then
        log "$prompt [auto-yes via SFE_INSTALL_ALLOW_UPDATES=1]"
        return 0
    fi
    if ! can_interactively_prompt; then
        return 1
    fi
    printf "%s [y/N] " "$prompt"
    read -r answer || return 1
    case "$answer" in
        y|Y|yes|YES)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

run_cmd() {
    log "+ $*"
    if is_enabled "$DRY_RUN"; then
        return 0
    fi
    "$@"
}

read_os_release_value() {
    key=$1
    if [ "$key" = "ID" ] && [ -n "$OS_ID_OVERRIDE" ]; then
        printf "%s\n" "$OS_ID_OVERRIDE"
        return 0
    fi
    if [ "$key" = "ID_LIKE" ] && [ -n "$OS_LIKE_OVERRIDE" ]; then
        printf "%s\n" "$OS_LIKE_OVERRIDE"
        return 0
    fi
    if [ ! -r /etc/os-release ]; then
        return 0
    fi
    sed -n "s/^${key}=//p" /etc/os-release | head -n 1 | tr -d '"'
}

is_debian_like() {
    os_id=$(read_os_release_value ID)
    os_like=$(read_os_release_value ID_LIKE)
    case "$os_id:$os_like" in
        debian:*|ubuntu:*|*:debian*|*:ubuntu*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

is_wsl() {
    if [ -n "$PROC_VERSION_OVERRIDE" ]; then
        version_text=$PROC_VERSION_OVERRIDE
    else
        if [ ! -r /proc/version ]; then
            return 1
        fi
        version_text=$(cat /proc/version 2>/dev/null || true)
    fi
    case "$version_text" in
        *icrosoft*|*Microsoft*|*WSL*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

find_command() {
    command -v "$1" 2>/dev/null || true
}

show_python_install_help() {
    log "Python 3.10+ is required for SFE, but no usable Python interpreter was found."
    log "Suggested commands:"
    if is_debian_like || is_wsl; then
        log "  sudo apt install python3 python3-venv python3-pip"
    fi
    log "  python3 --version"
    log "  python --version"
}

run_apt() {
    if [ "$(id -u)" -eq 0 ]; then
        run_cmd apt "$@"
    else
        run_cmd sudo apt "$@"
    fi
}

install_apt_packages() {
    if run_apt install "$@"; then
        return 0
    fi

    warn "The apt install command did not succeed."
    if confirm "Run \`sudo apt update\` and retry? This refreshes package metadata only; it does not upgrade packages."; then
        run_apt update
        run_apt install "$@"
        return 0
    fi
    return 1
}

detect_python_bin() {
    if [ -n "$PYTHON_BIN_OVERRIDE" ]; then
        find_command "$PYTHON_BIN_OVERRIDE"
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

ensure_python_available() {
    resolved_python=$(detect_python_bin)
    if [ -n "$resolved_python" ]; then
        PYTHON_BIN_RESOLVED=$resolved_python
        return 0
    fi

    show_python_install_help
    if [ -n "$PYTHON_BIN_OVERRIDE" ]; then
        die "The requested interpreter '$PYTHON_BIN_OVERRIDE' was not found on PATH."
    fi

    if ! is_debian_like && ! is_wsl; then
        die "Install Python 3.10+ and rerun make install."
    fi

    if ! can_prompt; then
        die "Python is missing and this session is non-interactive, so no system install command was run."
    fi

    if ! confirm "Run \`sudo apt install python3 python3-venv python3-pip\` now?"; then
        die "Python remains unavailable. Install it manually, then rerun make install."
    fi

    if ! install_apt_packages python3 python3-venv python3-pip; then
        die "Python remains unavailable after the requested apt install attempt."
    fi

    resolved_python=$(detect_python_bin)
    if [ -z "$resolved_python" ]; then
        die "Python still was not found after installation. Open a new shell if PATH changed, then rerun make install."
    fi
    PYTHON_BIN_RESOLVED=$resolved_python
}

check_python_version() {
    python_bin=$1
    minimum_python=$2
    if [ -z "$minimum_python" ]; then
        return 0
    fi

    if "$python_bin" - "$minimum_python" <<'PY'
import sys

minimum = tuple(int(part) for part in sys.argv[1].split("."))
current = sys.version_info[: len(minimum)]
raise SystemExit(0 if current >= minimum else 1)
PY
    then
        return 0
    fi

    current_python=$("$python_bin" -c 'import sys; print(".".join(str(part) for part in sys.version_info[:3]))')
    die "SFE requires Python $minimum_python or newer, but $python_bin reports $current_python."
}

venv_python_path() {
    venv_dir=$1
    if [ -x "$venv_dir/bin/python" ]; then
        printf "%s\n" "$venv_dir/bin/python"
        return 0
    fi
    if [ -x "$venv_dir/Scripts/python.exe" ]; then
        printf "%s\n" "$venv_dir/Scripts/python.exe"
        return 0
    fi
    printf "%s\n" "$venv_dir/bin/python"
}

ensure_venv() {
    python_bin=$1
    if [ -e "$VENV_DIR" ] && [ ! -d "$VENV_DIR" ]; then
        die "$VENV_DIR exists but is not a directory."
    fi

    if [ -d "$VENV_DIR" ]; then
        log "Reusing existing virtual environment at $VENV_DIR."
        return 0
    fi

    log "Creating a local virtual environment at $VENV_DIR."
    if create_venv "$python_bin"; then
        return 0
    fi

    if ! is_debian_like && ! is_wsl; then
        die "Virtual environment creation failed. Install the Python venv module for $python_bin and rerun make install."
    fi

    warn "Python is available, but \`$python_bin -m venv $VENV_DIR\` failed."
    log "On Debian, Ubuntu, and WSL this usually means \`python3-venv\` is missing."
    log "Suggested command:"
    log "  sudo apt install python3-venv python3-pip"

    if ! can_prompt; then
        die "This session is non-interactive, so no system install command was run. Install python3-venv and python3-pip manually, then rerun make install."
    fi

    if ! confirm "Run \`sudo apt install python3-venv python3-pip\` now and retry virtual environment creation?"; then
        die "Virtual environment creation was left incomplete. Install python3-venv and python3-pip manually, then rerun make install."
    fi

    if ! install_apt_packages python3-venv python3-pip; then
        die "Virtual environment creation could not continue because python3-venv/python3-pip were not installed."
    fi

    if create_venv "$python_bin"; then
        return 0
    fi

    die "Virtual environment creation still failed after installing python3-venv/python3-pip. Review the error above and rerun make install."
}

install_project_dependencies() {
    venv_python=$1
    log "Installing SFE into $VENV_DIR with the repository's editable package configuration."
    run_cmd "$venv_python" -m pip install --disable-pip-version-check -e .
}

create_venv() {
    python_bin=$1
    log "+ $python_bin -m venv $VENV_DIR"
    if is_enabled "$DRY_RUN"; then
        return 0
    fi
    "$python_bin" -m venv "$VENV_DIR"
}

extract_numeric_version() {
    printf "%s\n" "$1" | sed -n 's/.*\([0-9][0-9.]*\).*/\1/p' | head -n 1
}

compare_versions_lt() {
    current_version=$1
    latest_version=$2
    "$PYTHON_BIN" - "$current_version" "$latest_version" <<'PY'
import re
import sys

def normalize(value: str):
    match = re.search(r"\d+(?:\.\d+)*", value)
    if not match:
        return None
    return tuple(int(part) for part in match.group(0).split("."))

current = normalize(sys.argv[1])
latest = normalize(sys.argv[2])
if current is None or latest is None:
    raise SystemExit(2)
raise SystemExit(0 if current < latest else 1)
PY
}

check_aider_upgrade() {
    aider_path=$1
    aider_version_output=$2

    current_version=$(extract_numeric_version "$aider_version_output")
    if [ -z "$current_version" ]; then
        return 0
    fi

    if [ -n "$AIDER_LATEST_VERSION_OVERRIDE" ]; then
        latest_version=$AIDER_LATEST_VERSION_OVERRIDE
    else
        latest_version=$("$PYTHON_BIN" - <<'PY' 2>/dev/null || true
import json
import urllib.request

with urllib.request.urlopen("https://pypi.org/pypi/aider-chat/json", timeout=5) as response:
    payload = json.load(response)
print(payload["info"]["version"])
PY
)
    fi
    if [ -z "$latest_version" ]; then
        return 0
    fi

    if compare_versions_lt "$current_version" "$latest_version"; then
        warn "Aider $current_version is installed at $aider_path, but PyPI currently reports $latest_version."
        pipx_path=$(find_command "$PIPX_BIN")
        if [ -n "$pipx_path" ] && "$pipx_path" list 2>/dev/null | grep -Fq "package aider-chat"; then
            if confirm_update "Run \`$PIPX_BIN upgrade aider-chat\` now?"; then
                run_cmd "$pipx_path" upgrade aider-chat
            else
                log "Leaving the existing Aider installation unchanged. Updates require an interactive confirmation or SFE_INSTALL_ALLOW_UPDATES=1."
            fi
        else
            log "Leaving the existing Aider installation unchanged. Update it manually if you want the newer release."
        fi
    fi
}

show_aider_help() {
    log "Aider is not currently available on PATH."
    log "SFE's normal workspace_write flow expects an external Aider install."
    if is_debian_like || is_wsl; then
        log "Recommended commands:"
        log "  pipx install aider-chat"
        log "  aider --version"
        log "  which aider"
        log "If pipx is missing, install it first with:"
        log "  sudo apt install pipx"
        log "If ~/.local/bin is not on PATH yet, run:"
        log "  pipx ensurepath"
        log "  exec \$SHELL -l"
    else
        log "Recommended commands:"
        log "  pipx install aider-chat"
        log "  aider --version"
    fi
}

verify_aider_on_path() {
    if is_enabled "$DRY_RUN"; then
        return 0
    fi
    aider_path=$(find_command "$AIDER_BIN")
    if [ -n "$aider_path" ]; then
        log "Found Aider at $aider_path."
        return 0
    fi
    warn "Aider may have installed into a directory that is not on PATH yet."
    die "Run \`pipx ensurepath\`, open a new shell, and rerun make install."
}

ensure_aider() {
    if is_enabled "$SKIP_AIDER"; then
        log "Skipping Aider checks because SFE_INSTALL_SKIP_AIDER=1."
        return 0
    fi

    aider_path=$(find_command "$AIDER_BIN")
    if [ -n "$aider_path" ]; then
        aider_version_output=$("$aider_path" --version 2>&1 | head -n 1 || true)
        if [ -n "$aider_version_output" ]; then
            log "Found Aider: $aider_version_output"
        else
            log "Found Aider at $aider_path."
        fi
        check_aider_upgrade "$aider_path" "$aider_version_output"
        return 0
    fi

    show_aider_help

    pipx_path=$(find_command "$PIPX_BIN")
    if [ -n "$pipx_path" ]; then
        if ! can_prompt; then
            die "Aider is missing and this session is non-interactive, so no pipx install command was run."
        fi
        if ! confirm "Install Aider now with \`$PIPX_BIN install aider-chat\`?"; then
            die "Aider was left uninstalled. Install it later or rerun with SFE_INSTALL_SKIP_AIDER=1 if you only need the Python package."
        fi
        run_cmd "$pipx_path" install aider-chat
        verify_aider_on_path
        return 0
    fi

    if ! is_debian_like && ! is_wsl; then
        die "pipx is not available. Install pipx, then rerun make install."
    fi

    if ! can_prompt; then
        die "pipx and Aider are missing, and this session is non-interactive, so no system install command was run."
    fi

    if ! confirm "Install pipx now with \`sudo apt install pipx\` so Aider can be installed cleanly?"; then
        die "pipx was left uninstalled. Install pipx and Aider manually, then rerun make install."
    fi

    if ! install_apt_packages pipx; then
        die "pipx could not be installed."
    fi

    pipx_path=$(find_command "$PIPX_BIN")
    if [ -z "$pipx_path" ]; then
        die "pipx still was not found after installation. Open a new shell if PATH changed, then rerun make install."
    fi

    if ! confirm "Install Aider now with \`$PIPX_BIN install aider-chat\`?"; then
        die "Aider was left uninstalled. Install it later or rerun with SFE_INSTALL_SKIP_AIDER=1 if you only need the Python package."
    fi

    run_cmd "$pipx_path" install aider-chat
    verify_aider_on_path
}

ensure_python_available
PYTHON_BIN=$PYTHON_BIN_RESOLVED
MINIMUM_PYTHON=$(resolve_minimum_python || true)

log "Using Python interpreter: $PYTHON_BIN"
if [ -n "$MINIMUM_PYTHON" ]; then
    log "Checking Python version against pyproject.toml (>= $MINIMUM_PYTHON)."
fi
check_python_version "$PYTHON_BIN" "$MINIMUM_PYTHON"

ensure_venv "$PYTHON_BIN"
VENV_PYTHON=$(venv_python_path "$VENV_DIR")
install_project_dependencies "$VENV_PYTHON"
ensure_aider

log "SFE install completed."
if [ "$VENV_DIR" = ".venv" ]; then
    log "Activate it with: source .venv/bin/activate"
else
    log "Activate it with: source $VENV_DIR/bin/activate"
fi
