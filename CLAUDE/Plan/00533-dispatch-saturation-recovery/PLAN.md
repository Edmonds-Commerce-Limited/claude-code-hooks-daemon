# Plan 00533: dispatch saturation recovery

**Status**: In Progress
**Created**: 2026-10-19
**Owner**: dev
**Priority**: High
**GitHub Issue**: #124
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Issue #124 reports a client host where about 12 concurrent sessions shared one
daemon under heavy load. The process-wide `BoundedDispatcher`
(`core/bounded_dispatch.py`) admits `DISPATCH_MAX_INFLIGHT = 16` chains, a
module constant, and refuses the 17th at once (non-blocking acquire). For about
six minutes every chain was refused as "dispatch pool saturated": Stop chains
holding SAFETY+BLOCKING handlers failed closed and looped the agents, and the
documented-exempt recovery command `hooks-daemon restart` was denied too,
because the client carve-out in `init.sh` (`_is_daemon_recovery_command`) runs
only on a transport failure, while a saturated daemon sends a well-formed deny.
The straggler watchdog never fired, as live slow chains are not stragglers. Every
restart under load escalated to SIGKILL: the server waits up to 5 s for active
requests and the CLI's SIGTERM grace is the same 5 s (`Timeout.SOCKET_CONNECT`).

Scope is the Fable stand-in ruling
([RULING-fable.md](RULING-fable.md)), not an owner ruling.

## Goals

- The exact daemon-recovery command always gets through a saturated pool.
- `max_inflight` is configurable (shipped default stays 16), and a full pool
  waits a short deadline for a slot before refusing.
- Sustained saturation is logged as a rate-limited WARNING with the in-flight
  count and duration.
- A daemon stop under load is clean: the CLI's SIGTERM grace exceeds the
  server's active-request drain.

## Non-Goals

- Stop/SubagentStop semantics under saturation: stays fail-closed; changing it
  weakens `cron_stop_enforcer` and the other SAFETY+BLOCKING Stop handlers, so it
  is the owner's decision.
- Raising the shipped default above 16 (a capacity decision needing host data).
- A watchdog that restarts or sheds on saturation, upgrade handover without a
  live-daemon rebuild, and a persistent log: split to follow-up plans.

## Tasks

### Phase 1: Recovery and capacity

- [ ] ⬜ **Task 1.1**: Red test, then let the exact recovery command through a
  saturated pool: daemon-side before dispatch, and client-side by treating a
  saturation deny of a recovery command like a transport failure.
- [ ] ⬜ **Task 1.2**: Red test, then a configurable `max_inflight` and a
  bounded wait for a slot instead of an instant refusal.
- [ ] ⬜ **Task 1.3**: Red test, then a rate-limited sustained-saturation WARNING.
- [ ] ⬜ **Task 1.4**: Red test, then a SIGTERM grace longer than the
  active-request drain.

### Phase 2: Close out

- [ ] ⬜ **Task 2.1**: Release note in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`
  and config docs for the new option.
- [ ] ⬜ **Task 2.2**: File the follow-up plans for the split items; record the
  Stop-semantics question as `agent-needs-human`.

## Success Criteria

- [ ] Each change has a test that failed before it.
- [ ] The release note for the new option and behaviour is in the pending-release
  holding area `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.
- [ ] Targeted QA green on the merged head; CI green.

## Delivery & Milestones

- <!-- delivery commit hashes -->
