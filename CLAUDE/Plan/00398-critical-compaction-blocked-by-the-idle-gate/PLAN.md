# Plan 00398: critical compaction blocked by the idle gate

**Status**: Not Started
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

Graduated from [Plan 00397](../00397-niggles-ledger-eight/PLAN.md) N3, which
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

**The supervisor can hold its own gate shut.** It injects `/goal` text that can
sit unsubmitted, which IS a non-empty input box:

```text
would-resubmit: own line may still be unsubmitted in the input box (/goal) -> pressing [enter]
noop: goal clear pending but own line still in the input box
```

## Why the gate exists — the trade-off any fix must pay

The gate is not arbitrary. Injecting into a TUI that has half-typed human text
in it either loses the injection or corrupts what the human was writing. The
same reasoning is documented at line 3908 for the resume path. So "just drop the
`idle` check for critical" trades a guaranteed-safe behaviour for a
context-safety win, and the cost lands on the human's unsent keystrokes.

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

- [ ] ⬜ **Task 1.1**: RULING NEEDED on how a CRITICAL reading should behave when
  the input box is not empty. Options, with the cost of each stated:

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

- [ ] ⬜ **Task 1.2**: Independent of the ruling — the `not idle` NOOP must carry
  the tier and percentage. Today `session busy (composing)` is
  indistinguishable between a tick blocked at 8% and one blocked at CRITICAL,
  which is why Plan 00397 could measure the gate's frequency (20260 of 25834
  decisions) but NOT how often it blocked a red reading.

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
