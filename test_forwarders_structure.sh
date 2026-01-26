#!/bin/bash
#
# Test hook forwarder structure without requiring daemon to be running
# Verifies:
# 1. All 10 forwarders exist
# 2. All are executable
# 3. All source init.sh correctly
# 4. All have correct event names in JSON
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$SCRIPT_DIR/hooks"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counters
TOTAL=0
PASSED=0
FAILED=0

echo -e "${BLUE}🧪 Testing Claude Code Hook Forwarder Structure${NC}"
echo "=================================================="
echo

# Expected hooks with their event names
declare -A EXPECTED_HOOKS=(
    ["pre-tool-use"]="PreToolUse"
    ["post-tool-use"]="PostToolUse"
    ["session-start"]="SessionStart"
    ["permission-request"]="PermissionRequest"
    ["notification"]="Notification"
    ["user-prompt-submit"]="UserPromptSubmit"
    ["stop"]="Stop"
    ["subagent-stop"]="SubagentStop"
    ["pre-compact"]="PreCompact"
    ["session-end"]="SessionEnd"
)

# Function to test a single forwarder structure
test_forwarder_structure() {
    local hook_name=$1
    local expected_event=$2
    local hook_file="$HOOKS_DIR/$hook_name"

    TOTAL=$((TOTAL + 1))

    echo -e "${BLUE}Testing:${NC} $hook_name"

    # Check if hook file exists
    if [[ ! -f "$hook_file" ]]; then
        echo -e "  ${RED}❌ FAIL${NC} - Hook file not found: $hook_file"
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Check if hook is executable
    if [[ ! -x "$hook_file" ]]; then
        echo -e "  ${RED}❌ FAIL${NC} - Hook file not executable"
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Check if hook sources init.sh
    if ! grep -q 'source "$SCRIPT_DIR/../init.sh"' "$hook_file"; then
        echo -e "  ${RED}❌ FAIL${NC} - Hook does not source init.sh"
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Check if hook has correct event name
    if ! grep -q "\"event\": \"$expected_event\"" "$hook_file"; then
        echo -e "  ${RED}❌ FAIL${NC} - Hook missing or incorrect event name"
        echo -e "  ${YELLOW}Expected:${NC} \"event\": \"$expected_event\""
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Check for ensure_daemon call
    if ! grep -q 'ensure_daemon' "$hook_file"; then
        echo -e "  ${RED}❌ FAIL${NC} - Hook does not call ensure_daemon"
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Check for send_request call
    if ! grep -q 'send_request' "$hook_file"; then
        echo -e "  ${RED}❌ FAIL${NC} - Hook does not call send_request"
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Check for proper error handling
    if ! grep -q 'set -euo pipefail' "$hook_file"; then
        echo -e "  ${YELLOW}⚠️  WARN${NC} - Missing 'set -euo pipefail' (bash strict mode)"
    fi

    echo -e "  ${GREEN}✅ PASS${NC} - Structure correct"
    PASSED=$((PASSED + 1))
    echo

    return 0
}

# Test all hooks
echo -e "${YELLOW}Phase 1: Verifying all 10 forwarders exist${NC}"
echo
for hook_name in "${!EXPECTED_HOOKS[@]}"; do
    test_forwarder_structure "$hook_name" "${EXPECTED_HOOKS[$hook_name]}"
done

# Verify init.sh exists
echo -e "${YELLOW}Phase 2: Verifying init.sh exists${NC}"
echo
TOTAL=$((TOTAL + 1))
if [[ -f "$SCRIPT_DIR/init.sh" ]]; then
    echo -e "  ${GREEN}✅ PASS${NC} - init.sh found"
    PASSED=$((PASSED + 1))
else
    echo -e "  ${RED}❌ FAIL${NC} - init.sh not found"
    FAILED=$((FAILED + 1))
fi
echo

# Summary
echo "=================================================="
echo -e "${BLUE}Test Summary:${NC}"
echo "  Total:  $TOTAL"
echo -e "  ${GREEN}Passed: $PASSED${NC}"

if [[ $FAILED -gt 0 ]]; then
    echo -e "  ${RED}Failed: $FAILED${NC}"
    exit 1
else
    echo -e "  ${RED}Failed: $FAILED${NC}"
    echo
    echo -e "${GREEN}🎉 All forwarder structures correct!${NC}"
    echo
    echo -e "${YELLOW}Note:${NC} Daemon server not yet implemented (Phase 1)"
    echo "      Forwarders are ready for daemon integration"
    exit 0
fi
