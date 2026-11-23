# Plan 00631: teamchat role probe core

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (a) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
sections 3-6 and 4a. The one resolver that every other child consumes: which
teams this session holds a seat in, the role and seat kind in EACH team. v2
(`teamchat`) only: no v1/pingbus path, adapter or fallback (owner ruling Q66).
It never raises, returns absent when no team is configured, and role
`unknown` when a team is configured but unreadable.

Roles are PER TEAM and an OPEN set: the probe passes through whatever roles
teamchat declares (coordinator, worker, deployer, reviewer, others) and has no
hard-coded pair. A role with no behaviour attached means no change.

## Goals

- `SeatContext` with `role_in(team)` and `seat_kind_in(team)`; no session-wide
  role exists in the API.
- Absent, degraded (`unknown`) and role-change behaviour as in DESIGN.md
  sections 4 and 11, with a short-TTL cache.
- The session's teamchat membership reaches the daemon through the payload
  stamp (precedent: `SESSION_HOSTNAME`).
- A role gate primitive for handlers, composed with `handler_scope` (main
  thread only), keyed on the team an action concerns.

## Non-Goals

- Any v1/pingbus detection, reading the member `token`, any behaviour (that is
  the sibling child plans), the rate-limit answerer (Plan 00523).

## Tasks

### Phase 1: Shape and RED fixtures

- [ ] ⬜ **Task 1.1**: Record the teamchat state shape and declared-role set
  (umbrella Phase 0 input from fedora-desktop Plan 00209) in the umbrella
  DESIGN.md; settle Q1 (source A or C).
- [ ] ⬜ **Task 1.2**: RED. Absent fixture first, then degradation, role,
  multi-team (coordinator in one, worker in another), seat-kind, unknown-role,
  role-change and sub-agent fixtures.

### Phase 2: Resolver and payload stamp

- [ ] ⬜ **Task 2.1**: GREEN. `SeatContext` and the single teamchat module.
- [ ] ⬜ **Task 2.2**: Stamp the teamchat membership variable onto the payload
  (init.sh and server.py), never overwriting an existing value.
- [ ] ⬜ **Task 2.3**: Diagnostic CLI printing the resolved context or "absent"
  with the reason; `team_seat` config block (detection, TTL).
- [ ] ⬜ **Task 2.4**: Targeted QA green.

### Phase 3: Role gate primitive

- [ ] ⬜ **Task 3.1**: TDD the handler role gate (per-team, main-thread only).
- [ ] ⬜ **Task 3.2**: Invariant tests (role never relaxes a guard; `token` never
  opened; no v1 path exists). Targeted QA green.

## Dependencies

- Umbrella 00630. Blocked on the teamchat state shape (Task 1.1); related
  fedora-desktop Plan 00209. Every sibling child depends on this plan.

## Success Criteria

- [ ] The absent fixture produces no output, no error, no config need.
- [ ] A multi-team fixture resolves different roles per team.
- [ ] An unknown declared role switches nothing on.
- [ ] A role change takes effect within one TTL (test).
- [ ] Release-bound items (config block, payload field, CLI) recorded in the
  pending-release holding area.

## Delivery & Milestones

- Plan filed.
