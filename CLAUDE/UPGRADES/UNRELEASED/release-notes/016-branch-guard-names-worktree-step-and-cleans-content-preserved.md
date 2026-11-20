# Branch cleanup can finish a branch whose work reached the default another way

**Audience**: client projects

`delete-branch` still refuses a branch checked out in a linked worktree, because git refuses it too. When the branch's work is already safe, the refusal now says so. It names the proof, for example `proven content-preserved`, and the exact next step: `git worktree remove <path>`, then rerun `delete-branch`. A branch whose content the default branch lacks gets the plain refusal, with no removal step.

`branch-sweep --clean` now also offers a branch whose whole net change the remote-tracking default already holds, even when the branch carries merges from the default. This happens when the same bytes reached the default through another branch, or through a squash merge. Before this change, such a branch stayed `live` for ever. The sweep re-proves each one with `delete-branch`'s content tier, and the remote half re-proves it with the remote-delete proof, before deleting anything. Hooks are unchanged: the WIP and dormancy guards still count such a branch as open work, and cleanup after a merge still deletes only branches whose commits are all in the target.

No configuration changes.
