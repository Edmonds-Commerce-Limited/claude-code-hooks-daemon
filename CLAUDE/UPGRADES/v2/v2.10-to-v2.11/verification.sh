#!/bin/bash
# Verification script for v2.10 → v2.11 upgrade
# Validates that the upgrade was successful

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== v2.11.0 Upgrade Verification ===${NC}"
echo ""

FAILED=0

# Test 1: Version check
echo -n "Version check: "
if [[ -f ".claude/hooks-daemon/src/claude_code_hooks_daemon/version.py" ]]; then
    VERSION=$(grep '__version__' .claude/hooks-daemon/src/claude_code_hooks_daemon/version.py | cut -d'"' -f2)
    if [[ "$VERSION" == "2.11.0" ]]; then
        echo -e "${GREEN}✅ PASS${NC} (v$VERSION)"
    else
        echo -e "${RED}❌ FAIL${NC} (found v$VERSION, expected v2.11.0)"
        FAILED=1
    fi
else
    echo -e "${RED}❌ FAIL${NC} (version.py not found)"
    FAILED=1
fi

# Test 2: Config validation
echo -n "Config validation: "
if [[ -f ".claude/hooks-daemon.yaml" ]]; then
    # Check for obsolete handlers
    if grep -q "validate_sitemap:" .claude/hooks-daemon.yaml && ! grep -q "# validate_sitemap:" .claude/hooks-daemon.yaml; then
        echo -e "${YELLOW}⚠️  WARN${NC} (validate_sitemap still active - should be removed)"
    elif grep -q "remind_validator:" .claude/hooks-daemon.yaml && ! grep -q "# remind_validator:" .claude/hooks-daemon.yaml; then
        echo -e "${YELLOW}⚠️  WARN${NC} (remind_validator still active - should be removed)"
    else
        echo -e "${GREEN}✅ PASS${NC} (no obsolete handlers)"
    fi
else
    echo -e "${RED}❌ FAIL${NC} (config file not found)"
    FAILED=1
fi

# Test 3: Daemon restart
echo -n "Daemon restart: "
cd .claude/hooks-daemon
if untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli restart > /tmp/daemon_restart.log 2>&1; then
    echo -e "${GREEN}✅ PASS${NC}"
else
    echo -e "${RED}❌ FAIL${NC}"
    echo "   Check logs: cat /tmp/daemon_restart.log"
    FAILED=1
fi
cd - > /dev/null

# Test 4: Check for handler errors
echo -n "Handler loading: "
if [[ -f ".claude/hooks-daemon/untracked/daemon.log" ]]; then
    # Check for import errors or handler loading failures
    if grep -i "error.*validate_sitemap\|error.*remind_validator" .claude/hooks-daemon/untracked/daemon.log > /dev/null 2>&1; then
        echo -e "${RED}❌ FAIL${NC} (handler errors in log)"
        FAILED=1
    else
        echo -e "${GREEN}✅ PASS${NC} (no handler errors)"
    fi
else
    echo -e "${YELLOW}⚠️  SKIP${NC} (daemon log not found)"
fi

# Test 5: Daemon status
echo -n "Daemon status: "
cd .claude/hooks-daemon
STATUS=$(untracked/venv/bin/python -m claude_code_hooks_daemon.daemon.cli status 2>&1 || true)
cd - > /dev/null

if echo "$STATUS" | grep -q "running"; then
    echo -e "${GREEN}✅ PASS${NC} (daemon running)"
elif echo "$STATUS" | grep -q "not running"; then
    echo -e "${GREEN}✅ PASS${NC} (daemon not running - lazy startup)"
else
    echo -e "${YELLOW}⚠️  WARN${NC} (unexpected status)"
fi

echo ""
echo -e "${BLUE}==================================${NC}"

if [[ $FAILED -eq 0 ]]; then
    echo -e "${GREEN}✅ All Verification Checks Passed${NC}"
    echo ""
    echo "Your upgrade to v2.11.0 was successful!"
    echo ""
    echo "What changed:"
    echo "  • validate_sitemap handler removed"
    echo "  • remind_validator handler removed"
    echo ""
    echo "If you need similar functionality, see:"
    echo "  CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md"
    exit 0
else
    echo -e "${RED}❌ Some Verification Checks Failed${NC}"
    echo ""
    echo "Please review the failures above and:"
    echo "  1. Check daemon logs: .claude/hooks-daemon/untracked/daemon.log"
    echo "  2. Review upgrade guide: CLAUDE/UPGRADES/v2/v2.10-to-v2.11/v2.10-to-v2.11.md"
    echo "  3. If issues persist, consider rollback instructions in upgrade guide"
    exit 1
fi
