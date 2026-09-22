# Cache measurements and the warming arithmetic

## The harness already computes all of this — read `prompt_cache`

**Read this section before any of the rest.** Most of the transcript analysis
below turned out to be unnecessary: the `Status` event payload already carries
a fully-formed `prompt_cache` object, captured verbatim here from this
repository by enabling `daemon.payload_capture` (already scoped to `[Status]`)
for a few renders:

```json
{
  "warm": true,
  "caching_observed": true,
  "ttl": "1h",
  "expires_at": 1790079347,
  "requests": 4610,
  "misses": 14,
  "expected_rebuilds": 14,
  "hit_ratio": 0.9912764873518866,
  "cache_write_tokens": 10122957,
  "miss_recache_tokens": 4301557,
  "last_miss_at": 1789970486,
  "last_miss_cause": { "causes": ["messages_rewritten"] },
  "miss_causes": { "effort_changed": 2, "messages_rewritten": 12 },
  "recache_tokens_if_cold": 383761
}
```

Every input the warming decision needs is in there, already derived:

| need                        | field                            |
| --------------------------- | -------------------------------- |
| is the cache alive now      | `warm`                           |
| which TTL is in force       | `ttl`                            |
| exactly when it dies        | `expires_at` (unix seconds)      |
| `N`, the cost of going cold | `recache_tokens_if_cold`         |
| hit ratio                   | `hit_ratio`                      |
| **what invalidated it**     | `miss_causes`, `last_miss_cause` |

`expires_at` is the important one: the supervisor does not have to ESTIMATE
the gap or the TTL, it has a deadline. And `recache_tokens_if_cold` is `N`
measured rather than inferred from a transcript tail.

The same payload also carries `context_window` (with `context_window_size`,
here 1,000,000, and a `current_usage` breakdown) and `cost`
(`total_cost_usd`). So the status-line segment needs **no transcript reading at
all** for main-thread figures — no 68 MB tail-read, no `mtime_cache`, none of
the performance problem that shaped the original design.

### `miss_causes` is the invalidation answer, per session, already classified

This session: **14 misses in 4,614 requests**, attributed entirely to
`effort_changed` (2) and `messages_rewritten` (12).

That is direct evidence on the open question about hook denials. This session
issued many `PreToolUse` denials — `sed`, pipe-to-tail, LSP-symbol, write-clobber,
QA-suppression, self-matching-pgrep — and **not one appears as a miss cause**.
Every miss is accounted for by effort changes and message rewrites
(compaction). Consistent with the documented behaviour that scoped, call-time
checks leave the prefix intact.

Not proof — a cause the harness does not model could be folded into another
bucket — but it moves hook denials from "unknown, possibly dominant" to
"no evidence of any cost", and it removes the argument for re-cutting the plan
around them.

### What still needs the transcript

Only sub-agent figures. `prompt_cache` describes the main thread, so the
`SubagentStop` aggregation stays as designed.

---

## Original transcript-based analysis

Retained because it is how the sub-agent numbers were obtained, and because the
arithmetic is unchanged.

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

## The upstream documentation, vendored — what it CONFIRMS and what it OVERTURNS

`remote-docs/code.claude.com/docs/en/prompt-caching.md` (captured with
provenance). Read AFTER the measurements below were taken, which makes it a
check on them rather than their source.

**Confirms the hook-denial experiment.** Only a BARE tool-name deny rule can
invalidate, and only when tool search is unavailable or disabled: *"Scoped deny
rules like `Bash(rm *)`, and all allow and ask rules, don't change which tools
Claude sees. Claude Code checks them when Claude attempts a call, leaving the
prefix intact."* Every rule this daemon ships is of that second kind.

**Overturns Task 4.4's premise outright**, and the doc files it under *Actions
that KEEP the cache*: *"Your project-root and user-level CLAUDE.md files are
read once at session start and held in memory. Editing them mid-session does
not invalidate the cache, but the edit also doesn't apply."* So the planned
"editing a prefix-resident file is expensive" advisory would have warned about
a cost that does not exist. The measurement had already put the premise in
doubt; this settles it. **Nested CLAUDE.md files and `paths:`-scoped rules are
the exception** — they load lazily, so an edit BEFORE first load does take
effect.

**Confirms the measured TTL split, and names the lever.** Sub-agents *"fall
outside the main-conversation TTL bucket, so they get five minutes even on a
subscription"*. The controls are `promptCacheTtl` /
`CLAUDE_CODE_PROMPT_CACHE_TTL` for the main conversation and
**`subagentPromptCacheTtl` / `CLAUDE_CODE_SUBAGENT_PROMPT_CACHE_TTL`** for
everything else; both take `5m` or `1h` and need Claude Code v2.1.242+. A
sub-agent's own `experimental.cacheTtl` frontmatter is a further override
(v2.1.248+). `FORCE_PROMPT_CACHING_5M=1` beats all of them.

