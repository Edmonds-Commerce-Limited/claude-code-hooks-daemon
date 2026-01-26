#!/usr/bin/env bash
#
# Automated verification script for vX.Y → vX.Z upgrade
#
# Usage: bash verification.sh
# Exit code: 0 = success, 1 = failure

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"

echo "=== Upgrade Verification: vX.Y → vX.Z ==="
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass() {
    echo -e "${GREEN}✅ $1: PASS${NC}"
}

fail() {
    echo -e "${RED}❌ $1: FAIL${NC}"
    echo -e "${RED}   $2${NC}"
    exit 1
}

warn() {
    echo -e "${YELLOW}⚠️  $1: WARNING${NC}"
    echo -e "${YELLOW}   $2${NC}"
}

info() {
    echo "ℹ️  $1"
}

# 1. Check version updated
info "Checking version..."
VERSION_FILE="$DAEMON_DIR/src/claude_code_hooks_daemon/version.py"
if [ -f "$VERSION_FILE" ]; then
    VERSION=$(grep '__version__' "$VERSION_FILE" | cut -d '"' -f 2)
    if [ "$VERSION" = "X.Z.0" ]; then
        pass "Version check" "Version is X.Z.0"
    else
        fail "Version check" "Expected X.Z.0, got $VERSION"
    fi
else
    fail "Version check" "Version file not found"
fi

# 2. Check config exists
info "Checking configuration..."
CONFIG_FILE="$PROJECT_ROOT/.claude/hooks-daemon.yaml"
if [ -f "$CONFIG_FILE" ]; then
    pass "Config file" "Found at $CONFIG_FILE"
else
    fail "Config file" "Not found at $CONFIG_FILE"
fi

# 3. Check new handler registered in config
info "Checking new handler configuration..."
if grep -q "new_handler:" "$CONFIG_FILE"; then
    pass "Handler config" "New handler found in config"
else
    warn "Handler config" "New handler not found in config (may be disabled)"
fi

# 4. Check daemon can start
info "Checking daemon startup..."
cd "$DAEMON_DIR"
VENV_PYTHON="untracked/venv/bin/python"

# Stop daemon if running
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop > /dev/null 2>&1 || true

# Try to get status (daemon should start on first request)
if $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status > /dev/null 2>&1; then
    pass "Daemon startup" "Daemon responded to status check"
else
    fail "Daemon startup" "Daemon failed to respond"
fi

# 5. Check hook execution
info "Checking hook execution..."
HOOK_SCRIPT="$PROJECT_ROOT/.claude/hooks/event-type"
if [ -f "$HOOK_SCRIPT" ]; then
    # Test hook with sample input
    RESULT=$(echo '{"hook_event_name":"EventType","tool_name":"Bash","tool_input":{"command":"echo test"}}' | "$HOOK_SCRIPT" 2>/dev/null)
    if echo "$RESULT" | grep -q '"decision"'; then
        pass "Hook execution" "Hook returned valid JSON"
    else
        fail "Hook execution" "Hook did not return valid JSON"
    fi
else
    warn "Hook execution" "Hook script not found (may not apply to this event type)"
fi

# 6. Check new handler is registered
info "Checking new handler registration..."
# This check is upgrade-specific - modify based on what handler was added
# Example: check if SessionStart handler responds
SESSION_START_HOOK="$PROJECT_ROOT/.claude/hooks/session-start"
if [ -f "$SESSION_START_HOOK" ]; then
    RESULT=$(echo '{"hook_event_name":"SessionStart","source":"new"}' | "$SESSION_START_HOOK" 2>/dev/null)
    if echo "$RESULT" | grep -q '"decision"'; then
        pass "New handler" "New handler responds to events"
    else
        fail "New handler" "New handler not responding"
    fi
else
    warn "New handler" "SessionStart hook not found (may not be this event type)"
fi

# 7. Clean up
info "Cleaning up..."
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop > /dev/null 2>&1 || true

echo
echo -e "${GREEN}=== All Verification Checks Passed ===${NC}"
echo
echo "Upgrade to vX.Z.0 completed successfully!"
echo "You can now use the new features."
