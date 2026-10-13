---
name: acceptance-test
description: Acceptance testing - execute handler tests via real Claude Code tool calls in main thread
argument-hint: "[all|blocking-only|advisory-only|context-only|handler-name]"
---

# /acceptance-test - Acceptance Testing Skill

## Run this first

Claude Code loads this markdown and nothing else — the file below is not run
for you, and it holds the procedure to follow (Plan 00324):

```bash
bash "${CLAUDE_SKILL_DIR:-.claude/skills/acceptance-test}/invoke.sh" <filter, or omit for all>
```

Follow its output exactly; what is written here is orientation.

## Description

Execute acceptance tests for hooks daemon handlers via **real Claude Code tool calls in the main thread**. Tests verify real-world handler behaviour by invoking actual tools (Bash, Write, Edit, Read) and observing hook responses in system-reminders.

## Execution Routing

**Each test's `Requires Main Thread` field in the generated playbook decides where it runs.** The method's canonical
home is `CLAUDE/AcceptanceTests/GENERATING.md` ("SUB-AGENT EXECUTION"); `CLAUDE/development/RELEASING.md` Step 12
points there too. In short:

- **`Requires Main Thread: yes`** — run in the main session, sequentially, and NEVER delegate. Lifecycle events
  (SessionStart, SessionEnd, UserPromptSubmit) and this session's system-reminders cannot be observed from a
  sub-agent. The v2.9.0 incident (async agents created race conditions with release gates) is why these stay in the
  main thread.
- **`Requires Main Thread: no`** — may be delegated to parallel sub-agents, batched by the playbook's
  `Recommended Model` field (haiku for blocking tests, sonnet for advisory). Verified experimentally: sub-agents ARE
  blocked by PreToolUse hooks (Write and Edit included) and DO see PostToolUse system-reminders in their own context.

The measured hook-visibility table and per-test-type model rules are in `CLAUDE/AcceptanceTests/GENERATING.md`
("SUB-AGENT EXECUTION"). Whoever delegates still owns the result: every delegated test is a real tool call whose hook response was observed, and
the main thread tallies the results before the gate passes.

## Usage

```claude-code
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
3. **Executes each test** as a real tool call, routed by `Requires Main Thread` (see Execution Routing)
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
- **Main thread**: Tests marked `Requires Main Thread: yes` MUST run in the main Claude Code session
- **Real tool calls**: Each test must use actual Bash/Write/Edit/Read tools

## Integration with Release Process

This skill is used during the release workflow:

```text
/release
  -> Stage 4: Acceptance Testing Gate (BLOCKING)
     -> Main Claude executes /acceptance-test all
     -> Main-thread tests run sequentially; others may be delegated (see Execution Routing)
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
Updated: routing by the playbook's `Requires Main Thread` field (Plan 00474 N458)
