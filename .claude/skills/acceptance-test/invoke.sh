#!/usr/bin/env bash
# /acceptance-test skill - Main-thread sequential acceptance testing

set -euo pipefail

FILTER="${1:-all}"

cat <<PROMPT
# Acceptance Testing - Main Thread Sequential - Filter: ${FILTER}

Execute acceptance tests for hooks daemon handlers via **real Claude Code tool calls in the main thread**.

**CRITICAL**: All tests MUST be executed as real tool calls (Bash, Write, Edit, Read) in this main session.
Sub-agent testing is FORBIDDEN - agents cannot reliably test hooks (context limits, no Write tool, lifecycle events don't fire).

## Step 1: Restart Daemon

Ensure latest code is loaded:

\`\`\`bash
\$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
\`\`\`

**Expected**: "Daemon started successfully"

If daemon fails to start, ABORT and report error.

## Step 2: Generate Test Playbook (JSON)

Generate tests based on filter:

**Filter: ${FILTER}**

\`\`\`bash
# Determine filter flags based on input
FILTER_TYPE=""
FILTER_HANDLER=""

case "${FILTER}" in
    "all")
        # No filters - all tests
        ;;
    "blocking-only")
        FILTER_TYPE="--filter-type blocking"
        ;;
    "advisory-only")
        FILTER_TYPE="--filter-type advisory"
        ;;
    "context-only")
        FILTER_TYPE="--filter-type context"
        ;;
    *)
        # Handler name substring
        FILTER_HANDLER="--filter-handler ${FILTER}"
        ;;
esac

# Generate JSON playbook
\$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook --format json \$FILTER_TYPE \$FILTER_HANDLER > /tmp/acceptance_tests.json
\`\`\`

**Expected**: Valid JSON array of test objects

Verify JSON is valid and count tests:
\`\`\`bash
TOTAL_TESTS=\$(python3 -c "import json; print(len(json.load(open('/tmp/acceptance_tests.json'))))")
echo "Total tests: \$TOTAL_TESTS"
\`\`\`

**If TOTAL_TESTS = 0**: Report "No tests match filter: ${FILTER}" and STOP.

## Step 3: Execute Tests Sequentially in Main Thread

**For EACH test** in the playbook, execute it as a REAL tool call:

### Read the playbook
\`\`\`bash
cat /tmp/acceptance_tests.json
\`\`\`

### For each test, follow this pattern:

**BLOCKING tests** (test_type=blocking, expected: command blocked):
1. Use Bash tool with the test command (e.g., \`echo "git reset --hard HEAD"\`)
2. Observe: PreToolUse hook should block with error message
3. Check expected_message_patterns appear in block message
4. Result: PASS if blocked, FAIL if command executed

**ADVISORY tests** (test_type=advisory, expected: allow with context):
1. Use Bash tool with the test command (e.g., \`echo "git stash"\`)
2. Observe: Command succeeds, system-reminder contains advisory message
3. Check expected_message_patterns appear in system-reminder
4. Result: PASS if advisory shown, FAIL if no advisory

**CONTEXT tests** (test_type=context, expected: context injection):
1. Verified by observing system-reminders during normal tool use
2. SessionStart, PostToolUse, UserPromptSubmit fire every turn
3. Result: PASS if system-reminder shows handler active

**WRITE/EDIT tests** (expected: deny or allow):
1. Use Write tool with test content (e.g., file with QA suppression)
2. Observe: PreToolUse:Write hook blocking error
3. Result: PASS if blocked, FAIL if write succeeded

### Lifecycle Event Tests

Tests requiring lifecycle events (SessionStart, SessionEnd, PreCompact, Stop, SubagentStop) are verified by:
1. **SessionStart**: Confirmed at session start via system-reminder (already active)
2. **PostToolUse**: Confirmed after every tool call via system-reminder (already active)
3. **UserPromptSubmit**: Confirmed on every user message via system-reminder (already active)
4. **Others**: Confirmed by daemon loading without errors

Mark lifecycle tests as **PASS (verified via session)** rather than individually executed.

## Step 4: Track Results

Keep a running tally as you execute each test:

- **PASS**: Expected behavior observed
- **FAIL**: Unexpected behavior (handler bug) - STOP and investigate
- **SKIP**: Lifecycle event verified via session (not individually testable)

## Step 5: Report Results

After all tests complete, report:

If all tests passed (no failures):
\`\`\`
Acceptance Tests Complete!

Results Summary:
   Total tests: {total}
   Passed: {passed} (direct tool call verification)
   Skipped: {skipped} (lifecycle events - verified via session/daemon load)
   Failed: 0

All tests passed! Handlers working correctly.
\`\`\`

If any tests failed:
\`\`\`
Acceptance Tests FAILED!

Results Summary:
   Total tests: {total}
   Passed: {passed}
   Failed: {failed}
   Skipped: {skipped}

Failed Tests:
   1. HandlerName - description of failure
   2. HandlerName - description of failure

Investigation needed - fix handler bugs before release.
Enter FAIL-FAST cycle: TDD fix -> QA -> restart -> retest ALL from beginning.
\`\`\`

## FAIL-FAST Cycle (if any test fails)

1. STOP testing immediately
2. Investigate root cause of failure
3. Fix bug using TDD (write failing test -> implement fix -> verify)
4. Run FULL QA: \`./scripts/qa/run_all.sh\` (must pass 100%)
5. Restart daemon: \`\$PYTHON -m claude_code_hooks_daemon.daemon.cli restart\`
6. **RESTART acceptance testing FROM TEST 1** (not from where you left off)
7. Continue until ALL tests pass with ZERO code changes

## Cleanup

After reporting results:
\`\`\`bash
rm -f /tmp/acceptance_tests.json
\`\`\`

---

**Documentation**: SKILL.md for complete spec, CLAUDE/development/RELEASING.md for release integration

Begin Step 1 now (restart daemon).
PROMPT
