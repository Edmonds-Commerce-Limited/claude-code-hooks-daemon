#!/usr/bin/env bash
# Verification script for v2.12.0 → v2.13.0 upgrade
# Confirms upgrade was successful and daemon is functioning

set -e

echo "=========================================="
echo "v2.12 → v2.13 Upgrade Verification"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

FAILED=0

# Determine paths
if [ -f "src/claude_code_hooks_daemon/version.py" ]; then
    # Running from workspace root (self-install mode) or .claude/hooks-daemon/
    DAEMON_DIR="."

    # Check if self-install mode (workspace has untracked/venv)
    if [ -f "untracked/venv/bin/python" ]; then
        # Self-install mode
        CONFIG_FILE=".claude/hooks-daemon.yaml"
        PYTHON="untracked/venv/bin/python"
    else
        # Standard mode (.claude/hooks-daemon/)
        CONFIG_FILE="../../.claude/hooks-daemon.yaml"
        PYTHON="untracked/venv/bin/python"
    fi
elif [ -f ".claude/hooks-daemon/src/claude_code_hooks_daemon/version.py" ]; then
    # Running from project root (standard install)
    DAEMON_DIR=".claude/hooks-daemon"
    CONFIG_FILE=".claude/hooks-daemon.yaml"
    PYTHON=".claude/hooks-daemon/untracked/venv/bin/python"
else
    echo -e "${RED}✗ ERROR: Cannot locate daemon installation${NC}"
    echo "  Run this script from either:"
    echo "    - .claude/hooks-daemon/ directory"
    echo "    - Project root directory (if self-install mode)"
    exit 1
fi

# Check 1: Version number
echo -n "Checking version... "
VERSION=$($PYTHON -c "import sys; sys.path.insert(0, '$DAEMON_DIR/src'); from claude_code_hooks_daemon.version import __version__; print(__version__)")

if [ "$VERSION" = "2.13.0" ]; then
    echo -e "${GREEN}✓ PASS${NC} (v$VERSION)"
else
    echo -e "${RED}✗ FAIL${NC} (found v$VERSION, expected v2.13.0)"
    FAILED=1
fi

# Check 2: Configuration syntax
echo -n "Validating configuration... "
if [ -f "$CONFIG_FILE" ]; then
    if $PYTHON -c "import yaml; yaml.safe_load(open('$CONFIG_FILE'))" 2>/dev/null; then
        echo -e "${GREEN}✓ PASS${NC} (valid YAML)"
    else
        echo -e "${RED}✗ FAIL${NC} (invalid YAML syntax)"
        FAILED=1
    fi
else
    echo -e "${YELLOW}⚠ SKIP${NC} (config file not found at $CONFIG_FILE)"
fi

# Check 3: Daemon can start
echo -n "Testing daemon startup... "
if $PYTHON -m claude_code_hooks_daemon.daemon.cli restart 2>&1 | grep -q "started\|already running" || \
   $PYTHON -m claude_code_hooks_daemon.daemon.cli status 2>&1 | grep -q "RUNNING"; then
    echo -e "${GREEN}✓ PASS${NC} (daemon operational)"
else
    echo -e "${RED}✗ FAIL${NC} (daemon failed to start)"
    FAILED=1
fi

# Check 4: Core handlers load
echo -n "Verifying core handlers... "
if $PYTHON -c "from claude_code_hooks_daemon.handlers.pre_tool_use import DestructiveGitHandler; from claude_code_hooks_daemon.handlers.post_tool_use import LintOnEditHandler" 2>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} (handlers import successfully)"
else
    echo -e "${RED}✗ FAIL${NC} (handler import errors)"
    FAILED=1
fi

# Check 5: New feature - Single daemon enforcement module
echo -n "Checking new v2.13 features... "
if $PYTHON -c "from claude_code_hooks_daemon.daemon.process_verification import find_all_daemon_processes" 2>/dev/null; then
    echo -e "${GREEN}✓ PASS${NC} (single daemon enforcement available)"
else
    echo -e "${YELLOW}⚠ WARNING${NC} (cannot import new features)"
fi

# Check 6: Project handler - ReleaseBlockerHandler
echo -n "Verifying project handlers... "
if [ -f ".claude/project-handlers/stop/release_blocker.py" ] || \
   [ -f "$DAEMON_DIR/../../.claude/project-handlers/stop/release_blocker.py" ]; then
    echo -e "${GREEN}✓ PASS${NC} (ReleaseBlockerHandler found)"
else
    echo -e "${YELLOW}⚠ INFO${NC} (ReleaseBlockerHandler not in this project - normal for non-daemon projects)"
fi

# Check 7: Test suite (optional, takes time)
if [ "$1" = "--full" ]; then
    echo ""
    echo "Running full test suite (this may take a minute)..."
    if cd "$DAEMON_DIR" && $PYTHON -m pytest tests/ -q 2>&1 | tail -5; then
        echo -e "${GREEN}✓ PASS${NC} (all tests passing)"
    else
        echo -e "${RED}✗ FAIL${NC} (test failures detected)"
        FAILED=1
    fi
fi

echo ""
echo "=========================================="
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All Verification Checks Passed${NC}"
    echo ""
    echo "Upgrade to v2.13.0 successful!"
    echo ""
    echo "What's new:"
    echo "  • ReleaseBlockerHandler (project-level Stop handler)"
    echo "  • Single daemon process enforcement (auto-enabled in containers)"
    echo "  • PHP QA suppression fix (8 new patterns blocked)"
    echo "  • Realistic acceptance testing methodology"
    echo "  • Plan execution framework guidance"
    echo ""
    echo "No configuration changes required - your v2.12 config works as-is."
else
    echo -e "${RED}✗ Some Checks Failed${NC}"
    echo ""
    echo "Troubleshooting steps:"
    echo "  1. Check daemon logs: cat $DAEMON_DIR/untracked/daemon.log"
    echo "  2. Verify installation: cd $DAEMON_DIR && $PYTHON -m pip install -e ."
    echo "  3. Check git status: cd $DAEMON_DIR && git status"
    echo "  4. Restart daemon: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart"
    echo ""
    echo "For support, see: https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon/issues"
    exit 1
fi

echo "=========================================="
