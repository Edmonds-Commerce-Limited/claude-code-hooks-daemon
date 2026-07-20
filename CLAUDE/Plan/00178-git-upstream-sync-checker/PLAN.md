# Plan 00178: git upstream sync checker

**Status**: In Progress
**Created**: 2026-07-20
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

At the start of every new session the daemon should perform a **full git
fetch** (`git fetch --all --prune`) and, if the current branch is **behind** its
upstream, act on it according to a configurable policy. Today nothing does this:
the `git_branch` status-line handler background-fetches and shows a passive `↓N`
icon, but there is no prominent, session-start advisory telling the operator (or
agent) that the local branch has fallen behind and a `git pull` is warranted.

This plan adds a new `SessionStart` handler, `git_upstream_checker`, that runs on
new sessions (not resumes), performs the full fetch, computes ahead/behind
against `@{upstream}`, and then applies one of three configurable **modes**:

- **`warn`** (default) — inject a strong advisory recommending `git pull`.
- **`agent-pull`** — inject a directive instructing the agent to run `git pull`
  itself as its first action (agent-driven, can resolve conflicts).
- **`auto-pull`** — the daemon deterministically runs `git pull --ff-only` and
  reports the outcome; degrades to a `warn`-style message when it cannot
  fast-forward (diverged history or dirty working tree).

The git mechanism (fetch / upstream resolution / ahead-behind counts / clean
check / ff-only pull) lives in a focused, independently-testable
`utils/git_sync.py` module; the handler owns only policy/orchestration.

## Goals

- New `SessionStart` handler `git_upstream_checker` (new sessions only).
- Full fetch: `git fetch --all --prune`, non-interactive, bounded timeout,
  fail-silent when offline (still reports staleness from existing refs).
- Deterministic ahead/behind detection via `git rev-list --left-right --count @{upstream}...HEAD`.
- Configurable `mode`: `warn` | `agent-pull` | `auto-pull` (default `warn`).
- `auto-pull` is safe: `git pull --ff-only`, only on a clean tree; otherwise
  degrades to a warning, never leaves a conflicted/merged working tree.
- Silent when up to date, not a git repo, detached HEAD, or no upstream.
- Full wiring: HandlerID meta, Priority, `__init__`, config yaml, init defaults,
  generated docs, `get_claude_md()` guidance, acceptance tests.
- 95%+ coverage; QA green; daemon restarts RUNNING; dogfooded in this repo.

## Non-Goals

- Refactoring the existing `git_branch` status-line background fetch (its own
  fetch stays; a future DRY pass could share `git_sync`, out of scope here).
- Auto-committing or stashing local changes to make a pull possible.
- Non-fast-forward / merge / rebase pulls in `auto-pull` (ff-only only).
- Fetching on session *resume* (avoids re-fetch churn on every compaction).

## Tasks

### Phase 1: git_sync utility (TDD)

- [ ] ⬜ **Task 1.1**: Write failing tests `tests/unit/utils/test_git_sync.py`
  - upstream resolution (has upstream / none / detached)
  - ahead-behind counts parsing (behind, ahead, diverged, in-sync)
  - working-tree clean detection
  - `fetch_all_prune` invokes `git fetch --all --prune` non-interactively, is
    fail-silent on error/timeout
  - `pull_ff_only` success + failure (non-ff, dirty) mapped to typed result
- [ ] ⬜ **Task 1.2**: Implement `src/claude_code_hooks_daemon/utils/git_sync.py`
- [ ] ⬜ **Task 1.3**: Add `Timeout.GIT_FETCH_SESSION` / `GIT_PULL_SESSION`
  constants (reuse 30s network budget); no magic numbers.

### Phase 2: Handler (TDD)

- [ ] ⬜ **Task 2.1**: Write failing tests
  `tests/unit/handlers/session_start/test_git_upstream_checker.py`
  - init (id/priority/terminal/tags)
  - `matches()`: SessionStart new-session only; skips resume; enabled flag
  - `handle()` per mode: warn / agent-pull / auto-pull
  - silent paths: in-sync, not-a-repo, no-upstream, detached HEAD
  - auto-pull degrade-to-warn on non-ff / dirty tree
  - unknown mode falls back to `warn` (fail-safe, logged)
- [ ] ⬜ **Task 2.2**: Implement
  `src/claude_code_hooks_daemon/handlers/session_start/git_upstream_checker.py`
  - `get_claude_md()` guidance + `get_acceptance_tests()`

### Phase 3: Wiring

- [ ] ⬜ **Task 3.1**: `HandlerID.GIT_UPSTREAM_CHECKER` meta in `constants/handlers.py`
- [ ] ⬜ **Task 3.2**: `Priority.GIT_UPSTREAM_CHECKER` in `constants/priority.py`
- [ ] ⬜ **Task 3.3**: Export in `handlers/session_start/__init__.py`
- [ ] ⬜ **Task 3.4**: Register in `.claude/hooks-daemon.yaml` (enabled, mode: warn)
- [ ] ⬜ **Task 3.5**: Add to `daemon/init_config.py` fresh-install defaults
- [ ] ⬜ **Task 3.6**: Config schema/validation accepts the new options

### Phase 4: Integration, QA, docs

- [ ] ⬜ **Task 4.1**: Response-validation + dogfooding tests pass
- [ ] ⬜ **Task 4.2**: `./scripts/qa/run_all.sh` green (95%+ coverage)
- [ ] ⬜ **Task 4.3**: Daemon restart RUNNING; probe via `nc` on the live socket
- [ ] ⬜ **Task 4.4**: `generate-docs` to refresh `.claude/HOOKS-DAEMON.md`

### Phase 5: Live verify

- [ ] ⬜ **Task 5.1**: Simulate a behind branch; confirm warn/agent-pull/auto-pull
  behaviour against the live daemon.

## Technical Decisions

### Decision 1: Full fetch = `git fetch --all --prune`

`git fetch` alone updates all remote-tracking refs of the default remote;
`--all` covers every configured remote and `--prune` drops deleted branches —
this is the "full fetch" the user asked for.

### Decision 2: `auto-pull` uses `--ff-only` on a clean tree only

Deterministic and safe: never creates a merge commit, never conflicts, never
touches a dirty tree. Any non-ff / dirty situation degrades to a `warn` message
so the operator resolves it deliberately (FAIL SAFE, PROPER NOT QUICK).

### Decision 3: Default mode `warn`, enabled by default

The user said a pull should be "strongly advised"; pulling automatically is
opt-in. Enabled by default (in `warn`) matches sibling git SessionStart handlers
(`git_filemode_checker`, `gitignore_safety_checker`) and `version_check`, which
also do work on new sessions. Downstream projects can disable or change mode.

## Success Criteria

- [ ] Full fetch runs on new sessions; behind-count is accurate.
- [ ] All three modes behave as specified; auto-pull is safe.
- [ ] Silent when up to date / not applicable.
- [ ] QA green, daemon RUNNING, dogfooded, docs regenerated.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only. -->

- Plan created; recovery cron dffb57b7 (hourly :37, non-durable).
