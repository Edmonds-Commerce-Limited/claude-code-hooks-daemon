# Plan 00367: deployed docs in sync with daemon workflow

**Status**: In Progress
**Created**: 2026-09-10
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The daemon-owned `PlanWorkflow.core.md`, deployed verbatim into every
project, told every agent to "ask user for approval before marking plan
complete". Nothing in the daemon enforces that gate; everything the daemon
does enforce (the holding-area criterion, the terminal-placement hint,
archive atomicity, the supervisor's "work until complete" goal) drives an
agent straight through to Complete. Three plans were closed in one session
without asking, and the owner's ruling was that human approval for closing
plans "is just going to lead to lots of plans kept open for no good reason":
a fully completed plan can be closed, and deployed docs MUST be in sync with
the daemon's intended workflow.

That is a class, not an instance, and it is handled Defence Before Fix
(canonical source <https://defence-before-fix.github.io/>, now vendored and
recorded in `CLAUDE/CodeLifecycle/Bugs.md`). The net is the docs-QA check
`unenforced-approval-gate`: a core document may only prescribe a human
approval gate when the same paragraph names, in backticks, the daemon config
key that enforces it. The sweep found 14 instances: 3 in
`PlanWorkflow.core.md` and 11 in `Worktree.core.md` (the parent-to-main
merge approval). The plan-closing gate becomes a real, configurable one:
`plan_workflow.close_requires_human_approval`, default off.

## Goals

- The check `unenforced-approval-gate` blocks a NEW unenforced human gate
  in a core document at edit and commit time, advises on pre-existing
  ones in the sweep, and is documented as R14 of the documentation
  strategy.
- `plan_workflow.close_requires_human_approval` (default `false`) exists;
  when `true` the daemon denies an agent's flip of a PLAN.md to a terminal
  status and names how a human closes it.
- `PlanWorkflow.core.md` says a fully completed plan is closed, cites the
  key for the opt-in gate, and carries no other unenforced approval gate.
- The DBF canonical source is recorded in tracked docs, and the stale
  "CLAUDE.md Standard 15" pointers in LESSONS.md resolve again.

## Non-Goals

- No decision here on the 11 `Worktree.core.md` merge-approval
  instructions: enforce them behind a key or delete them is the owner's
  call (DBF section 4), recorded as known instances until made.
- No change to the definition of done ("merged into main").

## Tasks

### Phase 1: The net (DBF clauses 1 to 3, 5 and 6)

- [x] ✅ **Task 1.1**: Class attributed and swept by two techniques (grep of
  the templates and deployed core docs; grep of handler guidance strings).
- [x] ✅ **Task 1.2**: `docs_qa/checks/unenforced_approval_gate.py` with
  tests; red on the originating line 1032 of the plan workflow core doc;
  sweep count 14 recorded in the journal.
- [x] ✅ **Task 1.3**: R14 and the enforcement-table row in both copies of
  `DocumentationStrategy.core.md`; the sweep handler's check list; DBF
  section in `Bugs.md`; LESSONS.md pointers; DBF pages vendored.

### Phase 2: The gate

- [ ] ⬜ **Task 2.1**: `plan_workflow.close_requires_human_approval: bool`
  (default false) in `PlanWorkflowConfig`, threaded to the plan-workflow
  handlers; config-changes manifest in the holding area.
- [ ] ⬜ **Task 2.2**: With the key true, a Write/Edit that flips a PLAN.md
  `**Status**` to Complete, Cancelled or Superseded is denied with a terse
  reason naming the key and the human's route (the human edits the header
  themselves, or runs `hooks-daemon approve-plan-close NNNNN`, which
  records a one-shot approval the next flip consumes). TDD, acceptance
  test, handler reference regenerated.

### Phase 3: The fix (DBF clause 4)

- [ ] ⬜ **Task 3.1**: Rewrite the three `PlanWorkflow.core.md` instances
  (template and deployed copy): guideline 09 says a fully completed plan
  is closed and cites the key; the plan-creation "approval" steps describe
  the human's scope decision without prescribing an unenforced stop.
- [ ] ⬜ **Task 3.2**: Sweep count for `PlanWorkflow.core.md` is 0; the
  `Worktree.core.md` count is recorded for the owner's decision.

## Success Criteria

- [ ] A commit that adds an unenforced human gate to a core document is
  denied by the docs-QA commit gate.
- [ ] With the key on, an agent cannot close a plan; with it off (the
  default), a fully completed plan closes as before.
- [ ] `PlanWorkflow.core.md` carries no unenforced approval gate.
- [ ] Every release-bound consequence is in the pending-release holding
  area: a release-notes callout and a config-changes manifest.

## Delivery & Milestones

- Milestone A — the net is committed red on the originating instance,
  before any fix.
- Milestone B — the gate exists behind its key.
- Milestone C — the plan workflow core document is in sync.
