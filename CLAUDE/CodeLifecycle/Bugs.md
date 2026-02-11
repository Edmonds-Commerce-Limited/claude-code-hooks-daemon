# Bug Fix Lifecycle

**Status**: MANDATORY for all bug fixes
**Audience**: AI agents and human developers

## Overview

Rigorous process to fix bugs with confidence that they won't return.

**Core Principle**: If you can't reproduce it with a failing test, you can't be sure it's fixed.

## The Bug Fix Cycle

```
1. REPRODUCE → 2. WRITE FAILING TEST → 3. FIX → 4. VERIFY TEST PASSES → 5. REGRESSION TEST → 6. DAEMON RESTART → 7. LIVE VERIFY
```

## Phase 1: Reproduce the Bug

### Steps

1. **Gather information**:
   - Bug report/GitHub issue details
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details

2. **Reproduce locally**:
   - Follow exact steps from bug report
   - Verify bug occurs
   - Document exact conditions

3. **Identify affected component**:
   - Which handler/module is involved?
   - Which event type?
   - What inputs trigger it?

**Output**: Clear reproduction steps and root cause hypothesis.

## Phase 2: Write Failing Test (TDD)

**CRITICAL**: Write test that FAILS due to the bug.

### Unit Test for Bug

```python
def test_bug_XXX_handler_fails_to_match_pattern():
    """Regression test for GitHub Issue #XXX.

    Bug: HandlerName doesn't match pattern when [condition].
    This test MUST FAIL before the fix.
    """
    handler = HandlerName()

    # Setup conditions that trigger bug
    hook_input = {
        "tool_name": "Bash",
        "tool_input": {"command": "problematic command"}
    }

    # This assertion should FAIL (bug present)
    assert handler.matches(hook_input) is True  # Currently returns False (BUG)
```

### Integration Test (if applicable)

If bug involves component interactions:

```python
def test_bug_XXX_handler_integration_failure():
    """Integration test for bug #XXX.

    Bug: Handler doesn't integrate correctly with FrontController.
    """
    # Setup integration scenario
    # Assert current (broken) behavior
```

### Acceptance Test (if handler-related)

Add acceptance test via `get_acceptance_tests()` method if bug affects real-world usage.

**Run tests - they MUST FAIL**:
```bash
pytest tests/unit/.../test_bug_XXX.py -v
# Expected: FAILURE (proves bug exists)
```

## Phase 3: Implement Fix

### Fix Implementation

1. **Identify root cause** from failing test
2. **Implement minimal fix**:
   - Change only what's necessary
   - Don't refactor while fixing
   - Focus on making test pass

3. **Verify fix**:
   ```bash
   pytest tests/unit/.../test_bug_XXX.py -v
   # Expected: PASS (bug is fixed)
   ```

### Common Bug Patterns

**Import errors** (like the 5-handler issue):
```python
# WRONG
from claude_code_hooks_daemon.constants.decision import Decision

# RIGHT
from claude_code_hooks_daemon.core import Decision
```

**Pattern matching bugs**:
- Check regex escaping
- Verify case sensitivity flags
- Test edge cases

**Handler logic bugs**:
- Verify matches() and handle() alignment
- Check Decision.ALLOW vs Decision.DENY
- Verify terminal flag behavior

## Phase 4: Regression Testing

**CRITICAL**: Ensure fix doesn't break existing functionality.

### Run ALL Tests

```bash
# Run complete test suite
pytest tests/ -v

# Expected: ALL PASS (including new regression test)
```

### Run Full QA

```bash
./scripts/qa/run_all.sh

# Expected: ALL CHECKS PASSED
```

**If ANY test fails**: You introduced a regression. Fix it before proceeding.

## Phase 5: Daemon Verification (MANDATORY)

**CRITICAL**: Verify daemon loads successfully with fix.

```bash
# Restart daemon
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# Verify daemon is RUNNING
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Expected: Status: RUNNING

# Check logs for errors
$PYTHON -m claude_code_hooks_daemon.daemon.cli logs | grep -i error

# Expected: No errors related to your fix
```

**If daemon fails to start**: Your fix introduced an import/loading error. Fix it.

## Phase 6: Live Verification

Test in real environment:

1. **Reproduce original bug scenario**:
   - Use exact steps from bug report
   - Verify bug is no longer present

2. **Check for side effects**:
   - Test related functionality
   - Verify no new issues introduced

