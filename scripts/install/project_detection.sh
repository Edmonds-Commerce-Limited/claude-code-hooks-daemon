#!/bin/bash
#
# project_detection.sh - Unified project root detection and validation
#
# Detects Claude Code project root, validates structure, and determines
# installation mode (normal vs self-install).
#
# Usage:
#   source "$(dirname "$0")/lib/project_detection.sh"
#   PROJECT_ROOT=$(detect_project_root)
#   validate_project_structure "$PROJECT_ROOT"
#   INSTALL_MODE=$(detect_install_mode "$PROJECT_ROOT")
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# detect_project_root() - Find project root by walking up directory tree
#
# Searches for .claude/hooks-daemon.yaml starting from current directory
# and walking up the directory tree.
#
# Returns:
#   Prints project root path to stdout if found
#   Exit code 0 if found, 1 if not found
#
detect_project_root() {
    local dir
    dir="$(pwd)"

    # Primary signal: config file exists (ideal state)
    while [ "$dir" != "/" ]; do
        if [ -f "$dir/.claude/hooks-daemon.yaml" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done

    # Fallback signal: daemon repo exists but config missing (broken install)
    dir="$(pwd)"
    while [ "$dir" != "/" ]; do
        if [ -d "$dir/.claude/hooks-daemon/.git" ]; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done

    return 1
}

#
# detect_project_root_current_dir() - Check if current directory is project root
#
# Simpler check used by install.sh - only checks current directory,
# doesn't walk up tree.
#
# Returns:
#   Prints current directory to stdout if it's a project root
#   Exit code 0 if current dir is project root, 1 if not
#
detect_project_root_current_dir() {
    local pwd
    pwd="$(pwd)"

    if [ -d ".claude" ] && [ -d ".git" ]; then
        echo "$pwd"
        return 0
    fi

    return 1
}

#
# validate_project_structure() - Validate project has required directories
#
# Args:
#   $1 - Project root path
#   $2 - require_git (optional, default: true)
#        If true, requires .git directory
#        If false, only requires .claude directory
#
# Returns:
#   Exit code 0 if valid, exits via fail_fast if invalid
#
validate_project_structure() {
    local project_root="$1"
    local require_git="${2:-true}"

    if [ -z "$project_root" ]; then
        fail_fast "validate_project_structure: project_root parameter required"
    fi

    print_verbose "Validating project structure at: $project_root"

    # Check for .claude directory
    if [ ! -d "$project_root/.claude" ]; then
        fail_fast "No .claude directory found at: $project_root
This script must be run from a Claude Code project root.

Expected directory structure:
  your-project/
  ├── .claude/
  ├── .git/
  └── ..."
    fi
    print_verbose ".claude directory exists"

    # Check for .git directory (if required)
    if [ "$require_git" = "true" ]; then
        if [ ! -d "$project_root/.git" ]; then
            fail_fast "No .git directory found at: $project_root
This script must be run from a git repository root.

Expected directory structure:
  your-project/
  ├── .claude/
  ├── .git/
  └── ..."
        fi
        print_verbose ".git directory exists"
    fi

    return 0
}

#
# detect_install_mode() - Determine if project uses self-install mode
#
# Checks daemon.self_install_mode in .claude/hooks-daemon.yaml
#
# Args:
#   $1 - Project root path
#
# Returns:
#   Prints "self-install" or "normal" to stdout
#   Exit code 0 on success, 1 on failure
#
detect_install_mode() {
    local project_root="$1"

    if [ -z "$project_root" ]; then
        echo "normal"
        return 1
    fi

    local config_file="$project_root/.claude/hooks-daemon.yaml"

    if [ ! -f "$config_file" ]; then
        echo "normal"
        return 0
    fi

    # Use python3 to parse YAML and check self_install_mode
    if ! command -v python3 &>/dev/null; then
        echo "normal"
        return 0
    fi

    local self_install
    self_install=$(python3 -c "
import sys
try:
    import yaml
except ImportError:
    # yaml not available, assume normal mode
    print('normal')
    sys.exit(0)

try:
    with open('$config_file') as f:
        config = yaml.safe_load(f) or {}
    if config.get('daemon', {}).get('self_install_mode', False):
        print('self-install')
    else:
        print('normal')
except Exception:
    print('normal')
" 2>/dev/null)

    if [ -z "$self_install" ]; then
        echo "normal"
    else
        echo "$self_install"
    fi

    return 0
}

#
# get_daemon_dir() - Get daemon installation directory based on mode
#
# Args:
#   $1 - Project root path
#   $2 - Install mode ("self-install" or "normal")
#
# Returns:
#   Prints daemon directory path to stdout
#
get_daemon_dir() {
    local project_root="$1"
    local install_mode="$2"

    if [ -z "$project_root" ]; then
        fail_fast "get_daemon_dir: project_root parameter required"
    fi

    if [ "$install_mode" = "self-install" ]; then
        echo "$project_root"
    else
        echo "$project_root/.claude/hooks-daemon"
    fi
}

#
# get_venv_python() - Get path to venv Python binary based on mode
#
# Args:
#   $1 - Project root path
#   $2 - Install mode ("self-install" or "normal")
#
# Returns:
#   Prints venv Python path to stdout
#
get_venv_python() {
    local project_root="$1"
    local install_mode="$2"

    if [ -z "$project_root" ]; then
        fail_fast "get_venv_python: project_root parameter required"
    fi

    if [ "$install_mode" = "self-install" ]; then
        echo "$project_root/untracked/venv/bin/python"
    else
        echo "$project_root/.claude/hooks-daemon/untracked/venv/bin/python"
    fi
}

#
# detect_and_validate_project() - All-in-one detection and validation
#
# Combines detection, validation, and mode detection into single function.
# This is the recommended high-level function for most use cases.
#
# Args:
#   $1 - search_mode (optional, default: "walk-up")
#        "walk-up": Walk up directory tree to find project root
#        "current": Only check current directory
#
# Returns:
#   Sets global variables:
#     PROJECT_ROOT - Absolute path to project root
#     INSTALL_MODE - "self-install" or "normal"
#     DAEMON_DIR - Path to daemon installation directory
#     VENV_PYTHON - Path to venv Python binary
#   Exit code 0 on success, exits via fail_fast on failure
#
detect_and_validate_project() {
    local search_mode="${1:-walk-up}"

    print_verbose "Detecting project root (search_mode=$search_mode)..."

    # Detect project root
    if [ "$search_mode" = "current" ]; then
        PROJECT_ROOT=$(detect_project_root_current_dir)
    else
        PROJECT_ROOT=$(detect_project_root)
    fi

    if [ -z "$PROJECT_ROOT" ]; then
        fail_fast "Could not find project root.
No .claude/hooks-daemon.yaml found in current directory or any parent directory.
Current directory: $(pwd)

Make sure you're running this from within a Claude Code project."
    fi

    print_verbose "Project root: $PROJECT_ROOT"

    # Check if config file is missing (detected via fallback signal)
    NEEDS_CONFIG_REPAIR="false"
    if [ ! -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ]; then
        NEEDS_CONFIG_REPAIR="true"
        print_verbose "Config file missing - will be repaired during upgrade"
    fi
    export NEEDS_CONFIG_REPAIR

    # Validate structure
    validate_project_structure "$PROJECT_ROOT"

    # Detect install mode
    INSTALL_MODE=$(detect_install_mode "$PROJECT_ROOT")
    print_verbose "Install mode: $INSTALL_MODE"

    # Set derived paths
    DAEMON_DIR=$(get_daemon_dir "$PROJECT_ROOT" "$INSTALL_MODE")
    VENV_PYTHON=$(get_venv_python "$PROJECT_ROOT" "$INSTALL_MODE")

    print_verbose "Daemon directory: $DAEMON_DIR"
    print_verbose "Venv Python: $VENV_PYTHON"

    # Export for use by calling script
    export PROJECT_ROOT
    export INSTALL_MODE
    export DAEMON_DIR
    export VENV_PYTHON

    return 0
}
