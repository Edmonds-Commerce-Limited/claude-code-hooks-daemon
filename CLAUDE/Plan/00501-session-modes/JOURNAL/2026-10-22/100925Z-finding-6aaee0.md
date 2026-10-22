## 10:09 · finding · —   — Spikes 0.2 and 0.3: loop shape, mid-turn goal clear, halt unproven

Spikes 0.2 and 0.3 done from existing evidence; reports are SPIKE-0.2-stop-payloads.md and SPIKE-0.3-continue-false.md in the plan folder.

Takeaways:

- A goal loop is a chain of capped turns. Claude Code 2.1.296 ends a turn after 9 consecutive stop-hook blocks and posts "Goal paused · goal checks kept finding it unmet this turn · send a message to continue". The supervisor's `/compact` then post-compact `continue` resumed it (2026-10-11 13:01 to 13:03, six cap events that day). Ruling 7 (suppress `continue` under BLOCKED) is therefore load-bearing.
- A `/goal` or `/goal clear` typed while a turn runs executes at once, not queued behind the turn and not rejected: 129 mid-turn `Goal set:` injections and 7 mid-turn supervisor clears, each with its `goal_status sentinel:true` snapshot within 10 ms and no later evaluation.
- The supervisor's goal-clear family is gated on human-input idleness (`can_inject`, claude-supervise.py:7253), not on child output, so the busy-session clear already works with today's machinery; no ESC needed. The 5-per-process clear cap has been hit (2026-09-17).
- Stop `continue:false` against `/goal`: unproven. Docs say `continue:false` takes precedence over decision fields within one output and all hooks run in parallel; nothing covers merging with a prompt hook's block. No transcript example exists. A disposable headless `claude -p` in untracked/scratch/spike501-03 (user settings only, scratch Stop hook, session env vars unset) failed "Not logged in", so no live test was possible; the harness is left there.

Lever for Task 6.3: the immediate goal clear through the existing goal-clear channel, plus the BLOCKED suppression of `continue` and ticks. No `continue:false` halt until a live test proves it beats the evaluator and also disarms the goal.
