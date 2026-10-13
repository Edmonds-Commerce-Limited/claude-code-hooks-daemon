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

## How it fits this plan

- `manual-goals` suppresses goal injection only. Unlike `focus`, it does not drop cron ticks or work-driving
  advisories. It sits in the precedence list between `awaiting-human` and `focus` unless the owner says otherwise.
- The supervisor already reads modes from the per-session file (Task 5.1), so it needs no second channel to learn
  that goals are off. The side-channel record is the new supervisor change.
- Phase 0 gains a spike: does `UserPromptSubmit` fire for `/goal clear`?

## Questions for the owner (question 11 in PLAN.md)

1. **Exit:** what switches `manual-goals` off: a `/goal <condition>` the human types, a `hooks-daemon goals on`
   prompt, a new session, or all three?
2. **Post-compaction re-injection:** does `manual-goals` also stop the supervisor re-injecting the goal after a
   compaction? Recommended: yes, since that is the same automated injection.
3. **Scope of the mod section:** is a read-only mode display enough for the first mod section, with session-scoped
   config overrides (and persisting them) a later step? Recommended: yes, to "break the ice" with the smallest mod.
