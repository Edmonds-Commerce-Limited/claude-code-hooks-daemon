# Plan 00398: critical compaction blocked by the idle gate

**Status**: In Progress
**Created**: 2026-09-13
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

The supervisor's whole purpose is that a session never runs out of context
unattended. It can currently fail at exactly that, in the band where failing
matters most: **a CRITICAL context does not compact while anything sits in the
input box.**

Graduated from [Plan 00397](../Completed/00397-niggles-ledger-eight/PLAN.md) N3, which
holds the full evidence. Graduated rather than fixed there because the fix is a
design call with a real trade-off against the reason the gate exists, not a
one-line correction.

## The mechanism, read out of the code

`.claude/ccy/claude-supervise.py:3962`, `_evaluate_monitor`, in evaluation
order:

```python
if not reading.red:               -> NOOP "not red (tier=…)"
if foreground_ambiguous:          -> NOOP
if not idle:                      -> NOOP  _REASON_BUSY_COMPOSING   # EVERY band
urgent = reading.compact_urgent or reading.critical
if not urgent and not work_idle:  -> NOOP                           # lower band only
```

`idle` is False on "a human keystroke / non-empty input box" (line 3910). It is
checked BEFORE the urgent/critical split, so it suppresses every band.

**The docstring assists the misreading and should be fixed whatever else is.**
Line 3898 says `work_idle` "only gates the LOWER red band: an elevated-band or
critical reading compacts regardless of `work_idle`". Every word is true of
`work_idle`, and the sentence reads as "critical always compacts" — while the
absolute `idle` gate above it goes unmentioned.

## CORRECTION 3 — "the supervisor can hold its own gate shut" is FALSE, and it voids option 3

An earlier revision of this plan claimed the supervisor blocks its own
compaction by leaving `/goal` text unsubmitted in the box. **That is wrong**,
and it was the entire premise of option 3 — the option the owner ruled a "no
brainer". Establishing it before building is what caught it.

Both halves of the gate derive from HUMAN keystrokes ONLY:

```text
can_inject = facts.idle and facts.input_line_empty          (4611)
  facts.idle            = _is_idle(activity, …)             (6348)
  facts.input_line_empty= activity.line.is_empty            (6382)
  worker ANDs            line_recognizer.is_empty           (5743)

activity.record(forwarded)  <- called in ONE place: the stdin read loop (6195),
                               on bytes the HUMAN typed and that are forwarded
                               to the child. The worker's recognizer is fed the
                               SAME bytes via raw_tap (6200).
```

The supervisor's own injections are written to `master_fd` by a different path
and feed NEITHER tracker. So supervisor-authored text in the box does not make
`input_line_empty` False, cannot trip `_REASON_BUSY_COMPOSING`, and **never
blocks a compaction**.

**Where the false evidence came from**: the `own line may still be unsubmitted`
and `goal clear pending but own line still in the input box` log lines are real,
but they belong to the GOAL-CLEAR and RESUBMIT paths, which track supervisor
text separately via `machine.own_line_pending()`. They were read as evidence
about the COMPACT path. Two different gates, conflated.

**Consequence.** Option 3 targets a case that cannot occur, so it fixes nothing
and must not be built. All 277 red-blocked and 4 urgent-blocked ticks were
HUMAN-caused — text in the box, or a keystroke inside the idle floor. The real
choice is therefore between options 1, 2 and 4, every one of which trades
against the human's unsent text. That is precisely Plan 00168's H2, recorded as
BY DESIGN, so revisiting it needs a fresh ruling made on accurate premises.

## Why the gate exists — the trade-off any fix must pay

The gate is not arbitrary. Injecting into a TUI that has half-typed human text
in it either loses the injection or corrupts what the human was writing. The
same reasoning is documented at line 3908 for the resume path. So "just drop the
`idle` check for critical" trades a guaranteed-safe behaviour for a
context-safety win, and the cost lands on the human's unsent keystrokes.

## PRIOR ART — Plan 00168 already classified this, and that must not be re-discovered

`tests/unit/supervise/test_compaction_gap_repro.py` reproduces this exact
report ("an agent reached COMPACT NOW but never got a /compact") and pins the
behaviour as **H2 … BY DESIGN — never corrupt their input**, with a passing
test `TestH2InputBoxGuardBlocksEvenCritical`. The same file proves the
neighbouring theory false: critical DOES bypass `work_idle` while streaming.

So this plan is not reporting an unknown defect. It is **revisiting a recorded
design decision with the owner's authority**, because the symptom recurred and
the owner has now ruled. Any implementation must update that test rather than
work around it — it encodes the old decision deliberately.

## CORRECTION — the diagnosability claim that graduated with this plan was wrong

Plan 00397 N3 stated that `session busy (composing)` carries no band, so a tick
blocked at 8% could not be told from one blocked at CRITICAL. **That is false.**
Plan 00168 Phase 1 added `_noop_band_suffix` (line 4697) and the log reads:

