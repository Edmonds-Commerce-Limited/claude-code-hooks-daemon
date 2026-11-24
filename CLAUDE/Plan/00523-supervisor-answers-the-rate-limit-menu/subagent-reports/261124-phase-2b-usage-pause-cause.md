# Plan 00523 Phase 2b builder report: the usage pause records its cause

Branch `fix-n709-secret-guard-bootstrap` (a merged worktree reused, because a new branch is refused).

## Verification of the Fable analysis (00474 `261124-blockers-unblock-fable.md`, Blocker 3)

- Confirmed: the record has seven fields and no cause (`utils/usage_pause.py:76-91`, supervisor
  `claude-supervise.py:3836-3844`). Confirmed: `_usage_pause_outcome` is at `claude-supervise.py:9373`.
  Confirmed: `stop_failure_recorder` stores only the error type and a time.

- Line drift: the no-ceiling `[]` in `fresh_breaches` is at `usage_pause_gate.py:553-554`, not `:548`.

- Unverified: `DESIGN.md:302-304`. Plan 00523 has no DESIGN.md, so that citation belongs to
  another plan.

- Incomplete: the analysis names one early-lift path. The handler has three ways to lift or
  rewrite a record before `resume_at`:

  - `_hold_or_lift`: on a host with no ceiling, any held prompt lifts the pause at once.
  - The lift in `_early_tick`.
  - `rebase_pause`: rebuilt through `build_pause`, it dropped the cause.

  Each path has a RED test now.

- The parsers' answer to "does either reject an unknown key": neither does (both use `.get`). An
  older supervisor reads a record that carries `cause`; this is pinned by tests.

## Built (test-first: RED, then GREEN)

- `cause` (`ceiling` | `hard_limit`) in both readers. It is the last dataclass field and
  defaults to `ceiling`.
  - The writer refuses an unknown cause.
  - The readers turn an absent or unknown cause into `ceiling`. A list or dict value never
    reaches a set lookup, and the record is never dropped.
- Gate: `hard_limit_holds()`. Before `resume_at`, neither a held prompt nor an early resume
  tick lifts or re-bases a hard-limit pause. At `resume_at` or later, the ordinary logic
  applies. A re-base keeps the cause. The deny text, the rule verbose and `get_claude_md`
  state the exception.
- Supervisor (Task 2b.2): a hard-limit pause is NOOP, with the log line "hard limit, nothing
  injected".
  - An await in flight is still dropped, and the latch is never set.
  - It is live only up to `resume_at`, with no grace, because no resume cron exists to clear
    it. The post-reset `continue` then goes out, and the daemon's gate lifts the record on that
    prompt.
  - The dialog Enter still fires under a hard-limit pause.
- Release note `101-usage-pause-records-its-cause.md`.
- PLAN.md: 2b.2 ticked; the stale lines at ~138-141 and ~190-191 are fixed.

## Open

- **Task 2b.1** (the writer): nothing in the repo proves that a `rate_limit` StopFailure is a
  subscription-window hit rather than a transient 429, or that the snapshot reads the hit
  window as full. The only join is the read-only `session_state_document._limit_reset`
  (95%). A wrong `hard_limit` record would hold a session until the 7-day reset, so the
  writer waits for the Phase 1 live capture. Until it lands, everything above is inert.
- **Task 2b.3** (the back-off): the supervisor does not read the stop-failure records, so it
  needs a new channel.
- The supervisor's "usage pause lifted" log line keys on the compact latch, so a hard-limit
  pause ends without that line. This is cosmetic.
- The `usage-pause status` CLI and the session-state document do not show the cause.

## Tests run

All of these passed:

- the new and changed tests;
- whole directories: `tests/unit/supervise`, `tests/unit/utils`, `tests/unit/config`,
  `tests/unit/handlers/stop`, `tests/unit/handlers/user_prompt_submit`;
- tests for the usage-pause tool gate, stand-down, CLI and integration chain;
- `test_audit_error_hiding` and `test_check_generated_doc_drift`;
- the guidance coverage test, the config-changes manifest test, the release-note
  holding-area and shape tests, and the invariant-pairs checker;
- mypy on the changed source files, and black and ruff on the changed files.
