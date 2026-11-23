# Plan 00523 handoff 3: unit 1 GREEN, unit 2 designed, no unit 2 code yet (2026-11-23)

Third builder, stopped at the 150k context budget. Read handoffs 1 and 2
(`261123-handoff-design-opus.md`, `261123-handoff-red-tests-opus.md`) first.
Branch `plan-00523-rate-limit-dialog`, worktree
`/workspace/.claude/worktrees/agent-a64e490e6608e0f0a-c310ef8b`, head
`1c1e27190` (pushed).

## Done (commit 1c1e27190)

- In `.claude/ccy/claude-supervise.py`, right after `screen_shows_busy_footer`:
  `RateLimitDialog` (with a `signature` property), `recognise_rate_limit_dialog`,
  `rate_limit_dialog_near_miss`, `parse_rate_limit_reset` and
  `rate_limit_composer_text`, plus the `_RATE_LIMIT_*` constants. The imports
  gained `timedelta`, `tzinfo`, `ZoneInfo` and `ZoneInfoNotFoundError`. The
  pointer glyph is written as `chr(0x276F)`, because ruff RUF001 rejects the
  literal character.
- `TickFacts.screen_dump: str = ""`, carried in `_facts_to_json` and
  `_facts_from_json`.
- All 35 tests in `tests/unit/supervise/test_rate_limit_dialog.py` pass.
  ruff and black (`--target-version py311`) are clean. mypy has NOT been run
  yet.

## Unit 2 design (settled with the advisor; write RED tests first, same test file)

The design has two blocks inside `decide_once`, plus a state file.

**Per-instance state.** The sidecar directory is shared by every terminal, so
the state file is keyed by the Claude child's pid:
`sidecar_dir.parent / f"supervise-rate-limit-dialog.{facts.child_pid}.json"`.
When `child_pid` is None the feature is off; a legacy host sends no dump
anyway. Write the file atomically (tmp file, then `os.replace`). Fields:

- `window_reset` (float or None): the window key, which is the parsed reset
  time.
- `window_opened`
- `occurrence_keys`, `window_keys`, `last_signature`
- `phase`: one of `""`, `answered`, `cleared`, `done`, `abandoned`
- `answered_at`, `cleared_at`, `clear_attempts`
- `occurrence_open`

Drop the state 24 h after `window_reset`, or after `window_opened` when there
is no reset time. Do not keep the state in `CompactStateMachine`: the live
host never reloads, and its old `import_state` would drop the unknown keys.

**Early block.** It runs right after `machine.import_state`, before the usage
pause, and is skipped when `CCY_RATE_LIMIT_DIALOG=off`.

1. If `phase` is `answered` or `cleared` and `facts.human_raw_input` is
   non-empty, set `abandoned` and log it once. This check comes BEFORE the
   empty-dump return.
2. An empty `screen_dump` is a strict no-op: no file I/O at all, so the
   existing tests are untouched.
3. When a dialog is recognised, it decides the WHOLE tick: return a
   `TickOutcome` early, as `_usage_pause_outcome` does, with
   `machine_state=machine.export_state()`.
   - A new `parse_rate_limit_reset` value, or expired state, starts a new
     window.
   - A window whose `window_reset` is not None and which is already answered
     (or done or abandoned) gives NOOP: "already answered for this reset
     window".
   - With an unparsed reset, answer once per occurrence and never continue.
   - The gates are `idle`, `input_line_empty`, `main_focus_confirmed` and
     `output_quiet_seconds >= 3`. When they fail, the result is NOOP.
   - The caps are 6 keys per occurrence and 30 per window. When either is
     reached, the result is NOOP.
   - Pointer on the target row with `signature == last_signature`: `\r`, and
     set `answered` and `answered_at`.
   - Pointer on the target row but the signature changed: store the signature
     and return NOOP ("confirming").
   - Pointer elsewhere: one arrow per tick, `\x1b[A` or `\x1b[B`, and store the
     signature.
   - Dry-run: NOOP "would press ...", with no counts and no phase change.
   - `submit=False`. Use a new `Decision.WOULD_RATE_LIMIT_KEY = "would-rate-limit-key"`.
