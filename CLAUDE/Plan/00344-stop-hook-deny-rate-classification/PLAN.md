# Plan 00344: stop hook deny rate classification

**Status**: Not Started
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Single agent

## Overview

`AutoContinueStopHandler` DENIES most stops, on the principle that an agent
stopping without a reason should keep working. Nobody has ever checked what
that buys. A DENY that produces real work is the feature doing its job; a DENY
that produces one more paragraph and another stop is a wasted model turn, and
the two are indistinguishable from the outside.

Plan 00337 Task 5.0 shipped the instrumentation that can tell them apart.
`untracked/stop-events.jsonl` now records `session_id` and `transcript_bytes`
per stop. The transcript is append-only, so its size is monotonic within a
session: two consecutive records sharing a size are one stop logged twice, a
small growth is a text-only turn that stopped again, a large growth is real
work between the two stops.

**This plan exists because the measurement needs calendar time, not effort.**
It was split out of Plan 00337 rather than left inside it: leaving 00337 open
kept it on the goal ledger, so every stop was challenged on behalf of work that
cannot proceed for weeks — precisely the wasted-tick cost 00337 was filed to
remove. Splitting mirrors what Plan 00341 did when it reached the commit-gate
flip and filed Plan 00343 instead of folding it in.

## Evidence

Measured at the end of a ~2.5-hour session with three full QA runs and four
shipped commits:

```
instrumented rows: 49
  acceptance/integration probes (literal ids): 48
  REAL sessions (uuid ids): 1
```

Two facts follow, and both shape this plan:

- **A real stop event is rare.** That session was re-entered dozens of times by
  task notifications and cron ticks; none of those is a Stop hook event. The
  hook fired ONCE. Rows accrue roughly one per genuine stop, so the dataset
  needs many sessions, not one long one.
- **The file is 48:1 test fixtures.** The stop-hook acceptance tests drive the
  real wrapper against the real daemon, so six synthetic rows land per full QA
  run. Their session ids are fixed literals (`phase9-block-probe`,
  `socket-stdin-stop-block-probe`); real ones are UUIDs. Filtering on that
  shape is mandatory, not optional — an unfiltered read concludes the stop hook
  does nothing but deny 0-byte transcripts.

**The pre-Task-5.0 backlog cannot be used.** Those ~9,000 rows carry only
`timestamp`, `decision`, `reason_prefix`, `stop_hook_active` — no `session_id`,
so a row cannot be attributed to a session at all. Plan 00337's "50 of ~140
stops followed by another within TEN SECONDS" figure therefore cannot
distinguish one session re-firing from two concurrent sessions, and must be
treated as unproven rather than as evidence of double-logging.

## Goals

- Classify each DENY as "productive continue" or "wasted turn", from recorded
  evidence rather than impression.
- If the data shows waste, propose tuning that cites the classification.
- If it shows the handler working correctly, record that and close. A
  measurement that exonerates the code is a real result.

## Non-Goals

- Changing `AutoContinueStopHandler`'s branches before the measurement exists.
  Tuning a hot path on a hunch is what this plan is designed to avoid.
- Re-opening `_HUMAN_BLOCKED_PATTERNS`. Plan 00337 Task 3.4 closed that set to
  extension and Plan 00342 narrowed what it matches; neither is in scope here.
- Analysing the pre-Task-5.0 backlog. It cannot be attributed to sessions —
  see Evidence.
- Suppressing the acceptance probes at source. They are correct behaviour: an
  acceptance test of the live daemon SHOULD produce live telemetry.

## Tasks

### Phase 1: Wait for a usable sample

- [ ] ⬜ **Task 1.1**: Define "usable" before looking, so the threshold is not
  chosen to fit whatever the data happens to show. A first cut: at least 50
  UUID-session rows spanning at least 10 distinct sessions, so no single
  session's habits dominate.

- [ ] ⬜ **Task 1.2**: Re-run the count periodically and do nothing else until
  Task 1.1's bar is met. The classifier must filter to UUID session ids, and it
  must NOT group by a literal session id — probe ids are REUSED across runs,
  and an early draft read five separate QA runs sharing `phase9-block-probe` as
  24 double-logged stops.

### Phase 2: Classify

- [ ] ⬜ **Task 2.1**: Bucket every DENY by the transcript-size delta to the
  next stop in the SAME session: zero (double-logged), small (text-only turn),
  large (real work). Report the distribution, not an average — the question is
  what fraction is waste, and a mean hides it.

- [ ] ⬜ **Task 2.2**: Attribute each bucket to the DENY branch that produced
  it (`reason_prefix` is already recorded). "The default explain-or-continue
  branch wastes turns" and "the QA-failure branch wastes turns" would call for
  completely different fixes, so an undifferentiated rate is not actionable.

- [ ] ⬜ **Task 2.3**: Confirm or refute the double-logging hypothesis. Plan
  00337 suspected the hook logs one stop twice; with `session_id` and
  `transcript_bytes` this is now directly checkable rather than inferred from
  timestamps.

### Phase 3: Act on the result, either way

- [ ] ⬜ **Task 3.1**: If waste is material, propose tuning that cites the
  distribution and the branch attribution. Any change here alters how every
  session behaves, so the bar is evidence, not argument.

- [ ] ⬜ **Task 3.2**: If the handler is working correctly, record that
  plainly and close the plan. This is the expected outcome often enough that it
  needs saying up front — otherwise the measurement acquires a motive to find a
  problem.

## Success Criteria

- [ ] The sample size and session spread are stated before the classification
  is run, not after.
- [ ] Every DENY in the sample is bucketed and attributed to a branch.
- [ ] The outcome is a tuning proposal citing the distribution, or a recorded
  finding that the handler behaves correctly. Both are acceptable; silence is
  not.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00344-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: Plan 00337 Phase 5. Task 5.0 shipped the instrumentation; Tasks 5.1
  and 5.3 are the measurement, which needs data this plan waits for.
- Dedupe scout read all 44 live plans. Plan 00161 (idle housekeeping) is the
  nearest neighbour and is complementary rather than overlapping: it detects
  repeated no-op ticks in order to DO something with idle time, while this plan
  measures whether those stops were wasted at all. It may consume this plan's
  result later.
