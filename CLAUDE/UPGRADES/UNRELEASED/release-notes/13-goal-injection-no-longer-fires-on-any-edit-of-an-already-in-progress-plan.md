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
when the triggering Write/Edit is itself what moved the Status line.
`goal_injection`'s primary source of truth is a ground-truth PreToolUse
snapshot: a companion `plan_status_snapshot` handler reads the plan's
status immediately BEFORE the same Write/Edit lands and hands it to
`goal_injection` for the SAME tool call (matched by `tool_use_id`) — no
reconstruction, so a bare status value that also happens to appear
elsewhere in the document (a table cell, the plan's own title) can no
longer be misread either way. When no snapshot exists for a given call (a
daemon restart between the two dispatches, or a payload with no
`tool_use_id`) it falls back to reading its own Edit's replaced span
(reconstructing the pre-edit text from disk when the span carried only the
bare status value, with no `**Status**:` prefix) or, for a Write, git HEAD
read from the file's OWN enclosing repository (not necessarily the project
root's — a nested worktree checkout is a separate repo); that fallback use
is logged. `recovery_cron_advisor`'s Write path shares that same HEAD
comparison and has no snapshot of its own. An edit or rewrite whose
replaced/compared span never touched the Status line emits nothing from
either handler THROUGH THE FLIP PATH (no new ledger record, no
displacement advisory) — a session touching an already-live plan without
flipping it can still cause its OWN `/goal` signal to be (re)written, see
below.

**Two behaviours from Plan 00276/00269 are preserved, not just "no action
needed":**

- **A plan going terminal drops it from every CURRENT owning session's
  combined `/goal` text, when the triggering write is itself what moved
  the plan into that terminal status.** The retirement refresh used to key
  on an in-memory latch that a daemon restart empties; it now asks the
  persistent goal ledger instead, so a plan flipped in one daemon process
  and completed in the next is still retracted promptly. Like the flip
  side, the refresh only fires on a genuine transition INTO a terminal
  status — a later edit that merely touches an already-Complete plan (a
  note before its archive move, say) refreshes nobody. "Current owner" is
  resolved from the plan's live ledger entry, or else its MOST RECENTLY
  retired one, so a plan reopened and completed a second time retracts
  whoever actually did that, not a stale session from an earlier
  completed-then-reopened lifecycle. A session also becomes an owner of
  every plan its OWN combined `/goal` text names — not only the plan that
  triggered its write — so a plan it never directly touched still
  refreshes correctly for it later. Ownership per plan is capped (the
  oldest owner drops first past the cap) so a rolling ledger plan touched
  by dozens of teammates cannot grow its refresh cost without bound.
- **A resumed session still gets its `/goal` back — including a resume
  with the SAME session id.** Plan 00269 relied on "the first edit to an
  already-In-Progress plan re-fires" to survive a session restart. A
  session touching an already-live plan without itself producing a real
  flip is added to that plan's ledger entry (alongside whoever already
  owns it, never replacing them) and gets its own signal (re)written —
  with none of a real flip's side effects (no new ledger record, no
  displacement of any other live plan, no "GOAL DISPLACED" advisory). This
  fires once per `(session, plan)` per daemon lifetime — including
  immediately after that same session's own real flip, so an unrelated
  follow-up edit in the same lifetime does not write a redundant second
  signal — so a resumed session whose signal file was lost across a
  restart gets it back even though its session id and ledger history are
  unchanged. A session that already real-flipped a DIFFERENT plan of its
  own does not implicitly absorb an unrelated plan it merely happens to
  touch. For a Write specifically (not an Edit, which reads its own
  before/after span directly), git HEAD can lag an uncommitted flip that
  already landed on disk and in the ledger; the ledger — not HEAD — is
  authoritative for whether a plan has already started, so a teammate's
  Write to an already-ledgered-live plan is never misread as a fresh flip
  even before anyone commits.

No other action is needed — everything above is automatic.
