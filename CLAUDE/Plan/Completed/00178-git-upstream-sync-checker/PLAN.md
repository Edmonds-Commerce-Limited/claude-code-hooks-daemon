# Plan 00178: git upstream sync checker

**Status**: Complete
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

- [x] ✅ **Task 1.1**: Failing tests `tests/unit/utils/test_git_sync.py` (real bare
  remote + clone; 29 tests, 100% cov)
- [x] ✅ **Task 1.2**: Implemented `src/claude_code_hooks_daemon/utils/git_sync.py`
- [x] ✅ **Task 1.3**: Added `Timeout.GIT_FETCH_SESSION` / `GIT_PULL_SESSION`

### Phase 2: Handler (TDD)

- [x] ✅ **Task 2.1**: Failing tests
  `tests/unit/handlers/session_start/test_git_upstream_checker.py` (35 tests, 100% cov)
- [x] ✅ **Task 2.2**: Implemented
  `src/claude_code_hooks_daemon/handlers/session_start/git_upstream_checker.py`
  with `get_claude_md()` guidance + `get_acceptance_tests()`

### Phase 3: Wiring

- [x] ✅ **Task 3.1**: `HandlerID.GIT_UPSTREAM_CHECKER` meta in `constants/handlers.py`
- [x] ✅ **Task 3.2**: `Priority.GIT_UPSTREAM_CHECKER` in `constants/priority.py`
- [x] ✅ **Task 3.3**: Export in `handlers/session_start/__init__.py`
- [x] ✅ **Task 3.4**: Registered in `.claude/hooks-daemon.yaml` (enabled, mode: warn)
- [x] ✅ **Task 3.5**: Added to `daemon/init_config.py` fresh-install defaults
- [x] ✅ **Task 3.6**: Added to `.claude/hooks-daemon.yaml.example` (options accepted
  generically by the registry; example-config completeness test passes)

### Phase 4: Integration, QA, docs

- [x] ✅ **Task 4.1**: Response-validation + dogfooding tests pass (61)
- [x] ✅ **Task 4.2**: `./scripts/qa/llm_qa.py all` = 13/13 PASSED (10383 tests,
  95.3% cov) after fixing 4 findings (error_hiding exclusions, magic timeout,
  black, example-config completeness)
- [x] ✅ **Task 4.3**: Daemon restart RUNNING; live SessionStart probe silent (in sync)
- [x] ✅ **Task 4.4**: `generate-docs` refreshed `.claude/HOOKS-DAEMON.md` (SessionStart 11)

### Phase 5: Live verify

- [x] ✅ **Task 5.1**: Real-git end-to-end across all modes: warn / agent-pull /
  auto-pull (real fast-forward) / dirty-degrade / diverged-degrade

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
- Phase 1 (git_sync utility) delivered `49ff3430`.
- Phases 2–5 (handler + wiring + QA + live verify) delivered `440c1a65`;
  QA 13/13 (10383 tests, 95.3% cov), daemon RUNNING, all modes verified
  end-to-end against real git. (Daemon auto-regenerated CLAUDE.md guidance in
  `cb1c29f4`.)
