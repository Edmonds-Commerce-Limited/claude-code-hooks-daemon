# Plan 00523 handoff 2: RED tests committed, no supervisor code yet (2026-11-23)

Second builder, stopped at the 150k context budget. Read the first handoff
(`261123-handoff-design-opus.md`) first. This one records only what changed
since then. Branch `plan-00523-rate-limit-dialog`, worktree
`/workspace/.claude/worktrees/agent-a64e490e6608e0f0a-c310ef8b`.

## Done

- `tests/unit/supervise/test_rate_limit_dialog.py` (RED, 35 tests, all failing
  for missing symbols). Covered: the recogniser with positives and negatives,
  the near-miss flag, reset-time parsing, composer reading, and the
  `screen_dump` JSON round-trip plus the legacy default. ruff and black are
  clean. The fixtures are reconstructed, and the module docstring says so.
- hooks-screen builds cheaply. `nice -n 19 bash screen/build.sh` finished in
  under 2 s: the musl target is installed and only small vendored crates are
  built. The output lands in the worktree's `untracked/screen-build/`. The
  live host looks under `/workspace/untracked/`, so the lead must run the same
  command from `/workspace` to fix the live container. The build is also cheap
  there. Note that `BUILTIN_MARKERS` in `screen/src/main.rs` is empty, so the
  verdict word is always `unknown`. Only `--dump` is useful, which is all this
  plan needs.

## How to run the tests here

The worktree has no venv of its own. Use the main venv with the worktree
first on the path, or the source-tree guard aborts:

```
PYTHONPATH=$PWD/src:$PWD nice -n 19 /workspace/.venv/bin/python -m pytest -q \
  -p no:cacheprovider -o addopts="" tests/unit/supervise/test_rate_limit_dialog.py
```

## API the tests expect (module `.claude/ccy/claude-supervise.py`)

- `recognise_rate_limit_dialog(dump) -> RateLimitDialog | None`, where the
  result is a frozen dataclass with `options: tuple[str, ...]`, `selected`
  (the pointer row) and `target` (the row whose label is EXACTLY
  `Stop and wait for limit to reset`), plus a `signature` string covering the
  options and the pointer.
  - Pointer glyph `❯` (U+276F). Rows are `[❯] N. label`, numbered 1..n
    consecutively, with an optional trailing ` ✔`.
  - Strip box borders (`│╭╮╰╯─`) from row edges. A row of pure border chars
    counts as blank.
  - Inspect only the bottom ~14 non-blank rows. The title is followed (blank
    rows skipped) by the options.
  - After the options, allow at most ~4 trailing non-blank rows, none of which
    is a composer row (`>`/`❯` + space, not an option). That is what rejects
    the quoted-dialog-above-composer case and the scrolled-up case.
- `rate_limit_dialog_near_miss(dump) -> bool`: True when the target label, or
  a truncated prefix of it (`Stop and wait for limit to re`), appears and no
  dialog is recognised.
- `parse_rate_limit_reset(dump, now) -> float | None`: use the LAST row
  containing `hit your` and `resets <time>`. The formats are `3pm`, `3:30pm`,
  `Nov 29, 3pm` and `Jan 2, 2027, 3:30pm`, with an optional ` (Area/City)`
  suffix (zoneinfo; an unknown zone gives None; no suffix means local time).
  A time-only value in the past means tomorrow. A date without a year that is
  more than 30 days in the past means next year.
- `rate_limit_composer_text(dump) -> str | None`: the text after `> ` / `❯ `
  on a row whose previous non-blank row is a `─` rule. `""` means an empty
  composer, None means no composer is visible.
- `TickFacts.screen_dump: str = ""` in `_facts_to_json` / `_facts_from_json`.

## Design refinements (advisor review, on top of handoff 1)

1. **No `answered_at + 1 h` fallback.** With no parsed reset time, send no
   continue and log it once.
2. **Enter only on a confirmed row.** Send `\r` only when the pointer row IS
   the exact-label row, and only when the dialog signature equals the previous
   tick's (stored in the state file), because the rows load asynchronously.
   Otherwise send one arrow toward the target per tick. Add a test with the
   pointer on a non-target row: it must produce an arrow, never Enter.
3. **Gate dialog keys** on `facts.idle`, `facts.input_line_empty`,
   `facts.main_focus_confirmed` and `output_quiet_seconds >= 3`.
4. **Prefill.** From the bundle: `rtt="continue"`, and
   `armRateLimitAutoContinue` / `prefillRateLimitAutoContinue` set the draft to
   exactly `continue` ONLY when the draft is empty. The prefill never passes
   through stdin, so the host's `input_line_empty` reads True while the box
   holds it.
   - Resume, tick A: once reset+120 s has passed, the dialog is gone, idle,
     input empty, focus confirmed, quiet >= 30 s, no human raw input seen
     since the answer, and the composer reads `continue`, `""` or None, send
     `"\x7f" * 8` raw (`submit=False`). It deletes at most 8 characters,
     exactly the prefill, and is harmless on an empty box. No clear key exists
     in the supervisor today (only `\x1b` and `\r`).
   - Resume, tick B: if the composer reads `""` or None, send the continue
     payload (`f"{_format_bot_prefix(now)} {_CONTINUE_BODY}"`, `submit=True`).
     Any other composer text means: abandon, log once.
   - Any human raw input (`facts.human_raw_input` non-empty) after the answer
     means: abandon the continue (the human is present).
5. **Near miss.** Save a bounded (16 KB) dump to
   `<sidecar_dir.parent>/supervise-rate-limit-unrecognised.txt`, rewriting it
   only when the content changes. Do NOT suppress other families on a near
   miss: transcript text may quote the label.
6. Caps are counted at decision time in the worker, so a write the host
   refuses still burns a count. That fails closed; say so in the docs.

Everything else in handoff 1's "Design to implement" stands: the state file,
the env switch `CCY_RATE_LIMIT_DIALOG`, the new Decision values, the host
dump gated on quiet and cached by `total_appended` (bottom 40 rows), the lazy
binary re-resolve, and the screen check built when the feature is on (the
condition at ~11571).

## Remaining units (commit and push each)

1. GREEN the pure functions above.
2. State file, the `decide_once` branch (right after `machine.import_state`,
   before the usage pause), Decisions, env switch, plus tests for it (dry-run,
   caps, gates, Enter-only-on-target, the two-tick resume, human-input abandon,
   legacy empty dump means nothing happens).
3. Host: `screen_dump` in `_on_poll`, build condition, lazy re-resolve. It
   takes effect only on the next ccy relaunch; the worker part hot-reloads.
4. Docs (`CLAUDE/development/CcySupervisor.md`, `.claude/ccy/ccy.env`), PLAN.md
   (Status In Progress; the stale "installer-managed template" Non-Goal
   removed; Phase 2b left unchecked), the README row, a release note under
   `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, and a journal entry via
   `mkplan.bash --journal`.

## Open questions for the owner

- Claude Code has its own auto-continue (`_autoContinueLive`). Whether choosing
  Stop leaves it armed is unknown, so the supervisor's continue could follow
  Claude Code's own `continue` and duplicate it.
