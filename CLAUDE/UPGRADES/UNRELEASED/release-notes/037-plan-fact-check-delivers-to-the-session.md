# Callout: the opt-in plan fact-check now reaches the session as work

**Plan**: 00480
**Audience**: handler authors

The `plan_fact_check_feed` PostToolUse handler (still `default_enabled = False`, still never blocking) used to stop at storing a pending fact-check when a burst of plan edits went quiet. It now delivers it: the next PostToolUse event, whatever the tool, carries an instruction to dispatch the `plan-fact-checker` agent on that plan with the diff since the last checked content (written to `<daemon untracked dir>/plan-fact-check/<folder>.diff`), and to treat every REFUTED claim as work to fix, naming the claim, the evidence and the file. Each pending record is delivered once, and delivery is what marks the plan content as checked.

The daemon still runs no model, and the ccy supervisor channel is not used: its signal carries only a count and points at `hooks-daemon session-actions`, which lists SessionStart items only. A refutation does not block `plan_qa_commit_gate`.

Pending records now store the plan root and content snapshot. A record written by an earlier build is reported as unreadable (logged, never blocking); delete it from the `plan-fact-check/` directory to reset that plan.
