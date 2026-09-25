# Callout: the ccy supervisor no longer injects any `/effort` command

**Plan**: 00466
**Audience**: operators

Claude Code saves every interactively-typed `/effort <level>` into your own
`settings.json` under `modelSettings`, so a supervisor-typed "restore" or
"floor" permanently overwrote your own saved level — the exact fight the
supervisor was meant to end. It now holds no effort opinion and types no
`/effort` command at all, ever. The Fable-at-low ceiling and the downgrade
xhigh compensation are now `modelSettings` entries you add yourself; see the
post-upgrade task for the exact entries and
`CLAUDE/development/CcySupervisor.md` for the full explanation.
