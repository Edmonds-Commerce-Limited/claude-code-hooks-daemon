# Callout: SessionStart messages now carry an action tier, and it is computed

**Plan**: 00416
**Audience**: everyone

Session-start output has grown to the point where an agent reads all of it and
acts on none of it — every advisory looks equally urgent, so none of them is.
Each SessionStart message now carries one of three tiers, rendered into the
emitted block: `ACTION_REQUIRED`, `ACTION_SUGGESTED` or `INFO`.

**The tier is computed, never declared.** A message is `ACTION_REQUIRED` only
if it ships a verifier AND that verifier is currently failing — that is, the
session is genuinely mis-configured, not merely improvable. A handler cannot
assert its own importance: a `declared_tier` arriving from anywhere is clamped
to `INFO` and logged at ERROR. Tier inflation is therefore impossible by
construction rather than discouraged by convention, which matters because
every handler author sincerely believes their advisory is the important one.

`bin/hooks-daemon session-actions` prints the current tier for every
SessionStart handler (`--format json` for machine reading), so you can see what
a session would be told without starting one.
