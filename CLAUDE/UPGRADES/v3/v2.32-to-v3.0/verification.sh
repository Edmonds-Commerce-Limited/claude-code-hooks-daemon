#!/bin/bash
#
# Verification script for v2.32 -> v3.0 upgrade
#
# Usage: bash CLAUDE/UPGRADES/v3/v2.32-to-v3.0/verification.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Navigate to hooks-daemon root (4 levels up from this script)
DAEMON_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PYTHON="${DAEMON_ROOT}/untracked/venv/bin/python"
VERSION_FILE="${DAEMON_ROOT}/src/claude_code_hooks_daemon/version.py"
CONFIG_FILE="${DAEMON_ROOT}/.claude/hooks-daemon.yaml"
TEMP_OUTPUT="/tmp/v3.0-verify-$$.txt"

PASS=0
FAIL=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" -eq 0 ]; then
        echo "  PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $name"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== v2.32 -> v3.0 Upgrade Verification ==="
echo ""

# Check 1: Version is 3.0.x
VERSION=$(grep '__version__' "$VERSION_FILE" | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')
if [[ "$VERSION" == 3.0.* ]]; then
    check "Version is 3.0.x (found: $VERSION)" 0
else
    check "Version is 3.0.x (found: $VERSION)" 1
fi

# Check 2: Config does not contain command_redirection
if [ -f "$CONFIG_FILE" ]; then
    if grep -q "command_redirection" "$CONFIG_FILE"; then
        echo "    Found stale command_redirection in: $CONFIG_FILE"
        check "Config is clean of command_redirection" 1
    else
        check "Config is clean of command_redirection" 0
    fi
else
    echo "    Config file not found: $CONFIG_FILE"
    check "Config file exists" 1
fi

# Check 3: command_redirection module is gone
if [ -f "${DAEMON_ROOT}/src/claude_code_hooks_daemon/core/command_redirection.py" ]; then
    check "core/command_redirection.py removed" 1
else
    check "core/command_redirection.py removed" 0
fi

# Check 4: Daemon starts successfully
if "$PYTHON" -m claude_code_hooks_daemon.daemon.cli restart > "$TEMP_OUTPUT" 2>&1; then
    check "Daemon restarts successfully" 0
else
    echo "    Restart output: $(cat "$TEMP_OUTPUT")"
    check "Daemon restarts successfully" 1
fi

# Check 5: Daemon is running
STATUS=$("$PYTHON" -m claude_code_hooks_daemon.daemon.cli status 2>&1)
if echo "$STATUS" | grep -q "RUNNING"; then
    check "Daemon status is RUNNING" 0
else
    echo "    Status output: $STATUS"
    check "Daemon status is RUNNING" 1
fi

# Check 6: validate-project-handlers exits cleanly
if "$PYTHON" -m claude_code_hooks_daemon.daemon.cli validate-project-handlers > "$TEMP_OUTPUT" 2>&1; then
    check "Project handlers validate successfully" 0
else
    echo "    Validation output: $(cat "$TEMP_OUTPUT")"
    check "Project handlers validate successfully (run with --verbose for details)" 1
fi

# Cleanup
rm -f "$TEMP_OUTPUT"

echo ""
echo "=== Results ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo ""

if [ "$FAIL" -eq 0 ]; then
    echo "Upgrade verification: ALL CHECKS PASSED"
    exit 0
else
    echo "Upgrade verification: $FAIL CHECK(S) FAILED"
    echo ""
    echo "Troubleshooting:"
    echo "  - Run: $PYTHON -m claude_code_hooks_daemon.daemon.cli validate-project-handlers --verbose"
    echo "  - Check logs: $PYTHON -m claude_code_hooks_daemon.daemon.cli logs"
    echo "  - See upgrade guide: CLAUDE/UPGRADES/v3/v2.32-to-v3.0/README.md"
    exit 1
fi
