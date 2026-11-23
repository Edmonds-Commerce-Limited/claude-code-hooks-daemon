# Plan 00523 handoff 5: units 2b and 3 GREEN; only the paperwork remains (2026-11-23)

The fifth builder stopped here at the 150k context budget. Handoffs 3 and 4 hold the design; this file
records only what changed and what is left.

- Branch: `plan-00523-rate-limit-dialog`
- Worktree: `/workspace/.claude/worktrees/agent-a64e490e6608e0f0a-c310ef8b`
- Head: `ad6f29fa1` (pushed)
- Test command: see handoff 4. `PYTHONPATH=$PWD/src:$PWD` is required.

## Results at ad6f29fa1

| Check                                                                                                                                                                                                       | Result     |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `test_rate_limit_dialog.py`, `test_screen_focus_check.py`, `test_idle_compact.py`, `test_policy_worker.py`, `test_usage_pause.py`, `test_session_modes_gate.py`, `test_dry_run_fire_once.py` (run together) | 404 passed |
| `test_rate_limit_dialog.py` on its own                                                                                                                                                                      | 71 passed  |
| ruff, black `--target-version py311`, and mypy on `claude-supervise.py` plus the test file                                                                                                                  | clean      |

## Unit 2b (commit 997ceae6c)

- **`_rate_limit_resume_step(facts=, dry_run=, status_dir=) -> (_RateLimitResume | None, note)`** sits after `_rate_limit_dialog_step`.

- **Where it is called.** In `decide_once`, after the model-restore block and before the idle compaction. The gates are: `payload` None, NOOP, no signal, MONITOR, `not modes_gate_closed` and `not own_line_blocks_text`. The usage pause returns earlier.

- **The step's own gates:** the child pid, a dump, the switch on, a phase of `answered` or `cleared`, and the occurrence closed.

- **The reset.** It always uses the STORED `window_reset`. With none stored it sets `done` and never continues. Before `reset + 120s` it waits.

- **When the session must be quiet.** The step needs `idle`, `work_idle`, `input_line_empty`, `main_focus_confirmed` and no busy footer.

- **Output after the reset.** It abandons only in `answered`, never in `cleared`, because our own backspaces redraw the box.

- **The input box.**

  | What the box shows | What happens                                       |
  | ------------------ | -------------------------------------------------- |
  | `continue`         | send the backspaces, at most 2 tries; then abandon |
  | empty              | send the bot-prefixed `continue`, then `done`      |
  | other text         | abandon                                            |
  | no box visible     | wait                                               |

- **Dry run** sets `done` and logs "would send continue (dry-run), nothing typed".

## Unit 3 (commit ad6f29fa1)

- **Rendering.** `ScreenFocusCheck.recent_dump()` gives the bottom `_SCREEN_DUMP_ROWS`=40 rows of `--dump`. It is cached by `total_appended`, and a failure is not cached.
- **The binary.** A new `resolve_binary` callable re-resolves a missing binary at most once per `_SCREEN_RESOLVE_INTERVAL_SECONDS`=60. `_build_screen_check` passes it.
- **Sending.** `_rate_limit_screen_dump(screen, output_quiet_seconds=)` returns "" while the output has been quiet for less than 2 s, when there is no check, or when the switch is off. `_on_poll` sends its result as `TickFacts.screen_dump`.
- **When the screen check is built.** It is now also built when `_rate_limit_dialog_enabled()`.
- **Applies only after a relaunch.** This is HOST code and takes effect only on the next ccy relaunch; a worker reload is not enough. Until then the worker gets `screen_dump=""` and the whole feature stays inert.
- **Pyright.** The coordinator flagged `outcome` as possibly unbound in three loop tests. They now collect their outcomes into lists.

## Open risks (document them; do not widen the scope)

1. **Model restore on top of the pre-fill.** While the reset is pending, the composer holds Claude Code's pre-filled `continue`. `can_inject` cannot see the screen, so the model restore (or the usage pause's `/compact`) could be typed onto that text. Handoffs 3 and 4 do not cover this.
2. **An idle redraw blocks the resume.** In phase `answered`, any child output after the reset, including a status-line refresh, abandons the resume. This fails closed: no continue is sent.
3. **No screen in the fallback.** The in-process fallback (`_poll_once`, used when the worker is down) is sent no dump, so the dialog is not answered while the worker is down.
4. **Fixtures.** They are reconstructed, not live captures (see the test module's docstring). Nothing has been verified live.

## Left: the paperwork

- **Docs.** `CLAUDE/development/CcySupervisor.md` needs a section on the rate-limit dialog answer covering:

  - the `CCY_RATE_LIMIT_DIALOG` switch (on by default; off, 0, false or no disable it)
  - the state file `supervise-rate-limit-dialog.<child_pid>.json` and the near-miss capture `supervise-rate-limit-unrecognised.txt`, both in the status directory
  - the risks above
  - that the binary must be built (`nice -n 19 bash screen/build.sh`), and that the feature takes effect only on the next ccy relaunch

  Also check whether `ccy.env` documents switches.

- **PLAN.md.** Set the status to in progress or awaiting merge, NOT Complete. Update the README row to match.

- **Release note.** Add one under `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, checking the numbering for collisions.

- **Journal.** Add an entry with `CLAUDE/Plan/mkplan.bash --journal 00523 <category> <body-file>`.

- **Limits.** Do NOT build hooks-screen into /workspace, restart anything, merge or release.
