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

- [x] ✅ **Task 1.1** (vendored by Plan 00492 at `remote-docs/code.claude.com/docs/en/statusline.md`, one unlisted fake swapped and recorded in its provenance): Vendor the status line docs page with `hooks-daemon remote-docs add`.
  Record in `CLAUDE/Architecture/StatusLine.md` that `rate_limits` is now read.
  Blocked: `remote-docs add https://code.claude.com/docs/en/statusline` refuses the page
  (its content matches the `session-uuid` sensitive-content pattern; nothing written).
  StatusLine.md records the read and the URL; the vendoring needs an owner decision.
  **Owner ruling (2026-10-05):** unblocked by the fake-values registry plan `docs-fake-values-registry`: the page is vendored
  with unlisted fakes swapped for listed ones, recorded in its provenance — see
  [OWNER-RULINGS-261005.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261005.md) (D1). Unblocked: Plan 00492 landed the registry and vendored the page.
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
- [x] ✅ **Task 2.3**: When a ceiling applies to this host, the segment also shows it (for
  example `⛔ 80%`), so a session can see the line it is working under. One figure when both
  windows share a limit, else labelled per window (`⛔ 5h 80% 7d 95%`); plain text, shown
  only beside usage chips.

### Phase 3: Host configuration (TDD)

- [x] ✅ **Task 3.1** (merged; `HostConfig` and `UsageCeilingConfig` in `src/claude_code_hooks_daemon/config/models.py`): The top-level `hosts:` model. Keys are labels; `pattern` is an
  optional `fnmatch` glob defaulting to the label. Validation, an example config, and a
  `config-changes` manifest entry. Matching reuses Plan 00470's effective hostname reader
  and `hostname_matches`.
- [x] ✅ **Task 3.2** (merged; `utils/host_usage_ceiling.py`,
  `resolve_host_usage_ceiling()`; lowest matching ceiling wins per window): Resolve the
  settings for a session: which entries match, and how several matches combine (open
  question 2).

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

- [x] ✅ **Task 4.1** (merged 506fd3f5e): Pause entry. At or above the ceiling, the `UserPromptSubmit` gate
  refuses the incoming work, cron ticks and supervisor messages included. It delivers the
  pause directive instead: delete every cron (the failsafe and declared jobs included),
  create ONE recurring `*/10 * * * *` resume cron (it names no clock time, so no host time
  zone can misplace it; ticks before the resume time are dropped at no cost), then stop. The directive names the window, its
  percentage, the ceiling and the resume time. The resume time is the latest `resets_at`
  among the windows over the ceiling, plus a small margin.
- [x] ✅ **Task 4.2** (merged 506fd3f5e). Owner ruling, round 4: subagents are never denied
  or halted. Running ones finish, the main thread winds them up, and no new ones start
  (`Agent`/`Task` denied). A subagent over the ceiling still starts the pause. The main thread
  may also use `ToolSearch`, `SendMessage` and `TaskStop`. During the pause, the `PreToolUse`
  gate allows only `CronList`, `CronDelete` and `CronCreate`. Any other tool is denied, with `continue: false` and a
  `stopReason`, so a turn already running halts at its next tool call. Prerequisite:
  `PRE_TOOL_USE_SCHEMA` in `core/response_schemas.py` does not allow a top-level `continue`
  or `stopReason` today (`additionalProperties: False`). The schema, the response formatter
  and the vendored hooks contract need extending first (found by the Plan 00480 fact-check
  experiment).
- [x] ✅ **Task 4.3** (merged 506fd3f5e): Pause exit is verified. Stop is allowed once the Stop payload's
  `session_crons` holds exactly the one resume cron; otherwise the directive is repeated,
  as `cron_stop_enforcer` already does for declared crons. Every handler that forces
  continuation stands down during the pause: `handlers/stop/auto_continue_stop.py`, which does
  both unattended-mode Stop blocking and stop-explanation re-entry, plus
  `cron_stop_enforcer` and `cron_subagent_stop_enforcer`.
- [x] ✅ **Task 4.4** (merged 506fd3f5e): Start from `utils/cron_pause.py`. It is the existing session-scoped,
  TTL-bounded pause for declared crons, set by the `hooks-daemon cron-pause` CLI and honoured
  by the cron enforcers. Reuse or extend it rather than adding a second pause mechanism.
  Nothing re-arms the crons while paused. `persistent_cron_assertor` and
  the failsafe-cron advisors stay quiet, including on the compact's SessionStart, and the
  pause is recorded in a durable marker the daemon reads.
