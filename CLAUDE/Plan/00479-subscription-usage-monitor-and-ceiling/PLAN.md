# Plan 00479: subscription usage monitor and ceiling

**Status**: Not Started
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
- Changing the ccy supervisor. It is outside this repository, and its live instance is not
  touched.

## Tasks

### Phase 1: Ground truth

- [ ] ⬜ **Task 1.1**: Vendor the status line docs page with `hooks-daemon remote-docs add`.
  Record in `CLAUDE/Architecture/StatusLine.md` that `rate_limits` is now read.
- [ ] ⬜ **Task 1.2**: Capture real Status payloads into test fixtures: a main thread with
  data, before the first response (absent), a subagent or `--agent` thread, and integer and
  fractional percentages. Establish whether subagent threads carry `rate_limits`.

### Phase 2: Usage snapshot and status line segment (TDD)

- [ ] ⬜ **Task 2.1**: Keep the latest snapshot from each Status event: window, percentage,
  `resets_at` and when it was seen. Hold it per session in daemon state and persist it
  host-wide, so a fresh daemon or a session that has not yet rendered can read it. Treat a
  window past its `resets_at` as absent.
- [ ] ⬜ **Task 2.2**: A status-line usage segment, for example `5h 13% (3h 20m) · 7d 3%`, with
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

### Phase 4: Ceiling enforcement (TDD)

- [ ] ⬜ **Task 4.1**: A `UserPromptSubmit` gate. At or above the ceiling it blocks the
  prompt, cron ticks and supervisor messages included, and names the window, its
  percentage, the ceiling and the reset time.
- [ ] ⬜ **Task 4.2**: A `PreToolUse` gate that returns `continue: false` with a
  `stopReason`, so a turn already running halts at its next tool call.
- [ ] ⬜ **Task 4.3**: Every handler that forces continuation stands down above the ceiling,
  so the session can actually stop. That covers unattended-mode Stop blocking, stop
  explanation re-entry, and the cron stop and subagent enforcers.
- [ ] ⬜ **Task 4.4**: Suppress declared cron ticks while over the ceiling, reusing the
  awaiting-human marker machinery, so an idle stopped session costs no turns.
- [ ] ⬜ **Task 4.5**: Data safety. No snapshot, a stale snapshot, or no `rate_limits` at all
  means no stop, with a debug log line. Being stopped is visible in the status line.
- [ ] ⬜ **Task 4.6**: Acceptance tests and a live probe with a synthetic snapshot above the
  ceiling.

### Phase 5: Docs and release

- [ ] ⬜ **Task 5.1**: Write the configuration docs, the handler guidance, and a release note.

## Open questions for the owner

1. **After the window resets**: should the session resume on its own (the next cron tick
   below the ceiling simply proceeds), or stay stopped until a human restarts it?
   Recommended: resume. The 5-hour window resets often, and a pause leaves the headroom
   without needing a human.
2. **Several matching entries**: recommended that the lowest ceiling wins, being the safer
   choice. The alternative is first match in file order.
3. **One threshold or one per window**: `max_used_percent` applies to both windows.
   Recommended: also allow optional `five_hour` and `seven_day` overrides.
4. **Folding `persistent_crons` host selection** into the `hosts:` block later.

## Success Criteria

- [ ] The status line shows 5-hour and weekly usage from live payloads, and shows nothing
  for a session without the data.
- [ ] A session on a host whose entry sets `max_used_percent: 80` refuses a cron tick and
  halts a running turn once a window reaches 80%. A session on a host with no entry is
  unaffected.
- [ ] Missing or stale usage data never stops a session.

## Delivery & Milestones

- Plan filed with the owner's host-first and pattern rulings.
