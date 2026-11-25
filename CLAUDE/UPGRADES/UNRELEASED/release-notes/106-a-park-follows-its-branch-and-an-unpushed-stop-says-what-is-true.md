# Callout: A branch park follows later commits, and an unpushed stop no longer says "abandoned"

**Plan**: 00640
**Audience**: operators

A branch parked with `branch-park <name> --reason ...` stays handed over to the branch stop guard while further commits land on top of the parked commit, so a branch that cannot be pushed (for example a 403 for the account the container holds) no longer restarts the three-block cycle on every commit. The park ends when the tip no longer descends from the parked commit, when it outlives `branches.parked.max_age_days`, or when a human clears it, and the SessionStart "Park cleared" line follows the same rule. A stop let through on a branch whose only problem is that no remote holds its commits is now recorded as left unpushed, saying the work is intact locally and a push or a park with a reason is what is missing, instead of calling it abandoned.
