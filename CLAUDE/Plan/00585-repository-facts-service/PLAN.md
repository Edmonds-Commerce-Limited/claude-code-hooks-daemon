# Plan 00585: repository facts service

**Status**: Not Started
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Handlers increasingly need facts about the project's GitHub repository: whether it supports native draft pull
requests (Plan 00584), whether the signed-in account is an admin (Plan 00573, through `issue-validity`), branch
protection (Plan 00568), the default branch. Today the only such lookups are the lazy, TTL-cached permission caches
inside `src/claude_code_hooks_daemon/utils/github_issue_validity.py`, private to that module. Owner ruling
(2026-11-09): a rich metadata object, cached and kept up to date automatically, is better than hard-coded config.

The service holds one object per repository with each fact's value, its source and when it was last read. It refreshes
lazily on a time limit and at session start, never on every hook call, and a fact that cannot be read is "unknown",
never a guessed default. Tracked config holds only explicit overrides (for offline use or a GitHub Enterprise host),
never the facts themselves.

**Where it lives (owner question, answered 2026-11-09): a per-clone, untracked cache, not the Plan 00564 meta ref.**
GitHub is already the source of truth for these facts. A pushed copy would be a second copy that every clone must
refresh by pushing, which needs write access, adds noise, and races between clones. Some facts are per account
(admin permission) and must never be shared. The meta ref suits state with no other source that every clone must
agree on: allocations, and the project's own DECISIONS about these facts. Those decisions are later meta-ref keys
under Plan 00564's per-key rule, or config.

## Goals

- One shared, typed repository-facts object with per-fact value, source, last-read time and an `unknown` state.
- Automatic refresh: a time limit per fact, a refresh at session start, and a bounded `gh` call budget; a hook
  never waits on GitHub beyond that budget.
- `github_issue_validity`'s permission caches move onto it with no change in behaviour.
- Plan 00584's native-draft capability is read from it.
- A CLI verb prints the object and each fact's age, so a human can see what the daemon believes.

## Non-Goals

- No facts on the Plan 00564 meta ref, and no project decisions in this cache.
- No hand-maintained facts in tracked config; overrides only.

## Tasks

### Phase 1: Design

- [ ] ⬜ **Task 1.1**: Inventory every GitHub lookup the daemon makes (handlers, utils, CLI) and the facts each needs;
  fix the initial fact set
- [ ] ⬜ **Task 1.2**: For each fact, establish which `gh` probe a NON-admin token can read, and record facts GitHub
  only shows to admins as `unknown` for others. Open question for the owner: may an admin's session publish such
  account-independent facts (for example a private organisation's plan) to the meta ref for non-admin clones?
- [ ] ⬜ **Task 1.3**: Storage location, time limits, refresh triggers and the per-call budget; record the decisions

### Phase 2: Build

- [ ] ⬜ **Task 2.1**: RED tests, then the service with an injectable `gh` runner (as `github_issue_validity` has)
- [ ] ⬜ **Task 2.2**: Move `github_issue_validity`'s permission lookups onto it; the existing tests pass unchanged
- [ ] ⬜ **Task 2.3**: The CLI verb

### Phase 3: Delivery

- [ ] ⬜ **Task 3.1**: targeted QA, merge, verify CI; tell Plan 00584 the capability is available

## Success Criteria

- [ ] A fact that cannot be read is reported `unknown`, never defaulted (tested)
- [ ] No hook call exceeds the `gh` budget when GitHub is slow or unreachable (tested with a stalled runner)
- [ ] `github_issue_validity` uses the service, and its existing tests pass unchanged
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` naming the verb and
  any override keys

## Delivery & Milestones

- (pending)
