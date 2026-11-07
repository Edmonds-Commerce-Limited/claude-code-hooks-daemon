# Callout: branch containment sees what the remote holds outside refs/heads

**Plan**: 00570
**Audience**: operators

A remote can keep a finished branch under a namespace the clone never fetches, such as `refs/archive/<name>`. The sweep used to report that branch CONTAINED NOWHERE ("no remote ref holds its commits"), advise a `git push -u` that re-creates it on the remote, and `delete-branch` refused it as content found nowhere. The explicit commands `branch-sweep` and `delete-branch` now make one bounded `git ls-remote` (only when a branch would otherwise be unproven) and accept a remote ref at, or descending from, the branch tip as proof the remote holds it. They name the ref they relied on (`delete-branch` calls the new tier `remote-held`), and the sweep no longer advises pushing such a branch. A failed or timed-out listing falls back to the offline answer and says the remote could not be checked; it is never proof. The session-start summary and the branch creation guard stay network-free, and their text now says what was checked: no fetched remote-tracking ref of the remote holds the commits, with a pointer to `branch-sweep` for the remote check (reported as issue #166).
