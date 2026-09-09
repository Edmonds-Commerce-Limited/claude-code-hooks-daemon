# Callout: a daemon restart in a git worktree no longer regenerates and commits `CLAUDE.md`

**Plan**: 00364
**Audience**: everyone

Every daemon restart rewrites the `<hooksdaemon>` block in `CLAUDE.md` and
auto-commits it, so an agent never sees a dirty file it might try to revert.
In a linked worktree that commit landed on the worktree's branch, while the
main checkout's own restarts landed theirs on main, and the two generated
blocks conflicted on every merge back. Three agents in one session hit it.

The startup injection now skips a linked worktree and logs why. The branch
carries only the work done there, and the block is regenerated on main, for
the merged code, on the first restart after the merge. The explicit
`bin/hooks-daemon regenerate-docs` still writes the block in a worktree when
asked, since that is the documented way to recover a conflict-marked one.

The status line's worktree detection and the injector now share one probe,
`is_linked_worktree` in `utils/git_repo.py`.