```text
noop: session busy (composing) [red]
```

The measurement N3 called impossible is therefore available, and it is the real
number this plan rests on:

```text
277  noop: session busy (composing) [red]
  4  noop: session busy (composing) [urgent]      (critical folds into urgent)
174  successful compact injections, for comparison
```

**Task 1.2 survives but narrows.** The general NOOP path already carries the
band; it is specifically the INPUT-BOX DEFERRAL line that does not —
`injection deferred: input box not empty (session busy (composing))`, line 4685,
which omits the suffix the sibling path at 4697 adds.

## Goals

- A session at CRITICAL context compacts, or the reason it did not is visible at
  the time rather than reconstructable only from source.
- The documented promise about critical acting promptly matches what the code
  does — whichever of the two moves.

## Non-Goals

- Re-solving the LOWER red band. Deferring that one while the child streams is
  deliberate (Plan 00152) and is not in question here.
- The `work_idle` gate. It behaves as documented.
- Typed-command recognition. That is
  [Plan 00399](../00399-supervisor-does-not-see-tab-completed-slash-commands/PLAN.md).

## Tasks

### Phase 1: Owner decision

- [ ] 🔄 **Task 1.1**: RULING RECEIVED BUT VOIDED BY CORRECTION 3 — a fresh one
  is needed. The owner ruled verbatim: "3 is a no brainer / 2 flushing the box
  via hitting return is probably better than hitting escape".

  **Option 3 cannot be built.** It was described as bypassing the gate when the
  box holds only supervisor-authored text — but supervisor text never trips the
  gate at all, so there is nothing to bypass. The ruling was sound given the
  description; the description was wrong. Recorded rather than quietly
  re-scoped, because the owner decided on a premise this plan supplied.

  **What survives**: every blocked tick is HUMAN text or a recent human
  keystroke, so options 1, 2 and 4 are the live set and each one costs the
  human's unsent input. Task 1.3's objection to Enter-flush stands and now
  matters more, because option 2 is no longer the follow-on — it is a candidate
  for the primary.

  The original options, kept for the record:

  1. **CRITICAL bypasses `idle`.** Compacts regardless. Simplest, matches the
     docstring's existing promise — and can discard or corrupt whatever the
     human had half-typed.
  2. **CRITICAL flushes first.** Reuse the existing `[esc]`/resubmit machinery
     to clear the box, then compact. Preserves the no-inject-into-a-busy-TUI
     rule, at the cost of more moving parts on the most safety-critical path.
  3. **Distinguish WHOSE text is in the box.** The supervisor already knows
     when the unsubmitted line is its OWN (`own line may still be unsubmitted`).
     Bypassing `idle` when the box holds only supervisor-authored text is
     strictly safe — it destroys nothing a human typed. Narrower than 1, and
     does not fix a human who wandered off mid-sentence at CRITICAL.
  4. **Report only.** Leave the gate, make the suppression loud.

- [ ] ⬜ **Task 1.2**: NARROWED by the correction above. The general NOOP path
  already carries the band. Give the INPUT-BOX DEFERRAL line (4685) the same
  `_noop_band_suffix` its sibling at 4697 has, so the two log shapes agree and
  neither can hide a suppressed CRITICAL.

- [ ] ⬜ **Task 1.3**: RULING NEEDED — Enter-flush vs Esc-flush for option 2,
  raised AFTER the owner ruled and therefore still open.

  **The objection.** Enter does not clear the box, it SUBMITS. At CRITICAL that
  means a fragment is sent to the model, a turn starts, context GROWS, and
  `work_idle` goes False — so compaction is delayed by exactly the turn the
  fragment bought. Enter makes the problem worse at the only moment it is
  urgent. Esc clears, leaving the very next tick free to compact.

  **Why the owner's instinct is still right.** Esc destroys what the human
  typed, and nothing records it.

  **Proposed resolution, not yet ruled**: capture the box contents into the
  decision log (or a recoverable scratch file), THEN Esc. The text survives, no
  turn is spent, and compaction happens on the next tick. This needs its own
  decision because it adds a write of human-authored text to a log.

  Note this is orthogonal to Task 1.1: option 3 covers the supervisor's OWN
  text and needs no flush at all, so it ships without waiting on this.

## Success Criteria

- [ ] The behaviour of a CRITICAL reading against a non-empty input box is
  decided, implemented, and covered by a test that fails against today's code.
- [ ] No decision-log line can hide a suppressed CRITICAL compaction: the
  reason carries tier and percentage.
- [ ] The `_evaluate_monitor` docstring states the `idle` gate's scope, so the
  next reader is not told that critical compacts unconditionally.
- [ ] Full QA passes and CI is green.

## Delivery & Milestones

- Graduated from Plan 00397 N3. The owner reported sessions in other projects
  climbing to "COMPACT NOW" without compacting; that observation is what
  overturned an earlier, narrower conclusion that auto-compaction was healthy.
