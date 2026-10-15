# Callout: the sub-agent worktree guard forgets a worktree that has been removed

**Plan**: 00528
**Audience**: client projects

`subagent_worktree_write_guard` binds each sub-agent to the linked worktree of its first `Write`/`Edit`/`NotebookEdit`. A sub-agent working in the main checkout that made a scratch probe worktree, wrote a test file in it and removed it again stayed bound to the deleted probe, so its report write into the main checkout was denied with R-SUBAGENT-CROSS-WORKTREE-WRITE. A binding whose worktree is no longer on disk is now dropped and the write is judged as if unbound. A probe that still exists keeps the binding, so sub-agents should not `Write`/`Edit` inside a worktree they made themselves; the resident guidance now says so.
