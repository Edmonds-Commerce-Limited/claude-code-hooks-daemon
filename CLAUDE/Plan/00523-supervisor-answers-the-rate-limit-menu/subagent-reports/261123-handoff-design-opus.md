# Plan 00523 handoff: design ready, no code written yet (2026-11-23)

Written at the 150k context budget by the first implementing agent. Orientation
and design are done; implementation has NOT started. Branch:
`plan-00523-rate-limit-dialog` (from origin/main ab326aad0), worktree
`/workspace/.claude/worktrees/agent-a64e490e6608e0f0a-c310ef8b`.

## Owner order (verbatim essentials)

Supervisor (`.claude/ccy/claude-supervise.py`) detects Claude Code's
`/rate-limit-options` dialog from rendered screen text, selects
"Stop and wait for limit to reset" by keystroke, logs to decision.log, and
sends the supervisor's existing `continue` prompt after the parsed reset time.
Bounded, idempotent per reset window, fail-closed on any unrecognised screen,
env switch default ON. Strict detector (exact phrase, dialog in foreground),
negative tests. Screen-text fixtures only. LIGHT QA ONLY: targeted pytest on
touched files, ruff check, black --check --target-version py311, mypy on
touched files. No full gate, no merge to main, no release. Do not restart the
live worker. Also: the missing `hooks-screen` binary.

## Plan folding

Dedupe scout: Plan 00523 is the same deliverable (79 live plans checked; an
independent `ls -d CLAUDE/Plan/0*/ | wc -l` also gives 79, so the count
reconciles). Fold into 00523 rather than creating a plan: extend its tasks
with reset-time resume and hooks-screen degradation. There is no
installer-managed template twin of the supervisor (`git ls-files` shows only
`.claude/ccy/claude-supervise{,.py}`), so 00523's Non-Goal about "the
installer-managed template" is stale; edit `.claude/ccy/claude-supervise.py`.

## Evidence from the Claude Code 2.1.330 bundle (no live capture exists)

Extracted with `untracked/scratch/rl/find.py` (mmap search of
`/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`; a grep
over the 380 MB binary times out, use the script).

- The dialog is a `Dialog` with title exactly `What do you want to do?` around
  a `Select` (`declineValue:"cancel"`, `visibleOptionCount:P.length`). The same
  title is used by the trial-expired dialog, so the title alone is NOT enough.
- The target row is `{label:"Stop and wait for limit to reset", value:"cancel"}`.
  The label is plain `Stop` under usage-based billing (or another flag), so the
  exact-phrase match correctly does nothing there.
- Row order: `Le&&!w ? [...upgradeRows, Stop, ...others] : [Stop, ...others, ...upgradeRows]`
  (`Le` = feature flag `tengu_jade_anvil_4`). So Stop is USUALLY first but not
  always; the initially highlighted row (`selectedValue:Lo`) is unknown.
- `refuseInput`: input is refused for a window after the rows change. Send a key
  only after the screen has been quiet (stable) for a settle period, and re-check
  after each key.
- Esc (`onCancel: xe`) closes via the same `_i()` path as selecting Stop when no
  auto-resume is armed. The owner asked for the option, so select the row.
- Choosing Stop calls `prefillRateLimitAutoQueueContinue`. The composer may hold
  prefilled text afterwards. This is an OPEN QUESTION for the continue step.
- Limit message: `You've hit your <limit> · resets <AC(resetsAt,true)>`. The time
  formatter (`Y0`) gives `3pm`, `3:30pm` (under 24 h away) or `Nov 29, 3pm`,
  `Nov 29, 3:30pm`, `Jan 2, 2027, 3pm` (over 24 h away or a different year),
  each with an optional ` (Europe/London)` timezone suffix. The auto-resume row
  label is `Wait here, then continue automatically at <time>` (local tz, no suffix).

## Architecture constraints found

- Only the HOST holds the screen (`ScreenBuffer`/`ScreenFocusCheck`, ~line
  1255-1476) and the host never hot-reloads. The worker (`run_worker`, ~10259)
  gets `TickFacts` as JSON (`_facts_to_json`/`_facts_from_json`, ~10109). So:
  the HOST ships a gated `hooks-screen --dump` text in a NEW TickFacts field
  (`screen_dump: str = ""`, empty from a legacy host = fail closed), and
  recognition plus decision live in the WORKER (`decide_once`, ~8672). The host
  part takes effect only on the next ccy relaunch. Say so in the report.
- Host tick: `supervise()._on_poll` (~11683). Build the screen check also when
  the rate-limit feature is on (condition ~11571). Render the dump only when
  `output_quiet_seconds >= ~2s`, cached by `buffer.total_appended`, and send the
  bottom ~40 rows only.
