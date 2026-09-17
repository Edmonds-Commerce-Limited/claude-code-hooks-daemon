# Plan 00427: journal timestamps agent authored and timezone naive

**Status**: In Progress
**Created**: 2026-09-17
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct
**GitHub Issue**: #45

## Overview

A journal entry's `HH:MM` is typed by the agent, and the check that judges it
reads a naive clock. Both halves are real; the reported mechanism is not the
one the code implements, and the difference decides which remedies are even
coherent.

`journal_entry_future_dated._now()` returns a bare `datetime.now()`, and the
entry's time is rebuilt as a naive `datetime` from the day-file name. The check
runs inside a `PreToolUse` handler, so that clock is the **daemon's**, not the
writing agent's. One clock therefore judges every writer, and the offset's
DIRECTION decides the outcome — measured, with a one-hour offset:

| daemon zone | agent stamp | ahead   | fires? |
| ----------- | ----------- | ------- | ------ |
| UTC         | BST `10:35` | +59 min | YES    |
| UTC         | UTC `09:35` | −1 min  | no     |
| BST         | BST `10:35` | −1 min  | no     |
| BST         | UTC `09:35` | −61 min | no     |

So the check is not blind; it is blind in exactly **one** direction, because
only the future direction is judged, deliberately (its docstring says so). An
agent running BEHIND the daemon's clock is never reported, and its entry lands
earlier than entries written before it — the ordering violation the issue
describes. An agent AHEAD of the daemon is reported for a timestamp that is
correct in its own zone: a second symptom, in the opposite direction, that the
report does not mention.

The deeper problem is that **no journal file records which zone any timestamp
was written in**. The grammar in `_JOURNAL_TEMPLATE_.md` says "local 24h", and
a cross-zone pair satisfies it exactly. 2207 entry headings across 316
day-files are already written under that grammar, none carrying a zone, and the
journal is append-only.

## THE RULING (owner, in session, 2026-09-17)

**No backward migration. A new system is established and used going forwards;
historic data is what it is.** Entries written by the new system carry a clear
sentinel so a reader can tell which ones it produced — deliberately minimal,
"no bloat, but something".

That answers the migration half outright and dissolves most of the
canonical-clock problem: a reader no longer has to guess what an old timestamp
meant, because the sentinel tells them which entries are trustworthy and the
absence of one marks the rest as legacy. The 2207 existing entries are not
touched, not reinterpreted, and not annotated.

**What the sentinel must NOT become**: a per-entry banner. The requirement is
one unambiguous marker, cheap to read and cheap to write. A design that adds a
line to every entry fails the owner's "no bloat" condition.

## The question this plan originally put to the owner

Every workable remedy needs a decision this plan must not make for itself:

**Which clock is canonical for a journal timestamp, and what happens to the
2207 entries already written under the current grammar?**

The issue proposes a `journal-entry.bash` scaffolder — the agent writes only
the body, the script stamps the time, normalises the zone, records it, and
appends. That is a coherent answer, and it is also a new mandated step in a
workflow agents perform constantly, plus a change to a template shipped to
every client. Both are product calls.

## Goals

- Record the measured mechanism, so the next reader does not re-derive it or
  inherit the report's version of it.
- Put the canonical-clock question in front of the owner with its options and
  their costs.

## Non-Goals

- **Choosing the canonical zone.** That is the decision this plan exists to
  surface.
- **Migrating existing day-files.** The journal is append-only; any migration
  is its own decision with its own blast radius.
- **Building the scaffolder on spec.** It is one candidate answer, not the
  agreed one, and it is a hypothesis to verify rather than a patch to apply.
- **Re-opening 00422 N3's three-rule deadlock.** Related (see below), but its
  remedies narrow an advisory; this is upstream prevention. They are
  orthogonal, confirmed by the dedupe scout.

## Options, with their consequences

1. **A scaffolder that stamps the entry** (the issue's proposal). Removes both
   failure modes at once — the zone question and the estimated-time question —
   because the agent stops supplying the value. Costs a new mandated step, a
   new script to deploy and version, and it only binds agents that use it
   unless something blocks hand-authored appends.
2. **Make the comparison zone-explicit and record the zone in the entry.**
   Smaller, and it fixes the check rather than the authoring. Does nothing
   about an estimated timestamp, which is the half that was observed twice in
   one session (69 minutes out, then 12).
3. **Normalise the grammar to UTC without new tooling.** Cheapest to state,
   and it leaves 2207 zoneless entries behind that a reader cannot reconcile,
   plus every client's existing journals.
4. **Nothing.** The cross-zone case needs two writers in two zones on one
   day-file. Real — it is what produced the report — but not frequent.

## Prior art the owner should weigh

Plan 00163 Decision 11 (a user decision, 2026-07-14) rejected "an auto-stamp
git key" as over-engineering. **That is not this proposal**: the rejected
mechanism was a ROLLOUT device for limiting journalling to new plans, not a
timestamp generator. It is recorded here because it is adjacent owner
territory, not because it settles the question — reading it as a prior
rejection would be wrong.

The scaffolder precedent the issue cites is real and does support its case:
hand-creating a plan folder is blocked in favour of `mkplan.bash`, for exactly
the "agents get this hand-performed step wrong" reason.

## Tasks

### Phase 1: the owner's decision

- [x] ✅ **Task 1.1**: RULED — see THE RULING above. No migration; new system
  forwards; a minimal sentinel distinguishes entries it wrote. The 2207 legacy
  entries stand as they are.

### Phase 2: build what was chosen

- [ ] ⬜ **Task 2.1**: Implement the chosen option, RED test first. The
  regression case is the cross-zone pair, not a single-writer entry: a test
  that pins one clock proves nothing about two.

- [ ] ⬜ **Task 2.2**: If the grammar or template changes, update
  `_JOURNAL_TEMPLATE_.md` (both copies — the deployed one under `install/` and
  this project's own) and stage a `truth-changes` entry, since a client's docs
  may assert the "local 24h" rule.

## Success Criteria

- [ ] ⬜ The canonical-clock question is answered by the owner, in writing.

- [ ] ⬜ Whatever is built is proven against a TWO-clock reproduction, and the
  opposite-direction symptom (a correct-in-its-own-zone entry being reported)
  is checked too, not just the silent direction.

- [ ] ⬜ The existing 2207 entries have a stated interpretation.

## Delivery & Milestones

- Filed from issue #45 after reproducing the timezone reading (59.99 minutes
  apart for one instant) and measuring the check's real comparison, which
  differs from the reported one.
