# Plan 00501 Phase 5: review fixes and adviser rulings (Opus)

Branch `worktree-501-phase5-supervisor`. The code head is `e6447538e` (one commit on top of `aa9875a19`). This
report is committed on top of it. Inputs: the code review (`261022-221007-code-reviewer-a7d9c94ee048f6eea.md`), the
reviewer's probe, and the adviser rulings (committed as `subagent-reports/261022-phase5-merge-advice-fable.md`).

## 1. Wrongly-typed fields escaped as TypeError (Important)

**Fix.** Added `_session_modes_member(value, allowed, name)` in `.claude/ccy/claude-supervise.py`. It checks
`isinstance(value, str)` before the membership test and raises `_SessionModesError("<name> <value!r> is unknown")`.
`mode`, `source` and `lifetime` now go through it. I audited every other field the parser reads:

- `reason` already checks `isinstance` before its dict lookup.
- `detail` already uses `isinstance`.
- `entered_at` and `expires_at` go through `_usage_pause_number`, which is type-checked.
- `version` is compared with `!=` and never hashed.
- `session_id` is `isinstance`-checked, and `modes` is `isinstance(list)`-checked.

None of those can raise. Each one now has a test that pins it anyway.

**Tests** (`tests/unit/supervise/test_session_modes_gate.py`):

- The malformed-file parametrize has 13 new cases: `mode=[]`, `mode={}`, `reason={}`, focus with `reason=[]`,
  `source={}`, `source=[]`, `lifetime=[]`, `lifetime={}`, `detail=[]`, `entered_at=[]`, `expires_at={}`,
  `version=[]`, `session_id=[]`.
- `TestUnreadableModesFile::test_a_wrongly_typed_field_fails_closed_inside_decide_once[mode|source|lifetime]` runs
  the case end to end through `decide_once`. The goal is withheld, the named `noop: session-modes file unreadable`
  line names the field, and the status line is at WARNING level.

**Red/green.**

- Red: 9 of these failed with `TypeError: unhashable type` (6 reader cases and 3 `decide_once` cases). The
  remaining new cases passed already, as the audit predicted.
- Green: all pass.
- The probe now prints three `SessionModesReading(... errors=(...))` lines and no `ESCAPED`. I deleted the probe
  directory.

## 2. Goal-clear storm while BLOCKED

**Fix.** I kept the review's smallest option: a bounded ceiling.

- `_MAX_BLOCKED_GOAL_CLEAR_INJECTIONS = 3 * _MAX_GOAL_CLEAR_INJECTIONS` (15).
- In `decide_once`, a BLOCKED clear is exempt from the cap of 5 but is refused at this ceiling with
  `noop: goal clear ceiling reached while BLOCKED`.
- Each failed delete is still logged by `_consume_signal` as `warning: could not consume ...`, so the failure stays
  loud.
- I chose a ceiling over tracking which triggers failed to delete. That would need new machine state carried across
  the worker/host boundary, and this change touches only one branch.

**Tests.**

- `test_blocked_clears_have_a_bounded_ceiling`: at the ceiling, the clear is refused with the named noop.
- `test_an_undeletable_clear_stops_at_the_ceiling`: `Path.unlink` always raises. The test loops `decide_once`,
  `_consume_signal` and `_apply_post_injection_bookkeeping`. It asserts exactly 15 clears are typed, then the
  ceiling noop, and one consume warning per typed clear.

**Red/green.** Red: both failed with `AttributeError` because the ceiling did not exist yet. Without it the loop
would type all 25 iterations. Green: both pass. The existing `test_the_cap_does_not_refuse_a_blocked_clear` (count
cap+3) still passes.

## 3. Documentation

`CLAUDE/development/CcySupervisor.md`, "Session modes" section:

- A corrupt or wrongly-typed file keeps the session BLOCKED until the daemon renames it aside on its next registry
  load. A human prompt does not clear it, and the status-line WARNING is how an operator sees it.
- The Task 5.2 paragraph now documents the BLOCKED ceiling and its noop line.

## 4. Adviser Q2 and Q3

- **PLAN.md Goals.** "The ccy supervisor injects no goals or prompts." is replaced with the ruling's wording: no goal
  and no session-actions directive under focus, because the daemon writes neither signal. Post-compact `continue`
  and standing-auth are unaffected.
- **Task 7.1.** It now says to carry that sentence into the session-modes docs, and that `status-line-explained`
  must name the modes-file WARNING text (Q3).
- **Ruling file.** Committed at the path above.

## Release note

023 is amended with one clause: the ceiling of fifteen per process while blocked. This is user-visible, because a
blocked clear is no longer unbounded. The TypeError fix needs no note, since 023 already says an unreadable file
withholds prompts and warns.

## QA

- `tests/unit/supervise/`: 1515 passed, 1 skipped (venv python).
- Targeted QA on the clean committed tree at `e6447538e27b9808290bf30a1fd003a6d467a5df`:
  `llm_qa.py changed --range 6ac377288..HEAD --allow-unmapped` returned `QA: 41/41 PASSED`, with no `❌` lines.

Head (code): `e6447538e`. Nothing was merged, the daemon was not restarted, and the live supervisor and the main
checkout's `.claude/ccy/` were not touched.
