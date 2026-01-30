# Acceptance Testing Playbook - Implementation Plan

**Status**: Complete
**Created**: 2026-01-30
**Completed**: 2026-01-30
**Owner**: Claude Code
**Priority**: High

---

## Overview

Create a simple markdown playbook that I (Claude Code) can read and execute to validate that all hooks daemon handlers work correctly in real-world usage.

The playbook will contain safe test commands that trigger handler patterns without causing damage if handlers fail.

---

## Problem Statement

Despite comprehensive unit tests (2,699 tests, 95%+ coverage), handlers sometimes don't work as expected in actual Claude Code sessions because:
- Tests use mock hook inputs, not real Claude Code event formats
- No validation against actual daemon integration
- Need real-world acceptance testing

---

## Solution

**Single markdown playbook** (`CLAUDE/AcceptanceTests/PLAYBOOK.md`) that:
- Contains step-by-step test instructions
- Uses SAFE commands (e.g., `echo "git reset --hard"`) that won't cause harm if handlers fail
- Tests by attempting tool calls that trigger handlers
- Provides clear pass/fail criteria for each test
- Can be executed by Claude Code directly

**Key Insight**: Commands like `echo "git reset --hard"` are safe because:
- If handler works → Blocks the echo command (no execution)
- If handler broken → Echo executes harmlessly (just prints text)
- The handler matches on the full command string, so pattern is detected

---

## Playbook Structure

```markdown
# Acceptance Testing Playbook

## Prerequisites
- Daemon running (check with: $PYTHON -m claude_code_hooks_daemon.daemon.cli status)
- Clean git working tree

## Test 1: DestructiveGitHandler
### Test 1.1: git reset --hard
**Tool**: Bash
**Command**: `echo "git reset --hard HEAD"`
**Expected**: BLOCKED with message about destroying uncommitted changes
**Result**: [ ] PASS [ ] FAIL

### Test 1.2: git clean -f
**Tool**: Bash
**Command**: `echo "git clean -fd"`
**Expected**: BLOCKED with message about deleting untracked files
**Result**: [ ] PASS [ ] FAIL

[... more tests ...]

## Results Summary
| Handler | Result | Notes |
|---------|--------|-------|
| DestructiveGitHandler | [ ] PASS [ ] FAIL | |
| SedBlockerHandler | [ ] PASS [ ] FAIL | |
[... etc ...]
```

---

## Implementation Tasks

### Phase 1: Create Playbook File Structure
- [ ] Create `CLAUDE/AcceptanceTests/` directory
- [ ] Create `PLAYBOOK.md` with header and instructions
- [ ] Add prerequisites section
- [ ] Add results summary template

### Phase 2: Blocking Handler Tests (Priority 10-30)

**Test 1: DestructiveGitHandler** (Priority 10)
- [ ] Test 1.1: `echo "git reset --hard HEAD"` → should block
- [ ] Test 1.2: `echo "git clean -fd"` → should block
- [ ] Test 1.3: `echo "git push --force origin main"` → should block
- [ ] Test 1.4: `echo "git stash drop"` → should block
- [ ] Test 1.5: `echo "git checkout -- src/file.py"` → should block

**Test 2: SedBlockerHandler** (Priority 11)
- [ ] Test 2.1: `echo "sed -i 's/foo/bar/g' file.txt"` → should block
- [ ] Test 2.2: `echo "sed -e 's/old/new/' input.txt"` → should block

**Test 3: PipeBlockerHandler** (Priority 12)
- [ ] Test 3.1: `echo "npm test | tail -5"` → should block
- [ ] Test 3.2: `echo "pytest | head -20"` → should block

**Test 4: AbsolutePathHandler** (Priority 20)
- [ ] Test 4.1: Attempt Read with relative path `relative/path/file.txt` → should block
- [ ] Test 4.2: Attempt Write to `some/relative/path.txt` → should block

**Test 5: TddEnforcementHandler** (Priority 25)
- [ ] Test 5.1: Attempt Write to `/tmp/test-handlers/fake_handler.py` (no test file) → should block

**Test 6: EslintDisableHandler** (Priority 30)
- [ ] Test 6.1: Attempt Write to `/tmp/test.js` with `// eslint-disable-next-line` → should block
- [ ] Test 6.2: Attempt Write to `/tmp/test.ts` with `/* eslint-disable */` → should block

**Test 7: PythonQaSuppressionBlocker** (Priority 28)
- [ ] Test 7.1: Attempt Write to `/tmp/test.py` with `# type: ignore` → should block
- [ ] Test 7.2: Attempt Write to `/tmp/test.py` with `# noqa` → should block

**Test 8: GoQaSuppressionBlocker** (Priority 29)
- [ ] Test 8.1: Attempt Write to `/tmp/test.go` with `// nolint` → should block

