#!/bin/bash
#
# upgrade.sh - Upgrade hooks daemon to new version
#
# Usage:
#   ./upgrade.sh [VERSION]
#
# Arguments:
#   VERSION (optional): Target version (e.g., 2.14.0 or v2.14.0)
#                       If omitted, upgrades to latest version
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
    echo "Error: Not in a hooks daemon project (no .claude/hooks-daemon.yaml found)"
    exit 1
fi

DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"
TARGET_VERSION="${1:-latest}"

echo "Claude Code Hooks Daemon - Upgrade"
echo ""
echo "Project:        $PROJECT_ROOT"
echo "Daemon:         $DAEMON_DIR"
echo "Target version: $TARGET_VERSION"
echo ""

# Check if daemon directory exists
if [ ! -d "$DAEMON_DIR" ]; then
    echo "Error: Daemon directory not found: $DAEMON_DIR"
    echo ""
    echo "Run installation first:"
    echo "  curl -fsSL https://raw.githubusercontent.com/your-org/hooks-daemon/main/scripts/install.sh | bash"
    exit 1
fi

# Check if upgrade script exists
UPGRADE_SCRIPT="$DAEMON_DIR/scripts/upgrade.sh"
if [ ! -f "$UPGRADE_SCRIPT" ]; then
    echo "Error: Upgrade script not found: $UPGRADE_SCRIPT"
    echo ""
    echo "Your daemon installation may be incomplete or from an older version."
    echo "Try reinstalling from scratch."
    exit 1
fi

# Execute the daemon's upgrade script
echo "Executing upgrade..."
echo ""

cd "$PROJECT_ROOT"
bash "$UPGRADE_SCRIPT" "$TARGET_VERSION"
