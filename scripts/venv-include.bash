#!/bin/bash
#
# Venv management functions for project scripts
#
# Usage: source scripts/venv-include.bash
#

set -euo pipefail

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Plan 00100 Phase 2: venv resolution is delegated to the Python SSOT at
# src/claude_code_hooks_daemon/daemon/paths.py. This file is now a thin bash
# wrapper; the fingerprint + scan + legacy precedence lives in Python so the
# three other wrappers (scripts/install/venv_resolver.sh,
# src/.../skills/hooks-daemon/scripts/_resolve-venv.sh, and this file) stay
# in lock-step.
#
# Precedence (implemented in paths.py::resolve_existing_venv_python_with_diagnostics):
#   1. $HOOKS_DAEMON_VENV_PATH                — explicit override
#   2. ${PROJECT_ROOT}/untracked/venv-{fingerprint}/ — fingerprint-keyed
#   3. ${PROJECT_ROOT}/untracked/venv-*/      — scan for any existing venv
#   4. ${PROJECT_ROOT}/untracked/venv/        — legacy fallback (pre-v3.7.0)
#
# `--fallback-target` is passed because this file is sourced BEFORE the venv
# exists on fresh clones (ensure_venv creates it). On a miss the SSOT prints
# the fingerprint-keyed creation target instead of exiting 1, so ensure_venv
# has a stable path to mkdir/python3 -m venv into.
#
# The SSOT is invoked as a DIRECT SCRIPT (not `python -m`) so the package
# __init__.py — which imports pydantic — is bypassed. This matters here
# because venv-include.bash runs under the host `python3`, which at that
# point only has stdlib. paths.py is stdlib-only by design.
_resolve_venv_dir() {
    local paths_script="${PROJECT_ROOT}/src/claude_code_hooks_daemon/daemon/paths.py"
    local python_cmd="${HOOKS_DAEMON_PYTHON:-python3}"
    local python_path

    if [ -f "$paths_script" ] && python_path=$(
        "$python_cmd" "$paths_script" resolve-venv \
            --daemon-dir "$PROJECT_ROOT" --fallback-target 2>/dev/null
    ); then
        # SSOT returns bin/python or bin/python3 depending on which interpreter
        # the venv actually ships. Derive the venv dir via dirname-of-dirname
        # so either suffix works.
        dirname "$(dirname "$python_path")"
        return 0
    fi

    # SSOT unavailable (missing script or interpreter failure): legacy
    # fallback so pre-v3.7.0 installs still boot.
    echo "${PROJECT_ROOT}/untracked/venv"
}

VENV_DIR="$(_resolve_venv_dir)"
VENV_PYTHON="${VENV_DIR}/bin/python3"
VENV_PIP="${VENV_DIR}/bin/pip"

# Colours for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Colour

#
# Check if venv exists
#
venv_exists() {
    [[ -d "${VENV_DIR}" ]] && [[ -f "${VENV_PYTHON}" ]]
}

#
# Create venv if it doesn't exist
#
ensure_venv() {
    if venv_exists; then
        echo -e "${GREEN}✓${NC} Venv exists: ${VENV_DIR}"
        return 0
    fi

    # Plan 00100 Task 2.7: refuse to create a fresh venv at the bare legacy
    # path ``.../untracked/venv``. That is the shape that caused the v3.7.0
    # cross-Python corruption when two containers sharing an image landed on
    # the same directory. Pre-existing legacy venvs are still accepted above
    # (venv_exists returns true); this guard only fires on creation.
    if [[ "${VENV_DIR}" == */untracked/venv ]]; then
        echo -e "${RED}✗${NC} Refusing to create venv at legacy path: ${VENV_DIR}" >&2
        echo "    The legacy path has no Python-environment fingerprint and" >&2
        echo "    cannot safely be shared between concurrent installs." >&2
        echo "    Cause: the SSOT at src/claude_code_hooks_daemon/daemon/paths.py" >&2
        echo "    is unreachable, so venv-include.bash fell back to the legacy" >&2
        echo "    filename. Reinstall the daemon so paths.py is present." >&2
        return 1
    fi

    echo -e "${YELLOW}⚠${NC}  Venv not found, creating..."

    # Create venv directory structure
    mkdir -p "$(dirname "${VENV_DIR}")"

    # Create venv
    python3 -m venv "${VENV_DIR}"

    if [[ ! -f "${VENV_PYTHON}" ]]; then
        echo -e "${RED}✗${NC} Failed to create venv at ${VENV_DIR}"
        return 1
    fi

    echo -e "${GREEN}✓${NC} Created venv: ${VENV_DIR}"
}

#
# Install project dependencies (like composer install)
#
install_deps() {
    local force_reinstall="${FORCE_REINSTALL:-false}"

    ensure_venv || return 1

    echo -e "${YELLOW}→${NC} Installing dependencies..."

    # Install in editable mode with dev dependencies
    if [[ "${force_reinstall}" == "true" ]]; then
        "${VENV_PIP}" install -e ".[dev]" --force-reinstall --quiet
    else
        "${VENV_PIP}" install -e ".[dev]" --quiet
    fi

    echo -e "${GREEN}✓${NC} Dependencies installed"
}

#
# Run command in venv (like "composer run")
#
venv_run() {
    ensure_venv || return 1

    # Check if deps are installed (check for pytest as indicator)
    if ! "${VENV_PYTHON}" -c "import pytest" 2>/dev/null; then
        echo -e "${YELLOW}⚠${NC}  Dependencies not installed, installing now..."
        install_deps
    fi

    # Run command in venv
    "${VENV_PYTHON}" "$@"
}

#
# Run tool from venv bin/ (like ruff, mypy, black)
#
venv_tool() {
    local tool="$1"
    shift

    ensure_venv || return 1

    local tool_path="${VENV_DIR}/bin/${tool}"

    if [[ ! -f "${tool_path}" ]]; then
        echo -e "${RED}✗${NC} Tool '${tool}' not found in venv"
        echo -e "    Run: ${VENV_PIP} install ${tool}"
        return 1
    fi

    "${tool_path}" "$@"
}

#
# Get venv Python path for use in scripts
#
get_venv_python() {
    ensure_venv || return 1
    echo "${VENV_PYTHON}"
}

#
# Get venv pip path for use in scripts
#
get_venv_pip() {
    ensure_venv || return 1
    echo "${VENV_PIP}"
}

#
# Display venv status
#
venv_status() {
    echo "Venv Status:"
    echo "  Location: ${VENV_DIR}"

    if venv_exists; then
        echo -e "  Status: ${GREEN}exists${NC}"
        echo "  Python: ${VENV_PYTHON}"

        # Check for key dependencies
        local deps_ok=true
        for dep in pytest ruff mypy black; do
            if "${VENV_PYTHON}" -c "import ${dep}" 2>/dev/null; then
                echo -e "    ${GREEN}✓${NC} ${dep}"
            else
                echo -e "    ${RED}✗${NC} ${dep}"
                deps_ok=false
            fi
        done

        if [[ "${deps_ok}" == "false" ]]; then
            echo ""
            echo -e "${YELLOW}Some dependencies missing. Run:${NC}"
            echo "  ${VENV_PIP} install -e .[dev]"
        fi
    else
        echo -e "  Status: ${RED}missing${NC}"
        echo ""
        echo "Create venv with:"
        echo "  ensure_venv && install_deps"
    fi
}
