# Callout: branch-park can park with no commit and no push, and a standing park hands the branch over at stop

**Plan**: 00594
**Audience**: client projects

`branch-park` always added an empty trailer commit at the branch tip, which invalidated any QA already run on that tip, and always pushed, which a sub-agent told not to push cannot do. Two new switches change that per call: `--no-commit` records the park in git config only, leaving the tip untouched and pushing nothing, and `--no-push` writes the commit but does not push. `branches.park.commit` and `branches.park.push` set the same choice for every call. Both default to `true`, so nothing changes unless you set them.

The inventory and the pools read the park record rather than the trailer commit, so a no-commit park counts as parked and ages from the record. A no-commit park is local to the clone that made it: other checkouts cannot see it and read the branch as open work.

The branch stop guards (`R-BRANCH-STOP-GUARD`, `R-BRANCH-SUBAGENT-STOP-GUARD`) also stopped reporting the unpushed tip of a branch the stopping agent had parked with a reason. A park that is still recorded and uncleared counts as a handover; a commit after the park ends it and the checks resume.
