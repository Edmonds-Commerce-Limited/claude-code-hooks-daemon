# Callout: a keep fetched by the sweep lifts the creation guard's block, and the release retires its RC branch

**Plan**: 00641
**Audience**: operators

`branch-sweep --clean --remote` fetches the keep notes before it judges, so a keep written in another clone counted there. `branch-preflight` and the creation guard instead read a stale-mark snapshot written at session start, and only a local `branch-keep` cleared a mark. A merged release-candidate branch kept from another clone was therefore reported kept by the sweep and still refused every new branch (R-BRANCH-MERGED-POOL). The sweep now clears the snapshot's stale mark for every branch it sees as kept, so the two commands agree. The correction is made even on a dry run, because the snapshot is a derived cache.

The release procedure also gains a numbered post-release step, Step 15.2 in `CLAUDE/development/RELEASING.md`: delete the released `rc/X.Y.Z` branch (the command prints the restore line), or keep it with a reason that names the date or event that ends the keep. Before this the rule existed only as a sentence under "Ending an RC", so released RC branches stayed on the remote.
