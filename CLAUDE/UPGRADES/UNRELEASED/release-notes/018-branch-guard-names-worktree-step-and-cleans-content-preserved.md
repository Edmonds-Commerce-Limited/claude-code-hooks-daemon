# Callout: Branch cleanup can finish a branch whose work reached the default another way

**Plan**: 00594
**Audience**: client projects

`delete-branch` still refuses a branch checked out in a linked worktree, because git refuses it too. When the branch's work is already safe, the refusal now says so. It names the proof, for example `proven content-preserved`, and the exact next step: `git worktree remove <path>`, then rerun `delete-branch`. A branch whose content the default branch lacks gets the plain refusal, with no removal step.

`branch-sweep --clean` now also offers a branch whose whole net change the remote-tracking default already holds, even when the branch carries merges from the default. This happens when the same bytes reached the default through another branch, or through a squash merge. Before this change, such a branch stayed `live` for ever. The sweep re-proves each one with `delete-branch`'s content tier, and the remote half re-proves it with the remote-delete proof, before deleting anything. Hooks are unchanged: the WIP and dormancy guards still count such a branch as open work, and cleanup after a merge still deletes only branches whose commits are all in the target.

`branch-sweep --clean --remote` also deletes ANOTHER author's remote branch when it is content-preserved, as it already did for another author's merged branch. Each one is still judged by the live remote-delete proof, and the push carries a lease on the proven tip, so a branch whose remote tip moved after the sweep planned is not deleted.

A parked branch that is only content-preserved (never merged) is not cleaned: the sweep skips it and prints the park reason with the `branch-park <name> --clear` command that releases it. A merged parked branch is cleaned as before, and its cleared park is reported.

`--clean` re-reads the worktree list just before it removes a worktree. If that worktree has been switched to another branch since the sweep planned, the sweep skips the branch and says what the worktree now holds.

The remediation commands that `delete-branch`, `branch-sweep --clean`, cleanup after a merge and the branch stop guard print now shell-quote every path and branch name. A worktree path containing a space, or a branch name containing an apostrophe, pastes into a shell as one argument.

No configuration changes.
