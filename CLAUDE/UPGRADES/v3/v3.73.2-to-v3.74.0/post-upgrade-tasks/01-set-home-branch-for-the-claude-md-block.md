# Task: Declare the home branch if the main checkout is not on the default branch

**Type**: config-migration
**Severity**: recommended
**Applies to**: all
**Idempotent**: yes

## Why

The daemon now writes the `<hooksdaemon>` block into CLAUDE.md, and commits it, only while HEAD is attached to a home branch, which by default is the repository's default branch. A project whose main checkout lives on another branch (an environment, release or production branch), or whose default branch only accepts pull requests, silently stops receiving block updates until `branches.home` and `branches.home_commit` say so.

## How to detect if this applies to you

Compare the main checkout's branch with the default branch, and check whether the default branch is protected. Sample:

```bash
git branch --show-current
git symbolic-ref --short refs/remotes/origin/HEAD
gh api repos/{owner}/{repo}/branches/$(git symbolic-ref --short refs/remotes/origin/HEAD | cut -d/ -f2) --jq .protected
```

This applies when the two branch names differ, or when the default branch is protected and requires pull requests. Neither: this task does not apply. A repository with no remote and no `main`/`master` branch also applies: if git cannot name a default branch, the SessionStart notice already says so.

## How to handle

- Main checkout on a non-default branch: set `branches.home` in `.claude/hooks-daemon.yaml` to the exact names (globs are rejected) of the branches it lives on, then restart the daemon.
- Default branch accepts only pull requests: set `branches.home_commit: false`. The daemon then never writes CLAUDE.md on a home branch, so a pull is never blocked by a modified file; it reports a stale block at SessionStart. Run `regenerate-docs` in a pull-request worktree or branch and commit the result there; it refuses on a home branch.
- Not sure which applies: ask the user.

## How to confirm

Restart the daemon. With `home_commit: true` the block is current on the home branch. With `home_commit: false` the SessionStart notice appears only while the block is stale, and `git status` shows CLAUDE.md clean on the home branch.
