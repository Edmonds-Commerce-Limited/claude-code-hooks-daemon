# Plan 00634: HUMAN-approval check with a cited questions id

**Status**: Not Started
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (d) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md);
design in its [DESIGN.md](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md)
section 16. Before a destructive act (push, delete, permission change, merge to
main) the daemon requires a cited questions-room id and the team it names, and
runs `$TEAMCHAT_KIT/bin/teamchat verify --team <T> <id>` with the stamped
`TEAMCHAT_RUNTIME`. It passes only if the line is in the questions room, its
sender is a declared human of T, and the seat's role in T is coordinator.
Anything else is a deny with the reason, never a pass; there is no `history`
fallback. Nothing under teamchat's seat store or run directory is opened.

Coded against fedora-desktop issue 369: `verify` takes a questions-room id and
answers with room, sender, whether a declared team human, the attached `Q<n>`
and the text, with documented exit codes. Until it lands, today's `verify`
reads the main room only, so a questions-room cite cannot be verified and the
guard (and the 00632 GO gate) deny with that reason.

A verified readiness GO (Plan 00632) is accepted as the cite for the act
classes it authorised, until the window ends or the mode lapses; never for a
class it did not authorise.

## Goals

- Verifier module (one teamchat CLI call) and a short-lived approval record.
- PreToolUse guard on the destructive command set, advisory first.

## Non-Goals

- Treating a peer message or a role as approval (invariants 1-3), the
  readiness command, merge approval by agents (Plan 00502), a repo-to-team map.

## Tasks

### Phase 1: RED

- [ ] ⬜ **Task 1.1**: Fixtures shaped on the issue 369 answer: valid human id
  in the questions room passes; peer sender, main-room line, unknown id,
  binary missing, timeout, each documented non-zero exit all deny; another
  team's id denies; a seat not coordinator in T denies; a verified GO covers
  only its authorised classes and only inside its window; absent team
  unchanged. Settle Q4 (cite passing) and Q5 (workers).

### Phase 2: Verifier and guard

- [ ] ⬜ **Task 2.1**: Verifier module. Targeted QA green.
- [ ] ⬜ **Task 2.2**: Guard, advisory then block as the owner rules. Live
  verification once issue 369 lands. Targeted QA green.

## Dependencies

- Plan 00631 (role in T); fedora-desktop issue 369 (questions-room `verify`).
  Consumed by Plan 00632. Related Plan 00502.

## Success Criteria

- [ ] No path counts a peer line or a role as approval (tests).
- [ ] An unverifiable questions-room cite denies (test).
- [ ] Absent-team fixture passes.
- [ ] Release-bound items recorded in the pending-release holding area.

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet and issue 369.
