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
it: at every `SubagentStop`, including a re-entry after another handler's
block, `subagent_report_persistence` saves the stopping agent's full final
reply to a file under `untracked/agent-reports/auto/` — a subdirectory the
daemon exclusively writes into, distinct from the `untracked/agent-reports/`
parent a coordinator or agent may separately be told to hand-author a
non-plan report into. Persistence runs regardless of agent type, `Write`
access, or reply size, so nothing depends on the agent's own cooperation or
tool set.

Genuinely gitignored, not just conventionally so: a `*` `.gitignore` is
written into the directory the first time it is created, so the guarantee
holds even in a project whose own ignore rules say nothing about it. The
content itself is **not** vetted — no sensitive-content, secret-file or
markdown-location check runs, the file is only kept out of git's view.
Never overwrites (a same-second collision gets a numeric suffix), never
blocks a stop (persistence failing, or an unsafe `report_dir`, is logged,
not fatal), and is pruned to a bounded cap (default 500 files / 30 days)
after every write — pruning only ever touches the `auto/` subdirectory,
never a hand-authored report sitting in its parent.

`subagent_report_size_blocker` now points an over-threshold agent at that
already-saved path and asks for a short summary in reply, instead of asking
it to write a file itself — the "write the report to a file" instruction is
gone for every agent type when persistence succeeded, with the old
instruction kept only as a fallback for the rare case persistence failed.
`dispatch_declaration` mentions the same auto-saved path as a safety net,
separate from the destination a dispatch prompt should still declare.
