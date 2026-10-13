# Manual goals: a human `/goal clear` turns automated goals off (#106)

The owner filed #106 while answering the Plan 00474 owner sheet (row N334). It is folded into this plan because
items 2 to 4 are a session mode with a suppression set, a status-line label and an exit, which is what this plan
builds. Item 5, the control-panel mod, belongs to Plan 00497 (the hooks-daemon mod), which takes it as a feature that
depends on this plan's mode state. No work is scheduled until the owner answers question 11 in PLAN.md.

## The request, as filed

1. Detect a `/goal clear` typed by a human, and tell it apart from one the ccy supervisor injected.
2. Model the result as a session mode, `manual-goals`: automated goal injection stays off for the session until it is
   switched back.
3. A short status-line indicator for the active mode.
4. A clear way to switch it back; prompting for that at a sensible point is optional.
5. A first hooks-daemon mod: one mod with sub-sections, the first a control panel for session-scoped config overrides
   (config holds the defaults, the panel overrides them for the session, optionally persisting), with session modes
   in full detail.

## Facts gathered on the issue (the owner's research comments, not re-verified here)

- `/goal clear` has the aliases `stop`, `off`, `reset`, `none` and `cancel`, matched on the whole trimmed argument,
  ignoring case. Any other text after `/goal` sets a new goal, so the supervisor cannot mark its own clear in the
  command text.
- Whether `UserPromptSubmit` fires for a built-in slash command is undocumented; a logging hook must settle it. The
  transcript records the command either way.
- The supervisor's clear is legitimate: it is how a goal is retracted once no plan it names is still In Progress.

## Proposed design (from the issue's comments)

- **Side-channel record.** Before injecting a clearing `/goal`, the supervisor writes a short-lived
  `<session>.goal-clear-injected` record (session id, timestamp, the literal typed) in the sidecar directory it shares
  with the daemon.
- **Attribution.** A clearing `/goal` with a fresh, matching record is the supervisor's: consume the record and change
  no mode. With no record, it is a human's: enter `manual-goals`.
- **Fail safe.** An unreadable record counts as the supervisor's, so no mode changes. A human can repeat the clear; a
  spurious "human" clear would silently switch automation off.
- **Trade-off (coordinator note):** the record would be the first file the supervisor writes into the sidecar
  directory, which today only the daemon writes. Anything that can write there can forge a record and hide a human
  clear, and the fail-safe rule leans the same way. Under the careless-not-hostile threat model that is acceptable,
  but it is a new write path to review.

## How it fits this plan

- `manual-goals` suppresses goal injection only. Unlike `focus`, it does not drop cron ticks or work-driving
  advisories. Task 8.3 adds it to the precedence list (PLAN.md Goals), between `awaiting-human` and `focus` unless
  the owner says otherwise.
- The supervisor already reads modes from the per-session file (Task 5.1), so it needs no second channel to learn
  that goals are off. The side-channel record is the new supervisor change.
- Task 8.1 is a spike: does `UserPromptSubmit` fire for `/goal clear`?
- After a compaction the supervisor injects only `continue`; it types `/goal` only from a `*.goal-intent` signal the
  daemon writes (`claude-supervise.py`). So "suppress goal injection" means the daemon writes no goal-intent signal
  while the mode is on; there is no separate post-compaction `/goal` to stop.

## Questions for the owner (question 11 in PLAN.md)

1. **Exit:** what switches `manual-goals` off: a `/goal <condition>` the human types, a `hooks-daemon goals on`
   prompt, a new session, or all three?
2. **Post-compaction `continue`:** the issue asks whether the mode should stop a post-compaction goal
   re-injection. The supervisor does not re-inject a goal then (see above); it types `continue`. Should
   `manual-goals` also suppress that `continue`? Recommended: no. The mode is about goals; suppressing `continue` is
   what `BLOCKED` does (question 7).
3. **Scope of the mod section:** is a read-only mode display enough for the first mod section, with session-scoped
   config overrides (and persisting them) a later step? Recommended: yes, to "break the ice" with the smallest mod.
