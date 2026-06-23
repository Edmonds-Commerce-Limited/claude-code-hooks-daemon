#!/bin/bash
#
# prerequisites.sh - Unified prerequisite checking for install/upgrade
#
# Checks for required system dependencies: git, python3 (3.11+), and uv.
# Single source of truth for prerequisite validation.
#
# Usage:
#   source "$(dirname "$0")/lib/prerequisites.sh"
#   check_all_prerequisites
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# check_git() - Verify git is installed
#
# Returns:
#   0 - git found
#   1 - git not found (also exits via fail_fast)
#
check_git() {
    if ! command -v git &> /dev/null; then
        fail_fast "git is not installed. Please install git first.

Installation:
  Ubuntu/Debian: sudo apt-get install git
  macOS: brew install git or xcode-select --install
  Fedora: sudo dnf install git"
    fi
    print_success "git found"
    return 0
}

# Plan 00110 Phase 4 Task 4.2 — single source of truth for Python discovery.
# `_is_python_at_least_311` and the inline candidate-list scan have been
# retired in favour of the canonical helper in scripts/lib/python_discovery.sh.
# The helper handles HOOKS_DAEMON_PYTHON validation, glob-and-sort PATH
# discovery, and pyproject `requires-python` floor-raising.
_PREREQ_PYTHON_DISCOVERY_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/lib/python_discovery.sh"
if [ ! -f "$_PREREQ_PYTHON_DISCOVERY_LIB" ]; then
    fail_fast "Canonical python discovery helper missing: $_PREREQ_PYTHON_DISCOVERY_LIB"
fi
# shellcheck source=../lib/python_discovery.sh
source "$_PREREQ_PYTHON_DISCOVERY_LIB"

#
# check_python3() - Verify a compatible Python interpreter is available
#
# Delegates discovery to the canonical helper. The minimum version is the
# SSoT in pyproject.toml's `requires-python`; pass that pyproject path as $1
# so the floor is raised from it. The bare 3.11 literal is only the
# floor-of-last-resort when no pyproject is supplied. The "(X.Y+)" diagnostic
# text is derived from the effective (parsed) floor, never hardcoded.
#
# Sets and exports HOOKS_DAEMON_PYTHON to the chosen absolute path on success,
# or fails fast with the helper's stderr (which names interpreters actually
# observed on this host — never a hardcoded version that may not be installed).
#
# Args:
#   $1 - pyproject_path (optional). When given and parseable, raises the floor
#        to its `requires-python` value.
#
# Returns:
#   0 - compatible Python found (HOOKS_DAEMON_PYTHON exported)
#   1 - no compatible Python found (also exits via fail_fast)
#
check_python3() {
    local pyproject="${1:-}"
    local floor="3.11"
    # Raise the displayed/enforced floor from the pyproject SSoT when supplied,
    # so the diagnostic text and find_latest_python agree on the real minimum.
    if [ -n "$pyproject" ]; then
        local pp_floor
        if pp_floor="$(_pd_parse_pyproject_floor "$pyproject")"; then
            floor="$pp_floor"
        fi
    fi
    local found
    if ! found="$(find_latest_python "$floor" "$pyproject")"; then
        fail_fast "No compatible Python (${floor}+) found. See the diagnostic above for the interpreters discovered on this host.

Either:
  - Install Python ${floor} or newer and ensure it is on \$PATH, or
  - Set HOOKS_DAEMON_PYTHON to the absolute path of a ${floor}+ interpreter."
    fi
    HOOKS_DAEMON_PYTHON="$found"
    export HOOKS_DAEMON_PYTHON
    local found_version=""
    found_version=$("$HOOKS_DAEMON_PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2> /dev/null) || found_version="?"
    print_success "Python $found_version found ($HOOKS_DAEMON_PYTHON)"
    return 0
}

#
# check_uv() - Verify uv is installed (optionally auto-install)
#
# Args:
#   $1 - auto_install (optional, default: true)
#        If true, attempts to install uv if not found
#        If false, fails fast if uv not found
#
# Returns:
#   0 - uv found or successfully installed
#   1 - uv not found and auto-install failed (also exits via fail_fast)
#
check_uv() {
    local auto_install="${1:-true}"

    if command -v uv &> /dev/null; then
        print_success "uv found"
        return 0
    fi

    # uv not found
    if [ "$auto_install" != "true" ]; then
        fail_fast "uv is not installed. Please install uv first.

Installation:
  curl -LsSf https://astral.sh/uv/install.sh | sh
  Then restart your shell or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi

    # Auto-install uv
    print_info "uv not found, installing..."

    if ! curl -LsSf https://astral.sh/uv/install.sh | sh > /dev/null 2>&1; then
        fail_fast "Failed to install uv. Please install manually:

Installation:
  curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi

    # Add uv to PATH for this session
    export PATH="$HOME/.local/bin:$PATH"

    # Verify uv is now available
    if ! command -v uv &> /dev/null; then
        fail_fast "uv installed but not found in PATH.

Please restart your shell or run:
  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi

    print_success "uv installed successfully"
    return 0
}

#
# check_git_remote_origin() - Verify git remote 'origin' is configured
#
# The daemon requires a git remote 'origin' to operate (ProjectContext
# reads repo URL from it). Without it, the daemon fails to start with
# a confusing silent error at Step 11.
#
# Returns:
#   0 - git remote 'origin' exists
#   1 - no remote 'origin' (also exits via fail_fast)
#
check_git_remote_origin() {
    local remote_url
    if ! remote_url=$(git remote get-url origin 2>/dev/null); then
        fail_fast "No git remote 'origin' configured.

The daemon requires a remote named 'origin' to operate.

Fix:
  git remote add origin <your-repo-url>

Example:
  git remote add origin https://github.com/your-org/your-project.git"
    fi
    print_success "git remote 'origin' found ($remote_url)"
    return 0
}

#
# check_all_prerequisites() - Run all prerequisite checks
#
# Args:
#   $1 - auto_install_uv (optional, default: true)
#        Passed to check_uv()
#   $2 - pyproject_path (optional)
#        Forwarded to check_python3() so the Python floor is raised from the
#        pyproject `requires-python` SSoT rather than the bare 3.11 literal.
#
# Returns:
#   0 - all prerequisites met
#   1 - one or more prerequisites failed (also exits via fail_fast)
#
check_all_prerequisites() {
    local auto_install_uv="${1:-true}"
    local pyproject="${2:-}"

    print_info "Checking prerequisites..."

    check_git
    check_git_remote_origin
    check_python3 "$pyproject"
    check_uv "$auto_install_uv"

    print_success "All prerequisites met"
    return 0
}

#
# get_python_version() - Get Python version string
#
# Returns:
#   Prints version string (e.g., "3.11.5") to stdout
#   Exit code 0 on success, 1 on failure
#
get_python_version() {
    if ! command -v python3 &> /dev/null; then
        return 1
    fi

    python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null
}

#
# get_python_major_minor() - Get Python major.minor version
#
# Returns:
#   Prints version string (e.g., "3.11") to stdout
#   Exit code 0 on success, 1 on failure
#
get_python_major_minor() {
    if ! command -v python3 &> /dev/null; then
        return 1
    fi

    python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2>/dev/null
}
