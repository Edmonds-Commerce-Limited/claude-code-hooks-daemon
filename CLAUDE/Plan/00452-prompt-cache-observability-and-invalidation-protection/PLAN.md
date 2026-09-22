# Plan 00452: prompt cache observability and invalidation protection

**Status**: Not Started
**Created**: 2026-09-22
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

A session bills input at roughly 0.1x when the cached prefix is reused, and at
a write rate (1.25x on the 5-minute TTL, higher and currently unconfirmed on
the 1-hour TTL) whenever the prefix has to be rebuilt. Whether a project pays
mostly reads or mostly writes is decided by ONE thing: how its idle gaps
compare to its TTL.

Nothing here measures that, and the measurement is free — the session
transcript already carries a per-request `usage` object with
`cache_read_input_tokens`, `cache_creation_input_tokens` and a
`cache_creation` sub-object splitting `ephemeral_5m_input_tokens` from
`ephemeral_1h_input_tokens`.

**The gap profile is the whole problem, and it is project-specific.** A
continuously-driven agentic session never idles past its TTL and is already
near the 0.1x floor with nothing to win. A human-paced session — think, read,
go to lunch — crosses the TTL constantly and can spend most of its input budget
rewriting the same prefix. The same advice is right for one and badly wrong for
the other, so this plan measures the profile before recommending anything.

## Calibration data, and why it is NOT a baseline

One dogfood session of this repository measured 1,834,396,352 cache-read
tokens against 20,901,483 cache-write tokens — a **98.87% hit ratio**, 100% of
writes on the 1-hour TTL, mean cached prefix rising 130,550 -> 195,654 tokens
between the first and last 200 requests, peaking at 509,560.

**Do not read that as a typical project.** That session had two hourly crons
firing into it continuously, so it was never idle long enough to lose the
cache. The crons WERE a warming mechanism, which makes the number circular: it
measures a warmed session and therefore cannot be used to argue warming is
unnecessary. It is retained here only as a worked example of the analyser's
output and as the shape of the always-on end of the spectrum.

The interesting case is the opposite end, and this project has no measurement
of it at all.

### The main-thread figure hides the expensive half

Every one of those 7,634 records is `isSidechain: false` — **the 98.87% is main
thread only**. Sub-agent usage is not in that transcript at all; it lives in
the harness task directory, one file per agent, mixed in with plain-text bash
outputs that are not JSONL.

Measured from two sub-agents of the same session:

|             | records | read          | write      | hit    | TTL      | effective |
| ----------- | ------- | ------------- | ---------- | ------ | -------- | --------- |
| main thread | 7,634   | 1,849,355,510 | 20,993,274 | 98.87% | 1-hour   | 0.113x    |
| scout agent | 74      | 3,739,621     | 227,136    | 94.27% | 5-minute | 0.166x    |
| guide agent | 12      | 302,080       | 183,790    | 62.17% | 5-minute | 0.535x    |

Three things fall out, and they drive the design below.

**Sub-agents run on the 5-minute TTL while the main thread runs on the
1-hour.** Measured, not assumed — 100% of every sub-agent write was
`ephemeral_5m`, 100% of every main-thread write was `ephemeral_1h`.

**A dispatch has a floor cost.** The write is mandatory and paid once per
agent, so a SHORT agent never amortises it: the 12-record agent spent 38% of
its input on writes and came out 4.7x less cache-efficient per token than the
main thread. Delegating a small task to a sub-agent is not free — the main
thread's prefix is already cached at 0.1x, and a new agent starts cold at the
write rate. This project carries a standing authorisation to delegate freely,
and the cache cost of doing so has never been quantified. (The counterweight is
real and should be measured too: a sub-agent keeps work OUT of the main
prefix, which slows its growth. This is a trade-off to quantify, not a reason
to stop delegating.)

**A status line showing only the main thread would report 98.87% while the
expensive half is invisible.** That is the argument for three values rather
than one.

## The decision the supervisor actually has to make

Warming is a cache READ, so covering an idle gap `G` on TTL `T` costs
`(G / 0.9T) x 0.1 x N`. Not warming costs `P x W x N`, where `P` is the
probability the session resumes at all and `W` is the write multiplier.
Warming is the cheaper choice when:

```
G  <  9 x T x P x W
```

With `W = 1.25` on the 5-minute TTL and a session certain to resume, that is a
gap of about **56 minutes**. On the 1-hour TTL it is many hours. Both numbers
are large compared with real human pauses, which is why a human-paced project
can genuinely profit from warming and why the idea deserves testing rather than
dismissal.

