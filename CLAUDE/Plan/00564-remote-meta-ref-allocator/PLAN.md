# Plan 00564: remote meta ref allocator

**Status**: Not Started
**Created**: 2026-11-04
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Opus for Phase 1, Sonnet for the build
**Execution Strategy**: Sub-Agent Orchestration
**Release**: not the next release (owner, 4 November 2026)

## Overview

Plan 00562 (#154) made plan-number allocation read the remote's branches before choosing a number. That closes the observed collision, but two clones that have not pushed yet can still take the same number. The owner proposed a single source of truth on the remote: a metadata ref holding one `KEY=VALUE` file, edited only on the remote, never checked out locally.

**The mechanism.** A ref outside `refs/heads/`, for example `refs/hooks-daemon/meta`. It is never checked out and never appears in `git branch`, so it needs no branch exemptions. It holds one file of `KEY=VALUE` lines, for example `plan_number=562`. To allocate a number:

1. Fetch the ref.
2. Read the value.
3. Write a commit with the value plus one, using git plumbing (`hash-object`, `mktree`, `commit-tree`) with no checkout.
4. Push it as a fast-forward.

If another clone pushed first, the push is rejected as not a fast-forward; re-fetch and retry. The push is the lock: an atomic compare-and-swap through the remote.

**Prior art.**

- Gerrit's `refs/meta/config`: per-project configuration as a separate history, edited by fetch, commit, push.
- git-annex's `git-annex` branch: a metadata-only branch updated by plumbing.
- git-bug (`refs/bugs/*`) and git-appraise (`refs/notes/devtools/*`): issues and code reviews stored in custom refs.
- `git notes` (`refs/notes/*`).

**Who allocates.** Only someone with push access makes plans, so there is no read-only case. The real risks are GitHub or local network failures, so the design needs a fallback and a recovery step.

## Goals

- The meta ref is the authoritative plan-number allocator: two clones can never take the same number while the remote is reachable.
- When the remote is unreachable, allocation still succeeds through Plan 00562's local and remote-tracking answer, and the plan is marked as provisionally numbered.
- A recovery step, run when the remote is back, reconciles a provisional number: it claims the number on the meta ref if it is still free, or renumbers the plan folder and its references if not.
- The file format allows other `KEY=VALUE` facts later; plan number is the only key this plan adds.

## Non-Goals

- Moving any other fact onto the meta ref. That needs its own decision per key.
- Changing how plans are stored. Plan folders stay the visible record; the ref is the allocator.

## Tasks

### Phase 1: Design and proof

- [ ] ⬜ **Task 1.1**: Prove GitHub accepts a push to a custom `refs/hooks-daemon/*` namespace, and that a non-fast-forward push to it is rejected. Use a throwaway ref name and delete it afterwards. Owner approval is needed before pushing anything to the real remote.
- [ ] ⬜ **Task 1.2**: Design the retry bound, the timeouts, the provisional marker (where it is recorded, so recovery can find it) and the renumbering steps (folder, PLAN.md header, README row, counter, cross-references).
- [ ] ⬜ **Task 1.3**: Decide bootstrap: the first allocation in a repository creates the ref, seeded from Plan 00562's highest-known number.

### Phase 2: Build (test first)

- [ ] ⬜ **Task 2.1**: Allocator in `mkplan.bash` (both copies) and `plan_numbering.py`: fetch, compare-and-swap push, bounded retry. Tests: two clones racing against a bare remote get distinct numbers; a lost race retries.
- [ ] ⬜ **Task 2.2**: Fallback when unreachable: use Plan 00562's answer and record the provisional marker. Test with an unreachable and a hanging remote.
- [ ] ⬜ **Task 2.3**: Recovery command, `hooks-daemon plan-number reconcile`, plus a SessionStart advisory when provisional plans exist. Tests: free number claimed; taken number renumbered.
- [ ] ⬜ **Task 2.4**: Hooks never fetch or push. They keep reading only what is already fetched (Plan 00562's rule).

### Phase 3: Ship

- [ ] ⬜ **Task 3.1**: Docs, a release note and config-changes entries in the pending-release holding area.

## Success Criteria

- [ ] The racing-clones test gives distinct numbers every run.
- [ ] Offline allocation succeeds and is reconciled correctly in both recovery cases.
- [ ] No hook touches the network.
- [ ] A release note in `CLAUDE/UPGRADES/UNRELEASED/` (the pending-release holding area) describes the meta ref, because it writes a new ref to every client remote.

## Delivery & Milestones

- Proposed by the owner after Plan 00562 shipped the read-only scan.