- The hooks-screen binary is resolved ONCE at host start (`_build_screen_check`
  -> `resolve_screen_binary`). Make it lazy: when None, re-resolve at most once
  per ~60 s, so a binary built after start is picked up (host change).
- `_perform_injection(submit=False)` writes the payload RAW (no paste framing):
  use it for `\r`, `\x1b[A`, `\x1b[B`. Old hosts treat unknown decision_value
  strings fine (`_apply_post_injection_bookkeeping` compares strings).
  `import_state` merges by present key.
- `_apply_decision` refuses a payload when main focus is not confirmed (fine).
- `_poll_once` (in-process fallback, ~10007) builds TickFacts without the dump,
  so the fallback never answers: fail closed, acceptable.
- Existing continue payload: `f"{_format_bot_prefix(now)} {_CONTINUE_BODY}"`
  (`_CONTINUE_BODY = "continue"`, ~8063). Injected for real even in dry-run.

## Design to implement (TDD)

New section near the screen code, all stdlib:

1. `_RATE_LIMIT_DIALOG_ENV_VAR = "CCY_RATE_LIMIT_DIALOG"` (`on` default, `off`).
   Document in `.claude/ccy/ccy.env` and `CLAUDE/development/CcySupervisor.md`.
2. `recognise_rate_limit_dialog(dump) -> RateLimitDialog | None` (pure):
   non-blank rows, strip box-drawing border chars from row edges, inspect the
   bottom ~14 rows only. Need: a row exactly `What do you want to do?`;
   within 2 rows below it, consecutive numbered option rows `[❯]? N. label`
   (1..n); exactly one row with the pointer `❯`; exactly one label equal to
   `Stop and wait for limit to reset`; at most ~4 trailing rows, none starting
   with a prompt glyph (`>`/`❯`) or looking like an option. Returns options,
   selected index, target index. Negative tests: transcript quoting the dialog
   above a visible composer, `Stop` label, two pointers, no pointer, title only,
   trial-expired dialog, truncated label, prose mention.
3. `parse_rate_limit_reset(dump, now) -> float | None`: last row containing
   `limit` and `resets <time>`; exact formats above; tz via `zoneinfo`, else
   local; time-only in the past -> +1 day; date without year in the past by
   more than 30 days -> next year. Anything else -> None.
4. State file `sidecar_dir.parent / "supervise-rate-limit-dialog.json"`
   (atomic tmp+replace): `{reset_at, answered_at, occurrence_keys, window_keys, continued}`. Caps: keys per occurrence (~6; occurrence resets when a quiet
   dump shows no dialog), keys per window (~30). Resume due = (reset_at, or
   answered_at + 1 h fallback) + ~120 s margin; one continue per window; drop
   state 24 h after due.
5. `decide_once`: right after `machine.import_state`, before the usage pause,
   call the rate-limit branch. Dialog recognised -> it decides the WHOLE tick
   (suppresses every other family incl. the own-line resubmit Enter): not
   settled (`output_quiet_seconds < 3`) -> NOOP; cap reached -> NOOP + log;
   dry-run -> NOOP "would press ..."; pointer on target -> `\r`; else one arrow
   toward it (one key per tick, closed loop). New Decision values
   `would-rate-limit-key`, `would-rate-limit-continue`. No dialog + pending
   window due + idle/work_idle/input empty/focus confirmed/quiet >= 30 s ->
   continue payload once. Near miss (dump contains the label but not
   recognised) -> one deduped noop line plus a bounded (16 KB) dump saved to
   `supervise-rate-limit-unrecognised.txt` so the first real incident becomes
   a fixture.
6. Tests in a new `tests/unit/supervise/test_rate_limit_dialog.py` (fixtures
   reconstructed from bundle strings; SAY SO in the test docstring), plus a
   JSON round-trip test for `screen_dump`.

## hooks-screen

Source is in-repo (`screen/`, one vendored crate `vt100`, offline locked build
via `bash screen/build.sh`; cargo is at `/root/.cargo/bin`). Not yet checked:
whether the `x86_64-unknown-linux-musl` target is installed (`rustup target list --installed` printed nothing visible). The build lands in the CALLER's
`untracked/screen-build/`; the live host looks under `/workspace/untracked/`,
so a worktree build does not fix the live container. Do not touch
`/workspace`'s copy; report the build command to the lead instead.
CHANGELOG lines 240 and 292 and `ccy.env` line 63 document it.

## Remaining work

All of "Design to implement", the lazy binary re-resolution, docs, PLAN.md
update for 00523 (tasks, Status In Progress), a release note under
`CLAUDE/UPGRADES/UNRELEASED/release-notes/`, targeted QA, commit and push.
