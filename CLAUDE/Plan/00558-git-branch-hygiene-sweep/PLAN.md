# Plan 00558: git branch hygiene sweep

**Status**: Not Started
**Created**: 2026-11-02
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner reports that projects accumulate work on branches that nobody ever merges, and that work is then forgotten. In one client project, a forgotten branch held about 147,000 lines of code and kept drifting further behind main. Nothing in the daemon surfaces this today. Plan 00178 built a session-start check for the current branch being behind its upstream. Plan 00179 added an advisory for branches whose upstream has gone. Plans 00349 and 00352 reap agent worktrees and branches. None of these asks "which branches hold work that main does not have, and how stale is it?".

This repository shows the same pattern. On 2 November it had:

- 46 local branches;
- 4 remote branches with commits not on main, the oldest from June (`feature/00135-tmux-send-keys-injection`).

This plan adds a branch sweep that works the way `plan-qa --sweep` does for plans:

- a SessionStart summary, plus an on-demand CLI verb;
- for every local branch, remote branch and worktree that holds commits not on the default branch, it reports:
  - how much work is at stake (commits and lines);
  - how old the work is;
  - how far the branch has drifted behind the default branch;
  - which plan or issue it belongs to, if any.

Branches and plans are closely linked (`worktree-plan-NNNNN`, `worktree-issue-N`, plan numbers in commit messages), so the sweep cross-references them. Each branch then reads as one of:

- the in-flight branch of a live plan;
- the leftover of a completed plan;
- an orphan.

## Goals

- **Inventory.** `hooks-daemon branch-sweep` lists every branch and worktree with unmerged work:
  - ahead count, lines changed, last commit date, behind count, and whether a remote holds it;
  - the linked plan or issue, with that plan's status.
- **SessionStart summary.** One terse line naming the count and the largest or oldest offenders, plus the command for detail. It stays silent when nothing qualifies.
- **Classification.** Each branch is labelled one of:
  - live plan;
  - completed-plan leftover;
  - merged (safe to delete);
  - orphan with substantial work;
  - agent scratch.
- **Report-only by default.** The sweep never deletes, merges or rebases. Deletion stays with the existing `worktree-reap` and safe-delete routes (Plans 00349, 00352, 00206), which the sweep may name in its output.
- **Tunable thresholds.** Size, age and drift thresholds live in config. The defaults are noisy enough to catch a 147,000-line orphan and quiet about one-commit agent scratch.
- **Fast enough to run at session start.** A large repository is bounded by limits and caching, and the sweep reports what it skipped rather than guessing.

## Non-Goals

- Merging, rebasing or deleting branches automatically.
- Replacing `git_upstream_checker` (current branch versus its upstream) or `worktree-reap`.
- A judgement on whether the unmerged work is any good.

## Tasks

### Phase 1: Research

- [ ] ⬜ **Task 1.1**: Read Plans 00178, 00179, 00349, 00352 and 00206, and the `branch_count_advisor` and `git_upstream_checker` handlers. Record:
  - what each already computes and whether it can be reused;
  - which git commands are cheap enough for SessionStart (`for-each-ref`, `rev-list --count`, `--shortstat` cost on large diffs);
  - how plan and issue links can be read from branch names and commit messages.
- [ ] ⬜ **Task 1.2**: Decide the classification rules and default thresholds, and decide whether this extends `branch_count_advisor` or is a new handler. Record the decision.

### Phase 2: Build (TDD)

- [ ] ⬜ **Task 2.1**: Write a pure inventory module with fixture repositories in tests: ahead, behind, lines, age, remote presence, worktree mapping, and plan/issue linkage.
- [ ] ⬜ **Task 2.2**: Add the `branch-sweep` CLI verb, with text and `--json` output.
- [ ] ⬜ **Task 2.3**: Add the SessionStart summary handler. It must be time-bounded, cached and silent when clean.
- [ ] ⬜ **Task 2.4**: Wire the sweep into `/hooks-daemon housekeeping` as a report-only step, and add it to the docs.
- [ ] ⬜ **Task 2.5**: Add a release note in the pending-release holding area.

### Phase 3: Dogfood

- [ ] ⬜ **Task 3.1**: Run the sweep on this repository and act on what it finds: merge, plan, or ask the owner about each orphan.

## Success Criteria

- [ ] On a fixture repository, the sweep reports an orphan branch with substantial unmerged work, its size, its age, how far it lags main, and its plan link or the lack of one. A test proves this.
- [ ] The SessionStart line is silent on a clean repository and fits within the session-start time budget on this repository.
- [ ] Nothing is deleted or rewritten by the sweep.
- [ ] A release note is recorded in `CLAUDE/UPGRADES/UNRELEASED/` (the pending-release holding area).

## Delivery & Milestones

- Plan filed at the owner's request. The dedupe scout found no existing plan covering it (61 live plans checked, plus 486 archived).
