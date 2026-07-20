# Plan 00179: git upstream — drop auto-prune, add gone-branch advisory

**Status**: Complete
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Follow-up to Plan 00178. The shipped `git_upstream_checker` fetched with
`git fetch --all --prune`. User feedback: the daemon must **never do anything
potentially lossy or surprising automatically** at session start. Although
`--prune` only removes stale *remote-tracking* refs (it never deletes local
branches or working-tree data), it is a silent mutation, and — more importantly —
when a remote branch is deleted, any *local* branch that tracked it is left
behind and may hold unique commits. Cleaning those up is a genuinely lossy
operation that must be a deliberate, checked decision.

This plan makes two changes:

1. **Drop `--prune` from the automatic fetch** — the session-start fetch becomes
   purely additive (`git fetch --all`), never removing anything.
2. **Add a read-only "gone-branch" advisory** — detect local branches whose
   upstream was deleted on the remote, classify each as **merged** (safe to
   remove with `git branch -d`) or **not merged** (has unique commits — inspect
   and ask the human before removing), and instruct the agent accordingly. The
   daemon itself NEVER deletes a branch.

## Goals

- Automatic fetch is `git fetch --all` (no `--prune`) — additive only.
- Detect local branches whose upstream branch was deleted on the remote
  (non-destructively, via `git remote prune --dry-run`).
- Classify each gone branch merged/not-merged vs the default branch.
- Advisory instructs: merged ⇒ safe `git branch -d <name>`; not merged ⇒ ask the
  human, never force-delete (`-D` stays blocked by `destructive_git`).
- Gone-branch detection is gated behind `auto_fetch` (it is a network op) and is
  advisory in ALL modes (never mutates, even in `auto-pull`).
- Silent when nothing is behind AND no gone branches.
- 95%+ coverage; QA green; daemon RUNNING; dogfooded; docs regenerated.

## Non-Goals

- No automatic branch deletion, ever (not even for "safe"/merged branches).
- No automatic pruning of remote-tracking refs (removed entirely; not re-added
  behind an option in this plan — keep the surface minimal and safe-by-default).
- No stashing/committing to make anything safe.

## Tasks

### Phase 1: git_sync — drop prune + gone-branch detection (TDD)

- [x] ✅ **Task 1.1**: Update tests: rename `fetch_all_prune` → `fetch_all`
  (asserts NO `--prune`); add tests for `default_branch`, `gone_branches`
  (deleted-on-remote local branch, merged vs not-merged, none, offline/fail-silent).
- [x] ✅ **Task 1.2**: Implement in `utils/git_sync.py`: `fetch_all` (no prune),
  `default_branch`, `GoneBranch` dataclass, `gone_branches` (dry-run prune
  detection + merged classification). Fail-silent throughout.

### Phase 2: Handler advisory (TDD)

- [x] ✅ **Task 2.1**: Update handler tests: fetch call is `fetch_all`; add a
  gone-branch advisory section (merged ⇒ `git branch -d`; not-merged ⇒ ask
  human); gone detection gated behind `auto_fetch`; behind + gone combine;
  silent when neither.
- [x] ✅ **Task 2.2**: Implement in `git_upstream_checker.py`: call `fetch_all`,
  append gone-branch advisory; update `get_claude_md()` guidance.

### Phase 3: QA, docs, dogfood

- [x] ✅ **Task 3.1**: Update error_hiding exclusions for any new fail-silent fns.
  (No new exclusions needed — the new helpers use `if result is None` guards,
  not try/except; existing `_run_git`/`upstream_status` exclusions still cover it.)
- [x] ✅ **Task 3.2**: `./scripts/qa/llm_qa.py all` green (95%+). — 13/13,
  10401 tests, 95.3% coverage.
- [x] ✅ **Task 3.3**: Daemon restart RUNNING; regenerate `.claude/HOOKS-DAEMON.md`
  (no diff — handler `description` text unchanged).
- [x] ✅ **Task 3.4**: Live end-to-end: delete a remote branch, confirm additive
  fetch + gone-branch advisory (merged & not-merged) with no auto-deletion.
  Live-verified: `--no-prune` bug caught and fixed; both cases surface correctly.

## Technical Decisions

### Decision 1: fetch is additive-only (`git fetch --all`)

Removes the only silent mutation from the session-start path. Deleted-on-remote
detection moves to a separate, explicitly non-destructive `--dry-run` probe.

### Decision 2: detect via `git remote prune --dry-run`

A non-pruning fetch leaves remote-tracking refs stale, so `upstream:track` never
reports `gone`. `git remote prune <remote> --dry-run` reports exactly which
remote-tracking refs WOULD be pruned (i.e. deleted on remote) without removing
anything. Map those to local branches whose upstream matches.

### Decision 3: daemon never deletes; recommend `git branch -d` only

`git branch -d` is inherently safe (git refuses to delete an unmerged branch).
We pre-classify via `git branch --merged <default>` to label each branch, but the
advisory always defers the actual removal to the agent/human. `-D` remains
blocked by `destructive_git`.

## Success Criteria

- [x] No `--prune` in the automatic fetch (explicit `--no-prune` so it holds
  even under `fetch.prune = true`).
- [x] Gone branches surfaced with correct merged/not-merged classification.
- [x] Advisory never triggers deletion; recommends `-d` (safe) or ask-human.
- [x] QA green, daemon RUNNING, dogfooded, docs regenerated.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. -->

- Plan created; reuses live recovery cron `dffb57b7` (hourly :37, non-durable).
- Phase 1 (git_sync additive fetch + gone-branch detection) delivered `c3752b1f`.
- Phase 2/3 (handler gone-branch advisory + explicit `--no-prune` fetch fix)
  delivered `0f8bb4fc`. The `--no-prune` fix was a live dogfooding catch:
  `fetch.prune = true` in git config made a bare `git fetch --all` prune anyway,
  wiping the stale refs `gone_branches` needs.
