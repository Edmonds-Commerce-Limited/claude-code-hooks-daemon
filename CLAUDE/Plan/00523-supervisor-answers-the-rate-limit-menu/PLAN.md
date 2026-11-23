# Plan 00523: supervisor answers the rate limit menu

**Status**: In Progress
**Created**: 2026-10-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

When the account hits its five-hour or weekly limit, Claude Code shows an
interactive menu. One of its options waits until the limit resets. An
unattended session stays on that menu until somebody answers it. The owner
asked that the ccy supervisor answer it by pressing Enter, so the session
waits for the reset by default.

The supervisor cannot see the menu today. `OutputActivity.record` in
`.claude/ccy/claude-supervise.py` keeps only a byte count and the time of the
last output from the child. It uses those to tell busy from settled, and never
reads what the child prints. Its only handling of limits is the daemon's usage
pause (Plan 00479 Task 4.5), which is a separate trigger. So this plan adds a
new capability: a bounded tail of recent child output, and a recogniser for
the menu in it.

Read Plan 00487 (the supervisor plugin API) before choosing where the
recogniser lives. Read Plan 00339 (payload-then-`\r` submit timing) before
writing the keystroke.

## Goals

- When Claude Code's rate-limit menu appears, the supervisor presses Enter
  exactly once and the session waits for the reset.
- The key it sends is proven, against a captured real menu, to select the
  wait option.

## Non-Goals

- Choosing any option other than waiting (extra usage, switching model).
- Changing the daemon's usage pause (Plan 00479) or its `/compact`.

## Tasks

### Phase 1: Evidence

- [ ] ⬜ **Task 1.1**: Capture the real menu as raw PTY bytes (ANSI included),
  for both the five-hour and the weekly limit if they differ, with the
  highlighted default recorded. Commit the capture as a test fixture. If
  Enter does not select waiting, record the key sequence that does.
- [ ] ⬜ **Task 1.2**: Record whether Claude Code fires a `Notification` hook
  (or any other hook event the daemon receives) while the menu is shown. If it
  does, that event is the preferred trigger for Task 2.2's closer look, ahead
  of the idle heuristic.

### Phase 2: Recogniser (TDD)

- [x] ✅ **Task 2.1**: RED: tests on the captured bytes. The menu is
  recognised. Ordinary output that quotes the menu's wording is not
  recognised. Output split across chunks is handled. Done on RECONSTRUCTED
  screen fixtures (no live capture yet, Task 1.1); the rendered screen makes
  chunk splitting moot.
- [x] ✅ **Task 2.2**: GREEN. As built, the host sends the bottom 40 rows of
  `hooks-screen --dump` (`TickFacts.screen_dump`, only after 2 s of quiet
  output), and the worker's `_rate_limit_dialog_step` matches them. This is
  in the supervisor itself, not a plugin: the step must decide the whole tick
  ahead of the usage pause. Original wording: a bounded tail of child output, kept as a ring
  buffer like `RawInputTap`, plus the recogniser. The tail is inspected only
  when a closer look is triggered (owner's suggestion): output has been quiet
  past a threshold, as the existing `OutputActivity` settle logic measures it,
  or by the hook event from Task 1.2. It is rendered to plain screen text
  (Claude Code redraws menus with cursor movement) before matching, never
  matched as raw bytes. Put it in a plugin if Plan 00487's API fits;
  otherwise say why it does not.
- [x] ✅ **Task 2.3**: The keystroke is sent once per menu occurrence. A latch
  clears only when the menu leaves the screen. Each press is logged to the
  decision log, and dry-run mode logs it without sending. As built, the latch
  is per reset window, and the keys are capped per occurrence and per window.
- [x] ✅ **Task 2.4** (as built: `rate_limit_armed_status`, in the startup banner and the first decision-log line; the key is `CCY_RATE_LIMIT_DIALOG`): A readable armed state for Plan 00632's readiness check
  (Plan 00630 vet M-9): a config key that turns the answerer on, plus a
  supervisor status line saying whether it is armed in this session. TDD.
- [x] ✅ **Task 2.5** (added): after the reset, clear the pre-filled box and
  send one `continue`. Two guards go with it:
  - every other family is held while the pre-fill may be in the box;
  - output after the reset opens a bounded re-check rather than abandoning the
    window outright.

### Phase 2b: Hold every injection until a hard limit resets (owner report)

The owner saw a session at its weekly limit get `/compact` and `continue`
typed by the supervisor every 5 minutes. Each failed with "You've hit your
weekly limit · resets <time>", and the supervisor retried regardless.

- [ ] ⬜ **Task 2b.1**: Turn a hard limit into a pause the supervisor already
  honours. When the daemon records a `rate_limit` StopFailure
  (`stop_failure_recorder`, Plan 00470 Task 3.1), it writes the session's
  `.usage-paused` record. Its `resume_at` is the reset time from the latest
  status payload's `rate_limits` (Plan 00479), or the reset time this plan's
  screen recogniser reads, whichever is available. TDD.
- [ ] ⬜ **Task 2b.2**: A pause caused by a hard limit injects nothing, not even
  the single usage-pause `/compact` (`_usage_pause_outcome`), because every
  request fails until the reset. A ceiling pause keeps its `/compact`. TDD in
  the supervisor suite. (Whether the owner's "no usage ceiling" ruling retires
  the Plan 00479 ceiling, and with it this branch, is Plan 00630 Q16.)
- [ ] ⬜ **Task 2b.3**: With no reset time known, back off rather than retrying
  every tick: double the interval after each identical failure, up to a cap.

### Phase 3: Verify and ship

- [ ] ⬜ **Task 3.1**: Verify on a real session that hits a limit. The menu is
  answered, the session waits, and work resumes at the reset.
- [x] ✅ **Task 3.2**: Add a release note for the new supervisor behaviour
  (`025-supervisor-answers-the-rate-limit-dialog.md`).
- [x] ✅ **Task 3.3**: Independent review and the full QA gate, then merge.
  The review is done
  (`untracked/agent-reports/261123-00523-independent-review.md`, not tracked),
  and every finding I1-I5 and L1-L4 is fixed test-first. L5 (one `--dump`
  per output burst) is accepted. PR #223 merged to main as `42486817b` (merge
  commit; "CI green" is unverified here). The opus delta review verdict was
  safe (`subagent-reports/261123-opus-delta-review-pr223.md`). The Performance
  sweeps flake `test_many_appends_each_run_are_judged_quickly` failed once on
  this PR: the CI-log reader agent reported 1.68 s against the scaled budget
  `scaled_cpu_seconds(1.5)` (1.5 s is only the base budget, not the bound the
  runner applied), and it passed on re-run. Cited line numbers are unverified
  here.

