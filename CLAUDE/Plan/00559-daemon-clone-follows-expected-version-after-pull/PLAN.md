# Plan 00559: daemon clone follows expected version after pull

**Status**: Not Started
**Created**: 2026-11-02
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration
**GitHub Issue**: #148

## Overview

A pull or merge that changes `daemon.expected_version` leaves the gitignored
daemon clone at the old version. Three things currently respond to it:

- `daemon_sync_after_merge`, which only advises. It runs inside the old daemon
  and never sees a pull made in another terminal.
- `provision.sh --background`, which the session-start forwarder starts only at
  session start. It attempts each target version at most once
  (`install/background_sync.py`; Plan 00477 Task 5.2), and it skips the sync
  when no daemon comes up within its wait.
- `daemon_upgrade_detector`, which notices a clone changed under a running
  daemon. It does not notice a clone that is behind.

A long-lived unattended session can therefore keep working on the old daemon.
When that daemon restarts against the newer config, it either refuses to start
or comes up degraded with enforcement off. Issue #148 asks for two things: a
trigger that does not run inside the stale daemon, and an optional scheduled
check on each host. It also asks that a failed sync be retried.

Each answer changes what runs automatically on a client checkout: a download,
a venv rebuild and a daemon restart, set off by a pull. That is a call on the
safety posture and on product intent, so the owner decides before anything is
built.

## Owner decision required

1. **Post-pull trigger.** Which of these, if any?
   - (a) A git `post-merge`/`post-checkout`/`post-rewrite` hook that provision
     installs, and that runs `provision.sh` when `expected_version` differs
     from the clone.
   - (b) A version check in the `init.sh` launcher before it starts the daemon,
     which syncs first (or refuses to start the stale version and says why).
   - (c) Neither. Keep the advisory, and make a stale daemon fail loudly rather
     than run degraded.
2. **Retrying a failed background sync.** Keep at-most-once per target (today's
   design), or retry on later triggers with a bound (for example a backoff, or
   N attempts) so that a failure that keeps happening does not rerun a failing
   install on every session start?
3. **Scheduled host check** for unattended workers (`persistent_crons` can only
   enqueue a prompt, not a shell action). Build a host-scoped scheduled shell
   check, or leave it out?

Related plans that constrain the design (the dedupe check found no duplicate):

- Plan 00535 (upgrade handover without a live daemon rebuild). A re-provision
  set off by a hook must stop or hand over the running daemon before it
  rebuilds, or it hits that plan's mixed old/new tree.
- Plan 00473 (post-merge handlers judge the command's repository). A git
  post-merge trigger needs the same repository resolution, and should reuse
  `merge_directory` (`utils/merge_scope.py`), which `daemon_sync_after_merge`
  already calls.

## Goals

- Record the owner's answers, then build them with TDD.

## Non-Goals

- Changing the fixed provisioning source URL or the pre-deploy gate.

## Tasks

### Phase 0: Owner decisions

- [ ] ⬜ **Task 0.1**: The owner answers questions 1 to 3 above.

### Phase 1: Build per the decisions

- [ ] ⬜ **Task 1.1**: Red tests for each chosen behaviour, then the
  implementation and a release note.

## Success Criteria

- [ ] The owner's answers are recorded in this plan.
- [ ] Each chosen behaviour is proven by a test, with a release note in the
  pending-release holding area `CLAUDE/UPGRADES/UNRELEASED/`.

## Delivery & Milestones

- Filed from GitHub #148 and parked as `agent-needs-human`.
