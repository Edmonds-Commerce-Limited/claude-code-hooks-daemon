# Plan 00489: supervisor in-container restart primitive

**Status**: Not Started
**Created**: 2026-10-03
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #71

## Overview

Plan 00487 added the supervisor plugin API and the exit-for-restart path that ccy's lifecycle plugin uses. Exit-for-restart replaces the whole container, which is what a NEW Claude Code version needs, because Claude Code is baked into the ccy image. Two pieces of the original draft serve a different case. The credential switch (fedora-desktop Plan 00146) only needs to restart `claude` inside the running container, with a new token in its environment.

By owner decision (Plan 00487, OWNER-DECISIONS.md D2), those two pieces, 00487's Tasks 1.4 and 1.5, move here, so that 00487 can close once its live test passes. The design source is the same owner-ruled draft: fedora-desktop Plan 00146, `UPSTREAM-REQUEST-supervisor-plugins-draft.md`.

## Goals

- An in-container `Restart` supervisor primitive, triggered by a plugin result: `/exit` at idle, wait for the child, then re-fork with `--resume <id>`.
- The host half: a `before_spawn` hook that lets a host-level plugin change the next child's environment within a strict allowlist. If it fails, the supervisor falls back to a plain respawn.

## Non-Goals

- The credential-switch plugin itself; that stays fedora-desktop Plan 00146's work.
- Anything that needs a new Claude Code binary; that is 00487's exit-for-restart.

## Tasks

### Phase 1: In-container restart (was 00487 Task 1.4)

- [ ] ⬜ **Task 1.1**: TDD the `Restart` primitive:
  - refuse when the session id is ambiguous;
  - send `/exit` through the injection path, with a deadline;
  - re-fork with `--resume <id>`, after stripping `--continue`, `-c`, `--resume`, `-r` and `--fork-session`;
  - abandon the restart if the child ignores `/exit`.

### Phase 2: Host half (was 00487 Task 1.5)

- [ ] ⬜ **Task 2.1**: TDD the host half. `before_spawn` runs in the forked child, behind the `env_keys` allowlist and the denylist, with a close-on-exec result pipe and a `SIGKILL` deadline. If it fails, the supervisor falls back to a plain respawn.

### Phase 3: Close out

- [ ] ⬜ **Task 3.1**: Document both in `CLAUDE/development/CcySupervisor.md`, write a release-notes callout, verify the worker hot reload, and merge under this repository's merge discipline.

## Success Criteria

- [ ] A plugin can restart `claude` inside a running container on the same session, with a changed environment, and the session never fails to start because of it.
- [ ] Every failure falls back to a plain respawn and gets one fixed-template notice.

## Delivery & Milestones

- Plan filed (carved out of Plan 00487 by owner decision D2).
