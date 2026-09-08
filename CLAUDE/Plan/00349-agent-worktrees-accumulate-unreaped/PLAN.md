# Plan 00349: agent worktrees accumulate unreaped

**Status**: Not Started
**Created**: 2026-09-08
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`.claude/worktrees/` holds **21** worktrees named `agent-<hex>-<hex>`, left
behind by subagent dispatches from sessions that have since ended. Nothing
removes them. `git worktree list` in this repo is now 22 lines long, of which
one is the repository.

They are stale rather than valuable, which is the finding that makes cleanup
safe to design for. 15 are clean and identical to `main`. The other 6 each carry
195–224 commits not in `main` plus one staged-but-uncommitted file, which looks
alarming until checked: they diverged from `main` on 2026-08-28, and spot-checks
confirm their work already landed under different SHAs — e.g. the branch tip
`Fix Go error-hiding false positive…` is `main`'s `beabce8e`, and the Plan 00284
those commits belong to sits in `Completed/`. So the divergence is re-application
of the same work, not work that was lost.

Two costs, neither fatal, both compounding: disk (each worktree is a full
checkout) and legibility (`git worktree list` and branch listings are dominated
by dead entries, so a *live* agent worktree is hard to spot — which matters
because the isolation advice for concurrent agents depends on being able to see
them). The count only goes up: every dispatch that uses `isolation: "worktree"`
adds one, and the session that created it cannot clean up after itself once it
exits.

Found incidentally while surveying worktrees during Plan 00250. Not urgent — no
work is at risk — but it will not resolve itself.

## Goals

- Stale agent worktrees are removed automatically, or surfaced for removal, with
  no risk to a worktree that is still in use or holds unmerged work.
- The safety test is explicit and conservative: a worktree is only reapable when
  its work is demonstrably elsewhere, or it is clean and identical to `main`.
- `git worktree list` reflects live worktrees, so a genuinely concurrent agent is
  visible again.

## Non-Goals

- **Not** deleting anything as part of this plan's investigation phase. The 21
  present today are evidence; removing them is the deliverable, not the setup.
- **Not** changing how agent worktrees are *created* — Plan 00267 covers the
  `worktree_create` seeding side.
- **Not** a general branch-pruning policy for the repository. This is scoped to
  worktrees under `.claude/worktrees/` created by agent dispatch.

## Context & Background

The dedupe scout named four related plans; none covers this, and two are worth
reading before designing:

| Plan  | Title                                              | Status   | Relevance                                                                               |
| ----- | -------------------------------------------------- | -------- | --------------------------------------------------------------------------------------- |
| 00160 | Supervisor foreground identity & dead-file reaping | Dormant  | TTL-based reaping of stale per-repo session artefacts — the closest transferable design |
| 00161 | Idle housekeeping mode                             | Complete | Housekeeping framework that could host a reaper; does not name worktrees                |
| 00267 | Worktree seeding and config suggestions            | Complete | The `worktree_create` creation side; this plan is its lifecycle end                     |
| 00048 | Repository cruft cleanup                           | Complete | Cleaned stale worktrees once, manually, in a different directory                        |

The hard part is the safety test, not the deletion. "Clean and identical to
`main`" is easy. "Diverged but already landed under different SHAs" is the case
6 of these are in, and detecting it needs something like patch-id comparison
rather than ancestry — precisely because a re-applied commit has a different SHA.
Getting that wrong in the unsafe direction destroys work, so the default for
anything not provably reapable must be to surface it rather than remove it.

Note also that `git branch -D` is blocked by policy (`R-GIT-BRANCH-FORCE-DELETE`)
and `git worktree remove --force` discards uncommitted changes. Any automated
reaper has to be designed against those constraints, not around them.

## Tasks

### Phase 1: Establish the safety test

- [ ] ⬜ **Task 1.1**: Characterise the 21 present worktrees — clean vs dirty,
  merged vs diverged, and for each diverged one whether its commits exist on
  `main` under different SHAs
- [ ] ⬜ **Task 1.2**: Decide the reapable predicate and write it as a tested
  function. Conservative by construction: unknown ⇒ not reapable
- [ ] ⬜ **Task 1.3**: Confirm the predicate against all 21 without deleting
  anything, and record any it declines to classify

### Phase 2: Reap or surface

- [ ] ⬜ **Task 2.1**: Decide the mechanism — automatic cleanup at dispatch end,
  a TTL reaper in the idle-housekeeping path (Plan 00161), or a session-start
  advisory that reports the count and names the reapable ones
- [ ] ⬜ **Task 2.2**: Implement it, respecting `R-GIT-BRANCH-FORCE-DELETE` and
  never using `--force` on a worktree the predicate did not clear
- [ ] ⬜ **Task 2.3**: Handle the branch as well as the worktree — a removed
  worktree that leaves its branch behind has only moved the clutter

### Phase 3: Verify

- [ ] ⬜ **Task 3.1**: Full QA green, daemon restart RUNNING
- [ ] ⬜ **Task 3.2**: A dispatch that creates a worktree and a session end that
  disposes of it, observed rather than asserted

## Success Criteria

- [ ] `git worktree list` shows only live worktrees plus the repository
- [ ] The reapable predicate has tests covering clean, diverged-but-landed, and
  genuinely-unmerged worktrees, and declines the last of those
- [ ] No worktree holding unmerged work is ever removed automatically

## Delivery & Milestones

- Filed from a survey during Plan 00250; no code yet.
