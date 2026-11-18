# Callout: branch-pool pressure lands at session start and stop; creation is only a backstop

**Plan**: 00594
**Audience**: client projects

Branch-pool pressure used to land almost entirely at creation, which is the worst moment: an urgent fix could not get a branch because of other work. It now lands where it can be acted on.

- **Session start** lists every full pool with its exact fix commands (the same report as `branch-preflight`), under a `BRANCH POOLS` heading.
- **Stop** (`branch_stop_guard`, `branch_subagent_stop_guard`) adds two checks for the stopping session's OWN touched open branches: `dormant past the block stage` and `open pool over cap`. Branches this session never touched are never judged, and the deny offers only finish (merge) or `branch-park <name> --reason ...`, never a rename or the deletion of someone else's branch. In `branches.stop_guard.mode: warn` they are context only; `wip.mode: off` and `dormancy.mode: off` switch the matching check off. A hard-context handoff and a sub-agent stop do not run them.
- **After a merge**, `cleanup_after_merge` names the single `branch-sweep --clean` command when the merged pool is full.
- **Creation** is a backstop. New option `branches.wip.creation_grace` (default `2`, `>= 0`): the open-work cap denies a creation only at `cap + creation_grace` open branches, and warns (with the full report) between `cap` and that. Set `creation_grace: 0` to keep the old deny at the cap. The dormant, parked and merged pools are unchanged and still deny at their own limits.

`branch-preflight` follows the same rule: it exits 0 below `cap + creation_grace` and lists the cap as a warning.
