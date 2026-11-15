## 23:46 · finding · — — Peer report: branch pools, stale age and delete proof disagree on one set of refs

Peer report (lts-infra.1, no authority; branch-sweep read after git fetch --prune in the lts-infra checkout): the branch pools disagree on one set of refs.

Reported summary lines: Open work 4 of 10 (branches.wip.cap); Parked 4 of 10 (branches.parked.cap); Merged, not deleted 10 of 10 (branches.merged.cap). The creation guard refused a new branch at "10 of 10" and the report named R-BRANCH-PARKED-POOL (second-hand, verbatim text not yet received).

Reading, to test first: the only pool at 10 of 10 in the sweep is the MERGED pool, so the refusal quoted as a parked-pool deny may be the merged-pool deny (R-BRANCH-MERGED-POOL) or the parked rule reporting the wrong pool or count. The verbatim deny text decides it. If the parked rule really counts 10, the guard and the sweep count different sets (remote-only park refs are the suspect).

Further anomalies in the same output:

1. Seven merged entries read "0d old, STALE (unkept, past branches.merged.max_age_days 30)": an age of zero days flagged past a 30-day limit. Suspect the age is computed from a missing or zero timestamp (an empty park commit, or a ref with no commit date) and the staleness test reads "unkept" as "stale".
2. The sweep calls these branches "merged into main (proven by origin/main)", while the destructive-git guard refuses their remote delete as unmerged because the tip is an empty park commit. The sweep's proof and the guard's proof use different rules for a branch whose only unique commit is an empty park commit.

Unit (own plan task, test-first, after Plan 00608): reproduce each in tests against a fixture repo with remote-only park refs, one parked branch, and merged branches whose tip is an empty park commit; define one status for a remote-only park ref; make the sweep, the creation guard and the delete guard share one classification (the surviving-content tier on the unmerged remote-delete branch is related: an empty park commit carries no content). Needed from lts-infra: the verbatim deny text and the full parked list.
