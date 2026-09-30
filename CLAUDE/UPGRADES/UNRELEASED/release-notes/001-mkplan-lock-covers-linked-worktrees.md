# Callout: plan-number lock now covers every linked worktree

**Plan**: 00474
**Audience**: client projects

`mkplan.bash` now takes its lock in the repository's common git directory, so it is shared by every linked worktree (`git worktree add`) of a repository, just like the plan counter it guards. Previously each checkout had its own lock over the shared counter, and two runners in two worktrees could allocate the same plan number (reported as issue #59). `mkplan.bash` is daemon-owned and is redeployed over your copy on every upgrade, so the fix arrives with the upgrade and needs no action; if the common git directory cannot be resolved (for example on git older than 2.31), the script falls back to the old per-checkout lock.
