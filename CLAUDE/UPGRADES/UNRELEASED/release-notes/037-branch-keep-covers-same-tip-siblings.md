# Callout: a branch keep lifts the merged-pool block for every branch at that tip

**Plan**: 00594
**Audience**: client projects

`branch-keep` records the keep as a note on the branch's tip commit, so every
branch name at that tip is kept, and `branch-sweep` reports them all kept. The
creation guard (`R-BRANCH-MERGED-POOL`) reads a per-name snapshot, though, and
`branch-keep` cleared the stale mark only for the name it was given. A
same-tip sibling, for example a `-parked` twin, stayed stale to the guard and
went on denying branch creation. Re-keeping the sibling with the same reason
was refused before the mark was cleared. Now a keep clears the stale mark of
every name at the kept tips, and so does a re-keep refused for repeating its
reason.

Workaround on earlier versions: re-keep the sibling with a new reason.
