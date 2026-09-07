# Plan 00337: stop hook, human-input marker and failsafe cron — pragmatic retune

**Status**: In Progress
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The session of 2026-09-07 is a complete, self-contained reproduction of this
subsystem's central weakness, and the evidence is on disk rather than
remembered. Four consecutive hourly failsafe-cron ticks each consumed a full
model turn and each did nothing. The suppression designed to prevent exactly
that never armed — not because it is broken, but because arming it requires the
agent to utter one of four hardcoded phrases that **no agent-facing document
ever names**. The moment the agent read the handler source and said "blocked
only on human input", the marker armed on the next stop.

That is not a bug to be patched, it is a mechanism choice that does not
converge. The Stop message is doing two jobs at once: prose addressed to a
human, and a control signal for a daemon state machine. Prose is expected to
vary; control signals must be exact. Reconciling the two by regex means every
natural rephrasing is a silent miss, and the history shows the cost is paid
repeatedly — Plan 00298 introduced the pattern set, a dogfood miss led Plan
00314 to widen it (`923fd583`), a different phrasing missed again today, and
Plan 00314 still has further widening queued.

This plan proposes to stop widening and change the mechanism: tell the agent
the contract exists, let it declare the state explicitly, and add a backoff
that works even when the agent declares nothing at all. The project already has
the idiom — `ASKING BECAUSE:` is an explicit declaration the agent is told
about in `CLAUDE.md` — so this is applying an existing pattern, not inventing
one.

## Evidence

All from the 2026-09-07 session; `untracked/stop-events.jsonl` is the record.

- **Four no-op ticks.** Stop events at `00:59:27`, `01:32:53`, `02:32:53` and
  the tick answered at `03:34`, all `decision: allow`, all with
  `marker_written` **absent** — meaning `_maybe_record_human_blocked_marker`
  returned `None`, i.e. no pattern matched. `human-input-blockage-marker.json`
  was not on disk.
- **It armed the instant the wording matched.** The `03:34:41` record carries
  `"marker_written": true`, after a stop reading "STOPPING BECAUSE: blocked
  only on human input." The mechanism works; only arming is fragile.
- **The contract was documented in the wrong direction.** The `CLAUDE.md`
  rules-table row for `R-FAILSAFE-CRON-SUPPRESSED` said how to CLEAR the
  marker, never how to ARM it; the phrases themselves lived in
  `_HUMAN_BLOCKED_PATTERNS` and in the human reference tree. Task 2.3 later
  sharpened this — one phrase WAS resident, just unlabelled. Fixed in Phase 2.
- **Widening does not converge.** `cd02e32d` (00298) introduced the patterns;
  `923fd583` (00314) widened pattern 4 after a 2026-09-01/02 dogfood miss;
  today's miss used wording none of the four cover. Two misses, one widening.
- **Stop-hook volume.** ~140 logical stops on 2026-09-07, mostly DENY.
  Superseded in detail by Phase 5, which found the raw row count over-reports
  (one stop is logged twice, ~79 ms apart) and that the
  `R-STOP-AFTER-TOOL-ERROR` "cadence" is not one.

## Goals

- An agent can learn how to arm cron suppression from its own resident
  guidance, without reading daemon source.
- Arming is an explicit declaration, not an inference from prose.
- The cron stops burning turns on a session that is producing nothing, even
  when the agent declares nothing — without losing its ability to recover a
  session that was genuinely interrupted.
- The stop-hook DENY rate is measured, so any tuning is driven by data.
- Plan 00314's shipped-but-unrecorded state is corrected.

## Non-Goals

- Removing the existing `_HUMAN_BLOCKED_PATTERNS`. They must stay as a
  compatibility fallback so no currently-working phrasing regresses; the change
  is to stop _investing_ in them, not to delete them.
- Weakening the "blocked ONLY on human input" semantics. The 00298 reasoning —
  that a transient mention must not arm suppression — is correct and stands.
- Redesigning the failsafe cron's purpose. It exists to recover externally
  interrupted work; that stays.
- Touching the ccy supervisor's own injection logic (Plan 00317/00328
  territory).

## Tasks

### Phase 1: Correct the record on Plan 00314

- [x] ✅ **Task 1.1**: Verified against the current source, not the commit
  message, then updated. (Journal 14:20.)
- [x] ✅ **Task 1.2**: **Closed and archived in `9def2583`**, with its evidence
  limit stated: only the ARMING half is live-observed. (Journal 14:20.)
- [x] ✅ **Task 1.3**: **Systemic — filed as Plan 00341.** 2 of 22, and the
  header and the boxes rot independently. (Journal 14:40.)

### Phase 2: Make the contract visible (cheapest fix, highest ratio)

- [x] ✅ **Task 2.1**: **Shipped** in `auto_continue_stop.get_claude_md()`: the
  shapes, the zero-token saving, the clearing rule, the expiry, and the
  ONLY-blocking restriction. It had to be that section — the suppressor's own
  guidance already names the shape and is compressed to a rules-table row on
  the way into `CLAUDE.md`, which is what drops the arming half. (Journal
  15:45.)