3. **Document fix**:
   - Update GitHub issue with fix details
   - Document root cause
   - Link to regression test

## Phase 7: Commit with Context

Commit message should explain the bug and fix:

```
Fix: HandlerName fails to match pattern with [condition]

Bug: Handler didn't recognize [pattern] due to [root cause].

Fix: [What was changed and why]

Regression test: tests/unit/.../test_bug_XXX.py

Fixes: #XXX
```

## Definition of Done Checklist

A bug fix is DONE when ALL of the following are verified:

### 1. Reproduction
- [ ] Bug reproduced locally
- [ ] Exact steps documented
- [ ] Root cause identified

### 2. Failing Test
- [ ] Unit test written that FAILS (proves bug exists)
- [ ] Integration test if applicable
- [ ] Acceptance test added if handler-related
- [ ] Run: `pytest -v -k bug_XXX` (tests FAIL before fix)

### 3. Fix Implementation
- [ ] Root cause fixed with minimal change
- [ ] Failing tests now PASS
- [ ] Run: `pytest -v -k bug_XXX` (tests PASS after fix)

### 4. Regression Testing
- [ ] All existing tests still pass
- [ ] No new test failures introduced
- [ ] Run: `pytest tests/ -v` (ALL PASS)

### 5. Full QA
- [ ] Run: `./scripts/qa/run_all.sh`
- [ ] Expected: "ALL CHECKS PASSED"

### 6. Daemon Verification
- [ ] Daemon restarts successfully
- [ ] No import errors in logs
- [ ] Run: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- [ ] Verify: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` (RUNNING)

### 7. Live Verification
- [ ] Original bug scenario no longer reproduces
- [ ] No side effects observed
- [ ] Fix documented in commit message and GitHub issue

## FAIL-FAST Cycle (For Acceptance Test Failures)

If bug is found during acceptance testing:

```
1. Stop acceptance testing immediately
2. Create failing test for bug (unit/integration)
3. Fix bug using TDD
4. Run FULL QA: ./scripts/qa/run_all.sh
5. Restart daemon successfully
6. RESTART acceptance testing FROM TEST 1.1
7. Continue until ALL tests pass with ZERO code changes
```

**Why restart from Test 1.1?**
Your fix might have affected earlier tests. Full re-run ensures no regressions.

## Example: The 5-Handler Import Bug

**Bug**: Daemon fails to start after adding 5 new handlers.

### How it SHOULD have been caught

**Step 1: Reproduce**
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
# Error: No module named 'claude_code_hooks_daemon.constants.decision'
```

**Step 2: Write failing test**
```python
def test_bug_daemon_loads_with_new_handlers():
    """Regression test: Daemon should load new handlers.

    Bug: Daemon fails to start due to import error in 5 new handlers.
    """
    # This would be an integration test that imports handlers
    from claude_code_hooks_daemon.handlers.pre_tool_use import pip_break_system
    # This would FAIL with ImportError
```

**Step 3: Fix**
```python
# Change in all 5 handlers:
# from claude_code_hooks_daemon.constants.decision import Decision
from claude_code_hooks_daemon.core import Decision
```

**Step 4: Verify test passes**
```bash
pytest tests/integration/test_bug_daemon_loads.py -v
# PASS
```

**Step 5: Restart daemon**
```bash
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
# Daemon started successfully
```

## Common Bug Types

### Import Errors
- Wrong module path
- Circular imports
- Missing dependencies

**Prevention**: Always restart daemon after code changes.

### Pattern Matching Bugs
- Regex escaping issues
- Case sensitivity
- Edge cases not covered

**Prevention**: Comprehensive unit tests with edge cases.

### Handler Logic Bugs
- matches() and handle() mismatch
- Wrong Decision enum
- Terminal flag incorrect

**Prevention**: Integration tests with real inputs.

## Summary

**Key Points**:

1. **Reproduce first** - Can't fix what you can't see
2. **Write failing test** - Proves bug exists
3. **Fix minimally** - Don't refactor while fixing
4. **Test comprehensively** - Unit, integration, full QA
5. **Restart daemon** - Catches import errors
6. **Verify in real usage** - Ensure bug is actually fixed

**Never skip the daemon restart** - It caught the 5-handler import bug!

---

**See Also**:
- @CLAUDE/CodeLifecycle/Features.md - Feature development lifecycle
- @CLAUDE/CodeLifecycle/General.md - General code changes
- @CLAUDE/AcceptanceTests/GENERATING.md - Acceptance test generation
