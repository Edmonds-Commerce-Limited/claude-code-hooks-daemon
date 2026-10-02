# Plan 00479: subscription usage monitor and ceiling

**Status**: In Progress
**Created**: 2026-10-02
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The owner asked for two things.

1. **Show subscription usage in the status line**: the 5-hour and weekly windows, as other
   status lines already do.
2. **Add a host-level usage ceiling.** An unattended long-running session, such as the
   cron-driven SDLC loop, stops taking on work once usage passes a configured threshold (say
   80% used). The rest of the subscription is then left for other people and sessions.

The data is already arriving. Every Status payload this daemon receives carries
`rate_limits.five_hour` and `rate_limits.seven_day`, each with `used_percentage` (0 to 100)
and `resets_at` (epoch seconds), and nothing reads them. No other hook event carries usage,
so the daemon keeps the latest snapshot from the Status event and its other handlers read
it. [RESEARCH.md](RESEARCH.md) holds the payload schema, how community status lines render
it, and how a hook can halt a session.

The ceiling is configured per host, building on the session hostname from Plan 00470
Task 6.1. The effective hostname is `HOOKS_DAEMON_HOSTNAME`, then `CCY_HOST_HOSTNAME`, then
the system hostname, read from the session's own environment. Owner ruling: hosts are the
TOP-LEVEL key, each with its own settings. A key is a label; an optional `pattern` sub-key
holds an `fnmatch` glob (case-sensitive, as `cron_hosts.hostname_matches` already uses). With
no `pattern`, the label itself is the exact hostname.

```yaml
hosts:
  sdlc-runner:                  # a label
    pattern: "cchd-sdlc-*"      # glob against the effective hostname; omitted = the label
    usage_ceiling:
      max_used_percent: 80      # either window at or above this stops new work
  dev-laptop:
    usage_ceiling:
      max_used_percent: 95
```

## Goals

- A status-line segment shows 5-hour and weekly usage, with a reset countdown, and appears
  only when the data is present.
- A top-level `hosts:` config block: entries keyed by label, each with an optional glob
  `pattern` and per-host settings, matched against the effective session hostname.
- On a host whose ceiling is crossed, the session stops taking on new work:
  - prompts are refused, cron ticks and supervisor nudges included;
  - the running turn halts with a stated reason;
  - no handler forces the session to continue.
- Missing, stale or API-key-only data never stops a session, and the reason it did nothing
  is visible.

## Non-Goals

- Calling the undocumented OAuth usage endpoint for per-model weekly or extra-usage data. It
  needs the user's credential and is rate-limited.
- Moving `persistent_crons` job host selection into the new `hosts:` block. That is a
  possible follow-on (open question 4), not part of this plan.
- Restarting the running ccy supervisor session. Its code changes in this repository and
  reaches the running worker by hot-reload only.

## Tasks

### Phase 1: Ground truth

- [ ] ⬜ **Task 1.1**: Vendor the status line docs page with `hooks-daemon remote-docs add`.
  Record in `CLAUDE/Architecture/StatusLine.md` that `rate_limits` is now read.
- [x] ✅ **Task 1.2** (merged ee58adb7c): Capture real Status payloads into test fixtures: a main thread with
  data, before the first response (absent), a subagent or `--agent` thread, and integer and
  fractional percentages. Establish whether subagent threads carry `rate_limits`.

### Phase 2: Usage snapshot and status line segment (TDD)

