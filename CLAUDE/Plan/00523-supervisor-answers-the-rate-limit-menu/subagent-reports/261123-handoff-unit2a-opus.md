# Plan 00523 handoff 4: unit 2a GREEN (dialog keys); unit 2b, unit 3 and the paperwork remain (2026-11-23)

Fourth builder, stopped at the 150k context budget. Read handoff 3
(`261123-handoff-green-unit1-opus.md`) for the full unit 2 design; this file
records only what changed against it and what is left.

- Branch: `plan-00523-rate-limit-dialog`
- Worktree: `/workspace/.claude/worktrees/agent-a64e490e6608e0f0a-c310ef8b`
- Head: `56a74347d` (pushed)

## Running the tests

pytest refuses this worktree's import path unless you set PYTHONPATH (the
source-tree guard):

```
PYTHONPATH=$PWD/src:$PWD nice -n 19 /workspace/.venv/bin/python -m pytest -q -p no:cacheprovider --no-cov <files> > untracked/scratch/<name>.txt 2>&1
```

The tool commands:

- `/workspace/.venv/bin/ruff check`
- `/workspace/.venv/bin/black --check --target-version py311`
- `/workspace/.venv/bin/mypy --ignore-missing-imports .claude/ccy/claude-supervise.py`

All of them were clean at `56a74347d`. The test results at that commit:

| Test files                                                                                                | Result     |
| --------------------------------------------------------------------------------------------------------- | ---------- |
| `test_rate_limit_dialog.py`                                                                               | 50 passed  |
| `test_usage_pause.py`, `test_policy_worker.py`, `test_dry_run_fire_once.py`, `test_session_modes_gate.py` | 176 passed |

## Done in unit 2a (commit 56a74347d)

In `.claude/ccy/claude-supervise.py`:

- **`Decision` members:** `WOULD_RATE_LIMIT_KEY` and `WOULD_RATE_LIMIT_CONTINUE`. The second is not used yet. The old host passes `decision_value` through as a string (it calls `Decision(...)` only in the in-process `_poll_once`), so new values are safe there.
- **The rate-limit block.** It sits just above `_usage_pause_outcome` and holds:
  - the `_RATE_LIMIT_*` and `_PHASE_*` constants
  - `_rate_limit_dialog_enabled` (the `CCY_RATE_LIMIT_DIALOG` switch; off, 0, false or no disables it; on by default)
  - `_rate_limit_state_path`, which builds `status_dir/supervise-rate-limit-dialog.<child_pid>.json`
  - `_load_rate_limit_state`, which drops the state 24 h after `window_reset`, or after `window_opened`
  - `_save_rate_limit_state` (atomic)
  - `_human_typed`, which strips focus and SGR-mouse reports; bad base64 counts as typed
  - `_new_rate_limit_window` and `_save_unrecognised_screen`
  - `_rate_limit_dialog_step(machine, facts=, dry_run=, status_dir=) -> (TickOutcome | None, note | None)`
- **Wiring in `decide_once`.** The step is called right after `machine.import_state` and before the usage pause, and a non-None outcome is returned. The note is the LAST item in the final `noop_reason_log` chain.

Changes against the design in handoff 3, following the advisor:

- **Lost Enter.** `answered` alone does not mean the dialog is done. While the occurrence is still open (the dialog has not yet been seen gone on a settled dump), a recognised dialog is pressed again, within the caps. `occurrence_open` goes False on the first non-empty dump without the dialog. A dialog that returns after that, in a window with a parsed reset and any phase set, gives NOOP "already answered for this reset window".
- **Unparsed reset.** When a dialog reappears with `window_reset` None, the phase is reset and the dialog is answered again (once per occurrence).
- **Human typing abandons.** Any non-report stdin while the phase is `answered` or `cleared`, or while the phase is `""` with an occurrence open, sets `abandoned`. An open occurrence in `abandoned` or `done` gives NOOP "left to the human for this window".

