# Plan 00501 Phase 5 (supervisor): implementation report

Branch `worktree-501-phase5-supervisor`, base `6ac377288`. Implementation commit `bc99fb917`. Live supervisor,
`.claude/ccy/ccy.env*`, settings and the main checkout's `.claude/ccy/` were not touched; no process was signalled.

## Host vs worker classification

Every change is WORKER code (hot-reloads; no ccy relaunch needed):

| Change                                                                                   | Where                           | Tier   |
| ---------------------------------------------------------------------------------------- | ------------------------------- | ------ |
| `load_session_modes`, `SessionModesReading`, parse helpers, `_SESSION_MODES_*` constants | module level, called only below | worker |
| Gate: read modes, error log + status-line warning                                        | `decide_once`                   | worker |
| Post-compact `continue` skip                                                             | `decide_once`                   | worker |
| Goal / standing-auth / session-actions skips                                             | `decide_once`                   | worker |
| Clear cap not applied under BLOCKED                                                      | `decide_once`                   | worker |

No `TickFacts`, `TickOutcome`, machine export/import, `_apply_decision`, `PolicyWorker` or PTY-loop code changed. One
caveat, not a host change: the host's in-process fallback (`_poll_once`) calls the HOST's own (old) copy of
`decide_once`, so a tick decided in-process while the worker is silent does not apply the gate until the next ccy
relaunch. Documented in `CcySupervisor.md`.

## Task 5.1

- **Reader.** `load_session_modes(directory, now, own_sessions)` opens only `<stem>.session-modes` for each own session
  (stem rule copied from `session_stem`; `None` = glob all, unit tests only). It validates exactly what the daemon's
  `_parse_file`/`_parse_record` validate (version 1, `session_id` string matching the file name, `modes` list, exact
  record field set, `mode` in {focus, blocked}, reason only and always on blocked, closed `source`/`lifetime` sets,
  string `detail`, finite non-bool times, `expires_at > entered_at`). Live (`now < expires_at`) blocked entries map to
  `awaiting-human` (declared) / `goal-blocked` (goal-loop). Missing file = no mode.
- **Field pin.** `TestFieldPin` compares every supervisor constant to `core.session_mode_registry` / `utils.session_modes`
  (suffix, schema version, all field names, record field set, stored modes, sources, lifetimes, reason-to-label map
  derived from `SessionModeEntry.label`, `BLOCKED_LABELS`, stem rule over hostile ids). Reader tests also read files
  written by the daemon's own `SessionModeRegistry.enter`, so a format change fails both ways.
- **Gate.** Under BLOCKED, `decide_once` skips with deduped noops: `post-compact continue skipped: session BLOCKED (<label>)`,
  `goal injection skipped: ...`, `standing-auth reminder skipped: ...`, `session-actions directive skipped: ...`. The
  continue is replaced before the dry-run latch; the machine has already latched the compaction as handled, so it is not
  retried, and the compaction signal is left to expire (as the usage pause does). The goal signal is withheld, not
  consumed (ages out on its 600 s TTL). `/compact` still runs (tested).
- **Unreadable/malformed file: the gate falls CLOSED.** Named error in `decision.log`
  (`noop: session-modes file unreadable, work-driving prompts withheld: <file>: <error>`, outranking other noop lines so it
  is not hidden) and a status-line WARNING re-posted every tick it persists. Reasoning: the bad file may be the BLOCKED
  entry the gate exists to honour; withholding a prompt costs one turn a human can restart, typing into a blocked loop is
  what the mode exists to stop. The 5.2 cap exemption is NOT granted on an unreadable file (only a confirmed BLOCKED
  earns it). The "status" surface is the status line; `supervisor-status.json` is host-written and was left alone.

## Task 5.2

- With the goal skipped under BLOCKED, a pending `.goal-clear` wins the same tick (test: both present, BLOCKED ->
  `WOULD_GOAL_CLEAR`, goal file kept; not blocked -> `WOULD_GOAL`, existing order).
- `_MAX_GOAL_CLEAR_INJECTIONS` is checked only when not BLOCKED (test: count 8, both reasons -> clear typed; not blocked
  -> `goal clear cap reached`). Counting is unchanged (host bookkeeping), so a blocked clear still increments the
  counter. No busy-session rule added.

## Red / green evidence

- Red: `tests/unit/supervise/test_session_modes_gate.py` before implementation -> `AttributeError: module 'claude_supervise_standalone' has no attribute '_SESSION_MODES_SUFFIX'` (1 failed, run with `-x`).
- Green: the new file 54 passed; `tests/unit/supervise/` 1497 passed, 1 skipped.

## Reload-verification recipe for the coordinator (after merge to main)

Per `CcySupervisor.md` "The rule: verify the reload". Do not restart ccy.

1. Note the time the merge lands `.claude/ccy/claude-supervise.py` on main (`stat -c '%y' .claude/ccy/claude-supervise.py`
   in the main checkout). A plain merge rewrites the file, so its mtime advances and the hash check fires.
2. Within about 10 s run `ps -eo pid,lstart,args | grep 'claude-supervise.py --worker' | grep -v grep`. Expect a NEW pid
   whose start time is later than step 1. If the pid and start time are unchanged after ~30 s, `kill <worker-pid>` ONCE,
   then repeat the `ps` and expect a new pid plus a `worker died ... -> respawned` line in `untracked/supervise/decision.log`.
3. Check `decision.log` shows no `worker crash-looping` and the worker error log has no new `worker crashed (source ...)`.
4. Behaviour: with no `*.session-modes` file for the session nothing changes (no new noop lines). If the session has an
   `awaiting-human` entry (the status-line segment shows it), the next goal/standing-auth/session-actions signal or
   post-compact resume produces the matching `noop: ... skipped: session BLOCKED (awaiting-human)` line instead of an
   injection, and `/compact` still fires at red.

## QA

`FULL_QA_LOCK_WAIT_SECONDS=3600 ./scripts/qa/llm_qa.py changed --range 6ac377288..HEAD --allow-unmapped`:

- First run, on `bc99fb917`: `QA: 37/41 PASSED, 2/41 FAILED, 2/41 NOT MEANINGFUL (detector failed: format, pyright)`
  with `❌ format: 1 files need reformatting` (black on the supervisor) and `❌ pyright: 1 errors`
  (`reportArgumentType`, the blocked-label dict lookup on an unnarrowed `reason`). Fixed in `7373b488d`.
- Clean run, on `7373b488d` (final code head): `QA: 41/41 PASSED`, no `❌` lines.

Head after this report's commit: see `git log` on the branch (the report commit adds only this file).

## Open point for the coordinator

The plan's focus Goals line says "The ccy supervisor injects no goals or prompts" while focused; Phase 5's tasks scope
the gate to BLOCKED only, so focus alone does not close it (pinned by `test_goal_still_fires_under_focus_alone`). If
focus should also gate the supervisor, that is a follow-up task.
