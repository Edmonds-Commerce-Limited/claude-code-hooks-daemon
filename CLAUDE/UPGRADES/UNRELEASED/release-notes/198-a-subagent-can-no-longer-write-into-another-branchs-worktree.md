# Callout: a subagent can no longer write into another branch's worktree

**Plan**: 00474
**Audience**: operators

A new `subagent_worktree_write_guard` handler (rule `R-SUBAGENT-CROSS-WORKTREE-WRITE`, on by default) denies a subagent's `Write`, `Edit` or `NotebookEdit` whose target is in a different checkout of the repository than the linked git worktree the subagent works in: a sibling worktree, or the main working tree. Such edits used to land uncommitted in a branch nobody on the task owned, to be committed later under that branch's name. The deny names both worktrees and tells the subagent to report cross-branch needs to the coordinator. The coordinator, a subagent working in the main working tree, writes outside the repository and writes in another repository are not judged. Disable with `handlers.pre_tool_use.subagent_worktree_write_guard.enabled: false`.
