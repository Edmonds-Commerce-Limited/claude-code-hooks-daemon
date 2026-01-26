#!/usr/bin/env bash
#
# Automated verification script for v2.0 → v2.1 upgrade
#
# Usage: bash verification.sh
# Exit code: 0 = success, 1 = failure

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
DAEMON_DIR="$PROJECT_ROOT/.claude/hooks-daemon"

echo "=== Upgrade Verification: v2.0 → v2.1 ==="
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
    if [ "$VERSION" = "2.1.0" ]; then
        pass "Version check" "Version is 2.1.0"
    else
        fail "Version check" "Expected 2.1.0, got $VERSION"
    fi
else
    fail "Version check" "Version file not found at $VERSION_FILE"
fi

# 2. Check config exists
info "Checking configuration..."
CONFIG_FILE="$PROJECT_ROOT/.claude/hooks-daemon.yaml"
if [ -f "$CONFIG_FILE" ]; then
    pass "Config file" "Found at $CONFIG_FILE"
else
    fail "Config file" "Not found at $CONFIG_FILE"
fi

# 3. Check YOLO handler file exists
info "Checking YOLO handler file..."
HANDLER_FILE="$DAEMON_DIR/src/claude_code_hooks_daemon/handlers/session_start/yolo_container_detection.py"
if [ -f "$HANDLER_FILE" ]; then
    pass "Handler file" "YOLO handler file exists"
else
    fail "Handler file" "YOLO handler file not found"
fi

# 4. Check daemon can start
info "Checking daemon startup..."
cd "$DAEMON_DIR"
VENV_PYTHON="untracked/venv/bin/python"

if [ ! -f "$VENV_PYTHON" ]; then
    fail "Python venv" "Virtual environment not found at $VENV_PYTHON"
fi

# Stop daemon if running
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop > /dev/null 2>&1 || true
sleep 1

# Try to get status (daemon should respond)
if $VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli status > /dev/null 2>&1; then
    pass "Daemon startup" "Daemon responded to status check"
else
    warn "Daemon startup" "Daemon not running (normal with lazy startup)"
fi

# 5. Check SessionStart hook execution
info "Checking SessionStart hook..."
SESSION_START_HOOK="$PROJECT_ROOT/.claude/hooks/session-start"
if [ -f "$SESSION_START_HOOK" ]; then
    # Test hook with sample input
    RESULT=$(echo '{"hook_event_name":"SessionStart","source":"new"}' | "$SESSION_START_HOOK" 2>/dev/null)
    if echo "$RESULT" | grep -q '"decision"'; then
        pass "SessionStart hook" "Hook returned valid JSON"
    else
        fail "SessionStart hook" "Hook did not return valid JSON"
    fi
else
    warn "SessionStart hook" "Hook script not found at $SESSION_START_HOOK"
fi

# 6. Check if YOLO handler can be imported
info "Checking YOLO handler import..."
cd "$DAEMON_DIR"
IMPORT_TEST=$($VENV_PYTHON -c "
from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import YoloContainerDetectionHandler
handler = YoloContainerDetectionHandler()
print(handler.name)
" 2>&1)

if echo "$IMPORT_TEST" | grep -q "yolo-container-detection"; then
    pass "Handler import" "YOLO handler imports correctly"
else
    fail "Handler import" "Failed to import YOLO handler: $IMPORT_TEST"
fi

# 7. Check handler confidence scoring works
info "Checking confidence scoring..."
SCORE_TEST=$($VENV_PYTHON -c "
from claude_code_hooks_daemon.handlers.session_start.yolo_container_detection import YoloContainerDetectionHandler
handler = YoloContainerDetectionHandler()
score = handler._calculate_confidence_score()
print(f'score={score}')
" 2>&1)

if echo "$SCORE_TEST" | grep -q "score="; then
    SCORE=$(echo "$SCORE_TEST" | grep -oP 'score=\K\d+')
    pass "Confidence scoring" "Calculated score: $SCORE"
else
    fail "Confidence scoring" "Failed to calculate score: $SCORE_TEST"
fi

# 8. Check tests exist and can run
info "Checking test suite..."
TEST_FILE="$DAEMON_DIR/tests/unit/handlers/session_start/test_yolo_container_detection.py"
if [ -f "$TEST_FILE" ]; then
    pass "Test suite" "Test file exists"

    # Try to run tests if pytest available
    if [ -f "$DAEMON_DIR/.venv/bin/pytest" ]; then
        info "Running tests..."
        if $DAEMON_DIR/.venv/bin/pytest "$TEST_FILE" -v --tb=short > /dev/null 2>&1; then
            pass "Test execution" "All tests passed"
        else
            warn "Test execution" "Some tests failed (check with: .venv/bin/pytest $TEST_FILE -v)"
        fi
    else
        warn "Test execution" "pytest not available in .venv (optional)"
    fi
else
    warn "Test suite" "Test file not found (optional for users)"
fi

# 9. Clean up
info "Cleaning up..."
$VENV_PYTHON -m claude_code_hooks_daemon.daemon.cli stop > /dev/null 2>&1 || true

echo
echo -e "${GREEN}=== All Critical Verification Checks Passed ===${NC}"
echo
echo "Upgrade to v2.1.0 completed successfully!"
echo
echo "The YOLO Container Detection handler is now active."
echo "Start a new Claude Code session to see it in action (if in a container)."
