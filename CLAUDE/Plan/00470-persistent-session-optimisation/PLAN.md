# Plan 00470: persistent session optimisation

**Status**: In Progress
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

- [x] ✅ **Task 1.1**: Vendor `scheduled-tasks`, `model-config` and `interactive-mode` docs via `hooks-daemon remote-docs add`. `model-config` and `interactive-mode` were already vendored; `scheduled-tasks` added (`remote-docs/code.claude.com/docs/en/scheduled-tasks.md`). It confirms the 7-day recurring expiry (one final fire, then self-delete) and says `--resume`/`--continue` restore unexpired `CronCreate` tasks, which bears on Task 1.2.
- [x] ✅ **Task 1.2**: Probe the four open questions in RESEARCH.md §4 and record the results in RESEARCH.md. The CronCreate result carries `id` and the record keeper works live. Crons survive compaction. Re-dispatch after a usage limit is evidenced "no" but not directly probed.

### Phase 2: Cron expiry (owner: python-developer sub-agent, TDD)

- [x] ✅ **Task 2.1**: PostToolUse handler records CronCreate/CronDelete (`session_id`, id, schedule, prompt hash, created_at) in a daemon state file. Tests: record, delete, prune dead sessions.
  - `cron_record_keeper` (priority 36, default on) writes `cron-records.json` in the daemon's untracked dir (`utils/cron_records.py`). The `CronCreate` result shape is not contract-documented, so the id is read from a mapping key or `id: <token>` text; an unreadable result is not recorded and Task 1.2 should confirm the real shape.
  - Liveness signal: the daemon has no session registry, so a record is dead when older than 7 days (the cron cannot exist) or when its session's `session_crons` no longer lists its id.
- [x] ✅ **Task 2.2**: `cron_stop_enforcer` (and its SubagentStop twin) block a stop when a live job's record is older than `refresh_after`, naming the CronDelete + CronCreate. Unrecorded jobs get stamped, not blocked. Tests: age boundary, unknown age, pause respected, priority/terminal invariants unchanged.
  - Option `refresh_after_days`, default 6 (the day left before expiry is the margin for dropped ticks), shared logic in `utils/cron_refresh.py`. The `[awaiting-human]` marker is deliberately not consulted: it silences ticks, which is when a job ages unnoticed. The usage pause and `cron-pause` are respected.
- [x] ✅ **Task 2.3**: ccy supervisor watchdog: no hook traffic while every recorded job is past expiry triggers the reconcile prompt. Tests in the supervisor suite.
  - Done: `would-cron-reconcile` family in `.claude/ccy/claude-supervise.py`, tests in `tests/unit/supervise/test_cron_expiry_watchdog.py`. It needs a supervisor restart, since the PTY host measures the quiet time.
  - **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** Q1 a 2 h quiet threshold; Q2 (a) terminal-quiet proxy, no daemon change; Q3 reuse the `persistent_cron_assertor` wording. Unblocked.
  - Resolved questions (coordinator calls, not owner rulings):
    1. The quiet threshold N, in hours: 2 h.
    2. What counts as hook traffic: (a) PTY output quiet as a proxy, with no daemon change.
    3. The reconcile prompt text: reuse the `persistent_cron_assertor` "CronList and reconcile" wording.
  - Agent proposal once answered: the supervisor reads `cron-records.json` read-only with its own copy of the 7-day expiry, pinned to `utils/cron_records.py` by a test. It fires only when at least one record exists, all are past expiry and the quiet time has reached N. It is a last-in-line injection family with its own cap, below session-actions, and it respects the usage pause and the empty-input-box guard.
