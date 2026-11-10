# Callout: the worktree-removal deny says to delete ignored content in a separate command

**Plan**: 00594
**Audience**: client projects

When `git worktree remove` is denied because the worktree holds ignored content such as `untracked/scratch/`, the deny now says to delete those paths in a separate command first and then retry the removal. The command is judged before any of it runs, so a delete chained in front of the removal (`rm -rf <worktree>/untracked/scratch && git worktree remove <worktree>`) never counts and stays denied; when the command does chain such a delete, the deny says that the chained delete is not counted. Modified and untracked files get no delete advice.
