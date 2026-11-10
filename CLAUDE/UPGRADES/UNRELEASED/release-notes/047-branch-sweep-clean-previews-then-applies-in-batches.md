# Callout: branch-sweep --clean now previews; --apply deletes, in resumable batches

**Plan**: 00594
**Audience**: client projects

`hooks-daemon branch-sweep --clean` used to delete at once. It is now the dry run: it prints the whole plan, each local and remote branch with its proof (`would delete <name> (proven merged)`, `would delete remote <remote>/<name> (tip <sha>, proven merged into <default>)`), deletes nothing, and ends with the exact command that applies it. Add `--apply` to delete (`--clean --remote --apply` for remote copies too). `--apply` cannot be combined with `--dry-run`. Every command the daemon prints for a one-step cleanup already names `--apply`; a script of your own that ran `branch-sweep --clean` must add it.

`--apply` works in batches of 50 (`BULK_BATCH_SIZE`): one recovery bundle per batch, written before that batch's local deletions, and one `git push --delete` per batch for the remote copies, each under a lease on its proven tip. Remote deletes use the same proof as the remote-delete guard, unchanged. A run that is interrupted (Ctrl+C), a batch that fails, or a push the remote refuses stops cleanly: the report lists what was deleted, what remains, and `Resume with: <command>`. Resuming is running the same command again, because the repository is the only state: a deleted branch is no longer a candidate, and a branch gone since the plan was made is skipped as `already deleted`, not an error.

`--clean` no longer runs on the hook-sized inventory time budget (`branches.sweep.budget_ms`, 3 seconds by default). On a repository with hundreds of branches that budget could run out before the keep notes were read, so a branch kept with `branch-keep` looked deletable. The sweep now allows itself ten minutes.