This is the concrete answer to "can we enforce that TTLs are explicitly
configured so we have visibility?" — the knob exists and is per-bucket.

**Confirms the overage caveat**: the one-hour TTL applies only *"on a Claude
subscription within your plan's included usage"*; past the limit the main
conversation drops to five minutes.

**Two findings this project should act on that the plan had not considered:**

1. **Worktrees each build their OWN cache.** *"the cache is effectively scoped
   to one machine and directory … That includes worktrees of the same
   repository."* This project dispatches agents into isolated worktrees as a
   matter of course, and every one of them starts cold.
2. **`/rewind` is cheaper than `/compact`.** Rewind *"truncates back to a
   prefix that is already cached, rather than building a new one as compaction
   does."*

**Corrects one thing in this document.** There is no `/cost` command; the
per-session summary is `/usage`, which carries a `Prompt cache (main)` line
(v2.1.251+) with hit ratio, miss count and warm state — the same figures the
`prompt_cache` status-line object exposes.

## Hook denials do NOT invalidate the cache — measured, not inferred

Task 3.2 flagged this as the question that could outrank the whole plan: this
project's PreToolUse deny rules fire constantly, so if a denial invalidated
the prefix, nothing else in this plan would matter. **The answer is negative.**

Run as a direct experiment with `daemon.payload_capture` scoped to `[Status]`:

| Reading                         | `misses` | `requests` | `warm` |
| ------------------------------- | -------- | ---------- | ------ |
| baseline                        | 15       | 4,863      | true   |
| after `R-SED-FILE-MODIFICATION` | 15       | 4,865      | true   |
| after `R-GIT-STASH-PUSH`        | 15       | —          | true   |
| after `R-CHMOD-WORLD-WRITABLE`  | 15       | 4,869      | true   |

Three denials from three different handlers. Six requests flowed across them —
so this is not a case of nothing having happened — and `misses` never moved,
the attributed cause map never changed, and the cache stayed warm throughout.
Across 37 captured renders only ONE distinct miss count was ever observed.

**Why the experiment was necessary rather than reading `miss_causes` alone.**
The observational evidence (15 misses, all attributed to `effort_changed` and
`messages_rewritten`, none to a denial) is suggestive but cannot settle it:
absence of a "hook denial" category is equally consistent with the taxonomy
simply not having one and denials being filed under `messages_rewritten`. Only
moving the counter — or failing to — distinguishes those.

**Consequence**: the plan's "if positive, re-cut the scope around it" branch
does not fire. Deny-heavy projects carry no prompt-cache penalty for it, and
the invalidation-protection half of this plan can stay focused on what the
data DOES implicate — `messages_rewritten`, which is 13 of the 15.

Caveat worth keeping: this is one session, one model, three handlers. It is
strong evidence about PreToolUse denials, not a general claim about every hook
outcome.

## The measured gap profile, and why it proves the circularity

`hooks-daemon cache-gaps` over this session's own transcript:

| Gap bucket | Count |
| ---------- | ----- |
| `<1m`      | 7,696 |
| `1-5m`     | 66    |
| `5-15m`    | 88    |
| `15-60m`   | 233   |
| `>60m`     | **0** |

8,083 gaps. **321 cross a 5-minute TTL. ZERO cross the 1-hour TTL. The largest
gap in the entire session is 3,598 seconds — two seconds under 3,600.**

That figure is not a coincidence and it is not a healthy session found in the
wild. This project runs hourly crons, and they are holding the idle gap
underneath the TTL by a margin of two seconds. The session is warm *because
something is warming it*.

So the 98.87% hit ratio measured here **cannot be used to argue that warming
is unnecessary** — it is a measurement of a warmed session, and the warming is
the cron. Reasoning from it to projects in general is circular, and this table
is the evidence of the circularity rather than an answer to the question.

The genuinely transferable finding is the SPLIT: the same gap profile that
never crosses the 1-hour TTL crosses the 5-minute one 321 times. A project's
sub-agents can therefore be going cold repeatedly while its main thread never
does — which is exactly the half the status bar could not previously see.

**Task 2.4 remains open and cannot be closed from inside this repository.** The
tool now exists and any project can run it; what is missing is a transcript
from a HUMAN-PACED project, where the gaps are set by a person's attention
rather than by a scheduler.
