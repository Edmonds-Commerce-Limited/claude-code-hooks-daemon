# Feature Development Lifecycle

**Status**: MANDATORY for all new features and handlers
**Audience**: AI agents and human developers

## Overview

Complete lifecycle from idea to production-ready feature with rigorous testing at every layer.

## The Testing Pyramid

```
                    /\
                   /  \  Acceptance Tests
                  /    \  (Generated from code - Ephemeral, Pre-Release)
                 /------\
                /        \  Integration Tests
               /          \  (FrontController, EventRouter, Dogfooding)
              /------------\
             /              \  Unit Tests
            /                \  (TDD - Red/Green/Refactor - 95% coverage)
           /------------------\

          EVERY LAYER IS MANDATORY
```

## Phase 1: Planning

1. Create plan in `CLAUDE/Plan/NNNNN-description/PLAN.md`
2. Define success criteria
3. Identify test scenarios (what needs to be blocked/allowed/advised)
4. Get user approval (if applicable)

**See**: @CLAUDE/PlanWorkflow.md for planning standards

## Phase 2: TDD Implementation (Red/Green/Refactor)

### RED Phase: Write Failing Tests

```bash
# Create test file FIRST
tests/unit/handlers/{event_type}/test_{handler}.py
```

Write comprehensive tests:
- Initialization tests (name, priority, terminal flag)
- `matches()` positive cases (should trigger)
- `matches()` negative cases (should not trigger)
- `handle()` decision and reason tests
- Edge cases and error conditions

**Run tests - they MUST FAIL**:
```bash
pytest tests/unit/handlers/{event_type}/test_{handler}.py -v
# Expected: FAILURES (no handler implementation yet)
```

### GREEN Phase: Implement Handler

```bash
# Now create handler
src/claude_code_hooks_daemon/handlers/{event_type}/{handler}.py
```

Implement minimum code to pass tests:
- Use constants (HandlerID, Priority, Decision enums)
- Follow existing handler patterns
- Import from correct modules (core.Decision, not constants.decision!)

**Run tests - they MUST PASS**:
```bash
pytest tests/unit/handlers/{event_type}/test_{handler}.py -v
# Expected: ALL PASS
```

### REFACTOR Phase: Clean Up

- Remove duplication
- Improve clarity
- Maintain test passing

**Verify coverage**:
```bash
pytest tests/unit/handlers/{event_type}/test_{handler}.py --cov=src/claude_code_hooks_daemon/handlers/{event_type}/{handler}.py --cov-report=term-missing
# Expected: 95%+ coverage
```

## Phase 3: Integration Testing

Integration tests verify handler works with daemon components.

### Required Integration Tests

1. **Response Validation** (MANDATORY):
   Add test case to `tests/integration/test_all_handlers_response_validation.py`
   ```python
   def test_{handler}_returns_valid_response():
       """Verify {handler} returns valid HookResult."""
       # Test handler integrates with response validation
   ```

2. **FrontController Integration** (if complex):
   Create `tests/integration/test_{handler}_integration.py` if handler has:
   - Complex dispatch logic
   - Dependencies on other handlers
   - State management

**Run integration tests**:
```bash
pytest tests/integration/ -v -k {handler}
# Expected: ALL PASS
```

## Phase 4: Daemon Load Verification (CRITICAL - MANDATORY)

**THIS IS WHERE THE 5-HANDLER FAILURE WOULD HAVE BEEN CAUGHT**

### Why This Matters

Unit tests use mocks and don't import handlers through the daemon registry.
**Daemon load test catches**:
- Import errors (wrong module paths)
- Missing dependencies
- Circular imports
- Registration failures

### How to Verify

```bash
# Step 1: Register handler in config
# Edit .claude/hooks-daemon.yaml and add handler entry

# Step 2: Restart daemon
$PYTHON -m claude_code_hooks_daemon.daemon.cli restart

# Step 3: Verify daemon is RUNNING
$PYTHON -m claude_code_hooks_daemon.daemon.cli status

# Expected output:
# Daemon: RUNNING
# PID: [number]
# Socket: [path] (exists)

# Step 4: Check logs for errors
$PYTHON -m claude_code_hooks_daemon.daemon.cli logs | grep -i error

# Expected: No import errors, no loading failures
```

**If daemon fails to start**:
1. Check daemon logs for error details
2. Fix import/registration issues
3. Re-run daemon restart
4. **DO NOT PROCEED until daemon starts successfully**

## Phase 5: Dogfooding

Handler must be enabled in project's own config to dogfood it.

### Dogfooding Tests (Automatic)

```bash
# These tests auto-discover all handlers and verify config
pytest tests/integration/test_dogfooding_config.py -v
pytest tests/integration/test_dogfooding_hook_scripts.py -v

# Expected: ALL PASS (handler in config, scripts match)
```

**If dogfooding tests fail**:
- Ensure handler is enabled in `.claude/hooks-daemon.yaml`
- Ensure priority is set correctly
- Ensure event type section exists

## Phase 6: Full QA Suite

Run ALL quality checks before committing:

```bash
./scripts/qa/run_all.sh
```

