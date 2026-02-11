---
name: acceptance-test
description: Acceptance testing - execute handler tests via real Claude Code tool calls in main thread
argument-hint: "[all|blocking-only|advisory-only|context-only|handler-name]"
---

# /acceptance-test - Acceptance Testing Skill

## Description

Execute acceptance tests for hooks daemon handlers via **real Claude Code tool calls in the main thread**. Tests verify real-world handler behaviour by invoking actual tools (Bash, Write, Edit, Read) and observing hook responses in system-reminders.

## CRITICAL: Main Thread Only

**Acceptance tests MUST be executed in the main Claude Code session.** Sub-agent strategies (parallel Haiku batches) are unreliable and forbidden:

- Sub-agents run out of context on large test suites
- Sub-agents cannot use Write/Edit tools (PreToolUse:Write tests fail)
- Lifecycle events (SessionStart, SessionEnd) only fire in the main session
- Advisory messages in system-reminders are only visible to the main session
- The v2.9.0 incident proved async agents create race conditions with release gates

**The ONLY valid acceptance test is a real tool call in the main thread with the hook response observed directly.**

## Usage

```bash
# Test all handlers (default)
/acceptance-test
/acceptance-test all

# Test only blocking handlers
/acceptance-test blocking-only

# Test only advisory handlers
/acceptance-test advisory-only

# Test only context injection handlers
/acceptance-test context-only

# Test specific handler by name substring
/acceptance-test DestructiveGit
/acceptance-test npm
```

## Parameters

- **filter** (optional): Test filter
  - `all` (default): Run all tests
  - `blocking-only`: Only blocking handlers (test_type=blocking)
  - `advisory-only`: Only advisory handlers (test_type=advisory)
  - `context-only`: Only context injection handlers (test_type=context)
  - `<handler-substring>`: Filter by handler name (e.g., "Git", "npm", "TDD")

## What It Does

1. **Restarts daemon** to ensure latest code loaded
2. **Generates test playbook** from handler code via `generate-playbook`
3. **Executes each test sequentially** in the main thread using real tool calls
4. **Observes hook responses** in system-reminders and tool output
5. **Records pass/fail** for each test based on observed behaviour
6. **Reports summary** with pass/fail/skip counts

## Execution Method

Tests are executed **one at a time** via real Claude Code tool calls:

**BLOCKING tests** (expected: deny):
```
# Use Bash tool with the test command
Bash: echo "git reset --hard HEAD"
# Observe: PreToolUse hook blocking error in output
# Result: PASS if blocked, FAIL if command executed
```

**ADVISORY tests** (expected: allow with context):
```
# Use Bash tool with the test command
Bash: echo "git stash"
# Observe: PreToolUse hook additional context in system-reminder
# Result: PASS if advisory shown, FAIL if no advisory
```

**WRITE/EDIT tests** (expected: deny or allow):
```
# Use Write tool with test content
Write: file_path="/tmp/test.py" content="x = 1  # type: ignore"
# Observe: PreToolUse:Write hook blocking error
# Result: PASS if blocked, FAIL if write succeeded
```

**CONTEXT tests** (expected: allow with context):
```
# Verified by observing system-reminders during normal tool use
# SessionStart, PostToolUse, UserPromptSubmit already fire every turn
# Result: PASS if system-reminder shows handler active
```

## Test Types

**BLOCKING Tests**:
- Command is blocked by handler (deny decision)
- Verifies destructive operations are prevented
- Examples: git reset --hard, rm -rf, sudo pip, sed -i

**ADVISORY Tests**:
- Command succeeds but handler adds advisory context
- Verifies informational messages appear in system-reminders
- Examples: npm install warnings, git stash warnings, TDD reminders

**CONTEXT Tests**:
- Handler injects context into system-reminder
- Verified by observing system-reminders during session
- Examples: SessionStart hook active, PostToolUse hook active

## Lifecycle Event Handling

Tests for lifecycle events (`SessionStart`, `SessionEnd`, `PreCompact`, `Stop`, `SubagentStop`, `Notification`, `PermissionRequest`, `Status`) fire automatically during normal session usage. They are verified by:

1. **SessionStart**: Confirmed at session start via system-reminder
2. **PostToolUse**: Confirmed after every tool call via system-reminder
3. **UserPromptSubmit**: Confirmed on every user message via system-reminder
4. **Others**: Confirmed by daemon loading without errors (checked via `daemon status` and `daemon logs`)

These are marked **PASS (verified via session)** rather than individually executed.

## Output

On success:
```
Acceptance Tests Complete!

Results Summary:
   Total tests: 107
   Passed: 62 (direct tool call verification)
   Skipped: 45 (lifecycle events - verified via session/daemon load)
   Failed: 0

All tests passed! Handlers working correctly.
```

On failure:
```
Acceptance Tests FAILED!

Results Summary:
   Total tests: 107
   Passed: 59
   Failed: 3
   Skipped: 45

Failed Tests:
   1. RubyQaSuppression - rubocop:disable not blocked
   2. BritishEnglish - advisory not shown
   3. MarkdownOrganization - memory path blocked

Investigation needed - fix handler bugs before release.
Enter FAIL-FAST cycle: TDD fix -> QA -> restart -> retest ALL from beginning.
```

## Time Investment

- **Full suite**: 15-30 minutes (sequential main-thread execution)
- **Blocking only**: 5-10 minutes
- **Single handler**: 1-2 minutes

Sequential execution is slower than parallel but **100% reliable**.

## Requirements

- **Daemon running**: Must have hooks daemon active
- **Main thread**: Tests MUST run in the main Claude Code session (NOT sub-agents)
- **Real tool calls**: Each test must use actual Bash/Write/Edit/Read tools

## Integration with Release Process

This skill is used during the release workflow:

```bash
/release
  -> Stage 4: Acceptance Testing Gate (BLOCKING)
     -> Main Claude executes /acceptance-test all
     -> Tests run sequentially in main thread
     -> Each test is a real tool call with observed response
     -> If ANY test fails -> ABORT release, enter FAIL-FAST cycle
```

**See**: `CLAUDE/development/RELEASING.md` for complete release workflow

## Documentation

**Playbook generation**: `generate-playbook` CLI command
**Test definitions**: Each handler's `get_acceptance_tests()` method
**Generating docs**: `CLAUDE/AcceptanceTests/GENERATING.md`

## Version

Introduced in: v2.9.0 (Plan 00044)
Updated in: v2.10.0 - Switched from parallel sub-agent to main-thread sequential execution
