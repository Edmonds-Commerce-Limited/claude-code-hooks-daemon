# Callout: `worktree-reap` no longer risks reaping a worktree that just started, and its branch delete now actually works

**Plan**: 00372
**Audience**: operators

`bin/hooks-daemon worktree-reap` had two live defects. First, a worktree
created moments earlier for an actively-working agent looked identical to a
finished, stale one — no uncommitted paths, no commits ahead, no unlanded
patches — and was listed as safe to reap; it now also checks whether a live
process is running inside the worktree and how long ago it was created,
refusing anything with no history of its own that is either occupied or
under 15 minutes old. Second, the branch delete on the reap success path
never actually worked: it passed `git branch -d` a fully-qualified
`refs/heads/<name>` ref, which git rejects outright, so every reaped
worktree left its branch behind with a self-contradicting "git kept the
branch ... not found" message. Both are fixed; a completed reap now deletes
the branch as it always claimed to.
