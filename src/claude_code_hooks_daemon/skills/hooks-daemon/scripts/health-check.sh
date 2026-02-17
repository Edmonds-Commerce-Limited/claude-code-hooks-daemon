#!/bin/bash
#
# health-check.sh - Check daemon health and status
#
# Usage:
#   ./health-check.sh
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

echo "Claude Code Hooks Daemon - Health Check"
echo ""

# Check if Python exists
if [ ! -f "$PYTHON" ]; then
    echo "❌ Python venv not found: $PYTHON"
    echo ""
    echo "Daemon installation may be corrupted. Try reinstalling."
    exit 1
fi

# Get daemon status
echo "═══════════════════════════════════════"
echo "DAEMON STATUS"
echo "═══════════════════════════════════════"

"$PYTHON" -m claude_code_hooks_daemon.daemon.cli status 2>&1 || {
    echo ""
    echo "❌ Daemon status check failed"
    echo ""
    echo "Try restarting the daemon:"
    echo "  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
    exit 1
}

echo ""
echo "═══════════════════════════════════════"
echo "CONFIGURATION"
echo "═══════════════════════════════════════"

CONFIG_FILE="$PROJECT_ROOT/.claude/hooks-daemon.yaml"
if [ -f "$CONFIG_FILE" ]; then
    echo "✓ Config file: $CONFIG_FILE"

    # Validate config
    if "$PYTHON" -m claude_code_hooks_daemon.daemon.cli validate-config 2>&1 | grep -q "valid"; then
        echo "✓ Config validation: PASSED"
    else
        echo "⚠️  Config validation: FAILED"
        echo ""
        echo "Run for details:"
        echo "  $PYTHON -m claude_code_hooks_daemon.daemon.cli validate-config"
    fi
else
    echo "❌ Config file missing: $CONFIG_FILE"
fi

echo ""
echo "═══════════════════════════════════════"
echo "HANDLERS"
echo "═══════════════════════════════════════"

# Count handlers
HANDLER_COUNT=$("$PYTHON" -m claude_code_hooks_daemon.daemon.cli handlers 2>/dev/null | grep -c "^  -" || echo "0")
echo "✓ Loaded handlers: $HANDLER_COUNT"

echo ""
echo "═══════════════════════════════════════"
echo "RECENT ACTIVITY"
echo "═══════════════════════════════════════"

# Show last 5 log lines
echo "Last 5 log entries:"
"$PYTHON" -m claude_code_hooks_daemon.daemon.cli logs 2>/dev/null | tail -5 || echo "(no logs available)"

echo ""
echo "═══════════════════════════════════════"
echo ""
echo "✓ Health check complete"
echo ""
echo "For detailed logs:"
echo "  $PYTHON -m claude_code_hooks_daemon.daemon.cli logs"
echo ""
echo "To restart daemon:"
echo "  $PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
