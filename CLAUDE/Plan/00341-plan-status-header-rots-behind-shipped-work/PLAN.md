# Plan 00341: plan status header rots behind shipped work

**Status**: Not Started
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

A plan document can carry `**Status**: Not Started` while the work it describes
is already in `main`. The cost is concrete: the next agent reads the header,
believes nothing has been done, and either redoes shipped work or files a
duplicate. Plan 00337 Task 1.3 asked whether this was a one-off; it is not, and
measuring it produced a sharper description than "plans get stale".

Two failures are involved, and they are independent. The **checkbox** is not
ticked when a task ships — that one sits adjacent to the work, so an executor
usually gets it right. The **header** is not flipped — a separate act that
nothing prompts, and the one that actually rots. Plan 00110 proves they are
independent: it has 8 ticked boxes and 24 unticked, so its executor maintained
the boxes across five phases of delivery, and the header still reads
`Not Started`.

The existing plan QA check `header-body-coherence` cannot see either case. It
fires only when the body claims *completion*, which its rule expresses as
`doc.tasks.all_checked` — every box ticked. A plan that is a quarter delivered
behind a `Not Started` header is entirely invisible to it.

## Evidence

Measured across the 22 live plans reading `Status: Not Started`, by
cross-referencing each against commits naming it that touch files outside
`CLAUDE/Plan/`:

- **Plan 00110** — 15 subject-leading commits spanning Phases 2 through 6
  (`efa00101` … `1764f935`), 8 boxes ticked, 24 unticked, header
  `Not Started`. `plan-qa --lint` on it reports one finding, and it is about
  document SIZE — the coherence check stays silent.
- **Plan 00314** — Tasks 1.1-1.3 delivered in `923fd583` with every box
  unticked and the header `Not Started`. Found and corrected by Plan 00337
  Phase 1; archived in `9def2583`.
- **Plan 00311** — checked and DISMISSED. It also has a commit touching `src/`,
  but the commit is an opportunistic docs-QA link fix credited to the plan, not
  delivery of any of its five tasks. A commit naming a plan is not evidence
  that plan advanced, and the naive version of this check would report it.

So: 2 confirmed in 22, and one near-miss that defines the false-positive shape.

## Goals

- `Not Started` becomes a falsifiable claim rather than a default that survives
  delivery.
- A partially-delivered plan behind a non-terminal header is surfaced by the
  existing plan QA machinery, not discovered by an agent tripping over it.
- Any git-informed check distinguishes a commit that DELIVERED a task from one
  that merely NAMED the plan.

## Non-Goals

- Auto-editing plan documents. The check reports; a human or agent decides
  whether the header or the boxes are wrong.
- Inferring WHICH task a commit delivered. That needs commit messages to carry
  a task ref reliably, which they do not; the check only needs to establish
  that delivery happened at all.
- Revisiting `header-body-coherence`'s existing all-checked branch. It is
  correct for what it covers; this plan widens the coverage, it does not
  replace the rule.
- Auditing the 22 live `Not Started` plans one by one. Fix the check; let the
  sweep produce the list.

## Tasks

### Phase 1: The cheap half — no git required

- [ ] ⬜ **Task 1.1**: `Not Started` plus **any** ticked box is already
  self-contradictory and needs no history to detect — a single tick falsifies
  "not started". Extend `header_body_coherence.py` so `NOT_STARTED` also fires
  on a non-zero checked count, keeping the existing all-checked branch for both
  non-terminal statuses. Distinct message per branch: "started" and "finished"
  are different corrections.
- [ ] ⬜ **Task 1.2**: TDD it. The regression that matters is the one this plan
  was filed from — a plan with SOME boxes ticked and a `Not Started` header
  must produce a finding, and the same document with `In Progress` must not.
- [ ] ⬜ **Task 1.3**: Run the sweep and read the result before shipping. If
  Task 1.1 lights up a large number of live plans at BLOCK level, the level for
  the new branch is the decision to make — a check whose first run has to be
  suppressed to get any work committed is worth nothing.

### Phase 2: The git-informed half

- [ ] ⬜ **Task 2.1**: Decide whether this belongs in plan QA at all. Every
  existing check reads the plan tree; this one needs `git log`, which is a new
  dependency and a per-run cost on a sweep over 45 plans. The session sweep
  (`plan_qa_sweep`) is the plausible home; the edit-time lint is not.
- [ ] ⬜ **Task 2.2**: Define "delivery commit" precisely enough to exclude
  Plan 00311's shape. Working definition from the evidence: a commit whose
  subject LEADS with `Plan NNNNN` **and** which touches a file outside the plan
  tree. Test it against all three evidence cases before relying on it.
- [ ] ⬜ **Task 2.3**: Check the adjacent existing rule first.
  `same-commit-plan-doc` already relates commits to plan documents, in the
  opposite direction (a commit naming a plan should also touch its PLAN.md).
  Establish whether this is an extension of that check or a new one, and record
  why.

### Phase 3: Reduce the chance of the rot in the first place

- [ ] ⬜ **Task 3.1**: The header is not flipped because nothing prompts it at
  the moment of delivery. Consider whether the commit gate — which already
  reads staged plan documents — can advise when a commit stages source changes
  alongside a `Not Started` PLAN.md from the same plan folder. Advisory, not
  block: a first commit that scaffolds a plan and starts work is legitimate.
- [ ] ⬜ **Task 3.2**: Record the outcome even if it is "no". A prompt at
  delivery time is the intervention most likely to work and also the most
  likely to be noisy; a reasoned rejection is a real result.

## Success Criteria

- [ ] A plan with a `Not Started` header and at least one ticked box is
  reported by plan QA, with a message that names which of the two fields is
  likely wrong.
- [ ] Plan 00110's current on-disk state produces a finding; the same document
  with an `In Progress` header does not.
- [ ] Plan 00311's shape produces no finding from any check this plan adds.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00341-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: Plan 00337 Task 1.3, which asked whether "shipped but reads Not
  Started" was systemic and required the answer to be filed separately rather
  than absorbed as scope creep.
- Dedupe scout checked 44 live plans. Plan 00144 (plan QA system) is the
  nearest neighbour and its own Non-Goals exclude spec-vs-code drift; it
  validates a plan document against itself and against the index, never
  against the history of what shipped.
