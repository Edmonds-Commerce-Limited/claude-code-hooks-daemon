# Plan 00027: Plan Completion Move Advisor Handler

**Status**: Not Started
**Created**: 2026-02-06
**Type**: Handler Implementation
**Event Type**: PreToolUse
**Priority**: 50 (workflow advisory range)
**Owner**: To be assigned

## Overview

When a plan's PLAN.md is edited to mark its status as "Complete", agents frequently forget to `git mv` the plan folder to `CLAUDE/Plan/Completed/` and update the `CLAUDE/Plan/README.md`. This happened most recently with Plan 00014, where the agent updated the status and tasks but initially forgot the folder move and README update.

This handler detects when a PLAN.md file inside `CLAUDE/Plan/` is being edited or written with completion markers, and fires an advisory reminder about the remaining housekeeping steps.

## Goals

- Detect when a plan is being marked as complete (status change in PLAN.md)
- Provide a clear, actionable advisory with the exact `git mv` command
- Remind about README.md updates and plan statistics
- Non-blocking (advisory only, `terminal=False`)
- Zero false positives on plans already in Completed/

## Non-Goals

- Automatically moving the plan folder (too invasive for an advisory handler)
- Blocking the edit (plans should always be editable)
- Detecting partial completion (only triggers on explicit status markers)
- Handling plans outside the `CLAUDE/Plan/` directory structure

## Context & Background

### The Problem

Plan completion has a multi-step checklist documented in `CLAUDE/Plan/CLAUDE.md`:

1. Update plan status to `Complete` with completion date
2. Move folder to `CLAUDE/Plan/Completed/` via `git mv`
3. Update `CLAUDE/Plan/README.md` (move from Active to Completed, update links, update statistics)
4. Close GitHub issue if applicable

Steps 2-4 are routinely forgotten because the agent considers the plan "done" after updating the status. This handler catches the status update (step 1) and reminds about the remaining steps.

### Real-World Example (Plan 00014)

Agent edited `CLAUDE/Plan/00014-eliminate-cwd-calculated-constants/PLAN.md` to change:
```
**Status**: In Progress
```
to:
```
**Status**: Complete (2026-02-06)
```

The handler should fire and advise:
```
Plan 00014 appears to be marked as complete. Remember to:
1. Move to Completed/: git mv CLAUDE/Plan/00014-eliminate-cwd-calculated-constants CLAUDE/Plan/Completed/
2. Update CLAUDE/Plan/README.md (move from Active to Completed section)
3. Update plan statistics in README.md
```

### Detection Patterns

The handler should detect these completion signals in file content:

**Primary (Status field change)**:
- `**Status**: Complete` (with optional date suffix)
- `**Status**: Completed`
- `**Status**:` followed by text containing "complete" (case-insensitive)

**Secondary (Edit tool - old_string/new_string changes)**:
- `old_string` contains a non-complete status and `new_string` contains "Complete"
- Changing `- [ ]` to `- [x]` for ALL tasks is NOT sufficient alone (could be partial progress)

**Exclusions (must NOT trigger)**:
- Files already in `CLAUDE/Plan/Completed/` (already moved)
- Files not matching `CLAUDE/Plan/NNNNN-*/PLAN.md` pattern
- Writing a new plan that happens to mention the word "complete" in its body
- Editing README.md (meta-file, not a plan)

## Tasks

### Phase 1: TDD - Unit Tests (Red)

- [ ] **Task 1.1**: Create test file `tests/unit/handlers/pre_tool_use/test_plan_completion_advisor.py`
  - [ ] Test handler initialization (name, priority=50, terminal=False, tags)
  - [ ] Test `matches()` positive: Write tool writing PLAN.md with `**Status**: Complete`
  - [ ] Test `matches()` positive: Edit tool changing status to Complete
  - [ ] Test `matches()` positive: Write tool with `**Status**: Complete (2026-02-06)` (with date)
  - [ ] Test `matches()` positive: Case variations (`complete`, `Completed`, `COMPLETE`)
  - [ ] Test `matches()` negative: File already in `Completed/` directory
  - [ ] Test `matches()` negative: Non-PLAN.md file in plan directory
  - [ ] Test `matches()` negative: PLAN.md with "complete" only in body text (not status field)
  - [ ] Test `matches()` negative: README.md edits
  - [ ] Test `matches()` negative: Non-Write/Edit tool
  - [ ] Test `handle()` returns ALLOW with advisory guidance
  - [ ] Test `handle()` includes correct `git mv` command with plan folder name
  - [ ] Test `handle()` mentions README.md update
  - [ ] Test `handle()` mentions plan statistics update

### Phase 2: Implementation (Green)

- [ ] **Task 2.1**: Add constants
  - [ ] Add `PLAN_COMPLETION_ADVISOR` to `HandlerID` enum in `constants/handlers.py`
  - [ ] Add `PLAN_COMPLETION_ADVISOR = 50` to `Priority` enum in `constants/priority.py`

- [ ] **Task 2.2**: Create handler file `src/claude_code_hooks_daemon/handlers/pre_tool_use/plan_completion_advisor.py`
  - [ ] Implement `__init__()` with correct handler_id, priority, terminal=False, tags
  - [ ] Implement `matches()` to detect completion markers in PLAN.md edits
  - [ ] Implement `handle()` to return advisory guidance with `git mv` command
  - [ ] Implement `get_acceptance_tests()` for programmatic acceptance testing

- [ ] **Task 2.3**: Register handler
  - [ ] Add to handler registry/`__init__.py` if needed
  - [ ] Add to `.claude/hooks-daemon.yaml` config

