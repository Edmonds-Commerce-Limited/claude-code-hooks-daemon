# Plan 00634: HUMAN-approval check with a cited questions id

**Status**: In Progress
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
runs `$TEAMCHAT_KIT/bin/teamchat verify <id> --room questions` with the stamped
`TEAMCHAT_RUNTIME`. It passes only if the line is in the questions room, its
sender is a declared human of T, and the seat's role in T is coordinator.
Anything else is a deny with the reason, never a pass; there is no `history`
fallback. Nothing under teamchat's seat store or run directory is opened.

Coded against the fedora-desktop issue 369 `verify` contract as its peer
relayed it (one `verified` record: room, sender, `human`, `question`,
`sent_ms`; documented exit codes). It is not yet checked against a live
teamchat (Task 2.4); anything off that contract refuses.

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
- [x] ✅ **Task 2.2**: Guard `human_approval_check`, mode off | advise | block
  (advise by default). Targeted QA green.
- [x] ✅ **Task 2.3**: `DEFAULT_VERIFIER` is `TeamchatVerifyCli`, coded against
  the issue 369 contract as the peer relayed it
  ([subagent-reports/261124-fedora-desktop-contract-reply.md](subagent-reports/261124-fedora-desktop-contract-reply.md)):
  argv `verify <id> --room questions`, one `verified` record, the exact 13
  keys, exits 23/22/20/14 mapped, anything else refused. Wired on the owner's
  instruction with P1 off, which is safe only because the mode is `advise`.
  Builder report:
  [subagent-reports/261124-task-2-3-and-p2-verify-and-subagents.md](subagent-reports/261124-task-2-3-and-p2-verify-and-subagents.md).
- [ ] ⬜ **Task 2.4**: Live check of the verify call from a v2 seat (argv
  order, the value of `v`, the types of `item`, `from`, `body_sha256`).

### Preconditions for ever defaulting `mode: block`

From the independent review
([subagent-reports/261123-opus-independent-review-pr225.md](subagent-reports/261123-opus-independent-review-pr225.md)).
Owner ruling (2026-11-24): the check stays advise-only; nothing here is to be
flipped to block or defaulted on.

- [ ] 🔄 **P1 (review finding 1), bind the approval**: built OFF behind
  `require_question`, `max_line_age_seconds` and `single_use_cites` (owner
  question O4). Default unchanged: any human questions-room line passes.
- [x] ✅ **P2 (review finding 2), arm delegated threads**: a sub-agent is armed
  only when a held seat is DECLARED coordinator, and is judged as that seat
  (`role_gate(..., include_subagents=True)`, wired for this guard only).
  **Known collision for a later block flip**: `R-BRANCH-SUBAGENT-STOP-GUARD`
  refuses a sub-agent stop that leaves unpushed commits, so a coordinator
  seat's sub-agent in `block` mode could be unable either to push or to stop.
  It needs a hand-over route (e.g. sub-agents push only their own agent
  branch); the owner has not decided. Advise mode creates no conflict.
- [ ] ⬜ **P3 (review finding 5), advise is annotation only**: `advise` allows
  every refusal (uncited, forged, wrong team, verify unavailable, handler
  error). It must not be read as protection; only `block` enforces.

## Open design points (owner ruling pending)

- **Q4, proposed**: the cite is a trailing shell comment
  `# human-approval team=<T> id=<$id>` on the Bash command.
- **Q5, proposed**: `coordinator_seats_only` (default on) arms coordinator
  seats and unreadable roles on the main thread; off arms every main-thread
  seat.
- **Gap, replay** (precondition P1): with the binding switches off (the
  default) replay is UNBOUNDED. The 300 s in-memory approval record only skips
  re-verification; once it lapses the same line passes again. Nothing reads
  the line's text, so a human "NO" in the questions room still verifies.
- **Gap, deletes**: a plain `git branch -d` is not an act (merged-only delete).
- **Gap, `git -C <dir>`**: a merge or main-moving command run with `-C` is
  judged against the hook cwd, not `<dir>`.
- **Gap, permission scope**: the permission act is the world-writable `chmod`
  only (`dangerous_permissions.sets_world_writable`).
- **Choice, `gh pr merge`**: always counts as a merge into main, because it
  lands on the PR base on GitHub whatever the local checkout; an unreadable
  current branch with a merge named also counts (fail closed).
- **Mode**: `advise` only (owner ruling). `advise` is annotation only.
- **Unverified here**: the relayed verify contract has not been run against a
  live teamchat (Task 2.4). The id grammar is the contract's
  `^\$[A-Za-z0-9_-]{43}$`.

## Dependencies

- Plan 00631 (role in T); fedora-desktop issue 369 (questions-room `verify`).
  Consumed by Plan 00632. Related Plan 00502.

## Success Criteria

- [x] No path counts a peer line or a role as approval (tests).
- [x] An unverifiable questions-room cite denies (test).
- [x] Absent-team fixture passes.
- [x] Release-bound items recorded in the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`,
  `release-notes/087-human-approval-check.md`,
  `release-notes/103-human-approval-check-verifies-cites-and-judges-coordinator-sub-agents.md`).

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet and issue 369.
