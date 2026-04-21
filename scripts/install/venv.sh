#!/bin/bash
#
# venv.sh - Unified virtual environment management using uv
#
# Provides functions to create, recreate, and verify Python virtual environments
# using the uv package manager. Standardizes venv location and management.
#
# Usage:
#   source "$(dirname "$0")/lib/venv.sh"
#   create_venv "$DAEMON_DIR"
#   verify_venv "$VENV_PYTHON"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

# Ensure uv is in PATH (installed in ~/.local/bin by default)
if [ -d "$HOME/.local/bin" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

#
# create_venv() - Create virtual environment using uv sync
#
# Creates venv at {daemon_dir}/untracked/venv/ using uv.
# Sets up untracked directory structure with .gitignore.
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#   $2 - quiet (optional, default: false)
#        If true, suppresses uv output
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
create_venv() {
    local daemon_dir="$1"
    local quiet="${2:-false}"

    if [ -z "$daemon_dir" ]; then
        fail_fast "create_venv: daemon_dir parameter required"
    fi

    if [ ! -d "$daemon_dir" ]; then
        fail_fast "create_venv: daemon_dir does not exist: $daemon_dir"
    fi

    print_info "Creating virtual environment with uv..."

    # Create untracked directory with self-excluding .gitignore
    mkdir -p "$daemon_dir/untracked"
    echo "/untracked/" > "$daemon_dir/untracked/.gitignore"

    # Use uv to sync dependencies to untracked/venv
    # UV_PROJECT_ENVIRONMENT tells uv where to create the venv
    local venv_path="$daemon_dir/untracked/venv"

    # If a specific Python interpreter was found, tell uv to use it
    local python_args=()
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        python_args=(--python "$HOOKS_DAEMON_PYTHON")
    fi

    # Suppress "Failed to hardlink files" warning in containers/overlay filesystems
    export UV_LINK_MODE=copy

    if [ "$quiet" = "true" ]; then
        if UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir" "${python_args[@]}" > /tmp/uv_sync_output.txt 2>&1; then
            print_success "Virtual environment created at: $venv_path"
            rm -f /tmp/uv_sync_output.txt
            return 0
        else
            print_error "Failed to create virtual environment"
            if [ -f /tmp/uv_sync_output.txt ]; then
                cat /tmp/uv_sync_output.txt >&2
                rm -f /tmp/uv_sync_output.txt
            fi
            return 1
        fi
    else
        if UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir" "${python_args[@]}"; then
            print_success "Virtual environment created at: $venv_path"
            return 0
        else
            print_error "Failed to create virtual environment"
            print_info "Manual installation command:"
            echo "  cd $daemon_dir"
            echo "  UV_PROJECT_ENVIRONMENT=\$(pwd)/untracked/venv uv sync"
            return 1
        fi
    fi
}

#
# recreate_venv() - Delete existing venv and create fresh one
#
# Used during upgrades to ensure clean venv state.
# Follows "upgrade = clean reinstall" philosophy.
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#   $2 - quiet (optional, default: false)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
recreate_venv() {
    local daemon_dir="$1"
    local quiet="${2:-false}"

    if [ -z "$daemon_dir" ]; then
        fail_fast "recreate_venv: daemon_dir parameter required"
    fi

    local venv_path="$daemon_dir/untracked/venv"

    # Delete existing venv if it exists
    if [ -d "$venv_path" ]; then
        print_info "Removing existing virtual environment..."
        rm -rf "$venv_path"
        print_success "Existing venv removed"
    fi

    # Create fresh venv
    create_venv "$daemon_dir" "$quiet"
}

#
# verify_venv() - Verify venv exists and can import daemon package
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - daemon_dir: Path to daemon installation directory (for import test)
#
# Returns:
#   Exit code 0 if venv is valid, 1 if invalid
#
verify_venv() {
    local venv_python="$1"
    local daemon_dir="$2"

    if [ -z "$venv_python" ]; then
        print_error "verify_venv: venv_python parameter required"
        return 1
    fi

    # Check if venv Python exists
    if [ ! -f "$venv_python" ]; then
        print_error "Virtual environment Python not found: $venv_python"
        return 1
    fi

    # Check if Python is executable
    if [ ! -x "$venv_python" ]; then
        print_error "Virtual environment Python is not executable: $venv_python"
        return 1
    fi

    # Verify Python runs
    if ! "$venv_python" --version > /dev/null 2>&1; then
        print_error "Virtual environment Python failed to run: $venv_python"
        return 1
    fi

    print_verbose "Venv Python executable: $venv_python"

    # If daemon_dir provided, test import
    if [ -n "$daemon_dir" ] && [ -d "$daemon_dir" ]; then
        print_verbose "Testing daemon package import..."

        local import_test
        import_test=$("$venv_python" -c "
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path('$daemon_dir')
sys.path.insert(0, str(daemon_dir / 'src'))

try:
    import claude_code_hooks_daemon
    print('OK')
except ImportError as e:
    print(f'IMPORT_ERROR: {e}')
" 2>&1)

        if [[ "$import_test" == "OK" ]]; then
            print_verbose "Daemon package imports successfully"
        else
            print_error "Daemon package import test failed: $import_test"
            print_error "Virtual environment may be missing dependencies"
            return 1
        fi
    fi

    print_success "Virtual environment verified"
    return 0
}

#
# get_venv_python_version() - Get Python version from venv
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#
# Returns:
#   Prints version string to stdout (e.g., "3.11.2")
#   Exit code 0 on success, 1 on failure
#
get_venv_python_version() {
    local venv_python="$1"

    if [ -z "$venv_python" ] || [ ! -x "$venv_python" ]; then
        return 1
    fi

    "$venv_python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null
}

# Version stamp file name — lives inside the venv directory
VENV_VERSION_STAMP=".daemon-version"

#
# stamp_venv_version() - Write daemon version into venv directory
#
# Called after successful venv creation to record which daemon version
# the venv was built for. Enables stale-venv detection on upgrade.
#
# Args:
#   $1 - venv_path: Path to venv directory (e.g., .../untracked/venv)
#   $2 - version: Version string to stamp (e.g., v3.1.0)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
stamp_venv_version() {
    local venv_path="$1"
    local version="$2"

    if [ -z "$venv_path" ] || [ -z "$version" ]; then
        print_error "stamp_venv_version: venv_path and version required"
        return 1
    fi

    if [ ! -d "$venv_path" ]; then
        print_error "stamp_venv_version: venv directory does not exist: $venv_path"
        return 1
    fi

    echo "$version" > "$venv_path/$VENV_VERSION_STAMP"
    print_verbose "Stamped venv with version: $version"
    return 0
}

#
# get_venv_version() - Read daemon version from venv stamp
#
# Args:
#   $1 - venv_path: Path to venv directory
#
# Returns:
#   Prints version string to stdout (empty string if no stamp)
#   Exit code 0 always
#
get_venv_version() {
    local venv_path="$1"
    local stamp_file="$venv_path/$VENV_VERSION_STAMP"

    if [ -f "$stamp_file" ]; then
        cat "$stamp_file"
    else
        echo ""
    fi
}

#
# venv_version_matches() - Check if venv was built for the target version
#
# Args:
#   $1 - venv_path: Path to venv directory
#   $2 - target_version: Expected version string
#
# Returns:
#   Exit code 0 if versions match
#   Exit code 1 if mismatch or no stamp
#
venv_version_matches() {
    local venv_path="$1"
    local target_version="$2"

    if [ -z "$venv_path" ] || [ -z "$target_version" ]; then
        return 1
    fi

    local current_version
    current_version=$(get_venv_version "$venv_path")

    if [ -z "$current_version" ]; then
        print_verbose "No venv version stamp found (pre-stamp install)"
        return 1
    fi

    if [ "$current_version" = "$target_version" ]; then
        print_verbose "Venv version matches: $current_version"
        return 0
    else
        print_info "Venv version mismatch: have $current_version, need $target_version"
        return 1
    fi
}

#
# ensure_venv() - Auto-bootstrap venv for current Python environment fingerprint
#
# Plan 00099: the entry point init.sh calls on every daemon start. Computes
# the fingerprint of the target Python, then:
#   - venv missing                  -> create + stamp
#   - venv present, stamp missing   -> recreate + stamp (lazy upgrade from pre-stamp builds)
#   - venv present, stamp mismatch  -> recreate + stamp
#   - venv present, stamp matches   -> no-op (fast path)
#
# Honors HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 and CI=true to skip entirely
# (CI environments stub venvs out of band).
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#   $2 - target_version: Daemon version to stamp into the venv (e.g. v3.7.0)
#   $3 - python_bin (optional, default: python3): Target Python to fingerprint
#
# Side effect:
#   Prints the computed venv path to stdout on success so callers can
#   capture it (e.g. `VENV_PATH="$(ensure_venv ...)"`). Log messages go
#   to stderr via print_* helpers.
#
# Returns:
#   Exit code 0 on success (including skip), 1 on failure
#
ensure_venv() {
    local daemon_dir="$1"
    local target_version="$2"
    local python_bin="${3:-python3}"

    if [ -z "$daemon_dir" ] || [ -z "$target_version" ]; then
        print_error "ensure_venv: daemon_dir and target_version required"
        return 1
    fi

    # CI gate: allow opt-out for CI environments that stub venvs
    if [ "${HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP:-0}" = "1" ] || [ "${CI:-}" = "true" ]; then
        print_verbose "ensure_venv: skipped (HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP or CI set)"
        return 0
    fi

    # Compute fingerprint via the SSOT helper. Must be sourced by the caller.
    if ! declare -F python_venv_fingerprint > /dev/null; then
        print_error "ensure_venv: python_venv_fingerprint not loaded — source scripts/install/python_fingerprint.sh first"
        return 1
    fi

    local fingerprint
    if ! fingerprint=$(python_venv_fingerprint "$python_bin"); then
        print_error "ensure_venv: failed to compute fingerprint for $python_bin"
        return 1
    fi

    local venv_path="$daemon_dir/untracked/venv-$fingerprint"

    # Fast path: venv exists and stamp matches — no-op
    if [ -d "$venv_path" ] && venv_version_matches "$venv_path" "$target_version"; then
        print_verbose "ensure_venv: venv up-to-date at $venv_path"
        echo "$venv_path"
        return 0
    fi

    # Slow path: need to (re)create
    if [ -d "$venv_path" ]; then
        print_info "ensure_venv: stamp mismatch — rebuilding $venv_path"
        rm -rf "$venv_path"
    else
        print_info "ensure_venv: creating venv at $venv_path"
    fi

    HOOKS_DAEMON_PYTHON="$python_bin" \
        create_venv_at_path "$daemon_dir" "$venv_path" "true" || return 1

    stamp_venv_version "$venv_path" "$target_version" || return 1
    echo "$venv_path"
    return 0
}

#
# create_venv_at_path() - Create venv at an explicit path (fingerprint-keyed)
#
# Thin wrapper around `uv sync` that lets callers specify the venv location
# directly. Used by ensure_venv(). Keeps the existing create_venv() signature
# unchanged for backwards compatibility with install.sh / upgrade.sh.
#
# Args:
#   $1 - daemon_dir: Path to daemon project (for `uv sync --project`)
#   $2 - venv_path: Absolute path where the venv should be created
#   $3 - quiet (optional, default: false)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
create_venv_at_path() {
    local daemon_dir="$1"
    local venv_path="$2"
    local quiet="${3:-false}"

    if [ -z "$daemon_dir" ] || [ -z "$venv_path" ]; then
        print_error "create_venv_at_path: daemon_dir and venv_path required"
        return 1
    fi

    mkdir -p "$daemon_dir/untracked"
    if [ ! -f "$daemon_dir/untracked/.gitignore" ]; then
        echo "/untracked/" > "$daemon_dir/untracked/.gitignore"
    fi

    local python_args=()
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        python_args=(--python "$HOOKS_DAEMON_PYTHON")
    fi

    export UV_LINK_MODE=copy

    if [ "$quiet" = "true" ]; then
        if UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir" "${python_args[@]}" > /tmp/uv_sync_output.txt 2>&1; then
            print_verbose "Virtual environment created at: $venv_path"
            rm -f /tmp/uv_sync_output.txt
            return 0
        else
            print_error "Failed to create virtual environment at $venv_path"
            if [ -f /tmp/uv_sync_output.txt ]; then
                cat /tmp/uv_sync_output.txt >&2
                rm -f /tmp/uv_sync_output.txt
            fi
            return 1
        fi
    else
        if UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir" "${python_args[@]}"; then
            print_success "Virtual environment created at: $venv_path"
            return 0
        else
            print_error "Failed to create virtual environment at $venv_path"
            return 1
        fi
    fi
}

#
# install_package_editable() - Install package in editable mode
#
# Installs the daemon package in editable mode (-e) into the venv.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - quiet (optional, default: false)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
install_package_editable() {
    local venv_python="$1"
    local daemon_dir="$2"
    local quiet="${3:-false}"

    if [ -z "$venv_python" ]; then
        fail_fast "install_package_editable: venv_python parameter required"
    fi

    if [ -z "$daemon_dir" ]; then
        fail_fast "install_package_editable: daemon_dir parameter required"
    fi

    if [ ! -f "$venv_python" ]; then
        fail_fast "install_package_editable: venv Python not found: $venv_python"
    fi

    print_info "Installing daemon package in editable mode..."

    # Use uv pip (which works with uv-created venvs)
    # uv pip install automatically uses the active venv or can be told which one to use
    local pip_cmd="uv pip install -e $daemon_dir --python $venv_python"

    if [ "$quiet" = "true" ]; then
        if $pip_cmd > /dev/null 2>&1; then
            print_success "Daemon package installed"
            return 0
        else
            print_error "Failed to install daemon package"
            return 1
        fi
    else
        if $pip_cmd; then
            print_success "Daemon package installed"
            return 0
        else
            print_error "Failed to install daemon package"
            return 1
        fi
    fi
}
