# Plan 00631: teamchat role probe core

**Status**: In Progress
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (a) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
sections 2-6. The one resolver every other child consumes: which teams this
session holds a seat in, and the handle, role and duty in EACH team, read from
`teamchat whoami --json` (Q1 settled). v2 only. It never raises; it returns
absent when there is no team, and role and duty `unknown` when a team exists
but the probe gives no answer.

The `whoami --json` contract is pending fedora-desktop's `v2-seat-duty` merge:
per held seat exactly four keys, `team`, `handle`, `role`, `duty`. Code and
fixtures use only those four keys. The builder is already working against this
shape on a branch based on `a4fed6cbe399e3308` (as reported by the coordinator;
not in this clone).

## Goals

- `SeatContext` with `role_in(team)`, `duty_in(team)` and `any_duty(value)`;
  no session-wide role. Role is the wire set (`coordinator | worker | probe`,
  `null` is unknown); duty is an open set (`null` is unknown).
- Absent and no-answer cases kept apart (DESIGN.md section 4), with a 60 s TTL.
- `TEAMCHAT_RUNTIME` and `TEAMCHAT_KIT` reach the daemon through the payload
  stamp (precedent: `SESSION_HOSTNAME`).
- A role gate primitive for handlers, composed with `handler_scope` (main
  thread only).

## Non-Goals

- Any v1 detection; opening anything under teamchat's seat store, state root or
  run directory (invariant 5); decoding `status.json`; any behaviour (sibling
  plans); seat placement or a run lock (teamchat's).

## Tasks

### Phase 1: Shape and RED fixtures

- [ ] 🔄 **Task 1.1**: Record the merged `whoami --json` contract and its F44
  merge commit in the umbrella DESIGN.md section 2; confirm exit code 65.
  Prove the daemon shares the session's mount namespace and user (so the run
  directory resolves), or move the `whoami` call hook-side and stamp its JSON
  (DESIGN.md section 5). Contract and exit 69 recorded (v2 branch
  `fe67f23c3`); F44 hash, exit 65 and the namespace proof still open.
- [x] ✅ **Task 1.2**: RED (`tests/support/teamchat.py`,
  `tests/unit/utils/test_teamchat_seat.py`). Absent fixtures first (no `TEAMCHAT_RUNTIME`; exit
  69; empty `teams`); v2-only proof (`PINGBUS_MEMBERSHIP=off`); no-answer
  fixtures (exit 65, other non-zero, timeout, malformed JSON, unknown `v`,
  `TEAMCHAT_KIT` unset); role and duty fixtures (multi-team, duty `host`,
  `role: null`, `role: probe`, unknown duty, role change, one team listed
  twice raises an advisory); sub-agent fixture.

### Phase 2: Resolver and payload stamp

- [x] ✅ **Task 2.1**: GREEN (`src/claude_code_hooks_daemon/utils/teamchat_seat.py`). `SeatContext` and the single teamchat module,
  calling `$TEAMCHAT_KIT/bin/teamchat whoami --json` with the stamped
  `TEAMCHAT_RUNTIME`, bounded timeout.
- [x] ✅ **Task 2.2**: Stamp `TEAMCHAT_RUNTIME` and `TEAMCHAT_KIT` onto the
  payload (init.sh and server.py), never overwriting an existing value.
- [x] ✅ **Task 2.3**: Diagnostic CLI printing the resolved context or "absent"
  with the reason (`hooks-daemon team-seat`, `daemon/team_seat_cli.py`);
  `team_seat` config block (detection, TTL).
- [ ] 🔄 **Task 2.4**: Targeted QA green locally; the full pass is the PR's CI.

### Phase 3: Role gate primitive

- [x] ✅ **Task 3.1**: TDD the gate (`utils/team_role_gate.py`: `role_gate`, `duty_gate`): per named team for acts that name one,
  `any_duty` for acts that name none; main thread only.
- [x] ✅ **Task 3.2**: Invariant tests (role never relaxes a guard; no file
  opened under the seat store, state root or run directory; no v1 path).
  Targeted QA green.

## Dependencies

- Umbrella 00630. The final `whoami --json` contract (fedora-desktop
  `v2-seat-duty`, Plan 00209). Every sibling child depends on this plan.

## Success Criteria

- [x] The absent fixtures produce no output, no error, no config need.
- [x] A multi-team fixture resolves different roles per team.
- [x] An unknown duty or `probe` role switches nothing on.
- [x] A role change takes effect within one TTL (test).
- [x] Release-bound items (config block, payload fields, CLI) recorded in the
  pending-release holding area: the `team_seat` block in
  `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`, and the payload
  fields and `team-seat` command in
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/086-teamchat-role-probe-and-team-seat-command.md`.
  No truth-change: nothing previously true becomes false.

## Open items

- Task 1.1: the F44 merge hash of the `whoami --json` contract, confirmation
  of exit 65, and the proof that the daemon shares the session's mount
  namespace and user. No teamchat source is readable here; until proved, the
  probe degrades to role unknown (guards stay armed) when `whoami` cannot run.

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet (whoami, duty).
