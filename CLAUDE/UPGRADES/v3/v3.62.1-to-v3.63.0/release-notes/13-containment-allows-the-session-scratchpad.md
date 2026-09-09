# Callout: project_containment allows the session scratchpad Claude Code names

**Plan**: 00362
**Audience**: everyone

Claude Code's system prompt tells the agent to put temporary files in a
per-session scratchpad under the system temp directory, and
`project_containment` denied every write there, so each session burned a
blocked call on the contradiction. The handler now allows exactly the
directory the harness names in the hook payload (`scratchpad_dir`) and
nothing else under the temp directory; its guidance and deny message say so,
and still send anything durable to `untracked/scratch/`.
