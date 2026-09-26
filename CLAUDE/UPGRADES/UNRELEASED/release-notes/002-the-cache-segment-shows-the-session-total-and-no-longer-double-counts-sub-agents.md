# Callout: the cache segment shows the session total, and no longer double-counts sub-agents

**Plan**: 00452
**Audience**: operators

The status line's prompt-cache segment now shows all three figures the plan
set out to show: main, sub-agents and the whole session. Once a sub-agent has
run it reads `⚡ 99% 1h sub 94% 5m total 98%`.

- `sub NN% 5m` now carries the TTL the sub-agents actually wrote under
  (`5m`, `1h`, or `5m+1h` if the sub-agent TTL setting changed mid-session).
  The two halves run different TTLs by default, so the main thread's TTL was
  wrong for them.
- `total NN%` is the session weighted by tokens, not an average of the two
  percentages. It is possible because the payload's `hit_ratio` is itself
  token-weighted (checked against a real transcript: 0.991145 against
  0.991149), so main-thread reads can be recovered from it and
  `cache_write_tokens`. Where they cannot (no write count, or a ratio of
  exactly 1.0), no total is shown rather than an invented one.

**The sub-agent figure was wrong before this.** Claude Code writes one
transcript record per content block, and each carries the whole request's
usage. The sensor summed records, so it counted every request about twice
(measured: 4,276 records for 2,119 requests), inflating sub-agent write
tokens 1.5–2.3x and shifting individual agents' ratios by up to 1.8 points
across the twelve largest measured. It now counts
each request once, keyed on its message id.

Sub-agents that finished before the upgrade keep their old sidecar figures
for the rest of that session. New sessions are correct from the start.
