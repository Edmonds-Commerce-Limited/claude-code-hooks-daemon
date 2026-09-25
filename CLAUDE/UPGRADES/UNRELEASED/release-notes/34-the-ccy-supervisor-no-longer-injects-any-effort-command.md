# Callout: the ccy supervisor no longer injects any `/effort` command

**Plan**: 00466
**Audience**: operators

Claude Code saves every interactively-typed `/effort <level>` into your own
`settings.json` under `modelSettings`, so a supervisor-typed "restore" or
"floor" permanently overwrote your own saved level — the exact fight the
supervisor was meant to end. It now holds no effort opinion and types no
`/effort` command at all, ever. The Fable-at-low ceiling and the downgrade
xhigh compensation are now `modelSettings` entries you add yourself, which
apply only in a session that never sets its own effort (`/effort`, an
effort pick in `/model`, `--effort`, or the env var); see the post-upgrade
task for the exact entries and `CLAUDE/development/CcySupervisor.md` for the
full explanation. **Relaunch ccy** after upgrading — a worker reload alone
leaves the old in-process fallback able to type `/effort` until the host
restarts too.
