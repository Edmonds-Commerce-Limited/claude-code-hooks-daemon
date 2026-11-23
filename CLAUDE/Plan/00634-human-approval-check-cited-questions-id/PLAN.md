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
- [x] ✅ **Task 2.2**: Guard `human_approval_check`, mode off | advise | block
  (advise by default). Targeted QA green.
- [ ] ⬜ **Task 2.3**: Live verification once issue 369 lands; then swap the
  default verifier for `TeamchatVerifyCli` and confirm its argv and answer
  shape against the real contract. **Blocked on the preconditions below.**

### BLOCKING PRECONDITIONS for Task 2.3 and for ever defaulting `mode: block`

From the independent review
([subagent-reports/261123-opus-independent-review-pr225.md](subagent-reports/261123-opus-independent-review-pr225.md)).
None of these is done; each must land before the live verifier is wired or
`block` becomes the default.

- [ ] ⬜ **P1 (review finding 1), bind the approval**: a verified line must be
  bound to the act and to the line's text, and have a maximum line age. For
  example, single-use per cite, or the line must answer a `Q<n>` the
  coordinator posted that names the act. Today a coordinator can cite ANY
  human questions-room line, however old and whatever it says (even "NO").
- [ ] ⬜ **P2 (review finding 2), arm delegated threads**: sub-agents and
  in-process teammates are never armed, so a coordinator can hand a push,
  delete or merge to a sub-agent and bypass the check entirely.
- [ ] ⬜ **P3 (review finding 5), advise is annotation only**: `advise` allows
  every refusal (uncited, forged, wrong team, verify unavailable, handler
  error). It must not be read as protection; only `block` enforces.

## Open design points (owner ruling pending)

- **Q4, proposed**: the cite is a trailing shell comment
  `# human-approval team=<T> id=<$id>` on the Bash command.
- **Q5, proposed**: `coordinator_seats_only` (default on) arms coordinator
  seats and unreadable roles on the main thread; off arms every main-thread
  seat.
- **Gap, sub-agents** (precondition P2): under the Q5 default a coordinator's
  sub-agent or in-process teammate is not armed, so its push, delete or merge
  is unguarded. Arming it would deny every such act, because no sub-agent can
  pass.
- **Gap, replay** (precondition P1): replay is UNBOUNDED. The 300 s in-memory
  approval record only skips re-verification; once it lapses the same line
  verifies again and passes again, indefinitely. Nothing binds the line's
  text, age or question to the act.
- **Gap, deletes**: a plain `git branch -d` is not an act (merged-only delete).
- **Gap, `git -C <dir>`**: a merge or main-moving command run with `-C` is
  judged against the hook cwd, not `<dir>`.
- **Gap, permission scope**: the permission act is the world-writable `chmod`
  only (`dangerous_permissions.sets_world_writable`).
- **Choice, `gh pr merge`**: always counts as a merge into main, because it
  lands on the PR base on GitHub whatever the local checkout; an unreadable
  current branch with a merge named also counts (fail closed).
- **Mode `block`**: until issue 369 lands the default verifier refuses every
  cite, so `block` denies every armed act; the shipped default is `advise`.
- **Unverified here**: the `verify --json` flag, the answer shape, and the
  event id grammar (provisional `$[A-Za-z0-9_+=-]`; no `:`, `/`, `.` or `~`
  accepted, so a path-shaped id is refused; fails closed if real ids carry
  one).

## Dependencies

- Plan 00631 (role in T); fedora-desktop issue 369 (questions-room `verify`).
  Consumed by Plan 00632. Related Plan 00502.

## Success Criteria

- [x] No path counts a peer line or a role as approval (tests).
- [x] An unverifiable questions-room cite denies (test).
- [x] Absent-team fixture passes.
- [x] Release-bound items recorded in the pending-release holding area
  (`CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.77.0.yaml`,
  `release-notes/087-human-approval-check.md`).

## Delivery & Milestones

- Plan filed; revised for the fedora-desktop vet and issue 369.
