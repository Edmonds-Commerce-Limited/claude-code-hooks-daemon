# Callout: a slow handler can no longer bypass the rest of the chain on a client timeout

**Plan**: 00466
**Audience**: operators

The hooks client gives the daemon a 30s socket timeout
(`--timeout-ms 30000`). On a read-side timeout, the client's own fallback
emits an advisory `hookSpecificOutput` with context only — an ALLOW for every
non-`Stop` event. So a handler slow enough to run out that budget bypassed
every handler still queued behind it in the chain, not just itself. This was
not hypothetical: `destructive_git`'s `strip_inert_spans` measured at 99s on
a 200 KB `git commit` carrying many repeated `-m` flags, and 98s on a 200 KB
command carrying many quoted-delimiter heredocs, both already on `main`
before this plan.

Four changes close this:

- The daemon now enforces its own per-event chain deadline
  (`daemon.chain.deadline_seconds`, default 20s — well under the client's
  30s), independent of the client's own timeout. When the deadline is
  exceeded mid-chain, every `SAFETY`+`BLOCKING` handler not yet run is denied
  under the fail-closed rule above, with a "not judged in time" reason naming
  the handler; every other not-yet-run handler is skipped instead, with an
  advisory note. Setting `deadline_seconds: null` disables enforcement.
- **The client itself now also fails CLOSED on its own timeout, for
  PreToolUse specifically** (`.claude/init.sh`): a socket timeout, a crashed
  daemon, or a response that is not one of PreToolUse's two legitimate
  shapes now denies, rather than emitting the advisory-only
  `hookSpecificOutput` described above. This was deliberately NOT done in an
  earlier version of this fix, reasoned as "would turn a merely slow,
  overloaded host into a denial of every tool call" — that reasoning did not
  survive review: an overloaded host is exactly the condition under which a
  guard being skipped is least acceptable, and the daemon-side deadline
  above already tells a slow handler apart from a malicious payload before
  the client's timeout is ever reached. **If a client host is slow enough
  that the daemon-side deadline is not the thing firing, every PreToolUse
  tool call is now denied with `socket_timeout` until the host recovers.**
  This is the single most operator-visible behaviour change in this plan.
- `strip_inert_spans` (`shell_segmentation.py`) is now linear. The quadratic
  cost came from re-deriving prefix-dependent state from scratch on every
  regex match (segment/subcommand resolution, substitution depth, heredoc
  receiving-segment boundaries) instead of advancing incrementally in the
  guaranteed left-to-right match order. Both measured repros now run in
  well under half a second.
- A new test harness drives every `pre_tool_use` handler (not only
  `SAFETY`-tagged ones) with hostile inputs — many small quoted/backslashed/
  wildcarded tokens, deep command-substitution nesting, and long
  whitespace/quote runs — asserting on GIL starvation (a concurrent thread's
  own wakeup gap) as well as wall clock, so a future super-linear handler,
  or one that merely holds the GIL for its whole run, fails CI instead of
  reaching a client. Two shipped handlers were found this way and fixed:
  `lsp_enforcement` and `plan_number_helper` both held the GIL for
  70+/35+ seconds on a hostile whitespace/quote run.

If your own security review or documentation ever assumed a slow handler
could only deny or allow itself, re-check that claim for the version before
this fix — a slow handler silently allowed everything queued behind it too.
If it assumed the client stays fail-open on its own timeout, that is also no
longer true for PreToolUse.
