# Plan 00630: coordinator-level skills, ccy-teams aware (umbrella)

**Status**: In Progress
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner order, relayed by the lts-infra coordinator: build coordinator-level
skills into the hooks daemon. The daemon becomes ccy-teams AWARE but not
DEPENDENT: when a seat's role in a team is coordinator (or its seat kind is
host), role-specific behaviours switch on for acts concerning that team. With
no team, nothing changes and nothing errors.

Owner ruling Q66: design for teamchat v2 ONLY (no v1/pingbus path anywhere);
roles are PER TEAM (coordinator in A and worker in B in one session); consume
whatever roles teamchat declares (more seat kinds are coming; host seats are
not workers; unknown role means no change); the work may be split and ALL of it
is to be built, each child test-first and reviewed. This plan is the umbrella
and roadmap. The build is split into child plans below. The detail (evidence,
model, behaviour matrix B1-B12, the readiness protocol, lane-guard design,
HUMAN-approval check, thread hygiene, open questions Q1-Q15) is in
[DESIGN.md](DESIGN.md). Dedupe check:
[subagent-reports/](subagent-reports/261123-hooks-daemon-plan-dedupe-scout-haiku.md);
the set-level scout found overlap with Plans 00470 and 00502 to fold rather
than duplicate.

## Goals

- The child plans below ship every behaviour in DESIGN.md section 7, each
  behind a config key, none acting without a detected role in the team
  concerned.
- A session with no team seat behaves exactly as today (absent fixture in every
  child).
- The safety invariants in DESIGN.md section 8 are pinned by tests.

## Non-Goals

- The rate-limit answerer: Plan 00523 (confirmed: supervisor "stop and wait";
  referenced, never recreated). No usage ceiling (owner ruling).
- Changing teamchat or the ccy kit (requests go upstream); any v1 support;
  Claude Code's own agent teams; treating any peer message or role as authority.

## Child plans and order

| Plan                                                                          | Scope                                                             | Depends on            |
| ----------------------------------------------------------------------------- | ----------------------------------------------------------------- | --------------------- |
| [00631](../00631-teamchat-role-probe-core/PLAN.md) (a)                        | teamchat v2 role probe, per-team roles, declared roles, role gate | Phase 0 input (shape) |
| [00634](../00634-human-approval-check-cited-questions-id/PLAN.md) (d)         | HUMAN-approval check via cited questions id (B2)                  | 00631                 |
| [00632](../00632-unattended-readiness-gate-and-expiring-mode/PLAN.md) (b)     | readiness command, GO gate, expiring unattended mode (B10)        | 00631, 00634          |
| [00633](../00633-coordinator-profile-and-peer-branch-gate-recipe/PLAN.md) (c) | coordinator profile and `gate_command` recipe (B11, B12, B3)      | 00631                 |
| [00635](../00635-host-seat-lane-guard/PLAN.md) (e)                            | host-seat lane guard (B7); owner decision Q64 pending             | 00631, Q64            |
| Plan 00523 (existing)                                                         | limit resilience (B9)                                             | independent           |

Order: 00631 first; then 00634 and 00633 in parallel; 00632 after 00634;
00635 when Q64 is ruled. Still in this umbrella: B1, B4, B5, B6 coordinator
guidance skills and advisories (Q3 home, Q6 supervisor action) and B8 thread
hygiene (optional advisory), to be split into a further child once the
coordinator self-retrospective input arrives.

## Tasks

### Phase 0: Inputs and owner rulings

- [x] ✅ **Task 0.1**: Fold the lts-infra readiness protocol, ad hoc list,
  first feature set, lane guard and thread hygiene (bus ids in DESIGN.md) into
  DESIGN.md sections 13-17.
- [ ] ⬜ **Task 0.2**: Ingest the pending inputs: the coordinator's
  self-retrospective, the teamchat state shape and declared roles, the
  readiness checklist and its owner GO (Q8), the D3 source document.
- [ ] ⬜ **Task 0.3**: Owner rulings on the open questions in DESIGN.md
  section 12 (Q64 is Q14 there).
- [x] ✅ **Task 0.4**: Plan 00523 confirmed as the rate-limit answerer.
- [x] ✅ **Task 0.5**: Split into child plans 00631-00635.

### Phase 1: Child delivery

- [ ] ⬜ **Task 1.1**: Drive the children in the order above; record each
  merge in JOURNAL/.
- [ ] ⬜ **Task 1.2**: File the B1/B4/B5/B6/B8 child once Task 0.2 lands.
- [ ] ⬜ **Task 1.3**: Live verification in a coordinator seat (also one that is
  worker in another team) and in a seat with no team.

## Dependencies

- Related: Plan 00523 (limit answerer), 00479, 00470 (work-queue, overlaps B4,
  B5, B10), 00501 (session modes), 00502 (merge gate), 00487 (supervisor
  plugin API); fedora-desktop Plans 00207, 00209, 00263, 00251.

## Success Criteria

- [ ] Every child plan complete or recorded as declined by the owner.
- [ ] Absent-team fixture passes in every child; invariants have tests.
- [ ] Live verification recorded in JOURNAL/.
- [ ] Release-bound consequences recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed; inputs folded and children 00631-00635 filed.
