## 16:51 · thought · — — owner: allow agents to delete remote branches when provably safe (follow-up, after release)

Owner asked (typed, in session; not to block the release): agents should be allowed to remove remote branches when provably safe, e.g. the worktree-476-ci-gate-trial branch the owner had to delete by hand.

Current state: R-GIT-PUSH-DELETE-REMOTE already lets an agent delete a remote branch merged into the default branch; `delete-branch` proves the remote tip and pushes with a lease on it. An unmerged, not patch-equivalent branch is refused with no agent route; that is why the owner had to run the delete.

Proposed follow-up (after the current release, nothing built yet): a machine-proven tier for an unmerged branch that holds nothing unique: (a) the tip is already contained in a surviving ref, or (b) every file the branch changes already has the same final content on a surviving ref. The existing guard stays first; the deleting agent's own assertion never counts. A branch whose value is gone for a reason git cannot see (superseded design, reports kept elsewhere) still needs a human, by design.
