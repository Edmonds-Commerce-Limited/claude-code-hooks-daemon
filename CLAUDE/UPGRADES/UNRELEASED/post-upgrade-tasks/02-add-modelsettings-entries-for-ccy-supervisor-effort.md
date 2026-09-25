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
you add yourself, which Claude Code applies automatically whenever that
model serves a request (see `CLAUDE/development/CcySupervisor.md`).

## How to detect if this applies to you

Applies to every ccy user of this project who wants to keep either behaviour.
Check whether your settings file already has these entries (sample, adapt
the path to `$CLAUDE_CONFIG_DIR/settings.json` or `~/.claude/settings.json`
if you keep the owner's settings there instead of project settings):

```bash
grep -A2 '"claude-fable-5-1"\|"claude-opus-5"\|"claude-opus-4-8"' ~/.claude/settings.json 2>/dev/null
```

If nothing matches, the entries are missing.

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

- `claude-fable-5-1` at `low` replaces the DROP ANCHOR ceiling.
- `claude-opus-5` and `claude-opus-4-8` at `xhigh` cover Fable's two
  automatic-fallback targets (biology-flagged requests land on Opus 5,
  cybersecurity-flagged requests land on Opus 4.8), so whichever one an
  episode falls back to keeps the old compensation.

Never edit the owner's real settings file without asking first — this task
is advisory; report the exact JSON above and let the owner (or an
authorised session) apply it.

## How to confirm

Relaunch ccy (or wait for the next request on the model in question) and
confirm the session header shows the expected effort level for that model —
no supervisor action is needed for it to apply.

## Rollback / if this goes wrong

Remove the added `modelSettings` entries (or the whole key, if nothing else
uses it); Claude Code falls back to its own per-model default.
