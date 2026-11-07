# Callout: recovery bundles accumulate, and one command clears merged branches locally and remotely

**Plan**: 00571
**Audience**: client projects

`delete-branch` used to write every call into the same `untracked/deleted-branches.bundle`, so only the last deleted branch could be restored. Each call now writes its own bundle under `untracked/deleted-branches/`, named by UTC time plus a random suffix, and prints one exact `git fetch <bundle> refs/heads/<name>:refs/heads/<name>` restore line per deleted branch. `branch-sweep --clean` uses the same naming. An explicit `--bundle PATH` that already exists is refused rather than overwritten. An existing `untracked/deleted-branches.bundle` is left in place; it still holds the last branch deleted before the upgrade.

`branch-sweep --clean --remote` is new. It also deletes merged branches on `branches.remote`, using the proof the remote-delete guard already applies to an agent's `git push --delete` (the tip is an ancestor of the default branch or an integration line, and `ls-remote` confirms the live tip). Each delete carries a lease on that tip, and the remote tips go into the same recovery bundle. Every report that lists a merged branch (the sweep, the WIP-cap deny, the stop guard) now names `branch-sweep --clean` as the one-step fix, and `worktree-reap --reap-branches` prints each merged branch it skipped because it is not agent-owned (reported as issue #165).

`branch-sweep --clean` (with or without `--remote`) leaves running agents' worktrees alone. A worktree and its branch are skipped, with a `Skipped <name>: ...` reason, when a `running` work-queue record names them, when the worktree lives under `.claude/worktrees/` (Claude Code's own agent worktrees), or when git reports it `locked`. A freshly spawned agent's branch sits at the default branch's tip, so it used to look merged and removable. `worktree-reap` also keeps work-queue-running and locked worktrees.
