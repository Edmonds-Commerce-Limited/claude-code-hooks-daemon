# Plan 00586: five small defects, verify then fix

**Status**: Not Started
**Created**: 2026-11-09
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Five defects were noticed in passing during other work and recorded nowhere. Owner ruling: a finding gets a plan
(`CLAUDE/Worktree.md`, "Small Batches"). Three of them (A, B, D) came from review agents and have not been reproduced,
so every task starts by reproducing the defect. A task whose defect does not reproduce closes with the evidence that it
does not, and no change.

- **A.** `check-config-migrations` recommends handlers that have since been removed.
- **B.** `daemon.languages: []` is read as "no languages" rather than as unset.
- **C.** The `/hooks-daemon optimise` procedure (`scripts/optimise-invoke.sh`, `optimise.md`) gives wrong paths when
  the daemon is self-installed, as in this repository.
- **D.** In the release-gate workflow, a failing shard does not cancel the other shards, so a run that has already
  failed keeps using runners.
- **E.** The plan-number guard (`plan_number_helper`, R-PLAN-NUMBER-DISCOVERY) blocks a command that combines an
  `ls ... | awk` with `git add CLAUDE/Plan/...`, which discovers no plan number.

Dedupe scout (all 70 live plans checked before this one was filed): no live plan covers B, C, D or E. A overlaps Plan 00420 (fail-fast
config migration of retired handler keys), which is a superset: if 00420 is in progress when A is reached, A moves
there. Prior art: Plan 00323 (a contract test against the optimise checklist naming retired handlers; relevant to A
and C), Plans 00227 and 00138 (earlier false-positive fixes of the same guard as E).

## Goals

- Each of A to E is either fixed with a test that failed before the fix, or closed with the evidence that it does not
  reproduce.

## Non-Goals

- Plan 00420's wider config-migration work.
- Plan 00421's choice of which checks run in CI (D is job cancellation only).

## Tasks

### Phase 1: Verify and fix (one task per defect, independent)

- [ ] ⬜ **Task 1.1 (A)**: Reproduce: list every handler `check-config-migrations` can recommend and compare it with
  the registered handlers. RED test, then fix the source of the recommendation. Check Plan 00420 first
- [ ] ⬜ **Task 1.2 (B)**: Reproduce with a config holding `daemon.languages: []`. Decide which reading the config
  documentation promises; RED test for that reading, then fix the loader (or the documentation, if the code matches
  what it promises)
- [ ] ⬜ **Task 1.3 (C)**: Run the optimise procedure in this self-install checkout and record each wrong path. RED
  test, then fix through the existing install-mode path resolution
- [ ] ⬜ **Task 1.4 (D)**: Confirm in the release-gate workflow and on a failed run that the other shards ran to the
  end. Fix with the workflow's fail-fast or a cancel step, keeping the final aggregate job's verdict
- [ ] ⬜ **Task 1.5 (E)**: RED test with the exact command shape, then narrow the discovery-idiom match so it is
  allowed, keeping the existing tests for real discovery commands red-to-green

### Phase 2: Delivery

- [ ] ⬜ **Task 2.1**: targeted QA per task, merge each to main, verify CI

## Success Criteria

- [ ] Each of A to E: a test that failed before the fix and passes after it, or recorded evidence that it does not
  reproduce
- [ ] Release-bound consequence recorded: a callout in `CLAUDE/UPGRADES/UNRELEASED/release-notes/` for each
  user-visible fix (A, B, C, E); D changes CI only and has no release-bound consequence

## Delivery & Milestones

- (pending)
