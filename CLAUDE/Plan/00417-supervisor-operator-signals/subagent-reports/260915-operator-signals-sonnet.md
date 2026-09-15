# Plan 00417 Phase 1 — supervisor operator signals: implementation report

**Branch**: `worktree-issue-39-operator-signals` (worktree, not merged to main)
**Commits**: `5237f62a` (implementation), `c573fed5` (error-hiding scan fix),
`5aefc3cd` (plan/journal closeout)

## Summary

All six Phase 1 tasks and all five success criteria in PLAN.md are complete
and checked off. Full `./scripts/qa/llm_qa.py all`: **29/30 PASSED** — tests
23792 passed / 0 failed / 22 skipped, coverage 95.3%. The one failing check
(`docs_qa`, 2 advisory findings) is a pre-existing dead link in Plan 00413's
`NIGGLES.md`, unrelated to this diff. Daemon restarted and verified
`RUNNING` afterward with a fresh pid.

## What was built

- **`src/claude_code_hooks_daemon/utils/operator_signal.py`** (new) — the
  daemon-side writer. `write_operator_signal` validates a closed `kind` set
  (`reboot-warning`, `shutdown-warning`, `reboot-cancelled`) plus, for the
  two that need one, a positive-integer `minutes` (rejects `bool` explicitly
  since it's an `int` subclass). `discover_session_ids` backs
  `--all-sessions` by listing `<session>.json` context sidecars already in
  the project's shared, bind-mounted directory.

- **`.claude/ccy/claude-supervise.py`** — `load_operator_signal` (validates
  the untyped JSON independently of the writer, and *renders* the message in
  the same step) + `_render_operator_message` (the three fixed templates;
  `minutes` is the only interpolated value, `kind` only ever selects a
  branch) + a new `decide_once` branch, consumed at the idle choke point
  ahead of goal/model-switch/model-restore but subordinate to
  compact/continue/escape, DROP ANCHOR and the coupled-effort correction. A
  WARNING-level status-line countdown (`write_status_message`, same channel
  as the Ctrl+Z notice) posts the instant a valid signal is observed,
  independent of whether the chat line can type yet — anchored to
  `ts + minutes * 60` from the signal's own write time so it converges on a
  real deadline rather than perpetually restarting. `reap_stale_sidecars`
  now also reaps `*.operator-signal` files.

- **CLI**: `hooks-daemon signal <kind> [--minutes N] [--all-sessions] [--project-root PATH]`, mirroring `inject-goal`. Without `--all-sessions`
  it's session-keyed via `CLAUDE_CODE_SESSION_ID` exactly like `inject-goal`;
  `--all-sessions` needs no session context at all (the point — it's for
  host-side tooling) and writes one signal per live session discovered in
  the project's own context-sidecar directory, nothing outside it.

- **`CLAUDE/Architecture/OperatorSignals.md`** (new) — the signal set, the
  no-free-text rule and why, delivery semantics, and the CLI. Linked from
  `CLAUDE/CLAUDE.md`'s routing table.

## Design decisions worth flagging (asked for disagreement — here's where I used it)

1. **Precedence placement is a compromise, stated explicitly.** The task
   said "ahead of goal and model injections." I placed the branch right
   after DROP ANCHOR + the coupled-effort correction and before the manual
   model-switch override — literally ahead of both model families and goal.
   Consequence: it sits *before* the block that computes the shared
   `own_line_blocks_text` variable (goal/standing-auth use it to avoid
   pasting text over a possibly-unconfirmed line the supervisor itself
   typed). I gated on the raw `machine.own_line_pending` flag instead — a
   little more conservative (a line a *later* tick would resolve this same
   tick still reads as pending from this earlier vantage point), which is
   the safe direction. If a future reviewer wants operator signals to sit
   *after* the own-line block instead (trading "as fast as possible" for
   "reuses the exact same resolved variable"), that's a one-block move, not
   a redesign.

2. **The rendering templates live in the supervisor script, not the daemon
   package**, even though this is self-install and the daemon *could* import
   itself. Reasoning: the real trust boundary for this channel is a JSON
   file on disk (writable by anything with filesystem access to the
   container's bind-mounted `untracked/`), not the daemon's typed Python
   call — so the supervisor's read of untyped JSON is where the "only ever a
   number, never text" guarantee actually has to hold, independent of
   whatever discipline the writer's Python type hints provide. This mirrors
   how the existing model-switch/model-downgrade signals already split
   writer and reader across the process boundary.

3. **TTL default reuses `_DEFAULT_REAP_TTL_SECONDS` (1800s / 30 min)**, not
   the shorter goal-signal TTL (600s), on the theory that a reboot warning
   should still be deliverable if a session stays busy for a while, and a
   signal older than the reaper's own window is about to be deleted anyway
   regardless of what TTL I picked. Easy to change if 30 minutes is judged
   too generous or not generous enough — it's one named constant.

## On the open question (session answering "not yet")

No new opinion beyond what's already in PLAN.md: it needs a fixed-token
design (never text, per the same no-free-text rule) and an owner ruling on
the exact contract — e.g., does the session write it proactively at any
point, or only in response to something host-side has already signalled? I
did not build anything toward it; Phase 1 doesn't depend on it.

## TDD

RED-first for every new test file — each was written and run to a confirmed
failure before its corresponding source file existed:

- `tests/unit/utils/test_operator_signal.py` (20 tests, daemon-side writer)
- `tests/unit/supervise/test_operator_signal.py` (39 tests: kind pinning
  against the daemon writer, `_render_operator_message`, `load_operator_signal`
  validation/rejection, `decide_once` integration including precedence,
  status-line posting, exactly-once consumption, own-line safety, reaper
  coverage, and a round-trip test against the *real* daemon writer function)
- `tests/unit/daemon/test_cli_signal.py` (10 tests: single-session mode,
  validation refusals, `--all-sessions`)

Confirmed RED (real `AttributeError`/`AssertionError` output) before writing
each corresponding source file; quoted the actual pytest failure output
before implementing in each case during the session. Full
`tests/unit/supervise/` (839 tests) and `tests/unit/daemon/` (1917 tests)
re-run clean afterward — no regressions.

## A mistake worth naming

Mid-session I restarted the hooks-daemon while `llm_qa.py all`'s own test
step was still running, despite its CLI printing an explicit warning that
this would corrupt the run's daemon-socket-dependent acceptance tests. It
did — ten spurious errors in `test_playbook_harness.py`,
`test_stop_hook_hard_block.py`, `test_tool_use_error_recovery.py`. I killed
that run rather than trust its output, confirmed the daemon was healthy, and
re-ran clean without touching the daemon mid-run again. Also surfaced one
real, this-plan-caused finding from the killed run's still-valid partial
output: `cmd_signal`'s benign `except RuntimeError: logger.debug(...)`
(identical shape to `cmd_inject_goal`/`cmd_clear_goal`) had no matching entry
in `scripts/qa/error_hiding_exclusions.json`; added one with the same
justification, verified the self-scan test passes in isolation and in the
subsequent clean full run.

## Files touched

- `src/claude_code_hooks_daemon/utils/operator_signal.py` (new)
- `.claude/ccy/claude-supervise.py`
- `src/claude_code_hooks_daemon/daemon/cli.py`
- `scripts/qa/error_hiding_exclusions.json`
- `CLAUDE/Architecture/OperatorSignals.md` (new)
- `CLAUDE/CLAUDE.md`
- `tests/unit/utils/test_operator_signal.py` (new)
- `tests/unit/supervise/test_operator_signal.py` (new)
- `tests/unit/daemon/test_cli_signal.py` (new)
- `CLAUDE/Plan/00417-supervisor-operator-signals/PLAN.md`,
  `JOURNAL/00417-Journal-26-09-15.md`
