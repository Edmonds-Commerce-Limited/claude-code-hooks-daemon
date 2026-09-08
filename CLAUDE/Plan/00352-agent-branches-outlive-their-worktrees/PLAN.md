# Plan 00352: agent branches outlive their worktrees

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

`worktree-reap` (Plan 00349) enumerates candidates from `git worktree list`, so
the only branch it can ever see is one that still has a worktree attached. A
branch whose worktree has already gone — removed by Plan 00188's
`WorktreeRemove` handler, by a manual `git worktree remove`, or by a `prune`
after the directory was deleted — is invisible to it and survives forever.

This is not hypothetical. Reaping the 21 accumulated worktrees (Plan 00349 Task
3.3) removed 15 worktrees and their 15 branches and left **9** `agent-*`
branches behind. Six belong to the worktrees the predicate deliberately
refuses. The other three — `agent-a4ff553e443d90fc7-0b00a249`,
`agent-a88580597e044ef36-d1a957af`, `agent-a919dc7e0a2315615-f3d60e5a` — have no
worktree at all, appear nowhere in that reap's output, and are each **0 commits
ahead of `main`**. They predate the reap.

The cost is small and the same shape as Plan 00349's: a branch listing
dominated by dead entries makes a live agent branch hard to spot. It differs in
one useful way, though — an orphaned branch has no working tree, so there is no
uncommitted state to lose, and `git branch -d` already refuses anything not
fully merged. The safety argument is therefore much simpler than the worktree
case, which is precisely why it should not be smuggled into the worktree
reaper's predicate: the two have different risk profiles and deserve separate
decisions.

## Goals

- An `agent-*` branch with no worktree is surfaced, with whether it is fully
  merged into the base branch stated rather than assumed.
- Pruning them is an explicit, opt-in action, consistent with Plan 00349's
  report-and-offer decision.
- `git branch --list` reflects branches someone might still want.

## Non-Goals

- **Not** a general branch-pruning policy for the repository. Scoped to
  branches matching the agent-dispatch naming shape, exactly as Plan 00349
  scoped itself to `.claude/worktrees/`.
- **Not** deleting anything with `-D`. If `git branch -d` refuses a branch, that
  refusal is the answer and is reported, never overridden — the same rule Plan
  00349 Task 2.2 settled on.
- **Not** changing `worktree-reap`'s existing predicate or its output for
  worktrees that still exist.

## Context & Background

Plan 00349 built the worktree half and states the relevant Non-Goal outright:
"Not a general branch-pruning policy for the repository." That boundary is why
this is a separate plan rather than a task there.

| Plan  | Title                                   | Status   | Relevance                                                                 |
| ----- | --------------------------------------- | -------- | ------------------------------------------------------------------------- |
| 00349 | Agent worktrees accumulate unreaped     | Complete | Built `worktree-reap`; this is the branch-side gap it left open           |
| 00188 | WorktreeRemove handler                  | Complete | Removes a worktree on the event — one of the routes that orphans a branch |
| 00267 | Worktree seeding and config suggestions | Complete | The creation side, which also creates the branch                          |
| 00048 | Repository cruft cleanup                | Complete | Cleaned stale branches once, manually — the precedent, not a mechanism    |

The obvious implementation is to reuse what exists: `collect_worktree_states`
already knows which branches have worktrees, so "orphaned" is the set difference
between `git branch --list <pattern>` and that set. The interesting question is
what to report for a branch that is **not** fully merged, since unlike the
worktree case there is no uncommitted state — only commits, which `git cherry`
can still misreport as unlanded after a rebase (Plan 00349 Task 1.2).

## Tasks

### Phase 1: See them

- [ ] ⬜ **Task 1.1**: Enumerate `agent-*` branches with no worktree, and record
  for each whether it is fully merged into the base branch. Report only.

- [ ] ⬜ **Task 1.2**: Decide the surface: a flag on `worktree-reap` (they are
  the same lifecycle and a human clearing up wants one command) versus a
  separate command (the predicates and risk profiles genuinely differ). Record
  the reason, not just the choice.

### Phase 2: Offer them

- [ ] ⬜ **Task 2.1**: Prune on explicit opt-in only, `git branch -d` never
  `-D`, with a git refusal reported and never retried with force. Dry-run by
  default, matching Plan 00349.

- [ ] ⬜ **Task 2.2**: Observe it against a real throwaway branch — created,
  cleared, pruned, gone — rather than only against a fake git. Plan 00349 Task
  3.4 found this worth doing separately from the unit tests, which only ever
  assert the argv the code builds.

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA green, daemon restart RUNNING.

## Success Criteria

- [ ] The three orphans identified above are either pruned or reported with a
  stated reason for keeping them
- [ ] A branch that is not fully merged is never deleted
- [ ] Pruning never happens without an explicit opt-in flag

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00352-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from the verification of Plan 00349 Task 3.3, which measured the gap
  rather than predicting it.
