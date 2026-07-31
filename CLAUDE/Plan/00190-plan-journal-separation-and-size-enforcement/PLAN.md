# Plan 00190: PLAN-vs-JOURNAL Separation & Tiered Plan Size Enforcement

**Status**: In Progress
**Created**: 2026-07-31
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Agents conflate `PLAN.md` with `JOURNAL/`. They append narrative progress —
session logs, findings, dead-ends, pasted output — into the plan document
instead of the journal. The plan then grows monotonically and is never curated,
until it is too expensive to read and too tangled to trust. Locally the worst
offender is 57 KB; client projects report 100 KB+.

The root cause is **rule-bleed between two near-opposite rule-sets**. A journal
is append-only and unbounded; a plan document is curated and bounded. Applying
journal rules to a plan document produces exactly the observed failure. The
inverse bleed is also a hazard: applying plan rules to a journal invites an
agent to "tidy up" an append-only log and destroy the record.

This plan makes both contracts explicit, symmetric, and enforced — with tiered
size enforcement on plan documents (advise → strong warn → block), strict
file-scope demarcation so neither rule-set can leak onto the other file type,
and consistent guidance across every touch point. It deliberately reuses the
existing `plan_qa` surfaces rather than adding a parallel mechanism, and avoids
flooding context: one source of truth, thin pointers elsewhere.

## Context & Background

### The two contracts

| Axis                 | `JOURNAL/*.md`                            | plan-type files (`PLAN.md`, …) |
| -------------------- | ----------------------------------------- | ------------------------------ |
| **Write**            | append-only, never rewritten              | freely rewritten / curated     |
| **Growth**           | unbounded **by design**                   | bounded — lean, surgical       |
| **Size enforcement** | **never** size-limited                    | tiered advise → warn → block   |
| **History lives in** | the file itself                           | **git**, not the file body     |
| **Read**             | **never whole** — grep / tail / sub-agent | **read in full** for grounding |

The two axes are causally linked, which makes both rules self-justifying rather
than arbitrary hygiene:

- `PLAN.md` must stay lean **because** it is read in full for grounding every
  session. Its size limit is *derived from its read cost*.
- `JOURNAL/` may grow forever **because** it is never read whole. Unbounded
  growth is safe only under a bounded read discipline.

### Evidence: plans are edited as journals

A genuinely curated specification shows substantial deletions as resolved
material is condensed away. Measured `git log --numstat` churn shows deletions
near zero — these files are appended to, never curated:

| Plan                            | added | deleted | del/add |
| ------------------------------- | ----- | ------- | ------- |
| 00104 venv-resolver-dry         | 885   | 0       | 0.00    |
| 00188 hook-event-semantic-audit | 205   | 0       | 0.00    |
| 00135 event-driven-send-keys    | 751   | 37      | 0.05    |
| 00144 plan-qa-system            | 480   | 39      | 0.08    |
| 00100 venv-ssot-consolidation   | 723   | 130     | 0.18    |
| 00163 plan-journalling          | 525   | 94      | 0.18    |
| 00101 recap-stoppage            | 2214  | 1319    | 0.60    |

00101 is the sole outlier that was genuinely curated. Raw size is a *lagging*
indicator; the `del/add` ratio is a *leading* indicator of journal-drift.

### Two hazards the design must guard against

1. **Delete-instead-of-relocate.** A message that only says "your plan is too
   big" invites an agent to delete content to satisfy the check, destroying the
   record. Every size message must name `JOURNAL/` as the destination and state
   that the journal grows freely.
2. **Scope-dependent signals.** Dated headings, past-tense narrative and pasted
   tracebacks are *correct* journal content, and are only a defect signal when
   found in a plan document. Any content-shape detector needs an explicit
   file-scope predicate.

### Prior art in-repo

`CLAUDE/PlanJournalling.md` already states much of the write contract,
including the `Notes & Updates` → `JOURNAL/` migration, and Plan 00163 shipped
six advise-level journal checks. The gap is therefore **enforcement and reach**,
not authoring: the contract exists but is not demarcated, not size-enforced,
and not consistently reflected across touch points.

