# Phase 3 (Tasks 3.1-3.3): handed off at the context budget

Status: NOT implemented. No source, test or doc change was made, and Tasks 3.1 to 3.3 stay
unticked.

The agent read the plan, DESIGN.md and ROOTCAUSE.md, and every module Phase 3 touches:
config/models.py, core/branch_creation.py, branch_inventory.py, branch_sweep.py, branch_cleanup.py,
branch_park.py, the creation guard handler and the CLI's park/sweep commands. It crossed the
150k-token subagent context budget before writing code. It recorded the full implementation design
in [phase-3-pools-handoff.md](phase-3-pools-handoff.md), so a fresh agent can start at the failing
tests.

Four readings of DESIGN.md needed a decision. They are listed at the top of the handoff for the
owner or coordinator to confirm:

1. An unkept merged branch is stale from day 0, except while a worktree holds it.
2. Pool caps compare `>=`, as `wip.cap` does.
3. A stale kept merged branch is a `--clean` candidate.
4. Two new rule IDs, `R-BRANCH-PARKED-POOL` and `R-BRANCH-MERGED-POOL`.