- [x] ✅ **Task 2.2**: **Pinned, derived not restated.** The phrasings live in
  `_HUMAN_BLOCKED_EXAMPLES` and the guidance renders FROM that tuple; tests
  assert every example matches `_HUMAN_BLOCKED_PATTERNS`, that the guidance
  shows each one with its consequence and clearing rule, and — the Plan 00237
  lesson — that they reach the RENDERED `CLAUDE.md`.

- [x] ✅ **Task 2.3**: **The claim does not hold, so the phase is re-scoped.**
  One arming phrase is ALREADY in the resident block — `get_claude_md()` says
  "Use `STOPPING BECAUSE: need user input`", which `_HUMAN_BLOCKED_PATTERNS[2]`
  matches — and four stops still did not reach for it, because it is presented
  as how to ASK A QUESTION and the agent was waiting, not asking.

  So Phase 2 is not "add vocabulary", it is **state the consequence**: phrase
  your stop this way and the failsafe cron stops ticking. Tasks 2.1 and 2.2
  stand with that framing, and it strengthens Phase 3 rather than substituting
  for it — a phrase whose effect is invisible gets used by luck. (Journal
  14:55.)

### Phase 3: Replace inference with declaration

- [x] ✅ **Task 3.1**: **`STOPPING BECAUSE: [awaiting-human] …`**, anchored
  after the prefix where prose does not produce it by accident. A structured
  hook field is not ours to choose (the Stop input schema is Claude Code's); a
  dedicated tool is more precise but adds permanent tool-inventory surface
  this project is shrinking, and a tool call is not a stop, so the declaration
  would split across two acts. (Journal 17:25.)

- [x] ✅ **Task 3.2**: **Shipped.** `_declares_human_blocked()` checks the token
  first and falls back to the prose patterns, so both paths arm the same
  marker. Case-insensitive, matching the patterns' own handling. Six unit
  tests, including the one that carries the plan's whole point: wording no
  prose pattern reaches ("nothing further I can do until a person weighs in")
  arms nothing on its own and arms with the token — with a guard asserting the
  fixture stays unmatched, so the test cannot quietly stop proving anything.

  Deviated from "only the token is advertised": the guidance advertises BOTH,
  with the older phrasings labelled recognised-but-frozen. Dropping them from
  the docs while the fallback still accepts them would create the very
  code/docs disagreement this plan exists because of. **Live dogfood is still
  outstanding** — unit tests prove the token arms; no real stop has used it.

  **Dogfood bug found and fixed inside this phase.** The first draft matched
  the token anywhere in the stop text, so a stop message REPORTING the feature
  armed cron suppression on a session that was not blocked — the Plan 00228
  class, failing silently (ticks just stop arriving). `AutoContinueStopHandler`
  is outside `test_handlers_do_not_match_prose.py` by construction, its fixture
  being a Bash tool call. Reproduced RED, then anchored to the declaration
  position, which is where the guidance already says to put it. (Journal
  19:10.)

- [x] ✅ **Task 3.3**: **Cited, transfers only in part.** `ASKING BECAUSE:` is a
  **gate** (the agent wants to ask, so the declaration can be priced by
  denying the call); this token is a **state marker**, and a stop cannot be
  denied for failing to declare a state it may not be in — so it is
  permanently opt-in. Consequence: **Phase 4 is the load-bearing fix and Phase
  3 the optimisation on top**; the phase numbers are not a priority order.
  (Journal 16:00.)

- [x] ✅ **Task 3.4**: **Marked CLOSED TO EXTENSION** at the definition itself,
  where the next author will be standing when tempted — the comment says add
  nothing, and states why widening does not converge (00298 introduced it,
  00314 widened it after a miss, a third phrasing missed anyway).

  Reconciled with Plan 00314: there is no remaining widening task. Its archived
  PLAN.md already records that nothing further is queued and that this task
  supersedes the idea.

### Phase 4: Backoff that needs no cooperation from the agent

- [ ] ⬜ **Task 4.1**: The strongest fix is the one that does not depend on the
  agent saying anything. **Ask the goal ledger, not the agent.** Owner steer:
  "wondering if we should keep the cron running once we hit a human blocker or
  work is completely done — the completely done bit is tricky because agents
  stop randomly all the time, which is why we have so many stop systems." That
  splits the two cases, and they do NOT get the same answer:

  - **Blocked on human** is a real terminal-until-input state, and a user
    message already clears it. Suppressing is safe and is today's behaviour.
  - **"Work complete" must never suppress on the agent's say-so.** A false
    "done" is the single most common way an agent stops wrongly, and the cron
    is the net that catches it. Trusting a self-reported "done" would disable
    the safety net exactly when it is needed.

  The ledger resolves this, because it already answers "is work owed?" from
  daemon-side state rather than self-report. **Full truth table, algorithm and
  prerequisites: [DESIGN-cadence.md](DESIGN-cadence.md).** This supersedes the
  original framing, which keyed backoff on "consecutive unproductive ticks" —
  a heuristic, where the ledger is a state signal.

- [ ] ⬜ **Task 4.1b**: Respect the ledger's limit — **wider than this task
  originally said.** `live_plan_numbers` counts only plans already in the
  ledger that also resolve to `_STATE_IN_PROGRESS`, so a plan that never got a
  `/goal`, or one whose header still reads `Not Started`, is not "owed". Both
  biases point at "nothing owed", the direction that backs the cron off — so
  a plan being actively worked behind a stale header would lose its safety
  net. A real dependency on **Plan 00341**. (Journal 16:30, DESIGN-cadence.md.)

- [ ] ⬜ **Task 4.2**: Back off exponentially with a **cap** (doubling to a
  4-hour ceiling), never to silence — the cron exists to recover a session
  interrupted by a rate limit, and a later tick genuinely helps once the limit
  lifts. Algorithm settled in [DESIGN-cadence.md](DESIGN-cadence.md).

- [ ] ⬜ **Task 4.5** (found while designing): the suppressor **cannot reach
  the ledger yet** — `track_plans_in_project` is injected only into
  planning-tagged handlers and this one is not tagged PLANNING. Decide before
  Task 4.1; **Plan 00311 Task 1.1** hits the identical obstacle in
  `dispatch_declaration`, which argues for one shared decision rather than two
  local workarounds. (DESIGN-cadence.md.)

- [ ] ⬜ **Task 4.3**: Any genuine user message resets the cadence to hourly,
  matching how a user message already clears the marker.

- [x] ✅ **Task 4.4**: **Folds into `failsafe_cron_blockage_suppressor`**, on
  position rather than preference: a backoff must see every delivered tick,
  see every real prompt (to reset), hold a counter and be able to drop a tick,
  and that handler already does all four with an injectable clock and
  fail-open behaviour throughout. `recovery_cron_advisor` owns the cron's
  LIFECYCLE and never sees a delivered tick as a prompt, so it cannot count
  them.

  What does NOT fold: the counter cannot live in the existing marker, which is
  cleared on any real prompt and is absent in exactly the truth table's bottom
  row. It needs its own persistence and lifetime. (Journal 16:15.)

### Phase 5: Measure the stop-hook DENY rate before tuning it

- [ ] ⬜ **Task 5.0** (added after measuring): `stop-events.jsonl` records
  nothing that joins a row to the turn it came from, so Task 5.1 is blocked on
  instrumentation rather than effort.

  Design settled: add `session_id` **and `transcript_bytes`** — the transcript
  is append-only, so its size is monotonic and O(1) via `stat`, and two
  records with the same size are one stop logged twice. That turns Task 5.1
  into arithmetic over the ledger. Details in
  [DESIGN-cadence.md](DESIGN-cadence.md).

- [ ] ⬜ **Task 5.1**: Classify each DENY as "productive continue" or "wasted
  turn". **Gated on Task 5.0.** The ledger alone already shows 50 of today's
  ~140 logical stops are followed by another within TEN SECONDS — too fast for
  work — but cannot say whether that is the hook re-firing (a defect) or a
  text-only turn stopping again (agent behaviour). `transcript_bytes` settles
  it. Also corrects this plan's Evidence: the "28 DENY" figure was inflated by
  1291 double-logged pairs. (Journal 15:30.)

- [x] ✅ **Task 5.2**: **Not a cadence — the code is exonerated.** Measured over
  all 27 of today's `R-STOP-AFTER-TOOL-ERROR` events, the gaps run 482-3557 s
  with a coefficient of variation of 0.74; a timer would give ~0. The eye
  picked out the cluster around 500-900 s and missed the 3557 s ones. The
  events track how often the agent trips a PreToolUse block and then ends its
  turn, which bunches naturally in a long session.

- [ ] ⬜ **Task 5.3**: Only if the data shows waste, propose tuning. If it shows
  the handler working correctly, record that and close the phase — a
  measurement that exonerates the code is a real result.

## Success Criteria

- [ ] An agent reading only its resident `CLAUDE.md` can arm cron suppression
  correctly on the first attempt.
- [ ] An explicit declaration arms the marker; the prose patterns still work but
  are documented as frozen.
- [ ] A session producing nothing across consecutive ticks costs asymptotically
  less than one model turn per hour, while a session interrupted by a rate
  limit still recovers.
- [ ] The stop-hook DENY rate is classified with evidence, and any tuning cites
  that classification.
- [x] Plan 00314 reflects what actually shipped and is archived (`9def2583`).
- [ ] Full QA green (25/25), daemon restarted and the behaviour verified live —
  this subsystem is only ever proven by dogfooding it.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00337-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: the 2026-09-07 session, which reproduced the failure end to end and
  then accidentally demonstrated the fix. Raw evidence in
  `untracked/stop-events.jsonl`.
- Prior art: Plan 00298 (`cd02e32d`, introduced the mechanism, Completed), Plan
  00314 (`923fd583`, widened it once, shipped but unrecorded).
- Dedupe scout checked 45 live plans: no live plan proposes replacing prose
  inference with explicit declaration. Plan 00314 is a subset (fixing defects
  within the current mechanism); Plan 00108 (`ASKING BECAUSE:`) and Plan 00228
  (limits of prose-matching) are adjacent precedents this plan builds on.