## Goals

- State both contracts **symmetrically and in one place**, so they cannot blur.
- Guarantee **file-scope demarcation**: journal rules apply only to journal
  files; plan rules apply only to plan-type files. Neither can leak.
- Enforce **tiered size limits on plan documents only** — advise, then strong
  warn, then block — at thresholds derived from read cost.
- Make the remediation path unambiguous: **relocate narrative to `JOURNAL/`**,
  never delete it.
- Establish the **read contract**: read plans whole; grep/tail/sub-agent the
  journal.
- Keep it **consistent and non-flooding**: reuse existing `plan_qa` surfaces,
  one SSoT with thin pointers, no duplicated prose.

## Non-Goals

- **No retroactive rewriting of existing plans.** Legacy oversized plans are
  grandfathered, not bulk-edited.
- **No size limits, staleness nags, or curation pressure on journals** — ever.
- **No new parallel enforcement mechanism.** Work through the existing
  `plan_qa` check catalogue and its three surfaces.
- No change to the plan numbering, archival, or README-index invariants
  (owned by Plan 00144).
- No mandated journalling cadence — journalling must never become a heartbeat.

## Tasks

### Phase 1: Research & Design

- [x] ✅ **Task 1.1**: Establish empirical churn evidence (`del/add` ratios)
- [x] ✅ **Task 1.2**: Dispatch research fan-out across architecture, docs,
  forensics, workflow design, and config conventions
- [ ] 🔄 **Task 1.3**: Consolidate agent findings into a fixed design
  - [ ] ⬜ Confirm whether one check can emit tiered severities
  - [ ] ⬜ Fix threshold values (bytes / lines / tokens per tier)
  - [ ] ⬜ Decide the read-time advisory surface (build vs document-only)
  - [ ] ⬜ Settle plan-type-file terminology and the shared path classifier

### Phase 2: Scope Demarcation

- [ ] ⬜ **Task 2.1**: Introduce a single SSoT file classifier (plan doc /
  journal file / template / neither) consulted by every check
- [ ] ⬜ **Task 2.2**: Audit and fix any mis-scoped existing check
- [ ] ⬜ **Task 2.3**: Regression tests asserting no rule crosses the boundary
  in either direction

### Phase 3: Tiered Size Enforcement

- [ ] ⬜ **Task 3.1**: TDD the tiered size check (plan documents only)
- [ ] ⬜ **Task 3.2**: Config block with named threshold constants (no magic
  values) and grandfathering for legacy plans
- [ ] ⬜ **Task 3.3**: Remediation messaging that names `JOURNAL/` as the
  destination and only recommends handler-permitted commands

### Phase 4: Documentation Consistency

- [ ] ⬜ **Task 4.1**: Place the symmetric two-axis contract in its SSoT and
  reduce every other touch point to a thin pointer
- [ ] ⬜ **Task 4.2**: Remove or rename plan-document wording that invites
  journal-style accumulation
- [ ] ⬜ **Task 4.3**: Align every handler `get_claude_md()` with the contract

### Phase 5: Verification

- [ ] ⬜ **Task 5.1**: Full QA suite passes
- [ ] ⬜ **Task 5.2**: Daemon restart verified RUNNING
- [ ] ⬜ **Task 5.3**: Dogfood — this plan stays under the advise threshold
- [ ] ⬜ **Task 5.4**: Config-changes / truth-changes manifests for release

## Dependencies

- Related: Plan 00144 (Plan QA System) — owns the check catalogue and surfaces
- Related: Plan 00163 (Plan Journalling) — owns `JOURNAL/` and its checks

## Success Criteria

- [ ] Both contracts stated symmetrically in one authoritative location
- [ ] No check applies to both plan documents and journal files
- [ ] Journals are provably exempt from every size and curation rule
- [ ] Plan documents exceeding the tiers advise, then warn, then block
- [ ] Every enforcement message names the relocate-to-`JOURNAL/` remediation
- [ ] No guidance recommends a command this daemon's own handlers block
- [ ] Full QA passes; daemon restarts RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00190-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan scaffolded, indexed, and research fan-out dispatched
