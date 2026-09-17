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
- ~~**Building the scaffolder on spec.**~~ SUPERSEDED by the ruling: option 1
  is chosen and is being built.
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

## The design the ruling implies

Option 1 is chosen. These decisions follow from the ruling and from the
existing deployment architecture; they are the spec to build against.

**D1 — the sentinel lives in the DAY-FILE PREAMBLE, one line per file.** Not
per entry. The owner's condition is "no bloat, but something", and a per-entry
marker fails it — it would add a line to every one of thousands of entries. One
line at the top of a day-file states that the file's entries were written by
the scaffolder, and in which zone.

This also lands the "no migration" ruling for free, with no work: day-files are
created fresh each day, so new files carry the marker and the 2207 legacy
entries simply do not. **Absence of the sentinel IS the legacy marker.**
Nothing old is touched, rewritten or annotated.

**D2 — the script reads the clock; the agent never supplies a time.** This is
the half that fixes estimation, which was observed twice in one session (69
minutes out, then 12). An agent that cannot type a timestamp cannot guess one.

**D3 — normalise to UTC, and record the zone in the sentinel.** A timestamp
whose zone is written down is reconcilable by any later reader; that is the
property the current grammar lacks, and it is what makes two writers in two
zones safe rather than silently an hour apart.

**D4 — append mechanically, never rewrite.** The append-only rule stops being
a convention an agent must remember and becomes a property of the only
supported write path.

**D5 — validate the category and the ref before the entry lands.** The grammar
already names the legal categories; a scaffolder that accepts anything makes
the grammar advisory.

**D6 — EXTEND `mkplan.bash` rather than adding a sibling script** (owner's
suggestion, and the code agrees). Checked before adopting: `mkplan.bash`
already owns every piece this needs — it reads the clock itself
(`date +%H:%M`), holds `_JOURNAL_TEMPLATE_.md` and its `{{DATE}}`/`{{TIME}}`
placeholders, creates `JOURNAL/`, and writes the first day-file. A new script
would have duplicated all of it and added a second deployed asset to version
and drift-check.

Interface: an explicit flag, **not** a subcommand —
`mkplan.bash --journal <plan-number> <category> <body-file> [--ref R] [--title T]`.
A bare `mkplan.bash journal` would be ambiguous, because `journal` is a legal
plan name under the existing kebab validation; a leading `-` never is.

**D6a — the journal path must NOT touch the plan counter.** This is the hazard
the merge introduces and the one thing to get right: `mkplan.bash` takes an
exclusive lock on the plan dir and advances
`hooksdaemon.latestPlanNumber`. A journal append happens many times a day and
must do NEITHER. Two operations with different lifecycles now share a file, so
the counter path and the journal path have to be provably separate — a journal
append that advanced the counter would burn plan numbers silently, which is
exactly the class `counter_sanity` exists to catch after the fact.

**Explicitly NOT in this plan**: blocking hand-authored journal appends. That
is a separate, larger decision — it would make the scaffolder mandatory rather
than merely available, and the ruling did not ask for it. Worth noting so the
gap is deliberate and visible: until such a gate exists, a `Write` or a heredoc
can still append an unsentinelled entry to a sentinelled file.

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

- [ ] ⬜ **Task 2.1**: `journal-entry.bash` per D1–D5, RED test first. The
  regression case is the cross-zone pair, not a single-writer entry: a test
  that pins one clock proves nothing about two. Prove the append-only property
  by trying to violate it, not by observing that one append worked.

- [ ] ⬜ **Task 2.2**: Extend `mkplan.bash` per D6 — both copies, the bundled
  template under `install/templates/` and this project's deployed one, which
  must stay byte-identical or the drift checker fires. Pin D6a with a test that
  asserts a journal append leaves `hooksdaemon.latestPlanNumber` UNCHANGED.

