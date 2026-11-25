## 12:38 · decision · — — Park follows the branch: ancestor rule, age-bounded

Decision (Task 1.2): a park follows the branch. `_handed_over_by_park` now covers a branch while the recorded park commit is an ANCESTOR of the current tip (`git merge-base --is-ancestor`), so later commits on top of the parked tip do not re-arm the three-block cycle.

Bounds kept: the park is ignored once older than `branches.parked.max_age_days` (effective_pool_max_age for the parked pool); a tip that does not descend from the recorded commit (rewritten or unrelated history) is judged again; an unreadable record or a failed/over-budget ancestry check is judged as unparked (fail closed). An unparked unpushed branch is still denied three times. No agent assertion clears anything: only a record written by branch-park counts.

Not done: the abandoned record and deny wording still say "abandoned" for a branch that only lacks a push (Task 2.2); `announce_ended_parks` still clears a park record at the next session start when the tip moved off the recorded commit (it should follow the same ancestor rule); Task 2.3 live verification.