- [x] ✅ **Task 4.5** (merged; record `src/claude_code_hooks_daemon/utils/usage_pause.py`,
  `<session>.usage-paused` in the context sidecar; supervisor `_usage_pause_outcome`; live
  worker reloaded cleanly): The supervisor compact, in this repository. The supervisor is
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
- [x] ✅ **Task 4.6** (merged 506fd3f5e): Resume. When the resume cron fires, the gate re-reads usage. A window
  past its `resets_at` reads as absent, so a snapshot from before the reset cannot keep
  the session paused. Then:
  - below the ceiling: lift the pause, re-establish the declared crons, and continue the
    active work;
  - still over the ceiling (for example the weekly window): schedule the next resume cron
    and stop again.
- [x] ✅ **Task 4.7** (merged 506fd3f5e): Data safety. No snapshot, or no `rate_limits` at all, never pauses a
  session, and a debug log line records why. A paused session shows `⏸ usage` and its resume
  time in the status line.
- [x] ✅ **Task 4.8**: Acceptance tests. Run a live probe with a synthetic snapshot above the
  ceiling through the whole cycle: pause directive, cron set reduced to the resume cron,
  stop allowed, resume tick lifts the pause.
  - Handler cycle: every step passed in an isolated in-process harness with synthetic
    sessions
    ([report](subagent-reports/261002-p479-acceptance-sonnet.md)).
  - Daemon chain: `tests/integration/test_usage_pause_daemon_chain.py` (merged; 17 tests)
    runs the whole cycle through `controller.process_request`. The responses validate
    against the schemas, and the halting deny carries `continue: false` and `stopReason`.
    Other deny handlers do not drop the halt.
  - Residual: real `CronDelete`/`CronCreate` calls are verified only through the Stop gate's
    reading of `session_crons`. The first real pause on a host with a `hosts:` ceiling
    exercises them.

### Phase 5: Docs and release

- [x] ✅ **Task 5.1**: Write the configuration docs, the handler guidance, and a release note.

## Open questions for the owner

1. **Resolved (owner)**: pause, then resume through a scheduled cron at the predicted reset,
   with a supervisor compact before it (Phase 4).
   **Coordinator call (2026-10-05, under the owner's "go with the clear winners" instruction):** Q2 lowest ceiling wins; Q3 one number with per-window overrides; Q4 fold cron host lists into the `hosts:` block at the next major, keeping the old form working until then. Q2 to Q4 resolved; not owner rulings.

2. **Resolved (coordinator call)**: several matching entries: being built with the recommended default, the lowest
   ceiling wins, as the safer choice. The owner can overrule it with first match in file
   order.

3. **Resolved (coordinator call)**: one threshold or one per window: being built with the recommended default.
   `max_used_percent` applies to both windows, with optional `five_hour` and `seven_day`
   overrides.

4. **Resolved (coordinator call)**: folding `persistent_crons` host selection into the `hosts:` block at the next major, with the old form working until then.

## Success Criteria

- [x] The status line shows 5-hour and weekly usage from live payloads, and shows nothing
  for a session without the data. Seen live (Task 2.2); the no-data case is tested.

- [ ] A session on a host whose entry sets `max_used_percent: 80` pauses once a window
  reaches 80%:

  - it refuses new work and halts the running turn;
  - it ends with only a resume cron scheduled for the window's reset;
  - it resumes on that tick.

  A session on a host with no entry is unaffected.

  Verified through the daemon chain with a synthetic host
  (`tests/integration/test_usage_pause_daemon_chain.py`, Task 4.8). Still unobserved: a real
  session on a configured host making real `CronDelete`/`CronCreate` calls. Owner ruling D8
  (2026-10-06, [OWNER-RULINGS-261006.md](../00483-threat-model-conformance-audit/OWNER-RULINGS-261006.md)):
  dogfood it in this repository's own always-on session, on its datacentre VM, at 80%. This
  supersedes the earlier rule that this repository's config never carries a ceiling. The
  entry is keyed by the role alias `cchd-sdlc-runner` (owner, same day: a session's alias
  supersedes its hostname), not by the VM's real name, which stays out of the public config.
  The alias goes in the gitignored `.claude/ccy/ccy.env.local` on this VM
  (`export HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner`), which ccy 3.80+ sources after `ccy.env`.
  Owner ruling (same day): that file is written by IaC only, never by an agent, so the copy
  the coordinator had written was removed. The alias, and with it this check, waits for IaC
  to write the file; it then takes effect at the next ccy launch, and also makes this session
  the `issue-sdlc` cron's host. Live since the 2026-10-06 host reboot: the session after it
  has `HOOKS_DAEMON_HOSTNAME=cchd-sdlc-runner`, and the stop enforcer demanded the
  host-limited `issue-sdlc` cron, which was created. The ceiling pause itself is now armed
  in this session and is observed the first time a window reaches 80%.

- [x] Missing or stale usage data never stops a session (Task 4.7; acceptance step 6 and the
  chain test).

## Delivery & Milestones

- Plan filed with the owner's host-first and pattern rulings.
