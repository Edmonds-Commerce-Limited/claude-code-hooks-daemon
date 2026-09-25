# Callout: settings.json is now the single source of truth for ccy supervisor effort

**Plan**: 00466
**Audience**: operators

The ccy supervisor used to keep its own opinion of per-model effort (a
built-in floor table plus the `CCY_MIN_EFFORT_LEVELS` env var), which could
fight Claude Code's own `settings.json` — a configured medium effort could
still be overwritten with `/effort high`, or `/effort xhigh` on every model
restore. The supervisor now reads `settings.json` directly (per-model
`modelSettings.<model-id>.effortLevel`, falling back to the top-level
`effortLevel`) and only falls back to its built-in defaults when
`settings.json` configures nothing for a family. A restore to a
previously-downgraded model now lands on that model's configured effort
instead of xhigh. `CCY_MIN_EFFORT_LEVELS` no longer has any effect —
configure effort in `settings.json` instead. `settings.json` is re-read on
change, so an edit takes effect without a supervisor relaunch.
