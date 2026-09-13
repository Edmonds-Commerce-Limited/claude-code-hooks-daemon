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

- [ ] ⬜ **N1**: The `issue-sdlc` cron has no no-op backoff, so a saturated
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

  **Not yet diagnosed to a fix.** The cheap version is a cadence backoff
  mirroring Plan 00337. The more truthful version is that the loop can KNOW it is
  saturated — the selection rules are evaluated against labels it already reads —
  so it could stand down until the label set changes rather than guessing from a
  timer. Which of those is right is design, so this entry may well graduate.

## Success Criteria

- [ ] Every entry above is either fixed with a regression test, or graduated to
  a named plan and that plan is linked from the entry.
- [ ] No entry is closed on reasoning alone — each fix is proved against the
  case that was actually observed.
- [ ] Every release-bound consequence is in the pending-release holding area, or
  this plan records why it has none.
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
