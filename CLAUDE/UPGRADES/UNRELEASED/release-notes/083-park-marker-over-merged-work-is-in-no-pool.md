# Callout: a park marker over work the default already holds is in no pool, and its delete is proven

**Plan**: 00594
**Audience**: operators

A branch whose only commits beyond the default are empty `Parked-*` park markers (the work under the marker is already in the default, for example carried by a merged release line) used to be judged three ways: the branch-creation guard counted it as parked, `branch-sweep` called it merged, and the remote-delete guard refused it as unmerged. A clone could read `Parked: 4 of 10` in the sweep while creation was refused at `Parked branches: 10 (cap 10)`, and the refs had no route out.

There is now one rule (`branch_park.is_park_residue`, every commit in `default..tip` is a park marker; release note 089 narrows "park marker" to the park writer's own commit) and one pool function (`pool_for_ref`) used by the sweep, the creation guard and the remote-delete proof. Such a ref has the status `park-carried`: it counts in no pool, so it blocks no creation; `branch-sweep` lists it under "Park-carried" with its park reason and, when the remote-delete proof accepts it, the runnable `git push <remote> --delete <name>` line; `branch-sweep --clean --remote` deletes it under a lease on its tip. The proof tier is `park-carried`; a park over work the default does NOT hold stays parked and its remote delete stays refused, and an empty change that is not a park marker is still unproven. A ref with a local copy is reported the same way, and `--clean` deletes the local copy too (release note 089).

The merged-pool deny text now says an unkept merged branch is stale from day 0 whatever its age (its age is the tip commit date); only a keep is aged against `branches.merged.max_age_days`.
