#!/bin/bash
#
# Verification script for v2.29 → v2.30 upgrade
#
# Usage: bash CLAUDE/UPGRADES/v2/v2.29-to-v2.30/verification.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Navigate to hooks-daemon root (4 levels up from this script)
DAEMON_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
PYTHON="${DAEMON_ROOT}/untracked/venv/bin/python"
VERSION_FILE="${DAEMON_ROOT}/src/claude_code_hooks_daemon/version.py"
TEMP_OUTPUT="/tmp/v2.30-verify-$$.txt"

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

echo "=== v2.29 -> v2.30 Upgrade Verification ==="
echo ""

# Check 1: Version is 2.30.x
VERSION=$(grep '__version__' "$VERSION_FILE" | grep -o '[0-9]\+\.[0-9]\+\.[0-9]\+')
if [[ "$VERSION" == 2.30.* ]]; then
    check "Version is 2.30.x (found: $VERSION)" 0
else
    check "Version is 2.30.x (found: $VERSION)" 1
fi

# Check 2: Daemon starts successfully
if "$PYTHON" -m claude_code_hooks_daemon.daemon.cli restart > "$TEMP_OUTPUT" 2>&1; then
    check "Daemon restarts successfully" 0
else
    echo "    Restart output: $(cat "$TEMP_OUTPUT")"
    check "Daemon restarts successfully" 1
fi

# Check 3: Daemon is running
STATUS=$("$PYTHON" -m claude_code_hooks_daemon.daemon.cli status 2>&1)
if echo "$STATUS" | grep -q "RUNNING"; then
    check "Daemon status is RUNNING" 0
else
    echo "    Status output: $STATUS"
    check "Daemon status is RUNNING" 1
fi

# Check 4: validate-project-handlers exits cleanly
if "$PYTHON" -m claude_code_hooks_daemon.daemon.cli validate-project-handlers > "$TEMP_OUTPUT" 2>&1; then
    check "Project handlers validate successfully" 0
else
    echo "    Validation output: $(cat "$TEMP_OUTPUT")"
    check "Project handlers validate successfully (run with --verbose for details)" 1
fi

# Check 5: ClaudeMdInjector wrote hooksdaemon section
PROJECT_CLAUDE_MD="${DAEMON_ROOT}/CLAUDE.md"
if [ -f "$PROJECT_CLAUDE_MD" ] && grep -q "<hooksdaemon>" "$PROJECT_CLAUDE_MD"; then
    check "CLAUDE.md contains <hooksdaemon> section" 0
else
    check "CLAUDE.md contains <hooksdaemon> section" 1
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
    echo "  - See upgrade guide: CLAUDE/UPGRADES/v2/v2.29-to-v2.30/README.md"
    exit 1
fi