### Phase 3: Refactor and Verify

- [ ] **Task 3.1**: Refactor for clarity
  - [ ] Extract completion detection patterns to named constants
  - [ ] Ensure DRY with existing plan handlers

- [ ] **Task 3.2**: Run QA suite
  - [ ] `./scripts/qa/run_autofix.sh`
  - [ ] `./scripts/qa/run_all.sh` - ALL checks pass
  - [ ] Verify 95%+ coverage on new handler

### Phase 4: Integration

- [ ] **Task 4.1**: Daemon load verification
  - [ ] `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart`
  - [ ] `$PYTHON -m claude_code_hooks_daemon.daemon.cli status` shows RUNNING
  - [ ] No import errors in daemon logs

- [ ] **Task 4.2**: Integration tests
  - [ ] Add handler to `tests/integration/test_handler_instantiation.py` if applicable
  - [ ] Verify dogfooding tests pass: `pytest tests/integration/test_dogfooding*.py -v`

- [ ] **Task 4.3**: Live testing
  - [ ] Edit a PLAN.md to mark as complete - verify advisory fires
  - [ ] Edit a PLAN.md in Completed/ - verify advisory does NOT fire
  - [ ] Edit a non-plan .md file with "complete" - verify no false positive

## Handler Specification

```python
class PlanCompletionAdvisorHandler(Handler):
    """Advise when a plan is being marked as complete.

    Detects edits to CLAUDE/Plan/NNNNN-*/PLAN.md that change status
    to Complete, and reminds the agent to:
    1. git mv the plan folder to CLAUDE/Plan/Completed/
    2. Update CLAUDE/Plan/README.md
    3. Update plan statistics
    """

    def __init__(self) -> None:
        super().__init__(
            handler_id=HandlerID.PLAN_COMPLETION_ADVISOR,
            priority=Priority.PLAN_COMPLETION_ADVISOR,
            terminal=False,
            tags=[
                HandlerTag.WORKFLOW,
                HandlerTag.PLANNING,
                HandlerTag.ADVISORY,
                HandlerTag.NON_TERMINAL,
            ],
        )

    def matches(self, hook_input: dict[str, Any]) -> bool:
        """Check if editing PLAN.md with completion markers.

        Matches when:
        - Tool is Write or Edit
        - File path matches CLAUDE/Plan/NNNNN-*/PLAN.md (NOT in Completed/)
        - Content or edit contains status change to Complete/Completed
        """
        ...

    def handle(self, hook_input: dict[str, Any]) -> HookResult:
        """Return advisory guidance about plan completion steps."""
        ...
```

### Detection Logic Detail

**For Write tool** (`tool_name == "Write"`):
1. Check `file_path` matches `CLAUDE/Plan/<digits>-<name>/PLAN.md`
2. Check `file_path` does NOT contain `/Completed/`
3. Check `content` contains `**Status**:` followed by "complete" (case-insensitive)

**For Edit tool** (`tool_name == "Edit"`):
1. Check `file_path` matches `CLAUDE/Plan/<digits>-<name>/PLAN.md`
2. Check `file_path` does NOT contain `/Completed/`
3. Check `new_string` contains "Complete" in a status context
   - Pattern: `**Status**:` line with "complete" (case-insensitive)

### Advisory Message Format

```
Plan {number} appears to be marked as complete. Remember to:
1. Move to Completed/: git mv CLAUDE/Plan/{folder-name} CLAUDE/Plan/Completed/
2. Update CLAUDE/Plan/README.md (move from Active to Completed section, update link path)
3. Update plan statistics in README.md (increment Completed count, update total)
```

## Dependencies

- None (standalone handler)
- Related: Plan 003 (planning mode integration), Plan 00025 (acceptance tests)

## Technical Decisions

### Decision 1: Advisory vs Blocking
**Context**: Should this handler block the edit or just advise?
**Decision**: Advisory (ALLOW + guidance). Blocking would be too aggressive - the status change itself is correct and necessary. The handler just reminds about follow-up steps.

### Decision 2: Write + Edit vs Write Only
**Context**: Should we detect both Write and Edit tool calls?
**Decision**: Both. Agents may use Write to rewrite the entire PLAN.md, or Edit to change just the status line. Both patterns are common.

### Decision 3: Priority 50
**Context**: What priority should this handler have?
**Decision**: Priority 50 (workflow range). This is a workflow advisory, similar to `plan_workflow` (45) and `npm_command` (50). It should run after safety and code quality handlers but before low-priority advisories.

## Success Criteria

- [ ] Handler correctly detects status changes to "Complete" in active plan PLAN.md files
- [ ] Handler does NOT fire for plans already in Completed/
- [ ] Handler does NOT fire for non-PLAN.md files or non-plan directories
- [ ] Advisory message includes correct `git mv` command with actual folder name
- [ ] Advisory message mentions README.md update
- [ ] All tests passing with 95%+ coverage
- [ ] All QA checks pass
- [ ] Daemon restarts successfully with handler enabled
- [ ] Live testing confirms handler fires at the right time

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| False positives on "complete" in body text | Low | Medium | Only match `**Status**:` pattern, not arbitrary text |
| Missing Edit tool detection | Medium | Low | Test both Write and Edit tool paths |
| Handler not loading (import error) | High | Low | Daemon restart verification in Phase 4 |
| Conflict with plan_workflow handler | Low | Low | Different trigger conditions (creation vs completion) |

## Notes & Updates

### 2026-02-06
- Plan created based on real-world experience with Plan 00014 completion oversight
- Agent updated PLAN.md status but forgot `git mv` to Completed/ and README.md update
