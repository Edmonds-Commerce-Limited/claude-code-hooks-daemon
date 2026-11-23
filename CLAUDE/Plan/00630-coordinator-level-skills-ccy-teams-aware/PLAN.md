# Plan 00630: coordinator-level skills, ccy-teams aware (umbrella)

**Status**: In Progress
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**GitHub Issue**: #221
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Owner order, relayed by the lts-infra coordinator: build coordinator-level
skills into the hooks daemon. The daemon becomes ccy-teams AWARE but not
DEPENDENT: when `teamchat whoami --json` says a seat's role in a team is
coordinator, or a held team's duty is `host`, role-specific behaviours switch
on. With no team, nothing changes and nothing errors.

Owner ruling Q66: design for teamchat v2 ONLY (no v1 path anywhere); roles are
PER TEAM; consume whatever roles and duties teamchat declares (unknown means no
change); all of it is to be built, each child test-first and reviewed. This
plan is the umbrella and roadmap. The detail (model, behaviour matrix B1-B12,
readiness protocol, lane guard, HUMAN check, open questions, the fedora-desktop
vet dispositions and the coordinator situations) is in [DESIGN.md](DESIGN.md).
Dedupe check:
[subagent-reports/](subagent-reports/261123-hooks-daemon-plan-dedupe-scout-haiku.md).
Vet: [subagent-reports/261123-fedora-desktop-vet.md](subagent-reports/261123-fedora-desktop-vet.md).

## Goals

- The child plans below ship every behaviour in DESIGN.md section 7, each
  behind a config key, none acting without a detected role or duty.
- A session with no team seat behaves exactly as today (absent fixture in every
  child).
- The safety invariants in DESIGN.md section 8 are pinned by tests.

## Non-Goals

- The rate-limit answerer: Plan 00523 (referenced, never recreated).
  Readiness sets no usage ceiling (owner ruling; whether 00479's ceiling is
  retired is Q16).
- Changing teamchat or the ccy kit (requests go upstream); any v1 support;
  Claude Code's own agent teams; treating any peer message or role as authority.

## Child plans and order

| Plan                                                                          | Scope                                                     | Depends on                      |
| ----------------------------------------------------------------------------- | --------------------------------------------------------- | ------------------------------- |
| [00631](../00631-teamchat-role-probe-core/PLAN.md) (a)                        | `whoami` probe: per-team role and duty, role gate         | final `whoami` contract (merge) |
| [00634](../00634-human-approval-check-cited-questions-id/PLAN.md) (d)         | HUMAN-approval check via `teamchat verify` (B2)           | 00631, fedora-desktop issue 369 |
| [00632](../00632-unattended-readiness-gate-and-expiring-mode/PLAN.md) (b)     | readiness command, GO gate, expiring unattended mode      | 00631, 00634, 00523 armed state |
| [00633](../00633-coordinator-profile-and-peer-branch-gate-recipe/PLAN.md) (c) | coordinator profile and `gate_command` recipe (B11, B12)  | 00631                           |
| [00635](../00635-host-seat-lane-guard/PLAN.md) (e)                            | host-seat lane guard (B7), by duty                        | 00631, Q64                      |
| [00636](../00636-coordinator-conduct-advisories-and-board/PLAN.md) (f)        | B1, B4-B6 and retrospective situations s3-s5, s7, s8, s11 | 00631                           |
| [00637](../00637-coordinator-no-value-remote-branch-retire/PLAN.md) (g)       | coordinator no-value remote branch retire (Q17, s1)       | 00631, 00620                    |
| Plan 00523 (existing)                                                         | limit resilience (B9) and its armed state                 | independent                     |

Order: 00631 first; then 00634, 00633 and 00636 in parallel; 00632 after
00634; 00635 (Q64 D3 settled: build the handler). B8 thread hygiene is suspended (DESIGN.md
section 17).

## Tasks

### Phase 0: Inputs and owner rulings

- [x] ✅ **Task 0.1**: Fold the lts-infra readiness protocol, ad hoc list,
  first feature set, lane guard and thread hygiene into DESIGN.md sections
  13-17.
- [ ] 🔄 **Task 0.2**: Ingest the pending inputs. Done: the approved duty spec,
  the vet, the coordinator self-retrospective summary (section 19). Pending:
  the final `whoami --json` contract and its F44 merge commit, issue 369, the
  readiness checklist and its owner GO (Q8).
- [ ] ⬜ **Task 0.3**: Owner rulings on the open questions in DESIGN.md
  section 12 (Q1 and Q11 settled).
- [x] ✅ **Task 0.4**: Plan 00523 confirmed as the rate-limit answerer.
- [x] ✅ **Task 0.5**: Split into child plans 00631-00636.
- [x] ✅ **Task 0.6**: Disposition every vet finding (DESIGN.md section 18).

### Phase 1: Child delivery

- [ ] ⬜ **Task 1.1**: Drive the children in the order above; record each
  merge in JOURNAL/.
- [x] ✅ **Task 1.2**: File the B1/B4/B5/B6 child (00636).
- [ ] ⬜ **Task 1.3**: Live verification in a coordinator seat (also one that is
  worker in another team), a host-duty seat, and a seat with no team.

## Dependencies

- Related: Plan 00523, 00479, 00470, 00501, 00502, 00487, 00474 (s12 niggles);
  fedora-desktop Plans 00207, 00209, 00263, 00251 and issues 367, 369.

## Success Criteria

- [ ] Every child plan complete or recorded as declined by the owner.
- [ ] Absent-team fixture passes in every child; invariants have tests.
- [ ] Live verification recorded in JOURNAL/.
- [ ] Release-bound consequences recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed; inputs folded and children 00631-00635 filed.
- Vet findings dispositioned; child 00636 filed from the self-retrospective.