- [x] ✅ **Task 2.1** (ee58adb7c; `core.data_layer.latest_usage()`, mirrored to
  `usage-snapshot.json` in the daemon's untracked dir): Keep the latest snapshot from each Status event: window, percentage,
  `resets_at` and when it was seen. Hold it per session in daemon state and persist it
  host-wide, so a fresh daemon or a session that has not yet rendered can read it. Treat a
  window past its `resets_at` as absent.
- [x] ✅ **Task 2.2** (ee58adb7c; `usage_indicator`, seen live as
  `5h 67% (3h 19m) · 7d 84% (4d 23h)`): A status-line usage segment, for example `5h 13% (3h 20m) · 7d 3%`, with
  colour thresholds. Hidden when there is no data. Options for the layout and the warning
  level.
- [ ] ⬜ **Task 2.3**: When a ceiling applies to this host, the segment also shows it (for
  example `⛔ 80%`), so a session can see the line it is working under.

### Phase 3: Host configuration (TDD)

- [ ] ⬜ **Task 3.1**: The top-level `hosts:` model. Keys are labels; `pattern` is an
  optional `fnmatch` glob defaulting to the label. Validation, an example config, and a
  `config-changes` manifest entry. Matching reuses Plan 00470's effective hostname reader
  and `hostname_matches`.
- [ ] ⬜ **Task 3.2**: Resolve the settings for a session: which entries match, and how
  several matches combine (open question 2).

### Phase 4: The usage pause (TDD)

The owner's rulings set the protocol:

- **Pause**: crossing the ceiling pauses the session; it does not end it.
- **Crons**: all crons stop, and one new cron resumes the session when the usage is
  expected to have cleared, that is when the 5-hour or weekly window resets.
- **Compact**: on stopping, the supervisor issues a compact that explicitly does NOT
  continue, leaving only the resume cron. Resuming then does not pay the uncached-context
  penalty of a large conversation.

A hook cannot create or delete crons itself (`CronCreate`/`CronDelete` are model tools), so
the daemon directs the model and then verifies what it did.

- [ ] ⬜ **Task 4.1**: Pause entry. At or above the ceiling, the `UserPromptSubmit` gate
  refuses the incoming work, cron ticks and supervisor messages included. It delivers the
  pause directive instead: delete every cron (the failsafe and declared jobs included),
  create ONE one-shot resume cron, then stop. The directive names the window, its
  percentage, the ceiling and the resume time. The resume time is the latest `resets_at`
  among the windows over the ceiling, plus a small margin.
- [ ] ⬜ **Task 4.2**: During the pause, the `PreToolUse` gate allows only `CronList`,
  `CronDelete` and `CronCreate`. Any other tool is denied, with `continue: false` and a
  `stopReason`, so a turn already running halts at its next tool call. Prerequisite:
  `PRE_TOOL_USE_SCHEMA` in `core/response_schemas.py` does not allow a top-level `continue`
  or `stopReason` today (`additionalProperties: False`). The schema, the response formatter
  and the vendored hooks contract need extending first (found by the Plan 00480 fact-check
  experiment).
- [ ] ⬜ **Task 4.3**: Pause exit is verified. Stop is allowed once the Stop payload's
  `session_crons` holds exactly the one resume cron; otherwise the directive is repeated,
  as `cron_stop_enforcer` already does for declared crons. Every handler that forces
  continuation stands down during the pause: `handlers/stop/auto_continue_stop.py`, which does
  both unattended-mode Stop blocking and stop-explanation re-entry, plus
  `cron_stop_enforcer` and `cron_subagent_stop_enforcer`.
- [ ] ⬜ **Task 4.4**: Start from `utils/cron_pause.py`. It is the existing session-scoped,
  TTL-bounded pause for declared crons, set by the `hooks-daemon cron-pause` CLI and honoured
  by the cron enforcers. Reuse or extend it rather than adding a second pause mechanism.
  Nothing re-arms the crons while paused. `persistent_cron_assertor` and
  the failsafe-cron advisors stay quiet, including on the compact's SessionStart, and the
  pause is recorded in a durable marker the daemon reads.
- [ ] ⬜ **Task 4.5**: The supervisor compact, in this repository. The supervisor is
  `.claude/ccy/claude-supervise.py`, tested under `tests/unit/supervise/`, with its
  injection rules in `CLAUDE/development/CcySupervisor.md`. It already decides every
  `/compact`, `continue` and `/goal` injection.
  - **Daemon side**: the daemon records the pause state (reason and resume time) where the
    supervisor already reads daemon state, such as the `<session>.compacting` record.
  - **Supervisor side**, built TDD:
    - once the pause is recorded and the session has stopped, inject ONE `/compact` whose
      instruction is to do nothing until the resume cron fires;
    - inject no `continue` or goal nudges while paused;
    - resume normal behaviour when the pause lifts.
  - **Rollout**: verify the change on a branch, then apply it by the worker hot-reload in
    `CcySupervisor.md`. The running supervisor session is never restarted.
- [ ] ⬜ **Task 4.6**: Resume. When the resume cron fires, the gate re-reads usage. A window
  past its `resets_at` reads as absent, so a snapshot from before the reset cannot keep
  the session paused. Then:
  - below the ceiling: lift the pause, re-establish the declared crons, and continue the
    active work;
  - still over the ceiling (for example the weekly window): schedule the next resume cron
    and stop again.
- [ ] ⬜ **Task 4.7**: Data safety. No snapshot, or no `rate_limits` at all, never pauses a
  session, and a debug log line records why. A paused session shows `⏸ usage` and its resume
  time in the status line.
- [ ] ⬜ **Task 4.8**: Acceptance tests. Run a live probe with a synthetic snapshot above the
  ceiling through the whole cycle: pause directive, cron set reduced to the resume cron,
  stop allowed, resume tick lifts the pause.

### Phase 5: Docs and release

- [ ] ⬜ **Task 5.1**: Write the configuration docs, the handler guidance, and a release note.

## Open questions for the owner

1. **Resolved (owner)**: pause, then resume through a scheduled cron at the predicted reset,
   with a supervisor compact before it (Phase 4).
2. **Several matching entries**: being built with the recommended default, the lowest
   ceiling wins, as the safer choice. The owner can overrule it with first match in file
   order.
3. **One threshold or one per window**: being built with the recommended default.
   `max_used_percent` applies to both windows, with optional `five_hour` and `seven_day`
   overrides.
4. **Folding `persistent_crons` host selection** into the `hosts:` block later.

## Success Criteria

- [ ] The status line shows 5-hour and weekly usage from live payloads, and shows nothing
  for a session without the data.

- [ ] A session on a host whose entry sets `max_used_percent: 80` pauses once a window
  reaches 80%:

  - it refuses new work and halts the running turn;
  - it ends with only a resume cron scheduled for the window's reset;
  - it resumes on that tick.

  A session on a host with no entry is unaffected.

- [ ] Missing or stale usage data never stops a session.

## Delivery & Milestones

- Plan filed with the owner's host-first and pattern rulings.
