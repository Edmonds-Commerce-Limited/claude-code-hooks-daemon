# Plan 00539 / issue #127: implementer report

Plan work: Plan 00539, Tasks 1.1, 1.2, 1.3 and 2.1. Worktree
`untracked/worktrees/worktree-plan-00539`, branch `worktree-plan-00539`.
Implementation commit: `7832b002c`. The report is committed separately on top
of it.

## What changed

`.claude/ccy/claude-supervise.py`:

- New constants beside the other restart constants:
  `_RESTART_PENDING_FILENAME = "restart-pending.json"`,
  `_RESTART_PENDING_ENV = "CCY_SUPERVISOR_RESTART_PENDING"`,
  `_RESTART_PENDING_DEADLINE_MARGIN_SECONDS = 5.0`.
- `RestartCoordinator` gains a `pending_record_path` keyword argument and a
  read-only property. The path defaults to `state_path.with_name(...)`, so it
  sits beside `restart-request.json` in `_ccy_state_dir()`.
- `request()`: after every refusal (already-pending, dry-run, cooldown,
  abandon cap, ambiguous session id and the #125 focus hold) and BEFORE
  `_perform_injection`, it writes the record with the existing
  `_write_private_json`, which is atomic (temp file + replace) and creates
  the file with mode 0600 in a 0700 directory. Fields: `session_id`, `plugin`,
  `reason`, `requested_at` (wall clock), and `deadline` = `requested_at` +
  `wait_seconds` + the margin. `_PendingRestart.requested_at` now reuses the
  same value. If the write fails, the error is logged ("could not write") and
  the restart still goes ahead, so only the signal is lost (triage design
  choice). If typing raises (`except BaseException`), the record is removed and
  the error re-raised.
- `abandon()` and `finish()` remove the record (`unlink(missing_ok=True)`,
  and an `OSError` is logged as "could not remove"). Only a coordinator that
  holds a pending request removes it.
- `supervise()`: before `pty.fork()` it builds
  `{CCY_SUPERVISOR_RESTART_PENDING: str(restart.pending_record_path)}`, and
  the child branch applies it with `os.environ.update` just before
  `execvp`. The variable is set whether or not the file exists. The parent's
  own `os.environ` is untouched, so the worker and other tests do not inherit
  it. `CCY_SUPERVISOR_STATE_DIR` is only inherited from the launcher; this path
  is derived from the same state dir, so the two are consistent.
- The section comment ("Exit for restart") now describes step 2 and the
  reader contract.

Docs: `CLAUDE/development/CcySupervisor.md`, "Exit for restart". Step 2 now
says the record is written first, and a new **restart-pending record**
subsection covers the schema, when it is written and removed, the deadline
formula, the env var, and the **reader contract**: exists AND names its own
`session_id` AND `deadline` not passed. It also suggests optional hardening:
require the SessionEnd reason `prompt_input_exit`/`other`, so a `/clear` in
the window does not read as a restart. Release callout:
`CLAUDE/UPGRADES/UNRELEASED/release-notes/004-supervisor-restart-pending-record-for-session-end-hooks.md`.
The existing files are 001, 002, 002 and 003, so 004 was the next free
number.

## Red before green

- **Task 1.1**: added `TestPendingRecordIsWritten`, `TestNoRecordWithoutAnExit`
  (`test_plugin_exit_for_restart.py`) and
  `TestRestartExitHolds::test_held_exit_leaves_no_restart_pending_record`
  (`test_main_focus_hold.py`). The red run had 9 failed and 5 passed. The
  failures: `pending_record_path` missing (AttributeError),
  `_RESTART_PENDING_DEADLINE_MARGIN_SECONDS` missing, the record absent before
  typing or after `request()`, and no "could not write" line. The 5 that
  passed are absence checks (dry-run, ambiguous id, typing failure, cooldown,
  cap), which hold trivially while nothing writes. After implementation, 12
  passed and 2 failed: the cooldown and cap tests can only be set up through
  an abandon, so they depended on Task 1.2.
- **Task 1.2**: added `TestPendingRecordIsRemoved` (abandon, finish,
  unremovable record logged). The red run had 5 failed: these 3 plus the 2
  carried over. All of them passed after `_remove_pending_record` was added to
  `abandon()`/`finish()`, and both files were green (135 passed).
- **Task 1.3**: added `TestTheChildIsToldWhereTheRecordIs`, which runs a real
  PTY child. The child reports the env var at start, or reads the record when
  `/exit` arrives, as a SessionEnd hook would. The red run had 2 failed: the
  child saw `<unset>`. The third test checks that the parent environment is
  left alone, so it passes by design. All three passed after the export. The
  on-exit test also proves that the record exists while the child processes
  `/exit` and is gone after `supervise()` returns.
- **Task 2.1**: documentation only; there is no test.

## QA

- `pytest tests/unit/supervise` (worktree venv): 1442 passed, 1 skipped.
- `./scripts/qa/llm_qa.py changed --allow-unmapped`: the first run had
  `format` reformat 2 files in place. The re-run on the still tree gave
  `QA_EXIT=0`, `QA: 40/40 PASSED` (changed_tests 733 passed, 1 skipped). It
  was not recorded for a head because the tree was still uncommitted at the
  time. The supervisor file is unmapped ("too-broad"), so the full gate must
  cover it.
- No suppressions, no sed, no settings edits. No running supervisor or daemon
  was touched. The daemon-restart advisory does not apply, because no daemon
  code changed.

## Left for the coordinator

- PLAN.md task checkboxes and Delivery hashes have not been updated.
- Merge, the full gate and CI.