Everything hard is in the two estimates. `P` is the one that decides it: a
session whose human is at lunch has `P` near 1, an abandoned session has `P`
near 0, and warming an abandoned session is pure loss. A blind cron cannot tell
those apart. A supervisor, which can see whether work is mid-flight, is exactly
the component that can — that is the real argument for putting this in the
supervisor rather than in a cron.

## Context size: not in the decision, but all over the stakes

`N` (the cached prefix, which is essentially context usage) **cancels out of
the inequality above** — warming costs `(G/0.9T) x 0.1 x N` and rebuilding
costs `P x W x N`, so `N` divides out of both sides. Whether to warm is
therefore size-independent, and that is correct rather than an oversight.

What `N` governs is **how much the answer matters**. The cost of one
invalidation is `W x N`, and in the measured session `N` ran from 130,550
early to 509,560 at peak — a **3.9x swing in the price of being wrong, inside
a single session**. So `N` belongs in the WARNING severity and in
prioritisation, not in the choice itself. A cold cache at 10% context is
trivia; the same event at 90% is expensive.

`N` then re-enters the decision through three second-order channels, none of
which the bare inequality captures:

1. **A fixed per-ping overhead sets a floor.** A ping really costs
   `0.1N + C`, where `C` is the ping's own output tokens and per-request
   overhead and does NOT scale with `N`. At `N` ~ 10k, `0.1N` is about 1,000
   tokens and `C` is the same order, so overhead dominates and warming loses
   regardless of the gap. By `N` ~ 200k, `C` is noise. **There is a prefix size
   below which warming is never worth it** — find it, and gate on it.
2. **Pings grow the context they are protecting.** Every ping appends to the
   conversation, so `N` becomes `N + k x delta` permanently and every
   subsequent request pays the larger figure. That growth accelerates the
   arrival of compaction — **warming can cause the very invalidation it
   exists to prevent.** A warm ping must therefore be minimal: no tool calls,
   shortest possible reply.
3. **Proximity to compaction voids the whole thing.** A session about to
   compact is about to be invalidated anyway, so warming it is pure waste. This
   project already computes that signal: `context_sidecar` emits `red`,
   `critical` and `compact_urgent` from the shared `context_tiers` classifier.
   The warming decision should consume `compact_urgent` directly and never
   re-threshold a raw percentage — Plan 00135 Decision J, applied again.

## One JSON object, so the supervisor does arithmetic rather than guesswork

The supervisor should never parse a transcript or re-derive a threshold. It
reads ONE sidecar carrying raw counters, the constants, and the already-shared
classifications, and computes the decision deterministically.

Raw counters rather than verdicts alone, so a future question can be answered
without shipping a new sensor; and the multipliers live IN the file, so when
the 1-hour write rate is finally confirmed it is a data change, not a code
change.

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
    "agents_seen": 11,
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

`write_multiplier_1h` is `null` on purpose: it is not confirmed, and a null
that forces the supervisor to abstain is safer than a plausible number that
silently biases every decision. `last_request_at` is what lets the supervisor
compute `G` itself; `compact_urgent` is gate 3 above, already classified.

## Goals

- **A cache segment in the status line — the first deliverable.** It is the one
  surface every project gets with no configuration, and the number is currently
  invisible everywhere: no project knows its hit ratio, so no project knows
  whether it has a problem. Surfacing it is most of the value, and it is
  useful on its own even if nothing below is ever built.
- A read-only transcript analyser: hit ratio, effective multiplier, TTL mix,
  prefix-size curve, and every request that caused a cache write.
- An **idle-gap histogram** per project, against that project's TTL — the input
  the formula above needs, and the thing that decides whether warming is worth
  anything here.
- An empirical answer to which operations actually invalidate.
- Only then: a supervisor-side decision function implementing the inequality,
  with `P` and `G` estimated from observed session behaviour rather than
  assumed.

## Non-Goals

- **A fixed-interval warming cron.** Not because warming is wrong, but because
  a fixed interval cannot estimate `P`, and warming when `P` is low is the one
  case that strictly loses. The decision has to be conditional.
- **Blocking any edit.** This is cost, not safety; the cost is one bounded
  rewrite.
- **Mandating sub-agents for `CLAUDE.md` edits.** Invalidation follows the FILE
  changing, not who changed it, so delegating does not protect the parent's
  prefix. Batching is the lever that idea is reaching for.
- Controlling `cache_control` placement or TTL — Claude Code manages both.

## Tasks

### Phase 1: Surface it — the status line segment

Ships first and stands alone. Everything after this is optional; this is not.