- [x] ✅ **Task 2.4**: Make the background-process watchdog cron a standing job. The owner's decision: it is a sensible safety net for a long-running session, so every session gets it.
  - Declare it under `persistent_crons` next to `issue-sdlc` and `failsafe-recovery`.
  - Its prompt must be byte-identical to `background_process_tracker`'s canonical `[tick:watchdog]` text, pinned by a test the way the failsafe prompt is pinned.
  - A declared job is required by `cron_stop_enforcer` for the whole session. So the canonical prompt must stop telling the agent to CronDelete it once no background work remains: an idle tick is a no-op, not a reason to delete.
  - `background_process_tracker` must stop asking for a second watchdog when the declared one exists.
  - Fix `harvest-background` listing the same process group twice. It was observed in this session, and the doubled group was a wanted QA gate.
  - Tests: the declaration is re-asserted at SessionStart; the prompt pin; the stop enforcer requires the job; an idle tick is a no-op; each group is listed once.
  - Done: `background-watchdog` job (`37 * * * *`) declared; `watchdog_cron_prompt()` is the single text, rendered path-agnostic (`bin/hooks-daemon`) so a worktree's live cron matches the committed declaration; idle tick is a no-op; the advisory stands down when declared; `harvest-background` lists each pgid once.

### Phase 3: Limits, restarts, durable queue (owner: python-developer sub-agent, TDD)

- [x] ✅ **Task 3.1**: StopFailure handler package: record `rate_limit`, `authentication_failed`, `cloud_credential_error` to a durable file and surface them in the status line. `stop_failure_recorder` writes `stop-failures.json` (bounded to 50); `stop_failure_resolver` (UserPromptSubmit) marks a session's failure resolved at its next prompt; the usage indicator shows `⚠ usage limit HH:MM` until then. Report: `subagent-reports/261002-p470-stopfail-sonnet.md`.

- [x] ✅ **Task 3.2**: Notification handler records `quota_auto_resume_*`; on resume, inject a re-brief pointing at the queue. Also surface a BACKGROUND or teammate agent killed by a session or weekly limit, naming the agent so it can be re-briefed. Plan 00466 N46 covers only foreground dispatches, whose death arrives as a PostToolUse:Agent result. The 264 of 351 real dispatches that ran in the background report their death through a task notification instead.

  - A Notification cannot inject context, so `quota_resume_recorder` (Notification) writes `limit-events.json` and `limit_rebrief` (UserPromptSubmit, priority 39) delivers the one-shot re-brief at the next prompt. The same handler names a limit-killed background or teammate agent from the prompt-borne notification. No queue exists yet: the re-brief points at the worktrees, the plan JOURNAL and the last StopFailure record, and `_REBRIEF_PLACES` is where Task 3.3 adds the queue. Report: `subagent-reports/261003-task-3.2-notifications-sonnet.md`.

- [x] ✅ **Task 3.3**: Durable work-queue file format + the `issue-sdlc` skill writes and reads it; SessionStart (`resume`/`compact`) re-briefs from it. Observed on 2026-09-25, in two separate ways:

  - After a usage-limit restart, a new session had no teammates.
  - A user interrupt of the lead's turn killed all 11 running in-process agents.

  Both times, each agent had to be re-briefed by hand from its worktree state. The queue must hold enough per agent (worktree, task brief, last sha) that a respawn is mechanical.

  - `work-queue.json` plus `hooks-daemon work-queue add|update|done|list`, the `work_queue_rebrief` SessionStart handler and the `limit_rebrief` listing are advisory only (nothing is respawned). Report: `subagent-reports/261004-task-3.3-work-queue-sonnet.md`.
  - **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** Q1 list-only for now, auto-respawn revisited once the queue has proved reliable; Q2 prune after 14 days; Q3 mark stale, never delete silently; Q4 records carry the dispatching session. Follow-up code for Q2 to Q4 is not yet built.
  - Resolved questions (coordinator calls, not owner rulings):
    1. Auto-respawn: list only, as now.
    2. Retention: prune `done`/`abandoned` records after 14 days.
    3. Stale `running` records whose coordinator is gone: mark stale and list apart, never delete silently.
    4. Several coordinators share one queue: each record carries its dispatching session.

- [x] ✅ **Task 3.4**: Regression test that a teammate or sub-agent stop never writes the lead's `[awaiting-human]` marker.

  - No bug found: `auto_continue_stop` is the only writer and is scoped to the main thread, which a teammate's `agent_id` fails. Pinned in `tests/unit/handlers/stop/test_awaiting_human_marker_scope.py`, through the real chain, with a positive control and a sensitivity check.

