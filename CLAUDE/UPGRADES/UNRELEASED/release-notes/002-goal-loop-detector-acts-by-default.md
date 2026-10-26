# Callout: the goal-loop detector now acts by default, agents clear their own stuck goal, and a Blocked plan leaves the goal

**Plan**: 00501
**Audience**: operators

**Behaviour change: `goal_loop_detector` now defaults to `mode: act` (it was `observe`).** When a session keeps stopping on a goal the evaluator keeps rejecting, the detector now enters the `goal-blocked` session mode for `blocked_hours` and clears the goal (the ccy supervisor types `/goal clear` at its next idle), instead of only logging `would-enter`. The owner accepted a 64-hour, 1446-evaluation main-session loop as the trigger. To keep the old logging-only behaviour set `mode: observe` under `handlers.stop.goal_loop_detector.options`. Thresholds are unchanged. Without the ccy supervisor nothing types the clear, so a human must type `/goal clear`.

An agent may now run `bin/hooks-daemon clear-goal` itself when its goal cannot be satisfied: the first `loop-persisting` line and act mode's entry notice tell it to run that command, journal why, and stop with the real blocker stated. `clear-goal` retracts only that session's own goal; it ends no session mode and touches no plan.

A plan that moves to `Blocked` now drops out of the session's combined goal the way a retired plan does, and a goal whose plans are all Complete or Blocked is cleared. This is for the goal only: nothing is archived and the plan-QA terminal-status rules are unchanged.
