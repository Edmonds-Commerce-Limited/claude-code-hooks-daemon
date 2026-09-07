# Plan 00337: stop hook, human-input marker and failsafe cron — pragmatic retune

**Status**: Not Started
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
- **The agent could only comply by reading daemon source.** The four phrases
  live in `_HUMAN_BLOCKED_PATTERNS` (`handlers/stop/auto_continue_stop.py`).
- **The contract is documented in the wrong direction.** The generated
  `CLAUDE.md` block documents `R-FAILSAFE-CRON-SUPPRESSED` — that the marker
  exists and how to CLEAR it ("Send a real message") — but never how to ARM it.
  `docs/guides/HANDLER_REFERENCE.md` (3283, 3402) does name the phrases, but
  that is the human reference tree, not the agent's resident guidance. The
  handler's own `get_claude_md()` mentions human input, cron and suppression
  **zero** times.
- **Widening does not converge.** `cd02e32d` (00298) introduced the patterns;
  `923fd583` (00314) widened pattern 4 to add `human` after a 2026-09-01/02
  dogfood miss; today's miss used wording none of the four cover. Two misses,
  one widening, a third round still planned.
- **Stop-hook volume is worth measuring.** 34 stop events on 2026-09-07, of
  which 28 were `deny` inside a ~34-minute window, dominated by
  `R-STOP-NO-REASON` with `R-STOP-AFTER-TOOL-ERROR` recurring at roughly
  ten-minute intervals. Each DENY forces an extra model turn. Whether that is
  the auto-continue feature working as designed or over-firing is currently
  unknown, and worth a measurement before anyone tunes it.

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

- [ ] ⬜ **Task 1.1**: Plan 00314 reads `Status: Not Started` with all four
  tasks `⬜`, but Tasks 1.1-1.3 shipped in `923fd583` (marker-write
  observability, `human` pattern widening, 235 lines of tests). Its own JOURNAL
  entry from that commit exists — the executor journalled but never flipped the
  boxes. Verify against the code, then update.
- [ ] ⬜ **Task 1.2**: Task 1.4 was "live dogfood — arm the marker with a
  matching stop". Today's `marker_written: true` at `03:34:41` satisfies it.
  Record that evidence in 00314's journal and close the plan out with the
  atomic archival (git mv + README row + statistics in one commit).
- [ ] ⬜ **Task 1.3**: A plan whose work has shipped but reads "Not Started"
  invites a second agent to redo it. Check whether this is systemic —
  cross-reference live plan task boxes against commits naming those plans — and
  if it is, that is a finding for its own plan, not scope creep here.

### Phase 2: Make the contract visible (cheapest fix, highest ratio)

- [ ] ⬜ **Task 2.1**: Add the arming vocabulary to the stop handler's
  `get_claude_md()` so it reaches the generated `CLAUDE.md` block, next to the
  existing "Stop Explanation Required" guidance the agent already follows.
  State both directions: how to arm, and that a real user message clears it.
- [ ] ⬜ **Task 2.2**: Pin it with the existing `get_claude_md()` coverage gate
  (the integration test the release process already runs), so the guidance
  cannot silently drift from `_HUMAN_BLOCKED_PATTERNS`. Ideally derive the
  documented phrases FROM the pattern set rather than restating them, so they
  cannot disagree.
- [ ] ⬜ **Task 2.3**: Confirm the claim this phase rests on: that today's
  four-tick failure would not have occurred had the vocabulary been in the
  resident guidance. If that cannot be argued cleanly, this phase is weaker
  than it looks and should be re-scoped.

### Phase 3: Replace inference with declaration

- [ ] ⬜ **Task 3.1**: Design the explicit token. A bracketed marker composing
  with the prefix the agent already emits — e.g.
  `STOPPING BECAUSE: [awaiting-human] ...` — is matched exactly, needs no NLP,
  and reads acceptably to a human. Compare against alternatives (a dedicated
  tool, a structured hook field) and record why the chosen one wins.
- [ ] ⬜ **Task 3.2**: Implement with the existing regexes retained as a
  fallback. Both paths arm the same marker; only the token is advertised.
- [ ] ⬜ **Task 3.3**: Follow the in-project precedent rather than inventing a
  convention: `ASKING BECAUSE:` (`R-ASK-USER-QUESTION-UNJUSTIFIED`) is already
  an explicit agent-facing declaration, and Plan 00228 already documented the
  limits of inference-from-prose. Cite both.
- [ ] ⬜ **Task 3.4**: Mark `_HUMAN_BLOCKED_PATTERNS` closed to extension in a
  comment — new phrasings are handled by the token, not by another round of
  widening — and reconcile with Plan 00314's remaining widening task.

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
  daemon-side state rather than self-report: `_goal_ledger_challenge()` calls
  `GoalLedger.live_plan_numbers(plan_dir)`, which reads plan **Status on
  disk** — including goals the upstream single-slot `/goal` has forgotten. So
  the cron should consult the ledger:

  | Goals owed | Declared blocked-on-human | Cron                                                  |
  | ---------- | ------------------------- | ----------------------------------------------------- |
  | yes        | no                        | tick (the net working — agent likely stopped wrongly) |
  | yes        | yes                       | tick, backed off                                      |
  | no         | yes                       | suppress (today's behaviour)                          |
  | no         | no                        | back off hard                                         |

  This supersedes the original framing of this task, which keyed backoff purely
  on "consecutive unproductive ticks". Unproductive-tick counting is a
  heuristic; the ledger is a state signal, and state beats heuristic.

- [ ] ⬜ **Task 4.1b**: Respect the ledger's limit. It tracks **plan** goals, so
  work outside a plan is invisible to it and "no goals owed" is not proof of
  idleness. That is why the bottom row backs off rather than silences, and why
  the ledger must not become the sole authority.

- [ ] ⬜ **Task 4.2**: Back off exponentially with a **cap** (e.g. doubling to
  a 4-hour ceiling), never to silence. The cron exists to recover a session
  interrupted by a rate limit or API error, and in that case a later tick
  genuinely does help once the limit lifts; unbounded backoff would destroy the
  feature's reason to exist.

- [ ] ⬜ **Task 4.3**: Any genuine user message resets the cadence to hourly,
  matching how a user message already clears the marker.

- [ ] ⬜ **Task 4.4**: Decide where this lives. `recovery_cron_advisor` owns the
  cron lifecycle and `failsafe_cron_blockage_suppressor` owns tick-dropping;
  adding a third state-holder needs justifying against folding it into the
  latter.

### Phase 5: Measure the stop-hook DENY rate before tuning it

- [ ] ⬜ **Task 5.1**: 28 DENY events in ~34 minutes is either the auto-continue
  feature working exactly as intended or a handler over-firing. Do not guess —
  correlate the DENY events in `stop-events.jsonl` against the transcript and
  classify each as "productive continue" (work followed) or "wasted turn".
- [ ] ⬜ **Task 5.2**: The `R-STOP-AFTER-TOOL-ERROR` events recurring at roughly
  ten-minute intervals are the more suspicious signal — a regular cadence
  suggests something systematic rather than organic. Identify what produced
  them.
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
- [ ] Plan 00314 reflects what actually shipped and is archived.
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
