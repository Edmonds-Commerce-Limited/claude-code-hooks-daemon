#!/usr/bin/env bash
#
# Test script for SessionStart hook with YOLO detection
#
# Usage: bash session-start-test.sh

echo "Testing SessionStart hook..."
echo

# Test input
TEST_INPUT='{"hook_event_name":"SessionStart","source":"new"}'

# Run hook
echo "Input: $TEST_INPUT"
echo
echo "Output:"
echo "$TEST_INPUT" | .claude/hooks/session-start | jq .

echo
echo "Expected behavior:"
echo "- decision: allow"
echo "- reason: null"
echo "- context: Array of detection messages (if in YOLO container) or empty array"
