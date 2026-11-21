## 21:03 · action · — — Task 4.2 on main: pressure moves to stop and session start

Task 4.2 is on main: branch-pool pressure moves off creation and onto session start, stop and merge, as DESIGN 2.3 set out. Creation now denies only at the open-branch cap plus `branches.wip.creation_grace` (default 2), so an urgent fix can always get a branch; between the cap and that point the report still lists it as a warning. The stop guard gained dormant and over-cap checks that look only at the stopping session's own touched branches. Session start renders every full pool with the same report `branch-preflight` prints, and the merge advisory names the exact clear command.

The agent saw nine of the new tests fail before writing code. About thirty older tests that assert a deny exactly at the cap now set `creation_grace=0`, the documented way to keep the old behaviour; none was weakened.

Two things stay open. The "ignored stop report" grace variant from the design is not built; grace is a fixed option. And the stop checks count open-pool records without same-tip dedup, so a stack of same-tip branches counts once per link, which is Task 4.6's question.

Retrospective QA over everything since v3.74.0 found one real defect, a bandit B404 on a `subprocess` import in `branch_cleanup.py` (fixed, main QA green on the fix), plus a stale-daemon failure in the acceptance playbook harness that a daemon restart clears.
