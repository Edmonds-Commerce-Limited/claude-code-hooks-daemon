# Cache measurements and the warming arithmetic

Evidence behind [PLAN.md](PLAN.md). Everything here was measured from this
repository's own session transcripts or verified against the Claude Code
documentation; where a figure is unconfirmed it says so.

## Where the data lives

Each assistant record in a session transcript carries `message.usage`:

```
cache_read_input_tokens   cache_creation_input_tokens   input_tokens   output_tokens
cache_creation: { ephemeral_5m_input_tokens, ephemeral_1h_input_tokens }
```

The main-thread transcript is the per-project session JSONL. **Sub-agent usage
is not in it** — every one of the 7,634 usage records in the measured session
is `isSidechain: false`, and no record anywhere in that file has
`isSidechain: true`. Sub-agent transcripts live in the harness task directory,
one file per agent, interleaved with plain-text bash outputs that are not
JSONL at all.

Practical consequence for any reader: a naive `jq -s` over that directory
exits 4 on the first non-JSON file. Parse per line with `fromjson?`.

## Main thread versus sub-agents

Measured over one long dogfood session.

|             | records | read tokens   | write tokens | hit    | TTL      | effective |
| ----------- | ------- | ------------- | ------------ | ------ | -------- | --------- |
| main thread | 7,634   | 1,849,355,510 | 20,993,274   | 98.87% | 1-hour   | 0.113x    |
| scout agent | 74      | 3,739,621     | 227,136      | 94.27% | 5-minute | 0.166x    |
| guide agent | 12      | 302,080       | 183,790      | 62.17% | 5-minute | 0.535x    |

"Effective" is the blended input multiplier,
`(0.1 x read + W x write + 1.0 x uncached) / total_input`, against a floor of
0.10x.

**The TTL split is measured, not assumed**: 100% of sub-agent writes were
`ephemeral_5m`, 100% of main-thread writes `ephemeral_1h`. The documentation
agrees — sub-agents fall in the "everything else" bucket, which defaults to
the 5-minute TTL.

**Dispatch has a floor cost.** The first write is mandatory and paid once per
agent, so a short agent never amortises it. The 12-request agent spent 38% of
its input on writes and came out 4.7x less cache-efficient per token than the
main thread, whose prefix is already resident at 0.1x. The 74-request agent
recovered most of it. The amortisation curve between those two points is what
decides whether a delegation is cheap.

The counterweight is real and should be measured before anyone acts on this: a
sub-agent keeps work OUT of the main prefix, slowing its growth and deferring
compaction. This is a trade-off to quantify, not an argument against
delegating.

## Prefix size through a session

|                               | tokens  |
| ----------------------------- | ------- |
| mean over first 200 requests  | 130,550 |
| mean over last 200 requests   | 195,654 |
| peak                          | 509,560 |
| largest sub-agent prefix seen | 383,000 |

It grows, but not monotonically — compaction resets it, so the curve
sawtooths. The span matters because the cost of one invalidation is `W x N`:
**a 3.9x swing in the price of being wrong inside a single session.**

## Sub-agent compaction: evidence, not proof

Scanning 27 sub-agent transcripts for the markers the main transcript uses
(`isCompactSummary`, `compactMetadata` — 14 occurrences there) found **zero**.

That is consistent with "sub-agents never compact" and equally consistent with
"none of these 27 reached its threshold" — the main thread peaked at 509,560,
so the largest sub-agent at 383,000 may simply be under the limit. A third
possibility is a different marker spelling in sub-agent transcripts.

Supporting but still indirect: the docs are silent on whether
`autoCompactEnabled` / `autoCompactWindow` apply to sub-agents, describe each
sub-agent as starting fresh in an isolated window, and document `/compact`
only as a user command. This repository's own `acceptance-test` skill says
sub-agents "run out of context on large test suites" — exhaustion language.

The decisive test is a sub-agent driven deliberately to its ceiling, observing
what the coordinator receives: error, truncated report, or silent stop.

## The warming arithmetic

Warming is a cache READ, so covering an idle gap `G` on TTL `T` costs
`(G / 0.9T) x 0.1 x N`. Not warming costs `P x W x N`, where `P` is the chance
the session resumes and `W` the write multiplier. Warming is cheaper when:

```
G  <  9 x T x P x W
```

`N` divides out of both sides, so the DECISION is size-independent. With
`W = 1.25` on the 5-minute TTL and a session certain to resume, that is a gap
of about **56 minutes** — comfortably inside normal human pauses, which is why
a human-paced project can profit from warming and an always-driven one cannot.

### Why the always-on measurement cannot settle it

The 98.87% above came from a session with two hourly crons firing into it. The
crons ARE a warming mechanism, so that number measures a warmed session and
cannot be used to argue warming is unnecessary. It describes one end of the
spectrum only.

### The smallest practical warm turn — and why shaving it is pointless

Output-token distribution over 7,691 main-thread requests: min 0, p10 136,
median 358, mean 509. Turns of 10 output tokens or fewer do occur — 27 of them
— so a near-empty reply is achievable.

It does not matter. Cost the two halves at `N` = 195,654:

| component                             | token-equivalents    | share      |
| ------------------------------------- | -------------------- | ---------- |
| cache read (`0.1 x N`)                | ~19,565              | **99.8%**  |
| reply of ~5 output tokens             | ~25                  | 0.1%       |
| permanent context growth (~50 tokens) | ~5 per later request | negligible |

