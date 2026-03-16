#!/bin/bash
#
# init-handlers.sh - Scaffold new project-level handlers
#
# Usage:
#   ./init-handlers.sh
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

echo "Claude Code Hooks Daemon - Project Handler Scaffolding"
echo ""

# Check if Python exists
if [ ! -f "$PYTHON" ]; then
    echo "❌ Python venv not found: $PYTHON"
    echo ""
    echo "Daemon installation may be corrupted. Try reinstalling."
    exit 1
fi

# Use the daemon's CLI to scaffold handlers
echo "This will create a new project-level handler with:"
echo "  • Handler file (.claude/project-handlers/{event_type}/{name}.py)"
echo "  • Test file (co-located test_{name}.py)"
echo "  • TDD-ready boilerplate"
echo "  • Registration in .claude/hooks-daemon.yaml"
echo ""

# Call the daemon CLI to do the scaffolding
"$PYTHON" -m claude_code_hooks_daemon.daemon.cli init-project-handlers || {
    echo ""
    echo "❌ Handler scaffolding failed"
    echo ""
    echo "The daemon may not have the init-project-handlers command."
    echo "This feature requires daemon version 2.x.x or later."
    exit 1
}

echo ""
echo "✓ Handler scaffolding complete"
echo ""
echo "Next steps:"
echo "  1. Write failing tests (RED phase)"
echo "  2. Implement handler to make tests pass (GREEN phase)"
echo "  3. Refactor for clarity (REFACTOR phase)"
echo "  4. Restart daemon to load handler:"
echo "     $PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
echo ""
echo "See CLAUDE/HANDLER_DEVELOPMENT.md for complete TDD workflow."
