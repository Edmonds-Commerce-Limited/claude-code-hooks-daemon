# Plan 00339: supervisor injection lands unsubmitted

**Status**: Complete
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Reported live by the owner: the ccy supervisor's compaction message was sitting
in Claude Code's input box, followed by a newline, never submitted.

`_perform_injection` writes the payload, sleeps `_SUBMIT_DELAY_SECONDS` (0.2s),
then writes a standalone `\r`. That separation is on the **write** side, but
whether the two writes are read as one burst is decided at the **reader**. A
sender-side sleep cannot guarantee separation at the receiver, which is why the
failure is intermittent and load-dependent, and why the constant was already
tuned once (the comment records a long `/compact` line failing where a short
one worked).

**Measured, not inferred** (Phase 3 probes, real Claude Code v2.1.263 driven
over a PTY with the real 131-byte armed payload): a coalesced
`payload + \r` leaves the line sitting unsubmitted in the box, while a
coalesced `ESC[200~ payload ESC[201~ \r` submits. A short bare `/compact\r`
submits either way. So the trigger is not "arrived in one `read()`" — it is
Claude Code's **paste detection**: a burst that large is treated as pasted
text, and a carriage return inside pasted text is a literal newline. Framing
the payload states where the paste ends, making the following `\r` a keypress
regardless of how the writes are batched.

The supervisor cannot see this happen. Its own injections are deliberately kept
out of the `HumanInputLine` box model so they can never mark the box non-empty
— which means the one observable that would distinguish the two stall causes is
excluded by design. Its only stall remedy was `[esc]`, which flushes a command
Claude Code **queued** behind an in-flight turn but cannot submit a line that
never left the box. Each escape refreshes `_last_action_ts`, which both
`_escape_due` and `_await_timed_out` measure from, so the await timeout can
never cut the sequence short: the full budget of five escapes burns over ~5
minutes, the machine returns to MONITOR, and once the cooldown elapses it can
inject a **second** `/compact` on top of the first — which is how the box ends
up holding a compaction message, a newline, and more text.

## Goals

- Make the stall remedy cover both causes, without weakening the one that is
  proven in the field.
- Stop a second `/compact` stacking on top of an unsubmitted first.
- Remove the dependence on sender-side timing for the submit boundary, if that
  can be done without risking the live compaction path.

## Non-Goals

- Reworking the AWAIT_COMPACTING state machine or its budget semantics.
- Changing `_SUBMIT_DELAY_SECONDS` as a fix in itself. A larger delay narrows
  the window but cannot close it — the reader decides the coalescing, not the
  writer — and it would read as a fix while leaving the defect in place.
- Tracking supervisor-injected text in `HumanInputLine`. That exclusion is
  deliberate (it is what keeps an injection from marking the box non-empty and
  blocking the next one); undoing it to gain an observable would trade a
  reliable guard for a diagnostic.

## Tasks

### Phase 1: Make the remedy match the cause

- [x] ✅ **Task 1.1**: Confirm the mechanism from code and the live decision
  log rather than from the symptom alone. **Done.** `decision.log` shows the
  escape path working for the queued cause (`escape ... (1/5)` at 00:03:29,
  `compaction detected` at 00:03:31), which is why that remedy must not be
  displaced. It also shows no stall recorded for the reported episode, because
  the supervisor has no way to observe its own text sitting in the box.

- [x] ✅ **Task 1.2**: Add a second remedy, alternating rather than replacing.
  **Done.** New `Decision.WOULD_RESUBMIT` injects a bare `\r`
  (`_RESUBMIT_PAYLOAD`) with `submit=False`, so exactly one carriage return is
  written — submitting the submit would send two and the second would submit an
  empty box. `[esc]` stays the FIRST attempt because the queued cause is the
  observed one; from the second attempt the remedies alternate, so a stuck box
  gets an Enter as soon as ESC has visibly failed once. Both draw on the single
  `max_escapes` budget, so a wedged session still gives up after the same
  number of attempts instead of escalating twice as long.

