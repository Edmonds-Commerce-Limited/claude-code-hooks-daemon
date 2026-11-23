# Plan 00523 review fixes: handoff (context budget reached)

Worktree: /workspace/.claude/worktrees/agent-a64e490e6608e0f0a-c310ef8b
Branch: plan-00523-rate-limit-dialog, pushed at dff3b0e25. The working tree is clean.
Review: /workspace/untracked/agent-reports/261123-00523-independent-review.md

## Done

- I1 (dff3b0e25). `_read_child_start(pid, proc_root)` reads `/proc/<pid>/stat` field 22 and adds `btime`.
  `_rate_limit_child_start(pid)` is the patch point for tests.
  - `_rate_limit_state_path` now returns `Path | None`. The file name is `prefix.<pid>-<ticks>.json`, and
    None means the feature is off for the tick.
  - `_load_rate_limit_state(path, now, child_pid)` ignores state whose `window_opened` predates the child's
    start, with 5 s of slack.
  - `_sweep_rate_limit_states` runs when a new window opens.
  - In the tests, an autouse fixture `_child_starts` in `tests/unit/supervise/test_rate_limit_dialog.py`
    patches the start (pid 4242 gives (424200, 0.0), pid 7 gives (700, 0.0)).

## Left, in order (test-first; one commit and push per fix)

### I2: human keys before the first dump

In `_rate_limit_dialog_step`, keep an in-memory per-state-path tracker (a module dict, reset by the
autouse fixture). It holds `pending_keys`:

- set by any `_human_typed` tick, including ticks with an empty dump;
- cleared when a chunk ends with the human's own `\r` (a submitted prompt), or when a dialog-free
  dump is seen;
- initialised to True in a fresh worker. This is conservative: a reload mid-turn abandons the next dialog.

When the dialog is first seen, if `pending_keys` is set, open the occurrence as `abandoned`.

Also do both of these:

- **Changing dialog.** Store `seen_options` and the allowed `selected` set: after an arrow, {before,
  before±1}; otherwise {selected}. If the options differ, or the pointer is outside that set, abandon.
- **Re-parse bug the advisor found.** Line ≈8975 opens a new window whenever the re-parsed reset
  differs. An abandoned dialog left on screen past "resets 3pm" re-parses as tomorrow and gets
  answered. Keep the stored window while `occurrence_open` is set. Write a test for it.

Test from the review: the human presses Down with no dump, then the first dump arrives with no input.
Nothing should be typed.

### I3/L4: apply-time check on the host

The host is ONE select loop (≈12083). The tap cannot grow during the worker round trip, so check
`_fd_readable(resolved_stdin_fd)`.

- Add a testable helper `_rate_limit_apply_veto(outcome, *, stdin_pending: bool, current_dump: Callable[[], str]) -> str | None`. It applies to `WOULD_RATE_LIMIT_KEY` and `WOULD_RATE_LIMIT_CONTINUE`.
  - Veto if stdin is pending.
  - For an Enter payload, re-recognise `activity.screen.recent_dump()` and require
    `selected == target`.
- Call it in `_apply_worker_outcome` (≈10603) after the focus check. On a veto, log a noop and return
  False without adopting the state.
- This needs a ccy relaunch (host code).

### I4: require the context row

Require a row matching "hit your … limit" in the window ABOVE the title in
`recognise_rate_limit_dialog`. Add a negative test with an AskUserQuestion-shaped screen. In the docs,
say this NARROWS the risk: a model can write that row too.

### L1: no dump saved

Remove `_save_unrecognised_screen` and `_RATE_LIMIT_UNRECOGNISED_FILE`. The note carries only a
sha256 prefix and the row count. Keep the note text stable apart from those values.

Update `test_near_miss_screen_is_saved` and the test module docstring (lines 9-10), and the docs.

### L2: clamp the reset at parse time only

Return None unless `now - 300 <= reset <= now + 8 days`. Weekly resets are at most 7 days away, plus
a day of slack.

- `test_date_with_year` (Jan 2 2027 from Nov 23) needs a nearer `now`.
- Add tests for Feb 31, year 0000, year 9999 and a past explicit year.

### I5: placeholder in the input box

A narrow allow-list: `^Try ".*"$`, straight or curly quotes. It counts as empty only if no human key
arrived since the clear (`facts.input_line_empty` already ANDed). Anything else still abandons.
The placeholder strings were not verified against the binary; the binary grep was blocked.

### L3: awaiting-human test

`declared_blocked_entry` already carries the awaiting-human label, so the test passes at once. Assert
`entry.label == ModeLabel.AWAITING_HUMAN`, and add a goal-loop blocked case. Say in the commit that
it was green on arrival.

### Then

- Update `CLAUDE/development/CcySupervisor.md` (the rate-limit section), the release note
  (`CLAUDE/Plan/.../025-supervisor-answers-the-rate-limit-dialog.md`, found via
  `git diff --stat main...HEAD`) and the plan's PLAN.md. Journal only via `mkplan.bash --journal`.
- Run light checks: targeted pytest on the touched test file (scratch redirect), ruff, `black --check --target-version py311`, mypy on touched files, all under `nice -n 19`.
- Open the PR with `gh pr create`. Title: 'Plan 00523: supervisor answers the rate-limit menu'. A
  short body: what the change does, the review and what is fixed, and the relaunch caveat (host-side
  dump and veto). No private paths or seat names, and no closing keywords. Do NOT merge.

## Commands

```
cd <worktree>
PYTHONPATH=$PWD/src:$PWD timeout 300 nice -n 19 /workspace/.venv/bin/python -m pytest \
  tests/unit/supervise/test_rate_limit_dialog.py -q -p no:cacheprovider --no-cov > untracked/scratch/rl.txt 2>&1
/workspace/.venv/bin/ruff check <files>; /workspace/.venv/bin/black --check --target-version py311 <files>
```

Use `&&` chains, not `;`, when commands are sequenced (the safe-mode guard).
