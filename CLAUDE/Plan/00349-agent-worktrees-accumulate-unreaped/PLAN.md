# Plan 00349: agent worktrees accumulate unreaped

**Status**: In Progress
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
