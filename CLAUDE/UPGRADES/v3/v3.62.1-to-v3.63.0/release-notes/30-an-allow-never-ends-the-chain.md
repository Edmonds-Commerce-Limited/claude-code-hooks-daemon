# Callout: an ALLOW never ends the chain

**Plan**: 00242
**Audience**: handler authors

Terminality is now a property of the DECISION, not of the handler. A DENY
(or ASK/DEFER) from a `terminal=True` handler still ends the dispatch chain —
nothing later could un-deny it — but an ALLOW from any handler continues to
the next handler with its context kept, whatever its `terminal` flag says. The
class of defect Plan 00241 patched four instances of (a terminal handler's
advisory ALLOW silently disabling every handler behind it) cannot recur for
any handler, built-in or project-level, and its narrow warn-mode guard is
replaced by that invariant. The one exception is per event: the
PermissionRequest chain treats `auto_approve_reads`' approval as conclusive,
because approving a permission IS the answer. On the Stop chain this means a
handler registered above `auto_continue_stop` now runs on an ALLOWED stop and
is shadowed only when the stop is blocked. The first restrictive handler owns
both the reason shown and the `To disable:` footer, so the two can no longer
name different handlers. `daemon.chain.collect_all_violations` (off by
default) additionally keeps the chain running after a deny and returns one
merged response — the first deny leading, the others as bounded excerpts,
the advisories in one table — at a measured ~2 ms on the worst four-violation
path. Rate-limited advisories (`command_hints`, `recovery_cron_advisor`) no
longer spend a cooldown on a tool call that ended up denied: the new
`Handler.commit_side_effects()` hook hears the chain's final decision and
rolls the bookkeeping back, and the handler history now records each
handler's OWN verdict, so `lsp_enforcement`'s block-once is no longer burnt by
another handler's deny.
