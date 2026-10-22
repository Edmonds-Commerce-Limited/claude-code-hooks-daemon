# Plan 00501 Phase 5: merge advice (adviser ruling)

Adviser: Fable 5.1 sub-agent, delegated by the owner ("bubble up only what fable is not clear on").
Inputs read: `PLAN.md` (Goals, Rulings 01-11, Phases 5-8), `subagent-reports/261022-phase5-impl-opus.md`,
`CLAUDE/development/CcySupervisor.md` "Session modes" section, and the code cited below.

## Q1: merge Phase 5 while THIS session is in awaiting-human? -- CLEAR: (a) merge as is

**Ruling.** Merge now. Do not clear the mode by any agent route, and do not defer the merge.

**Why (b) is out -- there is no supported non-human exit, and that is deliberate.**

- `bin/hooks-daemon session-mode` accepts `get | focus <task> | focus off` only (`daemon/cli.py:11005-11020`).
  The IPC (`daemon/session_mode_ipc.py`) has `get_session_modes`, `enter_focus`, `exit_focus`,
  `get_mode_history`. Nothing exits BLOCKED. `/mode` wraps the same verbs.
- BLOCKED(declared) ends on exactly: a genuine human prompt in the SAME session
  (`failsafe_cron_blockage_suppressor._note_untagged_prompt`, classified by `is_genuine_human_prompt`, which
  rejects tick sentinels and the supervisor's marker), or the 24 h `DECLARED_BLOCKED_TTL_SECONDS`
  (`utils/session_modes.py:40`). It is `Lifetime.SESSION`, so a daemon restart does not clear it.
- Phase 2 (Task 2.1, ledger N378) made "only a human prompt in the same session" the contract and regression-tests
  the supervisor-typed and cross-session cases. An agent editing `<stem>.session-modes`, deleting it, or typing a
  line that masquerades as human would be exactly the bypass that task exists to prevent. Not legitimate, and
  it would make the field evidence for Phase 6/7 (declared stops count toward the detector) untrustworthy.

**Why (c) is out.** Deferring a QA-green, reviewed branch for the whole of Phases 6-8 (a detector, docs, a
live acceptance run, and manual goals) so that the gate does not apply to the session doing the work is
gaming the mode, and it stacks merge risk on a branch that touches `decide_once`. Phase 5's own reload
verification recipe needs the merge to run at all.

**Why (a) is honest and bounded.** The release genuinely IS awaiting the owner. The cost is: after the next
compaction the session gets no `continue`/goal/directive until the owner types or the 24 h TTL expires
(entered 19:46 UTC, so by 19:46 tomorrow). The owner's next message is the designed exit and is the same
message that answers the release question, so the stall ends the moment the blocker does. Until then the
session is not stopped by the merge: the goal already armed inside Claude Code is unaffected (the gate
withholds NEW `.goal-intent` injection; nothing disarms a live goal until Phase 6 act mode), so the current
turn and its Stop-evaluated goal keep driving work until a compaction leaves the session idle.

**One note for the coordinator, not a question.** The declaration at 19:46 sat uneasily with the Stop
guidance ("only when it is the ONLY thing blocking you ... if there is work you could still do, do it"):
Plan 00501 was workable. The release procedure mandated the stop, so the declaration stands, but the
mode's 24 h cap is precisely the "a mistake costs at most a day of ticks" bound the guidance names. Future
release-gate stops should say `[awaiting-human]` only when no other plan in the goal is workable.

## Q2: does focus need a supervisor-side task (5.3)? -- CLEAR: no task; fix the Goals sentence

**Daemon side already does what the plan means.**

- Goal: `enter_focus` calls `clear_goal_signal` (`core/focus_mode.py:178`), which UNLINKS a pending
  `<session>.goal-intent` and writes `.goal-clear` (`goal_injection.py:538-555`); while focused
  `goal_injection` (`drives_autonomy = True`) is chain-skipped, so no new intent is written.
  The supervisor has nothing to type.
- Session-actions directive: `session_actions_directive` is `drives_autonomy = True`
  (`handlers/session_start/session_actions_directive.py:76`), chain-gated under focus
  (`core/chain.py:1151`), so no `.session-actions` signal exists for the supervisor to act on.
- Standing-auth reminder: `standing_authorisations` is NOT a `drives_autonomy` handler and its supervisor
  channel ships OFF (`_DEFAULT_SUPERVISOR_CHANNEL_ENABLED = False`). It replays authorisations; it does not
  drive work. Focus should not suppress it (the Goals define focus as "every `drives_autonomy` handler is
  skipped", which it is not).
- Post-compact `continue`: must NOT be suppressed under focus. A focused session is a WORKING session on one
  task; `continue` resumes that task after a compaction. Suppressing it would turn focus into a halt, which
  is BLOCKED's job (Ruling 07 is scoped to BLOCKED for this reason).

So `test_goal_still_fires_under_focus_alone` pins the right supervisor behaviour: the supervisor is a dumb
typist of daemon signals, and under focus the daemon emits none of the work-driving ones. A supervisor-side
focus gate would be a second copy of a decision the daemon already makes, with its own format pin to keep.

**What to change instead (editorial, PLAN.md Goals, "Focus mode" bullet 3).** Replace
"The ccy supervisor injects no goals or prompts." with:

> The ccy supervisor types no goal and no session-actions directive while focused, because the daemon
> writes neither signal (goal cleared once on entry, `.goal-intent` and `.session-actions` not written);
> the supervisor itself reads no focus state. The post-compact `continue` and the standing-authorisation
> reminder are unaffected: focus is a working mode, not a halt.

Carry the same sentence into Task 7.1's docs. No Task 5.3.

## Q3: unreadable/malformed modes file => BLOCKED (fail-closed, loud) -- CLEAR: endorse

- Symmetric with the daemon's own rule ("never read as no modes", Task 1.2) and with the only error class
  that matters: the unreadable file may be the BLOCKED entry the gate exists to honour.
- The cost is bounded and visible: one withheld work-driving prompt per tick, a `noop:` line that outranks
  the others, and a status-line WARNING every tick. Nothing is destroyed; a human restarts the turn.
- It is self-healing: the daemon renames the file `*.corrupt` on its next registry load, after which the
  supervisor sees no file and the gate opens. So "closed" lasts until the daemon next touches the registry.
- The cap exemption (Task 5.2) is correctly withheld: an unconfirmed BLOCKED earns no special treatment.

One follow-on for Task 7.1 only: `status-line-explained` should name the WARNING text so an operator who
sees it knows the fix is "let the daemon load its registry / check the `.corrupt` file", not a restart.

## Summary

| Q   | Verdict                                                   | Status |
| --- | --------------------------------------------------------- | ------ |
| Q1  | (a) merge as is; no agent may clear BLOCKED; do not defer | CLEAR  |
| Q2  | no Task 5.3; daemon side sufficient; amend Goals wording  | CLEAR  |
| Q3  | endorse fail-closed                                       | CLEAR  |

Nothing to bubble up to the owner. The owner's next message to this session is already the designed exit
from awaiting-human and the release decision Plan 00476 waits on.
