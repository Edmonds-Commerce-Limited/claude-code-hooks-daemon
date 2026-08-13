# Verdict Log

The daemon makes hundreds of handler decisions per session and — before Plan
00209 — persisted none of them. `verdicts.jsonl` is the daemon's own audit
trail: one line per matched handler's decision, written automatically, with
no per-handler opt-in required.

This closes the gap a field report described directly: "the daemon makes
hundreds of decisions per session and persists none of them... every
interesting question about the tool — which handlers earn their keep, what
the real false-positive rate is per handler, whether a handler is in the
wrong mode — is currently unanswerable, and answerable cheaply."

## Where it lives

```
{daemon untracked dir}/logs/hooks/verdicts.jsonl
```

Same directory as `notifications.jsonl` and `subagent_completions.jsonl` —
normal install: `.claude/hooks-daemon/untracked/logs/hooks/`; self-install:
`untracked/logs/hooks/`.

## Schema

One JSON object per line:

```json
{"ts": "2026-08-12T09:14:03+00:00", "session": "abc123", "event": "PreToolUse",
 "tool": "Bash", "handler": "pipe_blocker", "verdict": "deny",
 "rule": "blacklisted", "mode": "block", "overridden": false}
```

| Field        | Meaning                                                                                                                                                                                                        |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ts`         | ISO-8601 timestamp (UTC).                                                                                                                                                                                      |
| `session`    | Session ID from the hook payload (`"default"` if absent).                                                                                                                                                      |
| `event`      | Hook event name (`PreToolUse`, `PostToolUse`, ...).                                                                                                                                                            |
| `tool`       | Tool name for this event (`Bash`, `Write`, ...), empty string if not applicable.                                                                                                                               |
| `handler`    | The handler that made this decision. `null` only for the synthetic override record below.                                                                                                                      |
| `verdict`    | The handler's own decision: `allow`, `deny`, `ask`, `continue` — or the synthetic `override`.                                                                                                                  |
| `rule`       | Optional, handler-set sub-classification (e.g. `pipe_blocker` distinguishes `"blacklisted"` vs `"unknown"`). `null` when a handler doesn't set one — most don't, and that's fine.                              |
| `mode`       | Derived from `verdict`: `"block"` for deny/ask, `"advisory"` otherwise. This is NOT each handler's own configured block/warn option (no generic way to read that) — it is what actually happened on this call. |
| `overridden` | `true` only on the synthetic escape-hatch record (see below); `false` on every normal per-handler entry.                                                                                                       |

### Every matched handler gets its OWN verdict, not the chain's merged one

A dispatch can match several handlers. The daemon's most-restrictive-wins
rule (Plan 00144) means the final decision shown to the agent can differ
from what an individual non-terminal handler itself returned. The verdict
log always records each handler's own decision — captured once, in
`HandlerChain.execute()` (`core/chain.py`), before any later handler's
result can change what the eventual merged outcome looks like.

### The synthetic `override` record

Handlers that implement the project's `MUST_..._BECAUSE=`/`MUST_..._BECAUSE:`
escape-hatch convention (`git_stash`, `root_recursion_guard`,
`plan_workflow`, `comment_size`, `comment_changelog`, `plan_qa_edit`, ...)
make `matches()` return `False` when their own hatch is present — so the
bypassed handler never appears in the log for that event at all. Detecting
the *shared shape* of the convention once (`daemon/verdict_log.py`) still
surfaces that an override happened:

```json
{"handler": null, "verdict": "override", "rule": null, "mode": null, "overridden": true}
```

This cannot name which specific handler was bypassed — only that an escape
hatch was used somewhere in the payload. That is still the strongest
available signal that a rule may be mis-tuned (a human decided a block was
wrong for this specific call).

## Retention: a rolling sample, not a durable counter

`verdicts.jsonl` is capped the same way as every other daemon JSONL log
(`utils/retention.py`'s `cap_log_file` — Plan 00181): on breach, the oldest
half is trimmed. This is a deliberate, documented trade-off (Plan 00209 Task
2.4), made explicit because Plan 00206 hit exactly this trap with a
different log: **a cap that discards the oldest half silently corrupts any
cumulative statistic derived from it.**

Concretely: a handler that fired long ago and was since trimmed out of the
window will look like it "never fired" if you only check the log's current
contents. `hooks-daemon verdicts` states this explicitly in its own output
— every number it prints describes the **retained window**, never a
lifetime total. If you need true lifetime counters, this log is not that;
building one would require a separate, never-truncated aggregate file,
which was deliberately not built here to keep the feature proportionate to
its value (see the plan's Non-Goals).

Default cap: 10 MB (`daemon.verdict_log.max_bytes` in `.claude/hooks-daemon.yaml`).

### Status renders are not recorded

A status handler RENDERS — it can only ever return `allow`, so its records
carry no information, and they arrive at the status line's refresh rate rather
than at the rate decisions are made.

Left in, they do not merely add noise, they consume the window. Measured on
this daemon's own log (Plan 00234): **43,929 of 44,180 retained records were
status renders — 99.43%**, filling the 10 MB cap in **65 minutes**. A log built
to answer "which handlers earn their keep?" could see one hour of one session.
Excluding them stretches the same cap to roughly **8 days**.

The filter is on the EVENT, not on a `status-*` name prefix: what makes these
records worthless is the event they serve, and a name test would both miss a
renamed handler and catch an unrelated one.

Status handlers are also omitted from the report's never-fired roster. Without
that, excluding their records would have turned 14 renderers into false "never
fired" entries — trading one misleading signal for another. Fired-ness is a
question about handlers that DECIDE.

Set `record_status_events: true` to opt back in when debugging the status line
itself, and expect the retained window to shrink to about an hour again.

## Configuration

```yaml
daemon:
  verdict_log:
    enabled: true # default — metadata only, never tool payloads or file contents
    max_bytes: 10485760 # 10 MB rolling-sample cap
    record_status_events: false # default — status renders are 99% noise (see above)