- [x] ✅ **Task 1.3**: Inherit every existing guard. **Done — no new gate was
  needed.** `_evaluate_tick` computes `can_inject = facts.idle and facts.input_line_empty` and passes it as `idle`, and the flush branch is
  already `if idle and self._escape_due(now)`. So a blind Enter can never
  submit a half-written human message, never fires for a human-originated
  `/compact`, and never fires once compaction is under way. Pinned by tests
  rather than assumed.

### Phase 2: Stop the second `/compact` stacking

- [x] ✅ **Task 2.1**: Establish whether Phase 1 closes this by itself.
  **Done — measured.** Reaching a second injection needs the whole flush budget
  to burn without a compaction starting: `_enter_monitor` leaves
  `_last_action_ts` at the last attempt, so once the cooldown elapses MONITOR
  injects again. Phase 1 puts an Enter at attempt 2 of 5, and Phase 3 stops the
  line being stuck in the first place, so the stacking path now needs THREE
  independent failures (framing, ESC, Enter). Confirmed with the probe that ESC
  does NOT clear the box — the TUI answers a single ESC with "Esc again to
  clear" — so the pre-Phase-1 machine could never have recovered on its own.

- [x] ✅ **Task 2.2**: Decide what a second `/compact` should do when the first
  may still be in the box. **Decided: ship no guard, and record why.** The
  probe establishes Ctrl-U (`0x15`) as a working box-clear — the TUI empties the
  box and offers "Ctrl+Y to paste deleted text" — so a clear-then-inject guard
  is now buildable. It is deliberately NOT shipped: it would fire on a path that
  needs three independent failures, and its cost is that `input_line_empty` is
  the supervisor's MODEL of the human's box, so any case where that model is
  wrong turns the guard into a keystroke that wipes human text. Guarding a
  triple-failure path with a change that can destroy real input is the wrong
  trade. The measurement is recorded here so the guard can be built without
  re-deriving it, if the path is ever actually observed.

### Phase 3: Remove the timing dependence (needs a live experiment)

- [x] ✅ **Task 3.1**: Evaluate explicit bracketed-paste framing. **Done and
  shipped.** `_perform_injection` now writes a submitted payload as ONE
  `_PASTE_START + payload + _PASTE_END` burst; the `\r` stays a separate,
  delayed write outside the frame. A raw keypress (`submit=False` — the ESC
  interrupt and the Phase 1 bare-Enter resubmit) is written unframed: framing a
  control character would paste it as literal text instead of pressing it.

- [x] ✅ **Task 3.2**: Do NOT ship it on reasoning alone. **Tested first, and
  the feared failure did not occur.** Three probes drove a real Claude Code
  v2.1.263 over a PTY, typing into the input box and never submitting a turn, so
  the experiment cost no model call:

  - The paste rendered INLINE, not as a `[Pasted text]` placeholder, and still
    opened the slash-command menu (`/compact`, `/autocompact`) exactly as
    typing it did. A submitted paste ran as a command.
  - The bug reproduced deterministically: the real payload + `\r` in ONE write
    sat unsubmitted in the box. The same write with paste framing submitted.
  - Also settled, as a by-product: a single ESC does not clear the box ("Esc
    again to clear"), and Ctrl-U does (with a kill-ring hint). Both feed
    Phase 2.

## Success Criteria

- [x] ✅ A `/compact` left unsubmitted in the input box is submitted by the
  supervisor without human intervention (Phase 1's alternating Enter).
- [x] ✅ The injection stops landing unsubmitted in the first place — verified
  against a real TUI, not reasoned about (Phase 3's paste framing).
- [x] ✅ The queued-command remedy still fires first and still works.
- [x] ✅ The give-up budget is unchanged in attempt count.
- [x] ✅ Neither remedy can fire while the human has text in the box, during a
  human-originated compaction, or once compaction is under way.
- [x] ✅ Full QA green (25/25, 18,195 tests, 95.2% coverage) and the daemon
  restarted and verified before the terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00339-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: owner bug report during the Plan 00336 session.
- Dedupe scout checked 46 live plans and found none covering it. Plan 00168
  (supervisor compaction injection not firing, Dormant) is the nearest by
  subsystem but scopes WHETHER an injection fires, not whether a fired one was
  submitted.
