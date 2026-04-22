#!/bin/bash
#
# Claude Code Hooks Daemon - Location Detection Script
#
# Detects where you are relative to the hooks-daemon installation.
# Helps LLM agents and developers determine the correct working directory
# before running upgrade or maintenance commands.
#
# Usage:
#   ./scripts/detect_location.sh
#   .claude/hooks-daemon/scripts/detect_location.sh
#
# Output (one of):
#   project_root      - You are at the project root (correct for most commands)
#   hooks_daemon_dir  - You are inside .claude/hooks-daemon/
#   wrong_location    - You are not in a recognized location
#
# Exit codes:
#   0 - Location detected successfully
#   1 - Could not determine location
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load SSOT venv resolver (v3.7.0+ fingerprint-keyed layout + legacy fallback).
if [ -f "${SCRIPT_DIR}/install/venv_resolver.sh" ]; then
    # shellcheck source=install/venv_resolver.sh
    source "${SCRIPT_DIR}/install/venv_resolver.sh"
fi

# Colors for output (only when stdout is a terminal)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    NC=''
fi

# Get absolute path of current directory
CURRENT_DIR="$(pwd)"

#
# detect_project_root() - Walk up directory tree to find project root
#
# Looks for .claude/hooks-daemon.yaml as the definitive marker
# of a project root with hooks-daemon installed.
#
# Returns:
#   0 and sets PROJECT_ROOT if found
#   1 if not found
#
detect_project_root() {
    local dir="$CURRENT_DIR"

    while [ "$dir" != "/" ]; do
        if [ -f "$dir/.claude/hooks-daemon.yaml" ]; then
            PROJECT_ROOT="$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done

    return 1
}

#
# Main detection logic
#

# Try to find project root
if ! detect_project_root; then
    echo "wrong_location"
    echo "" >&2
    echo -e "${RED}Could not find a project with hooks-daemon installed.${NC}" >&2
    echo "" >&2
    echo "No .claude/hooks-daemon.yaml found in any parent directory." >&2
    echo "Current directory: $CURRENT_DIR" >&2
    echo "" >&2
    echo "If you are trying to install hooks-daemon, see:" >&2
    echo "  CLAUDE/LLM-INSTALL.md" >&2
    exit 1
fi

# Determine our location relative to project root
HOOKS_DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"

# Check if we're inside .claude/hooks-daemon/
case "$CURRENT_DIR" in
    "$HOOKS_DAEMON_DIR"|"$HOOKS_DAEMON_DIR"/*)
        echo "hooks_daemon_dir"
        echo "" >&2
        echo -e "${YELLOW}You are inside .claude/hooks-daemon/${NC}" >&2
        echo "" >&2
        echo "Project root: $PROJECT_ROOT" >&2
        echo "Current dir:  $CURRENT_DIR" >&2
        echo "" >&2
        echo "Most commands should be run from the project root." >&2
        echo -e "Run: ${CYAN}cd $PROJECT_ROOT${NC}" >&2
        exit 0
        ;;
esac

# Check if we're at the project root
if [ "$CURRENT_DIR" = "$PROJECT_ROOT" ]; then
    # Check for self-install mode
    local_self_install="false"
    if [ -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ]; then
        if command -v python3 &>/dev/null; then
            local_self_install=$(python3 -c "
import yaml
try:
    with open('$PROJECT_ROOT/.claude/hooks-daemon.yaml') as f:
        config = yaml.safe_load(f) or {}
    print('true' if config.get('daemon', {}).get('self_install_mode', False) else 'false')
except Exception:
    print('false')
" 2>/dev/null || echo "false")
        fi
    fi

    echo "project_root"
    echo "" >&2
    echo -e "${GREEN}You are at the project root.${NC}" >&2
    echo "" >&2
    echo "Project root: $PROJECT_ROOT" >&2

    if [ "$local_self_install" = "true" ]; then
        echo "Mode: self-install (development)" >&2
        if declare -F resolve_existing_venv_python > /dev/null; then
            echo "Python: $(resolve_existing_venv_python "$PROJECT_ROOT")" >&2
        else
            echo "Python: $PROJECT_ROOT/untracked/venv/bin/python" >&2
        fi
    elif [ -d "$HOOKS_DAEMON_DIR" ]; then
        echo "Mode: normal installation" >&2
        if declare -F resolve_existing_venv_python > /dev/null; then
            echo "Python: $(resolve_existing_venv_python "$HOOKS_DAEMON_DIR")" >&2
        else
            echo "Python: $HOOKS_DAEMON_DIR/untracked/venv/bin/python" >&2
        fi
    fi

    exit 0
fi

# We found a project root but we're in some subdirectory (not hooks-daemon)
echo "project_root"
echo "" >&2
echo -e "${GREEN}You are in a subdirectory of the project.${NC}" >&2
echo "" >&2
echo "Project root: $PROJECT_ROOT" >&2
echo "Current dir:  $CURRENT_DIR" >&2
exit 0
