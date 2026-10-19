# Plan 00535: upgrade handover without live daemon rebuild

**Status**: Not Started
**Created**: 2026-10-19
**Owner**: dev
**Priority**: Medium
**GitHub Issue**: #124 (follow-up, split out by the Fable stand-in ruling in [Plan 00533](../00533-dispatch-saturation-recovery/RULING-fable.md))
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #124's timeline shows the upgrade script rebuilding the venv a running
daemon was using, and checking out the new source while that daemon still served
every session. The old daemon then reported "DAEMON VERSION CHANGED UNDERNEATH
THIS SESSION", and sessions met a mixed old/new tree until the restart. The
saturation that followed began within seconds of that restart.

## Goals

- An upgrade never rebuilds a venv, or checks out source, that a running daemon
  is executing from. Either stop the daemon first and start the new one after,
  or build the new tree aside and switch over atomically.
- Sessions never run against a mixed old/new tree during an upgrade.

## Non-Goals

- Dispatcher capacity and saturation behaviour (Plan 00533, Plan 00534).

## Tasks

### Phase 1: Establish

- [ ] ⬜ **Task 1.1**: Trace the upgrade path (skill `upgrade.sh` and the
  install modules it calls) and record each step that touches a tree a live
  daemon uses.

### Phase 2: Hand over cleanly

- [ ] ⬜ **Task 2.1**: Red test, then the chosen handover (stop-then-start, or
  aside-then-switch), with the daemon's own version-change detection as the
  check that it held.

## Success Criteria

- [ ] An upgrade test shows no request served from a mixed tree.
- [ ] A release note in the pending-release holding area
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` describes the handover.

## Delivery & Milestones

- <!-- delivery commit hashes -->
