# Callout: hand-sent hook probes are now marked, and `hooks-daemon probe` sends them

**Plan**: 00466
**Audience**: client projects

A test payload you pipe into `.claude/hooks/<event>` by hand was recorded in
the daemon's `verdicts.jsonl` as a real agent's tool call. That skewed every
figure drawn from the log. The new
`hooks-daemon probe <event> --json '<payload>'` (or `--file <path>`) sends one
payload through your project's hook entry point and prints the decision. It
marks the payload `"synthetic_source": "manual-probe"` so the log records it
as a probe. A payload that already names its own `synthetic_source` keeps
it. Every documented test command now carries the field, so add
`"synthetic_source": "manual-probe"` to any hand-built probe payload in your
own scripts or briefs. A marked probe of a handler scoped to the main thread
or to subagents, such as `auto_continue_stop`, also needs
`"probe_as": "main"` or `"sub"`. Without it, the probe is never shown to that
handler and a Stop probe answers `{}`. The command sets `probe_as: main` by
default; `--as sub` stands for a subagent, with the fixed
`agent_id` `manual-probe-agent`. Only a `manual-probe` source may name a
thread, plus the `transport-verify` probes that `hooks-daemon transport`
now marks when it verifies a toggle, and the daemon's own `test-probe`
acceptance and smoke-test probes. Sub-agent report persistence, the
status-line cache totals, the goal ledger and the human-blocked cron marker
now ignore synthetic events, so a probe never writes into state that real
sessions act on.
