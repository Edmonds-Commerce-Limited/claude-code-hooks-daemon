# Plan 00066: Fix Plan File Race Condition (ALLOW → DENY)

**Status**: Not Started
**Created**: 2026-02-22
**Owner**: TBD
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

The `markdown_organization` handler intercepts planning mode writes to `~/.claude/plans/*.md`
and redirects them to `CLAUDE/Plan/{number}-{name}/PLAN.md`. However, it currently returns
`Decision.ALLOW` after already performing the write, which causes Claude's Write tool to
detect the file was modified between its read and write operations — a classic TOCTOU race.
The fix is a one-line change: return `Decision.DENY` instead of `Decision.ALLOW`.

**Reference**: `CLAUDE/Plan/00066-plan-file-race-condition/bug-report.md`

## Root Cause

In `handle_planning_mode_write()` (`markdown_organization.py:238`), the handler does:

1. Calls `get_next_plan_number()` → e.g. `00026`
2. Creates `CLAUDE/Plan/00026-{name}/PLAN.md` with the plan content
3. Writes a redirect stub to the **original** `~/.claude/plans/{name}.md`
4. Returns `Decision.ALLOW`

When `ALLOW` is returned, Claude Code's Write tool proceeds to execute. But the tool checks
whether the file has been modified since Claude last read it — and it **has** been (step 3
wrote a stub). The write fails with:

> "File has been unexpectedly modified. Read it again before attempting to write it."

Claude then reads the file (seeing stub for `00026`), tries to write again, the handler
fires again calling `get_next_plan_number()` → `00027` (since `00026` dir now exists),
writes a **new** stub, returns `ALLOW`, tool fails again — **infinite loop**.

A secondary correctness bug: if `ALLOW` returned and the Write tool somehow succeeded,
it would **overwrite the redirect stub** with the raw plan content, defeating the redirect.

## The Fix

**Change `Decision.ALLOW` → `Decision.DENY` in `handle_planning_mode_write()`.**

When DENY is returned, Claude's Write tool is blocked entirely. The handler has already:
- Saved the content to the correct location
- Written the redirect stub

Nothing is left for the Write tool to do. DENY is the semantically correct signal: "I've
already handled this, do not proceed."

The deny `reason` message must clearly communicate **success** (not failure) so Claude
doesn't retry.

## Tasks

### Phase 1: TDD — Write Failing Tests
- [ ] Add test to `test_markdown_organization.py`: planning mode write returns `Decision.DENY`
- [ ] Add test: deny reason contains "PLAN SAVED" or "saved" keyword
- [ ] Add test: deny reason contains the correct folder path
- [ ] Verify tests FAIL before fix (RED)

### Phase 2: Implement Fix
- [ ] Change `handle_planning_mode_write()` return from `Decision.ALLOW` to `Decision.DENY`
- [ ] Change `context=context_parts` → `reason="".join(reason_parts)`
- [ ] Update reason message to clearly say content was saved (not blocked)
- [ ] Verify new tests PASS (GREEN)
- [ ] Update any existing tests that assert `Decision.ALLOW`

### Phase 3: QA & Verification
- [ ] Run `./scripts/qa/llm_qa.py all` — all 8 checks pass
- [ ] Daemon restart: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart` → RUNNING
- [ ] Enter plan mode in Claude Code to verify the fix works in practice
- [ ] Commit: `Fix: plan file race condition — return DENY after redirect to prevent TOCTOU`

## Code Change

**File**: `src/claude_code_hooks_daemon/handlers/pre_tool_use/markdown_organization.py`

**Before** (lines ~306-327):
```python
context_parts = [
    f"Planning mode write successfully redirected.\n\n"
    f"Your plan has been saved to: `{self._track_plans_in_project}/{folder_name}/PLAN.md`\n\n"
    f"A redirect stub was created at: `{file_path}`\n\n"
    f"**ACTION REQUIRED**: The plan folder has a temporary name.\n"
    f"Please rename `{folder_name}/` to `{next_number}-descriptive-name/` "
    f"based on the plan content. Keep the number prefix intact."
]
if self._plan_workflow_docs:
    workflow_path = self._workspace_root / self._plan_workflow_docs
    if workflow_path.exists():
        context_parts.append(
            f"\n\n**Workflow Documentation**: See `{self._plan_workflow_docs}` "
            f"for plan structure and conventions."
        )
return HookResult(
    decision=Decision.ALLOW,
    context=context_parts,
)
```

**After**:
```python
reason_parts = [
    f"PLAN SAVED SUCCESSFULLY\n\n"
    f"Your plan content has been automatically redirected to project version control.\n\n"
    f"Saved to: `{self._track_plans_in_project}/{folder_name}/PLAN.md`\n\n"
    f"A redirect stub was written to: `{file_path}`\n\n"
    f"Do NOT retry this write — the content is already saved.\n\n"
    f"**IMPORTANT**: The plan folder currently has a temporary name: `{folder_name}`\n\n"
    f"**You MUST rename this folder** to a descriptive name based on the plan content:\n"
    f"1. Read the plan to understand what it's about\n"
    f"2. Choose a clear, descriptive kebab-case name\n"
    f"3. Rename: `{self._track_plans_in_project}/{folder_name}/` → "
    f"`{self._track_plans_in_project}/{next_number}-descriptive-name/`\n"
    f"4. Keep the plan number prefix ({next_number}-) intact\n"
]
if self._plan_workflow_docs:
    workflow_path = self._workspace_root / self._plan_workflow_docs
    if workflow_path.exists():
        reason_parts.append(
            f"\nIf this plan is relevant to the current work and not already complete, "
            f"continue working on it.\n"
        )
return HookResult(
    decision=Decision.DENY,
    reason="".join(reason_parts),
)
```

## Affected Tests

Tests in `tests/unit/handlers/pre_tool_use/test_markdown_organization.py` that currently
assert `Decision.ALLOW` for planning mode writes must be updated to `Decision.DENY`.
Search for: `Decision.ALLOW` in the planning mode test section.

## Success Criteria

- [ ] Planning mode writes no longer loop — first write attempt completes cleanly
- [ ] Plan content is saved to `CLAUDE/Plan/{number}-{name}/PLAN.md`
- [ ] Redirect stub written to original path (unchanged behaviour)
- [ ] Deny reason clearly communicates plan was saved (not blocked/failed)
- [ ] All existing tests pass (updated for DENY)
- [ ] QA: all 8 checks pass
- [ ] Daemon restarts successfully
- [ ] Live test: plan mode write in Claude Code completes in one attempt

## Non-Goals

- Does not change `get_next_plan_number()` logic
- Does not change stub content format
- Does not change `plan_number_helper` handler
- Does not address the minor inconsistency in bug report about "decreasing" plan numbers
  (this is a separate issue from the race condition and resolves itself once DENY is returned)

## Notes

The decreasing plan numbers in the bug report (`00026 → 00024 → 00025`) are explained by
other existing plan directories being counted by `get_next_plan_number()`. Each failed
attempt creates a new directory, so the counter increments differently each time. Once the
DENY fix is applied, the handler runs exactly once per plan write — no accumulation of
ghost directories.
