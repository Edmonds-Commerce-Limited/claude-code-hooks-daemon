# Plan 00146: Hard-block rhetorical continue questions in explained stops

**Status**: Complete
**Created**: 2026-07-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Single-Threaded

## Overview

Dogfooding evidence from the current session: the main agent repeatedly finished
an obvious, already-planned unit of work and stopped with a rhetorical
confirmation question ("Want me to build slice 2 next?", "Should I proceed?"),
each prefixed with `STOPPING BECAUSE:`. The `auto_continue_stop` handler
ALLOWED every one of these stops, even though its own guidance says
confirmation-question stops must be auto-continued.

Root cause: in `AutoContinueStopHandler.handle()`, Branch 2 (explicit stop
explanation, `STOPPING BECAUSE:` prefix -> ALLOW) returns before Branch 3
(confirmation-question detection -> DENY) ever runs. Prefixing a rhetorical
"should I continue?" with `STOPPING BECAUSE:` therefore bypasses the
confirmation guardrail entirely. Additionally, the `CONFIRMATION_PATTERNS`
verb set is too narrow — "want me to **build** slice 2 next?" and "want me to
**start** it?" match nothing.

Secondary failure: six identical dismissive advisories fired in one stop
interaction — correct detection, but advisory-only and unbounded repetition
makes it toothless noise. Root cause found during live probing: the NITPICK
variants (`handlers/nitpick/dismissive_language.py` and
`hedging_language.py`) emit one identical context line per matching pattern
per message with no dedupe; the Stop-event detector additionally re-emits the
identical advisory on every subsequent stop.

## Goals

- A stop whose current-turn assistant message contains a rhetorical
  continue/confirmation question is DENIED (force-continue) **even when
  prefixed `STOPPING BECAUSE:`**, with a firm, unambiguous block message.
- The confirmation-question detection runs on the same freshness-resolved
  current-turn message the `STOPPING BECAUSE:` check uses (no stale-text
  divergence between the two checks).
- Broaden the rhetorical-continue verb set to cover the observed misses
  (want me to start/build/implement/etc.) without over-blocking genuine
  either/or questions.
- Advisory dedupe: identical dismissive/hedging advisories are emitted once,
  not six times (nitpick: one line per category; Stop detector: one emission
  per session + phrase-set).

## Non-Goals

- No rewrite of the Stop dispatch or handler consolidation. The overlap
  between `auto_continue_stop` (blocking) and `dismissive_language_detector` /
  `hedging_language_detector` (advisory) is noted below but the advisory
  handlers keep their advisory role — only the spam is fixed.
- No giant regex zoo. A focused verb-group extension of the existing
  `CONFIRMATION_PATTERNS`, shared by both branches (DRY), is the whole
  pattern change.
