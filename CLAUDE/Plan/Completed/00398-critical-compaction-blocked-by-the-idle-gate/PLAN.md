# Plan 00398: critical compaction blocked by the idle gate

**Status**: Complete
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

## THE ACTUAL DEFECT — the box gate is UNBOUNDED, and that is the over-sensitivity

The owner asked whether the gate is "over sensitive". It is, but not where the
earlier revisions of this plan looked. The two blocking causes log differently
and are wildly asymmetric:

```text
noop: session busy (composing)              281  <- keystroke inside the idle floor
injection deferred: input box not empty   20755  <- text SITTING in the box
```

The idle floor is `_DEFAULT_IDLE_FLOOR_SECONDS = 2.0` — two seconds, cleared by
the next 2s poll. It is not the problem and should not be touched.

**The box gate has no bound at all.** 20593 of 20755 deferral ticks (99.2%) fall
inside runs longer than two minutes, across only 32 runs:

```text
17975 ticks  09-03 20:26 -> 09-04 06:26     (~10 hours)
  830 ticks  08-13 17:01 -> 08-13 17:28
  448 ticks  08-13 16:45 -> 08-13 17:00
```

**The 10-hour run ends at URGENT, still blocked** — this is the reported symptom
captured in the log:

```text
2026-09-04T06:26:49  noop: session busy (composing) [urgent]
2026-09-04T06:26:55  noop: session busy (composing) [urgent]
```

**What is NOT established.** Whether the box was genuinely non-empty or the
tracker was STUCK cannot be told from this window: no submission occurred inside
it, and a submission is the only event that would have forced a clear. The run
is overnight, so "the human left text in the box and went to bed" explains it at
least as well. An earlier revision of this plan asserted a stuck tracker; that
claim is withdrawn as unproven.

**This reframes the fix and REMOVES most of the ruling.** The question is no
longer "should CRITICAL override the human's unsent text" (options 1/2/4, all
costly). It is "should a gate meant to cover the seconds a human is mid-sentence
still hold after ten hours". Bounding it keeps the invariant the gate exists for
— never type into a box someone is actively using — while ending the state where
an absent human's abandoned fragment prevents compaction indefinitely.

## LATENT, unproven, recorded so it is not lost

`_LINE_CLEAR_BYTES` is `{CR, LF, Ctrl-U, Ctrl-C}` and `_LINE_BACKSPACE_BYTES` is
`{0x08, 0x7F}`. **Ctrl-W (0x17) and Ctrl-K (0x0B) are in neither**, so they
empty the REAL box while being APPENDED here as literal bytes, leaving the
tracker permanently non-empty until an Enter arrives. The bracketed-paste latch
(line 685) has the same shape: while `_in_paste` is True every byte is appended
INCLUDING Enter, so a missed paste-end would make the buffer unclearable.

Neither is evidenced in this log. Both are cheap to cover with a unit test and
would produce exactly the unbounded runs measured above, so they are worth
testing whether or not they turn out to be the cause.

## RULED — bound the gate on TEXT STABILITY, not on elapsed non-emptiness

Owner ruling, verbatim: "if the text is the same after X seconds then we regards
it as captured text by accident or something / lets say 120 to give it plenty of
safety / if its purely supervisor text, then no need to be soft - just clear it
and force it through / if its human text - if not changed after 120 seconds then
we can submit it then do the compact".

**The primitive is right and is adopted.** "Unchanged for 120s" separates a human
mid-sentence from abandoned text, which "non-empty" cannot. The gate keeps doing
its job for the seconds it was designed for and stops holding for ever.

### Branch 2 (supervisor text) is UNREACHABLE — do not build it

Supervisor-authored text never trips this gate. `activity.record(forwarded)` has
exactly one call site (the stdin read loop, 6195) and feeds only human bytes;
the worker's recognizer is fed the same bytes via `raw_tap`. Injections are
written to `master_fd` by another path and register in neither tracker. This is
the same premise that voided option 3 — recorded again here because the ruling
restated it, so a future reader does not implement a branch that cannot fire.

### Branch 3 (submit human text) — adopted, with its cost recorded

Submitting does not merely empty the box: it starts a TURN. That grows context
and drives `work_idle` False, so the compaction being unblocked is delayed by
exactly that turn — at CRITICAL, the wrong direction. Accepted anyway because
the alternative destroys the human's words, and text unchanged for 120s is
plausibly a complete message whose Enter was forgotten, where submitting is what
the human wanted.

**Open sub-question, not blocking**: at CRITICAL specifically, capture-then-clear
(record the text, Esc, compact immediately) spends no turn and still preserves
the words. Worth revisiting if the submit-path turn cost shows up in practice.

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

- [x] ✅ **Task 1.1**: RULED — bound the gate on TEXT STABILITY (120s unchanged),
  not on elapsed non-emptiness. Recorded above with both caveats: branch 2 is
  unreachable and must not be built, and branch 3 costs a turn.

- [x] ✅ **Task 1.2** DONE — band suffix added to the deferral line; `test_critical_deferral_carries_the_band_suffix` RED then GREEN. The `evaluate()` docstring now states the `idle` gate's unconditional scope. Original scope:: Give the input-box deferral line (4685) the
  `_noop_band_suffix` its sibling at 4697 already has, so the two log shapes
  agree and a suppressed CRITICAL cannot hide in the deferral stream. This is
  what forced the whole investigation to reason from run-lengths rather than
  bands.

