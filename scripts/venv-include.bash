#!/bin/bash
#
# Venv management functions for project scripts
#
# Usage: source scripts/venv-include.bash
#
# Plan 00104 Phase 4 Task 3.2 fix: this file no longer enables errexit
# at file top. Sourcing executes in the caller's shell context, so a
# top-level ``set -euo pipefail`` poisons the caller's shell options —
# a caller whose errexit was previously OFF is silently flipped on and
# dies on the next non-zero command. Per-function errexit is enforced
# by adding explicit ``|| return $?`` checks to the few sites that
# need it (install_deps' pip calls). The top-level body itself uses
# explicit ``if !`` for every fallible call, so errexit was never
# actually load-bearing here.

# Project root directory
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Plan 00104 Phase 5 Task 5.5: venv resolution is delegated to the canonical
# bash library at ``scripts/lib/resolve_venv.sh``. That library invokes the
# Python SSOT (``daemon/paths.py``) under the venv's own ``bin/python`` (or
# ``bin/python3``) when one exists, so the fingerprint + scan + legacy
# precedence lives in Python and every wrapper agrees.
#
# The library is sourced inside its own subshell isolation (see
# ``resolve_venv.sh::resolve_venv_python``), so ``set -euo pipefail`` does
# NOT leak into this file's caller — preserving the Phase 4 Task 3.2 fix
# that prevents poisoning the caller's shell options.
#
# ``--fallback-target`` is passed because this file is sourced BEFORE the
# venv exists on fresh clones (``ensure_venv`` creates it). On a miss the
# SSOT prints the fingerprint-keyed creation target instead of exiting 1,
# so ``ensure_venv`` has a stable path to ``mkdir`` / ``python3 -m venv``
# into. Errors from the SSOT are NOT silenced — failures fail loudly, never
# silently fall back to the unversioned legacy path that v3.7.0 retired.
_RV_LIB="${PROJECT_ROOT}/scripts/lib/resolve_venv.sh"
if [ ! -f "$_RV_LIB" ]; then
    echo "❌ venv-include.bash: canonical resolver missing at $_RV_LIB" >&2
    echo "   Reinstall the daemon so scripts/lib/resolve_venv.sh is present." >&2
    unset _RV_LIB
    # shellcheck disable=SC2317  # `return` is reachable when sourced
    return 5 2>/dev/null || exit 5
fi
# shellcheck disable=SC1090  # path is computed at runtime from PROJECT_ROOT
source "$_RV_LIB"
unset _RV_LIB

# Plan 00103 Decision 2: ``set -e`` does not fire on ``var=$(cmd)`` failures
# (bash's documented variable-assignment exception), so the resolver's exit
# status must be propagated explicitly. Falling through silently here would
# resurrect the legacy-path fallback bug Decision 2 just removed.
if ! VENV_DIR="$(resolve_venv_dir "$PROJECT_ROOT" --fallback-target)"; then
    # shellcheck disable=SC2317  # `return` is reachable when sourced
    return 5 2>/dev/null || exit 5
fi
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
# capture-audit: allow -- legacy ensure_venv, called as `ensure_venv || exit 1`,
# never via $(...) capture. The captured ensure_venv lives in
# scripts/install/venv.sh and returns its venv path through stdout.
ensure_venv() {
    if venv_exists; then
        # >&2 is LOAD-BEARING (Plan 00200). venv_tool() calls ensure_venv on
        # every invocation, and callers redirect a tool's stdout into files
        # they then parse (e.g. run_lint.sh captures ruff's JSON). A banner on
        # stdout corrupts that capture. The error branches below already use
        # >&2; this success branch was the sole inconsistency, and it silently
        # blinded the ruff QA gate.
        echo -e "${GREEN}✓${NC} Venv exists: ${VENV_DIR}" >&2
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

    # >&2 is LOAD-BEARING here too (Plan 00200 Task 1.6): this path runs
    # inside ensure_venv, which venv_tool calls before running the real
    # tool with its stdout redirected to a file (e.g. run_lint.sh). A
    # stdout write here corrupts that capture exactly like the :87 banner
    # did -- it just only fires on a FRESH venv creation, not the common
    # "venv already exists" path, which is why it wasn't caught the first
    # time. Found by extending the capture-corruption auditor to also
    # recognise `cmd > file` (not just `$(cmd)`) as risky consumption.
    echo -e "${YELLOW}⚠${NC}  Venv not found, creating..." >&2

    # Create venv directory structure
    mkdir -p "$(dirname "${VENV_DIR}")"

    # Create venv
    python3 -m venv "${VENV_DIR}"

    if [[ ! -f "${VENV_PYTHON}" ]]; then
        echo -e "${RED}✗${NC} Failed to create venv at ${VENV_DIR}" >&2
        return 1
    fi

    echo -e "${GREEN}✓${NC} Created venv: ${VENV_DIR}" >&2
}

#
# Install project dependencies (like composer install)
#
install_deps() {
    local force_reinstall="${FORCE_REINSTALL:-false}"

    ensure_venv || return 1

    echo -e "${YELLOW}→${NC} Installing dependencies..."

    # Install in editable mode with dev dependencies. Plan 00104 Phase 4
    # Task 3.2 fix: explicit ``|| return $?`` because the file no longer
    # enables errexit at top level (so we don't poison the caller's
    # shell). Without this propagation, a pip failure would silently
    # report "Dependencies installed".
    if [[ "${force_reinstall}" == "true" ]]; then
        "${VENV_PIP}" install -e ".[dev]" --force-reinstall --quiet || return $?
    else
        "${VENV_PIP}" install -e ".[dev]" --quiet || return $?
    fi

    echo -e "${GREEN}✓${NC} Dependencies installed" >&2
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
        echo -e "${RED}✗${NC} Tool '${tool}' not found in venv" >&2
        echo -e "    Run: ${VENV_PIP} install ${tool}" >&2
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
