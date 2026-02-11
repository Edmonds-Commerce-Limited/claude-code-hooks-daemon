---
name: acceptance-test
description: Automated acceptance testing - execute handler tests in parallel batches and report comprehensive results
argument-hint: "[all|blocking-only|advisory-only|context-only|handler-name]"
---

# /acceptance-test - Automated Acceptance Testing Skill

## Description

Execute acceptance tests for hooks daemon handlers in parallel batches. Tests verify real-world handler behavior by running commands in Claude Code sessions and checking hook responses.

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
2. **Generates test playbook** as JSON with optional filters
3. **Groups tests** into batches of 3-5 for parallel execution
4. **Spawns parallel Haiku agents** to execute batches concurrently
5. **Collects results** from all agents
6. **Reports comprehensive summary** with pass/fail/skip counts

## Agent Architecture

Uses specialized `acceptance-test-runner` agent (Haiku model):
- **Fast & cheap**: Haiku for parallel batch execution
- **Read-only**: No file modifications, only command execution
- **Structured output**: Returns JSON for programmatic aggregation
- **Lifecycle handling**: Auto-skips SessionStart/SessionEnd/PreCompact events

## Test Types

**BLOCKING Tests**:
- Command is blocked by handler (deny decision)
- Verifies destructive operations are prevented
- Examples: git reset --hard, rm -rf, sudo pip

**ADVISORY Tests**:
- Command succeeds but handler adds advisory context
- Verifies informational messages appear
- Examples: npm install warnings, TDD reminders

**CONTEXT Tests**:
- Handler injects context into system-reminder
- Verifies context injection works
- Examples: git status, plan numbers

## Lifecycle Event Handling

Tests requiring lifecycle events (`SessionStart`, `SessionEnd`, `PreCompact`) cannot be triggered by subagents and are automatically marked **SKIP** (not FAIL). This is expected behavior.

## Output

On success:
```
✅ Acceptance Tests Complete!

📊 Results Summary:
   Total tests: 90
   Passed: 87
   Failed: 0
   Skipped: 3 (lifecycle events)

🎯 Handler Coverage:
   Blocking handlers: 45/45 passed
   Advisory handlers: 32/32 passed
   Context handlers: 10/10 passed

⏱️  Execution time: 4m 32s
🔧 Parallel batches: 18 (5 tests each)

All tests passed! Handlers working correctly.
```

On failure:
```
❌ Acceptance Tests Failed!

📊 Results Summary:
   Total tests: 90
   Passed: 85
   Failed: 2
   Skipped: 3 (lifecycle events)

❌ Failed Tests:
   1. DestructiveGitHandler - Test #3 (git push --force)
      Expected: Command blocked
      Actual: Command succeeded (handler didn't block)

   2. NpmAuditHandler - Test #17 (npm install advisory)
      Expected: Advisory message in system-reminder
      Actual: No advisory found

🔍 Investigation needed - fix handler bugs before release.
```

## Time Investment

- **Small filter** (10-20 tests): 1-2 minutes
- **Medium filter** (30-50 tests): 2-4 minutes
- **Full suite** (90+ tests): 4-6 minutes

Time scales with test count and batch parallelization.

## Requirements

- **Daemon running**: Must have hooks daemon active
- **Clean state**: Fresh Claude Code session recommended
- **Patience**: Parallel execution is fast but comprehensive testing takes time

## Error Handling

**Daemon not running**:
```
❌ Daemon not running
   Run: $PYTHON -m claude_code_hooks_daemon.daemon.cli restart
```

**No tests found**:
```
⚠️  No tests match filter: "NonexistentHandler"
   Check handler name or use different filter
```

**Agent batch failure**:
```
❌ Batch 3 failed to execute
   Re-running batch 3 individually...
```

## Integration with Release Process

This skill is used during the release workflow:

```bash
/release
  └─> Stage 2: Acceptance Testing Gate
      └─> Invokes: /acceptance-test all
          └─> If ANY test fails → ABORT release
```

**See**: `CLAUDE/development/RELEASING.md` for complete release workflow

## Documentation

**Agent spec**: `.claude/agents/acceptance-test-runner.md`
**Playbook generation**: `generate-playbook` CLI command with `--format json`

## Version

Introduced in: v2.9.0 (Plan 00044)