**Expected output**:
```
========================================
QA Summary
========================================
  Magic Values        : ✅ PASSED
  Format Check        : ✅ PASSED
  Linter              : ✅ PASSED
  Type Check          : ✅ PASSED
  Tests               : ✅ PASSED
  Security Check      : ✅ PASSED

Overall Status: ✅ ALL CHECKS PASSED
```

**If ANY check fails**: Fix issues and re-run full suite.

## Phase 7: Acceptance Testing (Pre-Release)

Before releasing, add acceptance tests to your handler via the `get_acceptance_tests()` method.

### Add Programmatic Acceptance Tests

Override `get_acceptance_tests()` in your handler to return test definitions:

```python
def get_acceptance_tests(self) -> list[AcceptanceTest]:
    return [
        AcceptanceTest(
            test_id="positive-case",
            description="Blocks dangerous command",
            hook_input={...},
            expected_decision="deny",
        ),
        AcceptanceTest(
            test_id="negative-case",
            description="Allows safe command",
            hook_input={...},
            expected_decision="allow",
        ),
    ]
```

### Generate and Execute Playbook

```bash
# Generate fresh playbook from code
$PYTHON -m claude_code_hooks_daemon.daemon.cli generate-playbook > /tmp/playbook.md
```

Execute tests in a real Claude Code session. See `CLAUDE/AcceptanceTests/GENERATING.md` for details.

**If ANY test fails**: Return to Phase 2 (fix bug with TDD)

**FAIL-FAST Cycle**:
```
Test fails → Fix with TDD → Full QA → Daemon restart → RESTART ALL TESTS FROM BEGINNING
```

## Phase 8: Live Testing

Test in real Claude Code session:

1. Trigger handler with real commands
2. Verify blocking/advisory behavior
3. Check for false positives
4. Check for false negatives
5. Document any edge cases found

## Definition of Done Checklist

A feature is DONE when ALL of the following are verified:

### 1. Unit Tests (TDD)
- [ ] Failing tests written BEFORE implementation
- [ ] Implementation makes tests pass
- [ ] 95%+ coverage maintained
- [ ] All edge cases covered
- [ ] Run: `pytest tests/unit/ -v`

### 2. Integration Tests
- [ ] Handler integrates with FrontController
- [ ] Handler integrates with EventRouter
- [ ] Response validation passes (valid JSON for event type)
- [ ] Config integration works
- [ ] Run: `pytest tests/integration/ -v`

### 3. Daemon Load Test (CRITICAL)
- [ ] Daemon restarts successfully with new code
- [ ] No import errors in daemon logs
- [ ] Handler appears in loaded handlers list
- [ ] Run: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
- [ ] Verify: `$PYTHON -m claude_code_hooks_daemon.daemon.cli status`

### 4. Dogfooding Tests
- [ ] `test_dogfooding_config.py` passes (handler in config)
- [ ] `test_dogfooding_hook_scripts.py` passes (scripts match)
- [ ] Run: `pytest tests/integration/test_dogfooding*.py -v`

### 5. Full QA Suite
- [ ] All 6 checks pass with ZERO failures
- [ ] Run: `./scripts/qa/run_all.sh`
- [ ] Expected output: "ALL CHECKS PASSED"

### 6. Acceptance Tests (Before Release)
- [ ] Handler implements `get_acceptance_tests()` with test definitions
- [ ] Generated playbook includes handler tests (`generate-playbook`)
- [ ] All relevant handler tests pass in real Claude Code session
- [ ] Results documented
- [ ] See: `CLAUDE/AcceptanceTests/GENERATING.md`

### 7. Live Testing
- [ ] Handler tested in real Claude Code session
- [ ] Expected behavior verified (blocks/allows correctly)
- [ ] No false positives or negatives observed

## Common Pitfalls

### ❌ What Went Wrong (5-Handler Example)

**Mistake**: Ran unit tests, saw 100% coverage, assumed done.

**What was missed**:
- ❌ No daemon restart after each commit
- ❌ Wrong import path (`constants.decision` instead of `core.Decision`)
- ❌ Daemon couldn't load any of the 5 handlers
- ❌ All protection was down

**How to avoid**:
- ✅ **ALWAYS restart daemon after code changes**
- ✅ Verify daemon status shows RUNNING
- ✅ Check daemon logs for import errors
- ✅ Run integration tests (not just unit tests)

### ❌ Other Common Mistakes

1. **Skipping integration tests** - "Unit tests pass, ship it!"
2. **Not testing in real daemon** - Mocks hide import errors
3. **No acceptance testing** - Works in tests, fails in reality
4. **No dogfooding** - Handler not enabled in project's own config

## Summary

**Remember**: Unit tests alone are NOT enough!

Complete testing pyramid:
1. Unit tests (isolated, TDD)
2. Integration tests (component interactions)
3. **Daemon load** (catches import errors) ← **CRITICAL**
4. Dogfooding (config completeness)
5. Full QA (comprehensive checks)
6. Acceptance tests (real-world scenarios)
7. Live testing (actual usage)

**NEVER skip the daemon restart check** - it catches issues that unit tests miss!

---

**See Also**:
- @CLAUDE/CodeLifecycle/Bugs.md - Bug fix lifecycle
- @CLAUDE/CodeLifecycle/General.md - General code changes
- @CLAUDE/AcceptanceTests/GENERATING.md - Acceptance test generation
- @CLAUDE/PlanWorkflow.md - Planning standards
