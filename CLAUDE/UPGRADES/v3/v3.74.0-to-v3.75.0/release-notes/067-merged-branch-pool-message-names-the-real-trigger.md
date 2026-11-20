# Callout: the merged-branch pool message says a branch is unkept, not that it is old

**Plan**: 00474
**Audience**: client projects

A merged branch that was neither deleted nor kept was reported as stale "past" the age limit even when it was days old. The branch-creation block and the sweep report now say "neither deleted nor kept" for that case, and mention the age limit only for a keep that has lapsed.
