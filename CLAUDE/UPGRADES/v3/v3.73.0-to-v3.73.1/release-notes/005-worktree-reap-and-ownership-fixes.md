# Callout: worktree-reap deletes merged branches safely, and running-agent holds match however the path is written

**Plan**: 00571
**Audience**: client projects

Two defects in v3.73.0's branch cleanup, both found in that release's own review and shipped as accepted known defects.

`worktree-reap --reap-branches` deleted a merged branch with a plain `git branch -d`, which refuses a branch merged into the default branch but never pushed to its own upstream, so that branch was skipped without explanation and the command still exited zero. It now deletes through the same path as `delete-branch`: the branch's containment is proven, its tip goes into a recovery bundle under `untracked/deleted-branches/`, and a branch it keeps is reported `KEPT` with the reason and makes the command exit non-zero.

The running-agent protection added in v3.73.0 (`branch-sweep --clean` and `worktree-reap` skip a worktree a `running` work-queue record names) compared worktree paths as written. A record holding a relative path, a trailing separator or a symlinked route to the same directory did not match, so that worktree could be cleaned while its agent was running. Paths are now compared after resolving them against the project root.
