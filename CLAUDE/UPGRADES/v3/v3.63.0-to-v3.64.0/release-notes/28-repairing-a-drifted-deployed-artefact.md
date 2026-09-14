# Callout: a drifted daemon-owned file can now actually be repaired

**Plan**: 00377
**Audience**: operators

Daemon-owned files deployed into your project — the agents under
`.claude/agents/`, the core documents under `CLAUDE/core/` — are refreshed on
upgrade and never clobber local edits. Two gaps meant a file that drifted could
not be brought back.

**`agents install <name> --force`.** When a deployed agent no longer matched any
shipped revision, the daemon refused to touch it and advised running
`hooks-daemon agents install <name>` — which is the command that had just
refused, so following the advice failed again. The refusal is correct and stays:
a bulk refresh must never discard your edits. It now has an explicit escape.
Only naming the agent AND passing `--force` overwrites it, and the result says
a customised copy was discarded rather than reporting a plain update.

**`hooks-daemon deploy-core-docs`.** Core documents were deployed only by the
install and upgrade scripts, so a project whose `CLAUDE/core/*.core.md` had gone
stale had no way to refresh them short of a full upgrade — and nothing reported
the drift, because nothing compares a deployed artefact with the template it
came from. This is the equivalent of `agents install` for core docs:
client-owned overrides are untouched, only daemon-owned files are rewritten.

If you have never edited a daemon-owned file, neither change affects you.
