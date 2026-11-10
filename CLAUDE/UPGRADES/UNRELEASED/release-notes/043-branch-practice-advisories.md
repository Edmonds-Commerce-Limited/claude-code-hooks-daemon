# Callout: branch_creation_guard advises on recovery-copy branch names and nested worktrees

**Plan**: 00594
**Audience**: client projects

`branch_creation_guard` now adds an advisory, never a deny, in two cases. A branch created with a recovery-copy name (`rescue/*`, `recovery/*`, `backup/*`, `*-rescue`, `*-backup`) is told to keep the copy as `refs/archive/<name>` or a `git bundle` instead, because the branch pools count only branches and a recovery copy kept as a branch counts as open work. A `git worktree add` whose target is inside another linked worktree is told that worktrees are created from the main checkout, never nested, and is given the main checkout's path. The patterns are a fixed list, not configurable. The three habits (archive instead of branching, create from the main checkout, remove an agent's worktree after the agent) are written once under "Branch Practice" in `CLAUDE/core/Worktree.core.md`, which refreshes on upgrade.
