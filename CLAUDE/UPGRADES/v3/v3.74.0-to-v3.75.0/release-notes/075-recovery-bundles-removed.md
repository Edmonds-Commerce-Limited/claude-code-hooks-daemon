# Callout: recovery bundles are gone; delete commands print a restore line instead

**Plan**: 00594
**Audience**: operators

`delete-branch`, `branch-sweep --clean --apply` and `worktree-reap --reap-branches` no longer write recovery bundles under `untracked/deleted-branches/` or `untracked/branch-cleanup/`. A delete is permitted by the machine proof alone, never by a copy. The `--bundle` and `--no-bundle` flags of `delete-branch` are removed, so a script that passes them must drop them. Each command now prints one `git branch <name> <sha>` restore line per deleted branch (remote deletes print `git push <remote> <sha>:refs/heads/<name>`), naming the tip the proof was made against. The JSON output of `delete-branch --format json` replaces its `bundle` key with a `restore` list. Bundles already on disk are untouched and can be deleted by hand.