- No blocking of genuine user-input stops ("Which of A, B, or C should we
  use?" style choice questions stay allowed).

## Context & Background

- Handler: `src/claude_code_hooks_daemon/handlers/stop/auto_continue_stop.py`
- Branch order in `handle()`: 1 QA-failure, 2 STOPPING BECAUSE (ALLOW,
  short-circuits), 2.5 tool_use_error, 3 confirmation question, 4 default.
- `_has_stop_explanation()` contains careful turn-freshness resolution
  (stale-tail detection + bounded re-read poll). The rhetorical check must
  reuse that resolved message, so the freshness logic is extracted into
  `_resolve_current_turn_message()` and both checks consume its result.
- CLAUDE.md and the handler's own `get_claude_md()` already forbid
  tautological confirmation questions; this plan makes the daemon enforce it.

## Tasks

### Phase 1: TDD — auto_continue_stop hard block

- [x] ✅ **Task 1.1**: RED — failing unit tests: `STOPPING BECAUSE:` +
  rhetorical continue question ("want me to build slice 2 next?",
  "Should I proceed?", "want me to start it?") -> DENY; genuine
  work-finished stop message -> ALLOW; genuine either/or choice question
  with `STOPPING BECAUSE: need user input` -> ALLOW.
- [x] ✅ **Task 1.2**: GREEN — extract `_resolve_current_turn_message()`,
  run confirmation detection independent of the has-reason branch, extend
  the confirmation verb set, add firm block reason constant.
- [x] ✅ **Task 1.3**: REFACTOR — keep `_has_stop_explanation()` as a thin
  wrapper; verify all existing auto_continue_stop tests still pass.

### Phase 2: TDD — advisory dedupe (dismissive + nitpick spam)

- [x] ✅ **Task 2.1**: RED — failing test: two consecutive Stop events with
  the same phrase set in the same session advise once; a changed phrase set
  or new session advises again.
- [x] ✅ **Task 2.2**: GREEN — in-memory last-advisory key
  (session id + phrase set) checked in `matches()`, recorded in `handle()`.
- [x] ✅ **Task 2.3**: The 6x-duplicate source found during live probing was
  the NITPICK variants (`handlers/nitpick/dismissive_language.py`,
  `hedging_language.py`): one identical context line per matching pattern
  per message. RED tests (one line per category max) + GREEN (category-set
  dedupe in `handle()`), both handlers.

### Phase 3: Verification

- [x] ✅ **Task 3.1**: Full QA 13/13 via `./scripts/qa/llm_qa.py all`.
- [x] ✅ **Task 3.2**: Daemon restart, status RUNNING.
- [x] ✅ **Task 3.3**: Live probe `.claude/hooks/stop` both ways: rhetorical
  explained stop -> blocked (exit 2, `decision: block`); clean work-finished
  stop -> allowed (exit 0); re-entry with block marker -> allowed (exit 0,
  no infinite re-entry).
- [x] ✅ **Task 3.4**: Commit referencing Plan 00146 (no push).

## Dependencies

- None.

## Technical Decisions

### Decision 1: Check rhetorical question inside Branch 2, not by reordering

**Context**: Branch 3 already detects confirmation questions but never runs
for explained stops.
**Options**: (a) move Branch 3 above Branch 2 wholesale; (b) run the
confirmation check on the resolved current-turn message inside Branch 2.
**Decision**: (b). Reordering wholesale would route rhetorical-question stops
through Branch 3's generic AUTO-CONTINUE message and would also change
behaviour for QA/tool-error interplay; checking within Branch 2 keeps the
freshness-resolved message consistent and lets the block message be firm and
specific ("the answer is obvious — get on with it").
**Date**: 2026-07-10

### Decision 2: One shared pattern list, extended verb group

**Context**: "want me to build/start X" was unmatched; both Branch 2 and
Branch 3 need the same notion of "rhetorical continue question".
**Decision**: Extend `CONFIRMATION_PATTERNS` via a shared `_CONTINUE_VERBS`
group (continue, proceed, start, begin, build, implement, execute, run,
launch, tackle, keep going, go ahead, move on/forward) used by every asker
form, and use the existing `_contains_confirmation_pattern()` from both
branches. The `"?" in text` requirement is kept, and no bare "should I"/"do"
verbs are matched, so genuine either/or choice questions ("which of A or B do
you prefer?") stay allowed.
**Date**: 2026-07-10

### Decision 3: Advisory-handler overlap noted, not consolidated

**Context**: `dismissive_language_detector` and `hedging_language_detector`
partially overlap `auto_continue_stop` (premature-stop language vs
confirmation questions). Consolidation would be a bigger refactor with its own
risk on the every-stop code path.
**Decision**: Keep responsibilities: `auto_continue_stop` blocks rhetorical
continue questions; the advisory detectors keep flagging softer language, but
deduped. Consolidation deferred; if the advisory handlers keep proving
toothless, fold their premature-stop signals into `auto_continue_stop` in a
follow-up plan.
**Date**: 2026-07-10

## Success Criteria

- [x] `STOPPING BECAUSE: ... want me to build X?` -> DENY with firm message
- [x] `STOPPING BECAUSE: work finished, QA green` -> ALLOW (clean stop)
- [x] Genuine either/or user-input question -> ALLOW
- [x] No infinite re-entry (re-entry guard untouched, live probe verified)
- [x] Identical dismissive advisory not repeated back to back
- [x] QA 13/13, daemon RUNNING after restart

## Risks & Mitigations

| Risk                                             | Impact | Probability | Mitigation                                                                                                                        |
| ------------------------------------------------ | ------ | ----------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Over-blocking genuine user-input stops           | High   | Medium      | Verb-scoped patterns (no bare "should I"), keep `?` requirement, explicit ALLOW test for either/or choice questions               |
| Infinite Stop re-entry loop from new DENY branch | High   | Low         | Re-entry guard in `matches()` untouched; live probe both ways; DENY reason instructs continuation, same as existing auto-continue |
| Breaking existing stale-tail freshness behaviour | Medium | Low         | Freshness logic extracted verbatim into `_resolve_current_turn_message()`; full existing test suite must stay green               |

## Notes & Updates

### 2026-07-10

- Plan scaffolded; dogfooding evidence from current session recorded in
  Overview.
- Recovery-cron advisory acknowledged: this executor runs as a subagent
  without Cron tools (no CronCreate available), so no recovery cron was
  created; execution is single-session and short-lived.
- RED confirmed: 7 failing tests (Branch 2 ALLOWed all rhetorical explained
  stops; no advisory dedupe). GREEN: 291 stop+nitpick tests pass; full QA
  13/13 (9627 tests, 95.4% coverage). Daemon restarted (RUNNING) and live
  probes verified: probe A (rhetorical explained stop) exit 2 with the hard
  block, probe B (clean stop) exit 0 allow, probe C (re-entry with block
  marker) exit 0 — no loop.
- During live probing, the real 6x-duplication source surfaced as the
  nitpick handlers (six identical "out of scope" lines in one advisory);
  fixed via per-category dedupe in both nitpick handlers (Task 2.3).
- Delivered in the single `Plan 00146:` commit that also moves this folder
  to `Completed/` (git history is authoritative for the hash).
