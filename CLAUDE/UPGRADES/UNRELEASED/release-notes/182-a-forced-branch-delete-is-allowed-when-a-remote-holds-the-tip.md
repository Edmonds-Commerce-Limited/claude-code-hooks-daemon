# Callout: a forced branch delete is allowed when a remote already holds the tip

**Plan**: 00474
**Audience**: operators

`destructive_git` used to deny every `git branch -D`, so an agent could not clear up its own stale worktree branches without a human. It now allows `git branch -D <names>` (also `-d --force`, `--delete --force` and `git update-ref -d refs/heads/<name>`) when every named branch's tip is reachable from a remote-tracking ref, judged in the repository the command runs in (`git -C` and a same-command `cd` are honoured). Otherwise it still denies, names each branch that is not on a remote and says to `git push -u origin <name>` first. Any failure while checking (git missing, a timeout, an unknown branch or directory, an unreadable command) denies. The two-option spellings `-d --force` and `--delete --force` were previously not blocked at all and are now judged the same way. Anything that leaves a branch on no remote still needs the owner.
