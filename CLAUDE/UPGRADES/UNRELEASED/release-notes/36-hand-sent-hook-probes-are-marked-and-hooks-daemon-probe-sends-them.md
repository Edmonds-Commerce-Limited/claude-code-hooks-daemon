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
own scripts or briefs. One limit: a marked probe is never shown to a handler
scoped `MAIN` or `SUB`, such as `auto_continue_stop`, so a marked Stop probe
answers `{}`. The command prints a note saying so. To test such a handler,
send the probe unmarked.
