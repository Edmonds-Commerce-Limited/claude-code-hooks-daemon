# Plan 00536: persistent daemon saturation log

**Status**: Not Started
**Created**: 2026-10-19
**Owner**: dev
**Priority**: Low
**GitHub Issue**: #124 (follow-up, split out by the Fable stand-in ruling in [Plan 00533](../00533-dispatch-saturation-recovery/RULING-fable.md))
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #124's reporter could not post-mortem the outage: the daemon's logs are
held in memory and every record was lost on each restart. Plan 00533 added a
sustained-saturation WARNING, but it lives in the same in-memory log. An outage
that ends in a restart (the usual way out) therefore leaves no evidence behind.

## Goals

- Saturation episodes, straggler restarts and forced (SIGKILL) stops are
  recorded somewhere that survives a daemon restart: a small, bounded,
  rotating journal under the daemon's untracked state directory.
- A command prints it, so an agent or a human can read it after recovery.

## Non-Goals

- Persisting the whole daemon log. Only the events needed for a post-mortem.

## Tasks

### Phase 1: Journal

- [ ] ⬜ **Task 1.1**: Red test, then a bounded, rotating journal (size-capped,
  atomic appends) written by the saturation warning, the straggler watchdog and
  the stop path.
- [ ] ⬜ **Task 1.2**: Red test, then a CLI verb that prints it.

## Success Criteria

- [ ] A saturation episode is readable after a daemon restart.
- [ ] A release note in the pending-release holding area
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/` names the journal and the verb.

## Delivery & Milestones

- <!-- delivery commit hashes -->
