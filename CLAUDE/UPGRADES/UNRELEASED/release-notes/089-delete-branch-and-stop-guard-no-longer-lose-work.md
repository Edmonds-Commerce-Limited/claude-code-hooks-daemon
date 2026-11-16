# Callout: delete-branch and the stop guard no longer let unpushed work go unjudged

**Plan**: 00618
**Audience**: client projects

`delete-branch` could delete a branch that held the only copy of its work. Its `content-preserved` proof accepted any branch whose file contents all existed somewhere in the default branch's history, so a branch that deleted a file, or set a file back to an older version, passed and was deleted even though it was never pushed. The tier now also needs the same per-path proof every remote delete uses: a commit on the default branch holds the branch's whole net change. A squash-merged branch still qualifies. A branch that copies existing content to a new path, changes only a file mode, or whose proof git cannot finish is now refused as `unproven`.

The coordinator's Stop guard handed over, without judging it, any branch checked out in a worktree under `.claude/worktrees/`, including a branch the main thread had worked on itself. A branch the stopping thread touched itself is now handed over only when a running work-queue record names it or git has its worktree locked, the same holds `worktree-reap` honours; a worktree that merely sits under `.claude/worktrees/` no longer hands such a branch over, so its dirty or unpushed work is judged. "Touched" means the main thread wrote into that worktree with `Write`/`Edit` or ran a branch-moving `git -C <worktree>` command there; to keep handing such a branch over while its agent runs, lock the worktree (`git worktree lock`) or give the agent a work-queue record. Branches the stopping thread did not touch are handed over exactly as before, including a background sub-agent's unlocked `.claude/worktrees/` worktree, so a coordinator waiting on sub-agents does not spend its stop-guard blocks on their branches.

`hooks-daemon session-state --watch --interval` now refuses zero, negative and non-finite values.
