# Plan 00634: HUMAN-approval check with a cited questions id

**Status**: 🔄 In Progress
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

- [x] ✅ **Task 1.1**: Fixtures shaped on the issue 369 answer (provisional):
  valid human id in the questions room passes; peer sender, main-room line,
  unknown id, binary missing, timeout, each non-zero exit all deny; another
  team's id denies; a seat not coordinator in T denies; a verified GO covers
  only its authorised classes and only inside its window; absent team
  unchanged.
- [ ] 🔄 **Task 1.2**: Q4 (cite passing) and Q5 (who is armed): proposed
  defaults implemented behind switches, **owner ruling pending** (see Open
  design points).

### Phase 2: Verifier and guard

- [x] ✅ **Task 2.1**: Verifier module `utils/human_approval.py`. Targeted QA
  green.
- [ ] ⬜ **Task 2.2**: Guard `human_approval_check`, mode off | advise | block
  (advise by default). Targeted QA green.
- [ ] ⬜ **Task 2.3**: Live verification once issue 369 lands; then swap the
  default verifier for `TeamchatVerifyCli` and confirm its argv and answer
  shape against the real contract.

## Open design points (owner ruling pending)

- **Q4, proposed**: the cite is a trailing shell comment
  `# human-approval team=<T> id=<$id>` on the Bash command.
- **Q5, proposed**: `coordinator_seats_only` (default on) arms coordinator
  seats and unreadable roles on the main thread; off arms every main-thread
  seat.
- **Gap, sub-agents**: under the Q5 default a coordinator's sub-agent is not
  armed, so a sub-agent's push, delete or merge is unguarded. Arming it would
  deny every such act, because no sub-agent can pass.
- **Gap, replay**: one verified human line authorises any act of the cited
  classes until its in-memory approval record lapses (TTL 300s). Nothing
  binds the line's text to the specific act.
- **Unverified here**: the `verify --json` flag, the answer shape, and the
  event id grammar (no `:` accepted; fails closed if real ids carry one).

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
