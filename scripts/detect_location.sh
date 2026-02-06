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
# is_hooks_daemon_repo() - Check if a directory is the hooks-daemon source repo
#
# Uses git remote URL as source of truth.
#
# Args:
#   $1 - Directory to check
#
# Returns:
#   0 if it is the hooks-daemon repo
#   1 otherwise
#
is_hooks_daemon_repo() {
    local dir="$1"
    if [ ! -d "$dir/.git" ]; then
        return 1
    fi

    local remote_url
    remote_url=$(git -C "$dir" remote get-url origin 2>/dev/null || echo "")
    remote_url=$(echo "$remote_url" | tr '[:upper:]' '[:lower:]')

    if echo "$remote_url" | grep -q "claude-code-hooks-daemon" || \
       echo "$remote_url" | grep -q "claude_code_hooks_daemon"; then
        return 0
    fi

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
        echo "Python: $PROJECT_ROOT/untracked/venv/bin/python" >&2
    elif [ -d "$HOOKS_DAEMON_DIR" ]; then
        echo "Mode: normal installation" >&2
        echo "Python: $HOOKS_DAEMON_DIR/untracked/venv/bin/python" >&2
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
