# Callout: removing a worktree whose detached HEAD is held by patch is no longer refused

**Plan**: 00474
**Audience**: everyone

`git worktree remove` of a clean worktree was refused ("HEAD would lose N commits") when its detached HEAD was not reachable from any surviving ref, even if a surviving branch, tag or remote-tracking ref already carried the same patch (a cherry-pick or rebase, `git cherry` showing `-`). Such a HEAD is now treated as held, on the same patch-equivalence the branch proof uses, plus the requirement that the holder's history holds the HEAD's net change. A HEAD with a commit no surviving ref holds by patch, a dirty worktree, and unregenerable ignored content are still refused. The deny text also no longer offers `switch -c <name>`, which the branch WIP cap refuses; it names `git -C <worktree> tag <name>` instead, because a tag is a surviving ref and is not a branch.
