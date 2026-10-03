# Callout: session start names open work branches beyond the limit, or far behind main

**Plan**: 00475
**Audience**: operators

A new advisory handler, `branch_count_advisor`, runs at the start of each new session and counts the local `worktree-*` branches, the work branches `CLAUDE/Worktree.md` limits to 3 at once (a branch whose worktree is gone still counts until it is deleted). When there are more than `max_open_branches` (default 3) it names every one of them; it also names any work branch more than `behind_main_threshold` commits (default 50) behind the default branch. It is advisory only: it never blocks, and it is silent when within both limits, outside a git repository, or when git fails. It makes at most one git call per work branch, each under the daemon's git timeout. Whether the limit should ever block is left to the project owner; no blocking mode exists.