- [ ] ⬜ **Task 1.0a**: Confirm the Status event delivers `transcript_path`.
  The payload carries `context_window` (`used_percentage`,
  `context_window_size`) but NO cache fields, so the segment must read the
  transcript itself. If `transcript_path` is absent on Status, that is the
  blocker and the whole approach needs re-cutting — establish it first.
- [ ] ⬜ **Task 1.0b**: Tail-read the last complete JSONL record rather than
  parsing the file. The dogfood transcript is 68 MB and the status line
  re-renders constantly; a whole-file parse per render is not viable. Reuse
  the package's existing `mtime_cache` so an unchanged transcript costs
  nothing.
- [ ] ⬜ **Task 1.0c**: Render **three** values — MAIN, SUB and TOTAL. There is
  only one status line and sub-agents do not get their own, so the single bar is
  the only place sub-agent cost can ever surface. A main-only segment would have
  read 98.87% while a sub-agent sat at 62%.
- [ ] ⬜ **Task 1.0c-ii**: Show which TTL is in force, PER SIDE. The two differ
  (5-minute for sub-agents, 1-hour for main), so a single TTL indicator would be
  wrong for one of them. Colour on a poor ratio, following the existing
  `context_tiers` pattern.
- [ ] ⬜ **Task 1.0c-iii**: Do NOT scan the task directory from the status line.
  It held 127 files, most of them not JSONL, and the line re-renders constantly.
  Aggregate at `SubagentStop`: one handler reads the finishing agent's totals
  once and updates a small sidecar; the status line reads that sidecar plus the
  main transcript tail. Same sensor/actuator split as `context_sidecar`.
- [ ] ⬜ **Task 1.0c-iv**: Tolerate unparseable lines when reading an agent
  transcript. A naive `jq -s` over that directory exits 4 on the first
  plain-text file, which would take the whole segment down.
- [ ] ⬜ **Task 1.0c-v**: Flag an invalidation VISUALLY when it happens. The
  cache write IS the ground-truth signal — `cache_creation_input_tokens > 0` on
  the newest record means the prefix was just rebuilt, and its size is the cost.
  This needs no list of suspected causes and cannot be wrong about whether an
  invalidation occurred, unlike a predictive advisory.
- [ ] ⬜ **Task 1.0d**: Put the cold/at-risk classification in ONE shared
  classifier, as Plan 00135 Decision J did for context tiers, so the status
  segment and any later supervisor logic cannot drift apart.

### Phase 2: Measure

- [ ] ⬜ **Task 1.1**: Transcript analyser emitting the metrics above.
- [ ] ⬜ **Task 1.2**: Guard the guard — a fixture transcript with known writes,
  asserting the write-detector finds them. A detector matching nothing would
  report a perfect score on a broken session.
- [ ] ⬜ **Task 1.3**: Idle-gap histogram from request timestamps, bucketed
  against the session's observed TTL.

### Phase 2: Establish what actually invalidates

- [ ] ⬜ **Task 2.1**: Correlate each cache write with the preceding turn.
  Classify: hook denial, prefix-file edit, MCP change, model/effort switch,
  compaction, unexplained.
- [ ] ⬜ **Task 2.2**: Settle the hook-denial question — undocumented, and this
  project's deny rules fire constantly. If hook denials DO invalidate, that
  outranks the rest of this plan and the scope should be re-cut around it.
- [ ] ⬜ **Task 2.3**: Gather gap profiles from a HUMAN-PACED project, not this
  one. The calibration session above cannot answer the question it is most
  needed for.

### Phase 3: Decide, on measured inputs

- [ ] ⬜ **Task 3.1**: Implement the inequality as a supervisor-side decision
  function, `P` and `G` estimated from observed behaviour.
- [ ] ⬜ **Task 3.2**: Dry-run it over recorded transcripts and report what it
  WOULD have spent versus what the session actually spent. Ship nothing
  that does not win on replay.
- [ ] ⬜ **Task 3.3**: Advisory on edits to prefix-resident files, quoting the
  live prefix size, and naming the cheap window — just after a compaction,
  when the prefix is at its smallest.

## Success Criteria

- [ ] Hit ratio reconciles with `/usage` for the same session.
- [ ] A gap histogram exists for at least one human-paced project.
- [ ] The decision function is validated by REPLAY against real transcripts,
  not by argument.
- [ ] Every advisory rule traces to a Phase 2 observation, not to a doc.
- [ ] Full QA green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00452-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Originated from an owner question about cache efficiency. First analysis
  over-generalised from this repository's cron-driven session; the correction —
  that the gap profile is project-specific and this project is the atypical
  end — is what the plan is built around.
