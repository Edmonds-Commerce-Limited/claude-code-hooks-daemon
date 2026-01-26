#!/bin/bash
#
# Test forwarders handle control characters correctly
#
# REGRESSION TEST: jq -Rs breaks on control characters in hook input
# This test verifies the fix works (using jq without -R flag)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOOKS_DIR="$SCRIPT_DIR/hooks"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🧪 Testing Forwarders with Control Characters${NC}"
echo "============================================"
echo

# Test input with control characters (newlines, tabs, quotes)
# This is typical output that Claude Code sends containing bash commands
TEST_INPUT_WITH_CONTROL_CHARS='{
    "tool_name": "Bash",
    "tool_input": {
        "command": "echo \"Hello\\nWorld\"\ttest\nls -la"
    }
}'

echo -e "${BLUE}Test Input:${NC}"
echo "$TEST_INPUT_WITH_CONTROL_CHARS" | jq .
echo

# Test pre-tool-use forwarder
HOOK_FILE="$HOOKS_DIR/pre-tool-use"

if [[ ! -f "$HOOK_FILE" ]]; then
    echo -e "${RED}❌ FAIL${NC} - Hook file not found: $HOOK_FILE"
    exit 1
fi

if [[ ! -x "$HOOK_FILE" ]]; then
    echo -e "${RED}❌ FAIL${NC} - Hook file not executable"
    exit 1
fi

echo -e "${BLUE}Running forwarder...${NC}"

# Execute hook with control character input
OUTPUT=$(echo "$TEST_INPUT_WITH_CONTROL_CHARS" | "$HOOK_FILE" 2>&1) || EXIT_CODE=$?
EXIT_CODE=${EXIT_CODE:-0}

if [[ $EXIT_CODE -ne 0 ]]; then
    echo -e "${RED}❌ FAIL${NC} - Non-zero exit code: $EXIT_CODE"
    echo -e "${YELLOW}Output:${NC}"
    echo "$OUTPUT"
    exit 1
fi

# Verify output is valid JSON
if ! echo "$OUTPUT" | jq . >/dev/null 2>&1; then
    echo -e "${RED}❌ FAIL${NC} - Invalid JSON output"
    echo -e "${YELLOW}Output:${NC}"
    echo "$OUTPUT"
    exit 1
fi

echo -e "${GREEN}✅ PASS${NC} - Forwarder handled control characters correctly"
echo -e "${YELLOW}Output:${NC}"
echo "$OUTPUT" | jq .
echo

# Verify the daemon received the correct structure
DECISION=$(echo "$OUTPUT" | jq -r '.decision // empty')
if [[ -n "$DECISION" ]]; then
    echo -e "${GREEN}✅ PASS${NC} - Daemon processed request (decision: $DECISION)"
else
    echo -e "${YELLOW}⚠️  WARN${NC} - No decision in response (may be expected)"
fi

echo
echo "============================================"
echo -e "${GREEN}🎉 Control character handling test PASSED${NC}"
echo
echo "This test verifies the fix for the jq -Rs regression."
echo "DO NOT change the jq command back to use -R or -s flags!"
