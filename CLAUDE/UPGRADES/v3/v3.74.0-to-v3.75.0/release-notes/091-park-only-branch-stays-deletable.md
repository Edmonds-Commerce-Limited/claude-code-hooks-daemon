# Callout: a branch left with only empty park commits over merged work stays deletable, locally too

**Plan**: 00617
**Audience**: client projects

Parking a branch adds an empty park commit to it. Once the branch's work is merged, those park commits are the only thing the branch has that the default branch lacks. Up to v3.74.0 nothing recognised this: `branch-sweep --clean --remote` and `R-GIT-PUSH-DELETE-REMOTE` refused the branch as unmerged, it stayed in the merged pool, and once that pool was full `R-BRANCH-MERGED-POOL` refused every new branch. Only a human could delete such a branch. The `park-carried` status from Plan 00594 (release note 083) fixed the remote copy of a parked branch. This release covers the shapes that still got stuck:

- **Park then unpark.** The tip is the unpark commit. The inventory called the branch `park-carried`, but the remote-delete proof and the creation guard looked only for a `Parked-Reason` trailer on the tip. So the remote delete was refused and the creation guard counted the branch as open work. Both now also recognise the `Unparked` trailer.
- **The local copy.** `branch-sweep --clean` now deletes the local copy of a `park-carried` branch too. The delete-branch guard proves it at a new `park-carried` tier (a forced delete, because git's own merged check counts the park commit). The restore line is printed as for any other delete.
- **Squash-merged, then parked.** The delete-branch guard counted the empty park commit as a patch missing from the default, so it refused the branch while the sweep called it merged. Park commits are now left out of the patch comparison. Every other commit still needs its patch in the default.

**The rule is now narrower and shared.** A commit counts as a park commit only when all three hold:

- Its message is exactly what `branch-park` writes.
- It has one parent.
- Its tree is identical to that parent's tree.

A branch counts as park-only when every commit the default lacks is such a commit. One function, `branch_park.is_park_residue`, answers for the sweep, the creation guard, the delete-branch guard and `R-GIT-PUSH-DELETE-REMOTE`, so they cannot disagree. A branch stays refused if any commit:

- changes a file, even under the park writer's exact message;
- is real work under park commits;
- is an empty commit with `Parked-*` trailers but wording `branch-park` never writes (accepted before this release);
- has no parent or two parents;
- has a parent outside the default branch.

Remote deletes still run under a lease on the proven tip, and each prints a `git push <remote> <sha>:refs/heads/<name>` restore line. There is no recovery bundle; release note 075 removed it.

Your parked branches need no action. `branch-park` has always written this exact message, so existing park commits qualify. A commit made by hand with park trailers does not, and such a branch is now refused where it used to be accepted. The branch inventory cache is rebuilt once after the upgrade.