- [ ] 🔄 **Task 3.5**: Server runbook: systemd/ccy restart with `--continue`, `autoContinueAtUsageLimit` on.

  - [RUNBOOK.md](RUNBOOK.md) holds the verified parts. `autoContinueAtUsageLimit` belongs in user settings: a project settings file turns it off. `--continue` is what restores crons.
  - Owner input: the host's restart unit around ccy is outside this repository. It is recorded in RUNBOOK.md §3 once it exists.
  - Owner ruling D10 (2026-10-06): inspect the public fedora-desktop reference clone and this VM's server install, then
    tell the owner what infrastructure agents must do. Report:
    [261006-ccy-environment-inspection-sonnet.md](subagent-reports/261006-ccy-environment-inspection-sonnet.md).
    - **Task 2.3**: no restart is needed. The supervisor is this repository's bind-mounted file, and its `--worker`
      hot-reloaded three seconds after the file's last write. To verify, compare the worker's `lstart` with the file's
      mtime.
    - **Task 3.5 gaps, for infrastructure agents**: nothing restarts a crashed `claude` or supervisor while the VM is
      up; boot restore is fedora-desktop's `ccy-sessions-restore.service` (with `--continue`), unconfirmed on this
      host; `autoContinueAtUsageLimit` is not provisioned anywhere; `HOOKS_DAEMON_HOSTNAME` is not set.
  - Owner ruling A1 (2026-10-06): the supervisor's Esc before a forced compact is not a human rejection. The compact
    instruction now says so and asks for interrupted tool calls to be retried. Merged `70331d361` on the owner's
    instruction (77 targeted tests, ruff and black clean; full QA owed in the combined post-merge run). Live: the
    `--worker` hot-reloaded 4 s after the merge wrote the file.

### Phase 4: Housekeeping and cost (owner: orchestrator; code by sub-agents)

- [ ] ⬜ **Task 4.1**: Measure disk/log growth on the server; add rotation where it is unbounded.
- [x] ✅ **Task 4.2**: Extend `idle_housekeeping_advisor` to report stale worktrees and daemons (report-first). Detection is `utils/stale_checkouts.py`; the advisory names each finding with its cleanup command and runs none. Options: `report_stale_checkouts`, `base_branch`, `stale_worktree_days`.
  - Remedies are real and never signal: `rm` of a proven-dead pid file, only this host's pid file, and a daemon with a vanished root gets a read-only `ps` and a human look. Merged 057116873.
- [x] ✅ **Task 4.5**: Stale-scan follow-ups from the Task 4.2 review (`untracked/scratch/merge-review/housekeeping.md` is lost on restart, so the list is here).
  - A pid file that `get_pid_path` relocates for a long path (the fallback runtime dir) is not scanned.
  - It parses the worktree listing separately from `worktree_reaping`, so the two can give different verdicts. Share one parser.
  - Validate `stale_worktree_days` (int ≥ 1); put one deadline across the scan's git calls; pass the CLI path in rather than a literal; revisit the `base_branch` default.
  - Done: `paths.pid_path_for` (shared with `get_pid_path`, no mkdir), one `git_repo.parse_worktree_porcelain`, `stale_worktree_days` setter validation, `ScanDeadline` budget with an INCOMPLETE report line, unset `base_branch` uses `git_sync.default_branch`. The report holds no CLI-path literal, so that item needed no change.
- [ ] ⬜ **Task 4.4**: Keep the prompt cache warm. The owner's intent is that the cache never expires in an always-on session. The design and the arithmetic belong to [Plan 00452](../00452-prompt-cache-observability-and-invalidation-protection/PLAN.md) Tasks 4.1–4.3. That plan rejected a fixed-interval warming cron, because warming loses when the probability of a next event is low. Its warming work is blocked on Task 2.4, which needs real idle-gap profiles.
  - This task feeds 00452. Collect this always-on session's gap profile, which unblocks 00452 Task 2.4.
  - Note for 00452: the declared crons at :23 and :47 already keep gaps under 60 minutes. But the daemon DROPS ticks when the session is blocked on a human or has backed off (R-FAILSAFE-CRON-SUPPRESSED, R-FAILSAFE-CRON-BACKED-OFF), which is exactly when the cache goes cold. So the warming decision must account for suppressed ticks.
