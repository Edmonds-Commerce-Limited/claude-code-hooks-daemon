## 14:02 · finding · —

Verdict reuse hole: confirmed real, and fixed on the branch (Task 2.4, builder's share).

What was open: single use is keyed on verdict_id, and nothing bound the id to anything.
A used verdict re-filed under a fresh verdict_id passed every check, and after the branch
was restored from its bundle the route deleted it a SECOND time. A git-refused verdict
re-filed the same way was also accepted. Both were proven red (6eb4a410c).

Fix, part one (f733a052f):

- \_shape_problems refuses a verdict whose id is not its nonce (the recorder always writes
  id = nonce);
- verdict_problems also treats a nonce in the consumed set as used;
- RejectStore.verdicts_for raises RejectError when a verdict file is not named by its id.

Then a wider replay was tested (red at 7ec987318): copy the request, dispatch and verdict
WHOLE under a fresh nonce, editing nothing else. That passes every id check, and it too
deleted the restored branch again.

Fix, part two (f586c0533): single use is also keyed on the reviewer agent. One agent
reviews one nonce, and every ledger line names its reviewer agents. verdict_problems takes
a required consumed_agents set, and record_removal re-checks it at append time.

Residue, inside RULINGS Q1 and accepted: a forger who also writes a NEW agent id into the
copied dispatch and verdict is not caught. That is the "writes all three files" forger
DESIGN section 3 already names.

verdicts_for has one caller (branch_safety.delete_branches), and it turns RejectError
into a refusal.

Result: 449 branch_reject tests pass; ruff, black and mypy are clean.
For the independent reviewer: these three commits change the verdict acceptance rules.
