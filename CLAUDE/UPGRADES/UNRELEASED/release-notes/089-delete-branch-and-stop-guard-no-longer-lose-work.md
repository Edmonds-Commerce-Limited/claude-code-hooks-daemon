# Callout: delete-branch and the stop guard no longer let unpushed work go unjudged

**Plan**: 00618
**Audience**: client projects

`delete-branch` could delete a branch that held the only copy of its work. Its `content-preserved` proof accepted any branch whose file contents all existed somewhere in the default branch's history, so a branch that deleted a file, or set a file back to an older version, passed and was deleted even though it was never pushed. The tier now also needs the same per-path proof every remote delete uses: a commit on the default branch holds the branch's whole net change. A squash-merged branch still qualifies. A branch that copies existing content to a new path, changes only a file mode, or whose proof git cannot finish is now refused as `unproven`.

The coordinator's Stop guard handed over, without judging it, any branch checked out in a worktree under `.claude/worktrees/` or a locked worktree, including branches the main thread had worked on itself. It now judges every branch the stopping thread touched, whatever owns its worktree. Another agent's branch is still handed over when a running work-queue record names it or its worktree is locked by git, the same holds `worktree-reap` honours. A worktree that merely sits under `.claude/worktrees/` no longer hands its branch over. A background sub-agent's branch that should not hold the coordinator's stop needs a work-queue record or a locked worktree.

`hooks-daemon session-state --watch --interval` now refuses zero, negative and non-finite values.
