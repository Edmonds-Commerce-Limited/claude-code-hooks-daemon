# Plan 00605: branch sweep classifies no merge base branches

**Status**: Complete (2026-11-14)
**Created**: 2026-11-14
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #203

## Overview

The branch inventory (`src/claude_code_hooks_daemon/core/branch_inventory.py`) measures each work branch against
each target with `_pair_facts`. That included a three-dot `git diff --shortstat <target>...<tip>` in `_lines`. When
the tip shares no history with the target (an orphan branch, or any branch after the default branch's history was
rewritten), git exits non-zero with "no merge base". `_lines` returned `None`, so `_pair_facts` returned `None`, and
the branch was left `UNCLASSIFIED` with a reason that blamed the sweep budget. Raising `branches.sweep.budget_ms`
could not help.

An unclassified branch still counts toward the open-work pool, so a repository full of them stayed over
`branches.wip.cap`. That blocked branch creation, and the sweep gave no way to clear it.

`branch-sweep` also had no way to override `branches.sweep.budget_ms` for a single run. The SessionStart
`branch_sweep` handler reads the same configured value.

## Goals

- A branch with no merge base against a target is measured, and classified as unmerged work that the target does
  not contain. Its commits are counted, and no error is reported.
- When a pair still cannot be measured, the record's reason names the real cause: the budget ran out, or git failed
  against a named target. One generic sentence blaming the budget is no longer used for every case.
- `branch-sweep --budget-ms N` overrides the configured budget for that run only. The configured value and the
  SessionStart handler are unaffected.

## Non-Goals

- No change to classification of branches that do share history with the target.
- No change to the WIP, parked or merged caps, or to what counts toward them.
- No change to `delete-branch` proofs.

## Tasks

### Phase 1: reproduce and fix

- [x] ✅ **Task 1.1**: A failing test reproduces the issue. An orphan branch in a temporary repository comes back
  `UNCLASSIFIED` with the budget reason, even though the budget is far from spent.
- [x] ✅ **Task 1.2**: Measure a no-merge-base pair without the three-dot diff. Lines are counted against the empty
  tree. `git cherry` is skipped and unique is set equal to ahead, because `git cherry` with no merge base compares
  against the target's whole history and could call a rewritten branch patch-equivalent. That was the review's
  critical finding. A shallow clone with no merge base stays `UNCLASSIFIED` with a "history not fetched" reason.
- [x] ✅ **Task 1.3**: Each reason for an unmeasured pair says which cause applied: the budget, or a git failure that
  names the target.
- [x] ✅ **Task 1.4**: Add a `branch-sweep --budget-ms N` flag (a positive integer) that applies to that run only,
  with tests.
- [x] ✅ **Task 1.5**: Add a release note under `CLAUDE/UPGRADES/UNRELEASED/release-notes/`, and update any doc that
  states the unclassified reason or lists `branch-sweep`'s flags.

## Success Criteria

- [x] The orphan-branch reproduction test fails before the fix and passes after it. The review-fix regression tests
  were also confirmed red: 4 of the 5 fail against the first commit's source.
- [x] Targeted QA passes on the branch (`QA: 43/43 PASSED`) and over the merged range on main (`QA: 43/43 PASSED`).
  Main CI run 43620790845 is green on attempt 2.
- [x] The pending-release holding area carries
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/073-branch-sweep-classifies-branches-with-no-merge-base.md`.
- [x] GitHub #203 is commented and closed.

## Delivery & Milestones

- Implementation `ad489f6a8`, review fixes `c482d3d83`, merged to main at `3b39560f9`.
- Reports: `subagent-reports/261114-python-developer-sonnet.md` and `subagent-reports/261114-code-reviewer-opus.md`.

## Follow-ups

- **CI acceptance socket discovery depends on the runner's hostname.** `tests/acceptance/conftest.py`
  `_discover_socket` looks only at `CLAUDE_HOOKS_SOCKET_PATH` and globs `untracked/`. On a runner whose hostname
  pushes the natural socket path past 104 bytes, the daemon falls back to a socket under `/tmp`, and all ten
  acceptance tests error. Main CI run 43620790845 attempt 1 failed this way on `ip-10-0-143-154`, and attempt 2
  passed. Fix: let discovery also try the daemon's own resolver (`get_socket_path`). This needs its own branch, which
  waits for the parked-branch slot to free.
- **The branch-creation guard does not see a worktree branch created by a script.** `branch_creation_guard` matches
  `checkout -b`, `branch <name>`, `worktree add` and Agent worktree isolation. `scripts/setup_worktree.sh` runs
  `git worktree add` itself, so it created this plan's branch while `branch-preflight` reported creation blocked.
