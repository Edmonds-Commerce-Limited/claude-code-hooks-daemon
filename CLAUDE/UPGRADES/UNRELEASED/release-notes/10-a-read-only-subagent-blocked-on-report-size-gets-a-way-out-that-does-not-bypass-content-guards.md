# Callout: the daemon now auto-saves every sub-agent's reply, and the report-size blocker points at it

**Plan**: 00460
**Audience**: operators

`subagent_report_size_blocker` used to tell every oversized-report subagent
to "write the report to a file", even one with no `Write` tool (the built-in
`Explore`/`Plan`, or any project agent whose frontmatter omits `Write`) — the
only thing such an agent could then do was reach for a Bash heredoc or
redirect, which lands on disk unexamined by the sensitive-content,
secret-file and markdown-location guards a real `Write` call gets.

The daemon now closes that gap at the source instead of only warning about
it: at every `SubagentStop`, `subagent_report_persistence` saves the
stopping agent's full final reply to a gitignored file under
`untracked/agent-reports/` — regardless of agent type, `Write` access, or
reply size. Nothing depends on the agent's own cooperation or tool set.
Never overwrites (a collision gets a numeric suffix), never blocks a stop
(persistence failing is logged, not fatal), and is pruned to a bounded cap
(default 500 files / 30 days) after every write.

`subagent_report_size_blocker` now points an over-threshold agent at that
already-saved path and asks for a short summary in reply, instead of asking
it to write a file itself — the "write the report to a file" instruction is
gone for every agent type when persistence succeeded, with the old
instruction kept only as a fallback for the rare case persistence failed.
`dispatch_declaration` mentions the same auto-saved path as a safety net,
separate from the destination a dispatch prompt should still declare.
