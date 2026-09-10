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

- No change to the definition of done ("merged into main").

**Superseded**: the original scope left the 11 `Worktree.core.md`
merge-approval instructions as an owner decision deferred to a later plan
(DBF section 4). The owner's ruling arrived before this plan closed:
enforce them behind a key, on the same shape as the plan-closing gate.
Phase 4 below does that; it is not a separate plan.

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

- [x] ✅ **Task 2.1**: `plan_workflow.close_requires_human_approval: bool`
  (default false) in `PlanWorkflowConfig`, threaded to the plan-workflow
  handlers; config-changes manifest in the holding area. (31112907)
- [x] ✅ **Task 2.2**: With the key true, a Write/Edit that flips a PLAN.md
  `**Status**` to Complete, Cancelled or Superseded is denied with a terse
  reason naming the key and the human's route (the human edits the header
  themselves, or runs `hooks-daemon approve-plan-close NNNNN`, which
  records a one-shot approval the next flip consumes). TDD, acceptance
  test, handler reference regenerated. (31112907: `plan_close_approval`,
  `R-PLAN-CLOSE-APPROVAL`)

### Phase 3: The fix (DBF clause 4)

- [x] ✅ **Task 3.1**: Rewrite the three `PlanWorkflow.core.md` instances
  (template and deployed copy): guideline 09 says a fully completed plan
  is closed and cites the key; the plan-creation "approval" steps describe
  the human's scope decision without prescribing an unenforced stop.
  (7dcd68b9)
- [x] ✅ **Task 3.2**: Sweep count for `PlanWorkflow.core.md` is 0; the
  `Worktree.core.md` count is recorded for the owner's decision. (7dcd68b9;
  journal 08:04)

### Phase 4: The Worktree.core.md fix (DBF clause 4, the deferred decision)

- [x] ✅ **Task 4.1**: `worktree.merge_to_main_requires_human_approval: bool`
  (default false) as `WorktreeConfig`, a real `Config` field path (so the
  docs-QA key resolver can confirm it); threaded through
  `HandlerRegistry.register_all` to every GIT-tagged handler the same way
  `plan_workflow` injects `_close_requires_human_approval`.
- [x] ✅ **Task 4.2**: `merge_to_main_approval` handler
  (`R-MERGE-TO-MAIN-APPROVAL`, priority 20, GIT-tagged, terminal): with the
  key true, a `git merge`/`gh pr merge` run in the MAIN checkout on its
  default branch is denied until a human runs
  `hooks-daemon approve-merge <branch>`, which records a one-shot marker
  under the daemon's untracked directory the next matching merge consumes.
  A linked worktree (child into parent) is never gated — checked via the
  `.git` entry, never guessed from the path. The command match reuses
  `GIT_INVOCATION` (the same evasion-hardened fragment `destructive_git`
  and `ancestry_preserving_merge` use) and blanks quoted literal spans
  (`utils.quoted_spans.blank_shell_literal_spans`) so a bare mention such
  as `echo 'git merge x'` is not read as a real merge. The one-shot marker
  logic is shared with `plan_close_approval` via a new
  `utils/one_shot_approval.py` (`OneShotApprovalStore`), and
  `plan_qa/close_approval.py` was refactored onto it rather than kept as a
  second copy. TDD, acceptance tests, handler reference, `approve-merge`
  CLI subcommand, evasion-suite classification.
- [x] ✅ **Task 4.3**: Rewrite every "human must approve"/"REQUIRES
  APPROVAL" instance in the `Worktree.core.md` TEMPLATE and the deployed
  copy (byte-identical) — the Merge Rules summary, Critical Rule 7, both
  worked examples (sequential and hierarchical-parallel), the Team Lead
  Workflow step, the shutdown sequence, the Common Pitfalls anti-pattern,
  the Verification Checklist, the Troubleshooting entry, the Quick
  Reference diagram and table, and the closing "Remember" bullet — so each
  describes the toggle instead of prescribing an unenforced stop.
  `CLAUDE/AgentTeam.md`'s parent-to-main merge instructions (Integration
  Phase, the worked walkthrough, the Gate Summary checklist) got the same
  treatment for consistency, though it sits outside the docs-QA corpus.
  `bin/hooks-daemon docs-qa --sweep` reports 0 `unenforced-approval-gate`
  findings across both core documents.

## Success Criteria

- [x] A commit that adds an unenforced human gate to a core document is
  denied by the docs-QA commit gate. (68c1510e)
- [x] With the key on, an agent cannot close a plan; with it off (the
  default), a fully completed plan closes as before. (31112907)
- [x] `PlanWorkflow.core.md` carries no unenforced approval gate. (7dcd68b9)
- [x] `Worktree.core.md` carries no unenforced approval gate; the sweep
  reports 0 across both core documents.
- [x] With `worktree.merge_to_main_requires_human_approval` on, a
  `git merge`/`gh pr merge` into main from the main checkout is denied
  until `hooks-daemon approve-merge <branch>`; with it off (the default),
  the parent-to-main merge happens once verification passes, as before.
- [x] Every release-bound consequence is in the pending-release holding
  area: a release-notes callout and a config-changes manifest. (31112907,
  7dcd68b9, Phase 4)

## Delivery & Milestones

- Milestone A — the net is committed red on the originating instance,
  before any fix. Delivered in 68c1510e.
- Milestone B — the gate exists behind its key. Delivered in 31112907:
  `plan_workflow.close_requires_human_approval`, the `plan_close_approval`
  handler and the `approve-plan-close` CLI subcommand.
- Milestone C — the plan workflow core document is in sync. Delivered in
  7dcd68b9; the sweep reports 0 instances in `PlanWorkflow.core.md` and 11
  in `Worktree.core.md`, which stay for the owner's decision.
- Milestone D — the worktree merge gate exists behind its key, and the
  worktree core document is in sync. `worktree.merge_to_main_requires_human_approval`,
  the `merge_to_main_approval` handler, the `approve-merge` CLI
  subcommand, and both copies of `Worktree.core.md` plus `AgentTeam.md`
  rewritten. Sweep reports 0 across both core documents.
