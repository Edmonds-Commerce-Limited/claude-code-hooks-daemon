# Callout: optimise scores every handler, derived from the registry

**Plan**: 00330
**Audience**: everyone

`/hooks-daemon optimise` no longer works from a hand-written list of 22
handlers: its checklist is produced by the new `hooks-daemon optimise-checklist` verb, which walks the handler registry, so all 116
handlers — status-line components and the nitpick detectors included — are
scored on every run and a handler cannot ship unreviewed. Each handler now
declares its own relevance (`Handler.get_relevance()`): `lsp_enforcement`
needs an LSP, the npm handlers a `package.json`, the ccy handlers an armed
supervisor, the flaggable-content trio a deployed quarantine agent. A relevant
handler's optimal state is enabled whatever its default, so a default-off
handler whose precondition holds is now recommended, and one whose
precondition is missing is reported as "not applicable here" with the reason
rather than as a shortfall — the old unconditional `lsp_enforcement`
recommendation goes with it. The report groups handlers into six computed
areas and collapses every fully-enabled area to one line, listing only what
to enable and what does not apply. A release-gate test now fails if a
registered handler is invisible to optimise, if the skill documents a CLI
verb that does not exist, names a retired handler, or references a config
key the schema does not define.