## Left: unit 2b, the late resume (write RED tests first, in the same test file)

Add a function, for example `_rate_limit_resume_step(facts, dry_run, status_dir)`, that returns the fields to set or None. Call it in `decide_once` AFTER the model-restore block and BEFORE the idle-compaction block (search for `# ── Idle compaction at a percentage (Plan 00603)`).

**Gate.** Every one of these must hold:

- `payload is None`
- `evaluation.decision is Decision.NOOP`
- `signal_path is None`
- `machine.state is SupervisorState.MONITOR`
- `not modes_gate_closed` and `not own_line_blocks_text`
- `facts.child_pid` set, the switch on, and `facts.screen_dump` non-empty
- `facts.idle`, `facts.work_idle`, `facts.input_line_empty` and `facts.main_focus_confirmed`
- `not screen_shows_busy_footer(dump)`

**Phases.** Load the state; act only when the phase is `answered` or `cleared` and `occurrence_open` is False. Use the STORED `window_reset`, never a re-parse: a time-only `resets 3pm` rolls to tomorrow after 3pm.

- **No stored reset:** set `done` and log once; never continue.
- **`now < reset + _RATE_LIMIT_RESUME_GRACE_SECONDS`:** NOOP, "waiting for the limit to reset".
- **`answered`:**
  - `facts.output_quiet_seconds < now - reset` means output came after the reset, so set `abandoned`.
  - Otherwise read the composer with `rate_limit_composer_text(dump)`:
    - `"continue"`: send `_RATE_LIMIT_BACKSPACES` with `submit=False` and decision `WOULD_RATE_LIMIT_KEY`, then set `cleared`, `cleared_at` and `clear_attempts=1`.
    - `""`: send the continue.
    - None: wait.
    - anything else: abandon.
- **`cleared`:**
  - `""`: send the continue.
  - `"continue"` with `clear_attempts < _RATE_LIMIT_CLEAR_ATTEMPTS`: send the backspaces again.
  - `"continue"` otherwise, or any other text: abandon.
  - None: wait.
- **The continue:** payload `f"{_format_bot_prefix(now)} {_CONTINUE_BODY}"`, `submit=True`, decision `WOULD_RATE_LIMIT_CONTINUE`; then set `done`. The existing `mark_own_line_typed` at the end of `decide_once` follows it up.
- **Dry run:** NOOP "would send continue (dry-run)", set `done`, type nothing.

**Logging.** Set `noop_reason_log` only when it is still None. Keep the strings stable, and give each abandon cause its own string.

**Tests to add:**

- tick A then tick B, then nothing more
- nothing sent before the reset
- abandon on output after the reset
- no parsed reset means no continue
- a time-only fixture with `now` past the reset (stored window used)
- no continue under the usage pause (write it with `usage_pause.write_usage_pause`, see `test_usage_pause.py`)
- no continue under BLOCKED (see `_enter_blocked` in `test_session_modes_gate.py`)
- dry run

The `_prompt_screen(text)` helper is already in the test file.

## Left after 2b (unchanged)

- **Unit 3, the host.** Add a `ScreenFocusCheck` method that returns the bottom 40 rows of `--dump`, cached by `total_appended`, and send them in `_on_poll` as `screen_dump` only when `output_quiet_seconds >= 2`. The binary must also be built when the feature is on. Re-resolve the binary lazily, at most once per 60 s. This takes effect only on the next ccy relaunch; document that, and `nice -n 19 bash screen/build.sh`. Do NOT build hooks-screen into /workspace.
- **Paperwork:**
  - docs in `CLAUDE/development/CcySupervisor.md`, plus `ccy.env` if the switch is documented there
  - PLAN.md and the README row
  - a release note under `CLAUDE/UPGRADES/UNRELEASED/release-notes` (check the numbering for collisions)
  - a journal entry via `mkplan.bash --journal`
