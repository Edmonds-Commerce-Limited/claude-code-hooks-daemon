# Callout: a read-only subagent blocked on report size gets a way out that does not bypass content guards

**Plan**: 00460
**Audience**: operators

`subagent_report_size_blocker` used to tell every oversized-report subagent
to "write the report to a file", even one with no `Write` tool (the built-in
`Explore`/`Plan`, or any project agent whose frontmatter omits `Write`) — the
only thing such an agent could then do was reach for a Bash heredoc or
redirect, which lands on disk unexamined by the sensitive-content,
secret-file and markdown-location guards a real `Write` call gets. A
Write-less agent is now told to condense its reply under the threshold
instead, with an explicit warning against writing around the missing tool.
`dispatch_declaration` separately advises a coordinator whose dispatch
prompt declares a report destination for an agent type that cannot write
one. Writable and unresolvable agent types are unaffected.
