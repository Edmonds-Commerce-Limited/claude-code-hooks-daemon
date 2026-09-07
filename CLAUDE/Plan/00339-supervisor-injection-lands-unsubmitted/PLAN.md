# Plan 00339: supervisor injection lands unsubmitted

**Status**: In Progress
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
keystroke/paste coalescing is decided on the **read** side. If the TUI event
loop is blocked for longer than the delay — rendering a long transcript, GC,
heavy load — both writes drain in a single `read()` and the carriage return is
absorbed into the multi-line input box as a literal newline. A sender-side
sleep cannot guarantee separation at the receiver, which is why the failure is
intermittent and load-dependent, and why the constant was already tuned once
(the comment records a long `/compact` line failing where a short one worked).

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

- [ ] ⬜ **Task 2.1**: Establish whether Phase 1 closes this by itself. If the
  resubmit submits the stuck line, the episode ends and no second injection is
  reached. The stacking is only observable when BOTH remedies fail, so measure
  before adding a guard for it.
- [ ] ⬜ **Task 2.2**: If it persists, decide what a second `/compact` should
  do when the first may still be in the box. Note the constraint from
  Non-Goals: the box model deliberately cannot see supervisor text, so this
  cannot be solved by reading the box.

### Phase 3: Remove the timing dependence (needs a live experiment)

- [ ] ⬜ **Task 3.1**: Evaluate explicit bracketed-paste framing. The
  supervisor owns the PTY master, so it IS the terminal; Claude Code enables
  bracketed paste (the evidence is that `HumanInputLine` already parses
  `ESC[200~`/`ESC[201~` out of the forwarded human stream). Wrapping the
  payload would make the paste boundary explicit and a following `\r`
  unambiguously a keypress — no heuristic, no timing.
- [ ] ⬜ **Task 3.2**: Do NOT ship it on reasoning alone. Claude Code may
  render a bracketed paste as a `[Pasted text]` placeholder rather than inline
  text, which would stop `/compact` being recognised as a slash command and
  break compaction entirely. Test it in a scratch session first; the payload is
  single-line, which is the case most likely to insert inline, but "likely" is
  not a basis for changing the live compaction path.

## Success Criteria

- [ ] A `/compact` left unsubmitted in the input box is submitted by the
  supervisor without human intervention.
- [ ] The queued-command remedy still fires first and still works.
- [ ] The give-up budget is unchanged in attempt count.
- [ ] Neither remedy can fire while the human has text in the box, during a
  human-originated compaction, or once compaction is under way.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00339-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: owner bug report during the Plan 00336 session.
- Dedupe scout checked 46 live plans and found none covering it. Plan 00168
  (supervisor compaction injection not firing, Dormant) is the nearest by
  subsystem but scopes WHETHER an injection fires, not whether a fired one was
  submitted.
