# Callout: destructive_git no longer denies git text printed by a single-quoted awk program

**Plan**: 00478
**Audience**: client projects

(GitHub #170.) `printf 'x\n' | awk '{print "git worktree remove " $1}'` was denied under R-GIT-WORKTREE-REMOVE-FORCE ("This delete could not be verified as safe: no forced branch delete or worktree removal could be read") although it runs no git. The `$1` made `destructive_git` keep the awk program as command text, its raw-text patterns matched `git worktree remove`, the parser read no removal, and the fail-closed unreadable branch denied. A single-quoted awk program is now data for awk, `$` included, so `print`/`printf` of `git worktree remove ...` or `git branch -D ...` (with `-F`, `BEGIN` blocks and so on) is allowed. Anything that may run the text is judged as before: a pipe into `sh`/`bash`/`xargs`, `eval "$(...)"`, `source <(...)`, `bash -c "$(...)"`, an awk `system(...)`, an awk `| "sh"` or `> "file"` redirect (a script a later command can run), and a real `git worktree remove` beside the print. The unreadable-command verdict itself is unchanged.
