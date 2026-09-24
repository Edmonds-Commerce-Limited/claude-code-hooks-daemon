# Callout: a slow handler can no longer bypass the rest of the chain on a client timeout

**Plan**: 00466
**Audience**: operators, security reviewers

The hooks client gives the daemon a 30s socket timeout
(`--timeout-ms 30000`). On a read-side timeout, the client's own fallback
emits an advisory `hookSpecificOutput` with context only — an ALLOW for every
non-`Stop` event. So a handler slow enough to run out that budget bypassed
every handler still queued behind it in the chain, not just itself. This was
not hypothetical: `destructive_git`'s `strip_inert_spans` measured at 99s on
a 200 KB `git commit` carrying many repeated `-m` flags, and 98s on a 200 KB
command carrying many quoted-delimiter heredocs, both already on `main`
before this plan.

Three changes close this:

- The daemon now enforces its own per-event chain deadline
  (`daemon.chain.deadline_seconds`, default 20s — well under the client's
  30s), independent of the client's own timeout. When the deadline is
  exceeded mid-chain, every `SAFETY`+`BLOCKING` handler not yet run is denied
  under the fail-closed rule above, with a "not judged in time" reason naming
  the handler; every other not-yet-run handler is skipped instead, with an
  advisory note. Setting `deadline_seconds: null` disables enforcement.
  Deliberately NOT a remedy: making the *client* fail closed on its own
  timeout would turn a merely slow, overloaded host into a denial of every
  tool call — the deadline belongs inside the daemon, which can tell safety
  handlers from advisories.
- `strip_inert_spans` (`shell_segmentation.py`) is now linear. The quadratic
  cost came from re-deriving prefix-dependent state from scratch on every
  regex match (segment/subcommand resolution, substitution depth, heredoc
  receiving-segment boundaries) instead of advancing incrementally in the
  guaranteed left-to-right match order. Both measured repros now run in
  well under half a second.
- A new test harness drives every `SAFETY`-tagged `pre_tool_use` handler with
  hostile inputs (many small quoted/backslashed/wildcarded tokens, deep
  command-substitution nesting) under a time bound, so a future super-linear
  handler fails CI instead of reaching a client.

If your own security review or documentation ever assumed a slow handler
could only deny or allow itself, re-check that claim for the version before
this fix — a slow handler silently allowed everything queued behind it too.
