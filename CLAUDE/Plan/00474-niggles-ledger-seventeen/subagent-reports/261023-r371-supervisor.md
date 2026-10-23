# Release v3.71.0 review fixes D3, D4, D5 (ccy supervisor)

Branch `worktree-r371-supervisor`. Base `047d41947`. Fix commit `0a6ad59bc`.
Review: `untracked/agent-reports/auto/261023-171619-code-reviewer-a5bf4b2ad2b70d6c8.md`, findings 3-5.

I did not touch the live supervisor, its worker, its settings or `ccy.env*`.
The D3 and D4 changes are HOST code (`MainFocusModel`, `_apply_decision`), so
they go live only at the next ccy relaunch. A worker reload is not enough.

## D3: an Alt/Meta chord released the focus hold. REAL

- **Verified:** `ESC [A` then `ESC b` left the model confirmed. The new
  parametrised test failed for `b`, `x`, space, CR and DEL. It also failed for
  the split form (`ESC` | `b`).
- **Fix:** a new `_META_CHORD_BYTES` set (printable ASCII, CR, DEL) at
  `.claude/ccy/claude-supervise.py:670`.
  - In `_consume_esc` (`:1123`), ESC + chord byte returns to ground and keeps
    the hold.
  - In `_resolve_pending` (`:1043-1061`), a pending lone ESC + chord byte keeps
    the hold, eats the chord byte, and parses the rest of the read fresh.
  - These still clear the hold: a bare Esc, a settled pending ESC, `ESC ESC`,
    and ESC + a control byte.
  - The split-ESC, split-arrow, paste and terminal-reply handling is unchanged.
    The class docstring and `CLAUDE/development/CcySupervisor.md` are updated.
- **Tests:** in `tests/unit/supervise/test_main_focus_hold.py`:
  - `test_esc_followed_by_printable_is_a_meta_chord_and_keeps_the_hold[alt-b|alt-x|alt-space|alt-enter|alt-backspace]`
    replaces `test_esc_followed_by_printable_releases`, which pinned the defect.
  - `test_meta_chord_split_across_reads_keeps_the_hold`
  - `test_meta_chord_neither_latches_nor_hides_a_later_arrow`
  - `test_bare_esc_after_a_meta_chord_releases`
  - `test_esc_followed_by_a_control_byte_still_releases`
  - new probe cases `up-esc-esc-split` and `up-esc-ctrl-c-split`
- **Changed expectations:** probe `E-up-esc-Please` and probe
  `up-esc-string-introducer` were `True` and are now `False`. Both are an Up,
  then a pending ESC, then a printable byte, which is the case the finding
  covers.
- **Trade-off:** if the human presses Esc and types a letter before the host
  tick settles the ESC, the model now reads a chord and keeps holding. The
  banner asks for one more Esc. The read stamp cannot tell this apart from a
  split `ESC b` (test `g` records why the clock is not trusted). This is listed
  under Known limits in `CcySupervisor.md`.

## D4: a goal-clear record outlived a clear that was never typed. REAL

- **Verified:** `decide_once` writes the record at `:8293`. Before the fix,
  `_apply_decision` returned early on a focus hold, and a raising PTY write
  propagated. Neither removed the record. The tests
  `test_clear_held_at_apply_removes_its_record` and
  `test_failed_pty_write_removes_its_record` failed before the fix.
- **Choice:** keep writing the record at decision time, and delete it when the
  clear is not typed. The record is stamped with the tick's `now_wall` before
  any byte is typed. That is what the daemon's `CLOCK_TOLERANCE_SECONDS` (1 ms,
  ledger N534) requires: a record may not post-date its clear. Moving the write
  to the host would put it in code that never hot-reloads. It would also need
  the worker's "no record, no clear" refusal rebuilt on the host. Deletion
  changes neither the stamp nor the refusal.
- **Fix:**
  - `goal_clear_record_path` (`:3344`) is the single path rule, now also used by
    `write_goal_clear_record`.
  - `discard_untyped_goal_clear_record` (`:3350`) acts only on a real
    `WOULD_GOAL_CLEAR` whose payload is `/goal clear`. Dry-run is never
    touched. A failed unlink is logged as `warning:`, the same way
    `_consume_signal` does it.
  - `_apply_decision` calls it on the focus-hold early return (`:8783`). That
    also covers `_apply_worker_outcome`'s held path.
  - It is also called from a `finally` around `_perform_injection` (`:8818`)
    when no byte reached the PTY. A partial write (the text typed, the Enter
    failed) keeps the record: supervisor text in the box may still be submitted.
- **Tests:** in `tests/unit/supervise/test_goal_clear_record.py`:
  - `test_typed_clear_keeps_its_record`
  - `test_clear_held_at_apply_removes_its_record`
  - `test_clear_held_in_the_worker_outcome_path_removes_its_record`
  - `test_failed_pty_write_removes_its_record`
  - `test_partial_pty_write_keeps_its_record`
  - `test_held_clear_whose_record_cannot_be_removed_is_logged`
  - `test_held_dry_run_clear_touches_no_record`
- **Residual (not changed):** there is one record per session, so a second
  decided clear overwrites a typed one that the daemon has not yet attributed.
  That was already true before this fix. The fix only adds deletion when
  nothing was typed.

## D5: a failed record write left a temp file. REAL

- **Verified:** `write_text` sat outside the `try`. The test
  `test_failed_temp_write_leaves_no_temp_file` left
  `.clear-sess-1.goal-clear-injected.<pid>.tmp` behind.
- **Fix:** `write_goal_clear_record` (`:3315`) now puts both the write and the
  replace inside the `try`. On `OSError` it unlinks the temp file and re-raises.
  If the unlink also fails, it raises an `OSError` that names the temp file and
  both causes, chained from the original. The caller already logs that text in
  its `goal clear NOT typed: attribution record could not be written` noop
  line, so the failure is not silent.
- **Tests:** `test_failed_temp_write_leaves_no_temp_file`,
  `test_temp_file_that_cannot_be_removed_is_named_in_the_error`.

## QA

- TDD: the 14 new or changed tests failed first, then passed after the fixes.
- `tests/unit/supervise` run explicitly: 1570 passed, 1 skipped.
- `./scripts/qa/run_autofix.sh`: clean, no changes.
- `FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range 047d41947..HEAD --allow-unmapped`
  gave **`QA: 41/41 PASSED`**, with no `❌` lines.
- No suppressions and no exclusions.
