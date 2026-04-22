#!/bin/bash
#
# Venv management functions for project scripts
#
# Usage: source scripts/venv-include.bash
#

set -euo pipefail

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Plan 00099: venv is keyed by a Python-environment fingerprint so concurrent
# containers from the same image share one venv while distinct Pythons
# (pyenv vs distro, different minor versions, cross-arch) are kept apart.
# Resolution precedence (highest first):
#   1. $HOOKS_DAEMON_VENV_PATH (explicit override)
#   2. untracked/venv-{fingerprint}/ (fingerprint-keyed, recomputed)
#   3. untracked/venv-*/ (any existing fingerprint venv — handles mismatch
#      between recomputed fingerprint and installer-picked Python)
#   4. untracked/venv/ (legacy fallback, pre-v3.7.0)
_resolve_venv_dir() {
    if [ -n "${HOOKS_DAEMON_VENV_PATH:-}" ]; then
        echo "$HOOKS_DAEMON_VENV_PATH"
        return 0
    fi
    local fp_helper="${PROJECT_ROOT}/scripts/install/python_fingerprint.sh"
    if [ -f "$fp_helper" ]; then
        # shellcheck disable=SC1090
        source "$fp_helper"
        local fingerprint
        if fingerprint=$(python_venv_fingerprint "${HOOKS_DAEMON_PYTHON:-python3}" 2>/dev/null); then
            local keyed="${PROJECT_ROOT}/untracked/venv-${fingerprint}"
            if [ -d "$keyed" ] && [ -f "$keyed/bin/python3" ]; then
                echo "$keyed"
                return 0
            fi
        fi
    fi
    # Scan fallback: any existing venv-*/bin/python3. Handles installer-vs-resolver
    # Python mismatch (installer used python3.13, resolver sees python3=3.9).
    local candidate
    for candidate in "${PROJECT_ROOT}"/untracked/venv-*; do
        if [ -d "$candidate" ] && [ -f "$candidate/bin/python3" ]; then
            echo "$candidate"
            return 0
        fi
    done
    # Prefer keyed path for creation if fingerprint helper worked and no
    # legacy venv exists, so new venvs land at the correct location.
    if [ -f "$fp_helper" ] && [ ! -d "${PROJECT_ROOT}/untracked/venv" ]; then
        local fingerprint_create
        # shellcheck disable=SC1090
        source "$fp_helper"
        if fingerprint_create=$(python_venv_fingerprint "${HOOKS_DAEMON_PYTHON:-python3}" 2>/dev/null); then
            echo "${PROJECT_ROOT}/untracked/venv-${fingerprint_create}"
            return 0
        fi
    fi
    # Legacy fallback (pre-v3.7.0 installs)
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
