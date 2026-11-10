# Callout: a failed worktree creation no longer leaves a locked worktree and branch behind

**Plan**: 00592
**Audience**: client projects

(GitHub #173.) A `git worktree add` that was killed (for example by its timeout) leaves the worktree locked with the reason `initializing`, so the handler's cleanup could neither remove the worktree nor delete its branch. The cleanup now releases a lock whose reason is exactly `initializing`, then removes the worktree and the branch it created as before. A worktree locked for any other reason is never touched. Whatever the cleanup still cannot remove is named (path and branch) in the error the handler raises.
