# Plan 00071: Plan Number Validation Hook Bug Fixes

**Status**: Complete (2026-02-27)
**Created**: 2026-02-27
**Owner**: Claude
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Three bug reports related to plan hooks were triaged and fixed in this plan:

1. **bug-report.md** — Plan file race condition (infinite empty folders). Triaged as duplicate of Plan 00066.
2. **bug-report-archive-trigger.md** — Plan number validation hook fires incorrectly on `git mv` archive operations. **Fixed.**
3. **bug-report-toctou-race.md** — Plan number validation hook false-positive when `mkdir` creates directory before `Write` fires. **Fixed.**

Bugs 2 and 3 are closely related — both are false positives in the `ValidatePlanNumberHandler` caused by the handler not accounting for normal plan lifecycle operations (archiving, multi-step creation).

---

## Bug 1: Plan File Race Condition (Triage Only)

**Report**: `bug-report.md`
**Verdict**: DUPLICATE — Already fixed by Plan 00066 (2026-02-22)

No code changes required. The report describes a known bug where `handle_planning_mode_write()` returned `Decision.ALLOW` after writing a redirect stub, causing infinite retries. Fixed by changing to `Decision.DENY` in commit `d1b75d3`.

The report likely originated from a different project using an older version of the hooks daemon.

---

## Bug 2: Archive Operations Triggering False Positives

**Report**: `bug-report-archive-trigger.md`
**Verdict**: REAL BUG — Fixed

### Root Cause

The `ValidatePlanNumberHandler` regex `mkdir.*?CLAUDE/Plan/(\d{3})-` used `.*?` which spanned across `&&` command boundaries. When running:

```bash
mkdir -p CLAUDE/Plan/Completed && git mv CLAUDE/Plan/023-old CLAUDE/Plan/Completed/023-old
```

The `.*?` matched from `mkdir` across `&&` into the `git mv` target path, treating the archive destination as a new plan creation.

### Fix (commit `9c0f46f`)

1. Changed regex to `mkdir[^&;]*CLAUDE/Plans?/(\d{3})-` — `[^&;]*` prevents spanning across `&&` or `;` command boundaries
2. `matches()` regex only matches direct children of `Plan/` root (`CLAUDE/Plan/NNN-name/`), not plans inside organizational subfolders (`CLAUDE/Plan/Completed/NNN-name/`)
3. Added `Plans?` support for both `Plan` and `Plans` folder names
4. Updated `_get_highest_plan_number()` to scan ALL non-numbered organizational subfolders (Completed/, Archive/, Backlog/, etc.), not just hardcoded `Completed/`

### Tests Added (7 new tests)

- `test_does_not_match_git_mv_to_completed` — original bug scenario
- `test_does_not_match_git_mv_to_any_subfolder` — generalized (Archive)
- `test_does_not_match_write_to_completed_folder` — Write to Completed/
- `test_does_not_match_write_to_any_organizational_subfolder` — loops over Archive, Backlog, OnHold, v1
- `test_does_not_match_mkdir_completed_folder` — mkdir in Completed/
- `test_does_not_match_mkdir_any_organizational_subfolder` — mkdir in Archive/
- `test_get_highest_plan_number_scans_all_organizational_subfolders` — scans Archive/, Backlog/

---

## Bug 3: TOCTOU Race — mkdir Before Write

**Report**: `bug-report-toctou-race.md`
**Verdict**: REAL BUG — Fixed

### Root Cause

When creating a plan, two tool calls happen in sequence:
1. `mkdir -p CLAUDE/Plan/024-name/` — creates directory (PreToolUse validates, passes)
2. `Write CLAUDE/Plan/024-name/PLAN.md` — creates file (PreToolUse validates again)

On step 2, `_get_highest_plan_number()` scans the filesystem and finds directory `024` (created in step 1). It calculates `expected = 024 + 1 = 025`, but the Write is for plan `024`. The handler incorrectly rejects it as "PLAN NUMBER INCORRECT".

### Fix

Changed the validation condition from:

```python
if plan_number != expected_number:  # only allows highest + 1
```

To:

```python
if plan_number != expected_number and plan_number != highest:
```

This allows both:
- `plan_number == highest + 1` — normal case (dir not yet created)
- `plan_number == highest` — TOCTOU case (mkdir already created the dir)

### Tests Added (4 new tests)

- `test_handle_write_allows_when_dir_already_created_by_mkdir` — exact bug scenario
- `test_handle_write_allows_when_dir_is_highest_from_completed` — TOCTOU with Completed/
- `test_handle_write_still_rejects_genuinely_wrong_number` — ensures wrong numbers still rejected
- `test_handle_write_still_rejects_low_number_with_existing_dir` — ensures low numbers still rejected

---

## Action Items

- [x] Triage bug-report.md (duplicate of Plan 00066)
- [x] Move all reports from `untracked/` to plan folder
- [x] Fix archive trigger false positive (Bug 2) with TDD
- [x] Fix TOCTOU race condition (Bug 3) with TDD
- [x] QA 8/8 passed after each fix
- [x] Daemon loads successfully after each fix
- [x] All 57 handler tests pass

## Success Criteria

- [x] All three reports triaged and documented
- [x] Bug 2 fixed: `git mv` to any organizational subfolder no longer triggers
- [x] Bug 3 fixed: Write after mkdir no longer false-positives
- [x] No regressions: genuinely wrong plan numbers still rejected
- [x] QA 8/8 passed, daemon running, 57 handler tests pass
