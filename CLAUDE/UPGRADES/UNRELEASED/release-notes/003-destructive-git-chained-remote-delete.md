# Callout: a merged branch's remote delete is no longer denied when chained after its worktree removal

**Plan**: 00474 (N578)
**Audience**: client projects

`git worktree remove <wt> && ... && git push origin --delete <b>` was denied by the destructive_git guard (R-GIT-PUSH-DELETE-REMOTE) even when `origin/<b>` was merged into the default branch, because the worktree removal also matched a rule and the remote delete was then never judged on its own proof. The remote delete is now judged the same alone or chained after a worktree removal or local branch delete, and every denial of it names the branch and why it is not proven merged. Unmerged branches, tags, `--mirror` and `--prune` stay denied.