### Phase 3: Advisory Handler Tests (Priority 36-60)

**Test 9: BritishEnglishHandler** (Priority 56)
- [ ] Test 9.1: Attempt Write to `/tmp/docs/test.md` with "color" → should allow with advisory

**Test 10: WebSearchYearHandler** (Priority 50)
- [ ] Test 10.1: Observational - note if outdated year suggestions appear in web searches

**Test 11: BashErrorDetectorHandler** (PostToolUse)
- [ ] Test 11.1: Run `ls /nonexistent/path/that/does/not/exist` → should provide advisory after error

**Test 12: PlanWorkflowHandler** (Priority 48)
- [ ] Test 12.1: Attempt Write to `/tmp/CLAUDE/Plan/00999-test/PLAN.md` → should allow with advisory

### Phase 4: Context Injection Tests

**Test 13: GitContextInjectorHandler** (UserPromptSubmit)
- [ ] Test 13.1: Observational - verify git context appears in responses

**Test 14: WorkflowStateRestorationHandler** (SessionStart)
- [ ] Test 14.1: Mark as SKIP (requires session compaction event)

**Test 15: DaemonStatsHandler** (StatusLine)
- [ ] Test 15.1: Observational - verify daemon stats in status line

### Phase 5: Finalization
- [ ] Review all tests for safety (confirm no destructive operations possible)
- [ ] Add cleanup section (remove /tmp/test* files after testing)
- [ ] Test the playbook by executing it myself
- [ ] Document any handler failures found
- [ ] Update plan status to Complete

---

## Safe Command Patterns

### For Bash Tool Tests
Use `echo "dangerous command"` pattern:
- `echo "git reset --hard HEAD"` ✅ Safe
- `echo "sed -i 's/foo/bar/' file.txt"` ✅ Safe
- `echo "rm -rf /"` ✅ Safe (but should also be blocked!)

Handlers match on the full command string, so patterns are detected even inside echo.

### For Write Tool Tests
Write to `/tmp/` with test content:
- `/tmp/test-handlers/fake_handler.py` ✅ Safe (writes to /tmp)
- `/tmp/test.js` with suppressions ✅ Safe (writes to /tmp)
- `/tmp/docs/test.md` with American spellings ✅ Safe (writes to /tmp)

If handler fails, harmless files created in /tmp (cleaned up after testing).

### For Read Tool Tests
Use non-existent relative paths:
- `relative/path/file.txt` ✅ Safe (file doesn't exist, Read fails harmlessly)
- `some/relative/path.txt` ✅ Safe (handler blocks before Read executes)

---

## Success Criteria

- [ ] Playbook created with all 15 handler tests
- [ ] All tests use safe commands (no destructive operations possible)
- [ ] Each test has clear pass/fail criteria
- [ ] Results summary table included
- [ ] Playbook is executable by Claude Code (clear instructions)
- [ ] Documents baseline handler behavior for regression testing

---

## Critical Safety Rules

1. **NEVER use actual destructive commands** (e.g., `git reset --hard`, `rm -rf`)
2. **ALWAYS use echo for bash patterns** (e.g., `echo "git reset --hard"`)
3. **ALWAYS write to /tmp/** for file write tests
4. **ALWAYS use non-existent paths** for Read tests with relative paths
5. **VERIFY handler fired** by checking for blocking error or advisory context

---

## Edge Cases & Considerations

1. **Echo-based tests and pattern matching**: Handlers examine the full bash command string. `echo "git reset --hard HEAD"` contains the dangerous pattern, so handlers match it. This is desired behavior - slightly over-cautious but safe.

2. **Write-to-/tmp tests**: If handlers fail, only harmless files created in /tmp. Include cleanup section in playbook to remove these after testing.

3. **Advisory handlers**: Don't block operations, just provide context/guidance. Pass criteria: operation succeeds AND advisory message received.

4. **Untestable handlers**: SessionStart (requires compaction), StatusLine (observational). Mark as SKIP or OBSERVATIONAL in results.

5. **Daemon must be running**: Playbook starts with prerequisite check to verify daemon is active.

---

## Files to Create

- `/workspace/CLAUDE/AcceptanceTests/PLAYBOOK.md` - The executable playbook (ONLY file needed)

---

## Next Steps

1. Create `CLAUDE/AcceptanceTests/` directory
2. Write `PLAYBOOK.md` with all 15 handler tests
3. Execute the playbook myself to validate handlers
4. Document results and any failures found
5. Mark plan as Complete

---

## Notes

- The original plan was over-engineered (bash orchestration scripts, validation frameworks, etc.)
- This simplified approach focuses on the core goal: a markdown checklist I can execute
- Safe commands proven to work (tested `echo "git reset --hard"` successfully)
- Hooks are working correctly when using proper safe test patterns
