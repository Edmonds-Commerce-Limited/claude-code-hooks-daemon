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

    if [ "$quiet" = "true" ]; then
        if UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir" > /dev/null 2>&1; then
            print_success "Virtual environment created at: $venv_path"
            return 0
        else
            print_error "Failed to create virtual environment"
            return 1
        fi
    else
        if UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir"; then
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
            print_warning "Daemon package import test failed: $import_test"
            print_warning "This is expected if daemon package not yet installed"
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
