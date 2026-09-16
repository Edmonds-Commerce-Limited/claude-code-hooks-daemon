# Plan 00422: niggles ledger fifteen

**Status**: Not Started
**Created**: 2026-09-16
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

The rolling ledger for defects found in passing. Ledger fourteen
([00419](../Completed/00419-niggles-ledger-fourteen/PLAN.md)) closed with eleven of its
fifteen entries terminal. The other four are re-filed here rather than counted
as terminal, because nothing downstream re-reads a closed plan: an unresolved
entry left inside an archived ledger is indistinguishable from a resolved one
to everybody except the person who wrote it.

So this ledger opens with four entries already in it, and collects the rest as
they are found. Their diagnoses are not reopened — what is inherited is the
unfinished remedy, not the finding.

**One of the four carries a class that now has three sightings**, and naming it
is a goal of this plan rather than a footnote in it. 00419's N3 (the two
plan-close gates), N12 (the three journal rules) and N13 (a declared cron that
cannot be paused for one session) are the same defect wearing three costumes: a
guard that is RIGHT about the state it judges and WRONG about the moment it
judges it. Three is a pattern. A ledger that meets it a fourth time and files it
as a fresh niggle would be repeating exactly the failure a ledger exists to
catch.

## Goals

- Record each niggle with enough evidence that someone else can reproduce it.
- Resolve each entry to a terminal state: fixed, graduated to its own plan, or
  dismissed as not-a-defect with the reasoning kept.
- Carry the four inherited entries to a terminal state rather than re-filing
  them onward a second time. An entry that crosses two ledgers unchanged is
  evidence that a ledger is the wrong container for it, and the answer then is
  to graduate it to its own numbered plan.
- Recognise the fourth sighting of the "right about the state, wrong about the
  moment" class as that class, instead of as a new finding.

## Non-Goals

- **Becoming a feature plan.** A niggle that needs design graduates to its own
  numbered plan and leaves a pointer here.
- **Re-deciding the inherited four.** 00419 assessed each of them and its
  reasoning stands; this plan owns their remedies, not their verdicts.

## Niggles

Full write-ups are in [NIGGLES.md](NIGGLES.md). One line each here so the
ledger's shape is readable without opening it:

| #   | Verdict                                                               | Origin                                                             | Status                                                  |
| --- | --------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------- |
| N1  | the `Priority` constants are not the numbers a fresh install ships    | [00419 N8](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md)  | ⬜ Open — remedy recorded, owner-gated, unbuilt         |
| N2  | the linter runs on gitignored scratch output                          | [00419 N11](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md) | ⬜ Open — remedy chosen and un-gated, nobody built it   |
| N3  | a committed future-dated entry makes the journal uncorrectable        | [00419 N12](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md) | ⬜ Open — remedies recorded, none chosen; advisory live |
| N4  | a cron cannot be both cancelled for a session and declared in config  | [00419 N13](../Completed/00419-niggles-ledger-fourteen/NIGGLES.md) | ⬜ Open — remedy recorded, owner-gated, unbuilt         |
| N5  | the v3.65.0 release reviews' NON-defects had no durable home          | the v3.65.0 release reviews                                        | ⬜ Open — evidence now tracked, twelve rows unworked    |
| N6  | a worktree cannot run the acceptance gates, and says the wrong reason | Plan 00424                                                         | ⬜ Open — two faults measured, remedies 1-3 un-gated    |

## Tasks

### Phase 1: the four inherited entries

- [ ] ⬜ **Task 1.1**: N1 — put the owner question that gates it, and only that
  question, in front of the owner: does a template-versus-constants consistency
  test get to fail loudly across the WHOLE template, or only across the
  `status_line` block where the divergence was found? The divergence itself is
  established and needs no further investigation.

- [ ] ⬜ **Task 1.2**: N2 — build remedy (1): exclude `untracked/` from
  `lint_on_edit`, RED first, so a scratch probe stops being linted while every
  file that can reach history still is. Un-gated; it has simply never been done.

- [ ] ⬜ **Task 1.3**: N3 — choose between teaching `journal-entry-ordering`
  about entries the file itself flags as future-dated, and giving a correction
  entry its own grammar. Both narrow an advisory that fires on a state the other
  two journal rules force into existence; neither weakens a gate. The existing
  finding against 00419's day-file is the regression case, and it cannot be
  cleared by editing that file.

- [ ] ⬜ **Task 1.4**: N4 — put the owner question in front of the owner: may a
  session suppress a cron the project declared, and if so through what recorded,
  expiring marker? Until that is answered, cancelling a declared cron for one
  session has no legal spelling.

- [ ] ⬜ **Task 1.5**: The class, named once rather than three times. N4, and
  00419's N3 and N12, are one shape: a guard right about the state and wrong
  about the moment. Write it up where a handler author will meet it — the
  candidate home is `CLAUDE/HANDLER_DEVELOPMENT.md`, beside the stage-selection
  guidance, since 00419 N3's remedy was a stage move and not a relaxation.

### Phase 2: the release-review carry-over

- [ ] ⬜ **Task 2.1**: N5 — work the twelve-row table in
  [NIGGLES.md](NIGGLES.md). Rows (a), (d) and (f) are documentation or test
  corrections needing no decision; (a) first, because it is a live trap for the
  next person to add a Stop handler.

- [ ] ⬜ **Task 2.2**: N5 remedy (2), owner-gated — decide whether a review
  dispatch should default to a TRACKED report destination, so a reviewer's
  evidence lands where git can see it without the coordinator remembering.
  `dispatch_declaration` currently recommends the gitignored path.

## Success Criteria

- [ ] ⬜ Each of the four inherited entries reaches a terminal state IN THIS
  LEDGER — fixed with a RED-first test, determined from the record, or graduated
  to its own numbered plan. Re-filing any of them into ledger sixteen is a
  failure of this criterion, not a way of satisfying it.

- [ ] ⬜ **Assessed when this ledger closes, not before**: every entry is
  terminal by the same test. Open while this is the current ledger, because a
  rolling ledger exists to keep collecting.

- [ ] ⬜ Every release-bound consequence is in the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/`) before the status flips, or this criterion
  says explicitly that the plan has none.

## Delivery & Milestones

- Opened because ledger fourteen closed with four entries that were not
  terminal. The house precedent is 00413, which graduated its unresolved entries
  to numbered plans rather than counting them; these four are a ledger's worth of
  work on their own, so they get a ledger.
