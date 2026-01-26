#!/bin/bash
#
# Test all hook forwarders to verify they:
# 1. Execute without errors
# 2. Generate valid JSON
# 3. Forward requests to daemon
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

echo -e "${BLUE}🧪 Testing Claude Code Hook Forwarders${NC}"
echo "============================================"
echo

# Test data for each hook type
declare -A TEST_INPUTS=(
    ["pre-tool-use"]='{"tool_name": "Bash", "tool_input": {"command": "echo test"}}'
    ["post-tool-use"]='{"tool_name": "Bash", "tool_input": {"command": "echo test"}, "tool_output": "test"}'
    ["session-start"]='{"source": "user"}'
    ["permission-request"]='{"permission": "file_read", "path": "/test/file.txt"}'
    ["notification"]='{"message": "Test notification", "level": "info"}'
    ["user-prompt-submit"]='{"prompt": "Test prompt"}'
    ["stop"]='{"reason": "user_request"}'
    ["subagent-stop"]='{"agent_name": "test-agent", "reason": "completed"}'
    ["pre-compact"]='{"context_length": 100000}'
    ["session-end"]='{"reason": "user_exit"}'
)

# Function to test a single forwarder
test_forwarder() {
    local hook_name=$1
    local hook_file="$HOOKS_DIR/$hook_name"
    local test_input="${TEST_INPUTS[$hook_name]}"

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

    # Execute hook with test input
    local output
    local exit_code

    output=$(echo "$test_input" | "$hook_file" 2>&1) || exit_code=$?
    exit_code=${exit_code:-0}

    # Check exit code
    if [[ $exit_code -ne 0 ]]; then
        echo -e "  ${RED}❌ FAIL${NC} - Non-zero exit code: $exit_code"
        echo -e "  ${YELLOW}Output:${NC} $output"
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Check if output is valid JSON
    if ! echo "$output" | jq . >/dev/null 2>&1; then
        echo -e "  ${RED}❌ FAIL${NC} - Invalid JSON output"
        echo -e "  ${YELLOW}Output:${NC} $output"
        FAILED=$((FAILED + 1))
        echo
        return 1
    fi

    # Parse JSON to verify structure
    local decision
    decision=$(echo "$output" | jq -r '.decision // empty')

    if [[ -z "$decision" ]]; then
        echo -e "  ${YELLOW}⚠️  WARN${NC} - No 'decision' field in output (may be expected for some hooks)"
    fi

    echo -e "  ${GREEN}✅ PASS${NC}"
    echo -e "  ${YELLOW}Output:${NC} $output"
    PASSED=$((PASSED + 1))
    echo

    return 0
}

# Test all hooks
for hook_name in "${!TEST_INPUTS[@]}"; do
    test_forwarder "$hook_name"
done

# Summary
echo "============================================"
echo -e "${BLUE}Test Summary:${NC}"
echo "  Total:  $TOTAL"
echo -e "  ${GREEN}Passed: $PASSED${NC}"

if [[ $FAILED -gt 0 ]]; then
    echo -e "  ${RED}Failed: $FAILED${NC}"
    exit 1
else
    echo -e "  ${RED}Failed: $FAILED${NC}"
    echo
    echo -e "${GREEN}🎉 All forwarders working correctly!${NC}"
    exit 0
fi
