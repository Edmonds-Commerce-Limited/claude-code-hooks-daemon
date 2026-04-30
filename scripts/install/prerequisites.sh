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

#
# _is_python_at_least_311() - Verify a Python interpreter is 3.11 or newer
#
# Plan 00103 Decision 3 Rule B: parses ``--version`` output rather than
# trusting the command name (because ``python3`` on RHEL/CentOS is 3.9 and
# on a Debian image may be anything from 3.7 to 3.13). Asserts MAJOR == 3
# AND MINOR >= 11, OR MAJOR > 3 (covers a hypothetical Python 4).
#
# Args:
#   $1 - cmd: Path or name of Python interpreter to probe
#
# Returns:
#   0 - cmd is executable AND reports Python 3.11+
#   1 - cmd missing, non-executable, or reports Python <3.11
#
# (Plan 00104 will move this helper into a shared library; currently
# duplicated between scripts/upgrade.sh and scripts/install/prerequisites.sh
# per the Decision 3 acceptance plan.)
#
_is_python_at_least_311() {
    local cmd="$1"
    [ -n "$cmd" ] || return 1
    if ! command -v "$cmd" > /dev/null; then
        return 1
    fi
    local version_output=""
    version_output="$("$cmd" --version 2>&1)" || return 1
    if [[ "$version_output" =~ Python[[:space:]]+([0-9]+)\.([0-9]+) ]]; then
        local major="${BASH_REMATCH[1]}"
        local minor="${BASH_REMATCH[2]}"
        if [ "$major" -gt 3 ]; then
            return 0
        fi
        if [ "$major" -eq 3 ] && [ "$minor" -ge 11 ]; then
            return 0
        fi
    fi
    return 1
}

#
# check_python3() - Verify a Python 3.11+ interpreter is available
#
# Plan 00103 Decision 3 Rule B (probe-list ban):
#   - Bare ``python3`` is INTENTIONALLY excluded from the candidate list.
#     Bare ``python3`` is unreliable on the user's PATH (RHEL/CentOS-default
#     is 3.9, Debian/container images vary). Probing it first means the
#     daemon gets bootstrapped against the wrong interpreter and fails deep
#     in the call stack. The probe must only use versioned commands.
#   - ``compgen -c python3.`` discovers any ``python3.NN`` so future versions
#     are picked up automatically.
#   - ``HOOKS_DAEMON_PYTHON`` is honoured as an explicit *input* override
#     (validated against 3.11+). An invalid override fails fast — never
#     silently falls back to PATH probing.
#
# Returns:
#   0 - compatible Python found (HOOKS_DAEMON_PYTHON exported)
#   1 - no compatible Python found (also exits via fail_fast)
#
check_python3() {
    # Step 1: explicit override wins (validated, no fallback on failure).
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        if _is_python_at_least_311 "$HOOKS_DAEMON_PYTHON"; then
            export HOOKS_DAEMON_PYTHON
            local found_version=""
            found_version=$("$HOOKS_DAEMON_PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2> /dev/null) || found_version="?"
            print_success "Python $found_version found (via HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON)"
            return 0
        fi
        fail_fast "HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON is not a usable Python 3.11+ interpreter.

Refusing to fall back to PATH probing — that would silently mask your broken override.

Either:
  - Unset HOOKS_DAEMON_PYTHON and let the installer probe PATH, or
  - Point HOOKS_DAEMON_PYTHON at an absolute path to a Python 3.11 or newer interpreter."
    fi

    # Step 2: build candidate list (versioned only) + open-ended discovery.
    local candidates=("python3.13" "python3.12" "python3.11")
    local discovered=""
    discovered="$(compgen -c "python3." 2> /dev/null)" || discovered=""
    if [ -n "$discovered" ]; then
        local cmd
        while IFS= read -r cmd; do
            [[ "$cmd" =~ ^python3\.[0-9]+$ ]] || continue
            local already=0
            local existing
            for existing in "${candidates[@]}"; do
                if [ "$existing" = "$cmd" ]; then
                    already=1
                    break
                fi
            done
            if [ "$already" -eq 0 ]; then
                candidates+=("$cmd")
            fi
        done <<< "$discovered"
    fi

    # Step 3: probe candidates in order; first 3.11+ match wins.
    local candidate
    for candidate in "${candidates[@]}"; do
        if _is_python_at_least_311 "$candidate"; then
            HOOKS_DAEMON_PYTHON="$(command -v "$candidate")"
            export HOOKS_DAEMON_PYTHON
            local found_version=""
            found_version=$("$HOOKS_DAEMON_PYTHON" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))' 2> /dev/null) || found_version="?"
            print_success "Python $found_version found ($HOOKS_DAEMON_PYTHON)"
            return 0
        fi
    done

    fail_fast "No compatible Python (3.11+) found.

Searched (versioned commands only — bare \"python3\" is intentionally not probed
because it is unreliable across distros): ${candidates[*]}

Please install Python 3.11 or higher:
  Ubuntu/Debian: sudo apt-get install python3.11
  macOS: brew install python@3.11
  Fedora: sudo dnf install python3.11
  Arch: sudo pacman -S python

Or set HOOKS_DAEMON_PYTHON to the absolute path of a 3.11+ interpreter:
  HOOKS_DAEMON_PYTHON=/usr/bin/python3.12 ..."
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
#
# Returns:
#   0 - all prerequisites met
#   1 - one or more prerequisites failed (also exits via fail_fast)
#
check_all_prerequisites() {
    local auto_install_uv="${1:-true}"

    print_info "Checking prerequisites..."

    check_git
    check_git_remote_origin
    check_python3
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