### Follow-ups from the delta review (open)

- [x] ✅ **F1**: the sweep deletes open key-capped state at anchor+48h, though
  load keeps it. Fixed: the sweep keeps it.
- [x] ✅ **F2**: a held Enter skips the host apply veto. Fixed: a held send is
  taken back (`_rate_limit_host_held`).
- [x] ✅ **F3**: the empty-box re-check abandons the window instead of retrying.
  Fixed: output within 5 s of a vetoed resume send is not a re-check trigger.
- [x] ✅ **F4**: a same-window re-answer after a D2 take-back, within the key
  cap. Fixed by a cap of 2 taken-back Enters per window.
- Still open and blocked: Task 3.1 and Phase 1 (live capture) need a real
  limit hit. Phase 2b (hold injections while a hard limit lasts) needs a design
  ruling first: the `.usage-paused` record has no field to tell a hard limit
  from a ceiling pause, and Plan 00630 Q16 may retire the ceiling pause.

## Success Criteria

- [ ] On a real limit hit, the menu is answered once and the session waits for
  the reset, proven by tests that failed first and by one live observation.
- [x] Release-bound consequences are recorded in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
  (`025-supervisor-answers-the-rate-limit-dialog.md`; no truth or config
  changes).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00523-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed at the owner's request; the dedupe scout found no overlapping plan
  (55 live plans checked).

- Branch `plan-00523-rate-limit-dialog`. The commits so far:

  - recogniser and parsers: `1c1e27190`
  - dialog answer: `56a74347d`
  - resume: `997ceae6c`
  - host screen dump: `ad6f29fa1`
  - pre-fill hold: `d4e5b2f02`
  - re-check window: `1dc68225e`
  - docs: `76cab97bf`

- Review fixes:

  - I1, state keyed on pid and start ticks: `dff3b0e25`
  - the stored window holds while the dialog is open: `c0fd7f7f4`
  - I2, keys before the first dump: `36013aba6`
  - I3/L4, host apply veto: `27f53c86a`
  - I4, the limit row is required: `67942b4fd`
  - I5, the placeholder counts as empty: `49051a467`
  - L1, near miss logged by hash only: `3579f3571`
  - L2, reset clamped to 300 s past and 8 days ahead: `0edb3bff3`
  - L3, awaiting-human test: `2aabccc73`
  - docs: `a3118578e`

- Merged: PR #223, merge commit `42486817b`. Status stays In Progress: the
  host part takes effect only after the next ccy relaunch, and the
  `hooks-screen` build is the owner's v2-window action, deliberately not built
  in /workspace.

  The host part (the screen dump and the apply veto) takes effect on the next
  ccy relaunch. Phase 1 (live capture), Phase 2b and Task 2.4 are still open.