**The read IS the cost.** A warm ping cannot be made meaningfully cheaper than
`0.1 x N`, because the whole point is to read the prefix. Effort spent
wordsmithing the prompt optimises 0.1% of the bill.

**This corrects an earlier overstatement.** The claim that a fixed per-ping
overhead `C` sets a prefix-size floor below which warming never pays was based
on `C` ~ 250 tokens; measured, a minimal turn's `C` is nearer 25-60. At
`N` = 10k that is 2-6% of the ping, not the dominant term. So the floor from
output overhead is weak, and channel 1 below should be treated as minor.
Channel 3 (compaction proximity) is the one that stands.

### The hook-heavy trap: a minimal ping is not one turn

In a project with Stop handlers, a bare `ok` is the MOST expensive reply
available. This repository's `auto_continue_stop` denies any stop without a
`STOPPING BECAUSE:` prefix, so `ok` is blocked and the model is re-invoked —
a second request, a second `0.1 x N` read, and more output. **The naive
minimal ping costs double.**

Two ways out, and the second is better:

1. Make the reply satisfy the handlers in one turn, e.g.
   `STOPPING BECAUSE: [cache-warm] no-op.` — still around 10 output tokens.
2. Have the Stop-family handlers RECOGNISE a warm ping and stand down, the way
   `scope: MAIN` already gates handlers by role. A marker in the ping prompt is
   the natural key. This is better because option 1 depends on every project's
   handler set independently, and any project that adds a Stop handler silently
   doubles its warming cost again.

Either way the requirement is explicit: **a warm ping must complete in exactly
one request.** Anything that re-fires the model doubles the only cost that
actually matters.

### Where `N` re-enters

1. **A fixed per-ping overhead sets a floor.** A ping costs `0.1N + C`, where
   `C` is its own output tokens and per-request overhead and does not scale
   with `N`. Near `N` = 10k the two are the same order and warming loses
   whatever the gap; by `N` = 200k, `C` is noise.
2. **Pings grow the context they protect**, permanently, bringing compaction
   forward — warming can cause the invalidation it prevents. A warm ping must
   be minimal: no tool calls, shortest possible reply.
3. **Proximity to compaction voids it.** A session about to compact is about to
   be invalidated anyway.

## Confirmed and unconfirmed constants

|                                                                | status                                          |
| -------------------------------------------------------------- | ----------------------------------------------- |
| cache read = 0.1x                                              | confirmed                                       |
| 5-minute write = 1.25x                                         | confirmed                                       |
| 1-hour write                                                   | **unconfirmed** — docs say only "a higher rate" |
| reading a cache entry resets its TTL                           | confirmed                                       |
| Claude Code manages `cache_control` placement; no user control | confirmed                                       |
| OTel attribute separating cacheRead from cacheCreation         | **unconfirmed**                                 |

`/usage` reports a "Prompt cache (main)" line with hit ratio, miss count, TTL
and warm/cold. There is no `/cost` command.

Invalidators confirmed by the docs: model switch, effort-level change, MCP
server connect/disconnect, compaction, image limit reached, Claude Code
upgrade, and **bare** deny rules such as `Bash` when tool search is
unavailable. **Scoped** deny rules (`Bash(rm *)`) and all allow/ask rules are
checked at call time and leave the prefix intact.

Whether a `PreToolUse` HOOK denial invalidates is **not documented anywhere**.
It matters here more than in most projects, because this daemon's deny rules
fire constantly. The scoped-rule language suggests runtime checks are
prefix-safe, but that is inference.

## The supervisor sidecar

One JSON object, so the supervisor does arithmetic rather than guesswork. Raw
counters so a future question needs no new sensor; the multipliers in the file
so confirming the 1-hour rate is a data change, not a code change.

```json
{
  "schema_version": 1,
  "captured_at": "2026-09-22T09:14:03Z",
  "session_id": "e5e72775",
  "main": {
    "requests": 7634,
    "cache_read_tokens": 1849355510,
    "cache_write_tokens": 20993274,
    "uncached_input_tokens": 15120,
    "output_tokens": 3777920,
    "ttl_5m_write_tokens": 0,
    "ttl_1h_write_tokens": 20993274,
    "prefix_tokens_latest": 195654,
    "prefix_tokens_peak": 509560,
    "last_request_at": "2026-09-22T09:13:21Z",
    "last_write_at": "2026-09-22T08:02:11Z"
  },
  "sub": {
    "agents_seen": 27,
    "requests": 86,
    "cache_read_tokens": 4041701,
    "cache_write_tokens": 410926,
    "ttl_5m_write_tokens": 410926,
    "ttl_1h_write_tokens": 0,
    "worst_agent_hit_ratio": 0.6217
  },
  "context": {
    "used_pct": 61.2,
    "window_size": 200000,
    "tier": "orange",
    "red": false,
    "compact_urgent": false
  },
  "constants": {
    "read_multiplier": 0.1,
    "write_multiplier_5m": 1.25,
    "write_multiplier_1h": null,
    "ping_overhead_tokens": 250,
    "min_prefix_tokens_to_warm": 50000
  }
}
```

`write_multiplier_1h` is `null` deliberately: a null that forces the
supervisor to abstain is safer than a plausible number that silently biases
every decision. `last_request_at` lets the supervisor compute `G` itself.
`context` mirrors `context_sidecar`'s existing classifications rather than
re-thresholding a raw percentage — Plan 00135 Decision J, so the status
segment and the supervisor cannot drift.
