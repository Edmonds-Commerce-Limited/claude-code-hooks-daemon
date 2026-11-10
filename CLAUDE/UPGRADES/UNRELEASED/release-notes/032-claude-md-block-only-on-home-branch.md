# Callout: the CLAUDE.md block is written and committed only on a home branch

**Plan**: 00594
**Audience**: client projects

At daemon start the main checkout used to write the `<hooksdaemon>` block into
CLAUDE.md and auto-commit it onto whatever HEAD was: a feature branch, a
detached HEAD (leaving a dangling commit), or a branch made only to get a
worktree removed. That is how the daemon created stray branches and commits on
its own.

The block is now written and committed only while HEAD is attached to a home
branch. By default that is the repository's default branch. On any other
branch, or on a detached HEAD, the daemon writes nothing, commits nothing and
logs at info level why, naming `regenerate-docs`. If HEAD or the default
branch cannot be resolved it does nothing and says so.

If a checkout lives on an environment, release or production branch for weeks,
declare it, because a configured list replaces the default:

```yaml
branches:
  home: [release-x]
```

`regenerate-docs` still writes the block on request from any branch, but it
commits only on a home branch. Off home, the file is left modified for you to
commit deliberately. Linked worktrees are still left alone at startup.
