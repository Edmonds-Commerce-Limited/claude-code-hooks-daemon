# Plan 00341: plan status header rots behind shipped work

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: **Shipped.** `header_body_coherence.py` now has a second
  branch: `NOT_STARTED` plus a non-zero checked count. Distinct message AND
  distinct remediation per branch — telling the author of a half-delivered
  plan to mark it `Complete` would be actively wrong, so the split is not
  cosmetic.

  Branch ORDER turned out to matter and is now pinned by a test: a
  `Not Started` plan with EVERY box ticked satisfies both conditions, and "you
  finished this" is the more useful correction than "you started this", so the
  completion branch is evaluated first. One finding, never two.

- [x] ✅ **Task 1.2**: TDD'd, RED first. The matched pair the plan asked for —
  `Not Started` + partially checked produces a finding, the same body with
  `In Progress` does not. The second half is what stops the new branch firing
  on every healthy in-flight plan, which is how this change would have gone
  wrong.

- [x] ✅ **Task 1.3**: **Observed, and it matched the pre-measurement.** The
  sweep over the live tree produced exactly **one** BLOCK finding —
  `00110-python-discovery-dry-consolidation`, "8 of 60 boxes ticked" — and no
  other plan moved. BLOCK is therefore right with no staged rollout and no
  exemption list.

  Ran because a rule reasoned about is not a rule observed; the value here was
  confirmation rather than surprise, which is a real result and not a wasted
  step.

  00110's header flipped to `In Progress` — the check's own remediation — and
  its README index row updated to match. A second sweep is clean of BLOCK
  findings. (Journal 21:30.)

### Phase 2: The delivery-time half — re-scoped, because it already half exists

Task 2.3 was done first and collapsed this phase. `same-commit-plan-doc`
already detects the exact situation: it reads plan numbers out of the commit
message, sees whether `src/`/`tests/`/`config/` are staged, and reports when
that plan's `PLAN.md` is untouched. Applied to `923fd583` — the commit this
plan was filed from — it fires: the message names Plan 00314, `src/` and
`tests/` are staged, and only the JOURNAL is touched. **The detection was never
missing; the finding was `Level.ADVISE` and the plan stayed `Not Started` for
five days anyway.** (Journal 17:55.)

The `git log` dependency the original Phase 2 worried about therefore
disappears — the commit stage already holds the facts.

- [x] ✅ **Task 2.3**: **An extension of `same-commit-plan-doc`, not a new
  check.** Same stage, same inputs, same plan-number extraction; only the
  assertion changes.
- [ ] ⬜ **Task 2.1** (was "does this belong in plan QA"): **Level.** Decide
  whether `same-commit-plan-doc` should BLOCK rather than ADVISE. Not an
  obvious yes — a first commit that scaffolds a plan and starts work
  legitimately may not touch `PLAN.md`, so the false-positive shape is real
  and needs an answer before the level moves.
- [ ] ⬜ **Task 2.2** (was "define delivery commit"): **Assert on content, not
  on the file being touched.** The check passes for ANY edit to `PLAN.md`, so
  a commit that adds a paragraph and leaves the header at `Not Started`
  satisfies it today. The stronger property — status is not `Not Started` when
  code ships for that plan — costs nothing extra, because the staged blob is
  already in hand. Prove it against `923fd583` (must fire) and against a
  plan-scaffolding first commit (must not).

### Phase 3: Reduce the chance of the rot in the first place

- [ ] ⬜ **Task 3.1**: Phase 2's content assertion IS this intervention, moved
  to where the facts already are. What remains here is the question Phase 2
  cannot answer: whether an advisory is enough. The evidence says it was not —
  the advisory fired on `923fd583` and changed nothing — which is the argument
  for Task 2.1 choosing BLOCK.
- [ ] ⬜ **Task 3.2**: Record the outcome even if it is "no". A block at
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
