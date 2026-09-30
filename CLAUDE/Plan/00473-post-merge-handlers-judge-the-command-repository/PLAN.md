# Plan 00473: post merge handlers judge the command repository

**Status**: Not Started
**Created**: 2026-09-29
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Graduated from Plan 00468 (G9, Task 4.2). `daemon_sync_after_merge` and
`merge_qa_report` must judge the repository the command ran in, not the
repository the payload `cwd` names. A teammate working in a worktree reports
the main checkout as its `cwd`, so a `git pull` or merge in the worktree is
judged against the wrong tree.

**Blocked on Plan 00464.** Its command-directory resolver (a leading `cd`, with
the payload `cwd` only as the base) is the fix, and this plan adopts it once it
merges. Nothing here starts before then.

## Goals

- Both handlers resolve the repository from the command through 00464's
  resolver, with tests from the main checkout and from a worktree.

## Non-Goals

- Building a second resolver. This plan reuses 00464's.

## Tasks

### Phase 1: adopt the resolver

- [ ] ⬜ **Task 1.1**: Switch `daemon_sync_after_merge` and `merge_qa_report` to
  the resolver, RED-first, once Plan 00464 merges.

## Success Criteria

- [ ] Both handlers judge the repository the command ran in, and a test pins it.
- [ ] Every release-bound consequence is in `CLAUDE/UPGRADES/UNRELEASED/`
  before the status flips, or this criterion says the plan has none.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00473-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Opened from Plan 00468 Task 4.2 (G9).
