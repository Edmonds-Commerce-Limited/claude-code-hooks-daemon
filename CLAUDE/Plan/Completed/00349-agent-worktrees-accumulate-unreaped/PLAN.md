# Plan 00349: agent worktrees accumulate unreaped

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Characterised, and the picture is cleaner than the
  Overview's spot-check suggested. **All 21 are stale**, in two groups:

  - **15 are clean and strictly behind `main`** — 0 ahead, 0 uncommitted, 249
    to 768 commits behind. Nothing to lose.
  - **6 carry one unlanded commit and one staged file, and both are accounted
    for.** All six are the same dispatch batch: the identical commit
    `1d49da27` ("Plan 00284: Task 3.2 slice E") and the identical staged
    `.claude/ccy/CLAUDE.md`. `git cherry` reports **1** unlanded patch each —
    not the 195–224 their `main..HEAD` count implies, so the bulk landed under
    different SHAs exactly as the Overview says.

  **Both remainders are already on `main` or deliberately untracked.** Every
  file `1d49da27` touched is in its landed state: Plan 00284 sits in
  `Completed/`, its `26-08-28` journal day-file is present,
  `ccy-supervisor-dogfooding.md` is thinned to the 17-line pointer the commit's
  own subject describes, and `DOC-CONVENTIONS.md` exists. And
  `.claude/ccy/CLAUDE.md` is **gitignored** (`.claude/ccy/.gitignore`), present
  on disk in the main checkout, and the live copy is NEWER than the staged one
  (4300 bytes vs 3050) — a superseded draft of an untracked file, not work at
  risk.

- [x] ✅ **Task 1.2**: `core/worktree_reaping.py` — `WorktreeState` (plain data,
  so the decision is testable without a git repo) plus `is_reapable` and
  `reap_refusal_reason`. Reapable means **no uncommitted paths, no commits
  ahead of the base, and no unlanded patches**; anything else refuses, and
  reports *every* applicable problem rather than the first.

  **It refuses the 6 that Task 1.1 proved safe, deliberately.** What made them
  safe was reading a commit subject, locating a plan folder and comparing byte
  counts — judgements this function cannot make and must not fake. A rebased
  commit that already landed is indistinguishable here from one that did not.
  Teaching it that gitignored files or already-landed patches do not count
  would have cleared those six correctly and been wrong the first time an agent
  staged something that mattered. A reaper that is occasionally too cautious
  wastes disk; one that is occasionally too eager destroys work that exists
  nowhere else. A negative count is refused too — that means the collector
  failed, and reading it as "zero ahead" would turn a collection failure into a
  deletion.

- [x] ✅ **Task 1.3**: Run against all 21, **deleting nothing**: `total=21 reapable=15 refused=6`, splitting exactly as the hand characterisation did.
  All 6 refusals are the same batch and carry the same reason. None was
  unclassifiable.

### Phase 2: Reap or surface

- [x] ✅ **Task 2.1**: **Report and offer, do not reap automatically.**

  *Cleanup at dispatch end already exists and is not enough.* The
  `WorktreeRemove` handler (Plan 00188) already prunes on that event and
  force-removes a named path. All 21 accumulated anyway, so the gap is not a
  missing reaction — it is worktrees whose creating session ended without ever
  firing the event. That needs a sweep, not a better reaction.

  *Automatic reaping is the wrong trade here, twice over.* The failure modes
  are asymmetric: accumulation costs disk and legibility, over-eager reaping
  destroys work that exists nowhere else. And Task 1.3 measured that the
  conservative predicate cannot clear 6 of 21 — so an automatic reaper would
  leave a permanent residue and still need a human path. Better to build the
  human path properly than to build both.

  So: a **collector** that classifies, a **report** naming the reapable ones and
  explaining each refusal, and an **explicit command** to act — dry-run by
  default.

- [x] ✅ **Task 2.2**: `reap_worktree` plus the `worktree-reap` CLI command that
  makes it usable — dry-run by
  default at the call site, no git command at all for a worktree the predicate
  refused, and **git asked to disagree twice**: `git worktree remove` runs
  without `--force`, so git refuses a worktree with modified or untracked
  files, and the branch is deleted with `-d`, never `-D`, so git refuses one
  that is not fully merged (also `R-GIT-BRANCH-FORCE-DELETE`). A git refusal is
  reported, never retried with force — that is the whole value of asking. A
  reap path whose only safety is the predicate has one bug between it and a
  deletion.

  `bin/hooks-daemon worktree-reap` is the surface. **Doing nothing is the
  default** — it reports and exits; acting needs `--reap`. A refused worktree is
  printed *with* its reason rather than omitted, because one that silently
  vanishes from the report looks handled. Exit 1 when any need a human, so the
  actionable case is visible to a script.

  Run against this repository: `15 reapable, 6 need a human. Nothing was changed.`

