# Research: usage and rate-limit data in Claude Code

Gathered for Plan 00479 against installed Claude Code v2.1.287. Sources:

- S: <https://code.claude.com/docs/en/statusline>, sections "Rate limit usage" and "Available data". Not yet vendored; Task 1.1 captures it.
- H: the vendored `remote-docs/code.claude.com/docs/en/hooks.md`.
- C: the Claude Code `CHANGELOG.md` on GitHub.

The full agent report, with line references, was saved untracked as
`untracked/agent-reports/261002-usage-statusline-research-sonnet.md`. The findings
that drive this plan follow.

## The status line payload is the only official source

| Field                                         | Type and unit                                         |
| --------------------------------------------- | ----------------------------------------------------- |
| `rate_limits.five_hour.used_percentage`       | number, 0 to 100, may be fractional (rolling 5 hours) |
| `rate_limits.seven_day.used_percentage`       | number, 0 to 100 (weekly window)                      |
| `rate_limits.{five_hour,seven_day}.resets_at` | Unix epoch seconds                                    |
| `rate_limits.spend_limit.*`                   | only behind a Claude apps gateway; can exceed 100     |

- **Introduced** in v2.1.80 (C). `spend_limit` arrived in v2.1.251.
- **Who gets it**: claude.ai Pro and Max subscribers only. API-key users never do.
- **When it is absent**: before the session's first API response. Each window can also be
  absent on its own, and a window is dropped once its `resets_at` has passed.
- **Not in the payload**: per-model weekly limits and extra-usage data. Those exist only in
  the undocumented OAuth usage endpoint that `/usage` itself calls. This plan does not use it:
  it needs the user's OAuth credential and is rate-limited.
- **Seen live here.** This session's daemon log holds Status payloads carrying
  `{'five_hour': {'used_percentage': 13, 'resets_at': 1790938800}, 'seven_day': {'used_percentage': 3, 'resets_at': 1791525600}}`.
  The daemon already receives the data and does nothing with it
  (`CLAUDE/Architecture/StatusLine.md`, "Documented but currently UNUSED").
- **Refresh**: the status line re-runs on a new assistant message, on other events, on
  `refreshInterval`, and when a window reaches its `resets_at`. It can go quiet while the
  session is idle.

## No hook payload carries usage

No hook event's input carries `rate_limits` (H). `StopFailure` reports
`error: "rate_limit"` only after the limit has been hit. So the daemon has to keep the last
snapshot from the Status event and hand it to its other handlers. The daemon handles Status
itself, so the snapshot can live in daemon state rather than a file a script writes.

## Community status lines

- **claude-powerline** renders 5-hour and weekly segments from the payload only. It hides
  them when the data is absent, shows a bar, warns at 80%, shows a reset countdown such as
  `4h 12m`, and has an optional pace display (used against elapsed share of the window).
- **ccstatusline** also calls the undocumented OAuth usage endpoint for per-model weekly
  data. It caches the result for 180 s and backs off on 429.
- **The trend**: status lines written since `rate_limits` existed prefer the official
  payload data.

## Ways a hook can stop an unattended session (H)

- **`continue: false` with `stopReason`**: works on any event. Claude stops processing after
  the hook, and this overrides event-specific decisions. It ends the current turn; it does
  not end the process.
- **`UserPromptSubmit` `decision: "block"`**: rejects the prompt. Cron ticks and supervisor
  nudges arrive as prompts, so this is the gate for loops (inferred, to be verified).
- **`PreToolUse` deny**: blocks one tool call only. Combined with `continue: false` it halts
  the session.
- **Stop hook**: can only BLOCK a stop. Any handler that forces continuation (unattended
  mode, stop-explanation re-entry, cron enforcement) must stand down above the ceiling, or it
  will drive the session past it.
- **The `autoContinueAtUsageLimit` setting** (default on) auto-resumes after a usage limit.
  It is relevant only once a real limit is hit, which the ceiling exists to prevent.

## Unverified

- Whether `rate_limits` is populated in subagent and `--agent` threads. Usage is
  account-wide, so the main thread's snapshot serves.
- Whether `continue: false` also prevents a later cron or loop re-wake. The
  `UserPromptSubmit` gate covers that case either way.
