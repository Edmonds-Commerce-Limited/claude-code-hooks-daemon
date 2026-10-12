# Plan 00512: worktree events outlive the chain deadline

**Status**: In Progress
**Created**: 2026-10-12
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #82

## Overview

The `worktree_create` handler runs `git worktree add` with a 30s budget
(`Timeout.GIT_WORKTREE`). That budget does not fit inside the limits around it:

- the daemon-wide chain deadline (`Timeout.CHAIN_DEADLINE_DEFAULT`, 20s,
  `daemon.chain.deadline_seconds`) is shorter;
- the client's socket wait (`HOOK_TOTAL`, 30s) is no longer.

So an add that takes more than about 20s, for example behind a slow
post-checkout hook, gets no path back to Claude Code, and the worktree creation
fails. The git call carries on in the handler's dispatched thread, and the
worktree and branch are still created, as an orphan. Claude Code itself is not
the limit: the WorktreeCreate hook has no `timeout` in settings, so the
harness default applies.

Coordinator ruling (the triage is in #82):

- WorktreeCreate and WorktreeRemove are not guards. They do work and report a
  path, so the 20s guard deadline is the wrong budget for them. They get an
  event-specific budget in which the chain deadline and the client wait both
  exceed the git budget with a margin.
- When the handler's own git call fails or times out, it removes any partly
  created worktree and branch.
- The PreToolUse guards keep the 20s deadline unchanged.

Plan 00495 (performance) is related: it addresses the SessionStart chain
overrunning the same 20s budget, by reducing work. It does not change the
budgets.

## Goals

- A `git worktree add` that finishes inside its own budget yields the worktree
  path.
- A failed or timed-out add leaves no orphan worktree or branch.
- A test asserts, for every event, that each handler's own subprocess budget is
  below that event's chain deadline, and the chain deadline is below the client
  wait. The class cannot return unnoticed.

## Non-Goals

- Changing the deadline for any guard event.
- Making `Timeout.GIT_WORKTREE` configurable.

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: RED. Write failing tests:
  - the budget-ordering invariant for the worktree events;
  - a slow add (a stub git, or a post-checkout hook in a temporary repository)
    still yields its path through the chain and the client transport;
  - a git add that fails or times out leaves no worktree and no branch.
- [ ] ⬜ **Task 1.2**: GREEN. Implement the event-specific budget in the daemon
  chain and in the client transport (`init.sh`, and the Python client where it
  applies), and the cleanup in the handler. Update the handler guidance and
  the config docs, and add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

### Phase 2: Land

- [ ] ⬜ **Task 2.1**: Review, coordinator checks, merge; comment on and close #82.

## Success Criteria

- [ ] The issue's slow-add scenario yields the path, and a failed add leaves no
  orphan.
- [ ] The release-bound consequence, the worktree events' longer budget, is in
  the pending-release holding area as a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- Issue #82 triaged and claimed; confirmed on `main` by reading the code.