- [ ] ⬜ **Task 4.3**: A/B the orchestrator: Sonnet main loop vs Opus, Opus sub-agents with pinned `model:` and structured verdict files; compare cost per tick, guard denies, and triage/verdict errors. Owner decides from the record.

### Phase 5: A human block must not halt everything (owner request)

An `[awaiting-human]` stop currently silences every declared cron, so one open
question stops all work. Seen: an issue-sdlc tick was suppressed while the session
waited on one bandit decision.

- [x] ✅ **Task 5.1**: A per-job `persistent_crons` option saying whether a live
  awaiting-human marker suppresses that job. `issue-sdlc` is not suppressed, because
  its work is independent of the pending question. `failsafe-recovery` is
  suppressed, because resuming interrupted work is exactly what waits on the human.
  TDD, with the default unchanged for undeclared jobs.
- [x] ✅ **Task 5.2**: Timed stand-in. When a stop declares `[awaiting-human]`, the
  session also schedules a one-off cron about three hours out. If the marker is
  still live when it fires, a Fable (`claude-fable-5-1`) sub-agent reads the
  pending question and the options the agent laid out, chooses one, and the
  session carries on.
  - The stand-in's choice is recorded in the plan journal as the stand-in's ruling,
    never as the owner's, and a later real message can overturn it.
  - It may only choose among engineering options. Decisions this repository
    reserves for a human stay blocked: releases, force deletes, QA suppressions,
    history rewrites, and anything the guards say to ask the user for.
  - **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** the stop hook blocks the stop until the one-off cron shows in `session_crons`, as `cron_stop_enforcer` does for declared jobs. Resolved; not an owner ruling.
  - Done: `utils/stand_in_cron.py` (prompt, one-off schedule, verdict) and `TickKind.STAND_IN` (`[tick:stand-in]`, so the suppressor lets it through under a live marker). The block lives in `auto_continue_stop` Branch 2 right after the marker is written, because `cron_stop_enforcer` runs first and cannot see the declaration. Option `stand_in_delay_hours` (default 3, validated); gated on `persistent_crons.enabled`; main thread only. Release note 038.

### Phase 6: Where declared crons run (owner ruling, issues #60 and #62)

- [x] ✅ **Task 6.1**: Each `persistent_crons` job is global (the default) or
  carries `hosts:`, a list of exact hostnames or globs. A job with `hosts:` is
  declared only where the effective hostname matches. The effective hostname is
  the first set of: `HOOKS_DAEMON_HOSTNAME`, then `CCY_HOST_HOSTNAME` (ccy sets it
  to the host machine's name, since a container's own hostname is a random id),
  then the system hostname. A session
  can so take a role, such as `cchd-sdlc-runner`, without a real hostname
  entering the tracked, public config.
- [x] ✅ **Task 6.2**: This project's `issue-sdlc` job gets
  `hosts: [cchd-sdlc-runner]`. An SDLC runner is started anywhere by exporting
  `HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner` before launching the session.
- [ ] ⬜ **Task 6.3** (paused until the owner is present, owner ruling D10 of 2026-10-06: the owner opens the second
  thread): Probe, by dogfooding, how extra agent threads opened in one
  Claude Code session (left arrow, then a new thread) appear in hook payloads:
  their `session_id`, transcript and `session_crons`. Record the results in
  RESEARCH.md before any design.
- [ ] ⬜ **Task 6.4**: From the probe: by default only the initial thread of a
  session is required to hold the declared crons. Threads opened later hold none
  unless explicitly instructed.

## Success Criteria

- [ ] An issue-sdlc tick fires while a failsafe tick is suppressed by a live
  awaiting-human marker, proven by test.
- [ ] A stale awaiting-human block is answered by the stand-in within the window,
  and a human-reserved decision is never taken by it.
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
