#!/bin/bash
#
# daemon-cli.sh - General wrapper for daemon CLI commands
#
# Usage:
#   ./daemon-cli.sh <command> [args...]
#
# Examples:
#   ./daemon-cli.sh logs
#   ./daemon-cli.sh status
#   ./daemon-cli.sh restart
#   ./daemon-cli.sh handlers
#

set -euo pipefail

# Detect project root
PROJECT_ROOT="$(pwd)"
while [ "$PROJECT_ROOT" != "/" ]; do
    if [ -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ]; then
        break
    fi
    PROJECT_ROOT="$(dirname "$PROJECT_ROOT")"
done

if [ ! -f "$PROJECT_ROOT/.claude/hooks-daemon.yaml" ]; then
    echo "❌ Not in a hooks daemon project (no .claude/hooks-daemon.yaml found)"
    exit 1
fi

DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
PYTHON="$DAEMON_DIR/untracked/venv/bin/python"

# Check if Python exists
if [ ! -f "$PYTHON" ]; then
    echo "❌ Python venv not found: $PYTHON"
    echo ""
    echo "Daemon installation may be corrupted. Try reinstalling."
    exit 1
fi

# Forward all arguments to daemon CLI
"$PYTHON" -m claude_code_hooks_daemon.daemon.cli "$@"
