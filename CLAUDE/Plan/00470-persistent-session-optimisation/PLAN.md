# Plan 00470: persistent session optimisation

**Status**: Not Started
**Created**: 2026-09-25
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner runs one session permanently on a datacentre server to monitor
GitHub issues and resolve them; that session is the dogfood. This plan tracks
everything an "always on" session needs that a normal session does not.

The sharpest gap is cron expiry: recurring crons auto-expire, and in an idle
session the cron tick is the only thing that produces a Stop, so when every job
expires together nothing ever fires again and `cron_stop_enforcer` never runs.
The next gaps are recovery after a usage limit (the weekly limit killed every
sub-agent with nothing to resume them) and restarts, both of which need durable
state rather than session memory. The last question is the orchestrator's model.

Evidence, with verified facts marked apart from inferences, is in
[RESEARCH.md](RESEARCH.md).

## Goals

- Declared crons are refreshed before they expire, and never die silently.
- A usage-limit stop, auth failure or restart leaves a durable record from
  which the orchestrator re-dispatches the lost work without a human.
- Work in flight lives in a durable queue file, never only in context.
- The orchestrator model is chosen from a measured comparison.

## Non-Goals

- Making crons durable inside Claude Code (not ours to change).
- Auto-merging on a cheap model's free-text judgement.
- Changing any other plan's scope.

## Tasks

### Phase 1: Probes (owner: orchestrator, main thread)

- [ ] ⬜ **Task 1.1**: Vendor `scheduled-tasks`, `model-config` and `interactive-mode` docs via `hooks-daemon remote-docs add`.
- [ ] ⬜ **Task 1.2**: Probe the four open questions in RESEARCH.md §4 and record the results in RESEARCH.md.

### Phase 2: Cron expiry (owner: python-developer sub-agent, TDD)

- [ ] ⬜ **Task 2.1**: PostToolUse handler records CronCreate/CronDelete (`session_id`, id, schedule, prompt hash, created_at) in a daemon state file. Tests: record, delete, prune dead sessions.
- [ ] ⬜ **Task 2.2**: `cron_stop_enforcer` (and its SubagentStop twin) block a stop when a live job's record is older than `refresh_after`, naming the CronDelete + CronCreate. Unrecorded jobs get stamped, not blocked. Tests: age boundary, unknown age, pause respected, priority/terminal invariants unchanged.
- [ ] ⬜ **Task 2.3**: ccy supervisor watchdog: no hook traffic while every recorded job is past expiry triggers the reconcile prompt. Tests in the supervisor suite.

### Phase 3: Limits, restarts, durable queue (owner: python-developer sub-agent, TDD)

- [ ] ⬜ **Task 3.1**: StopFailure handler package: record `rate_limit`, `authentication_failed`, `cloud_credential_error` to a durable file and surface them in the status line.
- [ ] ⬜ **Task 3.2**: Notification handler records `quota_auto_resume_*`; on resume, inject a re-brief pointing at the queue.
- [ ] ⬜ **Task 3.3**: Durable work-queue file format + the `issue-sdlc` skill writes and reads it; SessionStart (`resume`/`compact`) re-briefs from it.
- [ ] ⬜ **Task 3.4**: Regression test that a teammate or sub-agent stop never writes the lead's `[awaiting-human]` marker.
- [ ] ⬜ **Task 3.5**: Server runbook: systemd/ccy restart with `--continue`, `autoContinueAtUsageLimit` on.

### Phase 4: Housekeeping and cost (owner: orchestrator; code by sub-agents)

- [ ] ⬜ **Task 4.1**: Measure disk/log growth on the server; add rotation where it is unbounded.
- [ ] ⬜ **Task 4.2**: Extend `idle_housekeeping_advisor` to report stale worktrees and daemons (report-first).
- [ ] ⬜ **Task 4.3**: A/B the orchestrator: Sonnet main loop vs Opus, Opus sub-agents with pinned `model:` and structured verdict files; compare cost per tick, guard denies, and triage/verdict errors. Owner decides from the record.

## Success Criteria

- [ ] A job older than `refresh_after` is refreshed at a Stop, proven by test.
- [ ] Total cron expiry is recovered by the supervisor watchdog, proven by test.
- [ ] After a simulated usage-limit stop, the session re-dispatches queued work from the queue file alone.
- [ ] A teammate stop cannot silence the lead's ticks, proven by test.
- [ ] The orchestrator model decision cites the Phase 4 measurements.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00470-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Research and plan drafted.
