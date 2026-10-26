## 14:39 · decision · —   — Owner rulings on the goal-loop dogfood: act default, self clear-goal, Blocked drops from the goal

Owner rulings of 2026-10-26 on the goal-loop dogfood report (the 64-hour main-session loop: 1446 unmet evaluations, no human prompt between).

1. The incident is accepted as the trigger for Task 7.3. The `goal_loop_detector` default flips from `observe` to `act` now, without waiting for three counted true positives or two releases. `mode: observe` stays available as an opt-out. Thresholds are unchanged.
2. An agent may run `bin/hooks-daemon clear-goal` itself when its goal cannot be satisfied. The first `loop-persisting` line and act mode's entry notice now instruct: run `bin/hooks-daemon clear-goal`, journal why, then stop with the real blocker stated. `clear-goal` retracts only the session's own goal: it removes `<session>.goal-intent` and writes the `<session>.goal-clear` trigger the ccy supervisor types `/goal clear` from at its next idle. It needs `CLAUDE_CODE_SESSION_ID`, is idempotent, and ends no session mode.
3. A plan that moves to `Blocked` drops out of the combined goal the way a retired plan does, for goal-ledger purposes only (new `GOAL_DROPPING_STATUSES` in `plan_qa/model.py`; `TERMINAL_STATUSES`, archiving and plan-QA are unchanged). A goal whose plans are all Complete or Blocked is cleared.

Known limit: the once-per-plan-per-session latch in `goal_injection` also applies to a plan reopened from Blocked by the same session in the same daemon lifetime, exactly as it already does for a reopened Complete plan; a different session or a daemon restart re-emits the goal.
