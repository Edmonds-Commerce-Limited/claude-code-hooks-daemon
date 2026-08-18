# Plan 00256: docs consistency round, found by the v3.54.0 release

**Status**: In Progress
**Created**: 2026-08-18
**Owner**: Claude (Opus 5)
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The v3.54.0 release ran its Step 7 documentation gate and its Step 10 code
review gate early, and both surfaced documentation defects rather than only
code ones. Separately, executing the pipeline exposed places where
`RELEASING.md` has drifted from the artifacts it governs — it quotes counts
that the generators no longer produce, and forbids something the generated
playbook now says is verified safe.

The release is HELD until this plan closes: the human's instruction was that
v3.54.0 ships once the docs are clear and consistent.

None of this is cosmetic. Every item below is a place where a document asserts
something that is not true of the tree it describes, and a reader acting on it
would do the wrong thing.

## Goals

- Every factual claim in the v3.54.0 release documents matches the code.
- `RELEASING.md` stops asserting counts and prohibitions the generated
  artifacts contradict, so the next release does not re-derive the same
  conflict by hand.
- Where a wrong number came from an upstream document, the upstream is
  corrected too, so the error cannot be re-copied.

## Non-Goals

- Not fixing the two CODE blockers found by the same review round. They are
  real and they also hold the release, but they are code, not docs, and are
  tracked separately. See Dependencies.
- Not rewriting `RELEASING.md` wholesale. Only the statements that are
  measurably untrue.

## Context & Background

Three independent sources fed this list: the Opus Step 7 gate, the Step 10
code-review gate, and the pipeline execution itself.

| #   | Document                                      | Wrong claim                                                                                      |
| --- | --------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 1   | `RELEASES/v3.54.0.md`                         | Points at `check-config-migrations` for the one change that command deliberately does not report |
| 2   | `RELEASES/v3.54.0.md`                         | Reduces the Plan 00255 fix to a naming bug, dropping the wrong-safety-verdict half               |
| 3   | `CHANGELOG.md` + `RELEASES/v3.54.0.md`        | "15 files bypassed the facade" — the guard's own scanner measures 24 spawns across 12 files      |
| 4   | `CLAUDE/UPGRADES/config-changes/v3.54.0.yaml` | `date: "UNRELEASED"` in a shipping manifest                                                      |
| 5   | `CLAUDE/Plan/Completed/00246-*/PLAN.md`       | Source of the wrong "Fifteen files" figure that items 3 propagated                               |
| 6   | `CLAUDE/development/RELEASING.md` Step 12     | Quotes "~65 BLOCKING + ~24 ADVISORY" tests; the generator emits 216                              |
| 7   | `CLAUDE/development/RELEASING.md` Step 12     | "Sub-agent testing is FORBIDDEN" vs the playbook marking 154 of 216 delegable as verified safe   |
| 8   | `CLAUDE/development/RELEASING.md` Step 3      | Lists `CLAUDE.md` as a file whose version must be bumped; it carries no version string           |

Items 6 and 7 are the "context rot" case specifically: `RELEASING.md` restates
values that a generator owns, and the restatement went stale. The file already
records this exact lesson about its own QA-check count ("it previously said 10
while the suite ran 13") — the same failure recurred two steps further down.

## Tasks

### Phase 1: The v3.54.0 release documents

- [ ] ⬜ **Task 1.1**: Fix the `check-config-migrations` pointer in
  `RELEASES/v3.54.0.md` so the reach change points at `check-truth-changes`,
  which is the command that actually reports it.
- [ ] ⬜ **Task 1.2**: Restore the safety half of the Plan 00255 entry in
  `RELEASES/v3.54.0.md` — a tag named after the default branch could make a
  branch holding unique commits be reported safe to delete.
- [ ] ⬜ **Task 1.3**: Replace the "15 files" figure in `CHANGELOG.md` and
  `RELEASES/v3.54.0.md` with the measured one, and state the guard's real
  scope (it walks all of `src/`, with one exemption).
- [ ] ⬜ **Task 1.4**: Set a real ISO date in
  `CLAUDE/UPGRADES/config-changes/v3.54.0.yaml`. Check whether the release
  flow should set this automatically, since v3.53.0 shipped with the same
  placeholder — a recurring escape, not a one-off.

### Phase 2: The upstream that produced a wrong number

- [ ] ⬜ **Task 2.1**: Correct the "Fifteen files" figure in Plan 00246's
  archived `PLAN.md`, or annotate it, so the next reader does not re-copy it.
  Editing an archived plan is normally discouraged — record the reasoning.

### Phase 3: RELEASING.md context rot

- [ ] ⬜ **Task 3.1**: Remove the hardcoded acceptance-test counts from Step
  12 and point at `generate-playbook` as the source of truth, exactly as Step
  8 already does for the QA check count.
- [ ] ⬜ **Task 3.2**: Resolve the sub-agent contradiction in Step 12. The
  playbook ships a per-test `Requires Main Thread` field and says delegation
  was verified experimentally; the prose forbids delegation outright, citing a
  v2.9.0 incident. Decide which governs, write it once, and delete the loser.
- [ ] ⬜ **Task 3.3**: Fix Step 3's file list — `CLAUDE.md` carries no version
  string, so bumping it is not a real instruction.
- [ ] ⬜ **Task 3.4**: Sweep the rest of `RELEASING.md` for the same shape: any
  restated count or list a generator owns.

## Dependencies

- Blocks: the v3.54.0 release. The human's condition is that it ships once the
  docs are clear and consistent.
- Related: the two CODE blockers from the same review round, which also hold
  the release — the `delete-branch` protected-ref ambiguity, and the QA suite
  failing whenever a release is in progress.

## Success Criteria

- [ ] No claim in the v3.54.0 release documents is contradicted by the code
- [ ] `RELEASING.md` restates no count a generator owns
- [ ] The sub-agent question has one answer, in one place
- [ ] QA green, daemon restart RUNNING

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes. Blow-by-blow log lives in JOURNAL/. -->

- Filed during the v3.54.0 release, from its own Step 7 and Step 10 gates.
