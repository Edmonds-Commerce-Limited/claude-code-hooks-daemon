# Callout: focus mode points one session at one task

**Plan**: 00501
**Audience**: operators

You can now type `hooks-daemon focus <task>` at the start of a prompt to put that session, and only that session, into focus mode. Any case works, and so do the speech-to-text spellings `hooks daemon` and `hooks demon`. Type `hooks-daemon focus off` to end it; `done`, `end` and `disable` also work. The new `focus_mode_trigger` handler is on by default and states each change to the agent in one line.

While a session is focused:

- Every work-driving (`drives_autonomy`) handler is skipped for it, so `goal_injection` writes no `.goal-intent`.
- Declared `persistent_crons` ticks are dropped, even for a job that sets `runs_while_awaiting_human`.
- The watchdog tick is delivered.
- The failsafe tick is delivered with the line "focus mode: the active task is <task>; other plans are out of scope".
- A stop without a reason gets a one-line focus reminder in place of the goal-ledger plan list.

Entering focus clears an existing goal once. The ccy supervisor types `/goal clear` at its next idle; without the supervisor, a human must type it. Focus lasts 12 hours, and each prompt the human types renews it. The agent is told once when it expires.

The same operations are available as `/mode focus <task>`, `/mode focus off`, `hooks-daemon session-mode get|focus <task>|focus off`, and the `get_session_modes`, `enter_focus` and `exit_focus` IPC actions. The daemon-wide `/mode`, `get-mode`/`set-mode` and `get_mode`/`set_mode` are unchanged. `R-DECLARED-CRON-SUPPRESSED` now names focus as well as the blocked modes.
