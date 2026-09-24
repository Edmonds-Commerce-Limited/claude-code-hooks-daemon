# Callout: `goal_injection` and `recovery_cron_advisor` no longer fire on any edit of an already-In-Progress/Complete plan

**Plan**: 00466
**Audience**: operators

`goal_injection` (the ccy PTY supervisor's `/goal`-setting sensor) matched
the post-write STATE of a plan's `**Status**` line, not a TRANSITION to it,
so the first Write or Edit in a session to any plan that was already In
Progress fired — a table-row addition, a task tick, a typo fix. That
spuriously ledgered the touched plan as owed work, could displace a
genuinely live plan's `/goal` condition with a "GOAL DISPLACED" advisory,
and had the Stop hook challenge stops on the spuriously ledgered plan's
behalf. `recovery_cron_advisor`'s Write-path completion check had the same
defect shape for `**Status**: Complete`: rewriting an already-complete plan
re-injected the CronDelete teardown advisory every time. Both now fire only
when the triggering Write/Edit is itself what moved the Status line;
`goal_injection` reads its own Edit's replaced span (reconstructing the
pre-edit text from disk when the span carried only the bare status value,
with no `**Status**:` prefix) or, for a Write, git HEAD read from the
file's OWN enclosing repository (not necessarily the project root's — a
nested worktree checkout is a separate repo); `recovery_cron_advisor`'s
Write path shares that same HEAD comparison. An edit or rewrite that leaves
an already-In-Progress or already-Complete status unchanged emits nothing
from either handler.

**Two behaviours from Plan 00276/00269 are preserved, not just "no action
needed":**

- **A plan completing after a daemon restart still drops out of the
  combined `/goal` text.** The retirement refresh used to key on an
  in-memory latch that a restart empties; it now asks the persistent goal
  ledger instead, so a plan flipped in one daemon process and completed in
  the next is still retracted promptly.
- **A resumed session still gets its `/goal` back.** Plan 00269 relied on
  "the first edit to an already-In-Progress plan in a NEW session re-fires"
  to survive a session restart. A session with NO ledger entries of its own
  yet that touches an already-live plan (without itself producing a real
  flip) now has that plan's ledger entry re-assigned to it and gets its own
  signal written — with none of a real flip's side effects (no new ledger
  record, no displacement of any other live plan, no "GOAL DISPLACED"
  advisory). A session that already has its own live goal is unaffected.

No other action is needed — everything above is automatic.
