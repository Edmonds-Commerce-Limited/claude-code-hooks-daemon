# N534 Defect A: ruling on the focus-hold options (Fable advice)

Inputs read: `261023-focus-hold.md` (Defect A, options a-e), Plan 00538 PLAN.md,
`CcySupervisor.md` "Known limits". No code or plan was edited.

## Framing

The owner's word "buggy" needs one correction before anything is scheduled: there
is no thread detector to be buggy. Plan 00537 shipped a LATCH (Up/Down sets it,
Esc clears it) precisely because no detector exists. The defect is the absence of a
focus signal, and the new fact this run adds is the COST of that absence: a false
hold now blocks the goal-blocked `/goal clear`, so the stop loop burns a model
turn per stop until a human presses Esc. Everything below is ordered by that cost.

## Ruling

### 1. Now: remove the cost without touching the hold (new task, NOT in 00538)

The hold exists to stop a keystroke landing in the wrong panel. The goal-blocked
clear does not need a keystroke at all: the daemon writes the `.goal-clear`
trigger, the daemon owns the BLOCKED mode, and the daemon's own Stop handler is
what keeps the loop running. Make the daemon treat its OWN pending `.goal-clear`
trigger as sufficient to release the stop (or clear the goal itself at that Stop),
so the typed `/goal clear` becomes confirmation rather than the only exit.

- Daemon-only; no host code, no ccy relaunch.
- Fails in the safe direction: the worst case is a session that stops when it
  should have been nudged once more, never a payload in a sub-agent's panel.
- It is goal-loop behaviour (Plan 00501's domain), not a focus signal, so it does
  not belong in 00538. Put it as a task in Plan 00501 if that plan is still open;
  otherwise a small new plan. Either way the N534 niggle row should point at it.
- Verify first, from the code, WHY the clear is typed today. If the only reason is
  attribution (Defect B's typed-clear bookkeeping), the daemon-side clear can be
  attributed `DAEMON` and the bookkeeping stays sound.
- OWNER: product intent. The owner may have wanted every goal clear to be a
  visible typed command in the transcript. If so, item 1 reduces to "release the
  stop while the trigger is pending" and the typed clear still follows.

### 2. Now, in parallel: Plan 00538 Task 1.1, the spike (option c)

This is the only option that answers "where is focus". It is observation only
(capture `subagentStatusLine` input and hook payloads with a row selected and
with a transcript open), costs no code and no relaunch, and it is ALREADY the
plan's first task. Do not re-file it. Record this run as new evidence in 00538's
Overview (the false hold now blocks a goal-blocked clear, not only a banner) via
a journal entry, and raise its Priority from Low.

Task 1.2 (use a found signal to clear the latch on POSITIVE evidence of main
focus) stays as written. It is the only clearing rule that is sound in the
unsafe direction.

### 3. Conditional on 2 finding nothing: a weak, sound rule (options b+d merged)

If no positive signal exists, the one clearing rule that cannot fire while a
panel exists is "no sub-agent has ever started in this session". A panel row
can only exist for an agent that started, so a zero start count proves Up was
history recall.

- Source the count from a SubagentStart record written by the daemon (the hook is
  registered; no handler records it today), not from transcript files: the
  transcript variant (d) has a race in the unsafe direction.
- This is option (b)'s registry used ONLY as an ever-started counter. Do NOT use
  "started minus stopped == 0" as a clearing signal: a finished agent's row stays
  selectable (the report's point 3), so that rule clears the hold while a panel
  exists. That is the unsafe direction and it is why Plan 00537 rejected the
  spend meter's count.
- It would not have helped the session in this run (agents had started earlier),
  so its value is the history-recall case only. File it as 00538 Task 1.3, gated
  on 1.1's result.
- Host code is needed to read the record, so OWNER: it costs a ccy relaunch.

### 4. Rejected now

- **(e) Narrow what the hold blocks.** Agree with the report. `/goal clear` typed
  while a sub-agent's panel has focus goes to the sub-agent as its next message
  (or, with a row merely selected, Enter opens the transcript and the text is
  misrouted), which is the exact harm the hold prevents. The `/exit` restart
  path shares the same route and is worse. Item 1 is the safe form of (e): it
  bypasses the keyboard, not the hold.
- **(b) as a live-count clearing signal.** Unsound, see 3.
- **(a) alone.** It is the default until 1 lands, not a decision.

### 5. Owner decisions to bubble up (all OWNER:)

- OWNER: whether a goal clear may be made daemon-side without a typed command
  (item 1).
- OWNER: Plan 00538 Phase 2, auto-refocus. The supervisor would press keys off a
  screen model. Esc is right for a selected row, unknown for an open transcript,
  and Up may recall history; Plan 00160 already judged screen-scraping fragile.
  This is a safety control, not engineering; stays an owner call.
- OWNER: the mods `$.prompt.submit` route, which contradicts Plan 00497's ruling.
- OWNER: a ccy relaunch for any host-side change (item 3, and Defect B's residual
  record-without-typing fix).
- OWNER: until item 1 lands, the remedy is manual Esc. The status-line notice
  already says so; confirm that is acceptable for unattended sessions.

## Risks named

- Unsafe direction, always: any rule that clears the hold while a panel exists.
  Under-reporting counters, transcript races and live-count arithmetic all fail
  this way. Prefer a rule that cannot be wrong (ever-started == 0) or a positive
  focus signal over any heuristic.
- Item 1 changes BLOCKED-mode semantics; its tests must pin that a pending
  trigger releases exactly one stop path and never types anything.
- Hot-reload boundary (CcySupervisor.md): worker logic hot-reloads, host
  `TickFacts` does not. Item 3 is host code; item 1 is daemon code and needs only
  a daemon restart.

## Order

1 and 2 in parallel now; 3 only if 2 finds no signal; Phase 2 and the rest wait on
the owner.
