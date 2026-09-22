# Plan 00452: prompt cache observability and invalidation protection

**Status**: In Progress
**Created**: 2026-09-22
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Single Agent

## Overview

A session bills input at roughly 0.1x when the cached prefix is reused, and at
a write rate whenever it has to be rebuilt. Whether a project pays mostly reads
or mostly writes is decided by one thing: how its idle gaps compare to its TTL.

Nothing here measures that, and the measurement is free — the transcript
already carries a per-request `usage` object with the cache counters and a TTL
breakdown.

**No project can currently see its own hit ratio, so no project knows whether
it has a problem.** Surfacing the number is most of the value, which is why the
status-line segment ships first and stands alone.

Evidence, measurements and the warming arithmetic:
**[RESEARCH-cache-measurements.md](RESEARCH-cache-measurements.md)**.

## What the measurements settled

Summarised; the numbers and their caveats live in the research document.

- **The status bar must show MAIN, SUB and TOTAL.** Sub-agents have no status
  line of their own, and the main-thread figure hides them entirely — 98.87%
  main against 62.17% on a short sub-agent in the same session.
- **The two sides run different TTLs** (1-hour main, 5-minute sub, measured and
  doc-confirmed), so a single TTL indicator would be wrong for one of them.
- **A dispatch has a floor cost** the sub-agent must amortise, so very short
  sub-agents are cache-expensive.
- **`N` cancels out of the warming decision** but sets the stakes: one
  invalidation costs `W x N`, and `N` moved 130,550 -> 509,560 inside one
  session.
- **A warm ping cannot be made cheaper than `0.1 x N`** — the read is 99.8% of
  it — but in a hook-heavy project it must still be designed to complete in
  ONE request, or Stop handlers double it.
- **The hook-denial question is unresolved and outranks everything else here**
  if it turns out positive.

## Goals

- **A cache segment in the status line — the first deliverable.** Useful on its
  own even if nothing below is ever built.
- A read-only transcript analyser: hit ratio, effective multiplier, TTL mix,
  prefix-size curve, and every request that caused a cache write.
- An **idle-gap histogram** per project against its TTL — the input the
  decision needs, and the thing that says whether warming is worth anything.
- An empirical answer to which operations actually invalidate.
- Only then: a supervisor-side decision function, with `P` and `G` estimated
  from observed behaviour rather than assumed.

## Non-Goals

- **A fixed-interval warming cron.** Not because warming is wrong — for a
  human-paced project it can pay — but because a fixed interval cannot estimate
  `P`, and warming when `P` is low is the one case that strictly loses.
- **Blocking any edit.** This is cost, not safety; the cost is one bounded
  rewrite.
- **Mandating sub-agents for `CLAUDE.md` edits.** Invalidation follows the FILE
  changing, not who changed it, so delegating does not protect the parent's
  prefix. Batching is the lever that idea is reaching for.
- Controlling `cache_control` placement or TTL — Claude Code manages both.

## Tasks

### Phase 1: Surface it — the status line segment

Ships first and stands alone. Everything after this is optional; this is not.

**Task 1.1 is answered, and it collapses most of this plan.** The Status
payload already carries a `prompt_cache` object with `warm`, `ttl`,
`expires_at`, `hit_ratio`, `misses`, `miss_causes` and
`recache_tokens_if_cold`, plus `context_window` and `cost`. Main-thread
figures need NO transcript reading — which deletes the tail-read, the
`mtime_cache` dependency and the entire performance problem that shaped the
original design. See the research document.

- [x] ✅ **Task 1.1**: Establish what the Status event delivers. Done by
  enabling `daemon.payload_capture` (already scoped to `[Status]`) for a few
  renders. `transcript_path` IS present but is not needed for the main thread.
- [ ] ⬜ **Task 1.2**: Render MAIN, SUB and TOTAL with the TTL per side. Main
  reads straight from `prompt_cache`; only SUB needs aggregation.
- [ ] ⬜ **Task 1.4**: Aggregate sub-agent totals at `SubagentStop` into a small
  sidecar rather than scanning the task directory from the status line (127
  files, re-rendered constantly). Same sensor/actuator split as
  `context_sidecar`.
- [ ] ⬜ **Task 1.5**: Tolerate unparseable lines in an agent transcript — most
  files in that directory are not JSONL and a naive slurp exits non-zero.
- [ ] ⬜ **Task 1.6**: Flag an invalidation visually when it happens, keyed on
  `cache_creation_input_tokens > 0` in the newest record. The write IS the
  signal, so this needs no list of suspected causes and cannot be wrong about
  whether an invalidation occurred.
- [ ] ⬜ **Task 1.7**: Put the cold/at-risk classification in ONE shared
  classifier, as Plan 00135 Decision J did for context tiers, so the segment and
  any later supervisor logic cannot drift.

### Phase 2: Measure

- [ ] ⬜ **Task 2.1**: Transcript analyser emitting the metrics above.
- [ ] ⬜ **Task 2.2**: Guard the guard — a fixture transcript with known writes,
  asserting the detector finds them. A detector matching nothing would report a
  perfect score on a broken session.
- [ ] ⬜ **Task 2.3**: Idle-gap histogram from request timestamps, bucketed
  against the session's observed TTL.
- [ ] ⬜ **Task 2.4**: Gather gap profiles from a HUMAN-PACED project. This
  repository's cron-driven session cannot answer the question it is most needed
  for.

### Phase 3: Establish what actually invalidates

- [ ] ⬜ **Task 3.1**: Correlate each cache write with the preceding turn.
  Classify: hook denial, prefix-file edit, MCP change, model/effort switch,
  compaction, unexplained.
- [ ] ⬜ **Task 3.2**: Settle the hook-denial question. Undocumented, and this
  project's deny rules fire constantly. If positive, it outranks the rest of
  this plan and the scope should be re-cut around it.
- [ ] ⬜ **Task 3.3**: Settle whether sub-agents compact, by driving one to its
  ceiling and observing what the coordinator receives.

### Phase 4: Decide, on measured inputs

- [ ] ⬜ **Task 4.1**: Implement the inequality as a supervisor-side decision
  function reading the single sidecar.
- [ ] ⬜ **Task 4.2**: Design the warm ping to complete in ONE request —
  ideally by having Stop-family handlers recognise and stand down for it,
  rather than relying on every project's reply wording.
- [ ] ⬜ **Task 4.3**: Dry-run over recorded transcripts, reporting what it
  WOULD have spent against what the session actually spent. Ship nothing that
  does not win on replay.
- [ ] ⬜ **Task 4.4**: Advisory on edits to prefix-resident files, quoting the
  live prefix size and naming the cheap window — just after a compaction, when
  the prefix is smallest.

## Success Criteria

- [ ] Hit ratio reconciles with `/usage` for the same session.
- [ ] The status segment shows all three values and is correct on a session
  with zero sub-agents as well as one with many.
- [ ] A gap histogram exists for at least one human-paced project.
- [ ] The decision function is validated by REPLAY, not by argument.
- [ ] Every advisory rule traces to a Phase 3 observation, not to a doc.
- [ ] Full QA green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00452-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Originated from an owner question about cache efficiency. First analysis
  over-generalised from this repository's cron-driven session; the correction —
  that the gap profile is project-specific and this project is the atypical
  end — is what the plan is built around.
