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
branch cannot be named by git, it falls back to `init.defaultBranch`, then the
branch of an unborn HEAD (the block is written, no root commit is made), then a
sole local branch. If none resolves, nothing is written and the SessionStart
notice tells the agent to set `branches.home`.

If a checkout lives on an environment, release or production branch for weeks,
declare it, because a configured list replaces the default:

```yaml
branches:
  home: [release-x]
```

`home` takes exact branch names; a glob such as `release/*` is rejected at load.

`regenerate-docs` still writes the block on request from any branch, but it
commits only on a home branch. Off home, the file is left modified for you to
commit deliberately. Linked worktrees are still left alone at startup.

For a home branch that only accepts pull requests, set `home_commit: false`.
The daemon then never writes CLAUDE.md on a home branch: a modified file there
would make the next `git pull` fail whenever an upstream change touches
CLAUDE.md. A stale block is reported once in the log and at SessionStart; run
`regenerate-docs` on a pull-request branch and commit the result there.
