#!/usr/bin/env bash
# Test safety blocker handlers
# Tests: DestructiveGit, SedBlocker, PipeBlocker, AbsolutePath

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCEPTANCE_ROOT="$(dirname "$SCRIPT_DIR")"

# shellcheck source=/dev/null
source "$ACCEPTANCE_ROOT/validation/test-helpers.sh"

echo "========================================"
echo "Test Scenario 01: Safety Blockers"
echo "========================================"
echo ""

# Test 1: Destructive Git Handler
echo "Test 1: Destructive Git Handler"
echo "--------------------------------"

log_info "Test 1.1: git reset --hard should be blocked"
# In actual Claude Code session, attempting this should trigger handler
# For now, just document the expected behavior
log_info "Expected: Handler denies with message about destroying uncommitted changes"

log_info "Test 1.2: git clean -f should be blocked"
log_info "Expected: Handler denies with message about permanently deleting untracked files"

log_info "Test 1.3: git push --force should be blocked"
log_info "Expected: Handler denies with message about overwriting remote history"

log_info "Test 1.4: git push -f should be blocked"
log_info "Expected: Handler denies with message about overwriting remote history"

echo ""

# Test 2: Sed Blocker Handler
echo "Test 2: Sed Blocker Handler"
echo "---------------------------"

log_info "Test 2.1: sed -i in bash command should be blocked"
log_info "Expected: Handler denies with message about using Edit tool instead"

log_info "Test 2.2: sed -i in file Write should be blocked"
log_info "Expected: Handler denies with message about using Edit tool instead"

echo ""

# Test 3: Pipe Blocker Handler
echo "Test 3: Pipe Blocker Handler"
echo "----------------------------"

log_info "Test 3.1: npm test | tail should be blocked"
log_info "Expected: Handler denies with message about needing complete output"

log_info "Test 3.2: find . -name '*.py' | head should be blocked"
log_info "Expected: Handler denies with message about using Glob tool instead"

log_info "Test 3.3: pytest | grep should be blocked"
log_info "Expected: Handler denies with message about needing complete output"

echo ""

# Test 4: Absolute Path Handler
echo "Test 4: Absolute Path Handler"
echo "-----------------------------"

log_info "Test 4.1: Read with relative path should be blocked"
log_info "Expected: Handler denies with message about requiring absolute path"

log_info "Test 4.2: Write with relative path should be blocked"
log_info "Expected: Handler denies with message about requiring absolute path"

log_info "Test 4.3: Edit with relative path should be blocked"
log_info "Expected: Handler denies with message about requiring absolute path"

echo ""
echo "========================================"
echo "Safety Blockers Tests Complete"
echo "========================================"
echo ""
echo "NOTE: These tests are placeholders for manual execution in Claude Code."
echo "The actual handler behavior should be verified by:"
echo "  1. Starting daemon debug logging: ./scripts/debug_hooks.sh start"
echo "  2. Attempting these operations in a Claude Code session"
echo "  3. Verifying handlers block the operations"
echo "  4. Stopping debug logging: ./scripts/debug_hooks.sh stop"
echo "  5. Validating logs: ./CLAUDE/AcceptanceTests/validation/validate-logs.py <log-file>"
