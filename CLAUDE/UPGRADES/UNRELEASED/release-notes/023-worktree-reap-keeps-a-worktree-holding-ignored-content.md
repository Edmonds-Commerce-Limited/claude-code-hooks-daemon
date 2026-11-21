# Callout: `worktree-reap` keeps a worktree whose removal would lose ignored content

**Plan**: 00627
**Audience**: everyone

`hooks-daemon worktree-reap --reap` (and the housekeeping step `worktree-reap-reap`) used to judge a worktree from `git status`, which lists no ignored file, and then removed it with a plain `git worktree remove`, which deletes ignored files. A worktree holding scratch notes under `untracked/scratch/`, or any other ignored path outside `branches.cleanup_after_merge.regenerable`, lost them. It now runs the same check `branch-sweep --clean` and the worktree-removal guards use: such a worktree is reported `KEEP <name>: the worktree <path> holds N path(s) a removal would lose: ...`, in the dry run too, and nothing is removed. A git failure reading the worktree also keeps it. Expect some reaps that used to succeed to be kept: file or delete the listed paths, then reap again.
