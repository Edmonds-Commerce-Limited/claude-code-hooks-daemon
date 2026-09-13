# Plan 00392: niggles ledger six

**Status**: In Progress
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The open ledger for small defects. Ledger five (00390) closed when its last
entry was resolved, and SOP is that the next niggle found opens a NEW ledger
rather than reopening an archived one — so this exists because a niggle was
found, not in anticipation of one.

A niggle is recorded **in the turn it is found**, before the work that surfaced
it continues. The rule exists because the alternative is reporting it in context
output, where it is read once and then lost when the window compacts. Every
entry names what was OBSERVED, not what was guessed.

Entries may be fixed here, or GRADUATED to their own plan when they turn out to
be larger than a niggle. Graduating is a success: the ledger's job is to make
sure nothing is dropped, not to force every fix into one plan.

## Goals

- Every small defect found while doing other work is recorded, with enough
  evidence that someone else could reproduce it.
- Each entry is either fixed here or graduated to a named plan — never dropped.

## Non-Goals

- Batching. An entry is appended the turn it is found; the ledger is never
  "caught up" later from memory.
- Large work. Anything needing its own design graduates to its own plan.

## Tasks

### Phase 1: Entries

- [x] ✅ **N1** — GRADUATED to [Plan 00388](../00388-failsafe-marker-wiped-by-other-crons-in-multi-cron-sessions/PLAN.md)
  (Tasks 2.4 and 2.5). The `issue-sdlc` cron has no no-op backoff, so a saturated
  backlog costs a full model turn every hour, indefinitely. The failsafe cron
  has TWO mechanisms for exactly this; the issue cron has none.

  **Observed** on an `issue-sdlc` tick: every one of the seven open issues
  carries `agent-needs-human`, so all three selection rules miss and the tick is
  a guaranteed no-op. It stays one until a human clears an issue or a new one is
  filed:

  ```text
  #14 #22 #23 #24 #31 #32 #33  — all [agent-triaged, agent-needs-human]
  rule 1 (agent-working > 2h):  no match
  rule 2 (unlabelled, oldest):  no match
  rule 3 (triaged, actionable): no match — every one is agent-needs-human
  ```

  **Why this is a defect and not a wish**: this repository already treats a
  wasted cron tick as a real cost and has built against it twice. The failsafe
  cron has `FailsafeCronBlockageSuppressorHandler` plus two rule IDs that exist
  solely to explain a dropped tick — `R-FAILSAFE-CRON-SUPPRESSED` (Plan 00298's
  `[awaiting-human]` marker) and `R-FAILSAFE-CRON-BACKED-OFF` (Plan 00337's
  cadence backoff). Searching the handler tree for any `issue-sdlc` equivalent
  returns nothing. The asymmetry is the finding: the same cost was judged worth
  engineering against for one cron and left unaddressed for the other.

  **Not the same as Plan 00388.** That plan is about the `[awaiting-human]`
  marker being CLEARED by other crons in a multi-cron session — a mechanism that
  exists and is defeated. This is a mechanism that was never built for this cron
  at all. They interact (00388's fix would make the marker work; this would give
  the issue cron its own reason to stand down) but neither subsumes the other.

  **Diagnosed, and it is why this graduated rather than being fixed here.**
  Suppressing this cron with the existing `[awaiting-human]` marker needs the
  handler to recognise an `issue-sdlc` tick as automated — and that is the exact
  question Plan 00388 is blocked on. The suppressor decides it at
  `failsafe_cron_blockage_suppressor.py:269`:

  ```python
  is_cron_prompt = isinstance(prompt, str) and CANONICAL_CRON_PROMPT_MARKER in prompt
  ```

  `CANONICAL_CRON_PROMPT_MARKER` is the literal `"FAILSAFE RECOVERY CHECK"`, so
  no other cron can ever satisfy it, and any prompt that fails it CLEARS the
  marker. The two defects are therefore one mechanism:

  - Fix 00388 alone → the marker survives, but still suppresses only the
    failsafe cron; this one keeps burning a turn an hour.
  - Fix this alone → impossible; the marker it depends on is wiped by this very
    cron before it can be read.

  Graduated rather than given its own plan because it adds a second CONSUMER of
  a ruling the owner already has to make, not a second decision. Folding it in
  means one ruling covers both crons instead of this resurfacing later.

## Success Criteria

- [x] Every entry above is either fixed with a regression test, or graduated to
  a named plan and that plan is linked from the entry. N1 graduated to Plan
  00388, Tasks 2.4 and 2.5.
- [x] No entry is closed on reasoning alone. N1 was not fixed, so what had to be
  proved was the DIAGNOSIS: the saturation was observed against the real label
  set (seven issues, all `agent-needs-human`, all three selection rules missing),
  and the dependency on Plan 00388 was read out of
  `failsafe_cron_blockage_suppressor.py:269` rather than inferred from the
  handler's docstring.
- [x] This plan has no release-bound consequences: no code changed. N1 was
  recorded and graduated, so nothing a client installs or runs is different.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Opened because ledger 00390 closed when its entries were resolved and a new
  niggle was found, per the SOP in `CLAUDE/core/PlanWorkflow.core.md`: "The next
  niggle found opens a NEW ledger. Never reopen a closed one."
- N1 was found by an `issue-sdlc` tick that correctly reported "no eligible
  issue". The tick was a success; what it exposed is that the same tick will
  keep succeeding identically, at full cost, every hour.
- **Close this ledger when its entries are resolved.** Do not hold it open as a
  standing fixture — that error is what kept ledger 00390 open after its work
  was finished.