```

Default-on, unlike `payload_capture` (which records raw payloads and ships
off by default): the verdict log never records command text, file content,
or any payload — only handler/rule/verdict metadata — so there is no
privacy reason to ship it dormant.

## Reporting: `hooks-daemon verdicts`

```bash
./bin/hooks-daemon verdicts            # human-readable report
./bin/hooks-daemon verdicts --json     # machine-readable
./bin/hooks-daemon verdicts --log-file /path/to/verdicts.jsonl   # override path
```

Reports:

- Total recorded decisions (in the retained window)

- Override count and rate

- Per-handler fire counts, with each handler's own verdict mix

- Overall verdict mix across all handlers (allow/deny/ask/override)

- **Never-fired handlers** — only available when the daemon is running (the
  full registered-handler set is queried over the socket, the same way
  `hooks-daemon handlers` does); reports "unavailable" rather than a
  misleadingly empty list when it cannot be determined. Status handlers are
  excluded (see above).

  **"Never fired" is NOT evidence a handler is pointless.** A guard on a rare,
  catastrophic operation is SUPPOSED to sit silent — rarity is what success
  looks like for it, and this list only ever covers the retained window. Read
  it as "not exercised in this window", and establish that a handler *cannot*
  fire from its code before concluding anything. The report says so in its own
  output for the same reason.

## See also

- `src/claude_code_hooks_daemon/daemon/verdict_log.py` — the writer
- `src/claude_code_hooks_daemon/daemon/verdict_report.py` — the reader/aggregator
- `src/claude_code_hooks_daemon/core/chain.py` — `HandlerVerdict` / `ChainExecutionResult.decisions`
- `CLAUDE/Plan/00209-field-feedback-daemon-self-observability/` — the plan and originating field report
