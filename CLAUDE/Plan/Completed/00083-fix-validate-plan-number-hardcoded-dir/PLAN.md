# Plan 00083: Fix validate_plan_number Hardcoded Plan Directory

**Status**: Complete (2026-03-09)
**Type**: Bug Fix
**Severity**: High
**Recommended Executor**: Sonnet

## Context

The `validate_plan_number` handler hardcodes `"CLAUDE/Plan"` for its directory scan (line 188), ignoring the `track_plans_in_project` config option. Projects configuring `CLAUDE/Plans` (plural) or any other custom path get incorrect plan number validation — the handler scans a non-existent directory, returns 0, and warns every plan operation should use number `00001`.

The sibling handler `plan_number_helper` works correctly because it uses `shares_options_with="markdown_organization"` to inherit the configured path. This fix applies the same pattern.

Bug report: `untracked/hooks-daemon-plans-plural-dir-problems.md`

## Tasks

### Phase 1: TDD - Write Failing Tests

- [x] Add test: handler has `shares_options_with` set to `"markdown_organization"`
- [x] Add test: `_get_highest_plan_number()` uses `_track_plans_in_project` when set (custom dir like `CLAUDE/Plans`)
- [x] Add test: `_get_highest_plan_number()` falls back to `ProjectPath.PLAN_DIR` when `_track_plans_in_project` is None
- [x] Add test: error messages use configured plan directory (not hardcoded `CLAUDE/Plan`)
- [x] Run tests — must FAIL

### Phase 2: Implement Fix

- [x] Add `shares_options_with="markdown_organization"` to `__init__`
- [x] Add `self._track_plans_in_project: str | None = None` attribute
- [x] Update `_get_highest_plan_number()` line 188: use `self._track_plans_in_project or ProjectPath.PLAN_DIR`
- [x] Update error messages (lines 144-173) to use dynamic `plan_dir` variable instead of hardcoded `CLAUDE/Plan`
- [x] Run tests — must PASS

### Phase 3: QA & Verification

- [x] Run `./scripts/qa/run_all.sh`
- [x] Restart daemon, verify RUNNING
- [x] Commit

## Files to Modify

| File                                                                         | Change                                   |
| ---------------------------------------------------------------------------- | ---------------------------------------- |
| `src/claude_code_hooks_daemon/handlers/pre_tool_use/validate_plan_number.py` | Add config inheritance, use dynamic path |
| `tests/unit/handlers/pre_tool_use/test_validate_plan_number.py`              | Add tests for config-aware behaviour     |

## Reference: Correct Pattern (from plan_number_helper.py)

```python
# __init__:
shares_options_with="markdown_organization",
self._track_plans_in_project: str | None = None

# usage:
plan_dir = self._track_plans_in_project or ProjectPath.PLAN_DIR
plan_root = self.workspace_root / plan_dir
```

## Verification

1. Tests pass: `pytest tests/unit/handlers/pre_tool_use/test_validate_plan_number.py -v`
2. QA passes: `./scripts/qa/run_all.sh`
3. Daemon restarts: `$PYTHON -m claude_code_hooks_daemon.daemon.cli restart && $PYTHON -m claude_code_hooks_daemon.daemon.cli status`
