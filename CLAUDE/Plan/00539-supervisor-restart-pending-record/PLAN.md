# Plan 00539: supervisor restart pending record

**Status**: In Progress
**Created**: 2026-10-20
**Owner**: dev
**Priority**: Medium
**GitHub Issue**: #127
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #127: when a supervisor plugin returns `ExitForRestart`, the ccy supervisor
(`.claude/ccy/claude-supervise.py`) types `/exit` and keeps the pending restart
only in memory. `RestartCoordinator.finish()` writes `restart-request.json` and
`restarted.json` only after the child has exited. Claude Code runs SessionEnd
hooks while the child is exiting, so a SessionEnd hook cannot tell a scheduled
restart from a genuine exit. A hook that announces departures therefore
announces every restart.

Triage:
[subagent-reports/261020-issue127-triage-opus.md](subagent-reports/261020-issue127-triage-opus.md).
This plan builds on [Plan 00537](../Completed/00537-supervisor-holds-sends-off-main-focus/PLAN.md),
issue #125. Its ruling says a restart is persisted only when `/exit` was actually
sent, never on a focus hold.

## Goals

- **A private restart-pending record.** It carries the own session id, the
  plugin, the reason, the requested time and a wall-clock deadline. The
  in-memory deadline is monotonic, so it cannot be reused. The record is
  written atomically with mode 0600 in the supervisor's existing private state
  directory. It is written after every refusal in `request()`, the #125 focus
  hold included, and before `/exit` is typed. A refused or held restart leaves
  no record.
- **The record is removed** when typing fails (the error is then re-raised), in
  `abandon()`, and in `finish()`. The resumed session keeps the same session id,
  so a leftover record would mislabel a later genuine exit.
- **The child knows where to look.** The record's path is exported to the child
  at spawn as `CCY_SUPERVISOR_RESTART_PENDING`, beside
  `CCY_SUPERVISOR_STATE_DIR`.
- **A documented reader contract.** A hook treats its session as restarting
  only when the record exists, names its own session id and its deadline has
  not passed.

## Non-Goals

- A daemon-side SessionEnd consumer. None exists today; this plan only gives
  hooks the signal.
- Changing the refusal rules, the abandon wait, or #125's focus hold.

## Tasks

### Phase 1: Record

- [ ] ⬜ **Task 1.1**: Red tests, then write the record in `request()` after the
  last refusal and before `_perform_injection`. Tests: the record exists between
  `request()` and `finish()`/`abandon()`; it is absent after every refusal
  branch, including the focus hold, and when typing fails; it names the own
  session id; its deadline is wall-clock; the file is mode 0600.
- [ ] ⬜ **Task 1.2**: Red tests, then remove the record in `abandon()` and
  `finish()`.
- [ ] ⬜ **Task 1.3**: Red test, then export `CCY_SUPERVISOR_RESTART_PENDING` in
  the child's environment at spawn.

### Phase 2: Close out

- [ ] ⬜ **Task 2.1**: Document the reader contract where the supervisor's
  restart and plugin contract is documented. Add a release note in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Success Criteria

- [ ] Each change has a test that failed before it.
- [ ] No refusal path, focus hold included, leaves a record behind.
- [ ] A release note is in the pending-release holding area
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] Targeted QA is green on the merged head, and CI is green.

## Delivery & Milestones

- <!-- delivery commit hashes -->
