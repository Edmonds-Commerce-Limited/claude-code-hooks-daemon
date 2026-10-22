# Plan 00501 Phase 2 implementation report and handoff (Opus sub-agent)

Worktree `/workspace/untracked/worktrees/worktree-501-phase2-blocked`, branch `worktree-501-phase2-blocked`
(pushed). Head at handoff: `3bfaa6a1b` (Task 2.1). Tasks 2.2 and 2.3 are NOT started: this agent passed its soft
context budget (the injected CLAUDE.md guidance alone is large) and stopped at the Task 2.1 boundary. Targeted QA
has NOT been run (run it once after 2.3, as the brief says). No release note yet (Phase 2 changes behaviour, so the
next agent adds one; check origin/main for the next free number).

## Environment notes

- The worktree venv is `untracked/venv-*/bin/python` (`P=$(ls untracked/venv-*/bin/python)`); it imports the
  worktree's `src` (verified).
- Run pytest with `-p no:cacheprovider`; add `--no-cov` for a quick red run (a scoped `--cov` run exits 1 on the
  global fail-under even when every test passes; read the module's own coverage line instead).
- Black: `$P -m black -q <files>` (the Python 3.11 safety warning is benign). Commits must chain with `&&`.
- Recursive greps over `tests/` need `--exclude-dir=cyber-flag`. A `class X`/`def x` grep is denied once by the
  LSP guard; an identical retry is allowed.

## Task 2.1: delivered (commit `3bfaa6a1b`)

`handlers/user_prompt_submit/failsafe_cron_blockage_suppressor.py`: a prompt with no tick sentinel now goes through
`_note_untagged_prompt`. It clears nothing unless `is_genuine_human_prompt(prompt)` (so a `🤖 [ccy-supervisor` line or
other machine traffic is not the owner, logged at INFO), clears the marker only when the marker's `session_id` is
this session (another session's prompt is logged at INFO and keeps it), and resets the cadence only when the
cadence record is absent or belongs to this session.

Tests: `TestOnlyTheSameSessionsHumanClears` in
`tests/unit/handlers/user_prompt_submit/test_failsafe_cron_blockage_suppressor.py` (another session's prompt keeps the
marker and the next tick is still dropped; a supervisor line keeps the marker and the tick is dropped; the same
session's human still clears; a supervisor line keeps the cadence; another session's prompt keeps the cadence).

- RED (`untracked/scratch/p2-red-21.txt`): 3 failed, 1 passed (`AssertionError: assert None is not None`: the marker
  or cadence had been cleared).
- GREEN: `tests/unit/handlers/user_prompt_submit/` 364 passed. The new code is fully covered; the module's remaining
  uncovered lines (278-292, 422-427, 508, 556-558) are pre-existing. ruff, mypy --strict clean.

## Task 2.2: design for the next agent (TDD; tests first)

Code found (all in the worktree):

- Writer: `handlers/stop/auto_continue_stop.py` `_maybe_record_human_blocked_marker` (about line 987) calls
  `blockage_marker.write_marker`; on True, `handle()` Branch 2 calls `_stand_in_block` (about line 714).
- Readers of the legacy marker: the suppressor (above) and `handlers/stop/idle_workable_issue_stop_gate.py`
  `_awaiting_human` (about line 224). `utils/cron_pause.py` only reuses `marker_is_valid`'s rule (leave it).
- Registry: `get_data_layer().session_modes` (`core/session_mode_registry.py`); helpers
  `pin_session_modes`/`awaiting_human_entry` in `tests/support/autonomy.py`.

Steps:

1. `auto_continue_stop`: on a declared stop, `enter` a `SessionModeEntry(mode=BLOCKED, reason=DECLARED, source=AGENT, lifetime=SESSION, expires_at=now + 24 h)` (24 h is the suppressor's `expiry_hours` default; keep one
   constant). An `OSError` from the registry write must not be swallowed at DEBUG: log at WARNING via
   `log_and_continue` and report `marker_written=False` in `stop-events.jsonl`. Decide with the coordinator whether
   to keep writing the legacy file too during the transition (recommended: stop writing it, import it once).
2. **Mandatory stand-in exemption.** `_stand_in_block` gates on `autonomy_allowed(hook_input)`, which becomes False
   as soon as the awaiting-human mode exists, so R-STOP-STAND-IN-MISSING would silently stop firing. Gate it on
   `autonomy_verdict(hook_input).environment_allowed` and on the policy having no focus (`policy.focus_task is None`), i.e. ignore the BLOCKED label for this one demand. Test: the mode is recorded AND the stand-in deny
   still fires for that stop (and still does not fire in a desktop `containers-only` environment, nor under focus).
   Existing tests: `tests/unit/handlers/stop/test_auto_continue_stop_stand_in.py`,
   `test_auto_continue_stop_autonomy.py`.
3. Legacy import, once: when the registry loads (or on the suppressor's first read), a valid
   `human-input-blockage-marker.json` becomes a BLOCKED(declared) entry for its session with
   `expires_at = recorded_at + 24 h`, then the file is deleted. An expired or corrupt one is logged and deleted.
   Test it imports once and a second load does not re-import.
4. The suppressor reads the policy: replace `marker_is_valid` with `registry.policy(session_id).tick_action(tick, runs_while_blocked=..., work_owed=...)` (Phase 1's truth table matches today's rows 2/3 and the declared-job rule).
   The Task 2.1 clear becomes `registry.exit(session_id, ModeLabel.AWAITING_HUMAN)` (and GOAL_BLOCKED) on a genuine
   prompt in that session; the cross-session and supervisor-line tests from 2.1 must keep passing unchanged.
   `matches()` currently keys on the marker file existing; it must instead match any genuine prompt whose session
   has a registry mode or cadence record. Move `idle_workable_issue_stop_gate._awaiting_human` to the policy too.
5. Ruling 07 (post-compact `continue` suppressed under BLOCKED, `/compact` still runs, logged as a named noop
   reason): the `continue` is typed by the supervisor (`.claude/ccy/claude-supervise.py`, `WOULD_CONTINUE`), which
   this brief forbids touching, and the plan schedules it as Phase 5 Task 5.1 (supervisor reads the
   `<stem>.session-modes` file). The daemon side of Phase 2 is that the BLOCKED mode is written to that file.
   Next agent: check `handlers/pre_compact/compaction_signal.py` for a daemon-owned signal the supervisor already
   reads for the post-compact continue; if none, report to the coordinator that Ruling 07 lands in Task 5.1.

## Task 2.3: design

`core/mode_interceptor.py` `UnattendedModeInterceptor` (wired in `daemon/controller.py`) blocks every main-thread
Stop before the chain. Make it stand down when `hook_is_usage_paused(hook_input)` or when the session policy's
`unattended_block_applies` is False (BLOCKED either reason; focus does NOT stand it down). Tests: usage-paused,
awaiting-human and goal-blocked each allow the stop; focus and no mode still block; another session's mode changes
nothing.

## QA

Not run yet.

## Left

Tasks 2.2 and 2.3, the release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, PLAN.md ticks for 2.2/2.3,
targeted QA, and filling in this report's QA section with the QA line, head sha and unmapped files.