- [x] ✅ **Task 2.3**: The branch is deleted after the worktree, in the same
  call. A failed branch delete still reports the worktree as removed (the
  expensive part succeeded) and names the leftover branch, rather than
  reporting a total failure that would invite a retry.

### Phase 3: Verify

- [x] ✅ **Task 3.1**: **QA 26/26, coverage 95.3%**, `18807 passed, 0 failed, 7 skipped`; daemon RUNNING. `core/worktree_reaping.py` is at 100%, and
  `cmd_worktree_reap` has no uncovered line — the empty-repository branch was
  the last one, and it was reached by a test rather than by an exclusion.

- [x] ✅ **Task 3.2**: Observed, with a real `isolation: "worktree"` dispatch —
  and **it creates but does not dispose**, which is the accumulation mechanism
  caught in the act rather than inferred.

  The agent ran in `.claude/worktrees/agent-a1d18f9e…` on a branch of the same
  name, caught live in `git worktree list` mid-run. It was told to write
  nothing, and wrote nothing. After it finished, the directory, the
  `git worktree list` entry and the branch were all **still there** — despite
  the documented behaviour being auto-clean when unchanged. `git status` inside
  it is clean, it is 0 commits ahead, and `worktree-reap` classifies it
  reapable.

  This falsifies the task's own premise. It was written expecting to watch a
  session end dispose of a worktree; there was no disposal to watch. Task 2.1
  reasoned that the accumulation came from sessions ending *without firing the
  event* — the truth is simpler and worse, because one dispatch that completed
  normally still left its worktree behind. A sweep is the right design for a
  stronger reason than the one originally given.

- [x] ✅ **Task 3.3**: Reaped on the owner's explicit instruction ("you can reap
  worktrees you are the only one driving them") — the authorisation Task 2.1
  said the offer needed, given rather than assumed. **15 removed with their 15
  branches, 6 refused, no failures.** `git worktree list` went from 22 lines to
  7\.

  The 6 that remain are the batch Task 1.1 characterised and Task 1.2
  deliberately refuses. They stay until someone reads them, which is the
  designed outcome and not a residue to clear by loosening the predicate.

- [x] ✅ **Task 3.4**: Observed on a real worktree, and it behaved as the fake
  git said it would: the throwaway was created, the predicate cleared it, the
  dry-run changed nothing, `--only` reaped that one, and the directory, the
  `git worktree list` entry and the branch were all gone afterwards — with the
  other 21 untouched.

  The unit tests drive a fake git, so every assertion about `worktree remove`
  and `branch -d` was an assertion about the argv this code builds. This is the
  one that shows git accepting it.

  This is a better use of Phase 3 than Task 3.2, which verifies Plan 00188's
  handler rather than anything built here — and it does not add a 22nd
  worktree to the pile it is meant to reduce.

  **The gap it exposed is closed**: `--only NAME` acts on one worktree. Naming
  one narrows the TARGET and never overrides the predicate — a named worktree
  that is not reapable is still refused — and an unknown name **exits non-zero**
  rather than doing nothing quietly, because a typo that silently no-ops reads
  exactly like success.

## Success Criteria

- [ ] `git worktree list` shows only live worktrees plus the repository — **22
  lines down to 7, but not met and deliberately so.** None of the 6 remaining
  is live; they are the batch the predicate refuses. Meeting this literally
  would mean either a human reading them or a looser predicate, and the second
  is what this plan exists to avoid.
- [x] The reapable predicate has tests covering clean, diverged-but-landed, and
  genuinely-unmerged worktrees, and declines the last of those
- [x] No worktree holding unmerged work is ever removed automatically —
  reinforced by asking git to disagree twice (`worktree remove` without
  `--force`, `branch -d` not `-D`), and a git refusal is reported, never
  retried with force

**Found while verifying Task 3.3: three `agent-*` branches have no worktree at
all** (`a4ff553e…`, `a88580…`, `a919dc…`), all 0 commits ahead of `main`. They
predate this reap — none appears in its output. The reaper walks `git worktree list`, so a branch whose worktree was already removed is invisible to it and
survives forever. Left alone here: this plan's Non-Goals rule out a general
branch-pruning policy, and the authorisation received was for worktrees. Filed
as [Plan 00352](../00352-agent-branches-outlive-their-worktrees/PLAN.md).

## Delivery & Milestones

- Filed from a survey during Plan 00250; no code yet.
- `ae4794a7` — characterise the 21 worktrees and decide the predicate
- `6d246ab6` — read worktree state from git, with failures that stay refusals
- `a303b528` — reap a worktree, with git as the second and third safety net
- `42788bff` — the `worktree-reap` command
- `f2167f20` — `--only`, which narrows the target and never the predicate
- Verified against the real pile on the owner's authorisation: 22 `git worktree list` lines down to 7, 15 worktrees and 15 branches removed, 6 refused.
