# Task: add `modelSettings` entries for ccy supervisor effort

**Type**: config-migration
**Severity**: recommended
**Applies to**: all versions before this fix (Plan 00466) whose ccy session
relied on the supervisor's own effort floor or downgrade compensation
**Idempotent**: yes

## Why

The ccy supervisor used to type `/effort low` (a Fable ceiling, Plan 00297
DROP ANCHOR) and `/effort xhigh` (downgrade compensation) itself. Claude Code
saves every interactively-typed `/effort <level>` into `modelSettings` in
your own `settings.json`, so those injections permanently overwrote your own
saved level — the fight the redesign exists to end. The supervisor now
injects no `/effort` command at all; both behaviors are `modelSettings` data
you add yourself.

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

## How to handle

Add (or merge into an existing `modelSettings` object) the following to the
settings file the owner wants this applied to:

```json
{
  "modelSettings": {
    "claude-fable-5-1": { "effortLevel": "low" },
    "claude-opus-5": { "effortLevel": "xhigh" },
    "claude-opus-4-8": { "effortLevel": "xhigh" }
  }
}
```

- `claude-fable-5-1` at `low` replaces the DROP ANCHOR ceiling. It does not
  cover Fable 5 (`claude-fable-5`, what a gateway resolves `fable` to) or
  `mythos` ids; add those too if the project's gateway can serve them.
- `claude-opus-5` and `claude-opus-4-8` at `xhigh` cover Fable's two
  automatic-fallback targets (biology-flagged requests land on Opus 5,
  cybersecurity-flagged requests land on Opus 4.8). This is BROADER than the
  old compensation: it now applies an xhigh floor to Opus 5 and Opus 4.8
  wherever they serve in this session (an Opus 5.5 → Opus 4.8 cyber
  fallback, or a manual pick of either), not just a fable-origin episode.

Never edit the owner's real settings file without asking first — this task
is advisory; report the exact JSON above and let the owner (or an
authorised session) apply it.

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
