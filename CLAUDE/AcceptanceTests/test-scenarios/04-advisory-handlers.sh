#!/usr/bin/env bash
# Test advisory handlers
# Tests: British English, Web Search Year, Bash Error Detector

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCEPTANCE_ROOT="$(dirname "$SCRIPT_DIR")"

# shellcheck source=/dev/null
source "$ACCEPTANCE_ROOT/validation/test-helpers.sh"

echo "========================================"
echo "Test Scenario 04: Advisory Handlers"
echo "========================================"
echo ""

# Test 1: British English Handler
echo "Test 1: British English Handler"
echo "--------------------------------"

log_info "Test 1.1: Writing 'color' should trigger advisory"
log_info "Expected: Handler allows but suggests 'colour' (British English)"

log_info "Test 1.2: Writing 'behavior' should trigger advisory"
log_info "Expected: Handler allows but suggests 'behaviour' (British English)"

log_info "Test 1.3: Writing 'organize' should trigger advisory"
log_info "Expected: Handler allows but suggests 'organise' (British English)"

echo ""

# Test 2: Web Search Year Handler
echo "Test 2: Web Search Year Handler"
echo "--------------------------------"

log_info "Test 2.1: WebSearch with '2023' should trigger advisory"
log_info "Expected: Handler allows but suggests using current year (2026)"

log_info "Test 2.2: WebSearch with '2024' should trigger advisory"
log_info "Expected: Handler allows but suggests using current year (2026)"

log_info "Test 2.3: WebSearch with '2026' should be allowed"
log_info "Expected: Handler allows without warning"

echo ""

# Test 3: Bash Error Detector Handler
echo "Test 3: Bash Error Detector Handler"
echo "------------------------------------"

log_info "Test 3.1: Bash command with exit code 1 should trigger advisory"
log_info "Expected: Handler detects error and suggests investigation"

log_info "Test 3.2: Bash command with exit code 0 should be allowed"
log_info "Expected: Handler allows without warning"

echo ""
echo "========================================"
echo "Advisory Handlers Tests Complete"
echo "========================================"
echo ""
echo "NOTE: These tests are placeholders for manual execution in Claude Code."
echo "The actual handler behavior should be verified by:"
echo "  1. Starting daemon debug logging: ./scripts/debug_hooks.sh start"
echo "  2. Performing these operations in a Claude Code session"
echo "  3. Verifying handlers provide advisory messages"
echo "  4. Stopping debug logging: ./scripts/debug_hooks.sh stop"
echo "  5. Validating logs: ./CLAUDE/AcceptanceTests/validation/validate-logs.py <log-file>"
