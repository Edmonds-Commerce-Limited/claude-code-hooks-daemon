# Plan 00084: Fix Inplace-Edit Blocker xargs/pipe Bypass

**Status**: Complete (2026-03-09)
**Type**: Bug Fix
**Severity**: Medium
**Recommended Executor**: Sonnet

## Context

The `_is_safe_readonly_command()` method in the inplace-edit blocker handler returns `True` (safe) when `grep` appears anywhere in the command, even when grep pipes into `xargs sed -i`. This means `grep -rl 'pattern' | xargs sed -i 's/old/new/g'` bypasses the blocker entirely.

Bug report: `CLAUDE/Plan/00084-fix-inplace-edit-blocker-xargs-bypass/bug-report.md`

## Root Cause

In `_is_safe_readonly_command()` line 204:

```python
if re.search(r"(^|\s|[;&|])\s*grep\s+", command):
    return True  # ← Returns safe without checking rest of pipeline
```

When the command is `grep -rl 'X' | xargs sed -i 's/X/Y/g'`:

1. `matches()` finds `\bsed\b` in the command → proceeds
2. Not git/gh command → proceeds
3. `_is_safe_readonly_command()` finds `grep` → returns True (safe!)
4. `matches()` returns `not True` = False → blocker doesn't fire

## Tasks

### Phase 1: TDD - Write Failing Tests

- [x] Add test: `grep -rl 'X' | xargs sed -i` is NOT safe (should be blocked)
- [x] Add test: `find | xargs sed -i` is NOT safe
- [x] Add test: `grep | sed` read-only pipeline IS safe
- [x] Add test: plain `grep sed` (no pipe to execution) IS safe
- [x] Run tests — must FAIL

### Phase 2: Implement Fix

- [x] Fix `_is_safe_readonly_command()`: when grep is present, check for xargs sed in pipeline
- [x] Clarify handler docstring: intent is blocking destructive file modification, not read-only pipelines
- [x] Run tests — must PASS

### Phase 3: QA & Verification

- [x] Run `./scripts/qa/llm_qa.py all`
- [x] Restart daemon, verify RUNNING
- [x] Commit

## Files to Modify

| File                                                   | Change                            |
| ------------------------------------------------------ | --------------------------------- |
| `src/.../handlers/pre_tool_use/sed_blocker.py`         | Fix `_is_safe_readonly_command()` |
| `tests/unit/handlers/pre_tool_use/test_sed_blocker.py` | Add bypass regression tests       |
