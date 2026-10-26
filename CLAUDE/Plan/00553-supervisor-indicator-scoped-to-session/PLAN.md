# Plan 00553: supervisor indicator scoped to session

**Status**: In Progress
**Created**: 2026-10-26
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #140

## Overview

The status-line `supervisor_indicator` handler shows the green "armed" top hat for a session that no supervisor oversees. Re-verified on `main` after v3.71.0:

- `handle()` never reads `hook_input`, so it has no session to scope by.
- `_scan_for_supervisor` walks every `/proc` entry and accepts the first process carrying the `claude-supervise` marker.
- Step 1 trusts the per-project status-file pid. That file is per project, not per session, and in a container setup its pid can be from another PID namespace.
- `_activate` memoises the identity on the handler instance, which one daemon shares across every session of the project.

So any supervisor visible in the host's process table turns every session's indicator green. The indicator then claims a safety net (auto-compact) the session does not have.

## Goals

- A supervisor counts for the rendered session only when that session's id appears in the environment of a process in the supervisor's own descendant tree. This is the ownership rule Plan 00551 applies on the supervisor side (own session ids come only from its child tree).
- The ownership check applies to both resolution paths: the status-file pid and the `/proc` scan.
- The memoised identity is keyed by `session_id`, so one session's result never colours another's.
- No session id in the input, or ownership that cannot be established (an unreadable environ, EPERM), means not green. The handler falls back to the existing orange or none state, fails silent, and never raises.
- Plan 00171's throttles (negative cache, walk interval) keep the per-render cost bounded.

## Non-Goals

- Any change to the ccy supervisor (`.claude/ccy/claude-supervise.py`) or its status file format.
- The send-side focus hold (Plan 00538) and foreground identity (Plan 00160).

## Tasks

### Phase 1: Fix

- [ ] ⬜ **Task 1.1**: Write failing tests first:
  - the issue's case: an unrelated `claude-supervise` process plus an unsupervised session gives no green;
  - a supervisor whose descendant carries the session id gives green;
  - two sessions on one handler instance get independent results;
  - an unreadable environ gives not green;
  - the status-file pid path is held to the same ownership rule.
- [ ] ⬜ **Task 1.2**: Implement the ownership check and the per-session memo. Reuse or share the Plan 00551 descendant-environ logic rather than writing a second copy, if it can be imported from daemon code. Otherwise put a small shared helper under `utils/`.
- [ ] ⬜ **Task 1.3**: Update the docs (`CLAUDE/Architecture/StatusLine.md` supervisor section, the handler guidance) and add a release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] The issue's reproduction renders no green top hat for an unsupervised session, proven by a test that failed before the fix.
- [ ] A session genuinely under a supervisor still renders green, proven by a test.
- [ ] The release note is recorded in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Delivery & Milestones

- <!-- delivery commit hashes -->
