# Plan 00084: Fix Inplace-Edit Blocker xargs/pipe Bypass

**Status**: In Progress
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

- [ ] Add test: `grep -rl 'X' | xargs sed -i` is NOT safe (should be blocked)
- [ ] Add test: `find -exec sed -i` is NOT safe
- [ ] Add test: `echo "test" | sed 's/foo/bar/'` is NOT safe
- [ ] Add test: plain `grep sed` (no pipe to execution) IS safe
- [ ] Run tests — must FAIL

### Phase 2: Implement Fix

- [ ] Fix `_is_safe_readonly_command()`: when grep is present, check if command also contains a pipe to actual execution
- [ ] Run tests — must PASS

### Phase 3: QA & Verification

- [ ] Run `./scripts/qa/llm_qa.py all`
- [ ] Restart daemon, verify RUNNING
- [ ] Commit

## Files to Modify

| File | Change |
|------|--------|
| `src/.../handlers/pre_tool_use/sed_blocker.py` | Fix `_is_safe_readonly_command()` |
| `tests/unit/handlers/pre_tool_use/test_sed_blocker.py` | Add bypass regression tests |
