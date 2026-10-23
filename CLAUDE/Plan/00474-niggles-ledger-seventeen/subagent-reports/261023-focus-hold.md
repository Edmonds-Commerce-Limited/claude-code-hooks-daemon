# N534: supervisor focus hold and goal-clear attribution

Brief: `untracked/scratch/brief-n534.md`. Branch `worktree-n534-focus-hold`, base 9ea73b3be.

## Defect A: false focus hold, NOT fixed (no trustworthy signal)

The brief says to stop and report options if no trustworthy "is any sub-agent or teammate alive" signal exists.
None does.

What the supervisor can already read in the context-sidecar directory: context sidecars, usage pause, session
modes, model-downgrade signals, goal and goal-clear triggers, cron records. None of these carries a sub-agent count.

The daemon's only such reading is the spend meter's `live.json` (`utils/session_load.py`, `refresh_live_snapshot`).
Plan 00537 Task 2.1 already evaluated and rejected it as a clearing signal
(`Completed/00537-.../JOURNAL/00537-Journal-26-10-20.md`, 00:40 entry; `CcySupervisor.md` "Known limits").
`session_load.py` has not changed since that finding (last commit 59cbd6a4f, 26-10-16). Its five ways to
under-report a started agent all still hold:

1. It refreshes only at Stop/SubagentStop. Nothing recounts at SubagentStart: the event is registered in
   `.claude/settings.json`, but no daemon handler records it.
2. Its 120 s transcript liveness window drops an agent that is blocked in a long tool call or waiting on a permission.
3. It skips an agent whose last record is `end_turn`, but a teammate or background agent between turns still has a
   panel row.
4. It matches `finished` by description, so an agent that reuses a description is treated as finished.
5. It counts RUNNING agents, not selectable rows or transcripts. Even a correct zero does not prove focus is on the
   main prompt.

Under-reporting is the unsafe direction for a clearing signal, so shipping it would invent the heuristic the brief
rules out.

**Options for the owner:**

- **(a) Keep the Plan 00537 ruling.** Only Esc clears the hold. The cost is the run's failure: a stale hold blocks
  the blocked-loop clear.
- **(b) A daemon start/stop registry.** Record SubagentStart and SubagentStop per session, and let "started minus
  stopped == 0" clear the hold. This fixes 1, 2 and 4. It does not fix 3 or 5: a finished agent's row stays
  selectable, and teammates need checking. It needs daemon and host code (a ccy relaunch).
- **(c) The Plan 00538 Phase 1 spike.** Look for a positive focus signal (`subagentStatusLine` input, a hook payload
  field, a state file). This is the only option that answers the actual question, "where is focus".
- **(d) "No sub-agent transcript ever existed in this session".** Sound only as a weak rule, with a small race before
  the transcript file appears. It would not have helped this coordinator session if it had run any agent earlier.
- **(e) Narrow what the hold blocks.** Example: let the BLOCKED goal clear bypass it. Rejected here, because a
  `/goal clear` typed into a sub-agent's panel goes to the sub-agent. That is the harm the hold exists to prevent.

The status-line notice is unchanged, because no new way to clear the hold was added.

**Plan 00538.** This work completes or changes none of 00538's tasks. Its Phase 1 spike (Task 1.1 and 1.2) is option
(c) above, still open. Its owner items (auto-refocus, the mods route) were not touched. This run is new evidence for
its Overview's "false hold" cost: the false hold now stops a goal-blocked clear, not only a banner.

## Defect B: what happened, and the fix

**From the code** (`.claude/ccy/claude-supervise.py`):

- `decide_once` (worker) writes `<stem>.goal-clear-injected` (`write_goal_clear_record`, ~line 8074). It does this
  only once `can_inject` is true: main focus confirmed, idle (no stdin byte for `_DEFAULT_IDLE_FLOOR_SECONDS` = 2 s),
  and an empty own line. The record's `ts` is `facts.now_wall`, the tick START.
- So the record stamped 12:05:40.5 proves that at that tick the hold was NOT latched (the human had pressed a bare Esc
  by then) and no key had been typed for 2 s.
- The host then types the payload in `_apply_decision`. The only gates there are the focus model re-read at apply time
  and a PTY write failure (which raises). Idle and the empty box are not re-checked.
- Nothing in the supervisor learns that the human already cleared the goal. The `.goal-clear` trigger survives until
  the supervisor consumes it, and the daemon reads a typed clear only at the next Stop.
- **Conclusion:** the code path is a DOUBLE clear. The supervisor wrote its record AND typed `/goal clear` about 0.5 s
  after the owner's. "Record without typing" needs one of two things: an Up/Down arriving between the worker's
  decision and the host's apply (logged as `... decided before the focus hold latched; not typed`), or a PTY write
  error.
- `decision.log` for 12:05:40 would settle it. Per the brief I did not read live session artefacts.

**The attribution flaw.** `attribute_clear` accepted a clear stamped up to `CLOCK_TOLERANCE_SECONDS` (2.0 s) BEFORE the
record. The owner's clear (gap -0.5 s) was therefore attributed SUPERVISOR and consumed the record. The supervisor's
own later clear then found no record and was attributed HUMAN. The two verdicts were swapped, and with "record without
typing" the human's clear is lost outright.

The record is written before the supervisor types, and Claude Code floors transcript stamps to whole milliseconds on
the same host clock. So a supervisor clear is never stamped more than 1 ms before its record.

**Fix:** `CLOCK_TOLERANCE_SECONDS = 0.001` in `src/claude_code_hooks_daemon/core/goal_clear_attribution.py`. A clear
that precedes the record is now HUMAN, and the record is kept for the supervisor's own clear. This is daemon code, so
it takes effect at the next daemon restart (not done here).

**Residual risk (not fixed):** a record written but never typed (held at apply, or a PTY error), followed by a human
clear within `FRESH_WINDOW_SECONDS` (120 s). That clear is still credited to the supervisor. The fix would be host-side
(remove the record when the apply is held or fails) and needs a ccy relaunch.

## Tests

- RED, `tests/unit/core/test_goal_clear_attribution.py`, two failures for the right reason
  (`record=fresh gap=-0.5s` -> SUPERVISOR):
  - `test_a_clear_stamped_before_the_record_is_a_human_and_keeps_the_record`
  - `test_a_human_clear_then_the_supervisor_clear_are_each_attributed` (the double clear)
- New, passing: `test_a_stamp_truncated_to_the_millisecond_is_still_the_supervisor`.
- GREEN: attribution, `test_goal_loop_detector.py` and `test_goal_clear_record.py` all pass.
- Release note `025-goal-clear-attribution.md` gained one sentence.

## QA and head

See the final QA line and head sha appended below.
