# Feature Development Lifecycle

**Status**: MANDATORY for all new features and handlers
**Audience**: AI agents and human developers

> **Run every command below from the PROJECT ROOT.** Paths like
> `./bin/hooks-daemon` and `./scripts/qa/...` are relative to it, and resolve to
> nothing from anywhere else (`exit 127`).

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

**See**: [CLAUDE/PlanWorkflow.md](../PlanWorkflow.md) for planning standards

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

1. **Response Validation** (AUTOMATIC — nothing to add):

   `tests/integration/test_every_handler_response_validates.py` DERIVES its
   population from the handler package, so a new handler is covered on the
   commit that adds it. It reads the decisions your handler can return from its
   own AST and asserts each one serialises to a response its event's schema
   accepts. You do not register anything.

   If it fails, your handler returns a decision its event type cannot express —
   for example a DENY on `SessionStart`, `SessionEnd`, `PreCompact`,
   `Notification` or either worktree event, none of which can refuse anything.
   Fix the handler; do not exempt it.

   `to_json` enforces the same contract at runtime, so an invalid response never
   reaches Claude Code. It substitutes a valid one that is never weaker than what
   you asked for, and logs the violation at ERROR. A silent downgrade is
   therefore impossible — but a downgrade still happens, so a test failure here
   is real.

   `tests/integration/test_all_handlers_response_validation.py` is the older
   hand-written suite. It is a per-handler file covering a fraction of the
   handlers, kept for its richer per-scenario `hook_input` cases. Adding a case
   there is welcome and optional; the derived guard above is what guarantees
   coverage.

   **Project handlers are the one population this sweep cannot reach** — they
   live in a client's own repository. They get the same check from
   `bin/hooks-daemon validate-project-handlers`, which shares the underlying
   primitive (`core/decision_capability.py`) so the two cannot drift. See
   [CLAUDE/PROJECT_HANDLERS.md](../PROJECT_HANDLERS.md).

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
./bin/hooks-daemon restart

# Step 3: Verify daemon is RUNNING
./bin/hooks-daemon status

# Expected output:
# Daemon: RUNNING
# PID: [number]
# Socket: [path] (exists)

# Step 4: Check logs for errors
./bin/hooks-daemon logs | grep -i error

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
./scripts/qa/llm_qa.py all
```

**Expected output**: one `✅` line per check, then a summary line whose two
numbers are equal — e.g. `QA: 18/18 PASSED`.

The runner is the single source of truth for WHICH checks exist and how many.
Do not reproduce the list here: an earlier version of this section hardcoded six
checks and went stale as the suite grew, so a reader could see a full pass and
still believe checks were missing.

**If ANY check fails**: Fix issues and re-run full suite.

## Phase 7: Acceptance Testing (Pre-Release)

Before releasing, add acceptance tests to your handler via the `get_acceptance_tests()` method.

### Add Programmatic Acceptance Tests

Override `get_acceptance_tests()` in your handler to return test definitions:

Five fields are REQUIRED — `title`, `command`, `description`,
`expected_decision`, `expected_message_patterns`. There is no `test_id` and no
`hook_input`: the payload a tester (or a harness) sends is derived from
`command`, so make `command` a literal shell command wherever the test can be
expressed as one. Reserve English prose ("Use the Write tool to ...") for tests
that genuinely cannot be, because prose is not machine-executable.

```python
def get_acceptance_tests(self) -> list[Any]:
    from claude_code_hooks_daemon.core import AcceptanceTest, TestType

    return [
        AcceptanceTest(
            title="sudo pip install",
            command='echo "sudo pip install requests"',
            description="Blocks sudo pip install (system-wide corruption risk)",
            expected_decision=Decision.DENY,
            expected_message_patterns=[
                r"sudo pip install",
                r"virtual environment",
            ],
            safety_notes="Uses echo - safe to test",
            test_type=TestType.BLOCKING,
        ),
    ]
```

### Generate and Execute Playbook

```bash
# Generate fresh playbook from code
./bin/hooks-daemon generate-playbook > /tmp/playbook.md
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
2. Verify blocking/advisory behaviour
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
- [ ] Run: `./bin/hooks-daemon restart`
- [ ] Verify: `./bin/hooks-daemon status`

### 4. Dogfooding Tests

- [ ] `test_dogfooding_config.py` passes (handler in config)
- [ ] `test_dogfooding_hook_scripts.py` passes (scripts match)
- [ ] Run: `pytest tests/integration/test_dogfooding*.py -v`

### 5. Full QA Suite

- [ ] EVERY check the runner runs passes, with ZERO failures
- [ ] Run: `./scripts/qa/llm_qa.py all` (the same suite as `run_all.sh`, LLM-optimised)
- [ ] Expected output: "ALL CHECKS PASSED" / an `N/N PASSED` line

### 5b. Client-Mode Verification (if paths/interpreters/wrappers/assets changed)

Self-install mode is NOT representative of a real client install.

- [ ] Rebuild the fixture: `scripts/dummy-client-repo.sh create`
- [ ] Verify the new behaviour in client mode (`dummy-client-repo.sh cli …`)
- [ ] Confirm the dogfood daemon still reports RUNNING
- [ ] See: [CLAUDE/development/CLIENT-MODE-TESTING.md](../development/CLIENT-MODE-TESTING.md)

### 6. Acceptance Tests (Before Release)

- [ ] Handler implements `get_acceptance_tests()` with test definitions
- [ ] Generated playbook includes handler tests (`generate-playbook`)
- [ ] All relevant handler tests pass in real Claude Code session
- [ ] Results documented
- [ ] See: `CLAUDE/AcceptanceTests/GENERATING.md`

### 7. Live Testing

- [ ] Handler tested in real Claude Code session
- [ ] Expected behaviour verified (blocks/allows correctly)
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

- [CLAUDE/CodeLifecycle/Bugs.md](Bugs.md) - Bug fix lifecycle
- [CLAUDE/CodeLifecycle/General.md](General.md) - General code changes
- [CLAUDE/AcceptanceTests/GENERATING.md](../AcceptanceTests/GENERATING.md) - Acceptance test generation
- [CLAUDE/PlanWorkflow.md](../PlanWorkflow.md) - Planning standards
