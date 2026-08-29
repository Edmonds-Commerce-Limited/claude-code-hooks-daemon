# Status Line Handlers

Handlers for the `status_line` hook event: they assemble the terminal status
line Claude Code displays (model/context, git, environment, daemon health,
supervisor state).

**Canonical documentation**:
[CLAUDE/Architecture/StatusLine.md](/CLAUDE/Architecture/StatusLine.md) — the
single source of truth for the system design, handler chain, output format,
width-aware wrapping, configuration, and how to add new elements. The live
per-project handler roster is generated into
[.claude/HOOKS-DAEMON.md](/.claude/HOOKS-DAEMON.md); do not maintain a
hand-written handler table here.

## Edit guard: concurrency is a FIRST-CLASS CONCERN

Status-line code is inherently concurrent (every render; multiple sessions
share one daemon; the ccy PTY supervisor writes/reads some of the same
files). BEFORE adding or changing any handler here that touches a file or
shared in-memory state, read and honour the three non-negotiable rules in
StatusLine.md's "Concurrency & Thread Safety" section — atomic-replace
writes, fail-silent reads, lock-guarded shared state. `context_sidecar.py`,
`thread_registry.py` and `supervisor_indicator.py` are the conforming
references to mirror. The paired writer-side guidance sits at the top of
`.claude/ccy/claude-supervise.py`.
