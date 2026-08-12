# Plan 00216: plan duplicate source detection

**Status**: Not Started
**Created**: 2026-08-12
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Nothing in the plan system warns an author that an existing plan already covers
the same source material. `plan_qa` enforces number collisions, index/folder
bijection, statistics recount and status coherence — all *structural* — and is
blind to two plans being about the same thing.

The cost is not hypothetical. Plan 00213 was filed for a `planlib` proposal
that Plan 00199 had already covered five days earlier. The duplicate was found
only because a human-driven session happened to notice and say so. By then an
evaluation agent had spent a large amount of context independently
re-deriving an assessment that 00199's `PROPOSAL-ASSESSMENT.md` already held,
and had independently arrived at the same scoping conclusion 00199 had already
recorded.

This is the DBF case (Core Standard 15) in its clearest form: the duplicate
plan is the symptom, and the bug worth fixing is the guard that could not see
it. Filing more carefully is not a fix — the next author has the same blind
spot, and the plan tree is now large enough (206 folders) that reading it
before filing is not a realistic precaution.

## Context & Background

The detection surface already exists. `plan_qa` parses every `PLAN.md` at
sweep time (SessionStart) and at commit time, so a rule has the whole tree in
hand without new machinery. The signal is cheap: a plan that is *about* an
external document almost always names it — a proposal filename, a report
filename, a GitHub issue number, or a supporting document it carries in its
own folder.

Credit: the gap was identified by a peer session while closing 00199, and
recorded in that plan's closing journal
(`CLAUDE/Plan/Cancelled/00199-hooks-daemon-plan-lib/`).

## Goals

- Warn at plan-creation time when a new plan cites a source document that an
  existing non-terminal plan already cites.
- Make the warning name the existing plan and the shared citation, so the
  author can merge, supersede, or consciously proceed.
- Keep it advisory. A false positive must never block plan creation.

## Non-Goals

- Semantic similarity or embedding comparison. The signal here is a shared
  literal citation, which is cheap, explainable, and has an obvious remedy.
  A fuzzy "these plans feel related" warning would be ignored within a week.
- Blocking. Two plans legitimately citing one document is normal — a proposal
  can spawn a research plan and an implementation plan on purpose.
- Retrospectively de-duplicating the existing tree. If the sweep surfaces
  historic pairs, that is a finding to triage, not a precondition.

## Tasks

### Phase 1: Establish the signal against real data

- [ ] ⬜ **Task 1.1**: Enumerate what existing plans actually cite — supporting
  `.md` filenames in their own folder, backticked paths to other plans, GitHub
  issue numbers, report filenames
- [ ] ⬜ **Task 1.2**: Run the candidate rule over the whole current tree and
  count how many pairs it flags, inspecting each by hand
- [ ] ⬜ **Task 1.3**: Confirm it would have flagged the 00199/00213 pair, and
  record the measured false-positive rate

### Phase 2: Implement as an advisory check

- [ ] ⬜ **Task 2.1**: TDD a `plan_qa` check that reports two NON-TERMINAL plans
  sharing a citation (terminal-status plans are excluded — a superseded plan
  citing the same document is the correct end state, not a finding)
- [ ] ⬜ **Task 2.2**: Wire into the sweep and the CLI, advisory severity only
- [ ] ⬜ **Task 2.3**: Make the finding name both plan numbers and the shared
  citation, with a remedy naming the three real options: merge, supersede one,
  or proceed deliberately

### Phase 3: Close the creation-time gap

- [ ] ⬜ **Task 3.1**: Decide whether `mkplan.bash` should surface the same
  check at creation, when the cost of merging is lowest — the session sweep
  only fires on the NEXT session, by which point work may have started
- [ ] ⬜ **Task 3.2**: Triage whatever historic pairs the first full sweep finds

## Dependencies

- Related: Plan 00213 / Plan 00199 — the duplication that motivated this.
- Related: Plan 00214, whose measure-before-blocking method Phase 1 follows.

## Success Criteria

- [ ] The check would have caught the 00199/00213 duplication at filing time
- [ ] Measured false-positive rate is recorded, and the check is advisory
- [ ] A finding names both plans and the shared citation, not just a count
- [ ] Historic pairs surfaced by the first sweep are triaged

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00216-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Gap identified while reconciling the 00199/00213 duplication
