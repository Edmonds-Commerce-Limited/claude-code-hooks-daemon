# Plan 00630: coordinator-level skills, ccy-teams aware

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner order, relayed by the lts-infra coordinator: start a formal push to
build coordinator-level skills into the hooks daemon. The daemon becomes
ccy-teams AWARE but not DEPENDENT. When it detects that the current seat is a
pingbus team coordinator (or a host seat), role-specific behaviours switch on.
When no team is detected, nothing changes and nothing errors.

Today the coordinator's conduct is ad hoc. That covers conduct on the bus,
HUMAN-id verification before destructive acts, gating peers' branches (merge,
Layer 1+2 QA, push if green), departure and return, seat liveness, the
usage-limit response, the host-seat lane guard and thread hygiene. This plan
codifies them as detection, skills, advisories and guards. The supervisor's
auto-answer for Claude Code's rate-limit dialog is Plan 00523's. This plan
references it and does not duplicate it.

The order's lts-infra inputs (the retro and the readiness checklist) and
fedora-desktop Plan 00263 D3 could not be read from this seat, so Phase 0
ingests them. fedora-desktop issue 367 was read, and so were Plans 00207
(more roles, including a host-side `deployer`) and 00209 (bus v2 `teamchat`,
which replaces v1 `pingbus`). Both shape the detection design. The design, the
observed detection signals, the behaviour matrix and the open questions are in
[DESIGN.md](DESIGN.md). The pre-filing dedupe check is in
[subagent-reports/](subagent-reports/261123-hooks-daemon-plan-dedupe-scout-haiku.md).

## Goals

- One resolver answers "which teams, which role, which seat kind" for a
  session. It never raises. It returns absent when no team is configured, and
  `role: unknown` when a team is configured but its state cannot be read
  (DESIGN.md section 4).
- Each behaviour in DESIGN.md section 7 is gated on the detected role and is
  individually configurable.
- A session with no team seat behaves exactly as it does today. An
  absent-teams fixture proves this for every handler the plan adds.
- The safety invariants in DESIGN.md section 8 are each pinned by a test.

## Non-Goals

- The rate-limit dialog auto-answer (Plan 00523).
- Changing pingbus or the ccy kit. A `pingbus whoami --json` request goes
  upstream as a request only (Q1).
- Claude Code's own experimental agent teams (`CLAUDE/AgentTeam.md`).
- Treating any peer message, or a detected role, as authority.

## Tasks

### Phase 0: Inputs and owner rulings

- [ ] ⬜ **Task 0.1**: Ingest lts-infra Plan 00158 retro sections 2-3 and its
  readiness checklist. Record the owner GO and what it covers in JOURNAL/ (Q8).
- [ ] ⬜ **Task 0.2**: Ingest fedora-desktop Plan 00263 D3 (not on that
  repository's default branch at filing). Fill in the "(spec from Phase 0)"
  rows of DESIGN.md section 7.
- [ ] ⬜ **Task 0.3**: Get the owner's rulings on Q1-Q11 (DESIGN.md section 12)
  and record them in DESIGN.md.
- [ ] ⬜ **Task 0.4**: Confirm that Plan 00523 is the rate-limit auto-answer
  build the order calls "already requested". The mapping was inferred.

### Phase 1: Detection core (no behaviour)

- [ ] ⬜ **Task 1.1**: RED. Write the absent-teams fixture and the degradation,
  role, multi-team, seat-kind, role-change and sub-agent fixtures (DESIGN.md
  section 11).
- [ ] ⬜ **Task 1.2**: GREEN. Implement `SeatContext` and the resolver behind
  a per-bus-generation adapter (v1 `pingbus` now, v2 `teamchat` later) for
  the Q1 source, with a short-TTL cache.
- [ ] ⬜ **Task 1.3**: Stamp the three `PINGBUS_*` variables onto the payload
  the same way `SESSION_HOSTNAME` is stamped (init.sh and server.py).
- [ ] ⬜ **Task 1.4**: Add a diagnostic CLI that prints the resolved
  SeatContext, or "absent" with the reason.
- [ ] ⬜ **Task 1.5**: Add the `team_seat` config block (DESIGN.md section 9).
  An absent block means detection is on and every behaviour is at its Q2
  default.
- [ ] ⬜ **Task 1.6**: Run targeted QA (`./scripts/qa/llm_qa.py changed`) and
  get it green.

### Phase 2: Role gate primitive

- [ ] ⬜ **Task 2.1**: TDD a role gate that handlers declare, composed with
  `handler_scope` so that it applies to the main thread only.
- [ ] ⬜ **Task 2.2**: Add invariant tests for DESIGN.md section 8: a role
  never relaxes a guard, and the `token` file is never opened. Run targeted QA.

### Phase 3: Coordinator guidance (B1, B3, B4, B6)

- [ ] ⬜ **Task 3.1**: Write the skills in the home ruled by Q3.
- [ ] ⬜ **Task 3.2**: Add role-conditional SessionStart and Stop context that
  names those skills. Prove it is silent on the absent fixture. Run targeted QA.

### Phase 4: Enforcement (B2, B8, then B5)

- [ ] ⬜ **Task 4.1**: Thread-hygiene advisory (B8), if Q10 keeps it in the
  daemon. Run targeted QA.
- [ ] ⬜ **Task 4.2**: HUMAN-id verification guard (B2), built on the Q4
  mechanism, advisory first. Run targeted QA.
- [ ] ⬜ **Task 4.3**: Seat-liveness advisory (B5). Run targeted QA.

### Phase 5: Host-seat lane guard (B7)

- [ ] ⬜ **Task 5.1**: TDD the guard from the spec ingested in Task 0.2,
  advisory first. Run targeted QA.

### Phase 6: Supervisor actions (Q6) and live verification

- [ ] ⬜ **Task 6.1**: Supervisor side of B5 and B4, if Q6 rules for it. Follow
  the hot-reload verification rule in `.claude/ccy/`.
- [ ] ⬜ **Task 6.2**: Verify live in a real coordinator seat and in a seat
  with no team. Record both in JOURNAL/.
- [ ] ⬜ **Task 6.3**: Promote guards from advise to block where the owner
  rules. Update docs and the pending-release holding area.

## Dependencies

- Related: Plan 00523 (Not Started), which owns the rate-limit auto-answer.
- Related: Plan 00479 (Blocked), the usage signal behind B6.
- Related: Plan 00470 (Blocked), session liveness, which overlaps B4 and B5.
- Related: Plan 00501 (Blocked), session modes (Q7).
- Related: Plan 00502 (Not Started), the merge gate, related to B3.
- Related: Plan 00487 (Complete), the supervisor plugin API (Q6).
- Related: fedora-desktop Plans 00207 (team roles) and 00209 (bus v2). The
  resolver needs one adapter per bus generation.
- Phases 3-6 are blocked on Phase 0. Phases 1-2 can start once Q1, Q2 and Q9
  are ruled.

## Success Criteria

- [ ] The absent-teams fixture passes against every handler this plan adds,
  with no output, no error and no config needed.
- [ ] Each invariant in DESIGN.md section 8 has a passing test.
- [ ] Detection is re-resolved, so a role change takes effect within one TTL,
  and the role-change test proves it.
- [ ] Every behaviour B1-B8 is either shipped behind its config key or
  recorded as declined by the owner.
- [ ] Live verification in a coordinator seat and in a seat with no team is
  recorded in JOURNAL/.
- [ ] This project's targeted QA gate passes for every merged phase.
- [ ] Every release-bound consequence (new config block, handlers, skills,
  payload field) is recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed (no delivery yet)