- [ ] ⬜ **Task 2.3**: `_JOURNAL_TEMPLATE_.md` (both copies — the bundled one
  under `install/templates/` and this project's own) gains the sentinel line,
  and the grammar text stops saying a bare "local 24h". Stage a
  `truth-changes` entry: a client's own docs may assert the old rule.

- [x] ✅ **Task 2.1**: SUPERSEDED by D6 — no sibling script was built; the
  scaffolder is a flag on `mkplan.bash`. Its RED-first tests live in
  `tests/unit/scripts/test_mkplan_journal.py` (20 passing), including the
  two-clock regression and an append-only property proven by attempting a
  violation.

- [x] ✅ **Task 2.2**: `mkplan.bash` extended per D6, both copies byte-identical
  (checked by hash before merge). D6a pinned by
  `TestD6aCounterIsolation` — the counter is unchanged, an unset counter stays
  unset, and no plan-dir lock is taken.

- [x] ✅ **Task 2.3**: Both `_JOURNAL_TEMPLATE_.md` copies carry the sentinel and
  the grammar no longer says a bare "local 24h"; the `truth-changes` entry is
  staged as `CLAUDE/UPGRADES/UNRELEASED/truth-changes/v3.66.0.yaml`.

- [x] ✅ **Task 2.4**: Release note staged —
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/04-mkplan-journal-flag-stamps-utc-timestamps.md`.

### Phase 3: the reader must use the same clock as the writer

Phase 2 shipped a correct writer and left the check that judges it reading a
naive LOCAL clock, so a UTC-stamped entry looks hours into the future on any
host west of UTC. Measured across six zones at one instant (see JOURNAL):
`America/New_York` +239 minutes, `America/Los_Angeles` +419, against a
30-minute tolerance. This is not the pre-existing rare cross-zone case — it is
deterministic for a whole class of hosts, and it fires on correct data.

- [x] ✅ **Task 3.1**: RED first — `TestSentinelledFilesAreJudgedInUtc` failed
  with `AttributeError: ... has no attribute '_utc_now'`. Its three cases pin a
  host four hours west of UTC: a sentinelled file is silent, a genuinely future
  UTC entry is still reported, and a legacy file is still judged locally — that
  last one with the two clocks pinned to DISAGREE about the verdict, so it
  proves which clock was used rather than merely passing.

- [x] ✅ **Task 3.2**: `journal_entry_future_dated` chooses its clock from the
  day-file: sentinel present ⇒ UTC; sentinel absent ⇒ the existing local clock,
  because a legacy file's times really are local. This is the sentinel earning
  its keep rather than being merely informational, and it needs no migration.

- [x] ✅ **Task 3.3**: Pin the sentinel across its copies —
  `tests/unit/scripts/test_journal_sentinel_sync.py`. Drift here fails SILENTLY
  (the check just reverts to the local clock), so the guard was shown firing on
  three realistic drifts — a rewording, a zone swap, and a deleted line — with
  the control passing.

- [x] ✅ **Task 3.4**: Release note, and a correction to Task 2.4's note, which
  claimed Phase 2 alone closed the cross-zone symptom.

## Success Criteria

- [x] ✅ The canonical-clock question is answered by the owner, in writing —
  see THE RULING. No migration; sentinel marks what the new system wrote.

- [x] ✅ A day-file the scaffolder created carries exactly ONE sentinel, in the
  preamble, and an entry costs no extra lines — counted, not opined, by
  `TestSentinel`: one on a fresh file, none added by a second append that day.

- [x] ✅ An agent cannot supply a timestamp through the supported path, proven
  by trying — `test_does_not_accept_a_time_argument_at_all`.

- [x] ✅ Whatever is built is proven against a TWO-clock reproduction
  (`TestUtcCrossZoneRegression`, both offset directions), and the
  opposite-direction symptom was checked too — which is what found the Phase 3
  defect, so the criterion earned its place rather than being ticked off. It is
  now pinned by `TestSentinelledFilesAreJudgedInUtc` from a host west of UTC,
  the direction that had no coverage at all.

- [x] ✅ The existing 2207 entries have a stated interpretation: they are
  legacy, untouched, and the ABSENCE of a sentinel is what says so.

## Delivery & Milestones

- Filed from issue #45 after reproducing the timezone reading (59.99 minutes
  apart for one instant) and measuring the check's real comparison, which
  differs from the reported one.
