# Callout: the ccy supervisor no longer injects any `/effort` command

**Plan**: 00466
**Audience**: operators

Claude Code saves every interactively-typed `/effort <level>` except `max`
(session-only, unless pinned through `CLAUDE_CODE_EFFORT_LEVEL`) into your own
`settings.json` under `modelSettings`, so any level the supervisor typed
permanently overwrote your own saved level — the exact fight the supervisor
was meant to end. It now holds no effort opinion and types no
`/effort` command at all, ever. Fable at `low` and its fallback models at
`xhigh` are now per-model `modelSettings` levels you add yourself, which
apply only in a session that never sets its own effort (`/effort`, an
effort pick in `/model`, `--effort`, or the env var); the exact entries are
in `CLAUDE/development/CcySupervisor.md`, and the post-upgrade task walks
through adding them. `hooks-daemon check` no longer recommends an effort
level either: its "Effort Source" line warns when `CLAUDE_CODE_EFFORT_LEVEL`
(the shell variable, or the same variable set through any settings file's own
`env` object) or a project/local top-level `effortLevel` pins one level on
every model.
**Relaunch ccy** after upgrading — a worker reload alone leaves the old
in-process fallback able to type `/effort` until the host restarts too.
