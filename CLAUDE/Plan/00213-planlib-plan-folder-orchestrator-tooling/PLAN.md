# Plan 00213: planlib plan folder orchestrator tooling

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

An upstream proposal arrived from a client project: promote its plan-folder
orchestrator tooling (`planlib`) into the hooks daemon, so that every project
using the plan workflow gets the same bash library rather than each one growing
its own. The proposal is a **generic extraction** of code already running in a
private infrastructure repository — project-specific facts were pulled out into
a configuration seam, and the library is presented complete and self-contained
rather than excerpted.

The proposal arrived verified rather than sketched, which is why it is worth
holding: the library was concatenated and checked with `bash -n` (asserting
empty stderr, because `bash -n` prints a diagnostic and still exits 0 on a
malformed conditional, so the exit code alone is not the signal), passed
`shellcheck -x -S style`, and had every called function cross-referenced against
every defined one. The `§5` skeletons are explicitly marked as templates
containing placeholders, not runnable code.

This plan exists so the proposal is TRACKED rather than lingering in
`untracked/`. It is deliberately **Not Started**: adopting a ~62KB bash library
into the daemon is a scope decision for a human, not something to begin because
the document happens to be well written.

## Goals

- Preserve the proposal as tracked source with its provenance and verification
  claims intact, so a later evaluation starts from the document rather than from
  a re-derivation.
- Reach an explicit accept / adapt / decline decision on promoting `planlib`
  into the daemon, recorded under Technical Decisions.
- If accepted, land it behind the daemon's existing conventions rather than as a
  foreign body: config-driven seams, the deploy-assets path already used by
  `mkplan.bash`, and QA coverage equal to the rest of the shell surface.

## Non-Goals

- Adopting the library as-is without review. It is a proposal, not a patch.
- Re-verifying the author's claims as a precondition for filing this plan — the
  verification table is recorded as an assertion to be checked at evaluation
  time, not as something this plan takes on trust or on faith.
- Any change to `mkplan.bash` or the plan workflow before a decision is made.

## Context & Background

Supporting documents in this folder (the EXTRACT remedy from Plan 00211 —
durable detail belongs in named files, not inflating PLAN.md):

- `PROPOSAL.md` — the current proposal (v2), self-contained and verified.
- `PROPOSAL-v1-SUPERSEDED.md` — the earlier draft, kept because the daemon's
  own convention is to preserve superseded versions rather than delete them.

## Tasks

### Phase 1: Evaluation

- [ ] ⬜ **Task 1.1**: Read `PROPOSAL.md` and independently re-run its stated
  verification (`bash -n` with an empty-stderr assertion, `shellcheck -x -S style`, defined-vs-called function cross-reference)
- [ ] ⬜ **Task 1.2**: Assess overlap with what the daemon already ships —
  `mkplan.bash`, `deploy-plan-workflow`, the `plan_qa` check catalogue — and
  identify what `planlib` adds beyond them
- [ ] ⬜ **Task 1.3**: Record an accept / adapt / decline decision with rationale
  under Technical Decisions

### Phase 2: Adoption (only if Task 1.3 accepts)

- [ ] ⬜ **Task 2.1**: Define the configuration seam in `.claude/hooks-daemon.yaml`
  and its schema validation
- [ ] ⬜ **Task 2.2**: Wire deployment through the existing idempotent
  plan-workflow asset deploy path
- [ ] ⬜ **Task 2.3**: Bring shell QA coverage up to the standard the rest of the
  shell surface is held to (`shell_audit`, `shellcheck`)
- [ ] ⬜ **Task 2.4**: Stage `config-changes` and `truth-changes` manifests so the
  feature does not ship dormant and undocumented

## Dependencies

- Related: Plan 00211 (plan-size guidance / supporting-docs concept) — this plan
  folder is itself an application of that plan's EXTRACT remedy.

## Success Criteria

- [ ] An explicit, recorded decision exists on whether `planlib` is adopted
- [ ] No proposal document remains in `untracked/`
- [ ] If adopted: QA passes, the daemon restarts cleanly, and the feature ships
  with upgrade manifests rather than silently

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00213-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Proposal filed out of `untracked/` and into tracked source at plan creation
