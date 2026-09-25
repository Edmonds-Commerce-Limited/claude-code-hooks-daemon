# Task: add `modelSettings` entries for ccy supervisor effort

**Type**: config-migration
**Severity**: recommended
**Applies to**: all versions before this fix (Plan 00466) whose ccy session
relied on the supervisor's own `/effort` injections
**Idempotent**: yes

## Why

The ccy supervisor used to type `/effort low` whenever Fable ran above low
(Plan 00297's DROP ANCHOR) and `/effort xhigh` on a downgrade's fallback model
(downgrade compensation) itself. Claude Code saves every interactively-typed
`/effort <level>` except `max` (session-only, unless pinned through
`CLAUDE_CODE_EFFORT_LEVEL`) into `modelSettings` in your own `settings.json`,
so those injections permanently overwrote your own saved level — the fight
the redesign exists to end. The supervisor now injects no `/effort` command at all; the
levels those injections aimed for are per-model `modelSettings` entries you
add yourself.

**This only applies while the session's own effort has never been set.**
Claude Code applies a model's saved `modelSettings` level automatically only
while the session is still at its starting ("inherit") effort state. Any
`/effort <level>`, `/effort auto`, an effort pick in the `/model` picker's
slider, `--effort`, or `CLAUDE_CODE_EFFORT_LEVEL` PINS one value across every
later model and fallback for the rest of that session, and nothing un-pins
it mid-session — see `CLAUDE/development/CcySupervisor.md` for the full
explanation and citations. If a session has already pinned an effort, these
`modelSettings` entries will not apply until a fresh session starts without
touching effort at all.

## How to detect if this applies to you

Applies to every ccy user of this project who wants to keep either behaviour.
Check whether your settings file already has these entries (sample, adapt
the path to `$CLAUDE_CONFIG_DIR/settings.json` or `~/.claude/settings.json`
if you keep the owner's settings there instead of project settings):

```bash
grep -A2 '"claude-fable-5-1"\|"claude-opus-5"\|"claude-opus-4-8"' ~/.claude/settings.json
```

If nothing matches (including because the file does not exist — check that
separately, `2>/dev/null` on the sample above would hide an unreadable file
too), the entries are missing.

Then run `hooks-daemon check`: its "Effort Source" line is `[WARN]` when
`CLAUDE_CODE_EFFORT_LEVEL`, or a top-level `effortLevel` in the project or
local settings file, pins one level on every model — which would override
these per-model entries. Remove any pin it names.

## How to handle

Merge three entries into the `modelSettings` object of the settings file the
owner wants this applied to: `claude-fable-5-1` at `low`, and `claude-opus-5`
and `claude-opus-4-8` at `xhigh`. The exact JSON, and what each entry covers
and does not cover, is in `CLAUDE/development/CcySupervisor.md`, section "What
the owner should add to `modelSettings`" (in a client install, under
`.claude/hooks-daemon/`). Leave `claude-opus-5-5` out: it stays at its own
`medium` default.

Never edit the owner's real settings file without asking first — this task
is advisory; report the exact JSON and let the owner (or an authorised
session) apply it.

## How to confirm

The settings edit itself takes effect on the next request (no relaunch
needed for the DATA) — but this fix ALSO changed the supervisor's own CODE,
which needs a worker hot-reload or a full ccy relaunch to stop the OLD
in-process fallback path from still typing `/effort` (see
`CLAUDE/development/CcySupervisor.md`, "How the reload is noticed"). Relaunch
ccy, then confirm the session header shows the expected effort level for
that model, and that no supervisor action typed anything.

## Rollback / if this goes wrong

Remove the added `modelSettings` entries (or the whole key, if nothing else
uses it); Claude Code falls back to its own per-model default.
