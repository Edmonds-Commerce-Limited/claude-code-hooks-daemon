# Plan 00352: agent branches outlive their worktrees

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Three orphans, and **all three are fully merged into
  `main`** — 0 commits ahead, and each is listed by `git branch --merged main`:

  | Branch                             | Ahead of `main` | Merged |
  | ---------------------------------- | --------------- | ------ |
  | `agent-a4ff553e443d90fc7-0b00a249` | 0               | yes    |
  | `agent-a88580597e044ef36-d1a957af` | 0               | yes    |
  | `agent-a919dc7e0a2315615-f3d60e5a` | 0               | yes    |

  The set is computed as `git branch --list 'agent-*'` minus the branches
  `git worktree list --porcelain` reports — that difference IS the definition of
  orphaned, so no separate detection is needed.

  Note what this does **not** establish: that three is the steady state. It is a
  snapshot after one reap, and the population grows with every dispatch whose
  worktree is removed without its branch. Plan 00349 Task 3.2 showed a completed
  dispatch leaving both behind, so the ordinary route here is a later worktree
  removal, not a rare failure.

- [x] ✅ **Task 1.2**: **Reported by `worktree-reap`, acted on by a second flag
  of its own — `--reap-branches`, never by widening `--reap`.**

  *Why one command reports both.* The orphan set is DEFINED as the branch list
  minus the branches `collect_worktree_states` already reports, so a separate
  command would re-derive exactly the data `worktree-reap` has in hand. And the
  moment a human needs to know is the moment they finish reaping: three branches
  going quiet is invisible unless the thing that just removed their siblings
  says so.

  *Why a separate flag rather than widening `--reap`.* Someone with `--reap` in
  a script agreed to remove worktrees and their attached branches. Making that
  same invocation start deleting standalone branches changes what an existing
  command does without anyone re-reading it — the one property Plan 00349 Task
  2.1 was most careful about. A new flag cannot surprise an old caller.

  *What this does not do.* It stays scoped to the `agent-*` naming shape, so it
  is not the general branch-pruning policy Plan 00349 and Plan 00048 both
  declined.

### Phase 2: Offer them

- [x] ✅ **Task 2.1**: `collect_orphaned_branches` + `prune_branch`, wired to
  `worktree-reap --reap-branches`. Dry-run by default; `git branch -d`, never
  `-D`; a git refusal reported and never retried with force.

  **Unknown merge status counts as unmerged.** If `git branch --merged` cannot
  be read, every branch is marked unmerged rather than defaulting to safe —
  otherwise a git failure would become a deletion, the same rule Plan 00349
  Task 1.2 settled for counts.

- [x] ✅ **Task 2.2**: Observed against real branches, including the case the
  three real orphans could not exercise. Two throwaways with no worktree — one
  at `main`, one carrying a commit that exists nowhere else — were classified
  correctly: `would delete branch agent-probe-merged`, and the unmerged one
  refused by name with its reason.

  `--reap-branches` then deleted the four merged branches (the three real
  orphans and the probe) and left the unmerged one. The six `agent-*` branches
  that still have worktrees were untouched throughout.

  **The refused probe is still here, and that is the design working.** `-D` is
  blocked by project policy and this plan's Non-Goals, so a branch git declines
  to delete needs a human — even when the agent that made it knows it is
  worthless. Left for the owner: `git branch -D agent-probe-unmerged`.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: 26/26 QA checks pass (19711 tests, 0 failed, coverage
  95.3%), daemon restart RUNNING.

  One check had to be earned rather than observed. `semgrep` flagged the branch
  listing under `short-refname-in-branch-listing`: the first cut asked git for
  `--format=%(refname:short)`, which yields the shortest UNAMBIGUOUS name — so a
  branch shadowed by a same-named tag comes back as `heads/<name>`, a string no
  git command accepts. Every membership test and every `git branch -d` built
  from that listing would have been wrong for exactly the branch most at risk.
  Plan 00254 measured that same mistake force-deleting a branch holding the only
  copy of a file. The listing now asks for `%(refname)` and strips via
  `git_repo.strip_branch_ref`; the delete addresses `git_repo.branch_ref`.

## Success Criteria

- [x] The three orphans identified above are either pruned or reported with a
  stated reason for keeping them — all three pruned
- [x] A branch that is not fully merged is never deleted — refused by the
  predicate, and `git branch -d` refuses again behind it
- [x] Pruning never happens without an explicit opt-in flag — `--reap-branches`,
  separate from `--reap` so no existing caller changes behaviour

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00352-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed from the verification of Plan 00349 Task 3.3, which measured the gap
  rather than predicting it.
- `f6f1069c` — `collect_orphaned_branches` + `prune_branch`, wired to
  `worktree-reap --reap-branches`
- `f587a7f0` — address branches by full ref, never the short name