4. A non-empty dump with no dialog sets `occurrence_open=False` and
   `occurrence_keys=0`. On a near miss, write the last 16 KB to
   `sidecar_dir.parent/supervise-rate-limit-unrecognised.txt`, only when the
   content changed. Carry a near-miss note that becomes `noop_reason_log` only
   if nothing else claimed the tick. A near miss does NOT suppress the other
   families.

**Late resume block.** It goes after the model restore and before idle
compaction (around line 9600). It is gated on all of the following:

- `payload is None` and the evaluation decided NOOP
- `signal_path is None` and the machine is in MONITOR
- `not modes_gate_closed` and `not own_line_blocks_text`
- the dump is non-empty
- `idle`, `work_idle`, `input_line_empty` and `main_focus_confirmed`
- `not screen_shows_busy_footer(dump)`

The usage pause has already returned, so it is covered. The steps:

- With no reset time: set `done`, log once, and never continue.
- Before `now >= reset + 120`: NOOP, waiting.
- Phase `answered` (tick A): if `output_quiet_seconds < now - reset`, then
  output appeared after the reset (Claude Code or a human resumed), so set
  `abandoned`. Otherwise read the composer:
  - exactly `continue`: send `"\x7f" * 8` with `submit=False`, set `cleared`
    and `cleared_at`.
  - `""`: go straight to the continue.
  - None: wait.
  - anything else: abandon.
- Phase `cleared` (tick B): this is NOT driven by quietness, because our own
  backspaces repaint the screen. Act on the first settled dump after
  `cleared_at`.
  - Composer exactly `""`: send the continue payload,
    `f"{_format_bot_prefix(now)} {_CONTINUE_BODY}"` with `submit=True`, and set
    `done`.
  - Still `continue`: resend the backspaces while `clear_attempts < 2`.
  - None: wait.
  - Anything else: abandon.
  - The decision is a new `Decision.WOULD_RATE_LIMIT_CONTINUE`. Do NOT use
    `WOULD_CONTINUE`, which the host books as a post-compact resume.
- Dry-run: log "would send continue", set `done`, and type nothing.

**Logging.** Keep the noop strings stable, with no counters or ages, because
`write_noop` dedupes on the text; that is what makes "log once" work. The host
already logs injected keys as `"<decision>: <reason>; injected <payload>"`.

**Tests to write.**

- Enter only on the second stable tick.
- An arrow, never Enter, when the pointer is off the target.
- Unsettled gives NOOP, with the other families suppressed.
- dry-run, env off, legacy empty dump (no state file), `child_pid=None`.
- Once per window, and the caps.
- The resume ticks A and B, then nothing more.
- Before the reset, nothing is sent.
- Abandon on human input, and on output after the reset.
- No reset parsed means no continue.
- The near-miss file.
- A different `child_pid` does not see the state.
- Under the usage pause and under BLOCKED, no continue is sent.

`tests/unit/supervise/conftest.py` clears every ambient `CCY_*` variable, so
the default-ON switch holds in the tests. The pattern to follow is
`test_usage_pause.py` `_decide()`.

## Remaining after unit 2 (unchanged from handoff 2)

- Host (unit 3): add a `ScreenFocusCheck` method that returns the bottom 40
  rows of `--dump`, cached by `total_appended`. In `_on_poll`, send it only
  when `output_quiet_seconds >= 2` (otherwise `""`, never a stale cache). Build
  the screen check also when the feature is on (condition around line 11743).
  Re-resolve the binary lazily, at most once per 60 s.
- Docs, PLAN.md, the README row, a release note, and a journal entry.
- Light QA: targeted pytest on `test_rate_limit_dialog.py`,
  `test_usage_pause.py`, `test_policy_worker.py` and
  `test_dry_run_fire_once.py` under `nice`; ruff; black; mypy on the touched
  files.
