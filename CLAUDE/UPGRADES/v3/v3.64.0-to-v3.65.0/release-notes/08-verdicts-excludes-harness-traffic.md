# Callout: `hooks-daemon verdicts` no longer counts its own test harness

**Plan**: 00418
**Audience**: operators

`verdicts.jsonl` recorded acceptance-playbook probes and the forwarder's
socket-test fires in the same undifferentiated stream as your agents' real
tool calls — on this project's own log that was half the window — so every
per-handler count the report printed blended a harness with a workflow.
Records now carry a `synthetic` field naming the harness that produced them,
and the report excludes them by default; pass `--include-synthetic` to fold
them back in when you are debugging the harness itself. Expect your
per-handler counts to drop and a handler that only ever fired in the
acceptance suite to move into "never fired", which is the accurate statement:
no agent reached it in this window.