### Phase 2: Text-stability tracking

- [x] ✅ **Task 2.1** DONE — `TestHumanInputLineStability` — 6 tests including the continuous-typing-never-abandoned case. Original scope:: A failing test first: a box whose content is UNCHANGED
  across 120s of ticks is reported abandoned, while a box that changes on any
  tick inside the window is NOT. The changing case is the one a naive
  "non-empty for 120s" timer gets wrong, so it must exist before the code.
- [x] ✅ **Task 2.2** DONE — `_last_changed_at` stamped only on a real buffer change; `_DEFAULT_INPUT_LINE_ABANDON_SECONDS = 120.0`. Original scope:: Track content stability on `HumanInputLine` — a
  fingerprint of the buffer plus the monotonic time it last CHANGED. Not a
  timer started when the box first went non-empty: a human typing continuously
  for three minutes must never be judged abandoned.
- [x] ✅ **Task 2.3** DONE — wired to the compact path only; the 2s idle floor untouched. Original scope:: Wire abandonment into the compact path only, leaving the
  2s idle floor untouched. `_DEFAULT_IDLE_FLOOR_SECONDS` is correct and is not
  in scope.

### Phase 3: Acting on an abandoned box

- [x] ✅ **Task 3.1** DONE — `TestAbandonedInputBoxFlush` plus an end-to-end `supervise()` run proving submit-then-compact. Original scope:: A failing test: at red-or-worse with an abandoned box, the
  supervisor submits the pending text and then compacts, in that order.
- [x] ✅ **Task 3.2** DONE — reuses the existing resubmit payload and injection path — no second keystroke path. Original scope:: Implement, reusing the existing resubmit/Enter machinery
  rather than a second keystroke path.
- [x] ✅ **Task 3.3** DONE — `_abandoned_box_handled` one-shot, reset only when the box stops reading abandoned. Original scope:: Pin that the submit happens exactly ONCE per abandoned
  episode. A re-submitting loop against a box the Enter did not clear is the
  failure mode this whole area already has history with (`/compact` stall →
  `[esc]` flush), and it must not be reintroduced.
- [x] ✅ **Task 3.4** DONE — `TestH2InputBoxGuardBlocksEvenCritical` updated WITH a docstring recording that Plan 00168's decision was revisited, plus a contrasting test. Original scope:: Update `TestH2InputBoxGuardBlocksEvenCritical` in
  `tests/unit/supervise/test_compaction_gap_repro.py`. It encodes Plan 00168's
  deliberate decision, so it must be changed with a comment recording that the
  decision was revisited — never quietly deleted.

### Phase 4: The latent clear-byte gaps

- [x] ✅ **Task 4.1** DONE — 7 tests in `TestHumanInputLineClearByteGaps`, 5 initially RED. Original scope:: Failing tests that Ctrl-W (0x17) and Ctrl-K (0x0B) leave
  the tracker permanently non-empty, and that a bracketed-paste start with no
  end swallows a subsequent Enter.
- [x] ✅ **Task 4.2** DONE — Ctrl-W modelled as readline word-delete; Ctrl-K a no-op under this parser's existing cursor-at-end assumption; paste latch bounded at 65536 bytes. Original scope:: Decide each on its merits. Ctrl-W/Ctrl-K do NOT clear the
  whole line in a real shell, so treating them as clear bytes would be wrong;
  the honest fix is to model them (word-delete / kill-to-end) or to bound the
  paste latch. Recorded as a real choice rather than assumed.

## Review

The implementation and test review lives in **[REVIEW.md](REVIEW.md)** — what
was checked against the code rather than taken from the implementation report,
what the tests pin (including the one case where this acts on live human text),
the live dogfooding evidence, and the risks accepted rather than resolved.

## Success Criteria

- [x] The behaviour of a CRITICAL reading against a non-empty input box is
  decided, implemented, and covered by a test that fails against today's code —
  text-stability flush at 120s, `TestHumanInputLineStability` plus
  `test_abandoned_input_flush.py`.
- [x] No decision-log line can hide a suppressed CRITICAL compaction: the
  reason carries tier and percentage —
  `test_critical_deferral_carries_the_band_suffix`.
- [x] The `_evaluate_monitor` docstring states the `idle` gate's scope, so the
  next reader is not told that critical compacts unconditionally.
- [x] Full QA passes and CI is green — 29/29 locally (22,640 tests, coverage
  95.3%); CI green at `a7d0fb7b`, which carries this implementation. NOT
  `ec18062d`, the commit that introduced it: that run was cancelled with zero
  jobs by the concurrency gap recorded as Plan 00400 N3, so citing it would cite
  a run that does not exist.
- [x] The plan is archived into the holding area (`Completed/`) with the README
  row and statistics updated in the same commit.

## Delivery & Milestones

- Graduated from Plan 00397 N3. The owner reported sessions in other projects
  climbing to "COMPACT NOW" without compacting; that observation is what
  overturned an earlier, narrower conclusion that auto-compaction was healthy.
