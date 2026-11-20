# Callout: finished issues leave the workable cache, and setup_worktree.sh obeys the branch pools

**Plan**: 00606
**Audience**: operators

`work-queue done` no longer lists the issue it just finished as the next workable one: the issue number in the entry's branch or name is kept out of the workable-issues cache even while GitHub still shows the issue open, so the stop gate stops naming a finished issue. `branch_creation_guard` now treats `scripts/setup_worktree.sh <name>` as a branch creation (it runs `git worktree add` itself), so the branch pool caps apply to it exactly as they do to a direct `git worktree add`. The acceptance-test socket discovery also asks the daemon's own resolver, so a runner whose hostname pushes the socket to the `/tmp` fallback no longer errors every acceptance test.
