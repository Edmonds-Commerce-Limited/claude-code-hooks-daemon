# Code Review: Plan 00540 re-review of commit f2220c282 (vs a78d84bb8)

## Summary

The integrity warning now promises "a daemon upgrade repoints it" only when the migration would actually repoint the line. Both the warning and the migration call one predicate, `upgrade_repoints_script` in `utils/ccy_supervisor.py`. No regression and no blocking defect was found. There are two non-blocking findings.

Reviewed: 4 files, +84/-21. Issues: 0 critical, 0 important, 2 suggestions (non-blocking).

Verdict: **APPROVED**

## Checks

### (1) Shared predicate with equivalent inputs: verified
- Migration (`install/ccy_supervisor.py` `_migrate_wrapper_to_launcher`): `upgrade_repoints_script(line, target_ccy_dir)`, where `target_ccy_dir = project_root/.claude/ccy`.
- Warning (`utils/ccy_supervisor.py` `bare_script_upgrade_repoints`): `upgrade_repoints_script(line, ccy_env.parent)`, where `env_path = ccy_dir/ccy.env` and `ccy_dir = project_root/.claude/ccy`. So the deployed directory resolves the same way in both.
- Line selection is the same in both:
  - Both skip `#` comment lines.
  - Both require `CCY_CLAUDE_WRAPPER`.
  - Both filter on the same `file_name_token("claude-supervise.py")`. The warning's extra `"claude-supervise" in stripped` test is implied by that filter.
  - The warning works on stripped lines and the migration on raw lines. This makes no difference, because the prefix regex anchors on `=`/quote/whitespace.
- Probe `untracked/scratch/rr126/probe.py` ran 8 wrapper values. Each value was tested in a plain form and in a form with leading whitespace and CRLF. For all 16 cases, the migration's real repoint outcome equals `bare_script_upgrade_repoints`.

### (2) No migration regression: verified
- I walked through the control flow:
  - A script line outside the deployed dir still goes to `other_directory`, including when it has flags or a variable prefix.
  - A deployed script line behind flags or a variable goes to `unrewritable_prefix`.
  - Launcher lines are unchanged. The `elif has_unrewritable_prefix` produces the same result as the old standalone `if`.
- Probe `untracked/scratch/rr126/regress.py` ran 14 script and launcher values, each with a commented twin, under the a78d84bb8 src and the f2220c282 src. Output is byte-IDENTICAL: same content and the same other_directory, unrewritable_prefix and pinned lists.

### (3) Tests are real: verified
- I applied the new `test_ccy_supervisor_integrity.py` to the a78d84bb8 tree. All 3 leave-alone parametrizations FAIL on the old code. The repoint case passes on both old and new code, which is right because it is a regression guard.
- On the worktree, the 3 touched files give 182 passed.

## Suggestions (non-blocking)

### S1. Stale docstring now contradicts the behaviour (Confidence: 85%)
**Location:** `src/claude_code_hooks_daemon/utils/ccy_supervisor.py`, `wrapper_execs_bare_script` docstring

**Problem:** The docstring still says "A daemon upgrade repoints the line." unconditionally. That unconditional claim is the one this commit removes from the warning text.

**Fix:** Change it to "A daemon upgrade repoints it only when `upgrade_repoints_script` holds; otherwise it must be fixed by hand."

### S2. Mixed multi-line case is untested and its message is imprecise (Confidence: 70%)
**Location:** `utils/ccy_supervisor.py` `bare_script_upgrade_repoints`, and the handler's warning at `ccy_supervisor_integrity.py:258-272`

**Problem:** Take two active bare-script lines, one the upgrade can repoint and one it cannot. The result is `all(...)` = False, so the warning says "fix by hand". It does not name which line, and the upgrade would repoint the other line itself. The probe confirms the False result. No test covers this case. There is also no direct unit test of `upgrade_repoints_script` / `bare_script_upgrade_repoints` in `tests/unit/utils/test_ccy_supervisor.py`; they are covered only through the handler.

**Fix:**
- Add a handler test for the mixed case that asserts "by hand".
- Optionally, name the offending line or lines in the message.
- Add utils-level unit tests for the predicate (comment line ignored, CRLF, outside-dir, flags, variable).

## Evidence scripts
- `/workspace/untracked/scratch/rr126/probe.py`: checks that the warning and the migration agree.
- `/workspace/untracked/scratch/rr126/regress.py`, with outputs `old.txt` and `new.txt`: the old-vs-new migration diff (identical).
- `/workspace/untracked/scratch/rr126/oldtree/` and `oldsrc-tests.txt`: the new tests run on the old code (3 failed, 1 passed).
